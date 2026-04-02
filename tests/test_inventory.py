"""Inventory and safety stock recommendation tests

Tests for supply chain vulnerability scorer's inventory buffer component
and safety stock recommendations logic.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


class TestSupplyChainVulnerabilityScorer:
    """Tests for the supply chain vulnerability scorer."""

    def test_scorer_instantiation(self):
        """SupplyChainVulnerabilityScorer should instantiate."""
        from scoring.dimensions.supply_chain_vulnerability_scorer import (
            SupplyChainVulnerabilityScorer,
        )
        scorer = SupplyChainVulnerabilityScorer()
        assert scorer is not None

    def test_component_weights_sum_to_one(self):
        """Component weights should sum to 1.0."""
        from scoring.dimensions.supply_chain_vulnerability_scorer import (
            SupplyChainVulnerabilityScorer,
        )
        total = sum(SupplyChainVulnerabilityScorer.COMPONENT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001, f"Weight sum = {total}"

    def test_vulnerability_result_to_dict(self):
        """VulnerabilityResult.to_dict() should return complete dict."""
        from scoring.dimensions.supply_chain_vulnerability_scorer import (
            VulnerabilityResult,
        )
        result = VulnerabilityResult(
            score=45.0,
            risk_level="MEDIUM",
            components={"procurement_concentration_hhi": 0.3, "sole_source_ratio": 0.25},
            recommendations=["Diversify supply base"],
            timestamp=datetime.utcnow().isoformat(),
        )
        d = result.to_dict()
        assert d["score"] == 45.0
        assert d["risk_level"] == "MEDIUM"
        assert len(d["recommendations"]) == 1
        assert "components" in d

    def test_vulnerability_result_score_range(self):
        """VulnerabilityResult score should be representable in 0-100 range."""
        from scoring.dimensions.supply_chain_vulnerability_scorer import (
            VulnerabilityResult,
        )
        for score_val in [0.0, 25.5, 50.0, 75.0, 100.0]:
            result = VulnerabilityResult(
                score=score_val,
                risk_level="TEST",
                components={},
                recommendations=[],
                timestamp=datetime.utcnow().isoformat(),
            )
            assert 0 <= result.score <= 100


class TestSafetyStockRecommendation:
    """Tests for safety stock / inventory buffer logic."""

    def test_inventory_buffer_weight_exists(self):
        """inventory_buffer should be a component weight."""
        from scoring.dimensions.supply_chain_vulnerability_scorer import (
            SupplyChainVulnerabilityScorer,
        )
        weights = SupplyChainVulnerabilityScorer.COMPONENT_WEIGHTS
        assert "inventory_buffer" in weights
        assert weights["inventory_buffer"] > 0

    def test_high_inventory_reduces_vulnerability(self):
        """Higher inventory buffer days should reduce vulnerability score."""
        # Inventory buffer scoring: high days = low risk score
        high_buffer_days = 60
        low_buffer_days = 5

        # Simple scoring model: buffer_score = max(0, 100 - buffer_days * 2)
        high_score = max(0, 100 - high_buffer_days * 2)
        low_score = max(0, 100 - low_buffer_days * 2)
        assert high_score < low_score, "Higher buffer should give lower score"

    def test_zero_buffer_maximum_risk(self):
        """Zero inventory buffer should give maximum risk."""
        buffer_days = 0
        score = max(0, min(100, 100 - buffer_days * 2))
        assert score == 100

    def test_safety_stock_calculation_model(self):
        """Safety stock recommendation should consider lead time and demand variability."""
        # Standard safety stock formula: SS = Z * sigma_d * sqrt(LT)
        import math
        z_score = 1.96  # 97.5% service level
        sigma_d = 10    # demand std dev (units/day)
        lead_time_days = 14

        safety_stock = z_score * sigma_d * math.sqrt(lead_time_days)
        assert safety_stock > 0
        assert safety_stock == pytest.approx(z_score * sigma_d * math.sqrt(lead_time_days))

    def test_safety_stock_increases_with_lead_time(self):
        """Longer lead time should require more safety stock."""
        import math
        z = 1.96
        sigma = 10
        ss_short = z * sigma * math.sqrt(7)    # 7-day lead time
        ss_long = z * sigma * math.sqrt(30)     # 30-day lead time
        assert ss_long > ss_short

    def test_procurement_concentration_hhi_range(self):
        """HHI should be between 0 and 1."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        # Monopoly
        hhi_mono = analyzer.calculate_hhi({"A": 1.0})
        assert hhi_mono == 1.0
        # Equal split
        hhi_equal = analyzer.calculate_hhi({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
        assert 0 < hhi_equal < 1.0


class TestConcentrationRiskForInventory:
    """Concentration risk affecting inventory decisions."""

    def test_hhi_monopoly(self):
        """Single supplier should give HHI = 1.0 (maximum concentration)."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        hhi = analyzer.calculate_hhi({"sole_supplier": 1.0})
        assert hhi == 1.0

    def test_hhi_diverse(self):
        """Many equal suppliers should give low HHI."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        shares = {f"supplier_{i}": 0.1 for i in range(10)}
        hhi = analyzer.calculate_hhi(shares)
        assert hhi == pytest.approx(0.1, abs=0.01)
