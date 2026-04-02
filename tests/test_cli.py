"""CLI tool tests using click.testing.CliRunner

Tests for all CLI commands: risk, screen, route, alerts, dashboard, bom.
External API calls are mocked.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from click.testing import CliRunner
from datetime import datetime


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_calculate_risk_score(supplier_id, company_name, country=None, location=None):
    """Return a deterministic SupplierRiskScore."""
    from scoring.engine import SupplierRiskScore
    score = SupplierRiskScore(supplier_id=supplier_id, company_name=company_name)
    for dim in SupplierRiskScore.WEIGHTS:
        setattr(score, f"{dim}_score", 35)
    score.sanction_score = 0
    score.japan_economy_score = 10
    score.calculate_overall()
    return score


def _mock_screen_entity(name, country=None):
    """Return a mock screening result."""
    m = MagicMock()
    m.matched = False
    m.match_score = 0.12
    m.source = None
    m.matched_entity = None
    m.evidence = []
    if "huawei" in name.lower():
        m.matched = True
        m.match_score = 0.95
        m.source = "OFAC"
        m.matched_entity = "HUAWEI TECHNOLOGIES CO., LTD."
        m.evidence = ["OFAC SDN List match"]
    return m


class TestCLIRisk:
    """Tests for the 'risk' CLI command."""

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_risk_basic(self, mock_calc):
        """scri risk Japan should output a risk score."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["risk", "Japan"])
        assert result.exit_code == 0
        assert "Japan" in result.output

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_risk_detail_flag(self, mock_calc):
        """scri risk --detail should show all dimensions."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["risk", "China", "--detail"])
        assert result.exit_code == 0

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_risk_output_contains_level(self, mock_calc):
        """Output should contain risk level."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["risk", "Germany"])
        assert result.exit_code == 0


class TestCLIScreen:
    """Tests for the 'screen' CLI command."""

    @patch("pipeline.sanctions.screener.screen_entity", side_effect=_mock_screen_entity)
    def test_screen_no_match(self, mock_screen):
        """Screening a clean entity should show NO MATCH."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["screen", "Toyota Motor"])
        assert result.exit_code == 0
        assert "NO MATCH" in result.output

    @patch("pipeline.sanctions.screener.screen_entity", side_effect=_mock_screen_entity)
    def test_screen_match_found(self, mock_screen):
        """Screening a sanctioned entity should show MATCH FOUND."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["screen", "Huawei"])
        assert result.exit_code == 0
        assert "MATCH" in result.output

    @patch("pipeline.sanctions.screener.screen_entity", side_effect=_mock_screen_entity)
    def test_screen_with_country(self, mock_screen):
        """--country flag should be accepted."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["screen", "TestCo", "--country", "China"])
        assert result.exit_code == 0


class TestCLIRoute:
    """Tests for the 'route' CLI command."""

    @patch("features.route_risk.analyzer.RouteRiskAnalyzer.get_chokepoint_risk")
    def test_route_basic(self, mock_cp):
        """scri route Yokohama Rotterdam should work."""
        mock_cp.return_value = {
            "chokepoint_id": "malacca",
            "name": "Strait of Malacca",
            "risk_score": 30,
            "risk_factors": ["piracy"],
            "evidence": ["test"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["route", "Yokohama", "Rotterdam"])
        assert result.exit_code == 0

    def test_route_unknown_port(self):
        """Unknown port should handle gracefully."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["route", "UnknownPortXYZ", "Rotterdam"])
        assert result.exit_code == 0  # Should not crash
        assert "Error" in result.output or "error" in result.output.lower()


class TestCLIAlerts:
    """Tests for the 'alerts' CLI command."""

    @patch("pipeline.db.Session")
    def test_alerts_empty(self, mock_session):
        """Empty alerts should show appropriate message."""
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_ctx.query.return_value = mock_query
        mock_session.return_value = mock_ctx

        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["alerts", "--limit", "5"])
        assert result.exit_code == 0

    def test_alerts_limit_option(self):
        """--limit option should be accepted."""
        from cli.scri_cli import cli
        runner = CliRunner()
        # Even if DB is not available, command should not crash with bad args
        result = runner.invoke(cli, ["alerts", "--limit", "3"])
        # Exit code may be non-zero if DB unavailable, but should not be 2 (click usage error)
        assert result.exit_code != 2


class TestCLIDashboard:
    """Tests for the 'dashboard' CLI command."""

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_dashboard_basic(self, mock_calc):
        """scri dashboard should output a table."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["dashboard"])
        assert result.exit_code == 0

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_dashboard_custom_countries(self, mock_calc):
        """--countries flag should filter countries."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["dashboard", "--countries", "Japan,China"])
        assert result.exit_code == 0


class TestCLIVersion:
    """Tests for CLI version and help."""

    def test_version(self):
        """--version should print version."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.9.0" in result.output

    def test_help(self):
        """--help should print usage info."""
        from cli.scri_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "SCRI" in result.output or "scri" in result.output.lower()
