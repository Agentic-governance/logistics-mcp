"""スコア異常検知・データ品質モニタリング
スコア急変・データ鮮度・計算整合性をチェックし、アラートを生成する。
"""
import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  DIMENSION_FRESHNESS: Expected update intervals (hours) for all 24 dimensions
#  Used by check_data_freshness() to detect stale data.
#  v0.9.0: Replaces old FRESHNESS_THRESHOLDS with accurate per-source intervals.
# ---------------------------------------------------------------------------
DIMENSION_FRESHNESS: Dict[str, int] = {
    "conflict": 24,           # ACLED: daily
    "geo_risk": 24,           # GDELT: daily
    "disaster": 6,            # GDACS/USGS: near-realtime
    "weather": 6,             # Open-Meteo: 6-hourly
    "typhoon": 6,             # NOAA: 6-hourly
    "maritime": 24,           # IMF PortWatch: daily
    "sanctions": 24,          # Sanctions lists: daily
    "economic": 720,          # World Bank: monthly (30d)
    "currency": 24,           # Frankfurter/ECB: daily
    "health": 24,             # Disease.sh: daily
    "humanitarian": 168,      # OCHA: weekly
    "food_security": 168,     # FEWS NET/WFP: weekly
    "compliance": 720,        # FATF/TI: monthly
    "political": 720,         # Freedom House: monthly
    "trade": 2160,            # UN Comtrade: quarterly
    "internet": 24,           # Cloudflare: daily
    "labor": 2160,            # DoL ILAB: quarterly
    "port_congestion": 168,   # UNCTAD: weekly
    "aviation": 24,           # OpenSky: daily
    "energy": 720,            # FRED/EIA: monthly
    "japan_economy": 168,     # BOJ: weekly
    "climate_risk": 8760,     # ND-GAIN: annual
    "cyber_risk": 168,        # OONI/CISA: weekly
    "legal": 168,             # weekly
}

# Backward-compatible alias (legacy code may reference this name)
FRESHNESS_THRESHOLDS = DIMENSION_FRESHNESS


@dataclass
class AnomalyAlert:
    location: str
    dimension: str
    previous_value: float
    current_value: float
    delta: float
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "dimension": self.dimension,
            "previous_value": self.previous_value,
            "current_value": self.current_value,
            "delta": self.delta,
            "severity": self.severity,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class StaleDataAlert:
    location: str
    dimension: str
    last_updated: Optional[datetime]
    expected_max_age_hours: int
    actual_age_hours: Optional[float]
    severity: Literal["INFO", "WARNING"]
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "dimension": self.dimension,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "expected_max_age_hours": self.expected_max_age_hours,
            "actual_age_hours": round(self.actual_age_hours, 1) if self.actual_age_hours else None,
            "severity": self.severity,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ValidationError:
    check_name: str
    expected: str
    actual: str
    severity: Literal["WARNING", "CRITICAL"]
    message: str

    def to_dict(self) -> dict:
        return {
            "check_name": self.check_name,
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
            "message": self.message,
        }


# Simple file-based score history for delta comparison
_HISTORY_PATH = os.environ.get("SCORE_HISTORY_PATH", "data/score_history.json")


def _load_history() -> dict:
    try:
        if os.path.exists(_HISTORY_PATH):
            with open(_HISTORY_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_history(history: dict):
    try:
        os.makedirs(os.path.dirname(_HISTORY_PATH) or ".", exist_ok=True)
        with open(_HISTORY_PATH, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save score history: {e}")


class ScoreAnomalyDetector:
    """スコア異常検知エンジン"""

    def __init__(self, overall_threshold: int = 20, dimension_threshold: int = 30):
        self.overall_threshold = overall_threshold
        self.dimension_threshold = dimension_threshold

    @staticmethod
    def _compute_statistical_threshold(
        history_values: List[float], current_value: float
    ) -> Optional[dict]:
        """Compute mean +/- 2*sigma threshold from historical values.

        Returns dict with keys: mean, std, lower, upper, is_anomaly, z_score
        or None if fewer than 30 data points.
        """
        if len(history_values) < 30:
            return None
        mean = sum(history_values) / len(history_values)
        variance = sum((v - mean) ** 2 for v in history_values) / len(history_values)
        std = math.sqrt(variance) if variance > 0 else 0.0
        # Avoid division by zero: if std is negligible, any deviation is anomalous
        if std < 0.01:
            std = 0.01
        z_score = (current_value - mean) / std
        lower = mean - 2 * std
        upper = mean + 2 * std
        return {
            "mean": round(mean, 2),
            "std": round(std, 2),
            "lower": round(lower, 2),
            "upper": round(upper, 2),
            "is_anomaly": abs(z_score) > 2.0,
            "z_score": round(z_score, 2),
        }

    def check_score_anomaly(
        self, location: str, new_score_dict: dict
    ) -> List[AnomalyAlert]:
        """スコア急変検知。前回値との比較でアラートを生成。

        Improvements (v0.9.0):
        - First score for a location: no delta alert generated (no baseline)
        - 30+ historical data points: use mean +/- 2*sigma for anomaly detection
        - <30 data points: fall back to fixed threshold (overall >=20, dim >=30)
        """
        alerts: List[AnomalyAlert] = []
        history = _load_history()
        prev = history.get(location, {})

        overall = new_score_dict.get("overall_score", 0)
        scores = new_score_dict.get("scores", {})

        # Retrieve accumulated score history lists (new in v0.9.0)
        overall_history: List[float] = prev.get("overall_history", [])
        dim_histories: Dict[str, List[float]] = prev.get("dim_histories", {})

        # --- First-score guard ---
        # If this is the very first score for the location, skip delta/anomaly
        # alerts (no baseline to compare against). Only validity checks apply.
        is_first_score = prev.get("overall_score") is None and len(overall_history) == 0

        if not is_first_score:
            # 1. overall_score anomaly detection
            prev_overall = prev.get("overall_score")
            stat = self._compute_statistical_threshold(overall_history, overall)
            if stat is not None:
                # Statistical threshold (30+ data points)
                if stat["is_anomaly"]:
                    severity = "CRITICAL" if abs(stat["z_score"]) >= 3.0 else "WARNING"
                    alerts.append(AnomalyAlert(
                        location=location, dimension="overall",
                        previous_value=prev_overall if prev_overall is not None else 0,
                        current_value=overall,
                        delta=round(overall - (prev_overall or 0), 1),
                        severity=severity,
                        message=(
                            f"{location}: overall score {overall} outside "
                            f"statistical range [{stat['lower']}, {stat['upper']}] "
                            f"(z={stat['z_score']}, mean={stat['mean']}, std={stat['std']})"
                        ),
                    ))
            else:
                # Fixed threshold fallback (<30 data points)
                if prev_overall is not None:
                    delta = overall - prev_overall
                    if abs(delta) >= self.overall_threshold:
                        severity = "CRITICAL" if abs(delta) >= 30 else "WARNING"
                        alerts.append(AnomalyAlert(
                            location=location, dimension="overall",
                            previous_value=prev_overall, current_value=overall,
                            delta=delta, severity=severity,
                            message=f"{location}: overall score {delta:+d} "
                                    f"({prev_overall} -> {overall})",
                        ))

            # 2. Per-dimension anomaly detection
            prev_scores = prev.get("scores", {})
            for dim, val in scores.items():
                dim_hist = dim_histories.get(dim, [])
                prev_val = prev_scores.get(dim)
                stat_dim = self._compute_statistical_threshold(dim_hist, val)
                if stat_dim is not None:
                    # Statistical threshold (30+ data points)
                    if stat_dim["is_anomaly"]:
                        severity = "CRITICAL" if abs(stat_dim["z_score"]) >= 3.0 else "WARNING"
                        alerts.append(AnomalyAlert(
                            location=location, dimension=dim,
                            previous_value=prev_val if prev_val is not None else 0,
                            current_value=val,
                            delta=round(val - (prev_val or 0), 1),
                            severity=severity,
                            message=(
                                f"{location}: {dim} score {val} outside "
                                f"statistical range [{stat_dim['lower']}, {stat_dim['upper']}] "
                                f"(z={stat_dim['z_score']})"
                            ),
                        ))
                else:
                    # Fixed threshold fallback
                    if prev_val is not None:
                        delta = val - prev_val
                        if abs(delta) >= self.dimension_threshold:
                            severity = "CRITICAL" if abs(delta) >= 50 else "WARNING"
                            alerts.append(AnomalyAlert(
                                location=location, dimension=dim,
                                previous_value=prev_val, current_value=val,
                                delta=delta, severity=severity,
                                message=f"{location}: {dim} {delta:+d} "
                                        f"({prev_val} -> {val})",
                            ))

            # 3. CRITICAL到達 (>=80)
            if overall >= 80 and (prev_overall is None or prev_overall < 80):
                alerts.append(AnomalyAlert(
                    location=location, dimension="overall",
                    previous_value=prev_overall or 0, current_value=overall,
                    delta=overall - (prev_overall or 0), severity="CRITICAL",
                    message=f"{location}: reached CRITICAL level ({overall})",
                ))

        # 4. NaN/None/範囲外チェック (always runs, even on first score)
        for dim, val in scores.items():
            if val is None or not isinstance(val, (int, float)):
                alerts.append(AnomalyAlert(
                    location=location, dimension=dim,
                    previous_value=0, current_value=0,
                    delta=0, severity="WARNING",
                    message=f"{location}: {dim} has invalid value: {val}",
                ))
            elif val < 0 or val > 100:
                alerts.append(AnomalyAlert(
                    location=location, dimension=dim,
                    previous_value=0, current_value=val,
                    delta=0, severity="WARNING",
                    message=f"{location}: {dim} out of range [0,100]: {val}",
                ))

        # Update history — accumulate score lists for statistical analysis
        overall_history.append(overall)
        for dim, val in scores.items():
            if isinstance(val, (int, float)) and 0 <= val <= 100:
                dim_histories.setdefault(dim, []).append(val)

        history[location] = {
            "overall_score": overall,
            "scores": scores,
            "overall_history": overall_history,
            "dim_histories": dim_histories,
            "updated_at": datetime.utcnow().isoformat(),
        }
        _save_history(history)

        return alerts

    def check_data_freshness(
        self,
        location: str,
        data_timestamps: Optional[Dict[str, datetime]] = None,
    ) -> List[StaleDataAlert]:
        """各次元のデータ鮮度をチェック (v0.9.0: uses DIMENSION_FRESHNESS).

        Compares each dimension's last-updated timestamp against its expected
        update interval from DIMENSION_FRESHNESS.  Severity is WARNING when
        data exceeds 1x the threshold but less than 2x, and escalates to
        WARNING (high) when exceeding 2x.  Dimensions with near-realtime
        expectations (<=24h) always produce WARNING.
        """
        alerts: List[StaleDataAlert] = []
        now = datetime.utcnow()

        if data_timestamps is None:
            return alerts

        for dim, threshold_hours in DIMENSION_FRESHNESS.items():
            last_updated = data_timestamps.get(dim)
            if last_updated is None:
                continue

            age_hours = (now - last_updated).total_seconds() / 3600

            if age_hours > threshold_hours:
                # Near-realtime or daily sources get WARNING; longer-cycle
                # sources get INFO unless they exceed 2x threshold.
                if threshold_hours <= 24:
                    severity = "WARNING"
                elif age_hours > threshold_hours * 2:
                    severity = "WARNING"
                else:
                    severity = "INFO"

                alerts.append(StaleDataAlert(
                    location=location, dimension=dim,
                    last_updated=last_updated,
                    expected_max_age_hours=threshold_hours,
                    actual_age_hours=age_hours,
                    severity=severity,
                    message=f"{location}: {dim} data is {age_hours:.0f}h old "
                            f"(threshold: {threshold_hours}h)",
                ))

        return alerts

    def validate_score_consistency(
        self, score_dict: dict
    ) -> List[ValidationError]:
        """スコア計算の整合性をチェック"""
        errors: List[ValidationError] = []

        from scoring.engine import SupplierRiskScore
        weights = SupplierRiskScore.WEIGHTS

        # 1. 重み合計チェック
        total_weight = sum(weights.values())
        if abs(total_weight - 1.0) > 0.001:
            errors.append(ValidationError(
                check_name="weight_sum",
                expected="1.000", actual=f"{total_weight:.4f}",
                severity="CRITICAL",
                message=f"Weight sum is {total_weight:.4f}, expected 1.0",
            ))

        # 2. 制裁=100 → overall=100 チェック
        scores = score_dict.get("scores", {})
        overall = score_dict.get("overall_score", 0)
        if scores.get("sanctions") == 100 and overall != 100:
            errors.append(ValidationError(
                check_name="sanctions_override",
                expected="overall=100 when sanctions=100",
                actual=f"overall={overall}",
                severity="CRITICAL",
                message="Sanctions=100 should force overall=100",
            ))

        # 3. composite score 検算
        weighted_scores = {
            dim: scores.get(dim, 0) for dim in weights
        }
        weighted_sum = sum(
            weighted_scores.get(dim, 0) * w for dim, w in weights.items()
        )
        sorted_vals = sorted(weighted_scores.values(), reverse=True)
        peak = sorted_vals[0] if sorted_vals else 0
        second_peak = sorted_vals[1] if len(sorted_vals) > 1 else 0

        expected_composite = int(weighted_sum * 0.6 + peak * 0.30 + second_peak * 0.10)
        sanction_bonus = scores.get("sanctions", 0) // 2 if scores.get("sanctions", 0) > 0 and scores.get("sanctions", 0) < 100 else 0
        expected_final = min(100, expected_composite + sanction_bonus)

        if scores.get("sanctions") != 100 and abs(overall - expected_final) > 1:
            errors.append(ValidationError(
                check_name="composite_calculation",
                expected=f"{expected_final}",
                actual=f"{overall}",
                severity="WARNING",
                message=f"Composite score mismatch: expected {expected_final}, got {overall}",
            ))

        return errors


def write_alerts_to_file(alerts: list, base_dir: str = "data/alerts"):
    """アラートをJSONLファイルに出力"""
    os.makedirs(base_dir, exist_ok=True)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    filepath = os.path.join(base_dir, f"{date_str}.jsonl")
    with open(filepath, "a") as f:
        for alert in alerts:
            f.write(json.dumps(alert.to_dict(), ensure_ascii=False) + "\n")
