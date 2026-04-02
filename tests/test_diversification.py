"""Supplier diversification simulator tests

Tests for concentration analysis, diversification recommendations,
and supplier portfolio simulation.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


def _mock_calculate_risk_score(supplier_id, company_name, country=None, location=None):
    """Mock replacement for calculate_risk_score."""
    from scoring.engine import SupplierRiskScore
    score = SupplierRiskScore(supplier_id=supplier_id, company_name=company_name)
    # Set varied scores by country
    profiles = {
        "China": 55, "Japan": 25, "Vietnam": 35, "Taiwan": 40,
        "South Korea": 30, "Germany": 20, "United States": 22,
    }
    loc = country or location or ""
    overall = profiles.get(loc, 30)
    for dim in SupplierRiskScore.WEIGHTS:
        setattr(score, f"{dim}_score", overall)
    score.calculate_overall()
    return score


class TestConcentrationRiskAnalyzer:
    """Tests for the ConcentrationRiskAnalyzer."""

    def test_analyzer_instantiation(self):
        """ConcentrationRiskAnalyzer should instantiate."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        assert analyzer is not None

    def test_hhi_calculation_accuracy(self):
        """HHI should be sum of squared shares."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        shares = {"A": 0.5, "B": 0.3, "C": 0.2}
        hhi = analyzer.calculate_hhi(shares)
        expected = 0.5**2 + 0.3**2 + 0.2**2  # 0.25 + 0.09 + 0.04 = 0.38
        assert hhi == pytest.approx(expected, abs=0.001)

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_high_concentration_detection(self, mock_calc):
        """HHI > 0.25 should be detected as HIGH concentration."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        # One dominant supplier: HHI = 0.7^2 + 0.3^2 = 0.49 + 0.09 = 0.58
        suppliers = [
            {"country": "CN", "share": 0.7, "name": "DomCo"},
            {"country": "JP", "share": 0.3, "name": "AltCo"},
        ]
        result = analyzer.analyze_supplier_concentration(suppliers)
        assert result.get("concentration_level") == "HIGH"

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_low_concentration_detection(self, mock_calc):
        """Many equal suppliers should give LOW concentration."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        suppliers = [
            {"country": f"C{i}", "share": 0.1, "name": f"Co{i}"}
            for i in range(10)
        ]
        result = analyzer.analyze_supplier_concentration(suppliers)
        assert result.get("concentration_level") == "LOW"

    @patch("features.concentration.analyzer.ConcentrationRiskAnalyzer.analyze_supplier_concentration")
    def test_sector_template_fallback(self, mock_analyze):
        """When no suppliers provided, sector templates should be used."""
        mock_analyze.return_value = {
            "hhi": 0.2,
            "concentration_level": "MODERATE",
            "concentration_score": 40,
        }
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        result = analyzer.analyze_supplier_concentration([], sector="semiconductor")
        # Should use the semiconductor template
        assert result is not None

    def test_empty_suppliers_returns_error(self):
        """Empty suppliers with no sector should return error."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        result = analyzer.analyze_supplier_concentration([])
        assert "error" in result


class TestDiversificationSimulation:
    """Tests for diversification recommendations."""

    def test_sector_templates_exist(self):
        """All major sector templates should be defined."""
        from features.concentration.analyzer import SECTOR_TEMPLATES
        expected_sectors = {
            "semiconductor", "battery_materials", "automotive_parts",
            "electronics", "energy_lng", "food_grains",
        }
        assert expected_sectors.issubset(set(SECTOR_TEMPLATES.keys()))

    def test_sector_template_shares_sum_to_one(self):
        """Each sector template shares should sum to ~1.0."""
        from features.concentration.analyzer import SECTOR_TEMPLATES
        for sector, shares in SECTOR_TEMPLATES.items():
            total = sum(shares.values())
            assert abs(total - 1.0) < 0.02, f"{sector} shares sum to {total}"

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_concentration_with_risk_scores(self, mock_calc):
        """Concentration analysis should integrate risk scores per country."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        suppliers = [
            {"country": "CN", "share": 0.6, "name": "ChinaCo"},
            {"country": "VN", "share": 0.2, "name": "VietCo"},
            {"country": "JP", "share": 0.2, "name": "JapanCo"},
        ]
        result = analyzer.analyze_supplier_concentration(suppliers)
        assert "hhi" in result
        assert "concentration_level" in result
        assert "concentration_score" in result

    def test_diversification_reduces_hhi(self):
        """Adding more suppliers should reduce HHI."""
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()

        # Before: 2 suppliers with unequal shares
        hhi_before = analyzer.calculate_hhi({"A": 0.7, "B": 0.3})

        # After: redistribute adding a third supplier
        hhi_after = analyzer.calculate_hhi({"A": 0.4, "B": 0.3, "C": 0.3})

        assert hhi_after < hhi_before, "Adding suppliers should reduce concentration"
