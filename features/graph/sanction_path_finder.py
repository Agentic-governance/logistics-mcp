"""制裁パス検索エンジン（Sanction Path Finder）

BFS/PageRank ベースで制裁対象までのネットワーク距離を計算し、
サプライチェーン上のリスク伝播を検出する。

スコアリング:
  - 1ホップ = 100（直接取引/関係）
  - 2ホップ = 70（間接的関与）
  - 3ホップ = 40（遠隔リスク）
"""

import logging
from collections import deque
from typing import Optional

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx が必要です: pip install networkx")

from features.graph.unified_graph import (
    SCIGraph, NODE_PRODUCT, NODE_LOCATION, NODE_COMPANY, NODE_PERSON,
    EDGE_SUPPLIES, EDGE_CONTAINS, EDGE_ORIGINATES,
)

logger = logging.getLogger(__name__)

# ホップ距離に応じたエクスポージャスコア
_HOP_SCORES = {1: 100, 2: 70, 3: 40}

# 紛争地域の国コード一覧（DRC周辺 + 制裁頻出地域）
CONFLICT_REGIONS = {
    "CD",  # コンゴ民主共和国
    "CF",  # 中央アフリカ
    "SS",  # 南スーダン
    "SO",  # ソマリア
    "YE",  # イエメン
    "SY",  # シリア
    "AF",  # アフガニスタン
    "MM",  # ミャンマー
    "LY",  # リビア
    "RW",  # ルワンダ（紛争鉱物経由）
    "UG",  # ウガンダ（紛争鉱物経由）
}


class SanctionPathFinder:
    """3ホップ制裁検索エンジン

    SCIGraph 上で BFS を行い、指定エンティティから制裁対象ノードまでの
    最短経路と露出スコアを算出する。
    """

    def __init__(self, graph: Optional[SCIGraph] = None):
        self.graph = graph or SCIGraph()

    def find_sanction_exposure(self, entity_name: str, max_hops: int = 3) -> dict:
        """BFS探索で max_hops 以内の制裁対象を検索する。

        Args:
            entity_name: 起点エンティティ名
            max_hops: 探索最大ホップ数（デフォルト3）

        Returns:
            {
                "entity": str,
                "has_sanction_exposure": bool,
                "min_hops": int or None,
                "exposure_score": int,
                "paths": [{"target": str, "hops": int, "path": [...], "score": int}, ...],
                "sanctioned_nodes_found": int,
                "explored_nodes": int,
            }
        """
        G = self.graph.G
        if entity_name not in G:
            return {
                "entity": entity_name,
                "has_sanction_exposure": False,
                "min_hops": None,
                "exposure_score": 0,
                "paths": [],
                "sanctioned_nodes_found": 0,
                "explored_nodes": 0,
                "error": "ノードが見つかりません",
            }

        # BFS（無向化して双方向探索）
        undirected = G.to_undirected()
        try:
            reachable = nx.single_source_shortest_path_length(
                undirected, entity_name, cutoff=max_hops
            )
        except nx.NodeNotFound:
            return {
                "entity": entity_name,
                "has_sanction_exposure": False,
                "min_hops": None,
                "exposure_score": 0,
                "paths": [],
                "sanctioned_nodes_found": 0,
                "explored_nodes": 0,
            }

        # 制裁ノードを検出
        paths = []
        for nid, dist in reachable.items():
            if nid == entity_name or dist == 0:
                continue
            attrs = G.nodes.get(nid, {})
            if not (attrs.get("sanctioned", False) or attrs.get("sanctions_hit", False)):
                continue

            # 最短パスを取得
            try:
                path_nodes = nx.shortest_path(undirected, entity_name, nid)
            except nx.NetworkXNoPath:
                path_nodes = [entity_name, "...", nid]

            hop_score = _HOP_SCORES.get(dist, max(0, 100 - dist * 30))
            paths.append({
                "target": nid,
                "target_type": attrs.get("node_type", "unknown"),
                "hops": dist,
                "path": path_nodes,
                "score": hop_score,
                "target_country": attrs.get("country", attrs.get("nationality", "")),
            })

        # パスをスコア降順でソート
        paths.sort(key=lambda x: (-x["score"], x["hops"]))

        min_hops = min((p["hops"] for p in paths), default=None)
        exposure_score = max((p["score"] for p in paths), default=0)

        return {
            "entity": entity_name,
            "has_sanction_exposure": len(paths) > 0,
            "min_hops": min_hops,
            "exposure_score": exposure_score,
            "paths": paths,
            "sanctioned_nodes_found": len(paths),
            "explored_nodes": len(reachable),
        }

    def find_conflict_mineral_path(self, product_id: str) -> list:
        """BOM構成を遡り、紛争地域を経由するパスを検出する。

        製品ノードから CONTAINS エッジで子部品を辿り、
        さらに ORIGINATES / OPERATES_IN エッジで拠点に到達し、
        紛争地域かどうかを判定する。

        Args:
            product_id: 対象製品ノードID

        Returns:
            [{"path": [...], "conflict_region": str, "country_code": str}, ...]
        """
        G = self.graph.G
        if product_id not in G:
            return []

        conflict_paths = []
        visited = set()

        # DFS で BOM ツリーを探索
        stack = [(product_id, [product_id])]
        while stack:
            current, path = stack.pop()
            if current in visited:
                continue
            visited.add(current)

            attrs = G.nodes.get(current, {})
            node_type = attrs.get("node_type", "")

            # 拠点ノードに到達したら紛争地域チェック
            if node_type == NODE_LOCATION:
                cc = attrs.get("country_code", "").upper()
                if cc in CONFLICT_REGIONS:
                    conflict_paths.append({
                        "path": list(path),
                        "conflict_region": current,
                        "country_code": cc,
                    })
                continue

            # 順方向エッジを探索（current → neighbor）
            for _, neighbor, edge_attrs in G.edges(current, data=True):
                edge_type = edge_attrs.get("edge_type", "")
                if edge_type in (EDGE_CONTAINS, EDGE_ORIGINATES, EDGE_SUPPLIES, "OPERATES_IN"):
                    if neighbor not in visited:
                        stack.append((neighbor, path + [neighbor]))

            # 逆方向エッジも探索（predecessor → current）
            # PRODUCES: company→product なので、product から company を辿る
            # SUPPLIES: supplier→buyer なので、buyer から supplier を辿る
            for predecessor, _, edge_attrs in G.in_edges(current, data=True):
                edge_type = edge_attrs.get("edge_type", "")
                if edge_type in (EDGE_SUPPLIES, "PRODUCES"):
                    if predecessor not in visited:
                        stack.append((predecessor, path + [predecessor]))

        return conflict_paths

    def get_network_risk_score(self, entity_name: str, radius: int = 2) -> float:
        """PageRankベースのリスク伝播スコアを算出する。

        1. 制裁/高リスクノードに初期リスクを割り当て
        2. PersonalizedPageRank でリスクを伝播
        3. 対象エンティティの最終スコアを返す

        Args:
            entity_name: 対象エンティティ名
            radius: 探索半径（サブグラフ抽出用）

        Returns:
            0.0-100.0 のリスクスコア
        """
        G = self.graph.G
        if entity_name not in G or G.number_of_nodes() < 2:
            return 0.0

        # radius 以内のサブグラフを抽出
        undirected = G.to_undirected()
        try:
            reachable = nx.single_source_shortest_path_length(
                undirected, entity_name, cutoff=radius
            )
        except nx.NodeNotFound:
            return 0.0

        subgraph_nodes = set(reachable.keys())
        if len(subgraph_nodes) < 2:
            return 0.0

        subgraph = G.subgraph(subgraph_nodes).copy()

        # 制裁/高リスクノードに重みを設定（PersonalizedPageRank用）
        personalization = {}
        for nid in subgraph.nodes():
            attrs = subgraph.nodes[nid]
            score = 0.0
            if attrs.get("sanctioned", False) or attrs.get("sanctions_hit", False):
                score = 1.0
            elif attrs.get("is_pep", False):
                score = 0.3
            elif attrs.get("risk_score", 0) > 50:
                score = attrs.get("risk_score", 0) / 100.0
            else:
                score = 0.01  # ゼロを避ける
            personalization[nid] = score

        # PageRank 計算
        try:
            pr = nx.pagerank(subgraph, alpha=0.85, personalization=personalization)
        except (nx.PowerIterationFailedConvergence, ZeroDivisionError):
            return 0.0

        # 全体の最大値で正規化して 0-100 にスケーリング
        max_pr = max(pr.values()) if pr else 1.0
        if max_pr == 0:
            return 0.0

        entity_pr = pr.get(entity_name, 0.0)
        # 正規化: 自身が制裁対象なら100、そうでなければ相対スコア
        if G.nodes[entity_name].get("sanctioned", False):
            return 100.0

        normalized = (entity_pr / max_pr) * 100.0
        return round(min(100.0, normalized), 1)

    def get_full_exposure_report(self, entity_name: str, max_hops: int = 3) -> dict:
        """制裁エクスポージャ + ネットワークリスクの統合レポートを生成する。

        Args:
            entity_name: 対象エンティティ名
            max_hops: 制裁検索の最大ホップ数

        Returns:
            統合レポート辞書
        """
        sanction_exposure = self.find_sanction_exposure(entity_name, max_hops)
        network_risk = self.get_network_risk_score(entity_name, radius=max_hops)

        # 総合リスク判定
        exposure_score = sanction_exposure.get("exposure_score", 0)
        combined = max(exposure_score, network_risk)

        if combined >= 80:
            risk_level = "CRITICAL"
        elif combined >= 50:
            risk_level = "HIGH"
        elif combined >= 30:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return {
            "entity": entity_name,
            "risk_level": risk_level,
            "combined_score": round(combined, 1),
            "sanction_exposure": sanction_exposure,
            "network_risk_score": network_risk,
            "recommendation": _generate_recommendation(risk_level, sanction_exposure),
        }


def _generate_recommendation(risk_level: str, exposure: dict) -> str:
    """リスクレベルに応じた推奨アクションを生成する。"""
    if risk_level == "CRITICAL":
        return ("直接的な制裁エクスポージャが検出されました。"
                "即座に取引停止・法務部門への報告が必要です。")
    elif risk_level == "HIGH":
        hops = exposure.get("min_hops", "N/A")
        return (f"制裁対象が{hops}ホップ以内に存在します。"
                "強化デューデリジェンスと取引継続可否の検討が推奨されます。")
    elif risk_level == "MEDIUM":
        return ("間接的なリスク要因が存在します。"
                "定期的なモニタリングと追加調査を推奨します。")
    else:
        return "現時点で重大なリスクは検出されていません。定期モニタリングを継続してください。"


# ---------------------------------------------------------------------------
# CLI デモ
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    g = SCIGraph()
    g.add_company("Buyer Corp", country="JP")
    g.add_company("Tier1 Supplier", country="CN")
    g.add_company("Tier2 Supplier", country="RU", sanctioned=True)
    g.add_person("Oligarch X", nationality="RU", sanctioned=True)

    g.add_supply_relation("Tier1 Supplier", "Buyer Corp", confirmed=True)
    g.add_supply_relation("Tier2 Supplier", "Tier1 Supplier", probability=0.8)
    g.add_ownership("Oligarch X", "Tier2 Supplier", share_pct=80.0)

    finder = SanctionPathFinder(g)

    print("=== 制裁エクスポージャ ===")
    result = finder.find_sanction_exposure("Buyer Corp", max_hops=3)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    print("\n=== ネットワークリスクスコア ===")
    score = finder.get_network_risk_score("Buyer Corp", radius=3)
    print(f"Buyer Corp: {score}")

    print("\n=== 統合レポート ===")
    report = finder.get_full_exposure_report("Buyer Corp")
    print(json.dumps(report, indent=2, ensure_ascii=False))
