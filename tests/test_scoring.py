"""Scoring engine unit tests"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

class TestScoringEngine:
    def test_weight_sum_equals_one(self):
        """All dimension weights must sum to exactly 1.0"""
        from scoring.engine import SupplierRiskScore
        total = sum(SupplierRiskScore.WEIGHTS.values())
        assert abs(total - 1.0) < 0.0001, f"Weight sum = {total}, expected 1.0"

    def test_sanctions_override_to_100(self):
        """Sanctions score of 100 should make overall = 100"""
        from scoring.engine import SupplierRiskScore
        score = SupplierRiskScore(supplier_id="test", company_name="Test")
        score.sanction_score = 100
        result = score.calculate_overall()
        assert result == 100

    def test_composite_formula(self):
        """Verify the 60/30/10 composite formula"""
        from scoring.engine import SupplierRiskScore
        score = SupplierRiskScore(supplier_id="test", company_name="Test")
        # Set all dimension scores to 50
        for dim in SupplierRiskScore.WEIGHTS:
            setattr(score, f"{dim}_score", 50)
        result = score.calculate_overall()
        # weighted_sum = 50 * 1.0 = 50
        # peak = 50, second_peak = 50
        # composite = int(~50*0.6 + 50*0.30 + 50*0.10) = 49 (float truncation)
        # 25次元の重みは合計≈1.0だが浮動小数点で微小誤差あり
        assert result in (49, 50), f"Expected 49 or 50, got {result}"

    def test_score_range_0_to_100(self):
        """Overall score should always be in [0, 100]"""
        from scoring.engine import SupplierRiskScore
        # Test with extreme values
        score = SupplierRiskScore(supplier_id="test", company_name="Test")
        for dim in SupplierRiskScore.WEIGHTS:
            setattr(score, f"{dim}_score", 100)
        result = score.calculate_overall()
        assert 0 <= result <= 100

        # All zeros
        score2 = SupplierRiskScore(supplier_id="test2", company_name="Test2")
        result2 = score2.calculate_overall()
        assert 0 <= result2 <= 100

    def test_risk_levels(self):
        """Risk level thresholds should be correct"""
        from scoring.engine import SupplierRiskScore
        test_cases = [
            (85, "CRITICAL"),
            (70, "HIGH"),
            (45, "MEDIUM"),
            (25, "LOW"),
            (10, "MINIMAL"),
        ]
        for score_val, expected_level in test_cases:
            s = SupplierRiskScore(supplier_id="t", company_name="T")
            s.overall_score = score_val
            assert s.risk_level() == expected_level, f"Score {score_val} should be {expected_level}"

    def test_to_dict_structure(self):
        """to_dict() should return all required fields"""
        from scoring.engine import SupplierRiskScore
        score = SupplierRiskScore(supplier_id="test", company_name="Test Corp")
        score.calculate_overall()
        d = score.to_dict()
        assert "overall_score" in d
        assert "risk_level" in d
        assert "scores" in d
        assert "evidence" in d
        assert len(d["scores"]) == 27  # All 27 dimensions (v1.3.0)
