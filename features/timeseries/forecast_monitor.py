"""予測精度モニタリング — STREAM 3-B
予測 vs 実績の比較、累積 MAE 追跡、モデルドリフト検出。
"""
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import logging

logger = logging.getLogger(__name__)

# 出力先
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ACCURACY_JSONL = os.path.join(_PROJECT_ROOT, "data", "forecast_accuracy.jsonl")


class ForecastMonitor:
    """日次予測精度監視"""

    def __init__(self):
        self.db_path = os.path.join(_PROJECT_ROOT, "data", "timeseries.db")
        self._history: list[dict] = []
        self._load_history()

    def _load_history(self):
        """過去の精度記録を読み込み"""
        if os.path.exists(ACCURACY_JSONL):
            try:
                with open(ACCURACY_JSONL, "r") as f:
                    for line in f:
                        if line.strip():
                            self._history.append(json.loads(line))
            except Exception as e:
                logger.warning(f"Failed to load accuracy history: {e}")

    def evaluate_daily(self, locations: list[str] = None, dimension: str = "overall") -> dict:
        """昨日の予測 vs 実績を比較し、精度を記録。

        Args:
            locations: 評価対象国リスト（None=全PRIORITY_COUNTRIES[:20]）
            dimension: 評価次元

        Returns:
            日次精度レポート
        """
        if not locations:
            from config.constants import PRIORITY_COUNTRIES
            locations = PRIORITY_COUNTRIES[:20]

        if not os.path.exists(self.db_path):
            return {"error": "timeseries.db not found"}

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)

        evaluations = []
        total_ae = 0.0  # absolute error sum
        count = 0

        for loc in locations:
            # 実績値: 昨日のスコア
            actual_row = conn.execute(
                "SELECT overall_score, scores_json FROM risk_summaries "
                "WHERE location = ? AND date = ?",
                (loc, yesterday.isoformat()),
            ).fetchone()

            if not actual_row:
                continue

            if dimension == "overall":
                actual = float(actual_row["overall_score"]) if actual_row["overall_score"] else None
            else:
                try:
                    sj = json.loads(actual_row["scores_json"]) if actual_row["scores_json"] else {}
                    actual = float(sj.get(dimension, 0))
                except Exception:
                    actual = None

            if actual is None:
                continue

            # 予測値: 一昨日のデータから生成した1日先予測
            predicted = self._get_forecast_for_date(conn, loc, dimension, yesterday)

            if predicted is not None:
                ae = abs(actual - predicted)
                total_ae += ae
                count += 1

                evaluations.append({
                    "location": loc,
                    "dimension": dimension,
                    "date": yesterday.isoformat(),
                    "predicted": round(predicted, 2),
                    "actual": round(actual, 2),
                    "absolute_error": round(ae, 2),
                })

        conn.close()

        mae = total_ae / count if count > 0 else None

        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "date": yesterday.isoformat(),
            "dimension": dimension,
            "locations_evaluated": count,
            "mae": round(mae, 3) if mae is not None else None,
            "evaluations": evaluations,
        }

        # 記録を追記
        self._append_record(record)

        # ドリフト検出
        drift_alert = self._check_drift(mae)
        if drift_alert:
            record["drift_alert"] = drift_alert

        return record

    def _get_forecast_for_date(
        self, conn, location: str, dimension: str, target_date
    ) -> Optional[float]:
        """target_date に対する予測値を取得（過去データから1-step forecast）"""
        # target_date の2日前~30日前のデータを取得
        start = (target_date - timedelta(days=60)).isoformat()
        end = (target_date - timedelta(days=1)).isoformat()

        if dimension == "overall":
            rows = conn.execute(
                "SELECT overall_score FROM risk_summaries "
                "WHERE location = ? AND date >= ? AND date <= ? ORDER BY date ASC",
                (location, start, end),
            ).fetchall()
            scores = [float(r["overall_score"]) for r in rows if r["overall_score"] is not None]
        else:
            rows = conn.execute(
                "SELECT scores_json FROM risk_summaries "
                "WHERE location = ? AND date >= ? AND date <= ? ORDER BY date ASC",
                (location, start, end),
            ).fetchall()
            scores = []
            for r in rows:
                try:
                    sj = json.loads(r["scores_json"]) if r["scores_json"] else {}
                    if dimension in sj:
                        scores.append(float(sj[dimension]))
                except Exception:
                    pass

        if len(scores) < 3:
            return None

        # Weighted moving average (recent data weighted more)
        window = min(7, len(scores))
        recent = scores[-window:]
        weights = list(range(1, window + 1))
        total_w = sum(weights)
        wma = sum(s * w for s, w in zip(recent, weights)) / total_w

        # Trend component
        if len(scores) >= 14:
            older = scores[-14:-7]
            older_avg = sum(older) / len(older)
            recent_avg = sum(recent) / len(recent)
            trend = (recent_avg - older_avg) / 7
        elif len(scores) >= 7:
            older = scores[:-window]
            if older:
                older_avg = sum(older) / len(older)
                recent_avg = sum(recent) / len(recent)
                trend = (recent_avg - older_avg) / max(len(older), 1)
            else:
                trend = 0
        else:
            trend = 0

        predicted = wma + trend
        return max(0, min(100, predicted))

    def _append_record(self, record: dict):
        """精度記録を JSONL に追記"""
        os.makedirs(os.path.dirname(ACCURACY_JSONL), exist_ok=True)
        try:
            with open(ACCURACY_JSONL, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._history.append(record)
        except Exception as e:
            logger.error(f"Failed to write accuracy record: {e}")

    def _check_drift(self, current_mae: Optional[float]) -> Optional[dict]:
        """モデルドリフト検出: 直近7日 MAE > 全体 MAE × 1.5 → retrain trigger

        Returns:
            drift alert dict if drift detected, else None
        """
        if current_mae is None:
            return None

        # 過去の MAE 値を収集
        recent_maes = []
        all_maes = []

        for record in self._history:
            mae = record.get("mae")
            if mae is not None:
                all_maes.append(mae)

        # 直近7日の MAE
        recent_records = [
            r for r in self._history
            if r.get("date") and r.get("mae") is not None
        ][-7:]
        recent_maes = [r["mae"] for r in recent_records]

        if len(all_maes) < 14:
            return None  # Not enough history for drift detection

        overall_mae = sum(all_maes) / len(all_maes)
        recent_avg_mae = sum(recent_maes) / len(recent_maes) if recent_maes else 0

        if recent_avg_mae > overall_mae * 1.5:
            alert = {
                "type": "model_drift",
                "severity": "warning",
                "recent_7d_mae": round(recent_avg_mae, 3),
                "overall_mae": round(overall_mae, 3),
                "ratio": round(recent_avg_mae / overall_mae, 2),
                "action": "retrain_recommended",
                "message": (
                    f"Model drift detected: 7-day MAE ({recent_avg_mae:.2f}) > "
                    f"1.5x overall MAE ({overall_mae:.2f}). Retraining recommended."
                ),
                "timestamp": datetime.utcnow().isoformat(),
            }
            logger.warning(alert["message"])
            return alert

        return None

    def get_accuracy_report(self, days: int = 30) -> dict:
        """累積精度レポート

        Args:
            days: 直近N日のレポート
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()[:10]

        recent = [
            r for r in self._history
            if r.get("date", "") >= cutoff and r.get("mae") is not None
        ]

        if not recent:
            return {
                "period_days": days,
                "records": 0,
                "cumulative_mae": None,
                "best_mae": None,
                "worst_mae": None,
                "trend": "insufficient_data",
            }

        maes = [r["mae"] for r in recent]
        cumulative_mae = sum(maes) / len(maes)

        # Trend: compare first half vs second half
        half = len(maes) // 2
        if half > 0:
            first_half = sum(maes[:half]) / half
            second_half = sum(maes[half:]) / len(maes[half:])
            if second_half < first_half * 0.9:
                trend = "improving"
            elif second_half > first_half * 1.1:
                trend = "degrading"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "period_days": days,
            "records": len(recent),
            "cumulative_mae": round(cumulative_mae, 3),
            "best_mae": round(min(maes), 3),
            "worst_mae": round(max(maes), 3),
            "median_mae": round(sorted(maes)[len(maes) // 2], 3),
            "trend": trend,
            "daily_maes": [
                {"date": r["date"], "mae": r["mae"]}
                for r in recent[-14:]  # last 14 entries
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

    def check_retrain_needed(self) -> dict:
        """リトレーニング必要性の判定

        Returns:
            {"needed": bool, "reason": str, ...}
        """
        recent = [
            r for r in self._history
            if r.get("mae") is not None
        ][-7:]

        if len(recent) < 3:
            return {
                "needed": False,
                "reason": "Insufficient evaluation data",
                "evaluations": len(recent),
            }

        recent_maes = [r["mae"] for r in recent]
        avg_mae = sum(recent_maes) / len(recent_maes)

        # Check if recent MAE is above target
        target_mae = 6.0
        above_target = avg_mae > target_mae

        # Check for increasing trend
        if len(recent_maes) >= 5:
            first = sum(recent_maes[:2]) / 2
            last = sum(recent_maes[-2:]) / 2
            increasing = last > first * 1.2
        else:
            increasing = False

        needed = above_target or increasing
        reasons = []
        if above_target:
            reasons.append(f"MAE ({avg_mae:.2f}) exceeds target ({target_mae})")
        if increasing:
            reasons.append("MAE trending upward")

        return {
            "needed": needed,
            "reason": "; ".join(reasons) if reasons else "Model performance acceptable",
            "current_mae": round(avg_mae, 3),
            "target_mae": target_mae,
            "evaluations": len(recent),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def load_leading_indicators(self) -> list[dict]:
        """Load leading indicator config for use as forecast features.

        Reads config/leading_indicators.yaml and returns a list of
        leading indicator dicts with keys: leading, target, lag_days,
        min_r, country (optional), description.

        Returns:
            List of leading indicator configuration dicts. Empty list
            if config file is missing or cannot be parsed.
        """
        try:
            import yaml
        except ImportError:
            # Fallback: parse YAML manually for simple structure
            return self._load_leading_indicators_fallback()

        config_path = os.path.join(_PROJECT_ROOT, "config", "leading_indicators.yaml")
        if not os.path.exists(config_path):
            logger.warning(f"Leading indicators config not found: {config_path}")
            return []

        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to parse leading indicators config: {e}")
            return []

        indicators = config.get("leading_indicators", [])
        if not isinstance(indicators, list):
            logger.warning("leading_indicators key is not a list")
            return []

        # Validate and normalize each entry
        valid = []
        for item in indicators:
            if not isinstance(item, dict):
                continue
            if "leading" not in item or "target" not in item:
                continue
            valid.append({
                "leading": item["leading"],
                "target": item["target"],
                "lag_days": item.get("lag_days", 14),
                "min_r": item.get("min_r", 0.30),
                "country": item.get("country"),
                "description": item.get("description", ""),
            })

        logger.info(f"Loaded {len(valid)} leading indicator configs")
        return valid

    def _load_leading_indicators_fallback(self) -> list[dict]:
        """Fallback loader when PyYAML is not installed.

        Reads the YAML file line-by-line and extracts leading indicator
        entries from the simple list structure.
        """
        config_path = os.path.join(_PROJECT_ROOT, "config", "leading_indicators.yaml")
        if not os.path.exists(config_path):
            logger.warning(f"Leading indicators config not found: {config_path}")
            return []

        indicators = []
        current: dict = {}
        in_indicators_section = False

        try:
            with open(config_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("leading_indicators:"):
                        in_indicators_section = True
                        continue
                    if stripped.startswith("generalized_patterns:"):
                        # End of leading_indicators section
                        if current:
                            indicators.append(current)
                            current = {}
                        in_indicators_section = False
                        continue
                    if not in_indicators_section:
                        continue
                    if stripped.startswith("- leading:"):
                        if current:
                            indicators.append(current)
                        current = {"leading": stripped.split(":", 1)[1].strip()}
                    elif stripped.startswith("target:") and current:
                        current["target"] = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("lag_days:") and current:
                        try:
                            current["lag_days"] = int(stripped.split(":", 1)[1].strip())
                        except ValueError:
                            current["lag_days"] = 14
                    elif stripped.startswith("min_r:") and current:
                        try:
                            current["min_r"] = float(stripped.split(":", 1)[1].strip())
                        except ValueError:
                            current["min_r"] = 0.30
                    elif stripped.startswith("country:") and current:
                        current["country"] = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("description:") and current:
                        desc = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                        current["description"] = desc

            if current:
                indicators.append(current)
        except Exception as e:
            logger.error(f"Failed to parse leading indicators (fallback): {e}")
            return []

        # Filter valid entries
        valid = [
            i for i in indicators
            if "leading" in i and "target" in i
        ]
        logger.info(f"Loaded {len(valid)} leading indicator configs (fallback parser)")
        return valid
