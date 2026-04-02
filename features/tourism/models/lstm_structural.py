"""
LSTM構造成分モデル — LSTMStructural
=====================================
SCRI v1.4.0 TASK 2-A

PyTorch LSTM で長期構造トレンドを推定する。
PyTorch 未インストール時は numpy ベースの指数移動平均 + 線形回帰フォールバック。

入力: 来訪者数 + TMI (input_size=2)
出力: forecast_horizon ヶ月分の構造的需要水準
"""

from __future__ import annotations

import logging
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
# 内蔵訓練データ: 11カ国の2010-2024月次来訪者数（千人）
# ===========================================================================
# 2015-2019 は JNTO 年間値ベース（月次は季節パターン按分）
# 2020-2024 はコロナ影響を反映した推計値
# 2010-2014 は 2015-2019 パターンから逆推定

# 年間来訪者数（千人）
_ANNUAL_VISITORS: Dict[str, Dict[int, float]] = {
    "KR": {
        2010: 2440, 2011: 1660, 2012: 2040, 2013: 2460, 2014: 2760,
        2015: 4000, 2016: 5090, 2017: 7140, 2018: 7540, 2019: 5585,
        2020: 490, 2021: 18, 2022: 1013, 2023: 6960, 2024: 8820,
    },
    "CN": {
        2010: 1410, 2011: 1040, 2012: 1430, 2013: 1314, 2014: 2410,
        2015: 4990, 2016: 6370, 2017: 7355, 2018: 8380, 2019: 9594,
        2020: 1070, 2021: 22, 2022: 189, 2023: 2426, 2024: 6997,
    },
    "TW": {
        2010: 1270, 2011: 994, 2012: 1467, 2013: 2210, 2014: 2830,
        2015: 3680, 2016: 4170, 2017: 4560, 2018: 4757, 2019: 4890,
        2020: 694, 2021: 12, 2022: 332, 2023: 4200, 2024: 5360,
    },
    "US": {
        2010: 727, 2011: 566, 2012: 717, 2013: 799, 2014: 892,
        2015: 1033, 2016: 1243, 2017: 1375, 2018: 1527, 2019: 1724,
        2020: 219, 2021: 43, 2022: 323, 2023: 2045, 2024: 2520,
    },
    "AU": {
        2010: 226, 2011: 163, 2012: 206, 2013: 244, 2014: 303,
        2015: 376, 2016: 445, 2017: 495, 2018: 552, 2019: 621,
        2020: 74, 2021: 12, 2022: 137, 2023: 658, 2024: 840,
    },
    "TH": {
        2010: 214, 2011: 145, 2012: 260, 2013: 454, 2014: 658,
        2015: 797, 2016: 902, 2017: 987, 2018: 1132, 2019: 1319,
        2020: 138, 2021: 4, 2022: 164, 2023: 990, 2024: 1320,
    },
    "HK": {
        2010: 509, 2011: 450, 2012: 482, 2013: 746, 2014: 926,
        2015: 1524, 2016: 1839, 2017: 2231, 2018: 2208, 2019: 2291,
        2020: 346, 2021: 13, 2022: 260, 2023: 2116, 2024: 2700,
    },
    "SG": {
        2010: 181, 2011: 140, 2012: 189, 2013: 189, 2014: 227,
        2015: 309, 2016: 362, 2017: 404, 2018: 437, 2019: 492,
        2020: 59, 2021: 7, 2022: 97, 2023: 571, 2024: 720,
    },
    "DE": {
        2010: 125, 2011: 103, 2012: 116, 2013: 140, 2014: 158,
        2015: 183, 2016: 194, 2017: 196, 2018: 215, 2019: 236,
        2020: 29, 2021: 7, 2022: 60, 2023: 237, 2024: 290,
    },
    "FR": {
        2010: 155, 2011: 115, 2012: 140, 2013: 155, 2014: 178,
        2015: 208, 2016: 253, 2017: 269, 2018: 304, 2019: 336,
        2020: 38, 2021: 6, 2022: 65, 2023: 339, 2024: 410,
    },
    "GB": {
        2010: 184, 2011: 142, 2012: 173, 2013: 192, 2014: 220,
        2015: 258, 2016: 292, 2017: 310, 2018: 334, 2019: 424,
        2020: 52, 2021: 9, 2022: 89, 2023: 380, 2024: 480,
    },
}

# 季節パターン（12ヶ月の相対割合、合計≈12.0に正規化）
_SEASONAL_PATTERN: Dict[str, List[float]] = {
    "KR": [0.88, 0.80, 0.97, 0.93, 0.88, 0.91, 1.01, 1.06, 0.98, 0.91, 0.84, 0.91],
    "CN": [0.96, 0.30, 0.68, 0.89, 0.98, 0.79, 0.85, 0.94, 0.89, 0.98, 0.89, 0.94],
    "TW": [0.94, 0.87, 1.04, 1.01, 0.97, 0.94, 0.99, 1.06, 1.04, 1.01, 0.94, 0.99],
    "US": [0.85, 0.67, 0.91, 0.97, 0.85, 0.76, 0.97, 1.15, 0.91, 0.85, 0.76, 0.85],
    "AU": [0.64, 0.59, 0.73, 0.77, 0.70, 0.82, 1.19, 1.32, 1.01, 0.88, 0.77, 0.73],
    "TH": [0.85, 0.80, 0.95, 1.00, 0.90, 0.85, 1.05, 1.10, 1.00, 1.05, 1.00, 0.95],
    "HK": [0.90, 0.85, 1.00, 0.95, 0.90, 0.95, 1.05, 1.10, 1.00, 0.95, 0.90, 0.95],
    "SG": [0.88, 0.82, 0.98, 0.95, 0.90, 0.92, 1.02, 1.08, 1.00, 0.98, 0.92, 0.95],
    "DE": [0.72, 0.65, 0.90, 1.00, 0.95, 0.85, 1.10, 1.15, 1.05, 1.00, 0.80, 0.75],
    "FR": [0.72, 0.65, 0.90, 1.05, 0.95, 0.85, 1.10, 1.15, 1.05, 1.00, 0.80, 0.72],
    "GB": [0.75, 0.68, 0.92, 1.02, 0.95, 0.88, 1.08, 1.12, 1.02, 0.98, 0.82, 0.78],
}

# デフォルト季節パターン
_DEFAULT_SEASONAL = [0.82, 0.75, 0.95, 1.00, 0.92, 0.88, 1.05, 1.12, 1.00, 0.98, 0.85, 0.82]


def _generate_monthly_series(country: str) -> np.ndarray:
    """
    年間値と季節パターンから月次時系列を生成する。
    2010-2024 = 180ヶ月

    Returns:
        ndarray of shape (180,) — 千人単位
    """
    annual = _ANNUAL_VISITORS.get(country, {})
    seasonal = _SEASONAL_PATTERN.get(country, _DEFAULT_SEASONAL)

    # 季節パターンを合計=12に正規化
    s_arr = np.array(seasonal, dtype=np.float64)
    s_arr = s_arr / s_arr.sum() * 12.0

    months = []
    for year in range(2010, 2025):
        yearly_total = annual.get(year)
        if yearly_total is None:
            # 前年の値で補完
            yearly_total = annual.get(year - 1, 500)

        monthly_base = yearly_total / 12.0
        for m in range(12):
            months.append(monthly_base * s_arr[m])

    return np.array(months, dtype=np.float64)


# ===========================================================================
# PyTorch LSTM モデル定義
# ===========================================================================
if TORCH_AVAILABLE:
    class _LSTMNet(nn.Module):
        """PyTorch LSTM ネットワーク"""

        def __init__(
            self,
            input_size: int = 2,
            hidden_size: int = 64,
            num_layers: int = 2,
            dropout: float = 0.2,
            forecast_horizon: int = 24,
        ):
            super().__init__()
            self.hidden_size = hidden_size
            self.num_layers = num_layers
            self.forecast_horizon = forecast_horizon

            self.lstm = nn.LSTM(
                input_size=input_size,
                hidden_size=hidden_size,
                num_layers=num_layers,
                dropout=dropout if num_layers > 1 else 0.0,
                batch_first=True,
            )
            self.fc = nn.Linear(hidden_size, forecast_horizon)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            """
            Args:
                x: (batch, seq_len, input_size)
            Returns:
                (batch, forecast_horizon)
            """
            # LSTM
            lstm_out, _ = self.lstm(x)
            # 最後のタイムステップの hidden state を使用
            last_hidden = lstm_out[:, -1, :]
            out = self.fc(last_hidden)
            return out


# ===========================================================================
# LSTMStructural — メインクラス
# ===========================================================================
class LSTMStructural:
    """
    LSTM 構造成分モデル。

    PyTorch 版:
        - input_size=2 (来訪者数 + TMI)
        - hidden_size=64, num_layers=2, dropout=0.2
        - Huber Loss, Adam lr=0.001
        - forecast_horizon=24

    Numpy フォールバック版:
        - 指数移動平均 + 線形回帰で構造トレンドを推定
    """

    def __init__(
        self,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        forecast_horizon: int = 24,
        learning_rate: float = 0.001,
        epochs: int = 100,
        seq_len: int = 24,
    ) -> None:
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.forecast_horizon = forecast_horizon
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.seq_len = seq_len

        self._model = None
        self._trained = False
        self._use_torch = TORCH_AVAILABLE

        # 国別の学習済みパラメータ (numpy フォールバック用)
        self._np_params: Dict[str, Dict] = {}

        # 内蔵月次データ
        self._monthly_data: Dict[str, np.ndarray] = {}
        for c in _ANNUAL_VISITORS:
            self._monthly_data[c] = _generate_monthly_series(c)

        logger.info(
            "LSTMStructural 初期化: torch=%s, hidden=%d, horizon=%d",
            self._use_torch, hidden_size, forecast_horizon,
        )

    # -----------------------------------------------------------------------
    # fit — 学習
    # -----------------------------------------------------------------------
    def fit(
        self,
        data: Optional[Dict[str, np.ndarray]] = None,
        tmi_data: Optional[Dict[str, np.ndarray]] = None,
    ) -> None:
        """
        モデルを学習する。

        Args:
            data: {country: ndarray (n_months,)} 来訪者数時系列。
                  None なら内蔵データ使用。
            tmi_data: {country: ndarray (n_months,)} TMI 時系列。
                      None なら定数 0.5 で埋める。
        """
        data = data or self._monthly_data
        self._monthly_data.update(data)

        if self._use_torch:
            self._fit_torch(data, tmi_data)
        else:
            self._fit_numpy(data, tmi_data)

        self._trained = True

    # -----------------------------------------------------------------------
    # predict — 予測
    # -----------------------------------------------------------------------
    def predict(
        self,
        country: str,
        horizon: int = 24,
    ) -> np.ndarray:
        """
        構造的需要水準を予測する。

        Args:
            country: ISO2国コード
            horizon: 予測期間（ヶ月）

        Returns:
            ndarray of shape (horizon,) — 千人単位の構造的需要水準
        """
        if not self._trained:
            # 自動学習
            self.fit()

        if self._use_torch and self._model is not None:
            return self._predict_torch(country, horizon)
        else:
            return self._predict_numpy(country, horizon)

    # =======================================================================
    # PyTorch 実装
    # =======================================================================
    def _fit_torch(
        self,
        data: Dict[str, np.ndarray],
        tmi_data: Optional[Dict[str, np.ndarray]],
    ) -> None:
        """PyTorch LSTM で学習。"""
        if not TORCH_AVAILABLE:
            return self._fit_numpy(data, tmi_data)

        # 訓練データ準備
        X_all, y_all = [], []
        for country, visitors in data.items():
            n = len(visitors)
            if n < self.seq_len + self.forecast_horizon:
                continue

            tmi = tmi_data.get(country) if tmi_data else None
            if tmi is None:
                tmi = np.full(n, 0.5)

            # 正規化
            v_mean, v_std = visitors.mean(), visitors.std() + 1e-8
            v_norm = (visitors - v_mean) / v_std
            t_norm = tmi  # TMI は既に [0, 1]

            # スライディングウィンドウ
            for i in range(n - self.seq_len - self.forecast_horizon + 1):
                x_v = v_norm[i:i + self.seq_len]
                x_t = t_norm[i:i + self.seq_len]
                x = np.stack([x_v, x_t], axis=-1)  # (seq_len, 2)
                y = v_norm[i + self.seq_len:i + self.seq_len + self.forecast_horizon]
                X_all.append(x)
                y_all.append(y)

        if not X_all:
            logger.warning("学習データ不足 — numpy フォールバック")
            return self._fit_numpy(data, tmi_data)

        X_tensor = torch.FloatTensor(np.array(X_all))
        y_tensor = torch.FloatTensor(np.array(y_all))

        # モデル構築
        self._model = _LSTMNet(
            input_size=2,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
            forecast_horizon=self.forecast_horizon,
        )

        optimizer = torch.optim.Adam(self._model.parameters(), lr=self.learning_rate)
        criterion = nn.HuberLoss()

        # 学習
        self._model.train()
        for epoch in range(self.epochs):
            optimizer.zero_grad()
            pred = self._model(X_tensor)
            loss = criterion(pred, y_tensor)
            loss.backward()
            optimizer.step()

            if (epoch + 1) % 20 == 0:
                logger.debug("Epoch %d/%d — loss=%.4f", epoch + 1, self.epochs, loss.item())

        self._model.eval()
        logger.info("PyTorch LSTM 学習完了: %d エポック, 最終loss=%.4f", self.epochs, loss.item())

    def _predict_torch(self, country: str, horizon: int) -> np.ndarray:
        """PyTorch LSTM で予測。"""
        visitors = self._monthly_data.get(country)
        if visitors is None or len(visitors) < self.seq_len:
            return self._predict_numpy(country, horizon)

        v_mean, v_std = visitors.mean(), visitors.std() + 1e-8
        v_norm = (visitors - v_mean) / v_std

        # 末尾 seq_len を入力
        x_v = v_norm[-self.seq_len:]
        x_t = np.full(self.seq_len, 0.5)  # TMI は 0.5 デフォルト
        x = np.stack([x_v, x_t], axis=-1)
        x_tensor = torch.FloatTensor(x).unsqueeze(0)  # (1, seq_len, 2)

        with torch.no_grad():
            pred_norm = self._model(x_tensor).numpy()[0]

        # 逆正規化
        pred = pred_norm * v_std + v_mean

        # horizon 調整
        if len(pred) >= horizon:
            return pred[:horizon]
        else:
            # 線形外挿
            last_val = pred[-1]
            trend = (pred[-1] - pred[0]) / max(len(pred) - 1, 1)
            extra = np.array([last_val + trend * i for i in range(1, horizon - len(pred) + 1)])
            return np.concatenate([pred, extra])

    # =======================================================================
    # Numpy フォールバック実装
    # =======================================================================
    def _fit_numpy(
        self,
        data: Dict[str, np.ndarray],
        tmi_data: Optional[Dict[str, np.ndarray]],
    ) -> None:
        """
        Numpy フォールバック: 指数移動平均 + 線形回帰で構造トレンドを推定。
        """
        for country, visitors in data.items():
            n = len(visitors)
            if n < 12:
                continue

            # 12ヶ月移動平均でトレンド抽出
            kernel = np.ones(12) / 12.0
            if n >= 12:
                trend = np.convolve(visitors, kernel, mode="valid")
            else:
                trend = visitors.copy()

            # 線形回帰: trend = a*t + b
            t = np.arange(len(trend), dtype=np.float64)
            if len(t) >= 2:
                coeffs = np.polyfit(t, trend, 1)
                slope = coeffs[0]
                intercept = coeffs[1]
            else:
                slope = 0.0
                intercept = float(trend[-1]) if len(trend) > 0 else 0.0

            # 指数移動平均 (alpha=0.1)
            ema = np.zeros(n)
            ema[0] = visitors[0]
            alpha_ema = 0.1
            for i in range(1, n):
                ema[i] = alpha_ema * visitors[i] + (1 - alpha_ema) * ema[i - 1]

            self._np_params[country] = {
                "slope": slope,
                "intercept": intercept,
                "last_trend_idx": len(trend) - 1,
                "last_ema": ema[-1],
                "last_visitors": visitors[-1],
                "mean_level": float(visitors[-24:].mean()) if n >= 24 else float(visitors.mean()),
            }

        logger.info("Numpy フォールバック学習完了: %d カ国", len(self._np_params))

    def _predict_numpy(self, country: str, horizon: int) -> np.ndarray:
        """Numpy フォールバック: 線形トレンド外挿。"""
        params = self._np_params.get(country)

        if params is None:
            # 内蔵データで自動学習
            visitors = self._monthly_data.get(country)
            if visitors is not None:
                self._fit_numpy({country: visitors}, None)
                params = self._np_params.get(country)

        if params is None:
            # 完全フォールバック
            logger.warning("%s: 学習データなし — デフォルト予測", country)
            return np.full(horizon, 500.0)

        slope = params["slope"]
        intercept = params["intercept"]
        last_idx = params["last_trend_idx"]
        mean_level = params["mean_level"]

        # 線形トレンド外挿
        future_idx = np.arange(last_idx + 1, last_idx + 1 + horizon)
        forecast = slope * future_idx + intercept

        # 負値防止: 最低でも直近平均の10%
        floor = max(mean_level * 0.1, 1.0)
        forecast = np.maximum(forecast, floor)

        return forecast

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
