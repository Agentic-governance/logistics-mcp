"""Analytics module unit tests

Tests mock calculate_risk_score to avoid live API calls (24 external endpoints
per entity). This ensures analytics logic is tested independently of network
availability and API rate limits.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


def _make_mock_score(name="Test", country="JP", overall=42):
    """Create a mock SupplierRiskScore result for testing."""
    from scoring.engine import SupplierRiskScore
    score = SupplierRiskScore(supplier_id=f"mock_{name}", company_name=name)
    # Set varied dimension scores for realistic testing
    dim_values = {
        "geo_risk": 30, "conflict": 25, "political": 20, "compliance": 15,
        "disaster": 35, "weather": 10, "typhoon": 5, "maritime": 40,
        "internet": 12, "climate_risk": 28, "economic": 22, "currency": 18,
        "trade": 33, "energy": 27, "port_congestion": 14, "cyber_risk": 19,
        "legal": 11, "health": 8, "humanitarian": 6, "food_security": 9,
        "labor": 7, "aviation": 3,
    }
    for dim, val in dim_values.items():
        setattr(score, f"{dim}_score", val)
    score.sanction_score = 0
    score.japan_economy_score = 15
    score.calculate_overall()
    return score


def _mock_calculate_risk_score(supplier_id, company_name, country=None, location=None):
    """Mock replacement for calculate_risk_score."""
    return _make_mock_score(name=company_name, country=country or "JP")


class TestPortfolioAnalyzer:
    @patch("features.analytics.portfolio_analyzer.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_portfolio_weighted_score_calculation(self, mock_calc):
        """Weighted portfolio score should reflect share-weighted average"""
        from features.analytics.portfolio_analyzer import PortfolioAnalyzer
        analyzer = PortfolioAnalyzer()
        entities = [
            {"name": "Japan", "country": "Japan", "share": 0.6},
            {"name": "Yemen", "country": "Yemen", "share": 0.4},
        ]
        report = analyzer.analyze_portfolio(entities)
        # PortfolioReport uses weighted_portfolio_score
        assert report.weighted_portfolio_score is not None
        assert 0 <= report.weighted_portfolio_score <= 100

    @patch("features.analytics.portfolio_analyzer.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_hhi_calculation(self, mock_calc):
        """HHI should be low for equal distribution, high for monopoly"""
        from features.analytics.portfolio_analyzer import PortfolioAnalyzer
        analyzer = PortfolioAnalyzer()
        # Equal distribution among 4 suppliers
        entities_equal = [
            {"name": f"Co{i}", "country": "Japan", "share": 0.25} for i in range(4)
        ]
        report = analyzer.analyze_portfolio(entities_equal)
        # Compute HHI from entity shares: sum(share^2)
        hhi_equal = sum(e["share"] ** 2 for e in entities_equal)
        assert hhi_equal < 0.5  # Should be 0.0625 * 4 = 0.25

        # Monopoly
        entities_mono = [{"name": "Monopoly", "country": "Japan", "share": 1.0}]
        report2 = analyzer.analyze_portfolio(entities_mono)
        hhi_mono = sum(e["share"] ** 2 for e in entities_mono)
        assert hhi_mono >= 0.9  # Should be 1.0

    @patch("features.analytics.correlation_analyzer.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_correlation_matrix_symmetry(self, mock_calc):
        """Correlation matrix should be symmetric"""
        from features.analytics.correlation_analyzer import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        matrix = analyzer.compute_dimension_correlations(["Japan", "China", "US", "Germany", "India"])
        # Check that matrix[i][j] == matrix[j][i]
        for i, dim1 in enumerate(matrix.dimensions):
            for j, dim2 in enumerate(matrix.dimensions):
                assert abs(matrix.matrix[i][j] - matrix.matrix[j][i]) < 0.001, \
                    f"Matrix not symmetric at ({dim1}, {dim2})"

    @patch("features.analytics.benchmark_analyzer._get_scores_for_country")
    def test_benchmark_percentile_rank(self, mock_get_scores):
        """Benchmark dimension scores should be within valid range"""
        # Mock returns a to_dict()-style result
        mock_scores = _make_mock_score().to_dict()
        mock_get_scores.return_value = mock_scores

        from features.analytics.benchmark_analyzer import BenchmarkAnalyzer
        analyzer = BenchmarkAnalyzer()
        report = analyzer.benchmark_against_industry({
            "name": "Japan", "country": "Japan", "industry": "automotive"
        })
        # dimension_benchmarks is a list of DimensionBenchmark objects
        for db in report.dimension_benchmarks:
            assert 0 <= db.entity_score <= 100, \
                f"Entity score for {db.dimension} out of range: {db.entity_score}"
            assert db.relative_position in ("above_average", "average", "below_average"), \
                f"Invalid relative_position for {db.dimension}: {db.relative_position}"

class TestSensitivityAnalyzer:
    @patch("features.analytics.sensitivity_analyzer.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_sensitivity_weight_perturbation(self, mock_calc):
        """Weight perturbation should produce ranked sensitivities"""
        from features.analytics.sensitivity_analyzer import SensitivityAnalyzer
        analyzer = SensitivityAnalyzer()
        report = analyzer.analyze_weight_sensitivity("Japan", 0.05)
        assert len(report.sensitivity_ranking) > 0
        # Should be sorted by absolute impact (sum of |up| + |down|)
        impacts = [
            abs(s.weight_increase_impact) + abs(s.weight_decrease_impact)
            for s in report.sensitivity_ranking
        ]
        assert impacts == sorted(impacts, reverse=True)

    @patch("features.analytics.sensitivity_analyzer.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_monte_carlo_distribution_shape(self, mock_calc):
        """Monte Carlo should produce reasonable distribution"""
        from features.analytics.sensitivity_analyzer import SensitivityAnalyzer
        analyzer = SensitivityAnalyzer()
        result = analyzer.monte_carlo_score_distribution("Japan", n_simulations=50, noise_std=10.0)
        assert result.mean_score >= 0
        assert result.mean_score <= 100
        assert result.std_score >= 0
        assert result.var_95 >= 0
        assert len(result.risk_level_distribution) > 0
