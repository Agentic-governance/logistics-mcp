"""人-企業グラフ（Person-Company Graph）
NetworkX ベースの有向グラフで個人と企業の関係を管理する。

用途:
  - UBO（実質的支配者）チェーンの可視化
  - 兼任役員ネットワークの検出
  - N ホップ以内の制裁対象者・PEP 検出
  - リスク伝播分析
"""

import logging
from typing import Optional

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx が必要です: pip install networkx")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 関係タイプ定数
# ---------------------------------------------------------------------------
RELATION_CONTROLS = "CONTROLS"             # 支配関係（UBO）
RELATION_DIRECTOR_OF = "DIRECTOR_OF"       # 取締役
RELATION_EXECUTIVE_OF = "EXECUTIVE_OF"     # 経営幹部（CEO等）
RELATION_ASSOCIATED_WITH = "ASSOCIATED_WITH"  # その他関連
RELATION_OWNS = "OWNS"                     # 所有（企業→企業）
RELATION_SUBSIDIARY_OF = "SUBSIDIARY_OF"   # 子会社


# ---------------------------------------------------------------------------
# PersonCompanyGraph
# ---------------------------------------------------------------------------
class PersonCompanyGraph:
    """人-企業有向グラフ

    ノードタイプ:
      - person: 個人（UBO、役員、取締役等）
      - company: 企業

    エッジタイプ:
      - CONTROLS: 支配関係（UBO → 企業）
      - DIRECTOR_OF: 取締役関係
      - EXECUTIVE_OF: 経営幹部関係
      - ASSOCIATED_WITH: その他関連
      - OWNS: 企業間所有関係
      - SUBSIDIARY_OF: 子会社関係
    """

    def __init__(self):
        self.graph = nx.DiGraph()

    # ---- Node operations --------------------------------------------------

    def add_company(
        self,
        name: str,
        country: str = "",
        risk_score: int = 0,
        **attributes,
    ):
        """企業ノードを追加する。"""
        self.graph.add_node(
            name,
            node_type="company",
            country=country,
            risk_score=risk_score,
            **attributes,
        )
        logger.debug("企業ノード追加: %s (%s)", name, country)

    def add_person(
        self,
        name: str,
        nationality: str = "",
        is_pep: bool = False,
        sanctions_hit: bool = False,
        **attributes,
    ):
        """個人ノードを追加する。"""
        self.graph.add_node(
            name,
            node_type="person",
            nationality=nationality,
            is_pep=is_pep,
            sanctions_hit=sanctions_hit,
            **attributes,
        )
        logger.debug("個人ノード追加: %s (%s, PEP=%s, 制裁=%s)",
                      name, nationality, is_pep, sanctions_hit)

    def add_edge(
        self,
        person: str,
        company: str,
        relation_type: str,
        **attributes,
    ):
        """人-企業間のエッジを追加する。

        Args:
            person: 人物名（始点）
            company: 企業名（終点）
            relation_type: 関係タイプ ("CONTROLS", "DIRECTOR_OF", "ASSOCIATED_WITH" 等)
            **attributes: 追加属性（ownership_pct 等）
        """
        # ノードが存在しない場合は自動追加
        if person not in self.graph:
            self.add_person(person)
        if company not in self.graph:
            self.add_company(company)

        self.graph.add_edge(
            person,
            company,
            relation_type=relation_type,
            **attributes,
        )
        logger.debug("エッジ追加: %s -[%s]-> %s", person, relation_type, company)

    # ---- Query operations -------------------------------------------------

    def find_path(
        self,
        entity1: str,
        entity2: str,
        max_hops: int = 3,
    ) -> list[list[str]]:
        """2エンティティ間の全経路（max_hops以内）を検出する。

        Args:
            entity1: 始点エンティティ名
            entity2: 終点エンティティ名
            max_hops: 最大ホップ数

        Returns:
            経路リストのリスト
        """
        if entity1 not in self.graph or entity2 not in self.graph:
            return []

        try:
            # 有向グラフの双方向パスを検索
            undirected = self.graph.to_undirected()
            paths = list(nx.all_simple_paths(undirected, entity1, entity2, cutoff=max_hops))
            return paths
        except (nx.NetworkXError, nx.NodeNotFound):
            return []

    def get_risk_exposure(
        self,
        company: str,
        max_hops: int = 3,
    ) -> dict:
        """3ホップ以内の制裁対象者・PEPを検出する。

        Args:
            company: 対象企業名
            max_hops: 探索最大ホップ数

        Returns:
            {
                "company": str,
                "sanctioned_persons": [...],
                "pep_persons": [...],
                "high_risk_persons": [...],
                "total_risk_score": int,
                "risk_paths": [...],
            }
        """
        if company not in self.graph:
            return {
                "company": company,
                "sanctioned_persons": [],
                "pep_persons": [],
                "high_risk_persons": [],
                "total_risk_score": 0,
                "risk_paths": [],
            }

        sanctioned: list[dict] = []
        peps: list[dict] = []
        high_risk: list[dict] = []
        risk_paths: list[dict] = []

        # BFSで max_hops 以内の全ノードを探索
        undirected = self.graph.to_undirected()
        try:
            reachable = nx.single_source_shortest_path_length(undirected, company, cutoff=max_hops)
        except nx.NodeNotFound:
            reachable = {}

        for node, distance in reachable.items():
            if node == company:
                continue
            attrs = self.graph.nodes.get(node, {})
            node_type = attrs.get("node_type", "")

            if node_type != "person":
                continue

            person_info = {
                "name": node,
                "nationality": attrs.get("nationality", ""),
                "distance_hops": distance,
            }

            # 制裁対象チェック
            if attrs.get("sanctions_hit", False):
                sanctioned.append(person_info)
                # パスを取得
                try:
                    path = nx.shortest_path(undirected, company, node)
                    risk_paths.append({
                        "person": node,
                        "risk_type": "SANCTIONS",
                        "path": path,
                        "hops": len(path) - 1,
                    })
                except nx.NetworkXNoPath:
                    pass

            # PEPチェック
            if attrs.get("is_pep", False):
                peps.append(person_info)
                try:
                    path = nx.shortest_path(undirected, company, node)
                    risk_paths.append({
                        "person": node,
                        "risk_type": "PEP",
                        "path": path,
                        "hops": len(path) - 1,
                    })
                except nx.NetworkXNoPath:
                    pass

            # その他高リスク（制裁+PEP以外でリスクスコアが高い）
            risk_score = attrs.get("risk_score", 0)
            if risk_score >= 50 and not attrs.get("sanctions_hit") and not attrs.get("is_pep"):
                person_info["risk_score"] = risk_score
                high_risk.append(person_info)

        # 全体リスクスコア算出
        total_risk = 0
        if sanctioned:
            total_risk = 100  # 制裁対象者が存在 → 即100
        elif peps:
            total_risk = max(total_risk, 30 + len(peps) * 10)
        if high_risk:
            avg_risk = sum(p.get("risk_score", 0) for p in high_risk) / len(high_risk)
            total_risk = max(total_risk, int(avg_risk * 0.5))
        total_risk = min(100, total_risk)

        return {
            "company": company,
            "sanctioned_persons": sanctioned,
            "pep_persons": peps,
            "high_risk_persons": high_risk,
            "total_risk_score": total_risk,
            "risk_paths": risk_paths,
            "nodes_explored": len(reachable),
            "max_hops": max_hops,
        }

    # ---- Graph building ---------------------------------------------------

    def build_from_ubo(
        self,
        company_name: str,
        ubo_records: list,
    ):
        """UBOレコードリストからグラフを構築する。

        Args:
            company_name: 対象企業名
            ubo_records: UBORecord のリスト（dataclass or dict）
        """
        self.add_company(company_name)

        for ubo in ubo_records:
            if hasattr(ubo, "person_name"):
                name = ubo.person_name
                nationality = ubo.nationality
                ownership_pct = ubo.ownership_pct
                is_pep = ubo.is_pep
                sanctions_hit = ubo.sanctions_hit
            elif isinstance(ubo, dict):
                name = ubo.get("person_name", ubo.get("name", ""))
                nationality = ubo.get("nationality", "")
                ownership_pct = ubo.get("ownership_pct", 0.0)
                is_pep = ubo.get("is_pep", False)
                sanctions_hit = ubo.get("sanctions_hit", False)
            else:
                continue

            if not name:
                continue

            self.add_person(
                name,
                nationality=nationality,
                is_pep=is_pep,
                sanctions_hit=sanctions_hit,
            )
            self.add_edge(
                name,
                company_name,
                relation_type=RELATION_CONTROLS,
                ownership_pct=ownership_pct,
            )

        logger.info("UBOグラフ構築完了: %s (ノード: %d, エッジ: %d)",
                     company_name, self.graph.number_of_nodes(), self.graph.number_of_edges())

    def build_from_wikidata(
        self,
        company_name: str,
        executives: list,
        board_members: list,
    ):
        """Wikidata の経営幹部・取締役データからグラフを構築する。

        Args:
            company_name: 対象企業名
            executives: Executive のリスト（dataclass or dict）
            board_members: BoardMember のリスト（dataclass or dict）
        """
        self.add_company(company_name)

        # 経営幹部
        for exec_data in executives:
            if hasattr(exec_data, "name"):
                name = exec_data.name
                nationality = exec_data.nationality
                position = exec_data.position
                wikidata_id = exec_data.wikidata_id
            elif isinstance(exec_data, dict):
                name = exec_data.get("name", "")
                nationality = exec_data.get("nationality", "")
                position = exec_data.get("position", "")
                wikidata_id = exec_data.get("wikidata_id", "")
            else:
                continue

            if not name:
                continue

            self.add_person(name, nationality=nationality, wikidata_id=wikidata_id)
            self.add_edge(
                name,
                company_name,
                relation_type=RELATION_EXECUTIVE_OF,
                position=position,
            )

        # 取締役
        for member in board_members:
            if hasattr(member, "name"):
                name = member.name
                board_role = member.board_role
                other_boards = member.other_boards
                wikidata_id = member.wikidata_id
            elif isinstance(member, dict):
                name = member.get("name", "")
                board_role = member.get("board_role", "")
                other_boards = member.get("other_boards", [])
                wikidata_id = member.get("wikidata_id", "")
            else:
                continue

            if not name:
                continue

            self.add_person(name, wikidata_id=wikidata_id)
            self.add_edge(
                name,
                company_name,
                relation_type=RELATION_DIRECTOR_OF,
                board_role=board_role,
            )

            # 兼任先企業もグラフに追加
            for other_company in (other_boards or []):
                if other_company and other_company != company_name:
                    self.add_company(other_company)
                    self.add_edge(
                        name,
                        other_company,
                        relation_type=RELATION_DIRECTOR_OF,
                        board_role="Board Member (兼任)",
                    )

        logger.info("Wikidataグラフ構築完了: %s (ノード: %d, エッジ: %d)",
                     company_name, self.graph.number_of_nodes(), self.graph.number_of_edges())

    # ---- Export -----------------------------------------------------------

    def to_dict(self) -> dict:
        """グラフをJSON化可能な辞書に変換する。"""
        nodes = []
        for node, attrs in self.graph.nodes(data=True):
            node_data = {"id": node, "label": node}
            node_data.update(attrs)
            nodes.append(node_data)

        edges = []
        for src, dst, attrs in self.graph.edges(data=True):
            edge_data = {"source": src, "target": dst}
            edge_data.update(attrs)
            edges.append(edge_data)

        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "person_count": sum(1 for _, d in self.graph.nodes(data=True) if d.get("node_type") == "person"),
            "company_count": sum(1 for _, d in self.graph.nodes(data=True) if d.get("node_type") == "company"),
        }

    def get_connected_person_risks(
        self,
        person_name: str,
        max_hops: int = 2,
    ) -> dict:
        """指定人物と接続された他の人物のリスク情報を集約する。

        PersonRiskScorer のネットワークリスク計算に使用。
        兼任先企業を経由して到達可能な他の人物のリスクスコア平均を返す。

        Args:
            person_name: 対象人物名
            max_hops: 探索最大ホップ数

        Returns:
            {
                "connected_persons": [...],
                "avg_risk_score": float,
                "max_risk_score": int,
                "sanctioned_count": int,
                "pep_count": int,
                "shared_companies": [...],
            }
        """
        if person_name not in self.graph:
            return {
                "connected_persons": [],
                "avg_risk_score": 0.0,
                "max_risk_score": 0,
                "sanctioned_count": 0,
                "pep_count": 0,
                "shared_companies": [],
            }

        undirected = self.graph.to_undirected()
        try:
            reachable = nx.single_source_shortest_path_length(
                undirected, person_name, cutoff=max_hops
            )
        except nx.NodeNotFound:
            reachable = {}

        connected_persons: list[dict] = []
        shared_companies: set[str] = set()
        sanctioned_count = 0
        pep_count = 0

        for node, distance in reachable.items():
            if node == person_name:
                continue
            attrs = self.graph.nodes.get(node, {})
            node_type = attrs.get("node_type", "")

            if node_type == "company":
                shared_companies.add(node)
                continue

            if node_type == "person":
                info = {
                    "name": node,
                    "distance_hops": distance,
                    "is_pep": attrs.get("is_pep", False),
                    "sanctions_hit": attrs.get("sanctions_hit", False),
                    "risk_score": attrs.get("risk_score", 0),
                }
                connected_persons.append(info)
                if attrs.get("sanctions_hit", False):
                    sanctioned_count += 1
                if attrs.get("is_pep", False):
                    pep_count += 1

        # 平均リスクスコア算出
        risk_scores = [p.get("risk_score", 0) for p in connected_persons]
        # 制裁ヒットは100, PEPは50として加算
        for p in connected_persons:
            if p["sanctions_hit"]:
                risk_scores[connected_persons.index(p)] = max(risk_scores[connected_persons.index(p)], 100)
            elif p["is_pep"]:
                risk_scores[connected_persons.index(p)] = max(risk_scores[connected_persons.index(p)], 50)

        avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0
        max_risk = max(risk_scores) if risk_scores else 0

        return {
            "connected_persons": connected_persons,
            "avg_risk_score": round(avg_risk, 1),
            "max_risk_score": max_risk,
            "sanctioned_count": sanctioned_count,
            "pep_count": pep_count,
            "shared_companies": sorted(shared_companies),
        }

    def get_stats(self) -> dict:
        """グラフの統計情報を返す。"""
        persons = [n for n, d in self.graph.nodes(data=True) if d.get("node_type") == "person"]
        companies = [n for n, d in self.graph.nodes(data=True) if d.get("node_type") == "company"]
        sanctioned = [n for n in persons if self.graph.nodes[n].get("sanctions_hit", False)]
        peps = [n for n in persons if self.graph.nodes[n].get("is_pep", False)]

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "persons": len(persons),
            "companies": len(companies),
            "sanctioned_persons": len(sanctioned),
            "pep_persons": len(peps),
            "connected_components": nx.number_weakly_connected_components(self.graph),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    # デモ: テストグラフ構築
    graph = PersonCompanyGraph()

    # 企業追加
    graph.add_company("Acme Corp", country="US", risk_score=20)
    graph.add_company("Shell Co Ltd", country="BVI", risk_score=60)

    # 個人追加
    graph.add_person("John Doe", nationality="US", is_pep=False, sanctions_hit=False)
    graph.add_person("Jane Smith", nationality="Russia", is_pep=True, sanctions_hit=False)
    graph.add_person("Ivan Petrov", nationality="Russia", is_pep=False, sanctions_hit=True)

    # 関係追加
    graph.add_edge("John Doe", "Acme Corp", RELATION_CONTROLS, ownership_pct=51.0)
    graph.add_edge("Jane Smith", "Acme Corp", RELATION_DIRECTOR_OF)
    graph.add_edge("Jane Smith", "Shell Co Ltd", RELATION_CONTROLS, ownership_pct=100.0)
    graph.add_edge("Ivan Petrov", "Shell Co Ltd", RELATION_ASSOCIATED_WITH)

    # リスク検出
    exposure = graph.get_risk_exposure("Acme Corp", max_hops=3)
    print(json.dumps(exposure, indent=2, ensure_ascii=False))
    print("\n--- Stats ---")
    print(json.dumps(graph.get_stats(), indent=2))
