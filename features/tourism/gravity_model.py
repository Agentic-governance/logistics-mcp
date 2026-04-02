"""
観光需要の PPML 構造重力モデル (Poisson Pseudo-Maximum Likelihood)
================================================================
SCRI v1.4.0

数式 (レベル形式 — 拡張版):
  T_ij = exp(α + β1·ln(GDP_i) + β2·ln(EXR_ij) + β3·ln(FLIGHT_ij)
           + β4·VISA_ij + β5·BILATERAL_ij
           + β6·LEAVE_UTIL_i + β7·OUTBOUND_PROP_i + β8·TMI_i
           + β9·ln(RESTAURANT_i) + β10·ln(LANG_LEARNERS_i)
           + Σγ_i·SOURCE_FE + Σδ_t·YEAR_FE) + ε

PPMLの利点:
  - ゼロ観測値をそのまま扱える（対数変換不要）
  - Jensen不等式によるバイアスを回避
  - 異分散に頑健（Silva & Tenreyro 2006）

学術文献:
  - Silva & Tenreyro (2006) "The Log of Gravity" REStud
  - Lim (1997) "Review of International Tourism Demand Models"
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
# 学術文献ベースの事前係数（PPMLが失敗した場合のフォールバック）
# ---------------------------------------------------------------------------
COEFFICIENT_PRIORS: Dict[str, float] = {
    "ln_gdp_source":      1.10,   # ソース国GDP弾性値（正）
    "ln_exr":             0.85,   # 為替レート弾性値（円安→正）
    "ln_flight":          0.60,   # 航空供給弾性値（正）
    "visa_free":          0.35,   # ビザ免除ダミー（正）
    "bilateral_risk":    -0.40,   # 二国間リスク（負）
    # --- v1.4.0 拡張変数 ---
    "leave_utilization":  0.25,   # 有給取得率→余暇需要proxy（正）
    "outbound_propensity":0.30,   # 出国傾向率→海外旅行習慣（正）
    "travel_momentum":    0.20,   # TMI（正）— TASK1-Bが生成
    "ln_restaurant":      0.15,   # 日本食レストラン数対数→文化関心（正）
    "ln_lang_learners":   0.12,   # 日本語学習者数対数→文化関心（正）
}

# ---------------------------------------------------------------------------
# v1.4.0 拡張: 余暇proxy + 文化的関心proxy（11カ国ハードコード）
# ---------------------------------------------------------------------------
LEAVE_UTILIZATION: Dict[str, float] = {
    "KOR": 0.65, "CHN": 0.55, "TWN": 0.70, "USA": 0.75, "AUS": 0.80,
    "THA": 0.60, "HKG": 0.72, "SGP": 0.78, "DEU": 0.85, "FRA": 0.90, "GBR": 0.82,
}

OUTBOUND_PROPENSITY: Dict[str, float] = {
    "KOR": 0.54, "CHN": 0.11, "TWN": 0.72, "USA": 0.29, "AUS": 0.42,
    "THA": 0.17, "HKG": 1.28, "SGP": 1.55, "DEU": 1.33, "FRA": 1.05, "GBR": 1.07,
}

RESTAURANT_INDEX: Dict[str, float] = {  # 日本食レストラン指数 (2019=100)
    "KOR": 110, "CHN": 125, "TWN": 108, "USA": 135, "AUS": 120,
    "THA": 115, "HKG": 105, "SGP": 112, "DEU": 118, "FRA": 122, "GBR": 128,
}

# 日本語学習者数（千人）— 国際交流基金2021年調査ベース
LANGUAGE_LEARNERS: Dict[str, float] = {
    "KOR": 470, "CHN": 1060, "TWN": 170, "USA": 170, "AUS": 405,
    "THA": 184, "HKG": 25, "SGP": 50, "DEU": 14, "FRA": 14, "GBR": 20,
}

# Travel Momentum Index (TMI) — TASK1-Bが生成するが、デフォルト値をハードコード
# 0-1スケール。COVID回復度×構造トレンド
TRAVEL_MOMENTUM_DEFAULT: Dict[str, float] = {
    "KOR": 0.85, "CHN": 0.60, "TWN": 0.80, "USA": 0.72, "AUS": 0.75,
    "THA": 0.70, "HKG": 0.78, "SGP": 0.82, "DEU": 0.68, "FRA": 0.70, "GBR": 0.73,
}

# ---------------------------------------------------------------------------
# ISO2→ISO3 マッピング（タスク仕様のISO2コードとの変換用）
# ---------------------------------------------------------------------------
_ISO2_TO_ISO3: Dict[str, str] = {
    "CN": "CHN", "KR": "KOR", "TW": "TWN", "US": "USA", "AU": "AUS",
    "TH": "THA", "HK": "HKG", "SG": "SGP", "DE": "DEU", "FR": "FRA",
    "GB": "GBR",
}
_ISO3_TO_ISO2: Dict[str, str] = {v: k for k, v in _ISO2_TO_ISO3.items()}

def _normalize_country(code: str) -> str:
    """ISO2/ISO3どちらでも受け付けてISO2に正規化"""
    if code in _ISO2_TO_ISO3:
        return code
    if code in _ISO3_TO_ISO2:
        return _ISO3_TO_ISO2[code]
    return code

# ---------------------------------------------------------------------------
# 内蔵パネルデータ: 11カ国 × 2015-2019 + 2022-2024（年次、千人単位）
# JNTO公開データ / IMF WEO / BOJ為替統計
# コロナ期間 (2020-2021) は除外
# ---------------------------------------------------------------------------
# 各レコード: country(ISO2), year, visitors(千人), gdp_source(10億USD),
#             exr(ソース通貨/100JPY), flight_supply(2019=100), visa_free(0/1),
#             bilateral_risk(0-100)

_BUILTIN_PANEL: List[Dict[str, Any]] = [
    # --- 中国 CN ---
    {"country": "CN", "year": 2015, "visitors": 4994, "gdp_source": 11016, "exr": 5.73, "flight": 82, "visa_free": 0, "bilateral_risk": 52},
    {"country": "CN", "year": 2016, "visitors": 6373, "gdp_source": 11233, "exr": 6.19, "flight": 88, "visa_free": 0, "bilateral_risk": 48},
    {"country": "CN", "year": 2017, "visitors": 7356, "gdp_source": 12310, "exr": 5.95, "flight": 92, "visa_free": 0, "bilateral_risk": 45},
    {"country": "CN", "year": 2018, "visitors": 8380, "gdp_source": 13895, "exr": 5.82, "flight": 96, "visa_free": 0, "bilateral_risk": 43},
    {"country": "CN", "year": 2019, "visitors": 9594, "gdp_source": 14280, "exr": 5.92, "flight": 100, "visa_free": 0, "bilateral_risk": 45},
    {"country": "CN", "year": 2022, "visitors": 189,  "gdp_source": 17960, "exr": 5.50, "flight": 12, "visa_free": 0, "bilateral_risk": 55},
    {"country": "CN", "year": 2023, "visitors": 2426, "gdp_source": 17790, "exr": 5.28, "flight": 55, "visa_free": 0, "bilateral_risk": 50},
    {"country": "CN", "year": 2024, "visitors": 6924, "gdp_source": 18270, "exr": 5.10, "flight": 78, "visa_free": 0, "bilateral_risk": 48},
    # --- 韓国 KR ---
    {"country": "KR", "year": 2015, "visitors": 4002, "gdp_source": 1383, "exr": 9.30, "flight": 80, "visa_free": 1, "bilateral_risk": 55},
    {"country": "KR", "year": 2016, "visitors": 5090, "gdp_source": 1415, "exr": 9.50, "flight": 85, "visa_free": 1, "bilateral_risk": 50},
    {"country": "KR", "year": 2017, "visitors": 7140, "gdp_source": 1531, "exr": 8.80, "flight": 90, "visa_free": 1, "bilateral_risk": 48},
    {"country": "KR", "year": 2018, "visitors": 7539, "gdp_source": 1619, "exr": 8.90, "flight": 95, "visa_free": 1, "bilateral_risk": 45},
    {"country": "KR", "year": 2019, "visitors": 5585, "gdp_source": 1647, "exr": 9.10, "flight": 100, "visa_free": 1, "bilateral_risk": 50},
    {"country": "KR", "year": 2022, "visitors": 1013, "gdp_source": 1665, "exr": 7.60, "flight": 35, "visa_free": 1, "bilateral_risk": 52},
    {"country": "KR", "year": 2023, "visitors": 6958, "gdp_source": 1713, "exr": 7.50, "flight": 88, "visa_free": 1, "bilateral_risk": 42},
    {"country": "KR", "year": 2024, "visitors": 8818, "gdp_source": 1760, "exr": 7.20, "flight": 95, "visa_free": 1, "bilateral_risk": 40},
    # --- 台湾 TW ---
    {"country": "TW", "year": 2015, "visitors": 3677, "gdp_source": 534, "exr": 3.70, "flight": 82, "visa_free": 1, "bilateral_risk": 28},
    {"country": "TW", "year": 2016, "visitors": 4168, "gdp_source": 543, "exr": 3.50, "flight": 86, "visa_free": 1, "bilateral_risk": 27},
    {"country": "TW", "year": 2017, "visitors": 4564, "gdp_source": 575, "exr": 3.60, "flight": 90, "visa_free": 1, "bilateral_risk": 26},
    {"country": "TW", "year": 2018, "visitors": 4757, "gdp_source": 590, "exr": 3.60, "flight": 95, "visa_free": 1, "bilateral_risk": 26},
    {"country": "TW", "year": 2019, "visitors": 4891, "gdp_source": 612, "exr": 3.50, "flight": 100, "visa_free": 1, "bilateral_risk": 27},
    {"country": "TW", "year": 2022, "visitors": 332,  "gdp_source": 762, "exr": 3.30, "flight": 20, "visa_free": 1, "bilateral_risk": 30},
    {"country": "TW", "year": 2023, "visitors": 4202, "gdp_source": 751, "exr": 3.20, "flight": 82, "visa_free": 1, "bilateral_risk": 28},
    {"country": "TW", "year": 2024, "visitors": 5876, "gdp_source": 800, "exr": 3.10, "flight": 92, "visa_free": 1, "bilateral_risk": 27},
    # --- 米国 US ---
    {"country": "US", "year": 2015, "visitors": 1033, "gdp_source": 18221, "exr": 0.83, "flight": 85, "visa_free": 1, "bilateral_risk": 18},
    {"country": "US", "year": 2016, "visitors": 1243, "gdp_source": 18745, "exr": 0.92, "flight": 88, "visa_free": 1, "bilateral_risk": 17},
    {"country": "US", "year": 2017, "visitors": 1375, "gdp_source": 19543, "exr": 0.89, "flight": 92, "visa_free": 1, "bilateral_risk": 17},
    {"country": "US", "year": 2018, "visitors": 1526, "gdp_source": 20580, "exr": 0.91, "flight": 96, "visa_free": 1, "bilateral_risk": 16},
    {"country": "US", "year": 2019, "visitors": 1724, "gdp_source": 21430, "exr": 0.92, "flight": 100, "visa_free": 1, "bilateral_risk": 17},
    {"country": "US", "year": 2022, "visitors": 323,  "gdp_source": 25460, "exr": 0.75, "flight": 30, "visa_free": 1, "bilateral_risk": 18},
    {"country": "US", "year": 2023, "visitors": 2045, "gdp_source": 27360, "exr": 0.71, "flight": 80, "visa_free": 1, "bilateral_risk": 16},
    {"country": "US", "year": 2024, "visitors": 2529, "gdp_source": 28780, "exr": 0.66, "flight": 90, "visa_free": 1, "bilateral_risk": 17},
    # --- オーストラリア AU ---
    {"country": "AU", "year": 2015, "visitors": 377, "gdp_source": 1350, "exr": 0.90, "flight": 82, "visa_free": 1, "bilateral_risk": 20},
    {"country": "AU", "year": 2016, "visitors": 445, "gdp_source": 1268, "exr": 0.84, "flight": 86, "visa_free": 1, "bilateral_risk": 19},
    {"country": "AU", "year": 2017, "visitors": 493, "gdp_source": 1390, "exr": 0.86, "flight": 90, "visa_free": 1, "bilateral_risk": 19},
    {"country": "AU", "year": 2018, "visitors": 552, "gdp_source": 1434, "exr": 0.85, "flight": 95, "visa_free": 1, "bilateral_risk": 18},
    {"country": "AU", "year": 2019, "visitors": 621, "gdp_source": 1397, "exr": 0.83, "flight": 100, "visa_free": 1, "bilateral_risk": 20},
    {"country": "AU", "year": 2022, "visitors": 159, "gdp_source": 1680, "exr": 0.80, "flight": 20, "visa_free": 1, "bilateral_risk": 18},
    {"country": "AU", "year": 2023, "visitors": 596, "gdp_source": 1690, "exr": 0.75, "flight": 72, "visa_free": 1, "bilateral_risk": 17},
    {"country": "AU", "year": 2024, "visitors": 750, "gdp_source": 1720, "exr": 0.72, "flight": 88, "visa_free": 1, "bilateral_risk": 18},
    # --- タイ TH ---
    {"country": "TH", "year": 2015, "visitors": 796, "gdp_source": 401, "exr": 2.97, "flight": 80, "visa_free": 1, "bilateral_risk": 25},
    {"country": "TH", "year": 2016, "visitors": 901, "gdp_source": 413, "exr": 3.10, "flight": 85, "visa_free": 1, "bilateral_risk": 24},
    {"country": "TH", "year": 2017, "visitors": 987, "gdp_source": 456, "exr": 3.20, "flight": 90, "visa_free": 1, "bilateral_risk": 23},
    {"country": "TH", "year": 2018, "visitors": 1132, "gdp_source": 507, "exr": 3.25, "flight": 95, "visa_free": 1, "bilateral_risk": 22},
    {"country": "TH", "year": 2019, "visitors": 1319, "gdp_source": 544, "exr": 3.30, "flight": 100, "visa_free": 1, "bilateral_risk": 22},
    {"country": "TH", "year": 2022, "visitors": 195, "gdp_source": 495, "exr": 2.80, "flight": 22, "visa_free": 1, "bilateral_risk": 24},
    {"country": "TH", "year": 2023, "visitors": 995, "gdp_source": 514, "exr": 2.75, "flight": 70, "visa_free": 1, "bilateral_risk": 22},
    {"country": "TH", "year": 2024, "visitors": 1250, "gdp_source": 530, "exr": 2.70, "flight": 85, "visa_free": 1, "bilateral_risk": 21},
    # --- 香港 HK ---
    {"country": "HK", "year": 2015, "visitors": 1524, "gdp_source": 310, "exr": 0.65, "flight": 82, "visa_free": 1, "bilateral_risk": 22},
    {"country": "HK", "year": 2016, "visitors": 1839, "gdp_source": 321, "exr": 0.70, "flight": 86, "visa_free": 1, "bilateral_risk": 21},
    {"country": "HK", "year": 2017, "visitors": 2231, "gdp_source": 341, "exr": 0.72, "flight": 90, "visa_free": 1, "bilateral_risk": 20},
    {"country": "HK", "year": 2018, "visitors": 2208, "gdp_source": 362, "exr": 0.71, "flight": 95, "visa_free": 1, "bilateral_risk": 20},
    {"country": "HK", "year": 2019, "visitors": 2291, "gdp_source": 363, "exr": 0.72, "flight": 100, "visa_free": 1, "bilateral_risk": 22},
    {"country": "HK", "year": 2022, "visitors": 257, "gdp_source": 360, "exr": 0.60, "flight": 18, "visa_free": 1, "bilateral_risk": 25},
    {"country": "HK", "year": 2023, "visitors": 2114, "gdp_source": 383, "exr": 0.58, "flight": 75, "visa_free": 1, "bilateral_risk": 23},
    {"country": "HK", "year": 2024, "visitors": 2600, "gdp_source": 400, "exr": 0.56, "flight": 88, "visa_free": 1, "bilateral_risk": 22},
    # --- シンガポール SG ---
    {"country": "SG", "year": 2015, "visitors": 308, "gdp_source": 307, "exr": 0.82, "flight": 80, "visa_free": 1, "bilateral_risk": 15},
    {"country": "SG", "year": 2016, "visitors": 362, "gdp_source": 320, "exr": 0.78, "flight": 85, "visa_free": 1, "bilateral_risk": 14},
    {"country": "SG", "year": 2017, "visitors": 404, "gdp_source": 342, "exr": 0.80, "flight": 90, "visa_free": 1, "bilateral_risk": 14},
    {"country": "SG", "year": 2018, "visitors": 437, "gdp_source": 373, "exr": 0.81, "flight": 95, "visa_free": 1, "bilateral_risk": 13},
    {"country": "SG", "year": 2019, "visitors": 492, "gdp_source": 372, "exr": 0.80, "flight": 100, "visa_free": 1, "bilateral_risk": 15},
    {"country": "SG", "year": 2022, "visitors": 115, "gdp_source": 467, "exr": 0.72, "flight": 25, "visa_free": 1, "bilateral_risk": 14},
    {"country": "SG", "year": 2023, "visitors": 469, "gdp_source": 497, "exr": 0.70, "flight": 78, "visa_free": 1, "bilateral_risk": 13},
    {"country": "SG", "year": 2024, "visitors": 585, "gdp_source": 520, "exr": 0.68, "flight": 90, "visa_free": 1, "bilateral_risk": 13},
    # --- ドイツ DE ---
    {"country": "DE", "year": 2015, "visitors": 162, "gdp_source": 3358, "exr": 0.83, "flight": 80, "visa_free": 1, "bilateral_risk": 15},
    {"country": "DE", "year": 2016, "visitors": 183, "gdp_source": 3467, "exr": 0.85, "flight": 85, "visa_free": 1, "bilateral_risk": 14},
    {"country": "DE", "year": 2017, "visitors": 197, "gdp_source": 3665, "exr": 0.87, "flight": 90, "visa_free": 1, "bilateral_risk": 14},
    {"country": "DE", "year": 2018, "visitors": 215, "gdp_source": 3950, "exr": 0.86, "flight": 95, "visa_free": 1, "bilateral_risk": 13},
    {"country": "DE", "year": 2019, "visitors": 236, "gdp_source": 3861, "exr": 0.84, "flight": 100, "visa_free": 1, "bilateral_risk": 15},
    {"country": "DE", "year": 2022, "visitors": 52,  "gdp_source": 4072, "exr": 0.72, "flight": 22, "visa_free": 1, "bilateral_risk": 14},
    {"country": "DE", "year": 2023, "visitors": 212, "gdp_source": 4457, "exr": 0.68, "flight": 72, "visa_free": 1, "bilateral_risk": 13},
    {"country": "DE", "year": 2024, "visitors": 275, "gdp_source": 4520, "exr": 0.65, "flight": 88, "visa_free": 1, "bilateral_risk": 13},
    # --- フランス FR ---
    {"country": "FR", "year": 2015, "visitors": 214, "gdp_source": 2438, "exr": 0.83, "flight": 80, "visa_free": 1, "bilateral_risk": 18},
    {"country": "FR", "year": 2016, "visitors": 254, "gdp_source": 2465, "exr": 0.85, "flight": 85, "visa_free": 1, "bilateral_risk": 17},
    {"country": "FR", "year": 2017, "visitors": 269, "gdp_source": 2586, "exr": 0.87, "flight": 90, "visa_free": 1, "bilateral_risk": 16},
    {"country": "FR", "year": 2018, "visitors": 304, "gdp_source": 2790, "exr": 0.86, "flight": 95, "visa_free": 1, "bilateral_risk": 15},
    {"country": "FR", "year": 2019, "visitors": 336, "gdp_source": 2716, "exr": 0.84, "flight": 100, "visa_free": 1, "bilateral_risk": 18},
    {"country": "FR", "year": 2022, "visitors": 68,  "gdp_source": 2780, "exr": 0.72, "flight": 18, "visa_free": 1, "bilateral_risk": 16},
    {"country": "FR", "year": 2023, "visitors": 305, "gdp_source": 3050, "exr": 0.68, "flight": 72, "visa_free": 1, "bilateral_risk": 15},
    {"country": "FR", "year": 2024, "visitors": 390, "gdp_source": 3130, "exr": 0.65, "flight": 86, "visa_free": 1, "bilateral_risk": 15},
    # --- 英国 GB ---
    {"country": "GB", "year": 2015, "visitors": 258, "gdp_source": 2886, "exr": 0.55, "flight": 80, "visa_free": 1, "bilateral_risk": 16},
    {"country": "GB", "year": 2016, "visitors": 292, "gdp_source": 2660, "exr": 0.48, "flight": 85, "visa_free": 1, "bilateral_risk": 15},
    {"country": "GB", "year": 2017, "visitors": 328, "gdp_source": 2625, "exr": 0.52, "flight": 90, "visa_free": 1, "bilateral_risk": 15},
    {"country": "GB", "year": 2018, "visitors": 374, "gdp_source": 2828, "exr": 0.53, "flight": 95, "visa_free": 1, "bilateral_risk": 14},
    {"country": "GB", "year": 2019, "visitors": 424, "gdp_source": 2830, "exr": 0.52, "flight": 100, "visa_free": 1, "bilateral_risk": 16},
    {"country": "GB", "year": 2022, "visitors": 83,  "gdp_source": 3070, "exr": 0.45, "flight": 20, "visa_free": 1, "bilateral_risk": 15},
    {"country": "GB", "year": 2023, "visitors": 380, "gdp_source": 3340, "exr": 0.44, "flight": 75, "visa_free": 1, "bilateral_risk": 14},
    {"country": "GB", "year": 2024, "visitors": 480, "gdp_source": 3500, "exr": 0.42, "flight": 88, "visa_free": 1, "bilateral_risk": 14},
]

# 直近年データ（将来予測のベースライン用）
_LATEST_YEAR: Dict[str, Dict[str, Any]] = {}
for _r in _BUILTIN_PANEL:
    _c = _r["country"]
    if _c not in _LATEST_YEAR or _r["year"] > _LATEST_YEAR[_c]["year"]:
        _LATEST_YEAR[_c] = dict(_r)


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class FitResult:
    """PPML推定結果"""
    method: str
    n_obs: int
    coefficients: Dict[str, float]
    std_errors: Dict[str, float]
    p_values: Dict[str, float]
    pseudo_r2: float
    aic: float
    bic: float
    converged: bool
    summary_text: str = ""


@dataclass
class BayesianForecast:
    """ベイジアン（モンテカルロ）予測結果"""
    country: str
    months: List[str]           # "2026-01" 形式
    median: List[float]         # 中央値（千人）
    p10: List[float]
    p25: List[float]
    p75: List[float]
    p90: List[float]
    samples: Optional[np.ndarray] = None  # shape (n_samples, n_months)


@dataclass
class GravityPrediction:
    """後方互換: 旧形式の予測結果"""
    source_country: str
    baseline_forecast: float
    elasticities: Dict[str, float]
    r_squared: float
    model_method: str
    scenario_forecast: Optional[float] = None
    scenario_delta_pct: Optional[float] = None


# ===========================================================================
# メインクラス: PPML構造重力モデル
# ===========================================================================
class TourismGravityModel:
    """
    PPML構造重力モデルによる訪日観光需要推定

    - statsmodels Poisson GLM (PPML) でゼロ観測値対応
    - HC3ロバスト標準誤差
    - ソース国固定効果 + 年固定効果
    - フォールバック: 学術文献ベースの事前係数
    """

    # 説明変数の列名（v1.4.0拡張: 余暇proxy + 文化関心proxy）
    _FEATURE_NAMES = [
        "ln_gdp_source", "ln_exr", "ln_flight", "visa_free", "bilateral_risk",
        "leave_utilization", "outbound_propensity", "travel_momentum",
        "ln_restaurant", "ln_lang_learners",
    ]

    def __init__(self) -> None:
        self._coefficients: Optional[Dict[str, float]] = None
        self._vcov: Optional[np.ndarray] = None     # 分散共分散行列
        self._param_names: List[str] = []            # パラメータ名（FE含む）
        self._intercept: float = 0.0
        self._pseudo_r2: float = 0.0
        self._fitted: bool = False
        self._model_method: str = "not_fitted"
        self._glm_result: Any = None
        self._n_obs: int = 0
        # 固定効果ダミーの参照カテゴリ
        self._ref_country: str = "CN"      # ソース国FEの参照
        self._ref_year: int = 2019         # 年FEの参照
        self._source_countries: List[str] = []
        self._years: List[int] = []

    # -----------------------------------------------------------------------
    # パネルデータ → デザイン行列
    # -----------------------------------------------------------------------
    @staticmethod
    def _build_design_matrix(
        panel: List[Dict[str, Any]],
        ref_country: str = "CN",
        ref_year: int = 2019,
    ) -> Tuple[np.ndarray, np.ndarray, List[str], List[str], List[int]]:
        """
        パネルデータからPPML用の (y, X) 行列を構築。

        Returns:
            y: 訪問者数（レベル、千人） shape (N,)
            X: デザイン行列 shape (N, K) ※定数項含む
            col_names: 列名リスト
            countries: 固有の国コード
            years: 固有の年
        """
        # 固有の国・年を取得
        countries = sorted(set(r["country"] for r in panel))
        years = sorted(set(r["year"] for r in panel))

        # FEダミーの対象（参照カテゴリを除く）
        fe_countries = [c for c in countries if c != ref_country]
        fe_years = [y for y in years if y != ref_year]

        y_list = []
        X_list = []

        for row in panel:
            vis = row["visitors"]
            if vis < 0:
                continue
            gdp = max(row["gdp_source"], 1.0)
            exr = max(row["exr"], 0.001)
            flt = max(row["flight"], 1.0)

            # ISO2→ISO3 変換（拡張データ辞書はISO3キー）
            ctry_iso2 = row["country"]
            ctry_iso3 = _ISO2_TO_ISO3.get(ctry_iso2, ctry_iso2)

            # v1.4.0 拡張変数の取得
            leave_util = row.get("leave_utilization",
                                 LEAVE_UTILIZATION.get(ctry_iso3, 0.70))
            outbound_prop = row.get("outbound_propensity",
                                    OUTBOUND_PROPENSITY.get(ctry_iso3, 0.50))
            tmi = row.get("travel_momentum",
                          TRAVEL_MOMENTUM_DEFAULT.get(ctry_iso3, 0.70))
            restaurant = row.get("restaurant_index",
                                 RESTAURANT_INDEX.get(ctry_iso3, 100))
            lang_learners = row.get("lang_learners",
                                    LANGUAGE_LEARNERS.get(ctry_iso3, 50))

            features = [
                1.0,                                  # 定数項
                math.log(gdp),                        # ln_gdp_source
                math.log(exr),                        # ln_exr
                math.log(flt),                        # ln_flight
                float(row["visa_free"]),              # visa_free
                row["bilateral_risk"] / 100.0,        # bilateral_risk (0-1に正規化)
                # v1.4.0 拡張変数
                leave_util,                           # leave_utilization (0-1)
                outbound_prop,                        # outbound_propensity
                tmi,                                  # travel_momentum (0-1)
                math.log(max(restaurant, 1.0)),       # ln_restaurant
                math.log(max(lang_learners, 1.0)),    # ln_lang_learners
            ]
            # ソース国固定効果
            for c in fe_countries:
                features.append(1.0 if row["country"] == c else 0.0)
            # 年固定効果
            for yr in fe_years:
                features.append(1.0 if row["year"] == yr else 0.0)

            y_list.append(float(vis))
            X_list.append(features)

        col_names = ["const", "ln_gdp_source", "ln_exr", "ln_flight",
                      "visa_free", "bilateral_risk",
                      "leave_utilization", "outbound_propensity",
                      "travel_momentum", "ln_restaurant", "ln_lang_learners"]
        col_names += [f"fe_{c}" for c in fe_countries]
        col_names += [f"fe_{yr}" for yr in fe_years]

        return (np.array(y_list), np.array(X_list), col_names,
                countries, years)

    # -----------------------------------------------------------------------
    # fit()
    # -----------------------------------------------------------------------
    def fit(self, panel_data: Optional[List[Dict[str, Any]]] = None) -> FitResult:
        """
        PPML（Poisson GLM）で重力モデルを推定する。

        Args:
            panel_data: 外部パネルデータ。Noneなら内蔵データ使用。

        Returns:
            FitResult
        """
        data = panel_data if panel_data is not None else _BUILTIN_PANEL

        if len(data) < 10:
            logger.warning("訓練データ不足 (N=%d) — 事前係数フォールバック", len(data))
            return self._fallback_priors()

        y, X, col_names, countries, years = self._build_design_matrix(
            data, self._ref_country, self._ref_year
        )
        self._source_countries = list(countries)
        self._years = list(years)

        if len(y) < 10:
            logger.warning("有効観測数不足 (N=%d) — 事前係数フォールバック", len(y))
            return self._fallback_priors()

        try:
            import statsmodels.api as sm
            from statsmodels.genmod.families import Poisson

            # PPML = Poisson GLM + log link
            model = sm.GLM(y, X, family=Poisson())
            result = model.fit(cov_type="HC3", maxiter=100)

            self._glm_result = result
            self._param_names = col_names
            self._n_obs = len(y)

            # 係数の保存
            params = result.params
            self._intercept = float(params[0])
            self._coefficients = {}
            for i, name in enumerate(col_names):
                self._coefficients[name] = float(params[i])

            # 分散共分散行列
            self._vcov = np.array(result.cov_params())

            # McFadden疑似R²
            self._pseudo_r2 = self._calc_pseudo_r2(y, X, result)
            self._model_method = "PPML_HC3"
            self._fitted = True

            # 標準誤差・p値
            se_dict = {col_names[i]: float(result.bse[i]) for i in range(len(col_names))}
            pv_dict = {col_names[i]: float(result.pvalues[i]) for i in range(len(col_names))}

            logger.info(
                "PPML推定完了: pseudo-R²=%.4f, N=%d, AIC=%.1f",
                self._pseudo_r2, len(y), float(result.aic),
            )

            return FitResult(
                method="PPML_HC3",
                n_obs=len(y),
                coefficients=dict(self._coefficients),
                std_errors=se_dict,
                p_values=pv_dict,
                pseudo_r2=self._pseudo_r2,
                aic=float(result.aic),
                bic=float(result.bic),
                converged=True,
                summary_text=str(result.summary()),
            )

        except Exception as e:
            logger.error("PPML推定失敗: %s — 事前係数フォールバック", e)
            return self._fallback_priors()

    # -----------------------------------------------------------------------
    # fit_from_db()
    # -----------------------------------------------------------------------
    def fit_from_db(self) -> FitResult:
        """tourism_stats.db からデータを読んでPPML推定"""
        try:
            from pipeline.tourism.tourism_db import TourismDB
            import sqlite3

            db = TourismDB()
            conn = sqlite3.connect(db.db_path)
            conn.row_factory = sqlite3.Row

            query = """
                SELECT
                    g.source_country AS country,
                    g.year,
                    COALESCE(j.arrivals, 0) AS visitors,
                    g.gdp_source_usd AS gdp_source,
                    g.exchange_rate_jpy AS exr,
                    g.flight_supply_index AS flight,
                    g.visa_free,
                    g.bilateral_risk
                FROM gravity_variables g
                LEFT JOIN japan_inbound j
                    ON g.source_country = j.source_country AND g.year = j.year
                WHERE g.gdp_source_usd IS NOT NULL
                ORDER BY g.source_country, g.year
            """
            rows = conn.execute(query).fetchall()
            conn.close()

            if not rows or len(rows) < 10:
                logger.info("DB データ不足 → 内蔵データにフォールバック")
                return self.fit()

            panel = []
            for r in rows:
                panel.append({
                    "country": _normalize_country(r["country"]),
                    "year": r["year"],
                    "visitors": float(r["visitors"]),
                    "gdp_source": float(r["gdp_source"]) if r["gdp_source"] else 1.0,
                    "exr": float(r["exr"]) if r["exr"] else 1.0,
                    "flight": float(r["flight"]) if r["flight"] else 50,
                    "visa_free": int(r["visa_free"]) if r["visa_free"] is not None else 0,
                    "bilateral_risk": float(r["bilateral_risk"]) if r["bilateral_risk"] else 30,
                })

            return self.fit(panel_data=panel)

        except Exception as e:
            logger.info("DB読み込み失敗 (%s) → 内蔵データにフォールバック", e)
            return self.fit()

    # -----------------------------------------------------------------------
    # _fallback_priors()
    # -----------------------------------------------------------------------
    def _fallback_priors(self) -> FitResult:
        """学術文献ベースの事前係数でフォールバック"""
        self._coefficients = {"const": 3.5}
        self._coefficients.update(COEFFICIENT_PRIORS)
        self._intercept = 3.5
        self._pseudo_r2 = 0.0
        self._model_method = "prior_fallback"
        self._fitted = True
        self._param_names = list(self._coefficients.keys())

        # フォールバック用の近似分散共分散行列（大きめの分散）
        n_params = len(self._param_names)
        self._vcov = np.eye(n_params) * 0.25  # σ=0.5 の事前不確実性

        logger.info("事前係数によるフォールバック初期化完了")

        return FitResult(
            method="prior_fallback",
            n_obs=0,
            coefficients=dict(self._coefficients),
            std_errors={k: 0.5 for k in self._param_names},
            p_values={k: 1.0 for k in self._param_names},
            pseudo_r2=0.0,
            aic=0.0,
            bic=0.0,
            converged=False,
            summary_text="フォールバック: 学術文献ベースの事前係数を使用",
        )

    # -----------------------------------------------------------------------
    # predict_with_uncertainty() — モンテカルロサンプリング
    # -----------------------------------------------------------------------
    def predict_with_uncertainty(
        self,
        source_country: str,
        months: List[str],
        n_samples: int = 1000,
        scenario: Optional[Dict[str, float]] = None,
    ) -> BayesianForecast:
        """
        係数の事後分布からモンテカルロサンプリングで不確実性付き予測。

        Args:
            source_country: ISO2国コード (例: "KR")
            months: ["2026-01", "2026-02", ...] 形式
            n_samples: サンプル数
            scenario: {"ln_gdp_source": 7.5, "ln_exr": 0.8, ...} ショック変数

        Returns:
            BayesianForecast
        """
        if not self._fitted:
            self.fit()

        country = _normalize_country(source_country)
        X_future = self._build_future_X(country, months, scenario or {})

        # 係数ベクトルと共分散行列
        coef_vec = np.array([self._coefficients.get(n, 0.0) for n in self._param_names])
        vcov = self._vcov if self._vcov is not None else np.eye(len(coef_vec)) * 0.25

        # 正規分布から係数サンプリング
        rng = np.random.default_rng(42)
        try:
            coef_samples = rng.multivariate_normal(coef_vec, vcov, size=n_samples)
        except np.linalg.LinAlgError:
            # 共分散行列が正定値でない場合 → 対角近似
            stds = np.sqrt(np.abs(np.diag(vcov)))
            coef_samples = coef_vec + rng.normal(0, 1, (n_samples, len(coef_vec))) * stds

        # 予測: exp(X @ β) で各サンプルの予測値を計算
        # X_future: shape (n_months, n_params)
        # coef_samples: shape (n_samples, n_params)
        log_pred = X_future @ coef_samples.T  # shape (n_months, n_samples)
        # クリッピング（数値安定性）
        log_pred = np.clip(log_pred, -10, 15)
        pred_samples = np.exp(log_pred)  # 千人単位

        # パーセンタイル計算
        median = np.median(pred_samples, axis=1).tolist()
        p10 = np.percentile(pred_samples, 10, axis=1).tolist()
        p25 = np.percentile(pred_samples, 25, axis=1).tolist()
        p75 = np.percentile(pred_samples, 75, axis=1).tolist()
        p90 = np.percentile(pred_samples, 90, axis=1).tolist()

        return BayesianForecast(
            country=source_country,
            months=months,
            median=[round(v, 1) for v in median],
            p10=[round(v, 1) for v in p10],
            p25=[round(v, 1) for v in p25],
            p75=[round(v, 1) for v in p75],
            p90=[round(v, 1) for v in p90],
            samples=pred_samples.T,  # shape (n_samples, n_months)
        )

    # -----------------------------------------------------------------------
    # predict_point()
    # -----------------------------------------------------------------------
    def predict_point(
        self,
        source_country: str,
        year_month: str,
        shock: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        単一月のポイント予測（千人単位）。

        Args:
            source_country: ISO2国コード
            year_month: "2026-07" 形式
            shock: 変数ショック辞書

        Returns:
            予測訪問者数（千人）
        """
        if not self._fitted:
            self.fit()

        country = _normalize_country(source_country)
        X = self._build_future_X(country, [year_month], shock or {})
        coef_vec = np.array([self._coefficients.get(n, 0.0) for n in self._param_names])
        log_pred = float(X[0] @ coef_vec)
        return round(math.exp(np.clip(log_pred, -10, 15)), 1)

    # -----------------------------------------------------------------------
    # decompose_forecast_by_variable()
    # -----------------------------------------------------------------------
    def decompose_forecast_by_variable(
        self,
        source_country: str,
        year_month: str,
    ) -> Dict[str, float]:
        """
        予測値を各説明変数の寄与に分解する。

        exp(Σ β_k * x_k) なので、各変数の寄与 = β_k * x_k を計算し、
        予測値のログスケールでの寄与割合を返す。

        Returns:
            {"ln_gdp_source": 45.2, "ln_exr": 12.1, ...} (%)
        """
        if not self._fitted:
            self.fit()

        country = _normalize_country(source_country)
        X = self._build_future_X(country, [year_month], {})[0]
        coef_vec = np.array([self._coefficients.get(n, 0.0) for n in self._param_names])

        # 各変数の寄与（ログスケール）
        contributions = X * coef_vec
        total = float(np.sum(contributions))

        result = {}
        for i, name in enumerate(self._param_names):
            if name.startswith("fe_") or name == "const":
                continue
            if total != 0:
                result[name] = round(float(contributions[i]) / total * 100, 1)
            else:
                result[name] = 0.0

        return result

    # -----------------------------------------------------------------------
    # _build_future_X()
    # -----------------------------------------------------------------------
    def _build_future_X(
        self,
        country: str,
        months: List[str],
        scenario: Dict[str, float],
    ) -> np.ndarray:
        """
        将来月のデザイン行列を構築。

        Args:
            country: ISO2国コード
            months: ["2026-01", ...] 形式
            scenario: 変数オーバーライド

        Returns:
            X: shape (n_months, n_params)
        """
        latest = _LATEST_YEAR.get(country)
        if latest is None:
            # フォールバック: 平均的な値
            latest = {
                "gdp_source": 5000, "exr": 1.0, "flight": 80,
                "visa_free": 1, "bilateral_risk": 30,
            }

        # ISO2→ISO3 変換（拡張データ辞書はISO3キー）
        country_iso3 = _ISO2_TO_ISO3.get(country, country)

        n_months = len(months)
        n_params = len(self._param_names)
        X = np.zeros((n_months, n_params))

        # ベース値（シナリオでオーバーライド可能）
        gdp = scenario.get("ln_gdp_source", math.log(max(latest["gdp_source"], 1.0)))
        if "ln_gdp_source" not in scenario:
            gdp = math.log(max(latest["gdp_source"], 1.0))
        exr = scenario.get("ln_exr", math.log(max(latest["exr"], 0.001)))
        if "ln_exr" not in scenario:
            exr = math.log(max(latest["exr"], 0.001))
        flt = scenario.get("ln_flight", math.log(max(latest["flight"], 1.0)))
        if "ln_flight" not in scenario:
            flt = math.log(max(latest["flight"], 1.0))
        visa = scenario.get("visa_free", float(latest["visa_free"]))
        bilat = scenario.get("bilateral_risk", latest["bilateral_risk"] / 100.0)
        if "bilateral_risk" not in scenario:
            bilat = latest["bilateral_risk"] / 100.0

        # v1.4.0 拡張変数のベース値
        leave_util = scenario.get("leave_utilization",
                                  LEAVE_UTILIZATION.get(country_iso3, 0.70))
        outbound_prop = scenario.get("outbound_propensity",
                                     OUTBOUND_PROPENSITY.get(country_iso3, 0.50))
        tmi = scenario.get("travel_momentum",
                           TRAVEL_MOMENTUM_DEFAULT.get(country_iso3, 0.70))
        ln_rest = scenario.get("ln_restaurant",
                               math.log(max(RESTAURANT_INDEX.get(country_iso3, 100), 1.0)))
        if "ln_restaurant" not in scenario:
            ln_rest = math.log(max(RESTAURANT_INDEX.get(country_iso3, 100), 1.0))
        ln_lang = scenario.get("ln_lang_learners",
                               math.log(max(LANGUAGE_LEARNERS.get(country_iso3, 50), 1.0)))
        if "ln_lang_learners" not in scenario:
            ln_lang = math.log(max(LANGUAGE_LEARNERS.get(country_iso3, 50), 1.0))

        # ソース国FEと年FEのダミー
        fe_countries = [c for c in self._source_countries if c != self._ref_country]
        fe_years_list = [y for y in self._years if y != self._ref_year]

        for t in range(n_months):
            row = np.zeros(n_params)
            # パラメータ名→インデックスのマッピング
            idx = {name: i for i, name in enumerate(self._param_names)}

            if "const" in idx:
                row[idx["const"]] = 1.0
            if "ln_gdp_source" in idx:
                row[idx["ln_gdp_source"]] = gdp
            if "ln_exr" in idx:
                row[idx["ln_exr"]] = exr
            if "ln_flight" in idx:
                # 年内の月次変動は将来予測では一定と仮定
                row[idx["ln_flight"]] = flt
            if "visa_free" in idx:
                row[idx["visa_free"]] = visa
            if "bilateral_risk" in idx:
                row[idx["bilateral_risk"]] = bilat

            # v1.4.0 拡張変数
            if "leave_utilization" in idx:
                row[idx["leave_utilization"]] = leave_util
            if "outbound_propensity" in idx:
                row[idx["outbound_propensity"]] = outbound_prop
            if "travel_momentum" in idx:
                row[idx["travel_momentum"]] = tmi
            if "ln_restaurant" in idx:
                row[idx["ln_restaurant"]] = ln_rest
            if "ln_lang_learners" in idx:
                row[idx["ln_lang_learners"]] = ln_lang

            # ソース国FE
            fe_name = f"fe_{country}"
            if fe_name in idx:
                row[idx[fe_name]] = 1.0

            # 年FE（将来年は最新年のFEを使用）
            # 予測月から年を取得
            try:
                pred_year = int(months[t][:4])
            except (ValueError, IndexError):
                pred_year = 2026
            # 最も近い年のFEを使用
            closest_fe_year = None
            if fe_years_list:
                closest_fe_year = min(fe_years_list, key=lambda y: abs(y - pred_year))
            if closest_fe_year is not None:
                fe_yr_name = f"fe_{closest_fe_year}"
                if fe_yr_name in idx:
                    row[idx[fe_yr_name]] = 1.0

            X[t] = row

        return X

    # -----------------------------------------------------------------------
    # _calc_pseudo_r2() — McFadden's pseudo R²
    # -----------------------------------------------------------------------
    @staticmethod
    def _calc_pseudo_r2(y: np.ndarray, X: np.ndarray, result: Any) -> float:
        """McFadden's pseudo R² = 1 - LL(model) / LL(null)"""
        try:
            ll_model = result.llf
            # Null モデル: 定数項のみ
            import statsmodels.api as sm
            from statsmodels.genmod.families import Poisson
            X_null = np.ones((len(y), 1))
            null_model = sm.GLM(y, X_null, family=Poisson())
            null_result = null_model.fit()
            ll_null = null_result.llf

            if ll_null == 0:
                return 0.0
            return round(1.0 - ll_model / ll_null, 4)
        except Exception:
            return 0.0

    # -----------------------------------------------------------------------
    # 後方互換メソッド
    # -----------------------------------------------------------------------
    def predict(
        self,
        source_country: str,
        horizon_months: int = 12,
        scenario: Optional[Dict[str, float]] = None,
    ) -> GravityPrediction:
        """後方互換: 旧形式のpredict()"""
        if not self._fitted:
            self.fit()

        country = _normalize_country(source_country)
        # 年間予測
        year = 2026
        months = [f"{year}-{m:02d}" for m in range(1, min(horizon_months + 1, 13))]
        total = sum(self.predict_point(country, m) for m in months)

        elasticities = {}
        for name in self._FEATURE_NAMES:
            elasticities[name] = self._coefficients.get(name, COEFFICIENT_PRIORS.get(name, 0))

        return GravityPrediction(
            source_country=source_country,
            baseline_forecast=round(total, 1),
            elasticities=elasticities,
            r_squared=self._pseudo_r2,
            model_method=self._model_method,
        )

    def get_coefficients(self) -> Dict[str, float]:
        """推定係数を辞書で返す"""
        if not self._fitted:
            self.fit()
        return dict(self._coefficients or {})

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    def summary(self) -> str:
        """モデルのサマリーを文字列で返す"""
        if not self._fitted:
            return "モデル未推定。fit()を先に呼んでください。"

        lines = [
            "=" * 60,
            "PPML構造重力モデル（拡張版）— 推定結果サマリー",
            "=" * 60,
            f"推定手法: {self._model_method}",
            f"観測数: {self._n_obs}",
            f"McFadden pseudo R²: {self._pseudo_r2:.4f}",
            "",
            "--- 主要係数 (10変数) ---",
        ]
        if self._coefficients:
            for name in self._FEATURE_NAMES:
                val = self._coefficients.get(name, 0)
                prior = COEFFICIENT_PRIORS.get(name)
                prior_str = f" (事前値: {prior:.2f})" if prior is not None else ""
                lines.append(f"  {name:24s}: {val:+.4f}{prior_str}")

        if self._glm_result is not None:
            lines.append("")
            lines.append("--- statsmodels サマリー ---")
            lines.append(str(self._glm_result.summary()))

        return "\n".join(lines)
