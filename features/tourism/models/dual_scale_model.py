"""
Dual-Scale 統合モデル — DualScaleModel
========================================
SCRI v1.4.0 TASK 2-C

LSTM構造成分（長期トレンド）と Transformer サイクル成分（季節・短期変動）を
動的重み付けで統合する。

alpha = min(0.3 + 0.05*h, 0.8) でLSTM重みを動的変化:
  - 短期 → Transformer 主導（サイクル・季節を重視）
  - 長期 → LSTM 主導（構造トレンドを重視）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

from .lstm_structural import LSTMStructural
from .transformer_cycle import TourismTransformer

try:
    from ..seasonal_extractor import SeasonalExtractor
except ImportError:
    SeasonalExtractor = None


# ===========================================================================
# データクラス
# ===========================================================================
@dataclass
class DualScaleForecast:
    """Dual-Scale 統合予測結果"""
    country: str
    horizon: int
    # 統合予測
    forecast: np.ndarray           # (horizon,) 千人単位
    forecast_p10: np.ndarray       # (horizon,)
    forecast_p90: np.ndarray       # (horizon,)
    # 成分別
    structural: np.ndarray         # (horizon,) LSTM 構造成分
    cycle_p10: np.ndarray          # (horizon,) Transformer p10
    cycle_p50: np.ndarray          # (horizon,) Transformer p50
    cycle_p90: np.ndarray          # (horizon,) Transformer p90
    # 重み
    alpha_schedule: np.ndarray     # (horizon,) LSTM 重み α(h)
    # メタ情報
    lstm_backend: str = "numpy"    # "torch" or "numpy"
    transformer_backend: str = "numpy"


@dataclass
class BacktestResult:
    """バックテスト結果"""
    country: str
    holdout: int
    actual: np.ndarray             # (holdout,)
    predicted: np.ndarray          # (holdout,)
    mae: float
    mape: float
    rmse: float
    coverage_90: float             # p10-p90 に実績が入る割合


# ===========================================================================
# DualScaleModel
# ===========================================================================
class DualScaleModel:
    """
    LSTM（構造成分）と Transformer（サイクル成分）の Dual-Scale 統合モデル。

    動的重み alpha(h) = min(0.3 + 0.05*h, 0.8):
        - h=0 (直近): alpha=0.30 → Transformer 70%
        - h=10: alpha=0.80 → LSTM 80%
        - h=24: alpha=0.80 → LSTM 80% (上限)

    統合予測 = alpha * LSTM + (1-alpha) * Transformer
    """

    def __init__(
        self,
        alpha_base: float = 0.30,
        alpha_step: float = 0.05,
        alpha_max: float = 0.80,
        lstm_kwargs: Optional[Dict] = None,
        transformer_kwargs: Optional[Dict] = None,
    ) -> None:
        self.alpha_base = alpha_base
        self.alpha_step = alpha_step
        self.alpha_max = alpha_max

        # サブモデル初期化
        self.lstm = LSTMStructural(**(lstm_kwargs or {}))
        self.transformer = TourismTransformer(**(transformer_kwargs or {}))

        if SeasonalExtractor is not None:
            self.seasonal = SeasonalExtractor()
        else:
            self.seasonal = None

        self._fitted = False

        logger.info(
            "DualScaleModel 初期化: alpha=%.2f+%.2f*h (max=%.2f)",
            alpha_base, alpha_step, alpha_max,
        )

    # -----------------------------------------------------------------------
    # fit — 両モデル学習
    # -----------------------------------------------------------------------
    def fit(
        self,
        data: Optional[Dict[str, np.ndarray]] = None,
        tmi_data: Optional[Dict[str, np.ndarray]] = None,
    ) -> None:
        """
        LSTM と Transformer 両方を学習する。

        Args:
            data: {country: ndarray} 月次来訪者数。None なら内蔵データ。
            tmi_data: {country: ndarray} TMI 時系列。LSTM のみ使用。
        """
        logger.info("DualScaleModel 学習開始...")
        self.lstm.fit(data=data, tmi_data=tmi_data)
        self.transformer.fit(data=data)

        if self.seasonal is not None:
            self.seasonal.fit_all_countries()

        self._fitted = True
        logger.info(
            "DualScaleModel 学習完了 — LSTM=%s, Transformer=%s",
            "torch" if self.lstm.is_torch else "numpy",
            "torch" if self.transformer.is_torch else "numpy",
        )

    # -----------------------------------------------------------------------
    # predict — 統合予測
    # -----------------------------------------------------------------------
    def predict(
        self,
        country: str,
        horizon: int = 24,
    ) -> DualScaleForecast:
        """
        Dual-Scale 統合予測を行う。

        Args:
            country: ISO2国コード
            horizon: 予測期間（ヶ月）

        Returns:
            DualScaleForecast
        """
        if not self._fitted:
            self.fit()

        # LSTM 構造成分
        structural = self.lstm.predict(country, horizon)

        # Transformer サイクル成分
        cycle_p10, cycle_p50, cycle_p90 = self.transformer.predict(country, horizon)

        # 動的重みスケジュール
        alpha_schedule = np.array([
            min(self.alpha_base + self.alpha_step * h, self.alpha_max)
            for h in range(horizon)
        ])

        # 統合予測
        forecast = alpha_schedule * structural + (1 - alpha_schedule) * cycle_p50

        # 分位点の統合
        forecast_p10 = alpha_schedule * structural + (1 - alpha_schedule) * cycle_p10
        forecast_p90 = alpha_schedule * structural + (1 - alpha_schedule) * cycle_p90

        # 負値防止
        forecast = np.maximum(forecast, 0.0)
        forecast_p10 = np.maximum(forecast_p10, 0.0)
        forecast_p90 = np.maximum(forecast_p90, forecast)

        return DualScaleForecast(
            country=country,
            horizon=horizon,
            forecast=forecast,
            forecast_p10=forecast_p10,
            forecast_p90=forecast_p90,
            structural=structural,
            cycle_p10=cycle_p10,
            cycle_p50=cycle_p50,
            cycle_p90=cycle_p90,
            alpha_schedule=alpha_schedule,
            lstm_backend="torch" if self.lstm.is_torch else "numpy",
            transformer_backend="torch" if self.transformer.is_torch else "numpy",
        )

    # -----------------------------------------------------------------------
    # backtest — バックテスト
    # -----------------------------------------------------------------------
    def backtest(
        self,
        country: str,
        holdout: int = 12,
    ) -> BacktestResult:
        """
        直近 holdout ヶ月を除いて学習し、予測精度を評価する。

        Args:
            country: ISO2国コード
            holdout: ホールドアウト期間（ヶ月）

        Returns:
            BacktestResult
        """
        # 内蔵データ取得
        full_data = self.lstm.get_monthly_data(country)
        if full_data is None or len(full_data) < holdout + 24:
            logger.warning("%s: データ不足でバックテスト不可", country)
            return BacktestResult(
                country=country,
                holdout=holdout,
                actual=np.array([]),
                predicted=np.array([]),
                mae=float("inf"),
                mape=float("inf"),
                rmse=float("inf"),
                coverage_90=0.0,
            )

        # 訓練/テスト分割
        train_data = full_data[:-holdout]
        actual = full_data[-holdout:]

        # 訓練データのみで学習
        train_dict = {country: train_data}
        temp_lstm = LSTMStructural()
        temp_transformer = TourismTransformer()
        temp_lstm.fit(data=train_dict)
        temp_transformer.fit(data=train_dict)

        # 予測
        structural = temp_lstm.predict(country, holdout)
        cycle_p10, cycle_p50, cycle_p90 = temp_transformer.predict(country, holdout)

        # 統合
        alpha_schedule = np.array([
            min(self.alpha_base + self.alpha_step * h, self.alpha_max)
            for h in range(holdout)
        ])
        predicted = alpha_schedule * structural + (1 - alpha_schedule) * cycle_p50
        predicted = np.maximum(predicted, 0.0)

        pred_p10 = alpha_schedule * structural + (1 - alpha_schedule) * cycle_p10
        pred_p90 = alpha_schedule * structural + (1 - alpha_schedule) * cycle_p90
        pred_p10 = np.maximum(pred_p10, 0.0)
        pred_p90 = np.maximum(pred_p90, predicted)

        # 評価指標
        errors = actual - predicted
        mae = float(np.mean(np.abs(errors)))
        rmse = float(np.sqrt(np.mean(errors ** 2)))

        # MAPE (ゼロ除算回避)
        nonzero = actual > 0
        if nonzero.any():
            mape = float(np.mean(np.abs(errors[nonzero] / actual[nonzero])) * 100)
        else:
            mape = float("inf")

        # 90%カバレッジ
        in_range = (actual >= pred_p10) & (actual <= pred_p90)
        coverage_90 = float(in_range.mean())

        result = BacktestResult(
            country=country,
            holdout=holdout,
            actual=actual,
            predicted=predicted,
            mae=mae,
            mape=mape,
            rmse=rmse,
            coverage_90=coverage_90,
        )

        logger.info(
            "%s バックテスト: MAE=%.1f, MAPE=%.1f%%, RMSE=%.1f, Coverage90=%.0f%%",
            country, mae, mape, rmse, coverage_90 * 100,
        )
        return result

    # -----------------------------------------------------------------------
    # predict_all — 全国一括予測
    # -----------------------------------------------------------------------
    def predict_all(
        self,
        countries: Optional[List[str]] = None,
        horizon: int = 24,
    ) -> Dict[str, DualScaleForecast]:
        """全国の統合予測を一括実行。"""
        if countries is None:
            from .lstm_structural import _ANNUAL_VISITORS
            countries = list(_ANNUAL_VISITORS.keys())

        results = {}
        for c in countries:
            try:
                results[c] = self.predict(c, horizon)
            except Exception as e:
                logger.error("%s: 予測失敗 — %s", c, e)

        logger.info("全%d カ国の Dual-Scale 予測完了", len(results))
        return results

    # -----------------------------------------------------------------------
    # backtest_all — 全国バックテスト
    # -----------------------------------------------------------------------
    def backtest_all(
        self,
        countries: Optional[List[str]] = None,
        holdout: int = 12,
    ) -> Dict[str, BacktestResult]:
        """全国のバックテストを一括実行。"""
        if countries is None:
            from .lstm_structural import _ANNUAL_VISITORS
            countries = list(_ANNUAL_VISITORS.keys())

        results = {}
        for c in countries:
            try:
                results[c] = self.backtest(c, holdout)
            except Exception as e:
                logger.error("%s: バックテスト失敗 — %s", c, e)

        return results

    # -----------------------------------------------------------------------
    # summary — 予測サマリ
    # -----------------------------------------------------------------------
    def summary(self, forecast: DualScaleForecast) -> Dict:
        """予測結果のサマリ辞書を返す。"""
        return {
            "country": forecast.country,
            "horizon": forecast.horizon,
            "lstm_backend": forecast.lstm_backend,
            "transformer_backend": forecast.transformer_backend,
            "annual_forecast_total": float(forecast.forecast.sum()),
            "annual_p10": float(forecast.forecast_p10.sum()),
            "annual_p90": float(forecast.forecast_p90.sum()),
            "peak_month_idx": int(np.argmax(forecast.forecast)),
            "trough_month_idx": int(np.argmin(forecast.forecast)),
            "alpha_range": f"{forecast.alpha_schedule[0]:.2f}-{forecast.alpha_schedule[-1]:.2f}",
        }
