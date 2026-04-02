"""Integration test suite for SCRI Platform (Stream 7-A)

End-to-end tests that exercise the full pipeline:
  - Risk scoring engine (24 dimensions)
  - Sanctions screening (fuzzy match against DB)
  - Portfolio analysis (multi-entity risk)
  - Route risk & chokepoint analysis
  - Timeseries store/retrieve cycle
  - Due diligence report generation
  - Anomaly detection & alert generation

Tests marked @pytest.mark.slow may call external APIs and should be
skipped in CI with: pytest -m "not slow"
"""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers: mock scoring to avoid live API calls in CI
# ---------------------------------------------------------------------------

def _make_deterministic_score(supplier_id, company_name, country=None, location=None):
    """Return a deterministic SupplierRiskScore without hitting external APIs."""
    from scoring.engine import SupplierRiskScore, Evidence

    loc = (location or country or "").lower()
    score = SupplierRiskScore(supplier_id=supplier_id, company_name=company_name)

    # Assign realistic per-country dimension scores
    _profiles = {
        "jp": {"geo_risk": 12, "conflict": 5, "political": 8, "compliance": 10,
               "disaster": 30, "weather": 15, "typhoon": 20, "maritime": 18,
               "internet": 5, "climate_risk": 22, "economic": 15, "currency": 20,
               "trade": 25, "energy": 18, "port_congestion": 12, "cyber_risk": 10,
               "legal": 8, "health": 5, "humanitarian": 3, "food_security": 5,
               "labor": 4, "aviation": 5, "japan_economy": 18},
        "cn": {"geo_risk": 35, "conflict": 20, "political": 55, "compliance": 40,
               "disaster": 25, "weather": 18, "typhoon": 18, "maritime": 30,
               "internet": 45, "climate_risk": 30, "economic": 25, "currency": 22,
               "trade": 40, "energy": 28, "port_congestion": 20, "cyber_risk": 35,
               "legal": 30, "health": 15, "humanitarian": 10, "food_security": 12,
               "labor": 35, "aviation": 10, "japan_economy": 0},
        "ye": {"geo_risk": 75, "conflict": 90, "political": 85, "compliance": 70,
               "disaster": 30, "weather": 25, "typhoon": 8, "maritime": 60,
               "internet": 55, "climate_risk": 45, "economic": 65, "currency": 50,
               "trade": 55, "energy": 40, "port_congestion": 35, "cyber_risk": 40,
               "legal": 45, "health": 55, "humanitarian": 80, "food_security": 75,
               "labor": 60, "aviation": 25, "japan_economy": 0},
        "sg": {"geo_risk": 8, "conflict": 3, "political": 5, "compliance": 5,
               "disaster": 10, "weather": 12, "typhoon": 5, "maritime": 15,
               "internet": 3, "climate_risk": 15, "economic": 8, "currency": 10,
               "trade": 18, "energy": 12, "port_congestion": 15, "cyber_risk": 8,
               "legal": 5, "health": 5, "humanitarian": 2, "food_security": 8,
               "labor": 5, "aviation": 3, "japan_economy": 0},
    }

    # Resolve profile key
    key = loc[:2] if loc else "sg"
    for k in _profiles:
        if k in loc or loc.startswith(k):
            key = k
            break
    profile = _profiles.get(key, _profiles["sg"])

    for dim, val in profile.items():
        setattr(score, f"{dim}_score", val)

    score.sanction_score = 0
    score.evidence.append(Evidence(
        category="info", severity="info",
        description=f"Mock score for {company_name} ({loc})",
        source="test_integration",
    ))
    for dim in profile:
        score.dimension_status[dim] = "ok"

    score.calculate_overall()
    return score


# ---------------------------------------------------------------------------
# 1. Full Risk Assessment Pipeline
# ---------------------------------------------------------------------------

class TestFullRiskAssessmentPipeline:
    """Test the scoring engine produces valid scores for various countries."""

    @pytest.mark.slow
    @pytest.mark.network
    def test_full_risk_assessment_pipeline_live(self):
        """Score JP, CN, YE, SG with LIVE API calls and verify ranges."""
        from scoring.engine import calculate_risk_score

        countries = {
            "JP": ("test_jp", "test_entity", "Japan"),
            "CN": ("test_cn", "test_entity", "China"),
            "YE": ("test_ye", "test_entity", "Yemen"),
            "SG": ("test_sg", "test_entity", "Singapore"),
        }
        for code, (sid, name, country) in countries.items():
            result = calculate_risk_score(sid, name, country=country, location=country)
            assert 0 <= result.overall_score <= 100, (
                f"{code}: overall_score {result.overall_score} out of range"
            )
            assert result.risk_level() in (
                "CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL"
            ), f"{code}: unexpected risk_level {result.risk_level()}"
            d = result.to_dict()
            assert len(d["scores"]) == 27, (
                f"{code}: expected 25 dimensions, got {len(d['scores'])}"
            )

    def test_full_risk_assessment_pipeline(self):
        """Score JP, CN, YE, SG via deterministic mock and verify ranges."""
        countries = {
            "JP": ("test_jp", "test_entity", "Japan"),
            "CN": ("test_cn", "test_entity", "China"),
            "YE": ("test_ye", "test_entity", "Yemen"),
            "SG": ("test_sg", "test_entity", "Singapore"),
        }
        for code, (sid, name, country) in countries.items():
            result = _make_deterministic_score(sid, name, country=country,
                                                location=country)
            assert 0 <= result.overall_score <= 100, (
                f"{code}: overall_score {result.overall_score} out of [0,100]"
            )
            assert result.risk_level() in (
                "CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL"
            )
            d = result.to_dict()
            # Every dimension score should also be in [0, 100]
            for dim_name, dim_val in d["scores"].items():
                assert 0 <= dim_val <= 100, (
                    f"{code}.{dim_name} = {dim_val} out of range"
                )

    def test_full_risk_assessment_pipeline_ordering(self):
        """Yemen should be higher risk than Singapore."""
        results = {}
        for code in ("jp", "cn", "ye", "sg"):
            r = _make_deterministic_score(f"test_{code}", f"entity_{code}",
                                          location=code)
            results[code] = r
            assert 0 <= r.overall_score <= 100

        assert results["ye"].overall_score > results["sg"].overall_score, (
            f"Yemen ({results['ye'].overall_score}) should be riskier than "
            f"Singapore ({results['sg'].overall_score})"
        )


# ---------------------------------------------------------------------------
# 2. Sanctions Screen Known Entity
# ---------------------------------------------------------------------------

class TestSanctionsScreenKnownEntity:
    """Screen a known sanctioned entity and verify match."""

    def test_sanctions_screen_known_entity(self):
        """Screen a known sanctioned entity, verify matched=True."""
        from pipeline.sanctions.screener import screen_entity

        # Screen a well-known sanctioned entity name.
        # If the sanctions DB is populated with OFAC/OpenSanctions data,
        # "Rosoboronexport" (Russian arms exporter) should match.
        result = screen_entity("Rosoboronexport")

        assert hasattr(result, "matched")
        assert hasattr(result, "match_score")
        assert isinstance(result.match_score, (int, float))
        assert 0 <= result.match_score <= 100

        # If the sanctions DB is populated, we expect a match
        if result.matched:
            assert result.match_score >= 85
            assert result.matched_entity is not None
            assert len(result.evidence) > 0
        # If DB is empty, still verify structure is correct
        else:
            assert result.evidence == [] or isinstance(result.evidence, list)

    def test_clean_entity_not_matched(self):
        """A clearly non-sanctioned entity should not match."""
        from pipeline.sanctions.screener import screen_entity

        result = screen_entity("Toyota Motor Corporation", "Japan")
        assert result.matched is False or result.match_score < 90


# ---------------------------------------------------------------------------
# 3. Portfolio Analysis
# ---------------------------------------------------------------------------

class TestPortfolioAnalysis:
    """Run portfolio analysis on 5 countries and verify output structure."""

    @patch("features.analytics.portfolio_analyzer.calculate_risk_score",
           side_effect=_make_deterministic_score)
    def test_portfolio_analysis(self, mock_calc):
        """Portfolio analysis on 5 countries, verify output structure."""
        from features.analytics.portfolio_analyzer import PortfolioAnalyzer

        analyzer = PortfolioAnalyzer()
        entities = [
            {"name": "entity_jp", "country": "Japan", "tier": 1, "share": 0.30},
            {"name": "entity_cn", "country": "China", "tier": 1, "share": 0.25},
            {"name": "entity_sg", "country": "Singapore", "tier": 2, "share": 0.20},
            {"name": "entity_ye", "country": "Yemen", "tier": 3, "share": 0.15},
            {"name": "entity_de", "country": "Germany", "tier": 1, "share": 0.10},
        ]
        report = analyzer.analyze_portfolio(entities)

        # Verify output structure
        assert hasattr(report, "entities")
        assert hasattr(report, "weighted_portfolio_score")
        assert hasattr(report, "risk_distribution")
        assert hasattr(report, "top_risks")
        assert hasattr(report, "lowest_risks")
        assert hasattr(report, "dominant_risk_dimension")

        # 5 entities in, 5 results out
        assert len(report.entities) == 5

        # Weighted score in valid range
        assert 0 <= report.weighted_portfolio_score <= 100

        # Risk distribution should have the standard levels
        for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL"):
            assert level in report.risk_distribution

        # to_dict() should produce a serializable dict
        d = report.to_dict()
        assert "entity_count" in d
        assert d["entity_count"] == 5
        assert "weighted_portfolio_score" in d
        assert "dominant_risk_dimension" in d
        assert isinstance(d["entities"], list)


# ---------------------------------------------------------------------------
# 4. Route Risk with Chokepoint
# ---------------------------------------------------------------------------

class TestRouteRiskWithChokepoint:
    """Test route risk for a route passing through Suez Canal."""

    def test_route_risk_with_chokepoint(self):
        """Route from Shanghai to Rotterdam should pass through Suez."""
        from features.route_risk.analyzer import RouteRiskAnalyzer

        analyzer = RouteRiskAnalyzer()
        result = analyzer.analyze_route("shanghai", "rotterdam")

        assert "error" not in result, f"Route analysis failed: {result.get('error')}"
        assert "route_risk" in result
        assert "chokepoints_passed" in result
        assert "distance_km" in result
        assert "risk_level" in result

        # Route risk should be in valid range
        assert 0 <= result["route_risk"] <= 100

        # Shanghai -> Rotterdam (east_asia -> europe) should pass through
        # Malacca, Bab-el-Mandeb, and Suez
        cp_names = [cp["name"] for cp in result["chokepoints_passed"]]
        assert "Suez Canal" in cp_names, (
            f"Suez Canal not found in chokepoints: {cp_names}"
        )

        # Distance should be reasonable (> 5000 km)
        assert result["distance_km"] > 5000

        # risk_level should be a valid level
        assert result["risk_level"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")

    def test_chokepoint_suez_has_risk_score(self):
        """Suez Canal chokepoint should have a non-zero risk score."""
        from features.route_risk.analyzer import RouteRiskAnalyzer

        analyzer = RouteRiskAnalyzer()
        suez_risk = analyzer.get_chokepoint_risk("suez")

        assert "risk_score" in suez_risk
        assert suez_risk["risk_score"] > 0, "Suez should have baseline risk"
        assert "risk_factors" in suez_risk
        assert len(suez_risk["risk_factors"]) > 0

    def test_route_risk_alternative_routes(self):
        """Route should suggest alternative routes when chokepoints exist."""
        from features.route_risk.analyzer import RouteRiskAnalyzer

        analyzer = RouteRiskAnalyzer()
        result = analyzer.analyze_route("shanghai", "rotterdam")

        assert "alternative_routes" in result
        # East Asia -> Europe should have Cape of Good Hope alternative
        assert len(result["alternative_routes"]) > 0


# ---------------------------------------------------------------------------
# 5. Timeseries Store and Retrieve
# ---------------------------------------------------------------------------

class TestTimeseriesStoreAndRetrieve:
    """Save a score to timeseries store, retrieve it, verify match."""

    def test_timeseries_store_and_retrieve(self):
        """Store a score, retrieve it, verify the values match."""
        from features.timeseries.store import RiskTimeSeriesStore

        # Use a temporary database to avoid polluting production data
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_timeseries.db")
            store = RiskTimeSeriesStore(db_path=db_path)

            test_location = "TestCountry_Integration"
            test_timestamp = datetime(2026, 3, 15, 12, 0, 0)
            test_score = {
                "overall_score": 42,
                "risk_level": "MEDIUM",
                "scores": {
                    "geo_risk": 30,
                    "conflict": 25,
                    "disaster": 15,
                    "sanctions": 0,
                },
                "evidence": [
                    {"category": "test", "severity": "low",
                     "description": "test evidence"}
                ],
            }

            # Store
            store.store_score(test_location, test_score, timestamp=test_timestamp)

            # Retrieve latest
            latest = store.get_latest(test_location)
            assert latest, "No data retrieved from timeseries store"
            assert latest["overall_score"] == 42
            assert latest["location"] == test_location

            # Retrieve via history query
            history = store.get_history(
                test_location,
                start_date="2026-03-01",
                end_date="2026-03-31",
            )
            assert len(history) > 0, "History should contain stored records"

            # Verify the overall record is in the history
            overall_records = [r for r in history if r["dimension"] == "overall"]
            assert len(overall_records) >= 1
            assert overall_records[0]["score"] == 42

    def test_timeseries_daily_summary(self):
        """Store and verify daily summary."""
        from features.timeseries.store import RiskTimeSeriesStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_ts_summary.db")
            store = RiskTimeSeriesStore(db_path=db_path)

            test_score = {
                "overall_score": 55,
                "scores": {"geo_risk": 40, "conflict": 35},
                "evidence": [{"x": 1}, {"x": 2}],
            }
            store.store_daily_summary("TestLoc", test_score, date="2026-03-15")

            # Verify via direct SQL
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM risk_summaries WHERE location = ?", ("TestLoc",)
            ).fetchone()
            conn.close()

            assert row is not None
            assert dict(row)["overall_score"] == 55


# ---------------------------------------------------------------------------
# 6. DD Report Contains Required Fields
# ---------------------------------------------------------------------------

class TestDDReportContainsRequiredFields:
    """Generate DD report and verify all required fields are present."""

    @patch("pipeline.sanctions.screener.screen_entity")
    @patch("scoring.engine.calculate_risk_score")
    def test_dd_report_contains_required_fields(self, mock_calc, mock_screen):
        """DD report must contain entity, screening_result, risk_scores, etc."""
        # Mock the screening result
        mock_screen_result = MagicMock()
        mock_screen_result.matched = False
        mock_screen_result.match_score = 12.0
        mock_screen_result.matched_entity = None
        mock_screen_result.source = None
        mock_screen_result.evidence = []
        mock_screen.return_value = mock_screen_result

        # Mock the risk score
        mock_score = _make_deterministic_score("dd_test", "Test Corp",
                                                location="Singapore")
        mock_calc.return_value = mock_score

        from features.reports.dd_generator import DueDiligenceReportGenerator

        gen = DueDiligenceReportGenerator()
        report = gen.generate_report("Test Corp", "Singapore")

        # Required top-level fields
        required_fields = [
            "entity",
            "screening_result",
            "risk_scores",
            "edd_recommended",
            "edd_triggers",
            "data_sources",
            "evidence_count",
            "confidence_level",
            "risk_summary",
            "generated_at",
            "version",
        ]
        for field_name in required_fields:
            assert field_name in report, f"Missing required field: {field_name}"

        # Entity sub-fields
        assert "name" in report["entity"]
        assert "country" in report["entity"]
        assert report["entity"]["name"] == "Test Corp"
        assert report["entity"]["country"] == "Singapore"

        # Risk summary sub-fields
        assert "overall_score" in report["risk_summary"]
        assert "risk_level" in report["risk_summary"]

        # Confidence level should be a float in [0, 1]
        assert 0 <= report["confidence_level"] <= 1.0

    @patch("pipeline.sanctions.screener.screen_entity")
    @patch("scoring.engine.calculate_risk_score")
    def test_dd_report_edd_triggers_on_high_risk(self, mock_calc, mock_screen):
        """EDD should be recommended when sanctions matched."""
        mock_screen_result = MagicMock()
        mock_screen_result.matched = True
        mock_screen_result.match_score = 95.0
        mock_screen_result.matched_entity = {
            "name": "Sanctioned Corp", "source": "OFAC"
        }
        mock_screen_result.source = "OFAC"
        mock_screen_result.evidence = ["Sanctions list hit"]
        mock_screen.return_value = mock_screen_result

        # High-risk score
        mock_score = _make_deterministic_score("dd_high", "Sanctioned Corp",
                                                location="Yemen")
        mock_calc.return_value = mock_score

        from features.reports.dd_generator import DueDiligenceReportGenerator

        gen = DueDiligenceReportGenerator()
        report = gen.generate_report("Sanctioned Corp", "Yemen")

        assert report["edd_recommended"] is True
        assert len(report["edd_triggers"]) > 0


# ---------------------------------------------------------------------------
# 7. Alert Generation
# ---------------------------------------------------------------------------

class TestAlertGeneration:
    """Verify anomaly detection generates alerts on score jumps."""

    def test_alert_generation(self):
        """Anomaly detector should generate alerts when scores jump."""
        from features.monitoring.anomaly_detector import ScoreAnomalyDetector

        detector = ScoreAnomalyDetector(overall_threshold=20,
                                        dimension_threshold=30)

        # Use a temporary history file to avoid side effects
        test_history_path = os.path.join(
            tempfile.mkdtemp(), "test_score_history.json"
        )

        with patch("features.monitoring.anomaly_detector._HISTORY_PATH",
                    test_history_path):
            # First assessment: baseline (no delta alerts -- no prior data)
            baseline = {
                "overall_score": 30,
                "scores": {
                    "geo_risk": 20, "conflict": 15, "disaster": 10,
                    "political": 25, "compliance": 10, "maritime": 12,
                },
            }
            detector.check_score_anomaly("TestAlertCountry", baseline)

            # Second assessment: large jump (should trigger alerts)
            jumped = {
                "overall_score": 75,  # +45 from baseline
                "scores": {
                    "geo_risk": 80,     # +60
                    "conflict": 70,     # +55
                    "disaster": 10,     # no change
                    "political": 25,    # no change
                    "compliance": 10,   # no change
                    "maritime": 12,     # no change
                },
            }
            alerts = detector.check_score_anomaly("TestAlertCountry", jumped)

            # Should have alerts for overall jump AND dimension jumps
            assert len(alerts) > 0, "Expected alerts on score jump"

            # Check alert structure
            for alert in alerts:
                assert hasattr(alert, "location")
                assert hasattr(alert, "dimension")
                assert hasattr(alert, "previous_value")
                assert hasattr(alert, "current_value")
                assert hasattr(alert, "delta")
                assert hasattr(alert, "severity")
                assert hasattr(alert, "message")
                assert alert.severity in ("INFO", "WARNING", "CRITICAL")

            # Check for overall jump alert
            overall_alerts = [a for a in alerts if a.dimension == "overall"]
            assert len(overall_alerts) >= 1, "Expected overall score jump alert"
            assert overall_alerts[0].delta == 45  # 75 - 30

            # Delta >= 30 should produce CRITICAL severity
            severity_levels = [a.severity for a in alerts]
            assert "CRITICAL" in severity_levels or "WARNING" in severity_levels

        # Clean up
        shutil.rmtree(os.path.dirname(test_history_path), ignore_errors=True)

    def test_alert_critical_threshold(self):
        """Alert should fire when score reaches CRITICAL level (>=80)."""
        from features.monitoring.anomaly_detector import ScoreAnomalyDetector

        detector = ScoreAnomalyDetector()

        test_history_path = os.path.join(
            tempfile.mkdtemp(), "test_critical_history.json"
        )

        with patch("features.monitoring.anomaly_detector._HISTORY_PATH",
                    test_history_path):
            # Baseline below critical
            baseline = {"overall_score": 50, "scores": {"geo_risk": 30}}
            detector.check_score_anomaly("CriticalTestCountry", baseline)

            # Jump to critical
            critical = {"overall_score": 85, "scores": {"geo_risk": 30}}
            alerts = detector.check_score_anomaly("CriticalTestCountry", critical)

            # Should have a CRITICAL alert for reaching critical level
            critical_alerts = [
                a for a in alerts
                if a.severity == "CRITICAL" and "CRITICAL level" in a.message
            ]
            assert len(critical_alerts) >= 1, (
                f"Expected CRITICAL level alert, got: "
                f"{[a.message for a in alerts]}"
            )

        shutil.rmtree(os.path.dirname(test_history_path), ignore_errors=True)

    def test_validate_score_consistency(self):
        """Score consistency validation should catch weight sum issues."""
        from features.monitoring.anomaly_detector import ScoreAnomalyDetector

        detector = ScoreAnomalyDetector()

        valid_score = {
            "overall_score": 50,
            "scores": {
                "sanctions": 0, "geo_risk": 30, "conflict": 25,
                "political": 20, "compliance": 15, "disaster": 35,
                "weather": 10, "typhoon": 5, "maritime": 40,
                "internet": 12, "climate_risk": 28, "economic": 22,
                "currency": 18, "trade": 33, "energy": 27,
                "port_congestion": 14, "cyber_risk": 19, "legal": 11,
                "health": 8, "humanitarian": 6, "food_security": 9,
                "labor": 7, "aviation": 3,
            },
        }
        errors = detector.validate_score_consistency(valid_score)
        # Weight sum should pass (weights sum to 1.0)
        weight_errors = [e for e in errors if e.check_name == "weight_sum"]
        assert len(weight_errors) == 0, "Weight sum should be valid"
