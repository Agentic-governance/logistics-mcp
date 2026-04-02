"""Person-Company Graph テスト

UBO（実質的支配者）チェーン、役員ネットワーク、制裁対象者検出、
OpenSanctions グラフのテスト。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock


class TestPersonCompanyGraphBasics:
    """基本的なグラフ操作テスト"""

    def test_graph_instantiation(self):
        """PersonCompanyGraph のインスタンス化"""
        from features.graph.person_company_graph import PersonCompanyGraph
        graph = PersonCompanyGraph()
        assert graph is not None
        assert graph.graph.number_of_nodes() == 0

    def test_add_company_node(self):
        """企業ノード追加テスト"""
        from features.graph.person_company_graph import PersonCompanyGraph
        graph = PersonCompanyGraph()
        graph.add_company("Acme Corp", country="US", risk_score=30)
        assert "Acme Corp" in graph.graph
        attrs = graph.graph.nodes["Acme Corp"]
        assert attrs["node_type"] == "company"
        assert attrs["country"] == "US"
        assert attrs["risk_score"] == 30

    def test_add_person_node(self):
        """個人ノード追加テスト"""
        from features.graph.person_company_graph import PersonCompanyGraph
        graph = PersonCompanyGraph()
        graph.add_person("Taro Yamada", nationality="JP", is_pep=True)
        assert "Taro Yamada" in graph.graph
        attrs = graph.graph.nodes["Taro Yamada"]
        assert attrs["node_type"] == "person"
        assert attrs["nationality"] == "JP"
        assert attrs["is_pep"] is True

    def test_add_edge(self):
        """エッジ追加テスト"""
        from features.graph.person_company_graph import (
            PersonCompanyGraph, RELATION_CONTROLS,
        )
        graph = PersonCompanyGraph()
        graph.add_company("TestCo")
        graph.add_person("TestPerson")
        graph.add_edge("TestPerson", "TestCo", RELATION_CONTROLS, ownership_pct=51.0)
        assert graph.graph.has_edge("TestPerson", "TestCo")
        edge = graph.graph.edges["TestPerson", "TestCo"]
        assert edge["relation_type"] == RELATION_CONTROLS
        assert edge["ownership_pct"] == 51.0

    def test_add_edge_auto_creates_nodes(self):
        """エッジ追加時にノードが自動作成されるか"""
        from features.graph.person_company_graph import (
            PersonCompanyGraph, RELATION_DIRECTOR_OF,
        )
        graph = PersonCompanyGraph()
        graph.add_edge("AutoPerson", "AutoCompany", RELATION_DIRECTOR_OF)
        assert "AutoPerson" in graph.graph
        assert "AutoCompany" in graph.graph


class TestGraphPathFinding:
    """パス検索テスト"""

    def _build_sample_graph(self):
        """テスト用グラフ構築"""
        from features.graph.person_company_graph import (
            PersonCompanyGraph, RELATION_CONTROLS, RELATION_DIRECTOR_OF,
            RELATION_ASSOCIATED_WITH,
        )
        graph = PersonCompanyGraph()

        graph.add_company("CompanyA", country="US")
        graph.add_company("CompanyB", country="BVI")
        graph.add_company("CompanyC", country="RU")

        graph.add_person("Person1", nationality="US")
        graph.add_person("Person2", nationality="RU", sanctions_hit=True)
        graph.add_person("Person3", nationality="JP", is_pep=True)

        graph.add_edge("Person1", "CompanyA", RELATION_CONTROLS, ownership_pct=60)
        graph.add_edge("Person1", "CompanyB", RELATION_DIRECTOR_OF)
        graph.add_edge("Person2", "CompanyB", RELATION_CONTROLS, ownership_pct=100)
        graph.add_edge("Person2", "CompanyC", RELATION_ASSOCIATED_WITH)
        graph.add_edge("Person3", "CompanyA", RELATION_DIRECTOR_OF)

        return graph

    def test_find_path_direct(self):
        """直接接続されたパスの検出"""
        graph = self._build_sample_graph()
        paths = graph.find_path("Person1", "CompanyA")
        assert len(paths) >= 1
        assert paths[0] == ["Person1", "CompanyA"]

    def test_find_path_indirect(self):
        """間接パスの検出（Person1→CompanyB→Person2）"""
        graph = self._build_sample_graph()
        paths = graph.find_path("Person1", "Person2", max_hops=3)
        assert len(paths) >= 1
        # Person1 -> CompanyB -> Person2 がパスに含まれるはず
        found_path = False
        for path in paths:
            if "CompanyB" in path:
                found_path = True
                break
        assert found_path, f"Expected path through CompanyB, got {paths}"

    def test_find_path_no_connection(self):
        """接続なしの場合は空リスト"""
        from features.graph.person_company_graph import PersonCompanyGraph
        graph = PersonCompanyGraph()
        graph.add_company("IsolatedA")
        graph.add_company("IsolatedB")
        paths = graph.find_path("IsolatedA", "IsolatedB")
        assert paths == []

    def test_find_path_nonexistent_node(self):
        """存在しないノードは空リスト"""
        graph = self._build_sample_graph()
        paths = graph.find_path("NonExistent", "CompanyA")
        assert paths == []


class TestRiskExposure:
    """リスクエクスポージャー検出テスト"""

    def _build_risk_graph(self):
        """リスク検出テスト用グラフ"""
        from features.graph.person_company_graph import (
            PersonCompanyGraph, RELATION_CONTROLS, RELATION_DIRECTOR_OF,
            RELATION_ASSOCIATED_WITH,
        )
        graph = PersonCompanyGraph()

        graph.add_company("TargetCorp", country="JP", risk_score=20)
        graph.add_company("ShellCo", country="BVI", risk_score=60)

        graph.add_person("Clean CEO", nationality="JP")
        graph.add_person("Sanctioned Oligarch", nationality="RU", sanctions_hit=True)
        graph.add_person("PEP Minister", nationality="CN", is_pep=True)
        graph.add_person("HighRisk Trader", nationality="AE", risk_score=70)

        graph.add_edge("Clean CEO", "TargetCorp", RELATION_CONTROLS, ownership_pct=51)
        graph.add_edge("Clean CEO", "ShellCo", RELATION_DIRECTOR_OF)
        graph.add_edge("Sanctioned Oligarch", "ShellCo", RELATION_CONTROLS, ownership_pct=100)
        graph.add_edge("PEP Minister", "TargetCorp", RELATION_ASSOCIATED_WITH)
        graph.add_edge("HighRisk Trader", "ShellCo", RELATION_ASSOCIATED_WITH)

        return graph

    def test_risk_exposure_detects_sanctions(self):
        """制裁対象者の検出"""
        graph = self._build_risk_graph()
        exposure = graph.get_risk_exposure("TargetCorp", max_hops=3)
        assert len(exposure["sanctioned_persons"]) >= 1
        names = [p["name"] for p in exposure["sanctioned_persons"]]
        assert "Sanctioned Oligarch" in names

    def test_risk_exposure_detects_pep(self):
        """PEP の検出"""
        graph = self._build_risk_graph()
        exposure = graph.get_risk_exposure("TargetCorp", max_hops=3)
        assert len(exposure["pep_persons"]) >= 1
        names = [p["name"] for p in exposure["pep_persons"]]
        assert "PEP Minister" in names

    def test_risk_exposure_sanctions_gives_100(self):
        """制裁対象者が存在する場合、total_risk_score = 100"""
        graph = self._build_risk_graph()
        exposure = graph.get_risk_exposure("TargetCorp", max_hops=3)
        assert exposure["total_risk_score"] == 100

    def test_risk_exposure_unknown_company(self):
        """未知の企業は空のエクスポージャーを返す"""
        graph = self._build_risk_graph()
        exposure = graph.get_risk_exposure("UnknownCorp")
        assert exposure["total_risk_score"] == 0
        assert exposure["sanctioned_persons"] == []

    def test_risk_paths_contain_hops(self):
        """リスクパスにホップ数が含まれる"""
        graph = self._build_risk_graph()
        exposure = graph.get_risk_exposure("TargetCorp", max_hops=3)
        for rp in exposure["risk_paths"]:
            assert "hops" in rp
            assert rp["hops"] >= 1
            assert "path" in rp
            assert len(rp["path"]) >= 2


class TestUBOGraphBuilding:
    """UBOレコードからのグラフ構築テスト"""

    def test_build_from_ubo_dict(self):
        """辞書形式 UBO レコードからグラフ構築"""
        from features.graph.person_company_graph import PersonCompanyGraph
        graph = PersonCompanyGraph()

        ubo_records = [
            {"person_name": "Owner A", "nationality": "JP", "ownership_pct": 51.0,
             "is_pep": False, "sanctions_hit": False},
            {"person_name": "Owner B", "nationality": "CN", "ownership_pct": 30.0,
             "is_pep": True, "sanctions_hit": False},
        ]
        graph.build_from_ubo("TestCorp", ubo_records)

        assert "TestCorp" in graph.graph
        assert "Owner A" in graph.graph
        assert "Owner B" in graph.graph
        assert graph.graph.has_edge("Owner A", "TestCorp")
        assert graph.graph.has_edge("Owner B", "TestCorp")

    def test_build_from_ubo_empty(self):
        """空の UBO レコードでもエラーにならない"""
        from features.graph.person_company_graph import PersonCompanyGraph
        graph = PersonCompanyGraph()
        graph.build_from_ubo("EmptyCorp", [])
        assert "EmptyCorp" in graph.graph
        assert graph.graph.number_of_edges() == 0


class TestWikidataGraphBuilding:
    """Wikidata データからのグラフ構築テスト"""

    def test_build_from_wikidata(self):
        """Wikidata 経営幹部・取締役データからグラフ構築"""
        from features.graph.person_company_graph import PersonCompanyGraph
        graph = PersonCompanyGraph()

        executives = [
            {"name": "CEO Tanaka", "nationality": "JP", "position": "CEO", "wikidata_id": "Q123"},
        ]
        board_members = [
            {"name": "Director Suzuki", "board_role": "Independent Director",
             "other_boards": ["OtherCorp"], "wikidata_id": "Q456"},
        ]
        graph.build_from_wikidata("TestCorp", executives, board_members)

        assert "TestCorp" in graph.graph
        assert "CEO Tanaka" in graph.graph
        assert "Director Suzuki" in graph.graph
        # 兼任先企業も追加される
        assert "OtherCorp" in graph.graph

    def test_interlocking_directors_detected(self):
        """兼任取締役のネットワーク検出"""
        from features.graph.person_company_graph import PersonCompanyGraph
        graph = PersonCompanyGraph()

        board_members = [
            {"name": "Shared Director", "board_role": "Director",
             "other_boards": ["CompanyB", "CompanyC"], "wikidata_id": "Q789"},
        ]
        graph.build_from_wikidata("CompanyA", [], board_members)

        # Shared Director はすべての企業に接続
        assert graph.graph.has_edge("Shared Director", "CompanyA")
        assert graph.graph.has_edge("Shared Director", "CompanyB")
        assert graph.graph.has_edge("Shared Director", "CompanyC")

        # パス検索: CompanyA → CompanyB（Shared Director 経由）
        paths = graph.find_path("CompanyA", "CompanyB", max_hops=2)
        assert len(paths) >= 1


class TestGraphExport:
    """グラフエクスポートテスト"""

    def test_to_dict_structure(self):
        """to_dict() の構造検証"""
        from features.graph.person_company_graph import (
            PersonCompanyGraph, RELATION_CONTROLS,
        )
        graph = PersonCompanyGraph()
        graph.add_company("TestCo", country="JP")
        graph.add_person("TestPerson", nationality="JP")
        graph.add_edge("TestPerson", "TestCo", RELATION_CONTROLS)

        d = graph.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert "node_count" in d
        assert "edge_count" in d
        assert "person_count" in d
        assert "company_count" in d
        assert d["node_count"] == 2
        assert d["edge_count"] == 1
        assert d["person_count"] == 1
        assert d["company_count"] == 1

    def test_get_stats(self):
        """統計情報テスト"""
        from features.graph.person_company_graph import (
            PersonCompanyGraph, RELATION_CONTROLS,
        )
        graph = PersonCompanyGraph()
        graph.add_company("Co1")
        graph.add_company("Co2")
        graph.add_person("P1", sanctions_hit=True)
        graph.add_person("P2", is_pep=True)
        graph.add_edge("P1", "Co1", RELATION_CONTROLS)
        graph.add_edge("P2", "Co2", RELATION_CONTROLS)

        stats = graph.get_stats()
        assert stats["total_nodes"] == 4
        assert stats["total_edges"] == 2
        assert stats["persons"] == 2
        assert stats["companies"] == 2
        assert stats["sanctioned_persons"] == 1
        assert stats["pep_persons"] == 1


class TestConnectedPersonRisks:
    """接続された人物のリスク集約テスト"""

    def test_connected_person_risks_basic(self):
        """基本的な接続人物リスクテスト"""
        from features.graph.person_company_graph import (
            PersonCompanyGraph, RELATION_DIRECTOR_OF,
        )
        graph = PersonCompanyGraph()
        graph.add_company("SharedCo")
        graph.add_person("PersonA", risk_score=20)
        graph.add_person("PersonB", sanctions_hit=True)
        graph.add_edge("PersonA", "SharedCo", RELATION_DIRECTOR_OF)
        graph.add_edge("PersonB", "SharedCo", RELATION_DIRECTOR_OF)

        result = graph.get_connected_person_risks("PersonA", max_hops=2)
        assert result["sanctioned_count"] >= 1
        assert result["max_risk_score"] >= 100  # 制裁ヒットは100

    def test_connected_person_risks_nonexistent(self):
        """存在しない人物に対する空の結果"""
        from features.graph.person_company_graph import PersonCompanyGraph
        graph = PersonCompanyGraph()
        result = graph.get_connected_person_risks("Nobody")
        assert result["connected_persons"] == []
        assert result["avg_risk_score"] == 0.0


class TestRelationConstants:
    """関係タイプ定数テスト"""

    def test_all_relation_types_defined(self):
        """全関係タイプ定数が定義されている"""
        from features.graph.person_company_graph import (
            RELATION_CONTROLS,
            RELATION_DIRECTOR_OF,
            RELATION_EXECUTIVE_OF,
            RELATION_ASSOCIATED_WITH,
            RELATION_OWNS,
            RELATION_SUBSIDIARY_OF,
        )
        assert RELATION_CONTROLS == "CONTROLS"
        assert RELATION_DIRECTOR_OF == "DIRECTOR_OF"
        assert RELATION_EXECUTIVE_OF == "EXECUTIVE_OF"
        assert RELATION_ASSOCIATED_WITH == "ASSOCIATED_WITH"
        assert RELATION_OWNS == "OWNS"
        assert RELATION_SUBSIDIARY_OF == "SUBSIDIARY_OF"
