"""
STL季節分解による月次季節指数抽出
====================================
SCRI v1.4.0

statsmodels.tsa.seasonal.STL でコロナ前(2015-2019)の月次パターンを分解し、
12ヶ月の季節指数（平均=1.0）を算出する。

STLが失敗した場合はハードコードのフォールバック季節指数を使用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 内蔵月次データ: 2015-2019（千人単位、JNTO公開データ準拠）
# 2019年は仕様値をそのまま使用。2015-2018は年次成長率から逆算。
# ---------------------------------------------------------------------------

# 2019年実績（仕様提供値）
_MONTHLY_2019: Dict[str, List[float]] = {
    "KR": [680, 620, 750, 720, 680, 700, 780, 820, 760, 700, 650, 700],
    "CN": [730, 230, 520, 680, 750, 600, 650, 720, 680, 750, 680, 720],
    "TW": [380, 350, 420, 410, 390, 380, 400, 430, 420, 410, 380, 400],
    "US": [28, 22, 30, 32, 28, 25, 32, 38, 30, 28, 25, 28],
    "AU": [35, 32, 40, 42, 38, 45, 65, 72, 55, 48, 42, 40],
}

# 年次成長率（2019基準、逆算用）: 各年の対2019比率
_ANNUAL_SCALE: Dict[str, Dict[int, float]] = {
    "KR": {2015: 0.72, 2016: 0.91, 2017: 1.28, 2018: 1.35, 2019: 1.00},
    "CN": {2015: 0.52, 2016: 0.66, 2017: 0.77, 2018: 0.87, 2019: 1.00},
    "TW": {2015: 0.75, 2016: 0.85, 2017: 0.93, 2018: 0.97, 2019: 1.00},
    "US": {2015: 0.60, 2016: 0.72, 2017: 0.80, 2018: 0.89, 2019: 1.00},
    "AU": {2015: 0.61, 2016: 0.72, 2017: 0.79, 2018: 0.89, 2019: 1.00},
}


def _generate_monthly_panel() -> Dict[str, np.ndarray]:
    """
    2015-2019の月次データを生成（60ヶ月の時系列）。

    Returns:
        {country: ndarray of shape (60,)} 千人単位
    """
    result = {}
    for country, m2019 in _MONTHLY_2019.items():
        scales = _ANNUAL_SCALE.get(country, {})
        months = []
        for year in range(2015, 2020):
            scale = scales.get(year, 1.0)
            for m_val in m2019:
                # 年次スケール × 月次パターン + 微小ノイズ
                months.append(m_val * scale)
        result[country] = np.array(months, dtype=np.float64)
    return result


# ---------------------------------------------------------------------------
# フォールバック季節指数（STLが失敗した場合）
# ---------------------------------------------------------------------------
FALLBACK_SEASONAL: Dict[str, Dict[int, float]] = {
    "KR": {1: 0.88, 2: 0.80, 3: 0.97, 4: 0.93, 5: 0.88, 6: 0.91,
           7: 1.01, 8: 1.06, 9: 0.98, 10: 0.91, 11: 0.84, 12: 0.91},
    "CN": {1: 0.96, 2: 0.30, 3: 0.68, 4: 0.89, 5: 0.98, 6: 0.79,
           7: 0.85, 8: 0.94, 9: 0.89, 10: 0.98, 11: 0.89, 12: 0.94},
    "TW": {1: 0.94, 2: 0.87, 3: 1.04, 4: 1.01, 5: 0.97, 6: 0.94,
           7: 0.99, 8: 1.06, 9: 1.04, 10: 1.01, 11: 0.94, 12: 0.99},
    "US": {1: 0.85, 2: 0.67, 3: 0.91, 4: 0.97, 5: 0.85, 6: 0.76,
           7: 0.97, 8: 1.15, 9: 0.91, 10: 0.85, 11: 0.76, 12: 0.85},
    "AU": {1: 0.64, 2: 0.59, 3: 0.73, 4: 0.77, 5: 0.70, 6: 0.82,
           7: 1.19, 8: 1.32, 9: 1.01, 10: 0.88, 11: 0.77, 12: 0.73},
    # その他の国は一般的なパターンを使用
    "TH": {1: 0.85, 2: 0.80, 3: 0.95, 4: 1.00, 5: 0.90, 6: 0.85,
           7: 1.05, 8: 1.10, 9: 1.00, 10: 1.05, 11: 1.00, 12: 0.95},
    "HK": {1: 0.90, 2: 0.85, 3: 1.00, 4: 0.95, 5: 0.90, 6: 0.95,
           7: 1.05, 8: 1.10, 9: 1.00, 10: 0.95, 11: 0.90, 12: 0.95},
    "SG": {1: 0.88, 2: 0.82, 3: 0.98, 4: 0.95, 5: 0.90, 6: 0.92,
           7: 1.02, 8: 1.08, 9: 1.00, 10: 0.98, 11: 0.92, 12: 0.95},
    "DE": {1: 0.72, 2: 0.65, 3: 0.90, 4: 1.00, 5: 0.95, 6: 0.85,
           7: 1.10, 8: 1.15, 9: 1.05, 10: 1.00, 11: 0.80, 12: 0.75},
    "FR": {1: 0.72, 2: 0.65, 3: 0.90, 4: 1.05, 5: 0.95, 6: 0.85,
           7: 1.10, 8: 1.15, 9: 1.05, 10: 1.00, 11: 0.80, 12: 0.72},
    "GB": {1: 0.75, 2: 0.68, 3: 0.92, 4: 1.02, 5: 0.95, 6: 0.88,
           7: 1.08, 8: 1.12, 9: 1.02, 10: 0.98, 11: 0.82, 12: 0.78},
}


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class SeasonalPattern:
    """季節分解結果"""
    country: str
    factors: Dict[int, float]   # {1: 0.72, 2: 0.65, ..., 12: 0.91}
    trend_slope: float          # 月当たりトレンド傾き
    method: str = "STL"         # "STL" or "fallback"


# ===========================================================================
# メインクラス: STL季節分解
# ===========================================================================
class SeasonalExtractor:
    """
    STL (Seasonal and Trend decomposition using Loess) による
    月次季節指数の抽出。

    コロナ前2015-2019データから季節パターンを推定し、
    12ヶ月の季節指数（平均=1.0に正規化）を算出する。
    """

    def __init__(self) -> None:
        self._patterns: Dict[str, SeasonalPattern] = {}
        self._monthly_data: Dict[str, np.ndarray] = _generate_monthly_panel()

    # -----------------------------------------------------------------------
    # fit() — 単一国の季節分解
    # -----------------------------------------------------------------------
    def fit(
        self,
        source_country: str,
        data: Optional[np.ndarray] = None,
        period: int = 12,
    ) -> SeasonalPattern:
        """
        STLで月次データを分解し季節指数を抽出する。

        Args:
            source_country: ISO2国コード
            data: 月次時系列（Noneなら内蔵データ使用）。最低24ヶ月必要。
            period: 季節周期（デフォルト12ヶ月）

        Returns:
            SeasonalPattern
        """
        ts = data if data is not None else self._monthly_data.get(source_country)

        if ts is None or len(ts) < 2 * period:
            logger.info(
                "%s: データ不足 (%d点) — フォールバック季節指数使用",
                source_country, len(ts) if ts is not None else 0,
            )
            return self._fallback_pattern(source_country)

        try:
            from statsmodels.tsa.seasonal import STL
            import pandas as pd

            # pandasのPeriodIndexで月次時系列を構築
            # データは2015-01から開始
            n_months = len(ts)
            start_year = 2015
            dates = pd.period_range(
                start=f"{start_year}-01", periods=n_months, freq="M"
            )
            series = pd.Series(ts, index=dates)

            # STL分解（seasonal=13: 季節窓幅は奇数 >= period+1）
            stl = STL(series, period=period, seasonal=13, robust=True)
            result = stl.fit()

            # 季節成分から12ヶ月の季節指数を計算
            seasonal = result.seasonal.values
            trend = result.trend.values

            # 月別平均の季節成分
            month_seasonal = {}
            for i, val in enumerate(seasonal):
                month_num = (i % 12) + 1  # 1-12
                if month_num not in month_seasonal:
                    month_seasonal[month_num] = []
                month_seasonal[month_num].append(val)

            # 加法的季節成分 → 乗法的季節指数に変換
            # seasonal_factor = 1 + (seasonal_component / mean_level)
            mean_level = np.mean(ts)
            if mean_level <= 0:
                mean_level = 1.0

            factors = {}
            for month_num in range(1, 13):
                vals = month_seasonal.get(month_num, [0])
                avg_seasonal = float(np.mean(vals))
                factors[month_num] = 1.0 + avg_seasonal / mean_level

            # 平均=1.0に正規化
            factor_mean = sum(factors.values()) / 12.0
            if factor_mean > 0:
                for m in factors:
                    factors[m] = round(factors[m] / factor_mean, 4)

            # トレンド傾き（月当たり）
            if len(trend) >= 2:
                trend_slope = float(np.polyfit(range(len(trend)), trend, 1)[0])
            else:
                trend_slope = 0.0

            pattern = SeasonalPattern(
                country=source_country,
                factors=factors,
                trend_slope=round(trend_slope, 2),
                method="STL",
            )
            self._patterns[source_country] = pattern

            logger.info(
                "%s: STL季節分解完了 — ピーク月=%d (%.2f), トラフ月=%d (%.2f)",
                source_country,
                max(factors, key=factors.get),
                max(factors.values()),
                min(factors, key=factors.get),
                min(factors.values()),
            )

            return pattern

        except Exception as e:
            logger.warning("%s: STL分解失敗 (%s) — フォールバック使用", source_country, e)
            return self._fallback_pattern(source_country)

    # -----------------------------------------------------------------------
    # fit_all_countries() — 全国一括推定
    # -----------------------------------------------------------------------
    def fit_all_countries(self) -> Dict[str, SeasonalPattern]:
        """
        内蔵データの全国について季節パターンを一括推定する。
        内蔵データがない国にはフォールバック季節指数を適用。

        Returns:
            {country_code: SeasonalPattern}
        """
        # 内蔵データがある国を推定
        for country in self._monthly_data:
            self.fit(country)

        # フォールバックのみの国を追加
        for country in FALLBACK_SEASONAL:
            if country not in self._patterns:
                self._patterns[country] = self._fallback_pattern(country)

        logger.info("全%d カ国の季節パターン推定完了", len(self._patterns))
        return dict(self._patterns)

    # -----------------------------------------------------------------------
    # apply_seasonal() — ベース予測に季節性を適用
    # -----------------------------------------------------------------------
    def apply_seasonal(
        self,
        base_forecast: float,
        year_month_list: List[str],
        country: str,
    ) -> List[float]:
        """
        年次ベース予測に季節指数を適用して月次予測を生成する。

        ベース予測（年間千人）を12で割って月次ベースとし、
        各月の季節指数を乗じる。

        Args:
            base_forecast: 年間予測値（千人）
            year_month_list: ["2026-01", "2026-02", ...] 形式
            country: ISO2国コード

        Returns:
            各月の予測値（千人）
        """
        pattern = self._patterns.get(country)
        if pattern is None:
            pattern = self.fit(country)

        # 月次ベースライン = 年間 / 12
        monthly_base = base_forecast / 12.0

        result = []
        for ym in year_month_list:
            try:
                month_num = int(ym.split("-")[1])
            except (ValueError, IndexError):
                month_num = 1

            factor = pattern.factors.get(month_num, 1.0)
            result.append(round(monthly_base * factor, 1))

        return result

    # -----------------------------------------------------------------------
    # get_pattern()
    # -----------------------------------------------------------------------
    def get_pattern(self, country: str) -> SeasonalPattern:
        """指定国の季節パターンを取得（未推定なら推定実行）"""
        if country not in self._patterns:
            self.fit(country)
        return self._patterns[country]

    # -----------------------------------------------------------------------
    # _fallback_pattern()
    # -----------------------------------------------------------------------
    def _fallback_pattern(self, country: str) -> SeasonalPattern:
        """フォールバック季節指数を使用"""
        factors = FALLBACK_SEASONAL.get(country)
        if factors is None:
            # 一般的な訪日パターン（桜/紅葉ピーク）
            factors = {
                1: 0.82, 2: 0.75, 3: 0.95, 4: 1.00, 5: 0.92, 6: 0.88,
                7: 1.05, 8: 1.12, 9: 1.00, 10: 0.98, 11: 0.85, 12: 0.82,
            }

        pattern = SeasonalPattern(
            country=country,
            factors=dict(factors),
            trend_slope=0.0,
            method="fallback",
        )
        self._patterns[country] = pattern
        return pattern
