"""
ベイズ更新層 — Sequential Monte Carlo (粒子フィルタ)
====================================================
SCRI v1.4.0

PPMLグラビティモデルの予測分布を事前分布として初期化し、
月次実績データが入手され次第、粒子フィルタで事後分布を逐次更新する。

アルゴリズム:
  1. initialize(): 予測分布 (median, p10, p90) → 正規近似で粒子群を生成
  2. update(): 実績値を尤度関数として粒子の重みを更新
  3. リサンプリング: ESS < N/2 で系統的リサンプリング実行
  4. get_posterior(): 重み付き粒子から事後分位点を返す

参考文献:
  - Doucet et al. (2001) "Sequential Monte Carlo Methods in Practice"
  - Chopin (2002) "A sequential particle filter method for static models"
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class BayesianUpdater:
    """
    Sequential Monte Carlo（粒子フィルタ）による予測分布の逐次更新。

    PPMLグラビティモデルの予測分布を事前分布とし、
    実績値で尤度更新 → リサンプリングを繰り返す。
    """

    def __init__(self, n_particles: int = 1000) -> None:
        """
        Args:
            n_particles: 粒子数（デフォルト1000）。精度とメモリのトレードオフ。
        """
        self.n_particles: int = n_particles
        self.particles: Optional[np.ndarray] = None   # shape (n_particles, n_months)
        self.weights: Optional[np.ndarray] = None      # shape (n_particles,)
        self._n_months: int = 0
        self._update_log: List[Dict[str, Any]] = []    # 更新履歴

    # ------------------------------------------------------------------
    # initialize() — 予測分布から粒子群を生成
    # ------------------------------------------------------------------
    def initialize(self, forecast: Dict[str, List[float]]) -> None:
        """
        予測分布から初期粒子を生成する。

        Args:
            forecast: BayesianForecast互換の辞書。
                      必須キー: 'median', 'p90', 'p10'
                      各値は月別のリスト（千人単位）。

        正規近似:
            μ = median
            σ = (p90 - p10) / 3.29  ← 正規分布の80%区間幅
        """
        mu = np.array(forecast['median'], dtype=np.float64)
        p90 = np.array(forecast['p90'], dtype=np.float64)
        p10 = np.array(forecast['p10'], dtype=np.float64)

        # σ推定: 80%信頼区間の幅から逆算（z_90 - z_10 = 2*1.645 = 3.29）
        sigma = (p90 - p10) / 3.29
        # 最低σを設定（数値安定性 — 予測が非常に狭い場合のガード）
        sigma = np.maximum(sigma, mu * 0.01 + 1.0)

        self._n_months = len(mu)

        # 粒子の生成（各月独立に正規分布からサンプリング）
        rng = np.random.default_rng()
        self.particles = np.zeros((self.n_particles, self._n_months))
        for m in range(self._n_months):
            self.particles[:, m] = rng.normal(mu[m], sigma[m], self.n_particles)

        # 訪問者数は非負
        self.particles = np.maximum(self.particles, 0.0)

        # 均一重み
        self.weights = np.ones(self.n_particles) / self.n_particles
        self._update_log = []

        logger.info(
            "BayesianUpdater初期化: %d粒子, %d月, "
            "μ範囲=[%.0f, %.0f], σ範囲=[%.1f, %.1f]",
            self.n_particles, self._n_months,
            mu.min(), mu.max(), sigma.min(), sigma.max(),
        )

    # ------------------------------------------------------------------
    # update() — 単一月の実績で粒子を更新
    # ------------------------------------------------------------------
    def update(self, actual: float, month_index: int) -> Dict[str, Any]:
        """
        実績値で指定月の粒子重みを更新する。

        Args:
            actual: 実績訪問者数（千人単位）
            month_index: 0始まりの月インデックス

        Returns:
            更新結果の辞書 (ESS, resampled, etc.)

        尤度関数:
            L(粒子|実績) = N(actual | 粒子値, σ_obs)
            σ_obs = max(actual * 0.03, 100)  ← 3%の観測ノイズ、最低100千人
        """
        if self.particles is None or self.weights is None:
            raise RuntimeError("initialize()を先に呼んでください")
        if month_index < 0 or month_index >= self._n_months:
            raise IndexError(
                f"month_index={month_index} は範囲外 (0-{self._n_months - 1})"
            )

        # 観測ノイズ: 実績の3%または100千人のうち大きい方
        sigma_obs = max(actual * 0.03, 100.0)

        # 尤度の計算（正規分布のログ尤度で数値安定性確保）
        diff = actual - self.particles[:, month_index]
        log_likelihoods = -0.5 * (diff / sigma_obs) ** 2
        # オーバーフロー防止: 最大値を引いてからexp
        log_likelihoods -= log_likelihoods.max()
        likelihoods = np.exp(log_likelihoods)

        # 重みの更新
        self.weights *= likelihoods
        weight_sum = self.weights.sum()
        if weight_sum == 0 or not np.isfinite(weight_sum):
            # 完全退化 → 均一重みにリセット
            logger.warning("粒子重みが退化 — 均一重みにリセット")
            self.weights = np.ones(self.n_particles) / self.n_particles
        else:
            self.weights /= weight_sum

        # ESS (Effective Sample Size) の計算
        ess = 1.0 / (self.weights ** 2).sum()
        resampled = False

        # ESS < N/2 でリサンプリング（系統的リサンプリング）
        if ess < self.n_particles / 2:
            self._systematic_resample()
            resampled = True
            ess = float(self.n_particles)  # リサンプリング後はESS=N

        result = {
            "month_index": month_index,
            "actual": actual,
            "sigma_obs": sigma_obs,
            "ess": float(ess),
            "resampled": resampled,
        }
        self._update_log.append(result)

        logger.info(
            "ベイズ更新: month=%d, actual=%.0f, ESS=%.0f%s",
            month_index, actual, ess,
            " (リサンプル)" if resampled else "",
        )
        return result

    # ------------------------------------------------------------------
    # update_batch() — 複数月の実績を一括更新
    # ------------------------------------------------------------------
    def update_batch(self, actuals: List[Optional[float]]) -> List[Dict[str, Any]]:
        """
        複数月の実績を一括更新する。

        Args:
            actuals: 月別の実績リスト。Noneの月はスキップ。
                     例: [1200, 1350, None, 1500, ...]

        Returns:
            各月の更新結果リスト
        """
        results = []
        for i, actual in enumerate(actuals):
            if actual is not None:
                r = self.update(actual, i)
                results.append(r)
        return results

    # ------------------------------------------------------------------
    # get_posterior() — 事後分布の分位点を返す
    # ------------------------------------------------------------------
    def get_posterior(self) -> Dict[str, Any]:
        """
        現在の粒子群と重みから事後分布の分位点を計算する。

        Returns:
            {
                'median': [...],       # 月別中央値
                'p10': [...],          # 10パーセンタイル
                'p25': [...],          # 25パーセンタイル
                'p75': [...],          # 75パーセンタイル
                'p90': [...],          # 90パーセンタイル
                'effective_sample_size': float,
                'n_updates': int,      # 更新回数
            }
        """
        if self.particles is None or self.weights is None:
            raise RuntimeError("initialize()を先に呼んでください")

        # 重み付き分位点の計算
        # numpy の percentile は重みを直接サポートしないので
        # リサンプリング済み粒子の場合は均一重み → 直接 percentile
        # 非リサンプリングの場合は重み付きソートで計算
        median = np.zeros(self._n_months)
        p10 = np.zeros(self._n_months)
        p25 = np.zeros(self._n_months)
        p75 = np.zeros(self._n_months)
        p90 = np.zeros(self._n_months)

        for m in range(self._n_months):
            vals = self.particles[:, m]
            median[m] = self._weighted_percentile(vals, self.weights, 50)
            p10[m] = self._weighted_percentile(vals, self.weights, 10)
            p25[m] = self._weighted_percentile(vals, self.weights, 25)
            p75[m] = self._weighted_percentile(vals, self.weights, 75)
            p90[m] = self._weighted_percentile(vals, self.weights, 90)

        ess = 1.0 / (self.weights ** 2).sum()

        return {
            'median': [round(float(v), 1) for v in median],
            'p10': [round(float(v), 1) for v in p10],
            'p90': [round(float(v), 1) for v in p90],
            'p25': [round(float(v), 1) for v in p25],
            'p75': [round(float(v), 1) for v in p75],
            'effective_sample_size': round(float(ess), 1),
            'n_updates': len(self._update_log),
        }

    # ------------------------------------------------------------------
    # get_update_log() — 更新履歴を返す
    # ------------------------------------------------------------------
    def get_update_log(self) -> List[Dict[str, Any]]:
        """更新履歴を返す"""
        return list(self._update_log)

    # ------------------------------------------------------------------
    # _systematic_resample() — 系統的リサンプリング
    # ------------------------------------------------------------------
    def _systematic_resample(self) -> None:
        """
        系統的リサンプリング（Systematic Resampling）。
        多項リサンプリングより分散が小さい。
        """
        N = self.n_particles
        positions = (np.random.random() + np.arange(N)) / N
        cumsum = np.cumsum(self.weights)
        # 数値誤差対策
        cumsum[-1] = 1.0

        indices = np.searchsorted(cumsum, positions)
        indices = np.clip(indices, 0, N - 1)

        self.particles = self.particles[indices].copy()
        self.weights = np.ones(N) / N

    # ------------------------------------------------------------------
    # _weighted_percentile() — 重み付き分位点
    # ------------------------------------------------------------------
    @staticmethod
    def _weighted_percentile(
        values: np.ndarray,
        weights: np.ndarray,
        percentile: float,
    ) -> float:
        """
        重み付き分位点を計算する。

        Args:
            values: 値の配列
            weights: 重みの配列（合計1に正規化済み想定）
            percentile: 分位点（0-100）

        Returns:
            重み付きパーセンタイル値
        """
        sorted_idx = np.argsort(values)
        sorted_vals = values[sorted_idx]
        sorted_weights = weights[sorted_idx]
        cumsum = np.cumsum(sorted_weights)
        # 正規化
        cumsum /= cumsum[-1]
        target = percentile / 100.0
        idx = np.searchsorted(cumsum, target)
        idx = min(idx, len(sorted_vals) - 1)
        return float(sorted_vals[idx])
