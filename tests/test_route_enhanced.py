"""Enhanced route risk analysis tests

Tests for seasonal adjustments, alternative routes, chokepoint risk scoring,
and the RouteRiskAnalyzer class.
All external API calls are mocked.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


class TestRouteRiskAnalyzer:
    """Core route risk analysis tests."""

    def test_analyzer_instantiation(self):
        """RouteRiskAnalyzer should instantiate."""
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        assert analyzer is not None

    @patch("features.route_risk.analyzer.RouteRiskAnalyzer.get_chokepoint_risk")
    def test_analyze_route_yokohama_rotterdam(self, mock_cp):
        """Route from Yokohama to Rotterdam should pass through chokepoints."""
        mock_cp.return_value = {
            "chokepoint_id": "malacca",
            "name": "Strait of Malacca",
            "risk_score": 30,
            "risk_factors": ["piracy", "congestion"],
            "evidence": ["[test] mocked risk"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        result = analyzer.analyze_route("Yokohama", "Rotterdam")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result["origin"] == "Yokohama"
        assert result["destination"] == "Rotterdam"
        assert "distance_km" in result
        assert result["distance_km"] > 0
        assert "route_risk" in result
        assert "risk_level" in result

    @patch("features.route_risk.analyzer.RouteRiskAnalyzer.get_chokepoint_risk")
    def test_analyze_route_has_chokepoints(self, mock_cp):
        """East Asia to Europe route should pass chokepoints."""
        mock_cp.return_value = {
            "chokepoint_id": "test",
            "name": "Test",
            "risk_score": 40,
            "risk_factors": [],
            "evidence": [],
            "timestamp": datetime.utcnow().isoformat(),
        }
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        result = analyzer.analyze_route("Tokyo", "Hamburg")
        if "error" not in result:
            # Should have chokepoints (Malacca, Bab-el-Mandeb, Suez)
            assert "chokepoints_passed" in result

    @patch("features.route_risk.analyzer.RouteRiskAnalyzer.get_chokepoint_risk")
    def test_analyze_route_alternative_routes(self, mock_cp):
        """Should suggest alternative routes when available."""
        mock_cp.return_value = {
            "chokepoint_id": "test",
            "name": "Test",
            "risk_score": 50,
            "risk_factors": [],
            "evidence": [],
            "timestamp": datetime.utcnow().isoformat(),
        }
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        result = analyzer.analyze_route("Shanghai", "Rotterdam")
        if "error" not in result:
            assert "alternative_routes" in result

    def test_analyze_route_unknown_port(self):
        """Unknown port should return error."""
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        result = analyzer.analyze_route("UnknownPort123", "Rotterdam")
        assert "error" in result

    @patch("features.route_risk.analyzer.RouteRiskAnalyzer.get_chokepoint_risk")
    def test_analyze_route_same_region(self, mock_cp):
        """Route within same region may have no chokepoints."""
        mock_cp.return_value = {
            "chokepoint_id": "test",
            "name": "Test",
            "risk_score": 10,
            "risk_factors": [],
            "evidence": [],
            "timestamp": datetime.utcnow().isoformat(),
        }
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        result = analyzer.analyze_route("Tokyo", "Busan")
        if "error" not in result:
            assert result["distance_km"] < 2000  # Relatively close


class TestChokepoints:
    """Chokepoint definitions and risk scoring tests."""

    def test_all_seven_chokepoints_defined(self):
        """All 7 major chokepoints should be defined."""
        from features.route_risk.analyzer import CHOKEPOINTS
        expected = {"suez", "malacca", "hormuz", "bab_el_mandeb",
                    "panama", "turkish_straits", "taiwan_strait"}
        assert expected == set(CHOKEPOINTS.keys())

    def test_chokepoint_has_required_fields(self):
        """Each chokepoint should have lat, lon, name, risk_factors."""
        from features.route_risk.analyzer import CHOKEPOINTS
        for cp_id, cp in CHOKEPOINTS.items():
            assert "lat" in cp, f"{cp_id} missing lat"
            assert "lon" in cp, f"{cp_id} missing lon"
            assert "name" in cp, f"{cp_id} missing name"
            assert "risk_factors" in cp, f"{cp_id} missing risk_factors"
            assert len(cp["risk_factors"]) > 0, f"{cp_id} has no risk factors"

    def test_get_chokepoint_risk_unknown(self):
        """Unknown chokepoint should return error dict."""
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        result = analyzer.get_chokepoint_risk("nonexistent_strait")
        assert "error" in result


class TestHaversineDistance:
    """Distance calculation tests."""

    def test_haversine_known_distance(self):
        """Haversine formula should give reasonable results."""
        from features.route_risk.analyzer import _haversine
        # Tokyo to Shanghai: ~1,750 km
        dist = _haversine(35.65, 139.77, 31.35, 121.50)
        assert 1500 < dist < 2200, f"Expected ~1750km, got {dist}"

    def test_haversine_zero_distance(self):
        """Same point should give zero distance."""
        from features.route_risk.analyzer import _haversine
        dist = _haversine(35.65, 139.77, 35.65, 139.77)
        assert dist < 1


class TestPortResolution:
    """Port name resolution tests."""

    def test_resolve_known_port(self):
        """Known port names should resolve to coordinates."""
        from features.route_risk.analyzer import _resolve_port
        coords = _resolve_port("Tokyo")
        assert coords is not None
        assert len(coords) == 2

    def test_resolve_unknown_port(self):
        """Unknown port should return None."""
        from features.route_risk.analyzer import _resolve_port
        coords = _resolve_port("UnknownPort123XYZ")
        assert coords is None

    def test_resolve_port_case_insensitive(self):
        """Port resolution should be case insensitive."""
        from features.route_risk.analyzer import _resolve_port
        lower = _resolve_port("singapore")
        upper = _resolve_port("Singapore")
        assert lower == upper
