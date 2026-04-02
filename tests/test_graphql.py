"""GraphQL スキーマ & クエリ テスト

strawberry-graphql ベースの GraphQL エンドポイントを検証する。
外部 API 呼び出しはすべてモック化。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_calculate_risk_score(supplier_id, company_name, country=None, location=None):
    """テスト用のモックリスクスコア"""
    from scoring.engine import SupplierRiskScore
    score = SupplierRiskScore(supplier_id=supplier_id, company_name=company_name)
    for dim in SupplierRiskScore.WEIGHTS:
        setattr(score, f"{dim}_score", 35)
    score.sanction_score = 0
    score.japan_economy_score = 10
    score.calculate_overall()
    return score


def _mock_screen_entity(name, country=None):
    """テスト用のモック制裁スクリーニング"""
    m = MagicMock()
    m.matched = False
    m.match_score = 12.0
    m.source = None
    m.matched_entity = None
    m.evidence = []
    if "sanction" in name.lower():
        m.matched = True
        m.match_score = 95.0
        m.source = "OFAC"
        m.matched_entity = "SANCTIONED ENTITY"
    return m


class TestGraphQLSchemaStructure:
    """GraphQL スキーマ構造テスト"""

    def test_schema_exists(self):
        """スキーマオブジェクトの存在確認"""
        from api.graphql_schema import schema
        assert schema is not None

    def test_graphql_router_exists(self):
        """GraphQLRouter の存在確認"""
        from api.graphql_schema import graphql_router
        assert graphql_router is not None

    def test_schema_has_query_type(self):
        """スキーマに Query タイプが定義されている"""
        from api.graphql_schema import schema
        # strawberry schema で execute_sync が利用可能
        # 簡単なイントロスペクションクエリで Query タイプの存在を確認
        result = schema.execute_sync("{ __schema { queryType { name } } }")
        assert result.errors is None
        assert result.data["__schema"]["queryType"]["name"] == "Query"


class TestGraphQLCompanyQuery:
    """company クエリテスト"""

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_company_query_returns_result(self, mock_calc):
        """company(name: "Japan") がリスクスコアを返す"""
        from api.graphql_schema import schema
        result = schema.execute_sync('{ company(name: "Japan") { name riskScore riskLevel } }')
        assert result.errors is None
        assert result.data["company"]["name"] == "Japan"
        assert isinstance(result.data["company"]["riskScore"], int)
        assert result.data["company"]["riskLevel"] in (
            "CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL"
        )

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_company_query_country_field(self, mock_calc):
        """country フィールドが返される"""
        from api.graphql_schema import schema
        result = schema.execute_sync('{ company(name: "China") { country } }')
        assert result.errors is None
        assert result.data["company"]["country"] == "China"


class TestGraphQLSanctionsQuery:
    """searchSanctions クエリテスト"""

    @patch("pipeline.sanctions.screener.screen_entity", side_effect=_mock_screen_entity)
    def test_sanctions_no_match(self, mock_screen):
        """制裁リスト非該当のクエリ"""
        from api.graphql_schema import schema
        result = schema.execute_sync(
            '{ searchSanctions(entityName: "Toyota") { companyName matched matchScore } }'
        )
        assert result.errors is None
        data = result.data["searchSanctions"]
        assert data["companyName"] == "Toyota"
        assert data["matched"] is False

    @patch("pipeline.sanctions.screener.screen_entity", side_effect=_mock_screen_entity)
    def test_sanctions_match(self, mock_screen):
        """制裁リスト該当のクエリ"""
        from api.graphql_schema import schema
        result = schema.execute_sync(
            '{ searchSanctions(entityName: "Sanctioned Entity") { matched matchScore source } }'
        )
        assert result.errors is None
        data = result.data["searchSanctions"]
        assert data["matched"] is True
        assert data["matchScore"] >= 90

    @patch("pipeline.sanctions.screener.screen_entity", side_effect=_mock_screen_entity)
    def test_sanctions_with_country(self, mock_screen):
        """country パラメータ付きクエリ"""
        from api.graphql_schema import schema
        result = schema.execute_sync(
            '{ searchSanctions(entityName: "TestCo", country: "Russia") { companyName matched } }'
        )
        assert result.errors is None
        assert result.data["searchSanctions"]["companyName"] == "TestCo"


class TestGraphQLPersonCheckQuery:
    """personCheck クエリテスト"""

    @patch("pipeline.sanctions.screener.screen_entity", side_effect=_mock_screen_entity)
    def test_person_check_clean(self, mock_screen):
        """制裁非該当の人物チェック"""
        from api.graphql_schema import schema
        result = schema.execute_sync(
            '{ personCheck(name: "John Doe") { name isPep sanctionsHit } }'
        )
        assert result.errors is None
        data = result.data["personCheck"]
        assert data["name"] == "John Doe"
        assert data["sanctionsHit"] is False

    @patch("pipeline.sanctions.screener.screen_entity", side_effect=_mock_screen_entity)
    def test_person_check_sanctioned(self, mock_screen):
        """制裁該当の人物チェック"""
        from api.graphql_schema import schema
        result = schema.execute_sync(
            '{ personCheck(name: "Sanctioned Person") { name sanctionsHit } }'
        )
        assert result.errors is None
        assert result.data["personCheck"]["sanctionsHit"] is True


class TestGraphQLRiskDashboard:
    """riskDashboard クエリテスト"""

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_dashboard_returns_list(self, mock_calc):
        """ダッシュボードが国リストを返す"""
        from api.graphql_schema import schema
        result = schema.execute_sync(
            '{ riskDashboard(limit: 3) { name riskScore riskLevel } }'
        )
        assert result.errors is None
        assert isinstance(result.data["riskDashboard"], list)
        assert len(result.data["riskDashboard"]) <= 3


class TestGraphQLRiskDetail:
    """riskDetail クエリテスト"""

    @patch("scoring.engine.calculate_risk_score", side_effect=_mock_calculate_risk_score)
    def test_risk_detail_dimensions(self, mock_calc):
        """riskDetail がディメンション一覧を返す"""
        from api.graphql_schema import schema
        result = schema.execute_sync(
            '{ riskDetail(country: "Japan") { name riskScore dimensions { dimension score weight } evidenceCount } }'
        )
        assert result.errors is None
        data = result.data["riskDetail"]
        assert data["name"] == "Japan"
        assert isinstance(data["dimensions"], list)
        assert len(data["dimensions"]) > 0
        # 各ディメンションに必要なフィールドが存在
        for dim in data["dimensions"]:
            assert "dimension" in dim
            assert "score" in dim
            assert "weight" in dim


class TestGraphQLSearchPath:
    """searchPath クエリテスト"""

    @patch("features.route_risk.analyzer.RouteRiskAnalyzer.get_chokepoint_risk")
    def test_search_path_valid_route(self, mock_cp):
        """有効なルートのパス検索"""
        mock_cp.return_value = {
            "chokepoint_id": "malacca",
            "name": "Strait of Malacca",
            "risk_score": 30,
            "risk_factors": ["piracy"],
            "evidence": [],
            "timestamp": "2026-03-27T00:00:00",
        }
        from api.graphql_schema import schema
        result = schema.execute_sync(
            '{ searchPath(origin: "Tokyo", destination: "Singapore") { path totalRisk hops } }'
        )
        assert result.errors is None
        data = result.data["searchPath"]
        assert isinstance(data["path"], list)
        assert data["hops"] >= 0

    def test_search_path_unknown_port(self):
        """未知の港のパス検索"""
        from api.graphql_schema import schema
        result = schema.execute_sync(
            '{ searchPath(origin: "UnknownXYZ", destination: "Rotterdam") { path totalRisk hops } }'
        )
        assert result.errors is None
        # エラーではなく、空パスが返る
        data = result.data["searchPath"]
        assert data["hops"] == 0
