"""
観光需要の重力モデル (Gravity Model of Tourism Demand)
=====================================================
SCRI v1.3.0 — ROLE-B

数式:
  log(T_ij) = α + β1·log(GDP_i) + β2·log(GDP_j) + β3·log(DIST_ij)
            + β4·log(EXR_ij) + β5·log(FLIGHT_ij) + β6·VISA_ij
            + β7·BILATERAL_ij + β8·log(T_ij,t-1) + ε

学術文献:
  - Lim (1997) "Review of International Tourism Demand Models"
  - Khadaroo & Seetanah (2007) "Transport Infrastructure and Tourism"
  - Song & Li (2008) "Tourism demand modelling and forecasting"
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数: 首都間大圏距離 (km)
# ---------------------------------------------------------------------------
DISTANCE_TO_JAPAN: Dict[str, int] = {
    "CHN": 2100, "KOR": 1160, "TWN": 2100, "HKG": 2900,
    "USA": 10800, "THA": 4600, "SGP": 5300, "AUS": 7800,
    "PHL": 3000, "MYS": 5300, "VNM": 3600, "IND": 5800,
    "DEU": 9300, "GBR": 9500, "FRA": 9700, "CAN": 10400,
}

# ---------------------------------------------------------------------------
# 定数: ビザ政策 (無査証=True)
# ---------------------------------------------------------------------------
VISA_FREE: Dict[str, bool] = {
    "KOR": True, "TWN": True, "HKG": True, "SGP": True, "THA": True,
    "MYS": True, "USA": True, "AUS": True, "GBR": True, "DEU": True,
    "FRA": True, "CAN": True, "ITA": True,
    "CHN": False, "IND": False, "PHL": False, "VNM": False, "IDN": False,
}

# ---------------------------------------------------------------------------
# 学術文献ベースの事前係数（データ不足時のフォールバック）
# ---------------------------------------------------------------------------
COEFFICIENT_PRIORS: Dict[str, float] = {
    "exchange_rate": 0.85,   # EXRインデックス上昇=円安=訪日有利 → 正
    "flight_supply": 0.60,
    "gdp_source": 1.10,
    "visa_free": 0.35,
    "bilateral": -0.40,
    "distance": -0.80,
    "lagged_visitors": 0.45,
}

# ---------------------------------------------------------------------------
# 日本のGDP（兆USD）— 被説明変数の回帰に使用
# ---------------------------------------------------------------------------
_JAPAN_GDP_TRILLION: Dict[int, float] = {
    2019: 5.08, 2022: 4.23, 2023: 4.21, 2024: 4.07, 2025: 4.30,
}

# ---------------------------------------------------------------------------
# 内蔵サンプルパネルデータ: 主要15カ国 × 5年 (2019, 2022-2025)
# JNTO公開データ + World Bank GDP + 年平均為替レート
# コロナ期間(2020-2021)を除外
# ---------------------------------------------------------------------------
# 各レコード: (country, year, visitors_to_japan[千人], gdp_usd_trillion,
#              exchange_rate_index, flight_index, visa_free, bilateral_score, distance_km)
_SAMPLE_PANEL: List[Dict[str, Any]] = [
    # --- 中国 CHN ---
    {"country": "CHN", "year": 2019, "visitors": 9594, "gdp": 14.28, "exr": 1.00, "flight": 1.00, "visa": 0, "bilateral": 0.45, "dist": 2100},
    {"country": "CHN", "year": 2022, "visitors": 189,  "gdp": 17.96, "exr": 1.03, "flight": 0.12, "visa": 0, "bilateral": 0.38, "dist": 2100},
    {"country": "CHN", "year": 2023, "visitors": 2426, "gdp": 17.79, "exr": 1.05, "flight": 0.55, "visa": 0, "bilateral": 0.35, "dist": 2100},
    {"country": "CHN", "year": 2024, "visitors": 6924, "gdp": 18.27, "exr": 1.08, "flight": 0.78, "visa": 0, "bilateral": 0.37, "dist": 2100},
    {"country": "CHN", "year": 2025, "visitors": 5700, "gdp": 18.80, "exr": 1.06, "flight": 0.82, "visa": 0, "bilateral": 0.36, "dist": 2100},
    # --- 韓国 KOR ---
    {"country": "KOR", "year": 2019, "visitors": 5585, "gdp": 1.65, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.50, "dist": 1160},
    {"country": "KOR", "year": 2022, "visitors": 1013, "gdp": 1.67, "exr": 1.10, "flight": 0.35, "visa": 1, "bilateral": 0.55, "dist": 1160},
    {"country": "KOR", "year": 2023, "visitors": 6958, "gdp": 1.71, "exr": 1.18, "flight": 0.88, "visa": 1, "bilateral": 0.58, "dist": 1160},
    {"country": "KOR", "year": 2024, "visitors": 8818, "gdp": 1.76, "exr": 1.25, "flight": 0.95, "visa": 1, "bilateral": 0.60, "dist": 1160},
    {"country": "KOR", "year": 2025, "visitors": 8200, "gdp": 1.80, "exr": 1.22, "flight": 0.97, "visa": 1, "bilateral": 0.60, "dist": 1160},
    # --- 台湾 TWN ---
    {"country": "TWN", "year": 2019, "visitors": 4891, "gdp": 0.61, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.72, "dist": 2100},
    {"country": "TWN", "year": 2022, "visitors": 332,  "gdp": 0.76, "exr": 1.05, "flight": 0.20, "visa": 1, "bilateral": 0.72, "dist": 2100},
    {"country": "TWN", "year": 2023, "visitors": 4202, "gdp": 0.75, "exr": 1.12, "flight": 0.82, "visa": 1, "bilateral": 0.73, "dist": 2100},
    {"country": "TWN", "year": 2024, "visitors": 5876, "gdp": 0.80, "exr": 1.18, "flight": 0.92, "visa": 1, "bilateral": 0.74, "dist": 2100},
    {"country": "TWN", "year": 2025, "visitors": 5500, "gdp": 0.84, "exr": 1.15, "flight": 0.95, "visa": 1, "bilateral": 0.74, "dist": 2100},
    # --- 香港 HKG ---
    {"country": "HKG", "year": 2019, "visitors": 2291, "gdp": 0.36, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.65, "dist": 2900},
    {"country": "HKG", "year": 2022, "visitors": 257,  "gdp": 0.36, "exr": 1.00, "flight": 0.18, "visa": 1, "bilateral": 0.63, "dist": 2900},
    {"country": "HKG", "year": 2023, "visitors": 2114, "gdp": 0.38, "exr": 1.06, "flight": 0.75, "visa": 1, "bilateral": 0.64, "dist": 2900},
    {"country": "HKG", "year": 2024, "visitors": 2600, "gdp": 0.40, "exr": 1.10, "flight": 0.88, "visa": 1, "bilateral": 0.65, "dist": 2900},
    {"country": "HKG", "year": 2025, "visitors": 2500, "gdp": 0.41, "exr": 1.08, "flight": 0.90, "visa": 1, "bilateral": 0.65, "dist": 2900},
    # --- 米国 USA ---
    {"country": "USA", "year": 2019, "visitors": 1724, "gdp": 21.43, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.82, "dist": 10800},
    {"country": "USA", "year": 2022, "visitors": 323,  "gdp": 25.46, "exr": 1.15, "flight": 0.30, "visa": 1, "bilateral": 0.83, "dist": 10800},
    {"country": "USA", "year": 2023, "visitors": 2045, "gdp": 27.36, "exr": 1.28, "flight": 0.80, "visa": 1, "bilateral": 0.85, "dist": 10800},
    {"country": "USA", "year": 2024, "visitors": 2529, "gdp": 28.78, "exr": 1.35, "flight": 0.90, "visa": 1, "bilateral": 0.84, "dist": 10800},
    {"country": "USA", "year": 2025, "visitors": 2400, "gdp": 29.50, "exr": 1.30, "flight": 0.92, "visa": 1, "bilateral": 0.83, "dist": 10800},
    # --- タイ THA ---
    {"country": "THA", "year": 2019, "visitors": 1319, "gdp": 0.54, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.78, "dist": 4600},
    {"country": "THA", "year": 2022, "visitors": 195,  "gdp": 0.50, "exr": 0.95, "flight": 0.22, "visa": 1, "bilateral": 0.78, "dist": 4600},
    {"country": "THA", "year": 2023, "visitors": 995,  "gdp": 0.51, "exr": 1.05, "flight": 0.70, "visa": 1, "bilateral": 0.80, "dist": 4600},
    {"country": "THA", "year": 2024, "visitors": 1250, "gdp": 0.53, "exr": 1.12, "flight": 0.85, "visa": 1, "bilateral": 0.80, "dist": 4600},
    {"country": "THA", "year": 2025, "visitors": 1200, "gdp": 0.55, "exr": 1.08, "flight": 0.88, "visa": 1, "bilateral": 0.80, "dist": 4600},
    # --- シンガポール SGP ---
    {"country": "SGP", "year": 2019, "visitors": 492,  "gdp": 0.37, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.75, "dist": 5300},
    {"country": "SGP", "year": 2022, "visitors": 115,  "gdp": 0.47, "exr": 1.05, "flight": 0.25, "visa": 1, "bilateral": 0.76, "dist": 5300},
    {"country": "SGP", "year": 2023, "visitors": 469,  "gdp": 0.50, "exr": 1.12, "flight": 0.78, "visa": 1, "bilateral": 0.77, "dist": 5300},
    {"country": "SGP", "year": 2024, "visitors": 585,  "gdp": 0.52, "exr": 1.18, "flight": 0.90, "visa": 1, "bilateral": 0.78, "dist": 5300},
    {"country": "SGP", "year": 2025, "visitors": 560,  "gdp": 0.54, "exr": 1.15, "flight": 0.92, "visa": 1, "bilateral": 0.78, "dist": 5300},
    # --- オーストラリア AUS ---
    {"country": "AUS", "year": 2019, "visitors": 621,  "gdp": 1.40, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.78, "dist": 7800},
    {"country": "AUS", "year": 2022, "visitors": 159,  "gdp": 1.68, "exr": 1.02, "flight": 0.20, "visa": 1, "bilateral": 0.80, "dist": 7800},
    {"country": "AUS", "year": 2023, "visitors": 596,  "gdp": 1.69, "exr": 1.10, "flight": 0.72, "visa": 1, "bilateral": 0.81, "dist": 7800},
    {"country": "AUS", "year": 2024, "visitors": 750,  "gdp": 1.72, "exr": 1.16, "flight": 0.88, "visa": 1, "bilateral": 0.82, "dist": 7800},
    {"country": "AUS", "year": 2025, "visitors": 720,  "gdp": 1.75, "exr": 1.12, "flight": 0.90, "visa": 1, "bilateral": 0.82, "dist": 7800},
    # --- フィリピン PHL ---
    {"country": "PHL", "year": 2019, "visitors": 613,  "gdp": 0.38, "exr": 1.00, "flight": 1.00, "visa": 0, "bilateral": 0.70, "dist": 3000},
    {"country": "PHL", "year": 2022, "visitors": 118,  "gdp": 0.40, "exr": 0.98, "flight": 0.18, "visa": 0, "bilateral": 0.70, "dist": 3000},
    {"country": "PHL", "year": 2023, "visitors": 563,  "gdp": 0.44, "exr": 1.03, "flight": 0.72, "visa": 0, "bilateral": 0.72, "dist": 3000},
    {"country": "PHL", "year": 2024, "visitors": 700,  "gdp": 0.47, "exr": 1.08, "flight": 0.85, "visa": 0, "bilateral": 0.73, "dist": 3000},
    {"country": "PHL", "year": 2025, "visitors": 670,  "gdp": 0.49, "exr": 1.05, "flight": 0.87, "visa": 0, "bilateral": 0.73, "dist": 3000},
    # --- マレーシア MYS ---
    {"country": "MYS", "year": 2019, "visitors": 502,  "gdp": 0.36, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.72, "dist": 5300},
    {"country": "MYS", "year": 2022, "visitors": 62,   "gdp": 0.41, "exr": 0.96, "flight": 0.15, "visa": 1, "bilateral": 0.72, "dist": 5300},
    {"country": "MYS", "year": 2023, "visitors": 412,  "gdp": 0.40, "exr": 1.05, "flight": 0.68, "visa": 1, "bilateral": 0.74, "dist": 5300},
    {"country": "MYS", "year": 2024, "visitors": 530,  "gdp": 0.42, "exr": 1.12, "flight": 0.85, "visa": 1, "bilateral": 0.75, "dist": 5300},
    {"country": "MYS", "year": 2025, "visitors": 510,  "gdp": 0.44, "exr": 1.08, "flight": 0.87, "visa": 1, "bilateral": 0.75, "dist": 5300},
    # --- ベトナム VNM ---
    {"country": "VNM", "year": 2019, "visitors": 495,  "gdp": 0.26, "exr": 1.00, "flight": 1.00, "visa": 0, "bilateral": 0.72, "dist": 3600},
    {"country": "VNM", "year": 2022, "visitors": 72,   "gdp": 0.41, "exr": 0.92, "flight": 0.15, "visa": 0, "bilateral": 0.73, "dist": 3600},
    {"country": "VNM", "year": 2023, "visitors": 375,  "gdp": 0.43, "exr": 0.98, "flight": 0.62, "visa": 0, "bilateral": 0.74, "dist": 3600},
    {"country": "VNM", "year": 2024, "visitors": 520,  "gdp": 0.47, "exr": 1.05, "flight": 0.80, "visa": 0, "bilateral": 0.75, "dist": 3600},
    {"country": "VNM", "year": 2025, "visitors": 500,  "gdp": 0.50, "exr": 1.02, "flight": 0.82, "visa": 0, "bilateral": 0.75, "dist": 3600},
    # --- インド IND ---
    {"country": "IND", "year": 2019, "visitors": 175,  "gdp": 2.87, "exr": 1.00, "flight": 1.00, "visa": 0, "bilateral": 0.65, "dist": 5800},
    {"country": "IND", "year": 2022, "visitors": 33,   "gdp": 3.39, "exr": 0.92, "flight": 0.18, "visa": 0, "bilateral": 0.66, "dist": 5800},
    {"country": "IND", "year": 2023, "visitors": 157,  "gdp": 3.57, "exr": 0.98, "flight": 0.60, "visa": 0, "bilateral": 0.68, "dist": 5800},
    {"country": "IND", "year": 2024, "visitors": 220,  "gdp": 3.89, "exr": 1.03, "flight": 0.78, "visa": 0, "bilateral": 0.70, "dist": 5800},
    {"country": "IND", "year": 2025, "visitors": 210,  "gdp": 4.10, "exr": 1.00, "flight": 0.80, "visa": 0, "bilateral": 0.70, "dist": 5800},
    # --- ドイツ DEU ---
    {"country": "DEU", "year": 2019, "visitors": 236,  "gdp": 3.86, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.75, "dist": 9300},
    {"country": "DEU", "year": 2022, "visitors": 52,   "gdp": 4.07, "exr": 0.95, "flight": 0.22, "visa": 1, "bilateral": 0.76, "dist": 9300},
    {"country": "DEU", "year": 2023, "visitors": 212,  "gdp": 4.46, "exr": 1.08, "flight": 0.72, "visa": 1, "bilateral": 0.77, "dist": 9300},
    {"country": "DEU", "year": 2024, "visitors": 275,  "gdp": 4.52, "exr": 1.15, "flight": 0.88, "visa": 1, "bilateral": 0.78, "dist": 9300},
    {"country": "DEU", "year": 2025, "visitors": 260,  "gdp": 4.55, "exr": 1.10, "flight": 0.90, "visa": 1, "bilateral": 0.78, "dist": 9300},
    # --- 英国 GBR ---
    {"country": "GBR", "year": 2019, "visitors": 424,  "gdp": 2.83, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.78, "dist": 9500},
    {"country": "GBR", "year": 2022, "visitors": 83,   "gdp": 3.07, "exr": 1.02, "flight": 0.20, "visa": 1, "bilateral": 0.79, "dist": 9500},
    {"country": "GBR", "year": 2023, "visitors": 380,  "gdp": 3.34, "exr": 1.12, "flight": 0.75, "visa": 1, "bilateral": 0.80, "dist": 9500},
    {"country": "GBR", "year": 2024, "visitors": 480,  "gdp": 3.50, "exr": 1.20, "flight": 0.88, "visa": 1, "bilateral": 0.80, "dist": 9500},
    {"country": "GBR", "year": 2025, "visitors": 460,  "gdp": 3.55, "exr": 1.16, "flight": 0.90, "visa": 1, "bilateral": 0.80, "dist": 9500},
    # --- フランス FRA ---
    {"country": "FRA", "year": 2019, "visitors": 336,  "gdp": 2.72, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.74, "dist": 9700},
    {"country": "FRA", "year": 2022, "visitors": 68,   "gdp": 2.78, "exr": 0.95, "flight": 0.18, "visa": 1, "bilateral": 0.75, "dist": 9700},
    {"country": "FRA", "year": 2023, "visitors": 305,  "gdp": 3.05, "exr": 1.08, "flight": 0.72, "visa": 1, "bilateral": 0.76, "dist": 9700},
    {"country": "FRA", "year": 2024, "visitors": 390,  "gdp": 3.13, "exr": 1.15, "flight": 0.86, "visa": 1, "bilateral": 0.76, "dist": 9700},
    {"country": "FRA", "year": 2025, "visitors": 375,  "gdp": 3.18, "exr": 1.10, "flight": 0.88, "visa": 1, "bilateral": 0.76, "dist": 9700},
    # --- カナダ CAN ---
    {"country": "CAN", "year": 2019, "visitors": 375,  "gdp": 1.74, "exr": 1.00, "flight": 1.00, "visa": 1, "bilateral": 0.76, "dist": 10400},
    {"country": "CAN", "year": 2022, "visitors": 70,   "gdp": 2.14, "exr": 1.05, "flight": 0.18, "visa": 1, "bilateral": 0.77, "dist": 10400},
    {"country": "CAN", "year": 2023, "visitors": 338,  "gdp": 2.12, "exr": 1.15, "flight": 0.70, "visa": 1, "bilateral": 0.78, "dist": 10400},
    {"country": "CAN", "year": 2024, "visitors": 430,  "gdp": 2.18, "exr": 1.22, "flight": 0.85, "visa": 1, "bilateral": 0.78, "dist": 10400},
    {"country": "CAN", "year": 2025, "visitors": 410,  "gdp": 2.22, "exr": 1.18, "flight": 0.87, "visa": 1, "bilateral": 0.78, "dist": 10400},
]


# ---------------------------------------------------------------------------
# データクラス: 予測結果
# ---------------------------------------------------------------------------
@dataclass
class GravityPrediction:
    """重力モデル予測結果"""
    source_country: str
    baseline_forecast: float          # 予測訪日者数（千人）
    elasticities: Dict[str, float]    # 各変数の弾性値
    r_squared: float                  # モデルのR²
    model_method: str                 # 推定手法
    scenario_forecast: Optional[float] = None  # シナリオ予測値
    scenario_delta_pct: Optional[float] = None # シナリオ変化率


@dataclass
class ChangeDecomposition:
    """変化の要因分解結果"""
    source_country: str
    total_change_pct: float
    components: Dict[str, float]      # 要因別寄与率(%)
    period: str


@dataclass
class MarketShareResult:
    """市場シェアモデル結果"""
    source_country: str
    japan_share: float                # 日本のシェア(0-1)
    competitor_shares: Dict[str, float]
    japan_utility: float


# ===========================================================================
# メインクラス
# ===========================================================================
class TourismGravityModel:
    """
    観光需要の重力モデル

    log(T_ij) = α + β1·log(GDP_i) + β2·log(GDP_j) + β3·log(DIST_ij)
              + β4·log(EXR_ij) + β5·log(FLIGHT_ij) + β6·VISA_ij
              + β7·BILATERAL_ij + β8·log(T_ij,t-1) + ε
    """

    def __init__(self) -> None:
        # 推定結果
        self._coefficients: Optional[Dict[str, float]] = None
        self._intercept: float = 0.0
        self._r_squared: float = 0.0
        self._adj_r_squared: float = 0.0
        self._model_method: str = "not_fitted"
        self._ols_result: Any = None  # statsmodels RegressionResults
        self._fitted: bool = False
        # 変数名マッピング（回帰列名→意味名）
        self._var_names: List[str] = [
            "gdp_source", "gdp_japan", "distance",
            "exchange_rate", "flight_supply",
            "visa_free", "bilateral", "lagged_visitors",
        ]

    # -----------------------------------------------------------------------
    # パネルデータ→行列変換
    # -----------------------------------------------------------------------
    @staticmethod
    def _build_panel() -> Tuple[np.ndarray, np.ndarray, List[Dict]]:
        """
        内蔵パネルデータから回帰用の (y, X) 行列を構築。
        ラグ付き被説明変数を含めるため、各国の先頭1年分は除外。

        Returns:
            y: log(visitors) — shape (N,)
            X: 説明変数行列 — shape (N, 8)
            meta: 対応するメタ情報
        """
        # 国別にソート
        from collections import defaultdict
        by_country: Dict[str, List[Dict]] = defaultdict(list)
        for row in _SAMPLE_PANEL:
            by_country[row["country"]].append(row)
        for k in by_country:
            by_country[k].sort(key=lambda r: r["year"])

        y_list: List[float] = []
        X_list: List[List[float]] = []
        meta: List[Dict] = []

        for country, rows in by_country.items():
            for i in range(1, len(rows)):
                cur = rows[i]
                prev = rows[i - 1]
                # 訪問者数が0以下の場合はスキップ
                if cur["visitors"] <= 0 or prev["visitors"] <= 0:
                    continue

                japan_gdp = _JAPAN_GDP_TRILLION.get(cur["year"], 4.20)

                y_list.append(math.log(cur["visitors"]))
                X_list.append([
                    math.log(max(cur["gdp"], 0.01)),       # log(GDP_i)
                    math.log(japan_gdp),                     # log(GDP_j)
                    math.log(cur["dist"]),                   # log(DIST)
                    math.log(max(cur["exr"], 0.01)),        # log(EXR)
                    math.log(max(cur["flight"], 0.01)),     # log(FLIGHT)
                    float(cur["visa"]),                      # VISA (ダミー)
                    cur["bilateral"],                        # BILATERAL
                    math.log(prev["visitors"]),              # log(T_{t-1})
                ])
                meta.append({"country": country, "year": cur["year"]})

        return np.array(y_list), np.array(X_list), meta

    # -----------------------------------------------------------------------
    # fit()
    # -----------------------------------------------------------------------
    def fit(
        self,
        training_data: Optional[List[Dict[str, Any]]] = None,
        method: str = "OLS",
    ) -> Dict[str, Any]:
        """
        重力モデルをOLSで推定する。

        Args:
            training_data: 外部パネルデータ（Noneの場合は内蔵データ使用）
            method: 推定手法（"OLS"のみ現在サポート）

        Returns:
            推定結果の辞書
        """
        try:
            import statsmodels.api as sm
        except ImportError:
            logger.warning("statsmodels未インストール — 事前係数をフォールバック使用")
            return self._fallback_priors()

        # パネルデータ構築
        if training_data is not None:
            # 外部データが提供された場合、同じフォーマットに変換
            # (将来拡張用、現時点では内蔵データと同じ構造を想定)
            global _SAMPLE_PANEL
            original = _SAMPLE_PANEL
            _SAMPLE_PANEL = training_data
            y, X, meta = self._build_panel()
            _SAMPLE_PANEL = original
        else:
            y, X, meta = self._build_panel()

        if len(y) < 10:
            logger.warning("訓練データ不足 (N=%d) — 事前係数をフォールバック使用", len(y))
            return self._fallback_priors()

        # 定数項を追加
        X_const = sm.add_constant(X)

        try:
            model = sm.OLS(y, X_const)
            results = model.fit()
            self._ols_result = results

            # 係数を保存
            params = results.params
            self._intercept = float(params[0])
            self._coefficients = {}
            for i, name in enumerate(self._var_names):
                self._coefficients[name] = float(params[i + 1])

            self._r_squared = float(results.rsquared)
            self._adj_r_squared = float(results.rsquared_adj)
            self._model_method = method
            self._fitted = True

            # 係数の妥当性チェック（学術的に合理的な範囲か確認）
            self._validate_coefficients()

            logger.info(
                "重力モデル推定完了: R²=%.4f, Adj.R²=%.4f, N=%d",
                self._r_squared, self._adj_r_squared, len(y),
            )

            return {
                "method": method,
                "n_observations": len(y),
                "r_squared": self._r_squared,
                "adj_r_squared": self._adj_r_squared,
                "coefficients": {**self._coefficients, "intercept": self._intercept},
                "p_values": {
                    name: float(results.pvalues[i + 1])
                    for i, name in enumerate(self._var_names)
                },
                "summary": str(results.summary()),
            }

        except Exception as e:
            logger.error("OLS推定失敗: %s — 事前係数フォールバック", e)
            return self._fallback_priors()

    def _fallback_priors(self) -> Dict[str, Any]:
        """学術文献ベースの事前係数でフォールバック"""
        self._coefficients = dict(COEFFICIENT_PRIORS)
        self._coefficients["gdp_japan"] = 0.50
        self._intercept = 3.5  # 合理的なベースライン
        self._r_squared = 0.0
        self._adj_r_squared = 0.0
        self._model_method = "prior_fallback"
        self._fitted = True

        logger.info("事前係数によるフォールバック初期化完了")
        return {
            "method": "prior_fallback",
            "n_observations": 0,
            "r_squared": 0.0,
            "coefficients": {**self._coefficients, "intercept": self._intercept},
            "note": "学術文献ベースの事前係数を使用（データ不足のため）",
        }

    def _validate_coefficients(self) -> None:
        """推定係数が学術的に妥当な範囲内かチェック"""
        if self._coefficients is None:
            return
        # 為替レート弾性値: EXRインデックスは「ソース国通貨の対円購買力」
        # インデックス上昇=円安=訪日有利 → 正の係数が理論的に正しい
        # 通常 +0.3 ～ +1.5 (対数モデルなので符号は正)
        exr = self._coefficients.get("exchange_rate", 0)
        if exr < -0.5:
            logger.warning("為替レート弾性値が負 (%.3f): EXRインデックス定義と不整合の可能性", exr)
        # 距離: 通常負
        dist = self._coefficients.get("distance", 0)
        if dist > 0.3:
            logger.warning("距離弾性値が正 (%.3f): 理論と不整合の可能性", dist)
        # GDP: 通常正
        gdp = self._coefficients.get("gdp_source", 0)
        if gdp < -0.5:
            logger.warning("GDP弾性値が負 (%.3f): 理論と不整合の可能性", gdp)

    # -----------------------------------------------------------------------
    # predict()
    # -----------------------------------------------------------------------
    def predict(
        self,
        source_country: str,
        horizon_months: int = 12,
        scenario: Optional[Dict[str, float]] = None,
    ) -> GravityPrediction:
        """
        指定国からの訪日観光客数を予測する。

        Args:
            source_country: ISO3国コード
            horizon_months: 予測期間（月）
            scenario: シナリオ変数 {"exchange_rate": 1.2, "flight_supply": 0.9, ...}

        Returns:
            GravityPrediction
        """
        if not self._fitted:
            self.fit()

        coef = self._coefficients
        assert coef is not None

        # 最新の観測データを取得
        latest = self._get_latest_data(source_country)
        if latest is None:
            raise ValueError(f"国コード {source_country} のデータが見つかりません")

        prev_data = self._get_previous_data(source_country)
        lagged = prev_data["visitors"] if prev_data else latest["visitors"] * 0.9

        japan_gdp = _JAPAN_GDP_TRILLION.get(2025, 4.30)

        # ベースライン予測
        log_pred = self._intercept
        log_pred += coef.get("gdp_source", 0) * math.log(max(latest["gdp"], 0.01))
        log_pred += coef.get("gdp_japan", 0) * math.log(japan_gdp)
        log_pred += coef.get("distance", 0) * math.log(latest["dist"])
        log_pred += coef.get("exchange_rate", 0) * math.log(max(latest["exr"], 0.01))
        log_pred += coef.get("flight_supply", 0) * math.log(max(latest["flight"], 0.01))
        log_pred += coef.get("visa_free", 0) * float(latest["visa"])
        log_pred += coef.get("bilateral", 0) * latest["bilateral"]
        log_pred += coef.get("lagged_visitors", 0) * math.log(max(lagged, 1))

        baseline = math.exp(log_pred)

        # 期間調整（年次→月次近似）
        monthly_factor = horizon_months / 12.0
        baseline_adjusted = baseline * monthly_factor

        # 弾性値（係数そのもの = 対数モデルの弾性値）
        elasticities = {
            "exchange_rate": coef.get("exchange_rate", COEFFICIENT_PRIORS["exchange_rate"]),
            "flight_supply": coef.get("flight_supply", COEFFICIENT_PRIORS["flight_supply"]),
            "gdp_source": coef.get("gdp_source", COEFFICIENT_PRIORS["gdp_source"]),
            "visa_free": coef.get("visa_free", COEFFICIENT_PRIORS["visa_free"]),
            "bilateral": coef.get("bilateral", COEFFICIENT_PRIORS["bilateral"]),
            "distance": coef.get("distance", COEFFICIENT_PRIORS["distance"]),
        }

        result = GravityPrediction(
            source_country=source_country,
            baseline_forecast=round(baseline_adjusted, 1),
            elasticities=elasticities,
            r_squared=self._r_squared,
            model_method=self._model_method,
        )

        # シナリオ分析
        if scenario:
            log_scenario = log_pred  # ベースラインからの偏差
            for var_name, shock_value in scenario.items():
                if var_name in coef and shock_value > 0:
                    # ベースライン値との差分で計算
                    base_val = self._get_base_value(latest, var_name)
                    if base_val and base_val > 0:
                        delta_log = math.log(shock_value) - math.log(base_val)
                        log_scenario += coef[var_name] * delta_log

            scenario_forecast = math.exp(log_scenario) * monthly_factor
            result.scenario_forecast = round(scenario_forecast, 1)
            if baseline_adjusted > 0:
                result.scenario_delta_pct = round(
                    (scenario_forecast - baseline_adjusted) / baseline_adjusted * 100, 2
                )

        return result

    # -----------------------------------------------------------------------
    # decompose_change()
    # -----------------------------------------------------------------------
    def decompose_change(
        self,
        source_country: str,
        period_months: int = 12,
    ) -> ChangeDecomposition:
        """
        実績変化を要因分解する。

        各要因の寄与 = β_k × Δlog(x_k) / Δlog(T)

        Args:
            source_country: ISO3国コード
            period_months: 分解期間（月、12=年次比較）

        Returns:
            ChangeDecomposition
        """
        if not self._fitted:
            self.fit()

        coef = self._coefficients
        assert coef is not None

        # 直近2期間のデータを取得
        latest = self._get_latest_data(source_country)
        prev = self._get_previous_data(source_country)

        if latest is None or prev is None:
            raise ValueError(f"国コード {source_country} の時系列データが不足しています")

        # 実績変化率
        if prev["visitors"] <= 0:
            raise ValueError(f"{source_country}: 前期の訪問者数が0")
        total_change = (latest["visitors"] - prev["visitors"]) / prev["visitors"] * 100

        # 要因別分解: β × Δlog(x) を各要因について計算
        components: Dict[str, float] = {}

        # 各変数のΔlog計算
        factor_deltas = {
            "exchange_rate": self._safe_delta_log(latest["exr"], prev["exr"]),
            "flight_supply": self._safe_delta_log(latest["flight"], prev["flight"]),
            "gdp_source": self._safe_delta_log(latest["gdp"], prev["gdp"]),
            "bilateral": latest["bilateral"] - prev["bilateral"],  # レベル変数
            "visa_free": float(latest["visa"]) - float(prev["visa"]),  # ダミー変数
        }

        # 各要因の寄与率（%ポイント）
        total_explained = 0.0
        for name, delta in factor_deltas.items():
            beta = coef.get(name, COEFFICIENT_PRIORS.get(name, 0))
            # 対数モデルなので β × Δlog(x) ≈ 変化率への寄与
            contribution_pct = beta * delta * 100
            components[name] = round(contribution_pct, 2)
            total_explained += contribution_pct

        # 残差（説明できない部分）
        components["residual"] = round(total_change - total_explained, 2)

        period_label = f"{prev['year']}→{latest['year']}"

        return ChangeDecomposition(
            source_country=source_country,
            total_change_pct=round(total_change, 2),
            components=components,
            period=period_label,
        )

    # -----------------------------------------------------------------------
    # calculate_market_share_model()
    # -----------------------------------------------------------------------
    def calculate_market_share_model(
        self,
        source_country: str,
        competitors: Optional[List[str]] = None,
    ) -> MarketShareResult:
        """
        ロジットモデルで日本のシェアを推定する。

        多項ロジットモデル:
          P(日本) = exp(V_jp) / Σ_k exp(V_k)
          V_k = β_dist·log(DIST_k) + β_exr·log(EXR_k) + β_visa·VISA_k

        Args:
            source_country: ソース国ISO3コード
            competitors: 競合デスティネーションのISO3リスト

        Returns:
            MarketShareResult
        """
        if not self._fitted:
            self.fit()

        coef = self._coefficients
        assert coef is not None

        # デフォルト競合国（アジア太平洋の人気デスティネーション）
        if competitors is None:
            competitors = ["KOR", "THA", "SGP", "TWN", "VNM"]

        # 競合国のパラメータ（日本からの視点ではなく、ソース国からの視点）
        # ソース国→各デスティネーションの距離近似
        _COMPETITOR_DIST_FROM_SOURCES: Dict[str, Dict[str, int]] = {
            "CHN": {"JPN": 2100, "KOR": 950, "THA": 3200, "SGP": 4500, "TWN": 700, "VNM": 2300},
            "KOR": {"JPN": 1160, "KOR": 0, "THA": 3700, "SGP": 4600, "TWN": 1500, "VNM": 3100},
            "USA": {"JPN": 10800, "KOR": 11000, "THA": 13900, "SGP": 15300, "TWN": 12500, "VNM": 13600},
            "AUS": {"JPN": 7800, "KOR": 8300, "THA": 7500, "SGP": 6300, "TWN": 7400, "VNM": 7200},
        }

        # 一般的な距離近似（データがない場合）
        default_distances = {
            "JPN": 5000, "KOR": 5000, "THA": 5000, "SGP": 5500,
            "TWN": 5000, "VNM": 5000,
        }

        # 日本の効用関数値
        japan_dist = DISTANCE_TO_JAPAN.get(source_country, 5000)
        latest = self._get_latest_data(source_country)
        japan_exr = latest["exr"] if latest else 1.0
        japan_visa = float(VISA_FREE.get(source_country, False))

        beta_dist = coef.get("distance", COEFFICIENT_PRIORS["distance"])
        beta_exr = coef.get("exchange_rate", COEFFICIENT_PRIORS["exchange_rate"])
        beta_visa = coef.get("visa_free", COEFFICIENT_PRIORS["visa_free"])

        # 日本の効用
        v_japan = (
            beta_dist * math.log(japan_dist)
            + beta_exr * math.log(max(japan_exr, 0.01))
            + beta_visa * japan_visa
        )

        # 各競合国の効用
        utilities: Dict[str, float] = {"JPN": v_japan}
        src_distances = _COMPETITOR_DIST_FROM_SOURCES.get(source_country, {})

        for comp in competitors:
            if comp == source_country:
                continue
            comp_dist = src_distances.get(comp, default_distances.get(comp, 5000))
            if comp_dist <= 0:
                comp_dist = 100  # 国内観光
            # 競合国の為替・ビザは簡略化（日本との相対値）
            comp_exr = 1.0  # ベースライン
            comp_visa = 1.0 if comp in ("THA", "KOR", "SGP") else 0.0

            v_comp = (
                beta_dist * math.log(comp_dist)
                + beta_exr * math.log(max(comp_exr, 0.01))
                + beta_visa * comp_visa
            )
            utilities[comp] = v_comp

        # ロジットシェア計算
        max_v = max(utilities.values())  # オーバーフロー防止
        exp_utilities = {k: math.exp(v - max_v) for k, v in utilities.items()}
        total_exp = sum(exp_utilities.values())

        shares = {k: v / total_exp for k, v in exp_utilities.items()}
        japan_share = shares.pop("JPN", 0.0)
        competitor_shares = shares

        return MarketShareResult(
            source_country=source_country,
            japan_share=round(japan_share, 4),
            competitor_shares={k: round(v, 4) for k, v in competitor_shares.items()},
            japan_utility=round(v_japan, 4),
        )

    # -----------------------------------------------------------------------
    # ヘルパーメソッド
    # -----------------------------------------------------------------------
    def _get_latest_data(self, country: str) -> Optional[Dict]:
        """指定国の最新データを取得"""
        rows = [r for r in _SAMPLE_PANEL if r["country"] == country]
        if not rows:
            return None
        return max(rows, key=lambda r: r["year"])

    def _get_previous_data(self, country: str) -> Optional[Dict]:
        """指定国の1期前データを取得"""
        rows = sorted(
            [r for r in _SAMPLE_PANEL if r["country"] == country],
            key=lambda r: r["year"],
        )
        if len(rows) < 2:
            return None
        return rows[-2]

    @staticmethod
    def _safe_delta_log(current: float, previous: float) -> float:
        """安全なΔlog計算"""
        if current <= 0 or previous <= 0:
            return 0.0
        return math.log(current) - math.log(previous)

    @staticmethod
    def _get_base_value(data: Dict, var_name: str) -> Optional[float]:
        """データ辞書から変数名に対応する値を取得"""
        mapping = {
            "exchange_rate": "exr",
            "flight_supply": "flight",
            "gdp_source": "gdp",
            "bilateral": "bilateral",
        }
        key = mapping.get(var_name)
        if key and key in data:
            return float(data[key])
        return None

    # -----------------------------------------------------------------------
    # ユーティリティ
    # -----------------------------------------------------------------------
    def summary(self) -> str:
        """モデルのサマリーを文字列で返す"""
        if not self._fitted:
            return "モデル未推定。fit()を先に呼んでください。"

        lines = [
            "=" * 60,
            "観光需要の重力モデル — 推定結果サマリー",
            "=" * 60,
            f"推定手法: {self._model_method}",
            f"R²: {self._r_squared:.4f}",
            f"Adj. R²: {self._adj_r_squared:.4f}",
            f"切片: {self._intercept:.4f}",
            "",
            "--- 係数 ---",
        ]
        if self._coefficients:
            for name, val in self._coefficients.items():
                prior = COEFFICIENT_PRIORS.get(name, None)
                prior_str = f" (事前値: {prior:.2f})" if prior is not None else ""
                lines.append(f"  {name:20s}: {val:+.4f}{prior_str}")

        if self._ols_result is not None:
            lines.append("")
            lines.append("--- statsmodels サマリー ---")
            lines.append(str(self._ols_result.summary()))

        return "\n".join(lines)

    def get_coefficients(self) -> Dict[str, float]:
        """推定係数を辞書で返す"""
        if not self._fitted:
            self.fit()
        result = dict(self._coefficients or {})
        result["intercept"] = self._intercept
        return result

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    # -----------------------------------------------------------------------
    # build_training_dataset() — tourism_stats.db からパネルデータ構築
    # -----------------------------------------------------------------------
    def build_training_dataset(self) -> List[Dict[str, Any]]:
        """
        tourism_stats.db から outbound_stats × japan_inbound × gravity_variables を
        JOINしてパネルデータを構築する。
        DBがない場合は内蔵 _SAMPLE_PANEL にフォールバック。

        Returns:
            パネルデータ（_SAMPLE_PANEL 互換フォーマット）
        """
        try:
            from pipeline.tourism.tourism_db import TourismDB
            db = TourismDB()

            import sqlite3
            conn = sqlite3.connect(db.db_path)
            conn.row_factory = sqlite3.Row

            # outbound_stats × japan_inbound × gravity_variables を JOIN
            query = """
                SELECT
                    g.source_country AS country,
                    g.year,
                    COALESCE(j.arrivals, 0) AS visitors,
                    g.gdp_source_usd AS gdp,
                    g.exchange_rate_jpy AS exr,
                    g.flight_supply_index AS flight,
                    g.visa_free AS visa,
                    g.bilateral_risk AS bilateral,
                    o.outbound_total
                FROM gravity_variables g
                LEFT JOIN japan_inbound j
                    ON g.source_country = j.source_country
                    AND g.year = j.year
                    AND g.month = j.month
                LEFT JOIN outbound_stats o
                    ON g.source_country = o.source_country
                    AND g.year = o.year
                    AND g.month = o.month
                WHERE g.gdp_source_usd IS NOT NULL
                    AND g.exchange_rate_jpy IS NOT NULL
                ORDER BY g.source_country, g.year, g.month
            """
            rows = conn.execute(query).fetchall()
            conn.close()

            if not rows or len(rows) < 10:
                logger.info("tourism_stats.db データ不足 (%d行) — 内蔵データにフォールバック",
                            len(rows) if rows else 0)
                return list(_SAMPLE_PANEL)

            # _SAMPLE_PANEL 互換フォーマットに変換
            panel = []
            for r in rows:
                country = r["country"]
                dist = DISTANCE_TO_JAPAN.get(country, 5000)
                visitors = r["visitors"] if r["visitors"] and r["visitors"] > 0 else None
                if visitors is None:
                    continue

                # 千人単位に変換（DBは実数、_SAMPLE_PANELは千人）
                visitors_k = visitors / 1000.0 if visitors > 10000 else float(visitors)

                panel.append({
                    "country": country,
                    "year": r["year"],
                    "visitors": visitors_k,
                    "gdp": r["gdp"] if r["gdp"] else 0.01,
                    "exr": r["exr"] if r["exr"] else 1.0,
                    "flight": r["flight"] if r["flight"] else 0.5,
                    "visa": int(VISA_FREE.get(country, False)),
                    "bilateral": (r["bilateral"] or 50) / 100.0,
                    "dist": dist,
                })

            if len(panel) < 10:
                logger.info("DB変換後データ不足 (%d行) — 内蔵データにフォールバック", len(panel))
                return list(_SAMPLE_PANEL)

            logger.info("tourism_stats.db からパネルデータ構築完了: %d行", len(panel))
            return panel

        except (ImportError, Exception) as e:
            logger.info("tourism_stats.db 読み込み不可 — 内蔵データにフォールバック: %s", type(e).__name__)
            return list(_SAMPLE_PANEL)

    # -----------------------------------------------------------------------
    # auto_refit() — 新規データ取込後に自動再推定
    # -----------------------------------------------------------------------
    def auto_refit(self) -> Dict[str, Any]:
        """
        tourism_stats.db から最新データを取得し重力モデルを再推定する。
        係数変化が±20%超の場合はアラートを含む結果を返す。

        Returns:
            再推定結果 + アラート情報
        """
        # 旧係数を保存
        old_coefficients = dict(self._coefficients) if self._coefficients else {}

        # DBからパネルデータ構築
        panel_data = self.build_training_dataset()

        # 再推定
        fit_result = self.fit(training_data=panel_data)

        # 係数変化チェック（±20%超でアラート）
        alerts = []
        if old_coefficients and self._coefficients:
            for name, new_val in self._coefficients.items():
                old_val = old_coefficients.get(name)
                if old_val is None or old_val == 0:
                    continue
                change_pct = abs((new_val - old_val) / old_val) * 100
                if change_pct > 20:
                    alerts.append({
                        "variable": name,
                        "old_value": round(old_val, 4),
                        "new_value": round(new_val, 4),
                        "change_pct": round(change_pct, 1),
                        "severity": "WARNING" if change_pct < 50 else "CRITICAL",
                    })

        result = {
            "refit_result": fit_result,
            "data_source": "tourism_stats.db" if panel_data != list(_SAMPLE_PANEL) else "builtin",
            "panel_size": len(panel_data),
            "coefficient_alerts": alerts,
            "has_alerts": len(alerts) > 0,
        }

        if alerts:
            logger.warning(
                "重力モデル再推定: %d変数で係数変化±20%%超を検出",
                len(alerts),
            )

        return result
