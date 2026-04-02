"""
リスク調整レイヤー: シナリオベースの期待損失計算
================================================
SCRI v1.4.0

国別リスクシナリオ（楽観/ベース/悲観）の確率×影響率から期待損失を算出し、
SCRIスコアの現在値で動的に確率を調整する。

期待損失 = Σ (P_i × Impact_i)
動的調整: P_adjusted = P_base × (1 + scri_boost)
  scri_boost = (current_score - 50) / 100  (SCRIが50超なら確率上方修正)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 国別リスクシナリオ定義
# ---------------------------------------------------------------------------
RISK_SCENARIOS: Dict[str, List[Dict[str, Any]]] = {
    "CN": [
        {"name": "日中関係急悪化", "trigger_dimension": "bilateral",
         "base_probability": 0.15, "optimistic_probability": 0.05, "pessimistic_probability": 0.30,
         "impact_rate": 0.40},
        {"name": "中国景気後退", "trigger_dimension": "economic",
         "base_probability": 0.25, "optimistic_probability": 0.10, "pessimistic_probability": 0.40,
         "impact_rate": 0.20},
        {"name": "円高10%以上", "trigger_dimension": "currency",
         "base_probability": 0.35, "optimistic_probability": 0.15, "pessimistic_probability": 0.55,
         "impact_rate": 0.12},
        {"name": "中国国内感染症", "trigger_dimension": "health",
         "base_probability": 0.10, "optimistic_probability": 0.05, "pessimistic_probability": 0.20,
         "impact_rate": 0.60},
    ],
    "KR": [
        {"name": "韓国景気停滞", "trigger_dimension": "economic",
         "base_probability": 0.20, "optimistic_probability": 0.08, "pessimistic_probability": 0.35,
         "impact_rate": 0.10},
        {"name": "円高5%以上", "trigger_dimension": "currency",
         "base_probability": 0.40, "optimistic_probability": 0.20, "pessimistic_probability": 0.60,
         "impact_rate": 0.08},
        {"name": "日韓関係悪化", "trigger_dimension": "bilateral",
         "base_probability": 0.08, "optimistic_probability": 0.03, "pessimistic_probability": 0.18,
         "impact_rate": 0.30},
    ],
    "TW": [
        {"name": "台湾海峡緊張", "trigger_dimension": "bilateral",
         "base_probability": 0.12, "optimistic_probability": 0.05, "pessimistic_probability": 0.25,
         "impact_rate": 0.35},
        {"name": "台湾景気悪化", "trigger_dimension": "economic",
         "base_probability": 0.18, "optimistic_probability": 0.08, "pessimistic_probability": 0.30,
         "impact_rate": 0.15},
        {"name": "円高進行", "trigger_dimension": "currency",
         "base_probability": 0.35, "optimistic_probability": 0.15, "pessimistic_probability": 0.55,
         "impact_rate": 0.08},
    ],
    "US": [
        {"name": "米国景気後退", "trigger_dimension": "economic",
         "base_probability": 0.20, "optimistic_probability": 0.08, "pessimistic_probability": 0.35,
         "impact_rate": 0.15},
        {"name": "フライト供給減", "trigger_dimension": "aviation",
         "base_probability": 0.08, "optimistic_probability": 0.03, "pessimistic_probability": 0.15,
         "impact_rate": 0.15},
    ],
    "AU": [
        {"name": "豪ドル安", "trigger_dimension": "currency",
         "base_probability": 0.30, "optimistic_probability": 0.15, "pessimistic_probability": 0.45,
         "impact_rate": 0.12},
        {"name": "直行便減", "trigger_dimension": "aviation",
         "base_probability": 0.15, "optimistic_probability": 0.05, "pessimistic_probability": 0.25,
         "impact_rate": 0.12},
    ],
    "TH": [
        {"name": "タイ政情不安", "trigger_dimension": "political",
         "base_probability": 0.25, "optimistic_probability": 0.10, "pessimistic_probability": 0.40,
         "impact_rate": 0.30},
        {"name": "バーツ安", "trigger_dimension": "currency",
         "base_probability": 0.35, "optimistic_probability": 0.20, "pessimistic_probability": 0.50,
         "impact_rate": 0.10},
    ],
}

# ---------------------------------------------------------------------------
# 期待損失の上限（90%）
# ---------------------------------------------------------------------------
MAX_EXPECTED_LOSS = 0.90


class RiskAdjuster:
    """
    シナリオベースのリスク調整レイヤー。

    各国のリスクシナリオ（発生確率 × 影響率）から期待損失を計算し、
    ベースライン予測を下方修正する。SCRIリスクスコアが高い次元の
    シナリオは発生確率を動的に上方修正する。
    """

    def __init__(self, scenarios: Optional[Dict[str, list]] = None) -> None:
        self.scenarios = scenarios or RISK_SCENARIOS

    # -------------------------------------------------------------------
    # calculate_expected_loss — 期待損失計算
    # -------------------------------------------------------------------
    def calculate_expected_loss(
        self,
        country: str,
        scenario: str = "base",
        current_scri_scores: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        国別の期待損失を計算する。

        Args:
            country: ISO-2国コード (例: "CN", "KR")
            scenario: "optimistic" / "base" / "pessimistic"
            current_scri_scores: {dimension: score} 形式のSCRIスコア辞書
                                 各スコアは0-100。高い=リスク大。

        Returns:
            {
                "country": str,
                "scenario": str,
                "expected_loss": float,        # 0.0〜0.90
                "scenario_details": list,      # 各シナリオの詳細
                "scri_adjusted": bool,         # SCRI調整が適用されたか
            }
        """
        if current_scri_scores is None:
            current_scri_scores = {}

        country_scenarios = self.scenarios.get(country, [])
        if not country_scenarios:
            return {
                "country": country,
                "scenario": scenario,
                "expected_loss": 0.0,
                "scenario_details": [],
                "scri_adjusted": False,
            }

        # シナリオ選択のための確率キー
        prob_key_map = {
            "optimistic": "optimistic_probability",
            "base": "base_probability",
            "pessimistic": "pessimistic_probability",
        }
        prob_key = prob_key_map.get(scenario, "base_probability")

        scri_adjusted = len(current_scri_scores) > 0
        total_loss = 0.0
        details = []

        for sc in country_scenarios:
            raw_prob = sc.get(prob_key, sc["base_probability"])

            # SCRI動的調整: trigger_dimensionのスコアが50超なら確率上方修正
            adjusted_prob = raw_prob
            dim = sc.get("trigger_dimension", "")
            if dim and dim in current_scri_scores:
                score = current_scri_scores[dim]
                # scri_boost = (score - 50) / 100 → ±0.5 の範囲
                scri_boost = (score - 50.0) / 100.0
                adjusted_prob = raw_prob * (1.0 + scri_boost)
                # 確率は0〜1に収まるようにクリップ
                adjusted_prob = max(0.0, min(1.0, adjusted_prob))

            impact = sc["impact_rate"]
            contribution = adjusted_prob * impact
            total_loss += contribution

            details.append({
                "name": sc["name"],
                "trigger_dimension": dim,
                "raw_probability": round(raw_prob, 4),
                "adjusted_probability": round(adjusted_prob, 4),
                "impact_rate": round(impact, 4),
                "contribution": round(contribution, 6),
            })

        # 上限クリップ
        total_loss = min(total_loss, MAX_EXPECTED_LOSS)

        return {
            "country": country,
            "scenario": scenario,
            "expected_loss": round(total_loss, 6),
            "scenario_details": details,
            "scri_adjusted": scri_adjusted,
        }

    # -------------------------------------------------------------------
    # apply_risk_adjustment — ベースライン予測にリスク調整を適用
    # -------------------------------------------------------------------
    def apply_risk_adjustment(
        self,
        baseline_forecast: Dict[str, Any],
        expected_loss: float,
        country: str,
    ) -> Dict[str, Any]:
        """
        ベースライン予測に期待損失を適用する。

        - 中央値: median × (1 - expected_loss)
        - 不確実性幅: リスクが高いほど下方向に拡大

        Args:
            baseline_forecast: {"median": [...], "p10": [...], "p90": [...], ...}
            expected_loss: 期待損失率 (0.0〜0.90)
            country: 国コード（ロギング用）

        Returns:
            調整済み予測辞書
        """
        if expected_loss <= 0.0:
            return baseline_forecast

        loss_factor = 1.0 - expected_loss

        result = dict(baseline_forecast)

        # 中央値の調整
        if "median" in result:
            result["median"] = [
                round(v * loss_factor, 1) for v in result["median"]
            ]

        # P25/P75の調整（中央値と同じ比率）
        for key in ("p25", "p75"):
            if key in result:
                result[key] = [
                    round(v * loss_factor, 1) for v in result[key]
                ]

        # P10: リスク高→下方向に更に広がる
        # 追加の下方拡大 = expected_loss × 0.5
        if "p10" in result:
            lower_stretch = 1.0 + expected_loss * 0.5
            result["p10"] = [
                round(v * loss_factor / lower_stretch, 1) for v in result["p10"]
            ]

        # P90: リスク高→上方も若干縮小
        if "p90" in result:
            upper_shrink = 1.0 + expected_loss * 0.2
            result["p90"] = [
                round(v * loss_factor * upper_shrink, 1) for v in result["p90"]
            ]

        # メタ情報
        result["risk_adjustment"] = {
            "country": country,
            "expected_loss": round(expected_loss, 6),
            "loss_factor": round(loss_factor, 4),
        }

        logger.info(
            "%s: リスク調整適用 expected_loss=%.4f, loss_factor=%.4f",
            country, expected_loss, loss_factor,
        )

        return result
