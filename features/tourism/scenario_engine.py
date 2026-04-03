"""3シナリオ同時計算エンジン — SCRI v1.5.0
============================================================
マクロ経済・地政学ドライバーが訪日観光需要に与える影響を
国別に定量評価する。常に base / optimistic / pessimistic の
3シナリオを同時計算して返す。

弾性値:
  FX_ELASTICITY  = 国別（bilateral_fx_client由来）
  GDP_ELASTICITY = 1.24（全国共通）
  FLIGHT_ELASTICITY = 0.60
  POLITICAL_COEF = -0.008（ポイント当たり）
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# ── 国別為替弾性値 ──
FX_ELASTICITY: Dict[str, float] = {
    "KR": 0.45,
    "CN": 0.70,
    "TW": 0.50,
    "US": 0.30,
    "AU": 0.35,
    "TH": 0.80,
    "HK": 0.55,
    "SG": 0.40,
    "DE": 0.35,
    "FR": 0.35,
    "GB": 0.30,
    "IN": 0.90,
}

# ── グローバル弾性値 ──
GDP_ELASTICITY = 1.24       # GDP 1%変化 → 需要 1.24%変化
FLIGHT_ELASTICITY = 0.60    # フライト供給 1%変化 → 需要 0.60%変化
POLITICAL_COEF = 0.008      # 政治関係 1pt変化 → 需要 ±0.8%（正=改善、負=悪化）

# ── 国別ベースライン訪問者数（2024年実績・千人） ──
BASE_VISITORS_2024: Dict[str, int] = {
    "KR": 8600,
    "CN": 5200,
    "TW": 4800,
    "US": 3600,
    "HK": 1310,
    "AU": 620,
    "TH": 420,
    "SG": 380,
    "DE": 280,
    "FR": 250,
    "GB": 350,
    "IN": 310,
}

# ── 3シナリオ定義 ──
# 各ドライバーの値を定義。0 = 変化なし。
# fx_pct: 円安(+) / 円高(-) の変化率 (%)
# gdp_pct: 各国GDP変化率 (%) — 国コード→値のdict
# flight_pct: フライト供給変化率 (%) — 国コード→値のdict
# political_pts: 政治関係変化 (pt) — 国コード→値のdict（正=改善、負=悪化）
THREE_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "base": {
        "label": "ベース",
        "color": "#4a9eff",
        "description": "現状維持。為替・経済・地政学に大きな変化なし",
        "fx_pct": 0.0,
        "gdp_pct": {},
        "flight_pct": {},
        "political_pts": {},
    },
    "optimistic": {
        "label": "楽観",
        "color": "#51cf66",
        "description": "円安12-15%、中国GDP+1.5%、フライト増便10-18%、日中関係+5pt改善",
        "fx_pct": 13.5,  # 円安12-15%の中央値
        "gdp_pct": {
            "CN": 1.5,
        },
        "flight_pct": {
            "KR": 18.0,
            "CN": 15.0,
            "TW": 14.0,
            "TH": 12.0,
            "HK": 10.0,
            "SG": 10.0,
        },
        "political_pts": {
            "CN": 5.0,   # 日中関係+5pt改善
        },
    },
    "pessimistic": {
        "label": "悲観",
        "color": "#ff4d4d",
        "description": "円高5-10%、中国GDP-2.5%、米国GDP-1.5%、日中関係-30pt、台湾-15pt、フライト減5-15%",
        "fx_pct": -7.5,  # 円高5-10%の中央値
        "gdp_pct": {
            "CN": -2.5,
            "US": -1.5,
        },
        "flight_pct": {
            "KR": -5.0,
            "CN": -15.0,
            "TW": -10.0,
            "TH": -8.0,
            "HK": -12.0,
            "SG": -5.0,
        },
        "political_pts": {
            "CN": -30.0,  # 日中関係-30pt
            "TW": -15.0,  # 台湾海峡-15pt
        },
    },
}


class ScenarioEngine:
    """3シナリオ同時計算エンジン

    2つのメソッドのみ:
    - calculate_all_three(base_visitors) → dict（3シナリオ同時計算）
    - apply_to_forecast(monthly_baseline, country) → dict（月別予測に乗数適用）
    """

    def calculate_all_three(
        self,
        base_visitors: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """3シナリオを同時計算し、国別影響を返す

        Args:
            base_visitors: 国別ベースライン(千人)。省略時は2024年実績使用

        Returns:
            {
                "base": {"label":..., "total_change_pct":0, "country_impacts":{...}},
                "optimistic": {"label":..., "total_change_pct":+X, "country_impacts":{...}},
                "pessimistic": {"label":..., "total_change_pct":-X, "country_impacts":{...}},
            }
        """
        visitors = base_visitors or BASE_VISITORS_2024
        results = {}

        for scenario_name, scenario_def in THREE_SCENARIOS.items():
            fx_pct = scenario_def["fx_pct"]
            gdp_map = scenario_def["gdp_pct"]
            flight_map = scenario_def["flight_pct"]
            political_map = scenario_def["political_pts"]

            country_impacts = {}
            total_base = 0
            total_scenario = 0.0

            for cc, base_k in visitors.items():
                # 1. 為替チャネル: fx_pct * FX_ELASTICITY[cc]
                elasticity = FX_ELASTICITY.get(cc, 0.50)
                fx_effect = fx_pct * elasticity  # %

                # 2. GDP効果: gdp_change * GDP_ELASTICITY
                gdp_change = gdp_map.get(cc, 0.0)
                gdp_effect = gdp_change * GDP_ELASTICITY  # %

                # 3. フライト供給効果: flight_change * FLIGHT_ELASTICITY
                flight_change = flight_map.get(cc, 0.0)
                flight_effect = flight_change * FLIGHT_ELASTICITY  # %

                # 4. 政治関係効果: political_pts(正=改善、負=悪化) * POLITICAL_COEF * 100
                political_pts = political_map.get(cc, 0.0)
                political_effect = political_pts * POLITICAL_COEF * 100  # %  e.g. -30pt * 0.008 * 100 = -24%

                # 合計需要変化率(%)
                total_change = fx_effect + gdp_effect + flight_effect + political_effect

                # シナリオ後訪問者数
                scenario_k = base_k * (1.0 + total_change / 100.0)
                scenario_k = max(0, scenario_k)

                total_base += base_k
                total_scenario += scenario_k

                # 内訳
                breakdown = {}
                if abs(fx_effect) > 0.01:
                    breakdown["fx"] = round(fx_effect, 1)
                if abs(gdp_effect) > 0.01:
                    breakdown["gdp"] = round(gdp_effect, 1)
                if abs(flight_effect) > 0.01:
                    breakdown["flight"] = round(flight_effect, 1)
                if abs(political_effect) > 0.01:
                    breakdown["political"] = round(political_effect, 1)

                direction = "UP" if total_change > 0.5 else "DOWN" if total_change < -0.5 else "FLAT"

                country_impacts[cc] = {
                    "change_pct": round(total_change, 1),
                    "direction": direction,
                    "breakdown": breakdown,
                    "base_k": base_k,
                    "scenario_k": round(scenario_k, 1),
                }

            # 全体の変化率
            overall_change_pct = (
                (total_scenario - total_base) / total_base * 100.0
                if total_base > 0 else 0.0
            )

            up_markets = [cc for cc, imp in country_impacts.items() if imp["change_pct"] > 0.5]
            down_markets = [cc for cc, imp in country_impacts.items() if imp["change_pct"] < -0.5]

            results[scenario_name] = {
                "label": scenario_def["label"],
                "color": scenario_def["color"],
                "description": scenario_def["description"],
                "total_change_pct": round(overall_change_pct, 1),
                "country_impacts": country_impacts,
                "up_markets": up_markets,
                "down_markets": down_markets,
            }

        return results

    def apply_to_forecast(
        self,
        monthly_baseline: list,
        country: str = "ALL",
    ) -> Dict[str, Any]:
        """月別ベースライン予測に3シナリオの乗数を適用

        Args:
            monthly_baseline: 月別の予測値リスト（千人）
            country: 対象国コード。"ALL"なら全市場加重平均

        Returns:
            {
                "base": {"multiplier": 1.0, "values": [...]},
                "optimistic": {"multiplier": X, "values": [...]},
                "pessimistic": {"multiplier": X, "values": [...]},
            }
        """
        all_three = self.calculate_all_three()
        result = {}

        for scenario_name, scenario_data in all_three.items():
            if country == "ALL":
                # 全体の変化率を使用
                change_pct = scenario_data["total_change_pct"]
            else:
                # 国別の変化率
                impact = scenario_data["country_impacts"].get(country, {})
                change_pct = impact.get("change_pct", 0.0)

            multiplier = 1.0 + change_pct / 100.0
            values = [round(v * multiplier) for v in monthly_baseline]

            result[scenario_name] = {
                "multiplier": round(multiplier, 4),
                "change_pct": round(change_pct, 1),
                "values": values,
            }

        return result
