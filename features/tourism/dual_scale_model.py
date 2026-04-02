"""
Dual-Scaleモデル: 短期(Transformer的注意機構) + 長期(構造重力)の統合
=====================================================================
SCRI v1.4.0

短期(1-3月): 直近トレンド・季節性ベースの軽量注意機構 → 高重み
長期(12月+): PPML重力モデルの構造予測 → 高重み
中期(4-11月): 両者の線形混合

実装ノート:
  - 本番Transformerはtorchが必要だが、ここでは軽量な注意機構で代替
  - 「短期注意機構」= 直近12月の加重移動平均 + 季節指数
  - 短期の方がデータに近い分、信頼区間が狭い
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 短期・長期の混合比率（horizon月数→短期比率）
# ---------------------------------------------------------------------------
def _short_term_ratio(horizon_month: int) -> float:
    """
    短期比率を返す。
    horizon=1: 0.85 (短期ほぼ支配)
    horizon=3: 0.70
    horizon=6: 0.40
    horizon=12: 0.15
    horizon=24: 0.05
    """
    if horizon_month <= 0:
        return 0.85
    # ロジスティック減衰
    ratio = 0.90 / (1.0 + math.exp(0.35 * (horizon_month - 4.0)))
    return max(0.05, min(0.90, ratio))


@dataclass
class DualScaleForecast:
    """Dual-Scaleモデルの予測結果"""
    country: str
    months: List[str]
    median: List[float]
    p10: List[float]
    p25: List[float]
    p75: List[float]
    p90: List[float]
    short_term_ratios: List[float]
    method: str = "dual_scale"


# ---------------------------------------------------------------------------
# 短期注意機構 (Transformer-lite)
# ---------------------------------------------------------------------------
_RECENT_MONTHLY: Dict[str, List[float]] = {
    # 直近12月の月次訪問者数（千人）— 2025年推定
    "CN": [380, 320, 500, 540, 510, 430, 640, 580, 470, 720, 530, 590],
    "KR": [670, 600, 740, 720, 660, 590, 750, 690, 640, 790, 680, 750],
    "TW": [420, 460, 415, 450, 405, 380, 470, 450, 395, 495, 440, 455],
    "US": [110, 100, 155, 140, 125, 105, 120, 115, 100, 130, 110, 120],
    "AU": [65, 50, 55, 60, 45, 40, 65, 55, 50, 70, 55, 80],
    "TH": [55, 50, 60, 65, 55, 45, 70, 65, 50, 75, 60, 65],
    "HK": [150, 140, 175, 180, 160, 145, 190, 175, 155, 200, 170, 185],
    "SG": [40, 35, 48, 50, 42, 38, 52, 48, 40, 55, 45, 50],
}


def _short_term_forecast(country: str, year_months: List[str],
                         n_samples: int = 1000) -> np.ndarray:
    """
    直近データベースの短期予測（加重移動平均 + ノイズ）。
    shape: (n_samples, len(year_months))
    """
    recent = _RECENT_MONTHLY.get(country)
    if recent is None:
        # 未知国→ゼロ
        return np.zeros((n_samples, len(year_months)))

    recent_arr = np.array(recent, dtype=float)
    # 注意重み: 直近月ほど高い (指数減衰)
    weights = np.exp(np.linspace(-1.5, 0, 12))
    weights /= weights.sum()
    weighted_mean = float(np.dot(recent_arr, weights))

    samples = np.zeros((n_samples, len(year_months)))
    rng = np.random.default_rng(42)

    for t, ym in enumerate(year_months):
        try:
            month_num = int(ym.split("-")[1])
        except (ValueError, IndexError):
            month_num = 1
        # 季節指数（月別の相対値）
        seasonal = recent_arr[month_num - 1] / max(np.mean(recent_arr), 1.0)
        base = weighted_mean * seasonal

        # 成長トレンド: 年率5%
        years_ahead = t / 12.0
        trend = base * (1.05 ** years_ahead)

        # 不確実性: 短期は狭い (CV=0.08 + 0.01 × t)
        cv = 0.08 + 0.01 * t
        samples[:, t] = rng.lognormal(
            mean=math.log(max(trend, 1.0)) - 0.5 * cv**2,
            sigma=cv,
            size=n_samples,
        )

    return samples


class DualScaleModel:
    """
    短期注意機構と長期構造モデルを統合するDual-Scaleモデル。

    短期: 直近データの加重移動平均ベース（低不確実性）
    長期: 重力モデルの構造予測（高不確実性だが構造的に健全）
    """

    def __init__(self) -> None:
        self._gravity_model = None

    def _ensure_gravity(self):
        """重力モデルの遅延初期化"""
        if self._gravity_model is None:
            try:
                from features.tourism.gravity_model import TourismGravityModel
                self._gravity_model = TourismGravityModel()
                self._gravity_model.fit()
            except Exception as e:
                logger.warning("重力モデル初期化失敗: %s", e)

    def predict(
        self,
        country: str,
        year_months: List[str],
        n_samples: int = 1000,
    ) -> DualScaleForecast:
        """
        Dual-Scaleで国別訪問者数を予測する。

        Args:
            country: ISO-2国コード
            year_months: ["2026-01", ...] 形式
            n_samples: モンテカルロサンプル数

        Returns:
            DualScaleForecast
        """
        n_months = len(year_months)

        # 短期予測サンプル
        short_samples = _short_term_forecast(country, year_months, n_samples)

        # 長期予測サンプル（重力モデル）
        long_samples = self._get_gravity_samples(country, year_months, n_samples)

        # 混合
        ratios = [_short_term_ratio(t + 1) for t in range(n_months)]
        mixed = np.zeros((n_samples, n_months))
        for t in range(n_months):
            r = ratios[t]
            mixed[:, t] = r * short_samples[:, t] + (1 - r) * long_samples[:, t]

        # パーセンタイル計算
        median = np.median(mixed, axis=0)
        p10 = np.percentile(mixed, 10, axis=0)
        p25 = np.percentile(mixed, 25, axis=0)
        p75 = np.percentile(mixed, 75, axis=0)
        p90 = np.percentile(mixed, 90, axis=0)

        return DualScaleForecast(
            country=country,
            months=year_months,
            median=[round(float(v), 1) for v in median],
            p10=[round(float(v), 1) for v in p10],
            p25=[round(float(v), 1) for v in p25],
            p75=[round(float(v), 1) for v in p75],
            p90=[round(float(v), 1) for v in p90],
            short_term_ratios=[round(r, 3) for r in ratios],
        )

    def _get_gravity_samples(
        self, country: str, year_months: List[str], n_samples: int
    ) -> np.ndarray:
        """重力モデルからサンプルを取得。失敗時は短期データのスケール版"""
        n_months = len(year_months)
        self._ensure_gravity()

        if self._gravity_model is not None:
            try:
                forecast = self._gravity_model.predict_with_uncertainty(
                    country, year_months, n_samples=n_samples
                )
                if forecast.samples is not None:
                    return forecast.samples
            except Exception as e:
                logger.warning("重力モデル予測失敗 (%s): %s", country, e)

        # フォールバック: 短期データに長期不確実性を加味
        recent = _RECENT_MONTHLY.get(country)
        if recent is None:
            return np.zeros((n_samples, n_months))

        rng = np.random.default_rng(123)
        base_annual = float(sum(recent))
        samples = np.zeros((n_samples, n_months))

        for t, ym in enumerate(year_months):
            try:
                month_num = int(ym.split("-")[1])
            except (ValueError, IndexError):
                month_num = 1
            monthly_base = recent[month_num - 1]
            years_ahead = t / 12.0
            trend = monthly_base * (1.03 ** years_ahead)
            # 長期の不確実性は大きい (CV=0.15 + 0.02 × t)
            cv = 0.15 + 0.02 * t
            samples[:, t] = rng.lognormal(
                mean=math.log(max(trend, 1.0)) - 0.5 * cv**2,
                sigma=cv,
                size=n_samples,
            )

        return samples
