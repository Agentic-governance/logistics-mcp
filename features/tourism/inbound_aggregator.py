"""
ボトムアップ集計エンジン: 国別 → 日本全体 → 都道府県
=======================================================
SCRI v1.4.0

統合パイプライン:
  1. Dual-Scale予測 (短期Transformer + 長期構造) → 国別サンプル
  2. BayesianUpdater (実績による逐次更新) → 事後分布
  3. RiskAdjuster (シナリオ期待損失) → 下方修正
  4. 積み上げ → 日本全体 → 都道府県按分

各モジュールはtry/exceptで囲み、未実装時は既存フォールバック動作を維持。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 都道府県 × 国別シェア行列（宿泊旅行統計 + JNTO地域別データ準拠）
# 各都道府県における国籍別シェア（合計=1.0）
# ---------------------------------------------------------------------------
PREF_SHARE: Dict[str, Dict[str, float]] = {
    "東京": {"KR": 0.18, "CN": 0.30, "TW": 0.12, "HK": 0.06, "US": 0.10,
             "TH": 0.04, "AU": 0.03, "SG": 0.02, "DE": 0.02, "FR": 0.02, "GB": 0.03, "OTHER": 0.08},
    "大阪": {"KR": 0.25, "CN": 0.32, "TW": 0.14, "HK": 0.06, "US": 0.04,
             "TH": 0.03, "AU": 0.02, "SG": 0.02, "DE": 0.01, "FR": 0.01, "GB": 0.02, "OTHER": 0.08},
    "京都": {"KR": 0.15, "CN": 0.28, "TW": 0.15, "HK": 0.05, "US": 0.10,
             "TH": 0.03, "AU": 0.04, "SG": 0.02, "DE": 0.03, "FR": 0.03, "GB": 0.04, "OTHER": 0.08},
    "北海道": {"KR": 0.22, "CN": 0.25, "TW": 0.18, "HK": 0.10, "US": 0.03,
               "TH": 0.06, "AU": 0.04, "SG": 0.03, "DE": 0.01, "FR": 0.01, "GB": 0.01, "OTHER": 0.06},
    "沖縄": {"KR": 0.28, "CN": 0.20, "TW": 0.25, "HK": 0.12, "US": 0.02,
             "TH": 0.03, "AU": 0.02, "SG": 0.02, "DE": 0.01, "FR": 0.01, "GB": 0.01, "OTHER": 0.04},
    "福岡": {"KR": 0.40, "CN": 0.20, "TW": 0.15, "HK": 0.05, "US": 0.03,
             "TH": 0.04, "AU": 0.02, "SG": 0.02, "DE": 0.01, "FR": 0.01, "GB": 0.01, "OTHER": 0.06},
    "愛知": {"KR": 0.15, "CN": 0.35, "TW": 0.10, "HK": 0.05, "US": 0.08,
             "TH": 0.05, "AU": 0.03, "SG": 0.02, "DE": 0.03, "FR": 0.02, "GB": 0.02, "OTHER": 0.10},
    "広島": {"KR": 0.12, "CN": 0.20, "TW": 0.12, "HK": 0.05, "US": 0.15,
             "TH": 0.03, "AU": 0.08, "SG": 0.02, "DE": 0.05, "FR": 0.05, "GB": 0.06, "OTHER": 0.07},
    "千葉": {"KR": 0.18, "CN": 0.32, "TW": 0.12, "HK": 0.06, "US": 0.08,
             "TH": 0.05, "AU": 0.03, "SG": 0.02, "DE": 0.02, "FR": 0.02, "GB": 0.02, "OTHER": 0.08},
    "神奈川": {"KR": 0.16, "CN": 0.28, "TW": 0.12, "HK": 0.05, "US": 0.12,
               "TH": 0.04, "AU": 0.04, "SG": 0.02, "DE": 0.03, "FR": 0.03, "GB": 0.03, "OTHER": 0.08},
}

# ---------------------------------------------------------------------------
# ローカルリスク源（都道府県別の季節リスク要因）
# ---------------------------------------------------------------------------
LOCAL_RISK_SOURCES: Dict[str, Dict[str, Any]] = {
    "沖縄": {
        "typhoon_months": [7, 8, 9, 10],
        "base_typhoon_risk": 0.08,
    },
    "北海道": {
        "snow_months": [12, 1, 2, 3],
        "base_snow_risk": 0.03,
    },
    "東京": {
        "heat_months": [7, 8],
        "base_heat_risk": 0.01,
    },
}

# 全国予測で使用する主要国リスト
_FORECAST_COUNTRIES = ["KR", "CN", "TW", "US", "AU", "TH", "HK", "SG", "DE", "FR", "GB"]


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class JapanForecast:
    """日本全体のインバウンド予測"""
    months: List[str]           # "2026-01" 形式
    median: List[float]         # 中央値（千人）
    p10: List[float]
    p25: List[float]
    p75: List[float]
    p90: List[float]
    by_country: Dict[str, List[float]]   # 国別中央値
    country_samples: Optional[Dict[str, np.ndarray]] = None  # 国別サンプル
    pipeline_info: Optional[Dict[str, Any]] = None  # パイプライン情報


@dataclass
class PrefForecast:
    """都道府県別インバウンド予測"""
    prefecture: str
    months: List[str]
    median: List[float]
    p10: List[float]
    p25: List[float]
    p75: List[float]
    p90: List[float]
    by_country: Dict[str, List[float]]   # 国別中央値


# ===========================================================================
# メインクラス: ボトムアップ集計エンジン
# ===========================================================================
class InboundAggregator:
    """
    国別予測をボトムアップで積み上げ、日本全体および都道府県別の
    インバウンド予測を生成する。

    v1.4.0 パイプライン:
      Dual-Scale → Bayesian更新 → RiskAdjuster → 積み上げ

    不確実性の伝播はモンテカルロサンプリングで実現。
    """

    def __init__(self) -> None:
        self._gravity_model = None
        self._seasonal_extractor = None
        self._dual_scale = None
        self._risk_adjuster = None

    def _ensure_models(self) -> None:
        """遅延初期化: 各モデルをロード（失敗時はNone維持）"""
        if self._gravity_model is None:
            try:
                from features.tourism.gravity_model import TourismGravityModel
                self._gravity_model = TourismGravityModel()
                self._gravity_model.fit()
            except Exception as e:
                logger.warning("重力モデル初期化失敗: %s", e)

        if self._seasonal_extractor is None:
            try:
                from features.tourism.seasonal_extractor import SeasonalExtractor
                self._seasonal_extractor = SeasonalExtractor()
                self._seasonal_extractor.fit_all_countries()
            except Exception as e:
                logger.warning("季節分解器初期化失敗: %s", e)

        if self._dual_scale is None:
            try:
                from features.tourism.dual_scale_model import DualScaleModel
                self._dual_scale = DualScaleModel()
            except Exception as e:
                logger.warning("Dual-Scaleモデル初期化失敗: %s", e)

        if self._risk_adjuster is None:
            try:
                from features.tourism.risk_adjuster import RiskAdjuster
                self._risk_adjuster = RiskAdjuster()
            except Exception as e:
                logger.warning("RiskAdjuster初期化失敗: %s", e)

    # -----------------------------------------------------------------------
    # calculate_japan_total() — 日本全体の予測
    # -----------------------------------------------------------------------
    def calculate_japan_total(
        self,
        year_months: List[str],
        n_samples: int = 1000,
        risk_scenario: str = "base",
        scri_scores: Optional[Dict[str, Dict[str, float]]] = None,
        actuals: Optional[Dict[str, List[Optional[float]]]] = None,
    ) -> JapanForecast:
        """
        Dual-Scale → Bayesian更新 → RiskAdjuster → 積み上げ。

        Args:
            year_months: ["2026-01", "2026-02", ...] 形式
            n_samples: モンテカルロサンプル数
            risk_scenario: "optimistic" / "base" / "pessimistic"
            scri_scores: {country: {dimension: score}} SCRIスコア
            actuals: {country: [actual_or_None, ...]} 実績データ（ベイズ更新用）

        Returns:
            JapanForecast
        """
        self._ensure_models()
        n_months = len(year_months)
        if scri_scores is None:
            scri_scores = {}
        if actuals is None:
            actuals = {}

        pipeline_info = {
            "dual_scale_used": False,
            "bayesian_used": False,
            "risk_adjuster_used": False,
            "countries_processed": [],
        }

        # 国別のサンプル行列を収集
        country_samples: Dict[str, np.ndarray] = {}
        country_medians: Dict[str, List[float]] = {}

        for country in _FORECAST_COUNTRIES:
            try:
                samples = self._predict_country(
                    country, year_months, n_samples, pipeline_info
                )

                # --- Bayesian更新: 実績データがあれば適用 ---
                country_actuals = actuals.get(country)
                if country_actuals and self._can_bayesian():
                    try:
                        samples = self._apply_bayesian(
                            samples, country_actuals, pipeline_info
                        )
                    except Exception as e:
                        logger.warning("%s: ベイズ更新失敗 (%s)", country, e)

                # --- RiskAdjuster: 期待損失による下方修正 ---
                if self._risk_adjuster is not None:
                    try:
                        c_scri = scri_scores.get(country, {})
                        loss_result = self._risk_adjuster.calculate_expected_loss(
                            country, scenario=risk_scenario,
                            current_scri_scores=c_scri,
                        )
                        el = loss_result["expected_loss"]
                        if el > 0:
                            samples = samples * (1.0 - el)
                            pipeline_info["risk_adjuster_used"] = True
                    except Exception as e:
                        logger.warning("%s: リスク調整失敗 (%s)", country, e)

                country_samples[country] = samples
                country_medians[country] = [
                    round(float(np.median(samples[:, t])), 1)
                    for t in range(n_months)
                ]
                pipeline_info["countries_processed"].append(country)

            except Exception as e:
                logger.warning("%s: 予測失敗 (%s) — スキップ", country, e)
                country_samples[country] = np.zeros((n_samples, n_months))
                country_medians[country] = [0.0] * n_months

        # 国別サンプルの積み上げ（独立性を仮定）
        total_samples = np.zeros((n_samples, n_months))
        for country, samples in country_samples.items():
            total_samples += samples

        # パーセンタイル計算
        median = np.median(total_samples, axis=0)
        p10 = np.percentile(total_samples, 10, axis=0)
        p25 = np.percentile(total_samples, 25, axis=0)
        p75 = np.percentile(total_samples, 75, axis=0)
        p90 = np.percentile(total_samples, 90, axis=0)

        logger.info(
            "日本全体予測: %d月間, 中央値合計=%.0f千人, P10-P90=[%.0f, %.0f]",
            n_months, float(np.sum(median)),
            float(np.sum(p10)), float(np.sum(p90)),
        )

        return JapanForecast(
            months=year_months,
            median=[round(float(v), 1) for v in median],
            p10=[round(float(v), 1) for v in p10],
            p25=[round(float(v), 1) for v in p25],
            p75=[round(float(v), 1) for v in p75],
            p90=[round(float(v), 1) for v in p90],
            by_country=country_medians,
            country_samples=country_samples,
            pipeline_info=pipeline_info,
        )

    # -----------------------------------------------------------------------
    # _predict_country() — 国別予測（Dual-Scale優先）
    # -----------------------------------------------------------------------
    def _predict_country(
        self,
        country: str,
        year_months: List[str],
        n_samples: int,
        pipeline_info: dict,
    ) -> np.ndarray:
        """Dual-Scale → 重力モデル → フォールバックの優先順位で予測サンプル取得"""
        n_months = len(year_months)

        # 1) Dual-Scaleモデル
        if self._dual_scale is not None:
            try:
                ds_forecast = self._dual_scale.predict(
                    country, year_months, n_samples=n_samples
                )
                # DualScaleForecastからサンプルを再構成
                # median/p10/p90 から正規近似でサンプル生成
                median_arr = np.array(ds_forecast.median, dtype=float)
                p10_arr = np.array(ds_forecast.p10, dtype=float)
                p90_arr = np.array(ds_forecast.p90, dtype=float)
                sigma = (p90_arr - p10_arr) / 3.29
                sigma = np.maximum(sigma, median_arr * 0.01 + 1.0)

                rng = np.random.default_rng(hash(country) % (2**31))
                samples = np.zeros((n_samples, n_months))
                for m in range(n_months):
                    samples[:, m] = rng.normal(median_arr[m], sigma[m], n_samples)
                samples = np.maximum(samples, 0.0)

                pipeline_info["dual_scale_used"] = True
                return samples
            except Exception as e:
                logger.warning("%s: Dual-Scale予測失敗 (%s) — フォールバック", country, e)

        # 2) 重力モデル + 季節分解
        if self._gravity_model is not None and self._seasonal_extractor is not None:
            try:
                forecast = self._gravity_model.predict_with_uncertainty(
                    country, year_months, n_samples=n_samples
                )
                if forecast.samples is not None:
                    raw_samples = forecast.samples
                else:
                    med = np.array(forecast.median)
                    raw_samples = np.tile(med, (n_samples, 1))

                pattern = self._seasonal_extractor.get_pattern(country)
                seasonal_factors = np.array([
                    pattern.factors.get(int(ym.split("-")[1]), 1.0)
                    for ym in year_months
                ])
                adjusted_samples = raw_samples / 12.0 * seasonal_factors[np.newaxis, :]
                return adjusted_samples
            except Exception as e:
                logger.warning("%s: 重力モデル予測失敗 (%s) — ゼロ", country, e)

        return np.zeros((n_samples, n_months))

    # -----------------------------------------------------------------------
    # _can_bayesian() / _apply_bayesian() — ベイズ更新
    # -----------------------------------------------------------------------
    def _can_bayesian(self) -> bool:
        """BayesianUpdaterが利用可能か"""
        try:
            from features.tourism.bayesian_updater import BayesianUpdater
            return True
        except ImportError:
            return False

    def _apply_bayesian(
        self,
        samples: np.ndarray,
        actuals_list: List[Optional[float]],
        pipeline_info: dict,
    ) -> np.ndarray:
        """
        実績データで予測サンプルをベイズ更新する。

        実績がある月のサンプルを更新し、残りの月は条件付きシフト。
        """
        from features.tourism.bayesian_updater import BayesianUpdater

        n_samples, n_months = samples.shape
        median = np.median(samples, axis=0)
        p10 = np.percentile(samples, 10, axis=0)
        p90 = np.percentile(samples, 90, axis=0)

        updater = BayesianUpdater(n_particles=min(n_samples, 2000))
        forecast_dict = {
            "median": median.tolist(),
            "p10": p10.tolist(),
            "p90": p90.tolist(),
        }
        updater.initialize(forecast_dict)

        # 実績がある月を更新
        updated = False
        for i, actual in enumerate(actuals_list):
            if actual is not None and i < n_months:
                updater.update(actual, i)
                updated = True

        if updated:
            posterior = updater.get_posterior()
            # 事後分布のmedian/p10/p90からサンプルを再構成
            post_median = np.array(posterior["median"], dtype=float)
            post_p10 = np.array(posterior["p10"], dtype=float)
            post_p90 = np.array(posterior["p90"], dtype=float)
            sigma = (post_p90 - post_p10) / 3.29
            sigma = np.maximum(sigma, post_median * 0.01 + 1.0)

            rng = np.random.default_rng(99)
            new_samples = np.zeros_like(samples)
            for m in range(n_months):
                new_samples[:, m] = rng.normal(post_median[m], sigma[m], n_samples)
            new_samples = np.maximum(new_samples, 0.0)

            pipeline_info["bayesian_used"] = True
            return new_samples

        return samples

    # -----------------------------------------------------------------------
    # calculate_prefecture() — 都道府県別予測
    # -----------------------------------------------------------------------
    def calculate_prefecture(
        self,
        pref: str,
        japan_forecast: JapanForecast,
        year_months: List[str],
    ) -> PrefForecast:
        """
        全国予測に都道府県シェアとローカルリスクを適用して都道府県予測を生成。

        Args:
            pref: 都道府県名（例: "東京", "沖縄"）
            japan_forecast: calculate_japan_total()の結果
            year_months: 月リスト

        Returns:
            PrefForecast
        """
        shares = PREF_SHARE.get(pref)
        if shares is None:
            logger.warning("都道府県 '%s' のシェアデータなし — 全国の1%%で近似", pref)
            shares = {c: 0.01 / len(_FORECAST_COUNTRIES) for c in _FORECAST_COUNTRIES}
            shares["OTHER"] = 0.01

        n_months = len(year_months)
        local_risks = self._get_local_risk(pref, year_months)

        # 国別の積み上げ（サンプルベース）
        country_samples = japan_forecast.country_samples
        pref_by_country: Dict[str, List[float]] = {}
        pref_total_samples: Optional[np.ndarray] = None

        if country_samples is not None:
            n_samples = next(iter(country_samples.values())).shape[0]
            pref_total_samples = np.zeros((n_samples, n_months))

            for country in _FORECAST_COUNTRIES:
                share = shares.get(country, 0.0)
                if country in country_samples and share > 0:
                    c_samples = country_samples[country] * share
                    # ローカルリスク補正
                    for t in range(n_months):
                        c_samples[:, t] *= (1.0 - local_risks[t])
                    pref_total_samples += c_samples
                    pref_by_country[country] = [
                        round(float(np.median(c_samples[:, t])), 1)
                        for t in range(n_months)
                    ]
                else:
                    pref_by_country[country] = [0.0] * n_months

            # OTHER成分（全国中央値 × OTHERシェア）
            other_share = shares.get("OTHER", 0.0)
            if other_share > 0:
                other_med = np.array(japan_forecast.median) * other_share
                for t in range(n_months):
                    other_med[t] *= (1.0 - local_risks[t])
                pref_total_samples += np.tile(other_med, (n_samples, 1))

            # パーセンタイル
            median = np.median(pref_total_samples, axis=0)
            p10 = np.percentile(pref_total_samples, 10, axis=0)
            p25 = np.percentile(pref_total_samples, 25, axis=0)
            p75 = np.percentile(pref_total_samples, 75, axis=0)
            p90 = np.percentile(pref_total_samples, 90, axis=0)
        else:
            # サンプルがない場合 — 中央値ベースで計算
            total_share = sum(shares.get(c, 0) for c in _FORECAST_COUNTRIES) + shares.get("OTHER", 0)
            pref_median = []
            for t in range(n_months):
                val = japan_forecast.median[t] * total_share * (1.0 - local_risks[t])
                pref_median.append(round(val, 1))

            median = np.array(pref_median)
            # 不確実性は全国の比率を適用
            scale_10 = np.array(japan_forecast.p10) / np.maximum(np.array(japan_forecast.median), 1)
            scale_90 = np.array(japan_forecast.p90) / np.maximum(np.array(japan_forecast.median), 1)
            p10 = median * scale_10
            p25 = median * (scale_10 + 1) / 2
            p75 = median * (1 + scale_90) / 2
            p90 = median * scale_90

            for country in _FORECAST_COUNTRIES:
                share = shares.get(country, 0)
                pref_by_country[country] = [
                    round(japan_forecast.by_country.get(country, [0] * n_months)[t] * share * (1.0 - local_risks[t]), 1)
                    for t in range(n_months)
                ]

        return PrefForecast(
            prefecture=pref,
            months=year_months,
            median=[round(float(v), 1) for v in median],
            p10=[round(float(v), 1) for v in p10],
            p25=[round(float(v), 1) for v in p25],
            p75=[round(float(v), 1) for v in p75],
            p90=[round(float(v), 1) for v in p90],
            by_country=pref_by_country,
        )

    # -----------------------------------------------------------------------
    # _get_local_risk() — ローカルリスク計算
    # -----------------------------------------------------------------------
    @staticmethod
    def _get_local_risk(pref: str, year_months: List[str]) -> List[float]:
        """
        都道府県の月別ローカルリスクを計算する。

        ローカルリスクは台風、降雪、猛暑などの季節的リスク要因。
        リスク値は予測値の下方修正率（0.0=影響なし, 0.08=8%下方修正）。

        Args:
            pref: 都道府県名
            year_months: 月リスト

        Returns:
            各月のリスク値 (0.0-1.0)
        """
        risk_config = LOCAL_RISK_SOURCES.get(pref)
        if risk_config is None:
            return [0.0] * len(year_months)

        risks = []
        for ym in year_months:
            try:
                month_num = int(ym.split("-")[1])
            except (ValueError, IndexError):
                month_num = 1

            risk = 0.0

            # 台風リスク
            if month_num in risk_config.get("typhoon_months", []):
                risk += risk_config.get("base_typhoon_risk", 0.0)

            # 降雪リスク
            if month_num in risk_config.get("snow_months", []):
                risk += risk_config.get("base_snow_risk", 0.0)

            # 猛暑リスク
            if month_num in risk_config.get("heat_months", []):
                risk += risk_config.get("base_heat_risk", 0.0)

            risks.append(min(risk, 0.5))  # 上限50%

        return risks
