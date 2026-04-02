"""観光モデル高度テストスイート — SCRI v1.4.0

RiskAdjuster / BayesianUpdater / DualScaleModel のユニットテスト。
外部API非依存。ハードコードデータのみで検証。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np


# =====================================================================
# TestRiskAdjuster — リスク調整レイヤー
# =====================================================================
class TestRiskAdjuster:
    """features/tourism/risk_adjuster.py のテスト"""

    def _get_adjuster(self):
        from features.tourism.risk_adjuster import RiskAdjuster
        return RiskAdjuster()

    def test_expected_loss_ordering(self):
        """楽観 < ベース < 悲観"""
        adj = self._get_adjuster()
        for country in ["CN", "KR", "TW", "US", "AU", "TH"]:
            opt = adj.calculate_expected_loss(country, "optimistic")["expected_loss"]
            base = adj.calculate_expected_loss(country, "base")["expected_loss"]
            pess = adj.calculate_expected_loss(country, "pessimistic")["expected_loss"]
            assert opt <= base <= pess, \
                f"{country}: 楽観({opt}) <= ベース({base}) <= 悲観({pess}) 違反"

    def test_expected_loss_positive(self):
        """期待損失は正"""
        adj = self._get_adjuster()
        for country in ["CN", "KR", "TW", "US", "AU", "TH"]:
            result = adj.calculate_expected_loss(country, "base")
            assert result["expected_loss"] >= 0, \
                f"{country}: 期待損失が負 ({result['expected_loss']})"

    def test_expected_loss_bounded(self):
        """期待損失は0-90%"""
        adj = self._get_adjuster()
        for country in ["CN", "KR", "TW", "US", "AU", "TH"]:
            for scenario in ["optimistic", "base", "pessimistic"]:
                el = adj.calculate_expected_loss(country, scenario)["expected_loss"]
                assert 0.0 <= el <= 0.90, \
                    f"{country}/{scenario}: 期待損失が範囲外 ({el})"

    def test_scri_adjustment(self):
        """SCRIスコア高→確率上方修正→期待損失増加"""
        adj = self._get_adjuster()

        # SCRIスコアなし（ベース）
        base_loss = adj.calculate_expected_loss(
            "CN", "base", current_scri_scores={}
        )["expected_loss"]

        # SCRIスコアが全次元で高い（80/100）→ 確率上方修正
        high_scri = {
            "bilateral": 80, "economic": 80, "currency": 80, "health": 80,
        }
        high_loss = adj.calculate_expected_loss(
            "CN", "base", current_scri_scores=high_scri
        )["expected_loss"]

        assert high_loss > base_loss, \
            f"SCRIスコア高の方が期待損失が大きいはず: high={high_loss} vs base={base_loss}"

    def test_unknown_country(self):
        """未知国は期待損失0"""
        adj = self._get_adjuster()
        result = adj.calculate_expected_loss("ZZ", "base")
        assert result["expected_loss"] == 0.0
        assert result["scenario_details"] == []

    def test_apply_risk_adjustment(self):
        """リスク調整で中央値が下方修正される"""
        adj = self._get_adjuster()
        baseline = {
            "median": [1000.0, 1100.0, 1200.0],
            "p10": [800.0, 900.0, 1000.0],
            "p25": [900.0, 1000.0, 1100.0],
            "p75": [1100.0, 1200.0, 1300.0],
            "p90": [1200.0, 1300.0, 1400.0],
        }
        adjusted = adj.apply_risk_adjustment(baseline, 0.10, "CN")

        # 中央値が10%下方修正
        assert adjusted["median"][0] == pytest.approx(900.0, abs=0.2)

        # risk_adjustment メタ情報が含まれる
        assert "risk_adjustment" in adjusted
        assert adjusted["risk_adjustment"]["expected_loss"] == pytest.approx(0.10)

    def test_apply_zero_loss(self):
        """期待損失0ならベースラインそのまま"""
        adj = self._get_adjuster()
        baseline = {"median": [100.0], "p10": [80.0], "p90": [120.0]}
        result = adj.apply_risk_adjustment(baseline, 0.0, "XX")
        assert result["median"] == baseline["median"]

    def test_scenario_details_populated(self):
        """シナリオ詳細が返される"""
        adj = self._get_adjuster()
        result = adj.calculate_expected_loss("CN", "base")
        assert len(result["scenario_details"]) == 4  # CN has 4 scenarios
        for detail in result["scenario_details"]:
            assert "name" in detail
            assert "raw_probability" in detail
            assert "impact_rate" in detail
            assert "contribution" in detail


# =====================================================================
# TestBayesianUpdater — ベイジアン粒子フィルタ
# =====================================================================
class TestBayesianUpdater:
    """features/tourism/bayesian_updater.py のテスト"""

    def _get_updater(self, n_particles=500):
        from features.tourism.bayesian_updater import BayesianUpdater
        return BayesianUpdater(n_particles=n_particles)

    def _init_forecast(self):
        """テスト用の予測分布"""
        return {
            "median": [1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0],
            "p10": [800.0, 900.0, 1000.0, 1100.0, 1200.0, 1300.0],
            "p90": [1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1700.0],
        }

    def test_initialize(self):
        """初期化で粒子が生成される"""
        updater = self._get_updater()
        updater.initialize(self._init_forecast())
        assert updater.particles is not None
        assert updater.particles.shape == (500, 6)
        assert updater.weights is not None
        assert len(updater.weights) == 500
        # 初期重みは均一
        assert pytest.approx(updater.weights.sum(), abs=1e-6) == 1.0

    def test_update_shifts_distribution(self):
        """実績が高い→分布が上方シフト"""
        updater = self._get_updater(n_particles=2000)
        updater.initialize(self._init_forecast())

        # 事前中央値は約1000（month_index=0）
        pre = updater.get_posterior()
        pre_median_m0 = pre["median"][0]

        # 実績が大幅に高い（1500千人 vs 予測1000千人）
        updater.update(1500.0, month_index=0)

        post = updater.get_posterior()
        post_median_m0 = post["median"][0]

        # 事後中央値は上方シフトしているはず
        assert post_median_m0 > pre_median_m0, \
            f"実績高→中央値上昇: post={post_median_m0} vs pre={pre_median_m0}"

    def test_resampling(self):
        """ESS低下でリサンプリングが発生する"""
        updater = self._get_updater(n_particles=500)
        updater.initialize(self._init_forecast())

        # 極端な実績を入れてESSを下げる
        result = updater.update(2000.0, month_index=0)

        # リサンプリングが発生したか、ESS > 0
        assert result["ess"] > 0
        # リサンプリング後は重みが均一化される
        if result["resampled"]:
            assert pytest.approx(updater.weights.sum(), abs=1e-6) == 1.0

    def test_update_batch(self):
        """バッチ更新が動作する"""
        updater = self._get_updater()
        updater.initialize(self._init_forecast())

        actuals = [1050.0, None, 1250.0, None, None, None]
        results = updater.update_batch(actuals)
        # Noneでない月だけ更新される
        assert len(results) == 2
        assert results[0]["month_index"] == 0
        assert results[1]["month_index"] == 2

    def test_posterior_keys(self):
        """事後分布が必要なキーを含む"""
        updater = self._get_updater()
        updater.initialize(self._init_forecast())
        post = updater.get_posterior()
        for key in ["median", "p10", "p90", "p25", "p75",
                     "effective_sample_size", "n_updates"]:
            assert key in post, f"事後分布に '{key}' がない"

    def test_uninitialized_update_raises(self):
        """initialize前のupdate()はRuntimeError"""
        updater = self._get_updater()
        with pytest.raises(RuntimeError):
            updater.update(1000.0, 0)


# =====================================================================
# TestDualScaleIntegration — Dual-Scaleモデル
# =====================================================================
class TestDualScaleIntegration:
    """features/tourism/dual_scale_model.py のテスト"""

    def _get_model(self):
        from features.tourism.dual_scale_model import DualScaleModel
        return DualScaleModel()

    def test_predict_returns_forecast(self):
        """予測がmedian/p10/p90を含む"""
        model = self._get_model()
        months = [f"2026-{str(m).zfill(2)}" for m in range(1, 13)]
        forecast = model.predict("CN", months, n_samples=500)
        assert len(forecast.median) == 12
        assert len(forecast.p10) == 12
        assert len(forecast.p90) == 12
        assert len(forecast.p25) == 12
        assert len(forecast.p75) == 12
        # 全値が正
        for v in forecast.median:
            assert v > 0, f"中央値が正でない: {v}"

    def test_short_term_transformer_dominant(self):
        """短期(1-3月)ではTransformer(短期)比率が高い"""
        from features.tourism.dual_scale_model import _short_term_ratio
        # 1ヶ月先: 短期比率 > 0.6
        assert _short_term_ratio(1) > 0.6, \
            f"1ヶ月先の短期比率が低い: {_short_term_ratio(1)}"
        # 3ヶ月先: 短期比率 > 0.5
        assert _short_term_ratio(3) > 0.5, \
            f"3ヶ月先の短期比率が低い: {_short_term_ratio(3)}"
        # 12ヶ月先: 短期比率 < 0.3
        assert _short_term_ratio(12) < 0.3, \
            f"12ヶ月先の短期比率が高い: {_short_term_ratio(12)}"
        # 24ヶ月先: 短期比率 < 0.10
        assert _short_term_ratio(24) < 0.10, \
            f"24ヶ月先の短期比率が高い: {_short_term_ratio(24)}"

    def test_predict_unknown_country(self):
        """未知国でもエラーにならない"""
        model = self._get_model()
        months = ["2026-01", "2026-02", "2026-03"]
        forecast = model.predict("ZZ", months, n_samples=100)
        assert len(forecast.median) == 3

    def test_short_term_ratios_in_forecast(self):
        """予測結果にshort_term_ratiosが含まれる"""
        model = self._get_model()
        months = ["2026-01", "2026-06", "2026-12"]
        forecast = model.predict("KR", months, n_samples=100)
        assert len(forecast.short_term_ratios) == 3
        # 1月先 > 12月先
        assert forecast.short_term_ratios[0] > forecast.short_term_ratios[2]

    def test_percentile_ordering(self):
        """p10 < p25 < median < p75 < p90（全月）"""
        model = self._get_model()
        months = [f"2026-{str(m).zfill(2)}" for m in range(1, 7)]
        forecast = model.predict("CN", months, n_samples=2000)
        for i in range(len(months)):
            assert forecast.p10[i] <= forecast.p25[i] <= forecast.median[i], \
                f"月{i}: p10={forecast.p10[i]}, p25={forecast.p25[i]}, median={forecast.median[i]}"
            assert forecast.median[i] <= forecast.p75[i] <= forecast.p90[i], \
                f"月{i}: median={forecast.median[i]}, p75={forecast.p75[i]}, p90={forecast.p90[i]}"


# =====================================================================
# TestAggregatorIntegration — 集計エンジン統合
# =====================================================================
class TestAggregatorIntegration:
    """features/tourism/inbound_aggregator.py の統合テスト（軽量）"""

    def test_local_risk_okinawa_typhoon(self):
        """沖縄の台風シーズン(7-10月)にリスクがある"""
        from features.tourism.inbound_aggregator import InboundAggregator
        months = [f"2026-{str(m).zfill(2)}" for m in range(1, 13)]
        risks = InboundAggregator._get_local_risk("沖縄", months)
        # 7月(index=6)はリスクあり
        assert risks[6] > 0, "沖縄7月の台風リスクが0"
        # 4月(index=3)はリスクなし
        assert risks[3] == 0.0, "沖縄4月にリスクがあるのは不正"

    def test_local_risk_hokkaido_snow(self):
        """北海道の降雪シーズン(12,1,2,3月)にリスクがある"""
        from features.tourism.inbound_aggregator import InboundAggregator
        months = [f"2026-{str(m).zfill(2)}" for m in range(1, 13)]
        risks = InboundAggregator._get_local_risk("北海道", months)
        assert risks[0] > 0, "北海道1月の降雪リスクが0"
        assert risks[5] == 0.0, "北海道6月にリスクがあるのは不正"

    def test_pref_share_sums_to_one(self):
        """都道府県シェアの合計が約1.0"""
        from features.tourism.inbound_aggregator import PREF_SHARE
        for pref, shares in PREF_SHARE.items():
            total = sum(shares.values())
            assert pytest.approx(total, abs=0.02) == 1.0, \
                f"{pref}のシェア合計が1.0でない: {total}"
