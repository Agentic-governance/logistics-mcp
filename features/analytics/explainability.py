"""リスクスコア説明可能性 (XAI) エンジン — STREAM G-1
リスクスコアの内訳を自然言語（日本語）で解説し、
地域比較・トレンド・予測・推奨アクションを提供する。

Enhanced in v0.9.0:
- 過去履歴に基づくトレンド分析 (過去90日の推移)
- 線形回帰による30日先予測 (forecast) + 信頼区間
- スコア履歴の自動読み込み (data/score_history.json)
"""
import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from scoring.engine import SupplierRiskScore

logger = logging.getLogger(__name__)

# スコア履歴ファイル（anomaly_detectorと共有）
_HISTORY_PATH = os.environ.get("SCORE_HISTORY_PATH", "data/score_history.json")


def _load_score_history() -> dict:
    """スコア履歴をJSONファイルから読み込む"""
    try:
        if os.path.exists(_HISTORY_PATH):
            with open(_HISTORY_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"スコア履歴読み込み失敗: {e}")
    return {}


@dataclass
class RiskExplanation:
    """リスクスコアの説明結果"""
    summary: str              # 日本語の自然言語要約
    overall_score: float
    risk_level: str
    top_drivers: list[dict]   # [{dimension, score, weight, contribution, reason}]
    comparison: str           # 地域/グローバル平均との比較
    trend: str                # トレンド説明（過去90日の推移）
    forecast: str             # 30日先の予測テキスト (例: "30日後は83±8と予測")
    recommendations: list[str]
    trend_data: Optional[dict] = None   # {days, scores, slope, direction}
    forecast_data: Optional[dict] = None  # {predicted, lower, upper, horizon_days}
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "overall_score": self.overall_score,
            "risk_level": self.risk_level,
            "top_drivers": self.top_drivers,
            "comparison": self.comparison,
            "trend": self.trend,
            "forecast": self.forecast,
            "recommendations": self.recommendations,
            "trend_data": self.trend_data,
            "forecast_data": self.forecast_data,
            "generated_at": self.generated_at,
        }


def _risk_level(score: float) -> str:
    """リスクレベル判定"""
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score >= 20:
        return "LOW"
    return "MINIMAL"


# 次元名の日本語ラベル
DIMENSION_LABELS = {
    "sanctions": "制裁リスク",
    "geo_risk": "地政学リスク",
    "disaster": "災害リスク",
    "legal": "法的リスク",
    "maritime": "海上輸送リスク",
    "conflict": "紛争リスク",
    "economic": "経済リスク",
    "currency": "通貨リスク",
    "health": "感染症リスク",
    "humanitarian": "人道危機リスク",
    "weather": "気象リスク",
    "typhoon": "台風リスク",
    "compliance": "コンプライアンスリスク",
    "food_security": "食料安全保障リスク",
    "trade": "貿易依存リスク",
    "internet": "インターネットインフラリスク",
    "political": "政治リスク",
    "labor": "労働リスク",
    "port_congestion": "港湾混雑リスク",
    "aviation": "航空リスク",
    "energy": "エネルギー価格リスク",
    "japan_economy": "日本経済指標",
    "climate_risk": "気候変動リスク",
    "cyber_risk": "サイバーリスク",
}


class RiskExplainer:
    """リスクスコアの説明可能性 (XAI) エンジン"""

    # 地域平均スコア（ベンチマーク比較用）
    REGIONAL_AVERAGES = {
        "East Asia": {
            "countries": ["Japan", "South Korea", "Taiwan", "China"],
            "avg": 45,
        },
        "Southeast Asia": {
            "countries": [
                "Vietnam", "Thailand", "Malaysia", "Singapore",
                "Indonesia", "Philippines", "Myanmar", "Cambodia",
            ],
            "avg": 52,
        },
        "South Asia": {
            "countries": ["India", "Bangladesh", "Pakistan", "Sri Lanka"],
            "avg": 58,
        },
        "Middle East": {
            "countries": [
                "Saudi Arabia", "UAE", "Iran", "Iraq",
                "Turkey", "Israel", "Qatar", "Yemen",
            ],
            "avg": 55,
        },
        "Europe": {
            "countries": [
                "Germany", "United Kingdom", "France", "Italy",
                "Poland", "Netherlands", "Switzerland", "Ukraine",
            ],
            "avg": 35,
        },
        "Africa": {
            "countries": [
                "Nigeria", "Ethiopia", "Kenya", "Egypt",
                "South Sudan", "Somalia", "South Africa",
            ],
            "avg": 62,
        },
        "Americas": {
            "countries": [
                "United States", "Canada", "Mexico", "Colombia",
                "Venezuela", "Argentina", "Chile", "Brazil",
            ],
            "avg": 40,
        },
    }

    # 次元別の高リスク理由テンプレート
    DIMENSION_REASON_TEMPLATES = {
        "sanctions": {
            70: "主要制裁リスト(OFAC/EU/UN)でのヒット可能性が高い",
            40: "部分的な制裁対象 — 取引制限の可能性あり",
            0: "制裁リストにおける重大なリスクは検出されていない",
        },
        "compliance": {
            70: "FATFブラックリスト掲載中またはグレーリスト",
            40: "コンプライアンス指標が中程度のリスクを示す",
            0: "コンプライアンスリスクは低い水準",
        },
        "conflict": {
            70: "過去30日で多数の武力衝突が報告",
            40: "散発的な武力衝突が報告されている",
            0: "顕著な武力衝突は報告されていない",
        },
        "labor": {
            70: "強制労働リスク指数が高水準",
            40: "労働環境に一部の懸念が報告",
            0: "労働リスクは概ね低い水準",
        },
        "geo_risk": {
            70: "地政学的緊張が非常に高い — GDELT分析に基づく",
            40: "地政学的リスクが中程度に上昇",
            0: "地政学的リスクは安定的な水準",
        },
        "disaster": {
            70: "大規模自然災害の進行中または高い発生リスク",
            40: "自然災害リスクが中程度に上昇",
            0: "大きな自然災害リスクは検出されていない",
        },
        "economic": {
            70: "深刻な経済的不安定性 — GDP収縮/インフレ高騰",
            40: "経済指標に一部の悪化傾向",
            0: "経済状況は比較的安定",
        },
        "currency": {
            70: "通貨が大幅に下落中 — 為替変動リスクが高い",
            40: "通貨に中程度の変動リスク",
            0: "通貨は比較的安定している",
        },
        "health": {
            70: "重大な感染症の流行が進行中",
            40: "感染症リスクが中程度に上昇",
            0: "感染症リスクは低い水準",
        },
        "humanitarian": {
            70: "深刻な人道危機が進行中",
            40: "人道支援の必要性が高まっている",
            0: "人道的状況は安定している",
        },
        "political": {
            70: "政治的自由度が極めて低い — 権威主義的統治",
            40: "政治的自由度に一部の制約",
            0: "政治的自由度は比較的高い",
        },
        "maritime": {
            70: "海上輸送ルートに重大な混乱または脅威",
            40: "海上輸送に中程度のリスク",
            0: "海上輸送ルートは概ね安全",
        },
        "weather": {
            70: "極端な気象現象が進行中または予測されている",
            40: "気象条件に注意が必要",
            0: "気象条件は安定している",
        },
        "typhoon": {
            70: "台風/サイクロンの直撃リスクが非常に高い",
            40: "台風シーズンによる中程度のリスク",
            0: "台風/サイクロンの脅威は低い",
        },
        "food_security": {
            70: "深刻な食料不安が拡大中",
            40: "食料安全保障に一部の懸念",
            0: "食料供給は安定している",
        },
        "trade": {
            70: "貿易依存度が極めて高い — 集中リスク",
            40: "貿易構造に中程度の集中リスク",
            0: "貿易構造は分散されている",
        },
        "internet": {
            70: "インターネットインフラの深刻な障害または遮断",
            40: "インターネット接続の安定性に懸念",
            0: "インターネットインフラは安定している",
        },
        "port_congestion": {
            70: "港湾混雑が深刻 — 大幅な遅延が発生中",
            40: "港湾混雑が中程度に上昇",
            0: "港湾は正常に稼動している",
        },
        "aviation": {
            70: "航空輸送に重大な制約または安全上の懸念",
            40: "航空輸送に中程度のリスク",
            0: "航空輸送は安定している",
        },
        "energy": {
            70: "エネルギー価格の急騰 — コストリスクが高い",
            40: "エネルギー価格が中程度に上昇",
            0: "エネルギー価格は安定している",
        },
        "japan_economy": {
            70: "日本経済指標が大幅に悪化",
            40: "日本経済に一部の懸念",
            0: "日本経済指標は安定",
        },
        "climate_risk": {
            70: "気候変動に対する脆弱性が非常に高い",
            40: "気候リスクが中程度",
            0: "気候変動リスクは管理可能な水準",
        },
        "cyber_risk": {
            70: "サイバー脅威が非常に高い — 重大なインシデント",
            40: "サイバーセキュリティに中程度のリスク",
            0: "サイバーリスクは概ね低い水準",
        },
        "legal": {
            70: "法的紛争リスクが高い — 訴訟事例多数",
            40: "法的リスクが中程度",
            0: "法的リスクは低い水準",
        },
    }

    # リスクレベル別の推奨アクションテンプレート
    LEVEL_RECOMMENDATIONS = {
        "CRITICAL": [
            "即座にサプライチェーンの代替ルートを確保してください",
            "安全在庫の緊急積み増しを検討してください",
            "該当地域からの調達を一時停止する判断が必要です",
            "経営層へのエスカレーションを実施してください",
        ],
        "HIGH": [
            "代替サプライヤーの事前選定を進めてください",
            "安全在庫の見直しを推奨します",
            "定期的なリスクモニタリングの頻度を上げてください",
        ],
        "MEDIUM": [
            "リスクの推移を定期的に監視してください",
            "代替調達先のリストを更新してください",
        ],
        "LOW": [
            "定期的なリスク評価を継続してください",
        ],
        "MINIMAL": [
            "現在の調達体制を維持しつつ、定期監視を継続してください",
        ],
    }

    def _get_region(self, location: str) -> Optional[str]:
        """国名から所属地域を特定"""
        for region, info in self.REGIONAL_AVERAGES.items():
            if location in info["countries"]:
                return region
        return None

    def _get_regional_avg(self, location: str) -> Optional[float]:
        """国名から地域平均スコアを取得"""
        region = self._get_region(location)
        if region:
            return self.REGIONAL_AVERAGES[region]["avg"]
        return None

    def _get_global_avg(self) -> float:
        """全地域の加重平均を返す"""
        total_countries = 0
        weighted_sum = 0.0
        for info in self.REGIONAL_AVERAGES.values():
            n = len(info["countries"])
            total_countries += n
            weighted_sum += info["avg"] * n
        return weighted_sum / total_countries if total_countries > 0 else 50.0

    def _get_dimension_reason(self, dimension: str, score: float) -> str:
        """次元スコアに基づく理由テキストを生成"""
        templates = self.DIMENSION_REASON_TEMPLATES.get(dimension, {})
        if not templates:
            label = DIMENSION_LABELS.get(dimension, dimension)
            if score >= 70:
                return f"{label}が高水準 ({score:.0f}/100)"
            elif score >= 40:
                return f"{label}が中程度 ({score:.0f}/100)"
            else:
                return f"{label}は低水準 ({score:.0f}/100)"

        # 閾値の降順で最初にマッチするテンプレートを使用
        for threshold in sorted(templates.keys(), reverse=True):
            if score >= threshold:
                return templates[threshold]

        return templates.get(0, f"{dimension}: {score:.0f}/100")

    def _compute_contributions(self, scores: dict) -> list[dict]:
        """各次元のスコアと重みから寄与度を計算し、降順で返す"""
        weights = SupplierRiskScore.WEIGHTS
        contributions = []

        for dim, weight in weights.items():
            score = scores.get(dim, 0)
            contribution = score * weight
            contributions.append({
                "dimension": dim,
                "label": DIMENSION_LABELS.get(dim, dim),
                "score": score,
                "weight": round(weight, 4),
                "contribution": round(contribution, 2),
                "reason": self._get_dimension_reason(dim, score),
            })

        # sanctionsは別枠だがスコアがあれば追加
        if "sanctions" in scores and scores["sanctions"] > 0:
            sanction_score = scores["sanctions"]
            contributions.append({
                "dimension": "sanctions",
                "label": DIMENSION_LABELS.get("sanctions", "制裁リスク"),
                "score": sanction_score,
                "weight": 0.0,  # 別計算
                "contribution": sanction_score * 0.5 if sanction_score < 100 else 100.0,
                "reason": self._get_dimension_reason("sanctions", sanction_score),
            })

        contributions.sort(key=lambda x: -x["contribution"])
        return contributions

    def _generate_comparison(self, location: str, overall_score: float) -> str:
        """地域/グローバル平均との比較テキストを生成"""
        region = self._get_region(location)
        regional_avg = self._get_regional_avg(location)
        global_avg = self._get_global_avg()

        parts = []
        if region and regional_avg is not None:
            diff = overall_score - regional_avg
            if diff > 10:
                parts.append(
                    f"{region}地域平均({regional_avg:.0f})を{diff:.0f}ポイント上回っています（リスクが高い）"
                )
            elif diff < -10:
                parts.append(
                    f"{region}地域平均({regional_avg:.0f})を{abs(diff):.0f}ポイント下回っています（リスクが低い）"
                )
            else:
                parts.append(
                    f"{region}地域平均({regional_avg:.0f})と同程度です"
                )

        diff_global = overall_score - global_avg
        if diff_global > 10:
            parts.append(
                f"グローバル平均({global_avg:.0f})を{diff_global:.0f}ポイント上回っています"
            )
        elif diff_global < -10:
            parts.append(
                f"グローバル平均({global_avg:.0f})を{abs(diff_global):.0f}ポイント下回っています"
            )
        else:
            parts.append(f"グローバル平均({global_avg:.0f})と同程度です")

        return "。".join(parts)

    def explain_score(
        self,
        location: str,
        score_result: dict,
        score_history: Optional[list] = None,
    ) -> RiskExplanation:
        """リスクスコアの自然言語説明を生成する。

        Args:
            location: 国名またはロケーション名
            score_result: calculate_risk_score().to_dict() の結果
            score_history: 過去スコアのリスト [{date, overall_score}, ...]。
                           未指定の場合は data/score_history.json から自動読み込み。

        Returns:
            RiskExplanation: 説明結果データクラス
        """
        try:
            overall = score_result.get("overall_score", 0)
            level = score_result.get("risk_level", _risk_level(overall))
            scores = score_result.get("scores", {})

            # 0. 履歴データの取得
            history = score_history or self._get_location_history(location)

            # 1. 寄与度分析
            contributions = self._compute_contributions(scores)
            top_drivers = contributions[:5]

            # 2. 地域比較
            comparison = self._generate_comparison(location, overall)

            # 3. トレンド分析（過去90日の履歴に基づく）
            trend_text, trend_data = self._generate_trend_text(
                location, overall, level, history,
            )

            # 4. 30日先予測
            forecast_text, forecast_data = self._generate_forecast(
                location, overall, history,
            )

            # 5. 推奨アクション
            recommendations = self._generate_recommendations(
                location, overall, level, top_drivers, scores,
            )

            # 6. 自然言語サマリ生成
            summary = self._generate_summary(
                location, overall, level, top_drivers, comparison,
            )

            return RiskExplanation(
                summary=summary,
                overall_score=overall,
                risk_level=level,
                top_drivers=top_drivers,
                comparison=comparison,
                trend=trend_text,
                forecast=forecast_text,
                recommendations=recommendations,
                trend_data=trend_data,
                forecast_data=forecast_data,
            )

        except Exception as e:
            return RiskExplanation(
                summary=f"{location}: スコア説明の生成中にエラーが発生しました — {e}",
                overall_score=score_result.get("overall_score", 0),
                risk_level=score_result.get("risk_level", "UNKNOWN"),
                top_drivers=[],
                comparison="比較不可",
                trend="不明",
                forecast="予測不可",
                recommendations=["エラーにより推奨アクションを生成できませんでした"],
            )

    def _generate_summary(
        self,
        location: str,
        overall: float,
        level: str,
        top_drivers: list[dict],
        comparison: str,
    ) -> str:
        """日本語の要約テキストを生成"""
        level_labels = {
            "CRITICAL": "極めて高い",
            "HIGH": "高い",
            "MEDIUM": "中程度の",
            "LOW": "低い",
            "MINIMAL": "極めて低い",
        }
        level_jp = level_labels.get(level, level)

        summary = (
            f"{location}の総合リスクスコアは{overall:.0f}/100で、"
            f"リスクレベルは「{level}」（{level_jp}）です。"
        )

        if top_drivers:
            driver_texts = []
            for d in top_drivers[:3]:
                driver_texts.append(f"{d['label']}({d['score']:.0f})")
            summary += f"主なリスク要因は{', '.join(driver_texts)}です。"

        summary += comparison + "。"

        return summary

    def _get_location_history(self, location: str) -> list:
        """data/score_history.json からロケーション別のスコア履歴を取得する。

        Returns:
            [{date: str, overall_score: float}, ...] のリスト（日付昇順）
        """
        try:
            all_history = _load_score_history()
            # score_history.json の構造: {location: [{date, overall_score, scores}, ...]}
            loc_history = all_history.get(location, [])
            if not loc_history:
                # キーが小文字/大文字の揺れに対応
                for key, val in all_history.items():
                    if key.lower() == location.lower():
                        loc_history = val
                        break
            # 日付昇順にソート
            loc_history.sort(key=lambda x: x.get("date", ""))
            return loc_history
        except Exception as e:
            logger.debug(f"履歴取得失敗 ({location}): {e}")
            return []

    @staticmethod
    def _linear_regression(values: list) -> tuple:
        """単純線形回帰: y = a + b*x を計算する。

        Args:
            values: スコア値のリスト（時系列順）

        Returns:
            (intercept, slope, r_squared, residual_std)
        """
        n = len(values)
        if n < 2:
            return 0.0, 0.0, 0.0, 0.0

        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(values) / n

        ss_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values))
        ss_xx = sum((xi - x_mean) ** 2 for xi in x)
        ss_yy = sum((yi - y_mean) ** 2 for yi in values)

        if ss_xx == 0:
            return y_mean, 0.0, 0.0, 0.0

        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean

        # 決定係数 R²
        ss_res = sum((yi - (intercept + slope * xi)) ** 2 for xi, yi in zip(x, values))
        r_squared = 1.0 - (ss_res / ss_yy) if ss_yy > 0 else 0.0

        # 残差の標準偏差（予測の信頼区間に使用）
        residual_std = math.sqrt(ss_res / max(n - 2, 1))

        return intercept, slope, r_squared, residual_std

    def _generate_trend_text(
        self,
        location: str,
        overall: float,
        level: str,
        history: Optional[list] = None,
    ) -> tuple:
        """過去90日のスコア履歴に基づくトレンド説明を生成する。

        Returns:
            (trend_text: str, trend_data: dict or None)
        """
        # 履歴データがある場合: 統計的トレンド分析
        if history and len(history) >= 3:
            try:
                # 過去90日分のみ抽出
                cutoff = (datetime.utcnow() - timedelta(days=90)).isoformat()[:10]
                recent = [h for h in history if h.get("date", "") >= cutoff]

                if len(recent) >= 3:
                    values = [h.get("overall_score", 0) for h in recent]
                    intercept, slope, r_sq, _ = self._linear_regression(values)

                    # 1データポイントあたりの日数を推定
                    n_days = 90
                    daily_slope = slope * len(values) / n_days if n_days > 0 else 0

                    # 90日間のトータル変化量
                    total_change = values[-1] - values[0]

                    if abs(total_change) >= 5:
                        if total_change > 0:
                            direction = "上昇傾向"
                        else:
                            direction = "下降傾向"
                        trend_text = (
                            f"過去90日で{abs(total_change):.0f}点{direction}。"
                            f"（{values[0]:.0f}→{values[-1]:.0f}、"
                            f"データポイント数: {len(values)}）"
                        )
                    else:
                        trend_text = (
                            f"過去90日間のスコアは安定しています"
                            f"（変動幅: {abs(total_change):.0f}点）。"
                        )

                    trend_data = {
                        "days": 90,
                        "data_points": len(values),
                        "first_score": values[0],
                        "last_score": values[-1],
                        "total_change": round(total_change, 1),
                        "slope_per_day": round(daily_slope, 3),
                        "r_squared": round(r_sq, 4),
                        "direction": "up" if total_change > 0 else ("down" if total_change < 0 else "stable"),
                    }
                    return trend_text, trend_data
            except Exception as e:
                logger.debug(f"トレンド分析失敗 ({location}): {e}")

        # フォールバック: 単一時点の解説
        if level == "CRITICAL":
            text = (
                f"{location}のリスクは現在CRITICALレベルにあり、"
                "即時対応が求められます。"
            )
        elif level == "HIGH":
            text = (
                f"{location}のリスクは高い水準にあり、"
                "悪化すればCRITICALに達する可能性があります。"
            )
        elif level == "MEDIUM":
            text = (
                f"{location}のリスクは中程度ですが、"
                "特定の次元で急変が起きた場合は注意が必要です。"
            )
        else:
            text = f"{location}のリスクは現在安定しています。"

        return text, None

    def _generate_forecast(
        self,
        location: str,
        overall: float,
        history: Optional[list] = None,
        horizon_days: int = 30,
    ) -> tuple:
        """線形回帰に基づく30日先のスコア予測を生成する。

        Args:
            location: ロケーション名
            overall: 現在の総合スコア
            history: 過去スコアリスト
            horizon_days: 予測期間（日数）

        Returns:
            (forecast_text: str, forecast_data: dict or None)
        """
        if history and len(history) >= 5:
            try:
                values = [h.get("overall_score", 0) for h in history]
                n = len(values)
                intercept, slope, r_sq, residual_std = self._linear_regression(values)

                # データポイント間の平均日数を推定
                if n >= 2:
                    try:
                        first_date = datetime.fromisoformat(history[0].get("date", "")[:10])
                        last_date = datetime.fromisoformat(history[-1].get("date", "")[:10])
                        total_days = (last_date - first_date).days
                        avg_interval = total_days / (n - 1) if n > 1 else 1
                    except Exception:
                        avg_interval = 1.0
                else:
                    avg_interval = 1.0

                # horizon_days先のインデックス
                steps_ahead = horizon_days / avg_interval if avg_interval > 0 else horizon_days
                predicted_raw = intercept + slope * (n - 1 + steps_ahead)

                # 0-100に制限
                predicted = max(0, min(100, predicted_raw))

                # 信頼区間: ±2σ (95%信頼区間の近似)
                # 外挿の不確実性を考慮して、ステップ数に応じてσを拡大
                extrapolation_factor = math.sqrt(1 + steps_ahead / n)
                margin = 2.0 * residual_std * extrapolation_factor
                margin = max(margin, 3.0)  # 最低±3の不確実性

                lower = max(0, predicted - margin)
                upper = min(100, predicted + margin)

                # テキスト生成
                forecast_text = (
                    f"{horizon_days}日後のスコアは"
                    f"{predicted:.0f}±{margin:.0f}と予測"
                    f"（95%信頼区間: {lower:.0f}〜{upper:.0f}）"
                )

                forecast_data = {
                    "horizon_days": horizon_days,
                    "predicted": round(predicted, 1),
                    "lower": round(lower, 1),
                    "upper": round(upper, 1),
                    "margin": round(margin, 1),
                    "r_squared": round(r_sq, 4),
                    "data_points_used": n,
                    "method": "linear_regression",
                }
                return forecast_text, forecast_data

            except Exception as e:
                logger.debug(f"予測生成失敗 ({location}): {e}")

        # 履歴不足の場合: 現在値ベースの定性的予測
        forecast_text = (
            f"履歴データ不足のため定量予測は不可。"
            f"現在のスコア({overall:.0f})が{horizon_days}日間維持される見込み。"
        )
        return forecast_text, None

    def _generate_recommendations(
        self,
        location: str,
        overall: float,
        level: str,
        top_drivers: list[dict],
        scores: dict,
    ) -> list[str]:
        """推奨アクションを生成"""
        recs = list(self.LEVEL_RECOMMENDATIONS.get(level, []))

        # 次元固有の推奨
        for driver in top_drivers[:3]:
            dim = driver["dimension"]
            score = driver["score"]
            label = driver["label"]

            if score >= 70:
                if dim == "sanctions":
                    recs.append(
                        f"制裁リスク: {location}との取引前に法務部門による制裁コンプライアンスチェックを実施してください"
                    )
                elif dim in ("conflict", "geo_risk"):
                    recs.append(
                        f"{label}: 紛争地域からの調達を避け、代替ルートを確保してください"
                    )
                elif dim == "disaster":
                    recs.append(
                        f"{label}: BCP（事業継続計画）の発動準備を検討してください"
                    )
                elif dim in ("economic", "currency"):
                    recs.append(
                        f"{label}: 為替ヘッジや価格調整条項の導入を検討してください"
                    )
                elif dim == "port_congestion":
                    recs.append(
                        f"{label}: 代替港湾の利用やリードタイムの延長を検討してください"
                    )

        return recs

    def compare_locations(
        self,
        locations: list[str],
        score_results: list[dict],
    ) -> dict:
        """複数ロケーションを比較し、説明付きのランキングを返す。

        Args:
            locations: ロケーション名リスト
            score_results: 各ロケーションの score_result リスト

        Returns:
            比較結果辞書
        """
        try:
            explanations = []
            for loc, sr in zip(locations, score_results):
                exp = self.explain_score(loc, sr)
                explanations.append({
                    "location": loc,
                    "overall_score": exp.overall_score,
                    "risk_level": exp.risk_level,
                    "summary": exp.summary,
                    "top_drivers": exp.top_drivers[:3],
                    "comparison": exp.comparison,
                    "trend": exp.trend,
                    "forecast": exp.forecast,
                })

            # ランキング
            ranked = sorted(explanations, key=lambda x: -x["overall_score"])
            for i, item in enumerate(ranked):
                item["rank"] = i + 1

            # 最もリスクの高い/低いロケーション
            highest = ranked[0] if ranked else None
            lowest = ranked[-1] if ranked else None

            # 全ロケーション平均
            avg_score = (
                sum(e["overall_score"] for e in explanations) / len(explanations)
                if explanations else 0
            )

            return {
                "location_count": len(locations),
                "average_score": round(avg_score, 1),
                "ranking": ranked,
                "highest_risk": highest,
                "lowest_risk": lowest,
                "generated_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            return {
                "error": str(e),
                "location_count": len(locations),
                "generated_at": datetime.utcnow().isoformat(),
            }

    def explain_score_change(
        self,
        location: str,
        old_score: dict,
        new_score: dict,
    ) -> dict:
        """2期間のスコア変化を説明する。

        Args:
            location: ロケーション名
            old_score: 旧スコア結果 (to_dict形式)
            new_score: 新スコア結果 (to_dict形式)

        Returns:
            変化の説明辞書
        """
        try:
            old_overall = old_score.get("overall_score", 0)
            new_overall = new_score.get("overall_score", 0)
            overall_delta = new_overall - old_overall

            old_scores = old_score.get("scores", {})
            new_scores = new_score.get("scores", {})

            # 次元別変化
            dimension_changes = []
            all_dims = set(list(old_scores.keys()) + list(new_scores.keys()))
            for dim in all_dims:
                old_val = old_scores.get(dim, 0)
                new_val = new_scores.get(dim, 0)
                delta = new_val - old_val
                if abs(delta) >= 5:  # 5ポイント以上の変化のみ報告
                    direction = "上昇" if delta > 0 else "下降"
                    label = DIMENSION_LABELS.get(dim, dim)
                    dimension_changes.append({
                        "dimension": dim,
                        "label": label,
                        "old_score": old_val,
                        "new_score": new_val,
                        "delta": delta,
                        "direction": direction,
                        "reason": self._get_dimension_reason(dim, new_val),
                    })

            dimension_changes.sort(key=lambda x: -abs(x["delta"]))

            # 変化のサマリ生成
            if overall_delta > 0:
                direction_text = f"{abs(overall_delta):.0f}ポイント上昇（リスク増大）"
            elif overall_delta < 0:
                direction_text = f"{abs(overall_delta):.0f}ポイント下降（リスク改善）"
            else:
                direction_text = "変化なし"

            change_summary = (
                f"{location}の総合スコアが{old_overall:.0f}から{new_overall:.0f}に変化しました"
                f"（{direction_text}）。"
            )

            if dimension_changes:
                top_change = dimension_changes[0]
                change_summary += (
                    f"最大の変動要因は{top_change['label']}"
                    f"（{top_change['old_score']:.0f}→{top_change['new_score']:.0f}、"
                    f"{top_change['direction']}）です。"
                )

            # レベル変化
            old_level = old_score.get("risk_level", _risk_level(old_overall))
            new_level = new_score.get("risk_level", _risk_level(new_overall))
            level_changed = old_level != new_level

            if level_changed:
                change_summary += (
                    f"リスクレベルが{old_level}から{new_level}に変更されました。"
                )

            return {
                "location": location,
                "old_overall": old_overall,
                "new_overall": new_overall,
                "overall_delta": overall_delta,
                "old_level": old_level,
                "new_level": new_level,
                "level_changed": level_changed,
                "change_summary": change_summary,
                "dimension_changes": dimension_changes[:10],
                "generated_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            return {
                "location": location,
                "error": str(e),
                "generated_at": datetime.utcnow().isoformat(),
            }
