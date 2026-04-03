"""国別シナリオエンジン — SCRI v1.5.0
============================================================
マクロ経済・地政学シナリオが訪日観光需要に与える影響を
国別に定量評価する。BilateralFXClient と連携して
為替チャネル経由の需要変動も統合。

7+αシナリオ:
  base, jpy_weak_10, china_stimulus, flight_expansion,
  jpy_strong_10, japan_china_tension, us_recession,
  taiwan_strait_risk, stagflation_mixed
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ── BilateralFXClient（遅延インポート） ──
_fx_client = None


def _get_fx_client():
    global _fx_client
    if _fx_client is None:
        try:
            from pipeline.tourism.bilateral_fx_client import BilateralFXClient
            _fx_client = BilateralFXClient()
        except (ImportError, Exception) as e:
            logger.warning("BilateralFXClient インポート失敗: %s", e)
    return _fx_client


# ── 国別ベースライン訪問者数（2024年実績・千人） ──
BASE_VISITORS_2024: Dict[str, int] = {
    "KR": 8600,   # 韓国
    "CN": 5200,   # 中国
    "TW": 4800,   # 台湾
    "US": 3600,   # 米国
    "HK": 1310,   # 香港
    "AU": 620,    # 豪州
    "TH": 420,    # タイ
    "SG": 380,    # シンガポール
    "DE": 280,    # ドイツ
    "FR": 250,    # フランス
    "GB": 350,    # 英国
    "IN": 310,    # インド
}

# ── シナリオ定義 ──
# 各シナリオは country_impacts (国コード→需要変化率%), fx_shock (円変化率%),
# その他のグローバルファクターを定義
SCENARIOS: Dict[str, Dict[str, Any]] = {
    "base": {
        "label": "ベースケース",
        "description": "現状維持。為替・地政学リスクに大きな変化なし",
        "fx_shock_pct": 0.0,
        "country_overrides": {},  # 国ごとの追加需要変化率(%)
        "global_demand_shift_pct": 0.0,
    },
    "jpy_weak_10": {
        "label": "円安10%シナリオ",
        "description": "日銀YCC再修正で円が対主要通貨10%下落。外国人観光客にとって日本が割安に",
        "fx_shock_pct": 10.0,
        "country_overrides": {},
        "global_demand_shift_pct": 0.0,
    },
    "jpy_strong_10": {
        "label": "円高10%シナリオ",
        "description": "FRB利下げ＋日銀利上げで円が10%上昇。訪日コスト増",
        "fx_shock_pct": -10.0,
        "country_overrides": {},
        "global_demand_shift_pct": 0.0,
    },
    "china_stimulus": {
        "label": "中国景気刺激策",
        "description": "中国政府が大規模財政出動。個人消費回復で海外旅行需要が急増",
        "fx_shock_pct": 0.0,
        "country_overrides": {
            "CN": 25.0,   # 中国から訪日 +25%
            "HK": 10.0,   # 香港も連動 +10%
            "TW": 3.0,    # 台湾は軽微
        },
        "global_demand_shift_pct": 2.0,  # 全体にも波及
    },
    "flight_expansion": {
        "label": "航空便拡大",
        "description": "日本の地方空港を含むLCC路線増便。アジア近距離路線が大幅増",
        "fx_shock_pct": 0.0,
        "country_overrides": {
            "KR": 15.0,   # 韓国: LCC恩恵大
            "TW": 12.0,   # 台湾: 地方路線増
            "CN": 8.0,    # 中国: 団体便増
            "TH": 10.0,   # タイ: LCC増便
            "SG": 6.0,    # シンガポール
            "HK": 8.0,    # 香港
        },
        "global_demand_shift_pct": 3.0,
    },
    "japan_china_tension": {
        "label": "日中関係悪化",
        "description": "尖閣諸島問題や歴史問題で日中関係が急速に悪化。中国政府が日本渡航自粛を示唆",
        "fx_shock_pct": 2.0,  # 円やや安（リスクオフ）
        "country_overrides": {
            "CN": -40.0,   # 中国: 大幅減少
            "HK": -15.0,   # 香港: 連動だが軽微
            "TW": 5.0,     # 台湾: 代替需要
            "KR": 3.0,     # 韓国: 代替需要
            "US": 2.0,     # 米国: ほぼ無影響
        },
        "global_demand_shift_pct": -2.0,
    },
    "us_recession": {
        "label": "米国景気後退",
        "description": "米国がリセッション入り。世界的な消費マインド悪化",
        "fx_shock_pct": -5.0,  # ドル安＝円高
        "country_overrides": {
            "US": -20.0,   # 米国: 所得減で大幅減
            "AU": -8.0,    # 豪州: 資源国連動
            "GB": -5.0,    # 英国: 連動
            "DE": -5.0,    # ドイツ: 世界景気連動
            "FR": -5.0,    # フランス
            "CN": -3.0,    # 中国: 輸出減だが内需型に移行中
            "KR": -5.0,    # 韓国: 輸出依存
        },
        "global_demand_shift_pct": -5.0,
    },
    "taiwan_strait_risk": {
        "label": "台湾海峡リスク",
        "description": "台湾海峡での軍事緊張が高まり。東アジア全域で渡航リスク意識が上昇",
        "fx_shock_pct": 3.0,  # 円安（リスクオフ・円は安全通貨だが地域リスク）
        "country_overrides": {
            "TW": -50.0,   # 台湾: 直接影響で大幅減
            "CN": -30.0,   # 中国: 緊張の当事者
            "HK": -20.0,   # 香港: 地域リスク
            "KR": -10.0,   # 韓国: 近隣リスク意識
            "US": -5.0,    # 米国: 東アジア渡航警戒
        },
        "global_demand_shift_pct": -8.0,
    },
    "stagflation_mixed": {
        "label": "スタグフレーション混合",
        "description": "世界的なスタグフレーション。米国インフレ再燃で旅行需要減、一方で円安が日本を割安に",
        "fx_shock_pct": 8.0,  # 円安8%
        "country_overrides": {
            "US": -15.0,    # 米国: インフレで消費抑制
            "CN": 5.0,      # 中国: 相対的に安定
            "KR": -3.0,     # 韓国: 物価高
            "AU": -5.0,     # 豪州: 物価高
            "IN": -8.0,     # インド: 物価高
            "DE": -7.0,     # ドイツ: エネルギー高
            "FR": -6.0,     # フランス
            "GB": -8.0,     # 英国
        },
        "global_demand_shift_pct": -3.0,
    },
}


@dataclass
class CountryScenarioImpact:
    """国別シナリオ影響"""
    country_code: str
    scenario_name: str
    fx_demand_change_pct: float       # 為替チャネル経由の需要変化(%)
    override_demand_change_pct: float  # シナリオ固有の国別変化(%)
    global_demand_shift_pct: float     # グローバル需要シフト(%)
    total_demand_change_pct: float     # 合計需要変化(%)
    base_visitors_k: int              # ベースライン訪問者(千人)
    scenario_visitors_k: float        # シナリオ後訪問者(千人)
    explanation: str


class ScenarioEngine:
    """国別シナリオ影響計算エンジン

    各シナリオについて:
    1. 為替ショック → BilateralFXClient経由で国別需要変化を計算
    2. シナリオ固有の国別オーバーライドを加算
    3. グローバル需要シフトを加算
    4. 合計需要変化率 → シナリオ後訪問者数を算出
    """

    def __init__(self):
        self._fx_client = _get_fx_client()

    def list_scenarios(self) -> List[Dict[str, str]]:
        """利用可能シナリオ一覧"""
        return [
            {
                "name": name,
                "label": s["label"],
                "description": s["description"],
            }
            for name, s in SCENARIOS.items()
        ]

    def calculate_country_impacts(
        self, scenario_name: str
    ) -> Dict[str, CountryScenarioImpact]:
        """指定シナリオの国別影響を計算

        Returns:
            dict[str, CountryScenarioImpact]: 国コード → 影響
        """
        if scenario_name not in SCENARIOS:
            raise ValueError(
                f"未定義シナリオ: {scenario_name}. "
                f"利用可能: {list(SCENARIOS.keys())}"
            )

        scenario = SCENARIOS[scenario_name]
        fx_shock_pct = scenario["fx_shock_pct"]
        overrides = scenario["country_overrides"]
        global_shift = scenario["global_demand_shift_pct"]

        results: Dict[str, CountryScenarioImpact] = {}

        for cc, base_k in BASE_VISITORS_2024.items():
            # 1. 為替チャネル
            fx_demand = 0.0
            if abs(fx_shock_pct) > 0.01 and self._fx_client is not None:
                try:
                    shock = self._fx_client.calculate_fx_shock(
                        cc, fx_shock_pct,
                        current_rate=None,  # API/フォールバック自動
                    )
                    fx_demand = shock.demand_change_pct
                except Exception as e:
                    logger.warning("FXショック計算失敗 %s: %s", cc, e)
                    # フォールバック: 弾性値0.5 × ショック率
                    fx_demand = fx_shock_pct * 0.5
            elif abs(fx_shock_pct) > 0.01:
                # FXクライアントなし → 弾性値0.5で概算
                from pipeline.tourism.bilateral_fx_client import FX_ELASTICITY
                elasticity = FX_ELASTICITY.get(cc, 0.5)
                fx_demand = fx_shock_pct * elasticity

            # 2. シナリオ固有の国別オーバーライド
            override = overrides.get(cc, 0.0)

            # 3. グローバル需要シフト
            # 4. 合計
            total = fx_demand + override + global_shift

            # シナリオ後訪問者数
            scenario_k = base_k * (1.0 + total / 100.0)
            scenario_k = max(0, scenario_k)  # 負にはならない

            # 説明文
            parts = []
            if abs(fx_demand) > 0.01:
                parts.append(f"為替{fx_demand:+.1f}%")
            if abs(override) > 0.01:
                parts.append(f"固有{override:+.1f}%")
            if abs(global_shift) > 0.01:
                parts.append(f"全体{global_shift:+.1f}%")
            explanation = " + ".join(parts) if parts else "変化なし"

            results[cc] = CountryScenarioImpact(
                country_code=cc,
                scenario_name=scenario_name,
                fx_demand_change_pct=round(fx_demand, 2),
                override_demand_change_pct=override,
                global_demand_shift_pct=global_shift,
                total_demand_change_pct=round(total, 2),
                base_visitors_k=base_k,
                scenario_visitors_k=round(scenario_k, 1),
                explanation=explanation,
            )

        return results

    def calculate_japan_total_impact(
        self,
        scenario_name: str,
        base_visitors: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """シナリオの日本全体への影響サマリー

        Args:
            scenario_name: シナリオ名
            base_visitors: 国別ベースライン(千人)。省略時は2024年実績使用

        Returns:
            dict: 日本全体のサマリー
        """
        impacts = self.calculate_country_impacts(scenario_name)
        scenario = SCENARIOS[scenario_name]

        total_base = 0
        total_scenario = 0.0
        country_details = []

        for cc, impact in sorted(impacts.items(), key=lambda x: -x[1].base_visitors_k):
            total_base += impact.base_visitors_k
            total_scenario += impact.scenario_visitors_k
            country_details.append({
                "country": cc,
                "base_k": impact.base_visitors_k,
                "scenario_k": impact.scenario_visitors_k,
                "change_pct": impact.total_demand_change_pct,
                "explanation": impact.explanation,
            })

        total_change_pct = (
            (total_scenario - total_base) / total_base * 100.0
            if total_base > 0 else 0.0
        )

        diversification = self._explain_diversification(impacts)

        # by_country 辞書（country_impacts のインデックス版）
        by_country = {
            d["country"]: d for d in country_details
        }

        # up / down マーケット分類
        up_markets = [d["country"] for d in country_details if d["change_pct"] > 0]
        down_markets = [d["country"] for d in country_details if d["change_pct"] < 0]

        return {
            "scenario": scenario_name,
            "label": scenario["label"],
            "description": scenario["description"],
            "total_base_visitors_k": total_base,
            "total_scenario_visitors_k": round(total_scenario, 1),
            "total_change_pct": round(total_change_pct, 2),
            "country_impacts": country_details,
            "by_country": by_country,
            "up_markets": up_markets,
            "down_markets": down_markets,
            "diversification_note": diversification,
        }

    def _explain_diversification(
        self, impacts: Dict[str, CountryScenarioImpact]
    ) -> str:
        """市場集中リスクの説明"""
        if not impacts:
            return "データなし"

        total_base = sum(i.base_visitors_k for i in impacts.values())
        if total_base == 0:
            return "ベースライン訪問者ゼロ"

        # HHI (ハーシュマン・ハーフィンダル指数)
        hhi = sum(
            (i.base_visitors_k / total_base * 100) ** 2
            for i in impacts.values()
        )

        # 最大シェア国
        top = max(impacts.values(), key=lambda i: i.base_visitors_k)
        top_share = top.base_visitors_k / total_base * 100

        # 最大ダメージ国
        worst = min(impacts.values(), key=lambda i: i.total_demand_change_pct)

        if hhi > 2000:
            concentration = "高集中"
        elif hhi > 1500:
            concentration = "中集中"
        else:
            concentration = "分散的"

        return (
            f"市場集中度: HHI={hhi:.0f}({concentration})。"
            f"最大市場={top.country_code}(シェア{top_share:.1f}%)。"
            f"最大影響={worst.country_code}"
            f"({worst.total_demand_change_pct:+.1f}%)"
        )
