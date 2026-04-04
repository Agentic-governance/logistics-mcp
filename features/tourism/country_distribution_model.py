"""国別確率分布モデル + モンテカルロ集計 — SCRI v1.5.0
============================================================
各国のインバウンド需要を対数正規確率変数としてモデリングし、
共通ショック（FX）と国別ショック（政治）を組み込んだ
真のモンテカルロ集計で非対称な分布を生成する。

核心思想:
  - 国別サンプルを独立に生成するのではなく、共通FXショックを
    全国に伝播させることで相関構造を自然に表現
  - 合算はサンプルレベルで行い、結果としてp10/p50/p90が
    非対称（p50-p10 ≠ p90-p50）になる
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

# ========================================================================
# 国別リスクパラメータ (8カ国)
# ========================================================================
# base_k: 2024年実績ベースライン（千人/月、年平均月値）
# fx_elas: 為替弾性値（円安1%→需要+X%）
# vol_own: 国固有のボラティリティ（対数空間σ）
# pol_shock_pess: 悲観シナリオ時の政治ショック（対数空間、負値=減少）
COUNTRY_RISK_PARAMS: Dict[str, Dict[str, float]] = {
    "KR": {"base_k": 717, "fx_elas": 0.45, "vol_own": 0.06, "pol_shock_pess": 0.0},
    "CN": {"base_k": 433, "fx_elas": 0.70, "vol_own": 0.10, "pol_shock_pess": -0.27},
    "TW": {"base_k": 400, "fx_elas": 0.50, "vol_own": 0.07, "pol_shock_pess": -0.12},
    "US": {"base_k": 300, "fx_elas": 0.30, "vol_own": 0.08, "pol_shock_pess": 0.0},
    "HK": {"base_k": 109, "fx_elas": 0.55, "vol_own": 0.09, "pol_shock_pess": 0.0},
    "AU": {"base_k":  52, "fx_elas": 0.35, "vol_own": 0.07, "pol_shock_pess": 0.0},
    "TH": {"base_k":  35, "fx_elas": 0.80, "vol_own": 0.11, "pol_shock_pess": 0.0},
    "SG": {"base_k":  32, "fx_elas": 0.40, "vol_own": 0.08, "pol_shock_pess": 0.0},
}

# ========================================================================
# シナリオドライバー定義 (3シナリオ)
# ========================================================================
# fx_mu / fx_sigma: 共通FXショックの対数正規パラメータ
# pol_on: 政治ショックを有効にするか
SCENARIO_DRIVERS: Dict[str, Dict[str, Any]] = {
    "base": {
        "label": "ベース",
        "color": "#4a9eff",
        "fx_mu": 0.0,
        "fx_sigma": 0.04,
        "pol_on": False,
        "description": "現状維持。為替・経済・地政学に大きな変化なし",
    },
    "optimistic": {
        "label": "楽観",
        "color": "#51cf66",
        "fx_mu": 0.12,       # 円安12%程度 → 需要増
        "fx_sigma": 0.05,
        "pol_on": False,
        "description": "円安12-15%、中国GDP+1.5%、フライト増便、日中改善",
    },
    "pessimistic": {
        "label": "悲観",
        "color": "#ff4d4d",
        "fx_mu": -0.07,      # 円高7%程度 → 需要減
        "fx_sigma": 0.06,
        "pol_on": True,       # 政治ショック有効
        "description": "円高5-10%、景気後退、日中悪化-30pt、台湾緊張-15pt",
    },
}

# 月別季節指数（1月=0, 12月=11）— 全国合計の季節パターン
SEASONAL_INDEX = [
    0.92, 0.85, 1.08, 1.10, 1.02, 0.90,
    1.15, 1.08, 0.95, 1.22, 1.05, 1.10,
]

# 非掲載市場のスケールファクター（8カ国以外の寄与分）
OTHER_MARKETS_FACTOR = 1.25


class CountryDistributionModel:
    """国別の対数正規確率変数を生成するモデル

    generate_country_samples() が核心メソッド:
      共通FXショック + 国別政治ショック + 固有ボラティリティ
      → 対数正規サンプル（千人/月）
    """

    def __init__(
        self,
        params: Optional[Dict[str, Dict[str, float]]] = None,
        n_samples: int = 5000,
        seed: Optional[int] = None,
    ):
        self.params = params or COUNTRY_RISK_PARAMS
        self.n_samples = n_samples
        self.rng = np.random.default_rng(seed) if np else None

    def generate_country_samples(
        self,
        country: str,
        scenario: str,
        month_index: int = 0,
        fx_shock_common: Optional[Any] = None,
    ) -> Any:
        """国別サンプルを生成

        Args:
            country: 国コード (KR, CN, TW, ...)
            scenario: シナリオ名 (base, optimistic, pessimistic)
            month_index: 月インデックス（季節効果用、0-20の21ヶ月）
            fx_shock_common: 共通FXショック配列。Noneなら内部生成

        Returns:
            np.ndarray: shape=(n_samples,) の対数正規サンプル（千人）
        """
        if np is None:
            raise RuntimeError("numpy が必要です")

        cp = self.params.get(country)
        if cp is None:
            raise ValueError(f"未対応の国コード: {country}")

        sc = SCENARIO_DRIVERS.get(scenario)
        if sc is None:
            raise ValueError(f"未対応のシナリオ: {scenario}")

        base_k = cp["base_k"]
        fx_elas = cp["fx_elas"]
        vol_own = cp["vol_own"]
        pol_shock = cp.get("pol_shock_pess", 0.0) if sc["pol_on"] else 0.0

        # 季節指数（21ヶ月予測: 2026/04=index0 → 月=4月=index3）
        cal_month = (3 + month_index) % 12  # 0-indexed: 4月=3
        seasonal = SEASONAL_INDEX[cal_month]

        # 共通FXショック（対数空間）
        if fx_shock_common is None:
            fx_shock_common = self.rng.normal(
                sc["fx_mu"], sc["fx_sigma"], size=self.n_samples
            )

        # FXショックの需要インパクト = fx_shock * elasticity
        fx_impact = fx_shock_common * fx_elas

        # 国固有ノイズ（対数空間）
        own_noise = self.rng.normal(0.0, vol_own, size=self.n_samples)

        # 対数空間の合成: log(demand) = log(base*seasonal) + fx_impact + pol_shock + own_noise
        log_mu = math.log(base_k * seasonal)
        log_samples = log_mu + fx_impact + pol_shock + own_noise

        # 対数正規変換
        samples = np.exp(log_samples)

        return samples


class MonteCarloAggregator:
    """モンテカルロ集計器 — 国別サンプルをサンプルレベルで合算

    核心: aggregate_japan_total() が月ごとに
      1. 共通FXショックを1回生成
      2. 各国サンプルを生成（共通ショック伝播）
      3. サンプルレベルで合算（sum across countries）
      4. パーセンタイル計算（非対称な分布が自然に出現）
    """

    def __init__(
        self,
        n_samples: int = 5000,
        seed: Optional[int] = None,
    ):
        self.n_samples = n_samples
        self.seed = seed
        self.rng = np.random.default_rng(seed) if np else None

    def aggregate_japan_total(
        self,
        scenario: str,
        months: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """全国合計のMC集計を実行

        Args:
            scenario: シナリオ名 (base, optimistic, pessimistic)
            months: 月ラベルリスト。Noneなら21ヶ月(2026/04-2027/12)を自動生成

        Returns:
            {
                "scenario": str,
                "label": str,
                "color": str,
                "months": [str, ...],
                "median": [float, ...],
                "p10": [float, ...],
                "p90": [float, ...],
                "p05": [float, ...],
                "p95": [float, ...],
                "total_change_pct": float,
                "distribution_stats": {
                    "asymmetry": [...],
                    "max_uncertainty_month": str,
                    "mean_band_width": float,
                },
            }
        """
        if np is None:
            raise RuntimeError("numpy が必要です")

        if months is None:
            months = []
            for y in (2026, 2027):
                sm = 4 if y == 2026 else 1
                for m in range(sm, 13):
                    months.append(f"{y}/{str(m).zfill(2)}")

        sc = SCENARIO_DRIVERS.get(scenario)
        if sc is None:
            raise ValueError(f"未対応のシナリオ: {scenario}")

        model = CountryDistributionModel(
            n_samples=self.n_samples,
            seed=self.seed,
        )

        medians = []
        p10s = []
        p90s = []
        p05s = []
        p95s = []
        asymmetries = []

        countries = list(COUNTRY_RISK_PARAMS.keys())

        for mi, month_label in enumerate(months):
            # 1. 共通FXショック（月ごとに1回生成 → 全国に伝播）
            fx_shock = self.rng.normal(
                sc["fx_mu"], sc["fx_sigma"], size=self.n_samples
            )

            # 2. 各国サンプル生成
            total_samples = np.zeros(self.n_samples)
            for cc in countries:
                country_samples = model.generate_country_samples(
                    country=cc,
                    scenario=scenario,
                    month_index=mi,
                    fx_shock_common=fx_shock,
                )
                total_samples += country_samples

            # 非掲載市場分を加算
            total_samples *= OTHER_MARKETS_FACTOR

            # 3. パーセンタイル計算
            p05 = float(np.percentile(total_samples, 5))
            p10 = float(np.percentile(total_samples, 10))
            p50 = float(np.percentile(total_samples, 50))
            p90 = float(np.percentile(total_samples, 90))
            p95 = float(np.percentile(total_samples, 95))

            medians.append(round(p50))
            p10s.append(round(p10))
            p90s.append(round(p90))
            p05s.append(round(p05))
            p95s.append(round(p95))

            # 4. 非対称性: (p90-p50) - (p50-p10)
            asym = (p90 - p50) - (p50 - p10)
            asymmetries.append(round(asym, 1))

        # 全体の変化率（ベースラインとの比較）
        base_total = sum(
            cp["base_k"] for cp in COUNTRY_RISK_PARAMS.values()
        ) * OTHER_MARKETS_FACTOR
        median_avg = sum(medians) / len(medians) if medians else base_total
        total_change_pct = round((median_avg - base_total) / base_total * 100.0, 1)

        # 帯幅（p90-p10）の月別変動
        band_widths = [p90s[i] - p10s[i] for i in range(len(months))]
        max_bw_idx = int(np.argmax(band_widths)) if band_widths else 0
        mean_bw = round(sum(band_widths) / len(band_widths), 1) if band_widths else 0.0

        return {
            "scenario": scenario,
            "label": sc["label"],
            "color": sc["color"],
            "description": sc["description"],
            "months": months,
            "median": medians,
            "p10": p10s,
            "p90": p90s,
            "p05": p05s,
            "p95": p95s,
            "total_change_pct": total_change_pct,
            "distribution_stats": {
                "asymmetry": asymmetries,
                "asymmetry_mean": round(sum(asymmetries) / len(asymmetries), 1) if asymmetries else 0.0,
                "is_right_skewed": sum(1 for a in asymmetries if a > 0) > len(asymmetries) / 2,
                "max_uncertainty_month": months[max_bw_idx] if months else "",
                "max_band_width": round(band_widths[max_bw_idx], 1) if band_widths else 0.0,
                "mean_band_width": mean_bw,
                "band_widths": [round(bw, 1) for bw in band_widths],
            },
        }

    def compute_all_three(
        self,
        months: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """3シナリオ全てを計算して統合レスポンスを返す

        Returns:
            {
                "months": [...],
                "scenarios": {
                    "base": {...},
                    "optimistic": {...},
                    "pessimistic": {...},
                },
                "distribution_stats": {
                    "base": {...},
                    "optimistic": {...},
                    "pessimistic": {...},
                },
            }
        """
        results = {}
        dist_stats = {}

        for scenario_name in ("base", "optimistic", "pessimistic"):
            r = self.aggregate_japan_total(scenario=scenario_name, months=months)
            results[scenario_name] = r
            dist_stats[scenario_name] = r["distribution_stats"]

        # 共通月ラベル
        common_months = results["base"]["months"]

        return {
            "months": common_months,
            "scenarios": {
                name: {
                    "label": r["label"],
                    "color": r["color"],
                    "description": r["description"],
                    "median": r["median"],
                    "p10": r["p10"],
                    "p90": r["p90"],
                    "p05": r["p05"],
                    "p95": r["p95"],
                    "total_change_pct": r["total_change_pct"],
                }
                for name, r in results.items()
            },
            "distribution_stats": dist_stats,
        }

    @staticmethod
    def verify_asymmetry(result: Dict[str, Any]) -> Dict[str, Any]:
        """非対称性を検証 — p50-p10 ≠ p90-p50 であることを確認

        Args:
            result: aggregate_japan_total() の戻り値

        Returns:
            {
                "is_asymmetric": bool,
                "months_asymmetric": int,   # 非対称な月数
                "months_total": int,
                "sample_month": str,        # 代表月
                "sample_lower": float,      # p50-p10
                "sample_upper": float,      # p90-p50
                "sample_diff": float,       # |upper - lower|
            }
        """
        asymmetries = result.get("distribution_stats", {}).get("asymmetry", [])
        months = result.get("months", [])
        medians = result.get("median", [])
        p10s = result.get("p10", [])
        p90s = result.get("p90", [])

        n_asym = sum(1 for a in asymmetries if abs(a) > 1.0)

        # 代表月（最も非対称性が大きい月）
        if asymmetries:
            max_idx = max(range(len(asymmetries)), key=lambda i: abs(asymmetries[i]))
            sample_month = months[max_idx] if max_idx < len(months) else ""
            lower = medians[max_idx] - p10s[max_idx] if max_idx < len(medians) else 0
            upper = p90s[max_idx] - medians[max_idx] if max_idx < len(medians) else 0
        else:
            sample_month = ""
            lower = 0
            upper = 0

        return {
            "is_asymmetric": n_asym > 0,
            "months_asymmetric": n_asym,
            "months_total": len(months),
            "sample_month": sample_month,
            "sample_lower": round(lower, 1),
            "sample_upper": round(upper, 1),
            "sample_diff": round(abs(upper - lower), 1),
        }
