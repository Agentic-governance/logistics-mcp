"""統合知識グラフ（Supply Chain Intelligence Graph）

物流・企業・人物・製品・拠点を統合した MultiDiGraph。
サプライチェーン全体のリスク分析・制裁検索・可視化の基盤データ構造。
"""

import logging
from typing import Optional

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx が必要です: pip install networkx")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ノードタイプ定数
# ---------------------------------------------------------------------------
NODE_COMPANY = "company"
NODE_PERSON = "person"
NODE_PRODUCT = "product"
NODE_LOCATION = "location"

# ---------------------------------------------------------------------------
# エッジタイプ定数
# ---------------------------------------------------------------------------
EDGE_SUPPLIES = "SUPPLIES"           # サプライヤー → バイヤー
EDGE_OWNS = "OWNS"                   # 所有者 → 被所有者
EDGE_DIRECTOR_OF = "DIRECTOR_OF"     # 人物 → 企業（取締役）
EDGE_EXECUTIVE_OF = "EXECUTIVE_OF"   # 人物 → 企業（経営幹部）
EDGE_CONTROLS = "CONTROLS"           # UBO支配関係
EDGE_OPERATES_IN = "OPERATES_IN"     # 企業 → 拠点
EDGE_PRODUCES = "PRODUCES"           # 企業 → 製品
EDGE_CONTAINS = "CONTAINS"           # 製品 → 製品（BOM構成）
EDGE_ORIGINATES = "ORIGINATES"       # 製品 → 拠点（原産地）
EDGE_ASSOCIATED = "ASSOCIATED_WITH"  # 汎用関連


class SCIGraph:
    """Supply Chain Intelligence Graph — 統合知識グラフ

    NetworkX MultiDiGraph ベースで、企業・人物・製品・拠点の
    4種のノードと多様なリレーションを統一管理する。
    """

    def __init__(self):
        self.G = nx.MultiDiGraph()

    # =====================================================================
    # ノード追加
    # =====================================================================

    def add_company(self, company_id: str, **attrs) -> None:
        """企業ノードを追加する。

        Args:
            company_id: 企業識別子（名称 or ID）
            **attrs: country, risk_score, sanctioned, industry 等
        """
        self.G.add_node(
            company_id,
            node_type=NODE_COMPANY,
            country=attrs.pop("country", ""),
            risk_score=attrs.pop("risk_score", 0),
            sanctioned=attrs.pop("sanctioned", False),
            **attrs,
        )
        logger.debug("企業ノード追加: %s", company_id)

    def add_person(self, person_id: str, **attrs) -> None:
        """人物ノードを追加する。

        Args:
            person_id: 人物識別子
            **attrs: nationality, is_pep, sanctioned 等
        """
        self.G.add_node(
            person_id,
            node_type=NODE_PERSON,
            nationality=attrs.pop("nationality", ""),
            is_pep=attrs.pop("is_pep", False),
            sanctioned=attrs.pop("sanctioned", False),
            **attrs,
        )
        logger.debug("人物ノード追加: %s", person_id)

    def add_product(self, product_id: str, **attrs) -> None:
        """製品ノードを追加する。

        Args:
            product_id: 製品識別子
            **attrs: hs_code, name, material 等
        """
        self.G.add_node(
            product_id,
            node_type=NODE_PRODUCT,
            hs_code=attrs.pop("hs_code", ""),
            name=attrs.pop("name", product_id),
            **attrs,
        )
        logger.debug("製品ノード追加: %s", product_id)

    def add_location(self, location_id: str, **attrs) -> None:
        """拠点ノードを追加する。

        Args:
            location_id: 拠点識別子
            **attrs: country_code, risk_score, lat, lon 等
        """
        self.G.add_node(
            location_id,
            node_type=NODE_LOCATION,
            country_code=attrs.pop("country_code", ""),
            risk_score=attrs.pop("risk_score", 0),
            **attrs,
        )
        logger.debug("拠点ノード追加: %s", location_id)

    # =====================================================================
    # エッジ追加
    # =====================================================================

    def add_supply_relation(
        self,
        supplier_id: str,
        buyer_id: str,
        probability: float = 1.0,
        confirmed: bool = False,
        hs_code: str = "",
        source: str = "",
    ) -> None:
        """サプライ関係エッジを追加する。

        Args:
            supplier_id: サプライヤーノードID
            buyer_id: バイヤーノードID
            probability: 取引確度（0.0-1.0）
            confirmed: 通関データ等で確認済みか
            hs_code: 取引品目HSコード
            source: データソース名
        """
        # ノード未登録なら企業として自動追加
        if supplier_id not in self.G:
            self.add_company(supplier_id)
        if buyer_id not in self.G:
            self.add_company(buyer_id)

        self.G.add_edge(
            supplier_id, buyer_id,
            edge_type=EDGE_SUPPLIES,
            probability=probability,
            confirmed=confirmed,
            hs_code=hs_code,
            source=source,
        )
        logger.debug("サプライ関係追加: %s -> %s (確度=%.2f)", supplier_id, buyer_id, probability)

    def add_ownership(self, owner_id: str, owned_id: str, share_pct: float = 0.0) -> None:
        """所有関係エッジを追加する。

        Args:
            owner_id: 所有者ノードID（企業 or 人物）
            owned_id: 被所有者ノードID
            share_pct: 持株比率 (0-100)
        """
        if owner_id not in self.G:
            self.add_company(owner_id)
        if owned_id not in self.G:
            self.add_company(owned_id)

        self.G.add_edge(
            owner_id, owned_id,
            edge_type=EDGE_OWNS,
            share_pct=share_pct,
        )
        logger.debug("所有関係追加: %s -> %s (%.1f%%)", owner_id, owned_id, share_pct)

    def add_directorship(
        self,
        person_id: str,
        company_id: str,
        role: str = "Director",
        is_current: bool = True,
    ) -> None:
        """取締役/役員関係エッジを追加する。

        Args:
            person_id: 人物ノードID
            company_id: 企業ノードID
            role: 役職名
            is_current: 現職かどうか
        """
        if person_id not in self.G:
            self.add_person(person_id)
        if company_id not in self.G:
            self.add_company(company_id)

        edge_type = EDGE_EXECUTIVE_OF if "CEO" in role.upper() or "CTO" in role.upper() or "CFO" in role.upper() else EDGE_DIRECTOR_OF
        self.G.add_edge(
            person_id, company_id,
            edge_type=edge_type,
            role=role,
            is_current=is_current,
        )
        logger.debug("役員関係追加: %s -[%s]-> %s", person_id, role, company_id)

    def add_operates_in(
        self,
        company_id: str,
        location_id: str,
        facility_type: str = "office",
    ) -> None:
        """拠点関係エッジを追加する。

        Args:
            company_id: 企業ノードID
            location_id: 拠点ノードID
            facility_type: 施設種別 (office, factory, warehouse, port 等)
        """
        if company_id not in self.G:
            self.add_company(company_id)
        if location_id not in self.G:
            self.add_location(location_id)

        self.G.add_edge(
            company_id, location_id,
            edge_type=EDGE_OPERATES_IN,
            facility_type=facility_type,
        )
        logger.debug("拠点関係追加: %s -> %s (%s)", company_id, location_id, facility_type)

    def add_product_relation(
        self,
        company_id: str,
        product_id: str,
    ) -> None:
        """企業→製品の生産関係を追加する。"""
        if company_id not in self.G:
            self.add_company(company_id)
        if product_id not in self.G:
            self.add_product(product_id)

        self.G.add_edge(
            company_id, product_id,
            edge_type=EDGE_PRODUCES,
        )

    def add_bom_relation(
        self,
        parent_product_id: str,
        child_product_id: str,
        quantity: float = 1.0,
    ) -> None:
        """BOM構成関係（親製品 → 子部品）を追加する。"""
        if parent_product_id not in self.G:
            self.add_product(parent_product_id)
        if child_product_id not in self.G:
            self.add_product(child_product_id)

        self.G.add_edge(
            parent_product_id, child_product_id,
            edge_type=EDGE_CONTAINS,
            quantity=quantity,
        )

    def add_origin(self, product_id: str, location_id: str) -> None:
        """製品→原産地の関係を追加する。"""
        if product_id not in self.G:
            self.add_product(product_id)
        if location_id not in self.G:
            self.add_location(location_id)

        self.G.add_edge(
            product_id, location_id,
            edge_type=EDGE_ORIGINATES,
        )

    # =====================================================================
    # クエリ
    # =====================================================================

    def get_neighbors(self, node_id: str, max_hops: int = 1) -> list:
        """指定ノードから max_hops 以内の全隣接ノードを取得する。

        Args:
            node_id: 起点ノードID
            max_hops: 最大ホップ数

        Returns:
            [{"id": str, "node_type": str, "distance": int, ...}, ...]
        """
        if node_id not in self.G:
            return []

        undirected = self.G.to_undirected()
        try:
            reachable = nx.single_source_shortest_path_length(
                undirected, node_id, cutoff=max_hops
            )
        except nx.NodeNotFound:
            return []

        result = []
        for nid, dist in reachable.items():
            if nid == node_id:
                continue
            attrs = dict(self.G.nodes.get(nid, {}))
            attrs["id"] = nid
            attrs["distance"] = dist
            result.append(attrs)

        return sorted(result, key=lambda x: x["distance"])

    def get_sanctioned_nodes(self) -> list:
        """制裁フラグが立っているノードを全取得する。

        Returns:
            [{"id": str, "node_type": str, ...}, ...]
        """
        result = []
        for nid, attrs in self.G.nodes(data=True):
            if attrs.get("sanctioned", False) or attrs.get("sanctions_hit", False):
                info = dict(attrs)
                info["id"] = nid
                result.append(info)
        return result

    def get_nodes_by_type(self, node_type: str) -> list:
        """指定タイプのノードを全取得する。"""
        return [
            {"id": nid, **attrs}
            for nid, attrs in self.G.nodes(data=True)
            if attrs.get("node_type") == node_type
        ]

    def get_edges_by_type(self, edge_type: str) -> list:
        """指定タイプのエッジを全取得する。"""
        result = []
        for src, dst, key, attrs in self.G.edges(data=True, keys=True):
            if attrs.get("edge_type") == edge_type:
                result.append({"source": src, "target": dst, "key": key, **attrs})
        return result

    # =====================================================================
    # シリアライズ / 統計
    # =====================================================================

    def to_dict(self) -> dict:
        """グラフをJSON化可能な辞書に変換する。"""
        nodes = []
        for nid, attrs in self.G.nodes(data=True):
            node_data = {"id": nid}
            node_data.update(attrs)
            nodes.append(node_data)

        edges = []
        for src, dst, key, attrs in self.G.edges(data=True, keys=True):
            edge_data = {"source": src, "target": dst, "key": key}
            edge_data.update(attrs)
            edges.append(edge_data)

        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "stats": self.get_stats(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SCIGraph":
        """辞書からグラフを復元する。"""
        graph = cls()
        for node in data.get("nodes", []):
            node = dict(node)  # 元データを壊さない
            nid = node.pop("id")
            node_type = node.pop("node_type", NODE_COMPANY)
            if node_type == NODE_COMPANY:
                graph.add_company(nid, **node)
            elif node_type == NODE_PERSON:
                graph.add_person(nid, **node)
            elif node_type == NODE_PRODUCT:
                graph.add_product(nid, **node)
            elif node_type == NODE_LOCATION:
                graph.add_location(nid, **node)
            else:
                graph.G.add_node(nid, node_type=node_type, **node)

        for edge in data.get("edges", []):
            src = edge.pop("source")
            dst = edge.pop("target")
            edge.pop("key", None)
            graph.G.add_edge(src, dst, **edge)

        return graph

    def node_count(self) -> int:
        """総ノード数を返す。"""
        return self.G.number_of_nodes()

    def edge_count(self) -> int:
        """総エッジ数を返す。"""
        return self.G.number_of_edges()

    def get_stats(self) -> dict:
        """グラフの統計情報を返す。"""
        type_counts = {}
        for _, attrs in self.G.nodes(data=True):
            nt = attrs.get("node_type", "unknown")
            type_counts[nt] = type_counts.get(nt, 0) + 1

        edge_type_counts = {}
        for _, _, attrs in self.G.edges(data=True):
            et = attrs.get("edge_type", "unknown")
            edge_type_counts[et] = edge_type_counts.get(et, 0) + 1

        sanctioned = len(self.get_sanctioned_nodes())
        weakly = nx.number_weakly_connected_components(self.G) if self.G.number_of_nodes() > 0 else 0

        return {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "node_types": type_counts,
            "edge_types": edge_type_counts,
            "sanctioned_count": sanctioned,
            "weakly_connected_components": weakly,
        }

    def merge(self, other: "SCIGraph") -> None:
        """他のSCIGraphを統合する（ノード・エッジをマージ）。"""
        for nid, attrs in other.G.nodes(data=True):
            if nid in self.G:
                # 既存ノードは属性をマージ（新しい値で上書き）
                existing = dict(self.G.nodes[nid])
                existing.update({k: v for k, v in attrs.items() if v})
                self.G.nodes[nid].update(existing)
            else:
                self.G.add_node(nid, **attrs)

        for src, dst, key, attrs in other.G.edges(data=True, keys=True):
            self.G.add_edge(src, dst, **attrs)

        logger.info("グラフマージ完了: 現在ノード=%d, エッジ=%d",
                     self.G.number_of_nodes(), self.G.number_of_edges())

    def __repr__(self) -> str:
        return f"SCIGraph(nodes={self.node_count()}, edges={self.edge_count()})"


# ---------------------------------------------------------------------------
# CLI デモ
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    g = SCIGraph()

    # 企業
    g.add_company("Toyota Motor", country="JP", risk_score=10)
    g.add_company("Denso", country="JP", risk_score=15)
    g.add_company("Shell Co BVI", country="VG", risk_score=70, sanctioned=True)

    # 人物
    g.add_person("Akio Toyoda", nationality="JP")
    g.add_person("Ivan Petrov", nationality="RU", sanctioned=True)

    # 製品
    g.add_product("EV Battery Pack", hs_code="8507", name="EVバッテリーパック")

    # 拠点
    g.add_location("Toyota City", country_code="JP")

    # 関係
    g.add_supply_relation("Denso", "Toyota Motor", probability=0.95, confirmed=True)
    g.add_ownership("Ivan Petrov", "Shell Co BVI", share_pct=100.0)
    g.add_directorship("Akio Toyoda", "Toyota Motor", role="Chairman")
    g.add_operates_in("Toyota Motor", "Toyota City", facility_type="factory")
    g.add_product_relation("Denso", "EV Battery Pack")

    print(json.dumps(g.to_dict(), indent=2, ensure_ascii=False, default=str))
    print(f"\n制裁ノード: {g.get_sanctioned_nodes()}")
    print(f"隣接(Toyota Motor, 2hop): {g.get_neighbors('Toyota Motor', max_hops=2)}")
