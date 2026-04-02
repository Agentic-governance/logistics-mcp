"""Sanctions screening unit tests"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

class TestSanctionsScreening:
    def test_ofac_normalization(self):
        """Entity name normalization should handle common patterns"""
        from pipeline.sanctions.screener import normalize_name
        assert normalize_name("ABC CO., LTD.") == normalize_name("abc co ltd")

    def test_clean_entity_returns_result(self):
        """Clean entity should return no match"""
        from pipeline.sanctions.screener import screen_entity
        result = screen_entity("Toyota Motor Corporation", "Japan")
        # Toyota should not be sanctioned
        assert result.matched == False or result.match_score < 90

    def test_screen_returns_required_fields(self):
        """Screening result should have all required fields"""
        from pipeline.sanctions.screener import screen_entity
        result = screen_entity("Test Company", "US")
        assert hasattr(result, 'matched')
        assert hasattr(result, 'match_score')
        assert hasattr(result, 'source')
        assert hasattr(result, 'evidence')
