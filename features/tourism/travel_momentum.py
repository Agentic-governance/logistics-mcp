"""
旅行モメンタム指数 (TMI: Travel Momentum Index)
=================================================
SCRI v1.4.0 TASK 1-B

TMI = w1*delta_outbound + w2*leave_util + w3*leisure_share
    + w4*delta_restaurant + w5*(1-domestic) + w6*remote_work

各成分を [0,1] にスケールし、加重平均で算出。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ===========================================================================
# 初期重み
# ===========================================================================
DEFAULT_WEIGHTS = {
    "delta_outbound": 0.30,
    "leave_utilization": 0.20,
    "leisure_share": 0.15,
    "delta_restaurant": 0.15,
    "non_domestic": 0.10,       # 1 - domestic_ratio
    "remote_work": 0.10,
}


# ===========================================================================
# 国別ハードコードフォールバックデータ
# ===========================================================================

# delta_outbound: アウトバウンド伸び率の正規化値 (0-1)
# 2019=ベースライン、2020-2022=コロナ低下、2023-24=回復
_FALLBACK_DELTA_OUTBOUND: Dict[str, Dict[int, float]] = {
    "KR": {2015: 0.50, 2016: 0.60, 2017: 0.72, 2018: 0.78, 2019: 0.80,
            2020: 0.10, 2021: 0.08, 2022: 0.35, 2023: 0.72, 2024: 0.80},
    "CN": {2015: 0.45, 2016: 0.55, 2017: 0.62, 2018: 0.70, 2019: 0.75,
            2020: 0.05, 2021: 0.05, 2022: 0.08, 2023: 0.40, 2024: 0.60},
    "TW": {2015: 0.55, 2016: 0.62, 2017: 0.70, 2018: 0.75, 2019: 0.80,
            2020: 0.08, 2021: 0.05, 2022: 0.25, 2023: 0.70, 2024: 0.78},
    "US": {2015: 0.55, 2016: 0.60, 2017: 0.65, 2018: 0.70, 2019: 0.72,
            2020: 0.12, 2021: 0.20, 2022: 0.45, 2023: 0.65, 2024: 0.72},
    "AU": {2015: 0.52, 2016: 0.58, 2017: 0.63, 2018: 0.68, 2019: 0.72,
            2020: 0.06, 2021: 0.05, 2022: 0.30, 2023: 0.62, 2024: 0.70},
    "TH": {2015: 0.40, 2016: 0.45, 2017: 0.52, 2018: 0.58, 2019: 0.62,
            2020: 0.05, 2021: 0.03, 2022: 0.18, 2023: 0.50, 2024: 0.58},
    "HK": {2015: 0.75, 2016: 0.72, 2017: 0.78, 2018: 0.80, 2019: 0.70,
            2020: 0.10, 2021: 0.08, 2022: 0.35, 2023: 0.65, 2024: 0.72},
    "SG": {2015: 0.78, 2016: 0.80, 2017: 0.82, 2018: 0.85, 2019: 0.85,
            2020: 0.12, 2021: 0.10, 2022: 0.40, 2023: 0.75, 2024: 0.82},
    "DE": {2015: 0.68, 2016: 0.72, 2017: 0.75, 2018: 0.78, 2019: 0.80,
            2020: 0.15, 2021: 0.22, 2022: 0.50, 2023: 0.72, 2024: 0.78},
    "FR": {2015: 0.42, 2016: 0.45, 2017: 0.48, 2018: 0.52, 2019: 0.55,
            2020: 0.08, 2021: 0.12, 2022: 0.30, 2023: 0.48, 2024: 0.52},
    "GB": {2015: 0.72, 2016: 0.75, 2017: 0.78, 2018: 0.80, 2019: 0.82,
            2020: 0.10, 2021: 0.15, 2022: 0.42, 2023: 0.72, 2024: 0.78},
}

# leave_utilization: 有給消化率 (0-1)
_FALLBACK_LEAVE_UTIL: Dict[str, float] = {
    "KR": 0.68, "CN": 0.60, "TW": 0.70, "US": 0.55, "AU": 0.80,
    "TH": 0.65, "HK": 0.72, "SG": 0.75, "DE": 0.90, "FR": 0.92, "GB": 0.82,
}

# leisure_share: 余暇目的の割合 (0-1)
_FALLBACK_LEISURE_SHARE: Dict[str, float] = {
    "KR": 0.82, "CN": 0.78, "TW": 0.85, "US": 0.65, "AU": 0.72,
    "TH": 0.80, "HK": 0.80, "SG": 0.70, "DE": 0.75, "FR": 0.78, "GB": 0.70,
}

# delta_restaurant: 日本食レストラン伸び率の正規化値 (0-1)
_FALLBACK_DELTA_RESTAURANT: Dict[str, Dict[int, float]] = {
    "KR": {2019: 0.50, 2020: 0.45, 2021: 0.48, 2022: 0.55, 2023: 0.62, 2024: 0.68},
    "CN": {2019: 0.55, 2020: 0.48, 2021: 0.52, 2022: 0.60, 2023: 0.70, 2024: 0.78},
    "TW": {2019: 0.50, 2020: 0.48, 2021: 0.50, 2022: 0.55, 2023: 0.62, 2024: 0.68},
    "US": {2019: 0.50, 2020: 0.42, 2021: 0.45, 2022: 0.52, 2023: 0.60, 2024: 0.68},
    "AU": {2019: 0.50, 2020: 0.45, 2021: 0.48, 2022: 0.55, 2023: 0.62, 2024: 0.70},
    "TH": {2019: 0.55, 2020: 0.48, 2021: 0.52, 2022: 0.60, 2023: 0.70, 2024: 0.80},
    "HK": {2019: 0.50, 2020: 0.42, 2021: 0.45, 2022: 0.48, 2023: 0.55, 2024: 0.60},
    "SG": {2019: 0.50, 2020: 0.45, 2021: 0.48, 2022: 0.55, 2023: 0.62, 2024: 0.72},
    "DE": {2019: 0.50, 2020: 0.40, 2021: 0.42, 2022: 0.50, 2023: 0.58, 2024: 0.65},
    "FR": {2019: 0.50, 2020: 0.38, 2021: 0.42, 2022: 0.48, 2023: 0.55, 2024: 0.62},
    "GB": {2019: 0.50, 2020: 0.40, 2021: 0.42, 2022: 0.52, 2023: 0.60, 2024: 0.68},
}

# non_domestic: 1 - 国内旅行比率 (海外志向度)
_FALLBACK_NON_DOMESTIC: Dict[str, float] = {
    "KR": 0.45, "CN": 0.15, "TW": 0.55, "US": 0.25, "AU": 0.40,
    "TH": 0.20, "HK": 0.70, "SG": 0.75, "DE": 0.65, "FR": 0.35, "GB": 0.60,
}

# remote_work: リモートワーク普及率 (0-1)
_FALLBACK_REMOTE_WORK: Dict[str, Dict[int, float]] = {
    "KR": {2019: 0.05, 2020: 0.25, 2021: 0.28, 2022: 0.22, 2023: 0.20, 2024: 0.18},
    "CN": {2019: 0.03, 2020: 0.20, 2021: 0.18, 2022: 0.15, 2023: 0.12, 2024: 0.10},
    "TW": {2019: 0.04, 2020: 0.22, 2021: 0.25, 2022: 0.20, 2023: 0.18, 2024: 0.16},
    "US": {2019: 0.06, 2020: 0.42, 2021: 0.38, 2022: 0.32, 2023: 0.28, 2024: 0.26},
    "AU": {2019: 0.05, 2020: 0.40, 2021: 0.35, 2022: 0.30, 2023: 0.28, 2024: 0.25},
    "TH": {2019: 0.02, 2020: 0.15, 2021: 0.12, 2022: 0.10, 2023: 0.08, 2024: 0.07},
    "HK": {2019: 0.05, 2020: 0.30, 2021: 0.28, 2022: 0.22, 2023: 0.18, 2024: 0.15},
    "SG": {2019: 0.06, 2020: 0.45, 2021: 0.40, 2022: 0.35, 2023: 0.30, 2024: 0.28},
    "DE": {2019: 0.05, 2020: 0.35, 2021: 0.32, 2022: 0.28, 2023: 0.25, 2024: 0.24},
    "FR": {2019: 0.04, 2020: 0.32, 2021: 0.30, 2022: 0.25, 2023: 0.22, 2024: 0.20},
    "GB": {2019: 0.06, 2020: 0.42, 2021: 0.38, 2022: 0.32, 2023: 0.28, 2024: 0.26},
}

# 国別の典型的TMI値（ハードコードフォールバック）
_TYPICAL_TMI: Dict[str, Dict[int, float]] = {
    "KR": {2015: 0.55, 2016: 0.60, 2017: 0.68, 2018: 0.72, 2019: 0.75,
            2020: 0.18, 2021: 0.15, 2022: 0.38, 2023: 0.65, 2024: 0.72},
    "CN": {2015: 0.40, 2016: 0.48, 2017: 0.55, 2018: 0.62, 2019: 0.65,
            2020: 0.10, 2021: 0.08, 2022: 0.12, 2023: 0.42, 2024: 0.58},
    "TW": {2015: 0.52, 2016: 0.58, 2017: 0.65, 2018: 0.70, 2019: 0.75,
            2020: 0.12, 2021: 0.10, 2022: 0.28, 2023: 0.62, 2024: 0.72},
    "US": {2015: 0.48, 2016: 0.52, 2017: 0.58, 2018: 0.62, 2019: 0.65,
            2020: 0.15, 2021: 0.22, 2022: 0.42, 2023: 0.58, 2024: 0.65},
    "AU": {2015: 0.50, 2016: 0.55, 2017: 0.60, 2018: 0.65, 2019: 0.68,
            2020: 0.12, 2021: 0.10, 2022: 0.35, 2023: 0.58, 2024: 0.65},
    "TH": {2015: 0.38, 2016: 0.42, 2017: 0.48, 2018: 0.55, 2019: 0.58,
            2020: 0.08, 2021: 0.06, 2022: 0.20, 2023: 0.48, 2024: 0.55},
    "HK": {2015: 0.65, 2016: 0.62, 2017: 0.68, 2018: 0.72, 2019: 0.68,
            2020: 0.15, 2021: 0.12, 2022: 0.38, 2023: 0.60, 2024: 0.68},
    "SG": {2015: 0.68, 2016: 0.70, 2017: 0.72, 2018: 0.75, 2019: 0.78,
            2020: 0.18, 2021: 0.15, 2022: 0.42, 2023: 0.68, 2024: 0.75},
    "DE": {2015: 0.60, 2016: 0.65, 2017: 0.68, 2018: 0.72, 2019: 0.75,
            2020: 0.20, 2021: 0.25, 2022: 0.48, 2023: 0.65, 2024: 0.72},
    "FR": {2015: 0.40, 2016: 0.42, 2017: 0.45, 2018: 0.50, 2019: 0.52,
            2020: 0.12, 2021: 0.15, 2022: 0.30, 2023: 0.45, 2024: 0.50},
    "GB": {2015: 0.62, 2016: 0.65, 2017: 0.68, 2018: 0.72, 2019: 0.75,
            2020: 0.15, 2021: 0.18, 2022: 0.42, 2023: 0.65, 2024: 0.72},
}


# ===========================================================================
# TravelMomentumIndex
# ===========================================================================
@dataclass
class TMIComponents:
    """TMI の各成分値"""
    delta_outbound: float
    leave_utilization: float
    leisure_share: float
    delta_restaurant: float
    non_domestic: float
    remote_work: float
    tmi: float


class TravelMomentumIndex:
    """
    旅行モメンタム指数 (TMI) を算出する。

    TMI = w1*delta_outbound + w2*leave_util + w3*leisure_share
        + w4*delta_restaurant + w5*(1-domestic) + w6*remote_work

    全成分は [0, 1] にスケールされ、加重平均も [0, 1] 範囲。
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        # 重み合計を1.0に正規化
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    # -----------------------------------------------------------------------
    # calculate — メインエントリ
    # -----------------------------------------------------------------------
    def calculate(
        self,
        country: str,
        year_month: str,
        components: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        TMI を算出する。

        Args:
            country: ISO2国コード
            year_month: "YYYY-MM" 形式
            components: 外部から成分値を渡す場合の辞書

        Returns:
            float: TMI値 [0, 1]
        """
        if components is not None:
            return self._weighted_sum(components)

        # ハードコードフォールバックから成分を取得
        try:
            year = int(year_month.split("-")[0])
        except (ValueError, IndexError):
            year = 2024

        comp = self._get_fallback_components(country, year)
        tmi = self._weighted_sum({
            "delta_outbound": comp.delta_outbound,
            "leave_utilization": comp.leave_utilization,
            "leisure_share": comp.leisure_share,
            "delta_restaurant": comp.delta_restaurant,
            "non_domestic": comp.non_domestic,
            "remote_work": comp.remote_work,
        })
        return tmi

    # -----------------------------------------------------------------------
    # calculate_with_details — 成分詳細付き
    # -----------------------------------------------------------------------
    def calculate_with_details(
        self,
        country: str,
        year_month: str,
    ) -> TMIComponents:
        """TMI と各成分を返す。"""
        try:
            year = int(year_month.split("-")[0])
        except (ValueError, IndexError):
            year = 2024

        comp = self._get_fallback_components(country, year)
        tmi = self._weighted_sum({
            "delta_outbound": comp.delta_outbound,
            "leave_utilization": comp.leave_utilization,
            "leisure_share": comp.leisure_share,
            "delta_restaurant": comp.delta_restaurant,
            "non_domestic": comp.non_domestic,
            "remote_work": comp.remote_work,
        })
        comp.tmi = tmi
        return comp

    # -----------------------------------------------------------------------
    # get_typical_tmi — ハードコードの典型的TMI
    # -----------------------------------------------------------------------
    def get_typical_tmi(self, country: str, year: int) -> float:
        """国別・年別の典型的TMI値を返す。"""
        country_data = _TYPICAL_TMI.get(country, {})
        if year in country_data:
            return country_data[year]
        # 最近年のフォールバック
        if country_data:
            closest = min(country_data.keys(), key=lambda y: abs(y - year))
            return country_data[closest]
        return 0.5  # デフォルト

    # -----------------------------------------------------------------------
    # 内部メソッド
    # -----------------------------------------------------------------------
    def _weighted_sum(self, components: Dict[str, float]) -> float:
        """加重平均を計算し [0, 1] にクリップ。"""
        tmi = 0.0
        for key, weight in self.weights.items():
            val = components.get(key, 0.5)
            tmi += weight * np.clip(val, 0.0, 1.0)
        return float(np.clip(tmi, 0.0, 1.0))

    def _get_fallback_components(self, country: str, year: int) -> TMIComponents:
        """ハードコードデータから成分値を取得。"""
        # delta_outbound
        do_data = _FALLBACK_DELTA_OUTBOUND.get(country, {})
        delta_outbound = do_data.get(year, 0.5)
        if not do_data and year not in do_data:
            delta_outbound = 0.5

        # leave_utilization (時系列変動なし、国定数)
        leave_util = _FALLBACK_LEAVE_UTIL.get(country, 0.65)

        # leisure_share (国定数)
        leisure_share = _FALLBACK_LEISURE_SHARE.get(country, 0.70)

        # delta_restaurant
        dr_data = _FALLBACK_DELTA_RESTAURANT.get(country, {})
        delta_restaurant = dr_data.get(year, 0.50)
        if not dr_data:
            delta_restaurant = 0.50

        # non_domestic
        non_domestic = _FALLBACK_NON_DOMESTIC.get(country, 0.40)

        # remote_work
        rw_data = _FALLBACK_REMOTE_WORK.get(country, {})
        remote_work = rw_data.get(year, 0.15)
        if not rw_data:
            remote_work = 0.15

        return TMIComponents(
            delta_outbound=delta_outbound,
            leave_utilization=leave_util,
            leisure_share=leisure_share,
            delta_restaurant=delta_restaurant,
            non_domestic=non_domestic,
            remote_work=remote_work,
            tmi=0.0,  # 後で計算
        )
