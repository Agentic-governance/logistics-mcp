"""
Transformer サイクル成分モデル — TourismTransformer
=====================================================
SCRI v1.4.0 TASK 2-B

Transformer Encoder-Decoder で季節・短期サイクル変動を推定し、
3分位点（p10/p50/p90）を同時予測する。

PyTorch 未インストール時は STL 季節分解 + 線形予測 + ノイズの
numpy フォールバックを使用。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# --- PyTorch 動的インポート ---
try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None
    nn = None


# ===========================================================================
# 内蔵データ（LSTMモジュールと共有）
# ===========================================================================
try:
    from .lstm_structural import (
        _ANNUAL_VISITORS,
        _SEASONAL_PATTERN,
        _DEFAULT_SEASONAL,
        _generate_monthly_series,
    )
except ImportError:
    # スタンドアロン使用時のフォールバック
    _ANNUAL_VISITORS = {}
    _SEASONAL_PATTERN = {}
    _DEFAULT_SEASONAL = [0.82, 0.75, 0.95, 1.00, 0.92, 0.88, 1.05, 1.12, 1.00, 0.98, 0.85, 0.82]

    def _generate_monthly_series(country: str) -> np.ndarray:
        return np.full(180, 500.0)


# ===========================================================================
# カレンダー特徴量
# ===========================================================================

# 月別のカレンダー特徴量: (月番号, 祝日フラグ, 季節sin, 季節cos)
def _calendar_features(horizon: int, start_month: int = 1) -> np.ndarray:
    """
    未来のカレンダー特徴量を生成する。

    Returns:
        ndarray of shape (horizon, 4) — [month_sin, month_cos, holiday_flag, season_flag]
    """
    features = []
    for h in range(horizon):
        month = ((start_month - 1 + h) % 12) + 1
        # 三角関数で月の循環性を表現
        month_sin = math.sin(2 * math.pi * month / 12.0)
        month_cos = math.cos(2 * math.pi * month / 12.0)
        # 祝日フラグ (年末年始=1月, GW=5月, 盆=8月, 春節=2月)
        holiday = 1.0 if month in (1, 2, 5, 8, 12) else 0.0
        # 季節フラグ (桜=3-4月, 紅葉=10-11月)
        season = 1.0 if month in (3, 4, 10, 11) else 0.0
        features.append([month_sin, month_cos, holiday, season])
    return np.array(features, dtype=np.float64)


# ===========================================================================
# PyTorch Transformer モデル定義
# ===========================================================================
if TORCH_AVAILABLE:

    class _PositionalEncoding(nn.Module):
        """位置エンコーディング"""

        def __init__(self, d_model: int, max_len: int = 200):
            super().__init__()
            pe = torch.zeros(max_len, d_model)
            position = torch.arange(0, max_len).unsqueeze(1).float()
            div_term = torch.exp(
                torch.arange(0, d_model, 2).float() * -(math.log(10000.0) / d_model)
            )
            pe[:, 0::2] = torch.sin(position * div_term)
            pe[:, 1::2] = torch.cos(position * div_term)
            pe = pe.unsqueeze(0)  # (1, max_len, d_model)
            self.register_buffer("pe", pe)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return x + self.pe[:, :x.size(1)]

    class _QuantileLoss(nn.Module):
        """Quantile Loss (p10/p50/p90 同時推定)"""

        def __init__(self, quantiles: Tuple[float, ...] = (0.1, 0.5, 0.9)):
            super().__init__()
            self.quantiles = quantiles

        def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
            """
            Args:
                pred: (batch, horizon, n_quantiles)
                target: (batch, horizon)
            """
            losses = []
            for i, q in enumerate(self.quantiles):
                errors = target - pred[:, :, i]
                losses.append(torch.max((q - 1) * errors, q * errors))
            return torch.mean(torch.stack(losses))

    class _TransformerNet(nn.Module):
        """Transformer Encoder-Decoder for tourism cycle forecasting."""

        def __init__(
            self,
            d_model: int = 64,
            nhead: int = 4,
            num_encoder_layers: int = 3,
            num_decoder_layers: int = 3,
            dim_feedforward: int = 256,
            dropout: float = 0.1,
            input_size: int = 1,
            calendar_size: int = 4,
            forecast_horizon: int = 24,
            n_quantiles: int = 3,
        ):
            super().__init__()
            self.d_model = d_model
            self.forecast_horizon = forecast_horizon
            self.n_quantiles = n_quantiles

            # Encoder 入力投影
            self.encoder_proj = nn.Linear(input_size, d_model)
            self.pos_encoder = _PositionalEncoding(d_model)

            # Decoder 入力投影 (カレンダー特徴量)
            self.decoder_proj = nn.Linear(calendar_size, d_model)
            self.pos_decoder = _PositionalEncoding(d_model)

            # Transformer
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=nhead,
                dim_feedforward=dim_feedforward,
                dropout=dropout,
                batch_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_encoder_layers)

            decoder_layer = nn.TransformerDecoderLayer(
                d_model=d_model,
                nhead=nhead,
                dim_feedforward=dim_feedforward,
                dropout=dropout,
                batch_first=True,
            )
            self.decoder = nn.TransformerDecoder(decoder_layer, num_layers=num_decoder_layers)

            # 出力: 3分位点
            self.output_proj = nn.Linear(d_model, n_quantiles)

        def forward(
            self,
            src: torch.Tensor,
            tgt: torch.Tensor,
        ) -> torch.Tensor:
            """
            Args:
                src: (batch, src_len, input_size) — 過去の時系列
                tgt: (batch, tgt_len, calendar_size) — 未来のカレンダー特徴量

            Returns:
                (batch, tgt_len, n_quantiles)
            """
            # Encoder
            enc_input = self.encoder_proj(src)
            enc_input = self.pos_encoder(enc_input)
            memory = self.encoder(enc_input)

            # Decoder
            dec_input = self.decoder_proj(tgt)
            dec_input = self.pos_decoder(dec_input)
            dec_output = self.decoder(dec_input, memory)

            # 出力
            out = self.output_proj(dec_output)
            return out


# ===========================================================================
# TourismTransformer — メインクラス
# ===========================================================================
class TourismTransformer:
    """
    Transformer サイクル成分モデル。

    PyTorch 版:
        - d_model=64, nhead=4
        - num_encoder_layers=3, num_decoder_layers=3
        - Quantile Loss (p10/p50/p90)
        - Encoder: 過去24ヶ月データ
        - Decoder: 未来の既知情報（カレンダー、祝日、季節フラグ）

    Numpy フォールバック版:
        - STL 季節分解 + 線形予測 + ノイズで3分位点を生成
    """

    def __init__(
        self,
        d_model: int = 64,
        nhead: int = 4,
        num_encoder_layers: int = 3,
        num_decoder_layers: int = 3,
        forecast_horizon: int = 24,
        learning_rate: float = 0.001,
        epochs: int = 80,
        context_len: int = 24,
    ) -> None:
        self.d_model = d_model
        self.nhead = nhead
        self.num_encoder_layers = num_encoder_layers
        self.num_decoder_layers = num_decoder_layers
        self.forecast_horizon = forecast_horizon
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.context_len = context_len

        self._model = None
        self._trained = False
        self._use_torch = TORCH_AVAILABLE

        # 国別パラメータ (numpy フォールバック用)
        self._np_params: Dict[str, Dict] = {}

        # 内蔵月次データ
        self._monthly_data: Dict[str, np.ndarray] = {}
        for c in _ANNUAL_VISITORS:
            self._monthly_data[c] = _generate_monthly_series(c)

        logger.info(
            "TourismTransformer 初期化: torch=%s, d_model=%d, horizon=%d",
            self._use_torch, d_model, forecast_horizon,
        )

    # -----------------------------------------------------------------------
    # fit — 学習
    # -----------------------------------------------------------------------
    def fit(
        self,
        data: Optional[Dict[str, np.ndarray]] = None,
    ) -> None:
        """
        モデルを学習する。

        Args:
            data: {country: ndarray (n_months,)} 来訪者数時系列。
                  None なら内蔵データ使用。
        """
        data = data or self._monthly_data
        self._monthly_data.update(data)

        if self._use_torch:
            self._fit_torch(data)
        else:
            self._fit_numpy(data)

        self._trained = True

    # -----------------------------------------------------------------------
    # predict — 予測
    # -----------------------------------------------------------------------
    def predict(
        self,
        country: str,
        horizon: int = 24,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        サイクル成分を予測する。

        Args:
            country: ISO2国コード
            horizon: 予測期間（ヶ月）

        Returns:
            tuple(p10, p50, p90) — 各 ndarray of shape (horizon,) 千人単位
        """
        if not self._trained:
            self.fit()

        if self._use_torch and self._model is not None:
            return self._predict_torch(country, horizon)
        else:
            return self._predict_numpy(country, horizon)

    # =======================================================================
    # PyTorch 実装
    # =======================================================================
    def _fit_torch(self, data: Dict[str, np.ndarray]) -> None:
        """Transformer で学習。"""
        if not TORCH_AVAILABLE:
            return self._fit_numpy(data)

        X_src, X_tgt, y_all = [], [], []

        for country, visitors in data.items():
            n = len(visitors)
            if n < self.context_len + self.forecast_horizon:
                continue

            # 正規化
            v_mean = visitors.mean()
            v_std = visitors.std() + 1e-8
            v_norm = (visitors - v_mean) / v_std

            # スライディングウィンドウ
            for i in range(n - self.context_len - self.forecast_horizon + 1):
                # Encoder 入力: 過去 context_len ヶ月
                src = v_norm[i:i + self.context_len].reshape(-1, 1)

                # Decoder 入力: 未来のカレンダー特徴量
                start_month = ((i + self.context_len) % 12) + 1
                tgt = _calendar_features(self.forecast_horizon, start_month)

                # ターゲット
                y = v_norm[i + self.context_len:i + self.context_len + self.forecast_horizon]

                X_src.append(src)
                X_tgt.append(tgt)
                y_all.append(y)

        if not X_src:
            logger.warning("学習データ不足 — numpy フォールバック")
            return self._fit_numpy(data)

        src_tensor = torch.FloatTensor(np.array(X_src))
        tgt_tensor = torch.FloatTensor(np.array(X_tgt))
        y_tensor = torch.FloatTensor(np.array(y_all))

        # モデル構築
        self._model = _TransformerNet(
            d_model=self.d_model,
            nhead=self.nhead,
            num_encoder_layers=self.num_encoder_layers,
            num_decoder_layers=self.num_decoder_layers,
            input_size=1,
            calendar_size=4,
            forecast_horizon=self.forecast_horizon,
            n_quantiles=3,
        )

        optimizer = torch.optim.Adam(self._model.parameters(), lr=self.learning_rate)
        criterion = _QuantileLoss(quantiles=(0.1, 0.5, 0.9))

        # 学習
        self._model.train()
        for epoch in range(self.epochs):
            optimizer.zero_grad()
            pred = self._model(src_tensor, tgt_tensor)  # (batch, horizon, 3)
            loss = criterion(pred, y_tensor)
            loss.backward()
            optimizer.step()

            if (epoch + 1) % 20 == 0:
                logger.debug("Epoch %d/%d — loss=%.4f", epoch + 1, self.epochs, loss.item())

        self._model.eval()
        logger.info("Transformer 学習完了: %d エポック, 最終loss=%.4f", self.epochs, loss.item())

    def _predict_torch(
        self, country: str, horizon: int
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Transformer で予測。"""
        visitors = self._monthly_data.get(country)
        if visitors is None or len(visitors) < self.context_len:
            return self._predict_numpy(country, horizon)

        v_mean = visitors.mean()
        v_std = visitors.std() + 1e-8
        v_norm = (visitors - v_mean) / v_std

        # 末尾 context_len を入力
        src = v_norm[-self.context_len:].reshape(1, -1, 1)
        src_tensor = torch.FloatTensor(src)

        # カレンダー特徴量
        last_month = (len(visitors) % 12) + 1
        cal = _calendar_features(max(horizon, self.forecast_horizon), last_month)
        tgt_tensor = torch.FloatTensor(cal[:self.forecast_horizon]).unsqueeze(0)

        with torch.no_grad():
            pred_norm = self._model(src_tensor, tgt_tensor).numpy()[0]  # (horizon, 3)

        # 逆正規化
        p10 = pred_norm[:, 0] * v_std + v_mean
        p50 = pred_norm[:, 1] * v_std + v_mean
        p90 = pred_norm[:, 2] * v_std + v_mean

        # horizon 調整
        def _adjust(arr, h):
            if len(arr) >= h:
                return arr[:h]
            trend = (arr[-1] - arr[0]) / max(len(arr) - 1, 1) if len(arr) > 1 else 0
            extra = np.array([arr[-1] + trend * i for i in range(1, h - len(arr) + 1)])
            return np.concatenate([arr, extra])

        return _adjust(p10, horizon), _adjust(p50, horizon), _adjust(p90, horizon)

    # =======================================================================
    # Numpy フォールバック実装
    # =======================================================================
    def _fit_numpy(self, data: Dict[str, np.ndarray]) -> None:
        """
        Numpy フォールバック: STL 季節分解 + 線形予測。
        """
        for country, visitors in data.items():
            n = len(visitors)
            if n < 24:
                continue

            # 12ヶ月移動平均でトレンド抽出
            kernel = np.ones(12) / 12.0
            trend = np.convolve(visitors, kernel, mode="valid")

            # 季節成分: 元データ / トレンド の月別平均
            offset = 6  # convolve "valid" のオフセット
            seasonal = np.ones(12)
            for m in range(12):
                idx = list(range(m, min(n - 11, len(trend)), 12))
                if idx:
                    ratios = []
                    for i in idx:
                        if i < len(trend) and trend[i] > 0:
                            ratios.append(visitors[i + offset] / trend[i])
                    if ratios:
                        seasonal[m] = float(np.mean(ratios))

            # 正規化 (平均=1.0)
            s_mean = seasonal.mean()
            if s_mean > 0:
                seasonal = seasonal / s_mean

            # トレンド線形回帰
            t = np.arange(len(trend), dtype=np.float64)
            if len(t) >= 2:
                coeffs = np.polyfit(t, trend, 1)
                slope, intercept = coeffs[0], coeffs[1]
            else:
                slope, intercept = 0.0, float(trend[-1])

            # 残差の標準偏差 (ノイズ推定)
            fitted = slope * t + intercept
            residuals = trend - fitted
            noise_std = float(np.std(residuals)) if len(residuals) > 1 else 0.0

            self._np_params[country] = {
                "seasonal": seasonal,
                "slope": slope,
                "intercept": intercept,
                "last_trend_idx": len(trend) - 1,
                "noise_std": noise_std,
                "mean_level": float(visitors[-24:].mean()),
            }

        logger.info("Numpy フォールバック (Transformer) 学習完了: %d カ国", len(self._np_params))

    def _predict_numpy(
        self, country: str, horizon: int
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Numpy フォールバック: 季節 × トレンド + ノイズで3分位点。"""
        params = self._np_params.get(country)

        if params is None:
            visitors = self._monthly_data.get(country)
            if visitors is not None:
                self._fit_numpy({country: visitors})
                params = self._np_params.get(country)

        if params is None:
            logger.warning("%s: 学習データなし — デフォルト予測", country)
            base = np.full(horizon, 500.0)
            return base * 0.8, base, base * 1.2

        seasonal = params["seasonal"]
        slope = params["slope"]
        intercept = params["intercept"]
        last_idx = params["last_trend_idx"]
        noise_std = params["noise_std"]
        mean_level = params["mean_level"]

        # トレンド外挿
        future_idx = np.arange(last_idx + 1, last_idx + 1 + horizon)
        trend_forecast = slope * future_idx + intercept

        # 季節性適用
        p50 = np.zeros(horizon)
        visitors = self._monthly_data.get(country)
        if visitors is not None:
            last_month = len(visitors) % 12
        else:
            last_month = 0

        for h in range(horizon):
            month_idx = (last_month + h) % 12
            p50[h] = trend_forecast[h] * seasonal[month_idx]

        # 負値防止
        floor = max(mean_level * 0.05, 1.0)
        p50 = np.maximum(p50, floor)

        # 分位点 (ノイズに基づく)
        # z-score: p10 → -1.28, p90 → +1.28
        p10 = p50 - 1.28 * noise_std * seasonal[np.array([(last_month + h) % 12 for h in range(horizon)])]
        p90 = p50 + 1.28 * noise_std * seasonal[np.array([(last_month + h) % 12 for h in range(horizon)])]

        # 不確実性は horizon が長いほど拡大
        uncertainty_scale = np.array([1.0 + 0.02 * h for h in range(horizon)])
        p10 = p50 - np.abs(p50 - p10) * uncertainty_scale
        p90 = p50 + np.abs(p90 - p50) * uncertainty_scale

        p10 = np.maximum(p10, floor * 0.5)
        p90 = np.maximum(p90, p50)  # p90 >= p50

        return p10, p50, p90

    # -----------------------------------------------------------------------
    # ユーティリティ
    # -----------------------------------------------------------------------
    def get_monthly_data(self, country: str) -> Optional[np.ndarray]:
        """内蔵月次データを返す。"""
        return self._monthly_data.get(country)

    @property
    def is_torch(self) -> bool:
        """PyTorch を使用しているか。"""
        return self._use_torch and self._model is not None
