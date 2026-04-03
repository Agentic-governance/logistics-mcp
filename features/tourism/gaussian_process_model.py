# features/tourism/gaussian_process_model.py
# ガウス過程による訪日旅行需要予測 (SCRI v1.5.0)
# gpytorch利用可能時はExactGP、不可時はnumpyフォールバック

import math
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import torch
    import gpytorch
    from gpytorch.kernels import (
        ScaleKernel, RBFKernel, MaternKernel, PeriodicKernel,
    )
    from gpytorch.means import ConstantMean
    from gpytorch.models import ExactGP
    from gpytorch.distributions import MultivariateNormal
    from gpytorch.likelihoods import GaussianLikelihood
    from gpytorch.mlls import ExactMarginalLogLikelihood
    GPYTORCH_AVAILABLE = True
except ImportError:
    GPYTORCH_AVAILABLE = False

from .calendar_events import (
    get_demand_multiplier,
    get_uncertainty_multiplier,
    get_events_for_country_month,
)

logger = logging.getLogger(__name__)

# ── 国別2024年月平均訪日人数 ──
BASE_MONTHLY: Dict[str, int] = {
    "KR": 716_000,
    "CN": 583_000,
    "TW": 430_000,
    "US": 272_000,
    "AU": 53_000,
    "TH": 35_000,
    "HK": 109_000,
    "SG": 45_000,
}

# =====================================================================
# GPytorch版 カーネル & モデル
# =====================================================================
if GPYTORCH_AVAILABLE:

    class TourismGPKernel(gpytorch.kernels.Kernel):
        """
        観光需要向け複合カーネル:
          seasonal (12ヶ月周期) × trend (RBF 3年) + risk (Matern ν=0.5, 3ヶ月) + noise
        """
        is_stationary = False

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            # seasonal: 12ヶ月周期
            self.seasonal = ScaleKernel(
                PeriodicKernel(period_length_prior=None)
            )
            self.seasonal.base_kernel.period_length = 12.0

            # trend: RBF (lengthscale ~36ヶ月 = 3年)
            self.trend = ScaleKernel(RBFKernel())
            self.trend.base_kernel.lengthscale = 36.0

            # risk: Matern ν=0.5 (OU過程) lengthscale ~3ヶ月
            self.risk = ScaleKernel(MaternKernel(nu=0.5))
            self.risk.base_kernel.lengthscale = 3.0

        def forward(self, x1, x2, diag=False, **params):
            seasonal_trend = self.seasonal(x1, x2, diag=diag, **params) * \
                             self.trend(x1, x2, diag=diag, **params)
            risk_cov = self.risk(x1, x2, diag=diag, **params)
            return seasonal_trend + risk_cov

    class TourismGPModel(ExactGP):
        """ExactGP with ConstantMean + TourismGPKernel"""

        def __init__(self, train_x, train_y, likelihood):
            super().__init__(train_x, train_y, likelihood)
            self.mean_module = ConstantMean()
            self.covar_module = TourismGPKernel()

        def forward(self, x):
            mean_x = self.mean_module(x)
            covar_x = self.covar_module(x)
            return MultivariateNormal(mean_x, covar_x)


# =====================================================================
# メインクラス: GaussianProcessInboundModel
# =====================================================================
class GaussianProcessInboundModel:
    """
    ガウス過程ベースの訪日インバウンド需要予測モデル。
    gpytorchが利用可能ならExactGP、不可ならカレンダー+対数正規フォールバック。
    """

    def __init__(self):
        self._models: Dict[str, object] = {}      # country → fitted model/data
        self._likelihoods: Dict[str, object] = {}
        self._fitted: Dict[str, bool] = {}

    # ── fit ──
    def fit(self, country: str, monthly_data: List[float],
            n_iterations: int = 100) -> None:
        """
        月次データで国別GPモデルを学習。
        monthly_data: 時系列順の月次訪日人数リスト
        """
        if GPYTORCH_AVAILABLE:
            self._fit_gp(country, monthly_data, n_iterations)
        else:
            # フォールバック: データを保存しておくだけ
            self._models[country] = {"monthly_data": monthly_data}
            self._fitted[country] = True
            logger.info("GP未利用(gpytorch不可): %s のデータを保存", country)

    def _fit_gp(self, country: str, monthly_data: List[float],
                n_iterations: int) -> None:
        """gpytorch版の学習"""
        n = len(monthly_data)
        train_x = torch.linspace(0, n - 1, n).float()
        train_y = torch.tensor(monthly_data, dtype=torch.float32)

        # 対数スケールで学習
        train_y_log = torch.log(train_y.clamp(min=1.0))

        likelihood = GaussianLikelihood()
        model = TourismGPModel(train_x, train_y_log, likelihood)

        model.train()
        likelihood.train()

        optimizer = torch.optim.Adam(model.parameters(), lr=0.1)
        mll = ExactMarginalLogLikelihood(likelihood, model)

        for i in range(n_iterations):
            optimizer.zero_grad()
            output = model(train_x)
            loss = -mll(output, train_y_log)
            loss.backward()
            optimizer.step()

        self._models[country] = model
        self._likelihoods[country] = likelihood
        self._fitted[country] = True
        logger.info("GPモデル学習完了: %s (%d反復)", country, n_iterations)

    # ── predict ──
    def predict(self, country: str, months: List[int],
                n_samples: int = 1000,
                risk_adjustments: Optional[Dict[int, float]] = None
                ) -> Dict:
        """
        予測: 月リスト → 分布統計量を返す。
        risk_adjustments: {month: multiplier} で外部リスク調整。
        """
        if risk_adjustments is None:
            risk_adjustments = {}

        if GPYTORCH_AVAILABLE and isinstance(self._models.get(country), ExactGP):
            return self._predict_gp(country, months, n_samples, risk_adjustments)
        else:
            return self._calendar_only_fallback(country, months, n_samples,
                                                risk_adjustments)

    def _predict_gp(self, country: str, months: List[int],
                    n_samples: int,
                    risk_adjustments: Dict[int, float]) -> Dict:
        """gpytorch版の予測"""
        model = self._models[country]
        likelihood = self._likelihoods[country]
        model.eval()
        likelihood.eval()

        test_x = torch.tensor(months, dtype=torch.float32)

        with torch.no_grad(), gpytorch.settings.fast_pred_var():
            pred = likelihood(model(test_x))
            mean_log = pred.mean.numpy()
            var_log = pred.variance.numpy()

        # 対数正規分布からサンプル生成
        samples = np.random.lognormal(
            mean=mean_log[:, None],
            sigma=np.sqrt(var_log[:, None]),
            size=(len(months), n_samples),
        )

        # カレンダー効果 + リスク調整の適用
        calendar_effects = {}
        for i, m in enumerate(months):
            month_1based = (m % 12) + 1
            cal_mult = get_demand_multiplier(country, month_1based)
            risk_mult = risk_adjustments.get(m, 1.0)
            samples[i] *= cal_mult * risk_mult
            calendar_effects[m] = {
                "demand_multiplier": cal_mult,
                "uncertainty_multiplier": get_uncertainty_multiplier(
                    country, month_1based),
                "events": [e.name for e in get_events_for_country_month(
                    country, month_1based)],
            }

        # 統計量
        result = {
            "country": country,
            "months": months,
            "median": np.median(samples, axis=1).tolist(),
            "mean": np.mean(samples, axis=1).tolist(),
            "p10": np.percentile(samples, 10, axis=1).tolist(),
            "p25": np.percentile(samples, 25, axis=1).tolist(),
            "p75": np.percentile(samples, 75, axis=1).tolist(),
            "p90": np.percentile(samples, 90, axis=1).tolist(),
            "std": np.std(samples, axis=1).tolist(),
            "uncertainty_by_month": {
                m: float(np.std(samples[i]) / max(np.mean(samples[i]), 1))
                for i, m in enumerate(months)
            },
            "calendar_effects": calendar_effects,
            "model_type": "gpytorch",
        }
        return result

    # ── numpy フォールバック ──
    def _calendar_only_fallback(self, country: str, months: List[int],
                                n_samples: int,
                                risk_adjustments: Dict[int, float]) -> Dict:
        """
        gpytorch不可時のフォールバック:
        国別2024年月平均 × カレンダー倍率 × リスク調整、対数正規分布でパーセンタイル生成
        """
        base = BASE_MONTHLY.get(country, 100_000)
        # ベースライン月次変動 (1-12月、季節パターン)
        seasonal_pattern = np.array([
            0.85, 0.80, 1.10, 1.20, 1.05, 1.00,
            1.05, 0.95, 0.90, 1.10, 1.05, 0.95,
        ])

        all_samples = np.zeros((len(months), n_samples))
        calendar_effects = {}
        uncertainty_by_month = {}

        for i, m in enumerate(months):
            month_1based = ((m - 1) % 12) + 1  # 1-12に正規化
            seasonal = seasonal_pattern[month_1based - 1]

            cal_demand = get_demand_multiplier(country, month_1based)
            cal_uncertainty = get_uncertainty_multiplier(country, month_1based)
            risk_mult = risk_adjustments.get(m, 1.0)

            mu = base * seasonal * cal_demand * risk_mult
            # 不確実性: 基本CV=0.15、カレンダー不確実性で増幅
            sigma_log = 0.15 * cal_uncertainty

            # 対数正規分布でサンプル
            log_mu = math.log(max(mu, 1)) - 0.5 * sigma_log ** 2
            samples = np.random.lognormal(
                mean=log_mu, sigma=sigma_log, size=n_samples
            )
            all_samples[i] = samples

            uncertainty_by_month[m] = float(
                np.std(samples) / max(np.mean(samples), 1)
            )
            calendar_effects[m] = {
                "demand_multiplier": cal_demand,
                "uncertainty_multiplier": cal_uncertainty,
                "events": [e.name for e in get_events_for_country_month(
                    country, month_1based)],
            }

        result = {
            "country": country,
            "months": months,
            "median": np.median(all_samples, axis=1).tolist(),
            "mean": np.mean(all_samples, axis=1).tolist(),
            "p10": np.percentile(all_samples, 10, axis=1).tolist(),
            "p25": np.percentile(all_samples, 25, axis=1).tolist(),
            "p75": np.percentile(all_samples, 75, axis=1).tolist(),
            "p90": np.percentile(all_samples, 90, axis=1).tolist(),
            "std": np.std(all_samples, axis=1).tolist(),
            "uncertainty_by_month": uncertainty_by_month,
            "calendar_effects": calendar_effects,
            "model_type": "numpy_fallback",
        }
        return result


# =====================================================================
# 複数市場集計: MultiMarketGPAggregator
# =====================================================================
class MultiMarketGPAggregator:
    """
    複数市場のGP予測を集計し、訪日総数を予測。
    市場間相関・共通ショック・シナリオ分析を含む。
    """

    # 市場間相関行列 (主要ペア)
    CORRELATION_MATRIX: Dict[Tuple[str, str], float] = {
        ("KR", "TW"): 0.45,
        ("KR", "CN"): 0.40,
        ("CN", "TW"): 0.50,
        ("CN", "HK"): 0.65,
        ("TW", "HK"): 0.55,
        ("US", "AU"): 0.55,
        ("US", "CA"): 0.70,  # 暗黙的 (CAがBASE_MONTHLYにない場合も定義)
        ("US", "GB"): 0.60,
        ("AU", "NZ"): 0.65,
        ("KR", "US"): 0.20,
        ("CN", "US"): 0.15,
        ("SG", "MY"): 0.50,
        ("SG", "TH"): 0.40,
        ("TH", "MY"): 0.35,
    }

    # シナリオ定義
    SCENARIOS = {
        "base": {},
        "optimistic": {
            "all_markets_mult": 1.112,
            "flight_bonus": 1.09,
        },
        "pessimistic": {
            "all_markets_mult": 1.0 / 1.112,  # ~0.899
            "cn_extra_mult": 0.85,
            "cn_growth_mult": 0.90,
        },
    }

    def __init__(self, markets: Optional[List[str]] = None):
        self.markets = markets or list(BASE_MONTHLY.keys())
        self.gp_model = GaussianProcessInboundModel()

    def get_correlation(self, a: str, b: str) -> float:
        """市場ペアの相関を取得 (対称)"""
        if a == b:
            return 1.0
        return self.CORRELATION_MATRIX.get(
            (a, b),
            self.CORRELATION_MATRIX.get((b, a), 0.10)  # デフォルト弱相関
        )

    def predict_japan_total_gp(
        self,
        months: List[int],
        scenario: str = "base",
        n_samples: int = 1000,
    ) -> Dict:
        """
        全市場合計の訪日予測。
        各市場を独立にGP予測 → 共通ショック追加 → シナリオ調整 → 集計。
        """
        scenario_params = self.SCENARIOS.get(scenario, {})
        market_results = {}
        market_samples = {}

        # 各市場の予測
        for mkt in self.markets:
            risk_adj = self._build_risk_adjustments(mkt, months, scenario,
                                                    scenario_params)
            pred = self.gp_model.predict(mkt, months, n_samples=n_samples,
                                         risk_adjustments=risk_adj)
            market_results[mkt] = pred

            # サンプル再生成 (集計用)
            base = BASE_MONTHLY.get(mkt, 100_000)
            samples = np.zeros((len(months), n_samples))
            for i, m in enumerate(months):
                month_1based = ((m - 1) % 12) + 1
                cal_demand = get_demand_multiplier(mkt, month_1based)
                cal_uncertainty = get_uncertainty_multiplier(mkt, month_1based)
                seasonal_pattern = np.array([
                    0.85, 0.80, 1.10, 1.20, 1.05, 1.00,
                    1.05, 0.95, 0.90, 1.10, 1.05, 0.95,
                ])
                seasonal = seasonal_pattern[month_1based - 1]
                risk_mult = risk_adj.get(m, 1.0)

                mu = base * seasonal * cal_demand * risk_mult
                sigma_log = 0.15 * cal_uncertainty
                log_mu = math.log(max(mu, 1)) - 0.5 * sigma_log ** 2
                samples[i] = np.random.lognormal(
                    mean=log_mu, sigma=sigma_log, size=n_samples
                )
            market_samples[mkt] = samples

        # 共通ショック: 全市場に5%の共通変動を追加
        common_shock = np.random.normal(0, 0.05, size=(len(months), n_samples))
        for mkt in self.markets:
            for i in range(len(months)):
                market_samples[mkt][i] *= (1.0 + common_shock[i])

        # 市場間相関の反映 (簡易版: ペア相関で重み付けノイズ混合)
        self._apply_correlations(market_samples, months, n_samples)

        # 集計
        total_samples = np.zeros((len(months), n_samples))
        for mkt in self.markets:
            total_samples += market_samples[mkt]

        result = {
            "scenario": scenario,
            "months": months,
            "markets": self.markets,
            "total": {
                "median": np.median(total_samples, axis=1).tolist(),
                "mean": np.mean(total_samples, axis=1).tolist(),
                "p10": np.percentile(total_samples, 10, axis=1).tolist(),
                "p25": np.percentile(total_samples, 25, axis=1).tolist(),
                "p75": np.percentile(total_samples, 75, axis=1).tolist(),
                "p90": np.percentile(total_samples, 90, axis=1).tolist(),
                "std": np.std(total_samples, axis=1).tolist(),
            },
            "by_market": {
                mkt: {
                    "median": np.median(market_samples[mkt], axis=1).tolist(),
                    "mean": np.mean(market_samples[mkt], axis=1).tolist(),
                    "p10": np.percentile(market_samples[mkt], 10, axis=1).tolist(),
                    "p90": np.percentile(market_samples[mkt], 90, axis=1).tolist(),
                }
                for mkt in self.markets
            },
            "market_details": market_results,
            "common_shock_std": 0.05,
            "model_type": "gpytorch" if GPYTORCH_AVAILABLE else "numpy_fallback",
        }
        return result

    def _build_risk_adjustments(
        self, market: str, months: List[int],
        scenario: str, params: Dict
    ) -> Dict[int, float]:
        """シナリオ別のリスク調整倍率を構築"""
        adj = {}
        for m in months:
            mult = 1.0
            if scenario == "optimistic":
                mult *= params.get("all_markets_mult", 1.0)
                mult *= params.get("flight_bonus", 1.0)
            elif scenario == "pessimistic":
                mult *= params.get("all_markets_mult", 1.0)
                if market == "CN":
                    mult *= params.get("cn_extra_mult", 1.0)
                    mult *= params.get("cn_growth_mult", 1.0)
            adj[m] = mult
        return adj

    def _apply_correlations(
        self,
        market_samples: Dict[str, np.ndarray],
        months: List[int],
        n_samples: int,
    ) -> None:
        """
        市場間相関の簡易反映:
        高相関ペアについて共通ノイズ成分を注入。
        """
        processed = set()
        for (a, b), corr in self.CORRELATION_MATRIX.items():
            if a not in market_samples or b not in market_samples:
                continue
            if (a, b) in processed or (b, a) in processed:
                continue
            processed.add((a, b))

            if corr > 0.3:
                # 相関度に応じた共通ノイズ
                shared_noise = np.random.normal(
                    0, 0.02 * corr, size=(len(months), n_samples)
                )
                market_samples[a] *= (1.0 + shared_noise)
                market_samples[b] *= (1.0 + shared_noise)
