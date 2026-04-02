"""グラフ可視化データ生成（Graph Visualizer）

SCIGraph を D3.js force-directed graph 形式のJSONに変換する。
フロントエンドでの可視化やエクスポートに使用。
"""

import logging
from typing import Optional

from features.graph.unified_graph import (
    SCIGraph, NODE_COMPANY, NODE_PERSON, NODE_PRODUCT, NODE_LOCATION,
    EDGE_SUPPLIES, EDGE_OWNS, EDGE_DIRECTOR_OF, EDGE_EXECUTIVE_OF,
    EDGE_CONTROLS, EDGE_OPERATES_IN, EDGE_PRODUCES, EDGE_CONTAINS,
    EDGE_ORIGINATES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ノードタイプ → カラー / サイズ定義（D3.js用）
# ---------------------------------------------------------------------------
_NODE_STYLES = {
    NODE_COMPANY: {"color": "#4A90D9", "shape": "rect", "base_size": 20},
    NODE_PERSON: {"color": "#E67E22", "shape": "circle", "base_size": 15},
    NODE_PRODUCT: {"color": "#2ECC71", "shape": "diamond", "base_size": 12},
    NODE_LOCATION: {"color": "#9B59B6", "shape": "triangle", "base_size": 18},
}

_EDGE_STYLES = {
    EDGE_SUPPLIES: {"color": "#3498DB", "width": 2, "dash": ""},
    EDGE_OWNS: {"color": "#E74C3C", "width": 2.5, "dash": ""},
    EDGE_DIRECTOR_OF: {"color": "#F39C12", "width": 1.5, "dash": "5,5"},
    EDGE_EXECUTIVE_OF: {"color": "#F39C12", "width": 2, "dash": ""},
    EDGE_CONTROLS: {"color": "#E74C3C", "width": 3, "dash": ""},
    EDGE_OPERATES_IN: {"color": "#9B59B6", "width": 1, "dash": "3,3"},
    EDGE_PRODUCES: {"color": "#2ECC71", "width": 1.5, "dash": ""},
    EDGE_CONTAINS: {"color": "#1ABC9C", "width": 1, "dash": "2,2"},
    EDGE_ORIGINATES: {"color": "#8E44AD", "width": 1, "dash": "4,4"},
}


def to_d3_json(graph: SCIGraph, highlight_sanctioned: bool = True) -> dict:
    """SCIGraph を D3.js force-directed graph 形式のJSONに変換する。

    Args:
        graph: 変換対象の SCIGraph
        highlight_sanctioned: 制裁ノードを強調表示するか

    Returns:
        {
            "nodes": [{"id", "type", "label", "risk", "country", "color", "size", ...}],
            "links": [{"source", "target", "type", "confirmed", "color", "width", ...}],
            "metadata": {"node_count", "edge_count", "stats"},
        }
    """
    G = graph.G

    nodes = []
    for nid, attrs in G.nodes(data=True):
        node_type = attrs.get("node_type", "unknown")
        style = _NODE_STYLES.get(node_type, {"color": "#95A5A6", "shape": "circle", "base_size": 10})

        # リスクスコアに応じたサイズ調整
        risk_score = attrs.get("risk_score", 0)
        size = style["base_size"] + (risk_score / 10)

        # 制裁ノードは赤くハイライト
        color = style["color"]
        is_sanctioned = attrs.get("sanctioned", False) or attrs.get("sanctions_hit", False)
        if highlight_sanctioned and is_sanctioned:
            color = "#FF0000"
            size *= 1.5

        # ラベル生成
        label = nid
        if node_type == NODE_PRODUCT:
            label = attrs.get("name", nid)
        elif node_type == NODE_LOCATION:
            label = f"{nid} ({attrs.get('country_code', '')})"

        node_data = {
            "id": nid,
            "type": node_type,
            "label": label,
            "risk": risk_score,
            "country": attrs.get("country", attrs.get("country_code", attrs.get("nationality", ""))),
            "color": color,
            "size": round(size, 1),
            "shape": style["shape"],
            "sanctioned": is_sanctioned,
            "is_pep": attrs.get("is_pep", False),
        }

        # タイプ固有属性
        if node_type == NODE_PRODUCT:
            node_data["hs_code"] = attrs.get("hs_code", "")
        elif node_type == NODE_PERSON:
            node_data["nationality"] = attrs.get("nationality", "")
        elif node_type == NODE_COMPANY:
            node_data["industry"] = attrs.get("industry", "")

        nodes.append(node_data)

    links = []
    seen_links = set()  # MultiDiGraph の重複エッジを視覚的に区別
    for src, dst, key, attrs in G.edges(data=True, keys=True):
        edge_type = attrs.get("edge_type", "unknown")
        style = _EDGE_STYLES.get(edge_type, {"color": "#BDC3C7", "width": 1, "dash": ""})

        # 確定度に応じたスタイル
        confirmed = attrs.get("confirmed", False)
        probability = attrs.get("probability", 1.0)
        opacity = 1.0 if confirmed else max(0.3, probability)
        width = style["width"] if confirmed else style["width"] * 0.7

        link_key = f"{src}->{dst}:{edge_type}:{key}"
        if link_key in seen_links:
            continue
        seen_links.add(link_key)

        link_data = {
            "source": src,
            "target": dst,
            "type": edge_type,
            "confirmed": confirmed,
            "probability": probability,
            "color": style["color"],
            "width": round(width, 1),
            "dash": style["dash"],
            "opacity": round(opacity, 2),
        }

        # エッジ固有属性
        if edge_type == EDGE_OWNS:
            link_data["share_pct"] = attrs.get("share_pct", 0)
        elif edge_type in (EDGE_DIRECTOR_OF, EDGE_EXECUTIVE_OF):
            link_data["role"] = attrs.get("role", "")
        elif edge_type == EDGE_SUPPLIES:
            link_data["hs_code"] = attrs.get("hs_code", "")
            link_data["source_data"] = attrs.get("source", "")
        elif edge_type == EDGE_OPERATES_IN:
            link_data["facility_type"] = attrs.get("facility_type", "")

        links.append(link_data)

    return {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "node_count": len(nodes),
            "edge_count": len(links),
            "stats": graph.get_stats(),
        },
    }


def to_adjacency_matrix(graph: SCIGraph) -> dict:
    """隣接行列形式で出力する（小規模グラフ分析用）。

    Args:
        graph: 対象 SCIGraph

    Returns:
        {"labels": [...], "matrix": [[...]]}
    """
    G = graph.G
    node_list = sorted(G.nodes())
    idx = {n: i for i, n in enumerate(node_list)}
    n = len(node_list)
    matrix = [[0] * n for _ in range(n)]

    for src, dst in G.edges():
        i, j = idx.get(src), idx.get(dst)
        if i is not None and j is not None:
            matrix[i][j] += 1

    return {
        "labels": node_list,
        "matrix": matrix,
    }


def to_mermaid(graph: SCIGraph, max_nodes: int = 50) -> str:
    """Mermaid フローチャート形式のテキストを生成する。

    大規模グラフはテキストレポート向けに上位ノードに絞る。

    Args:
        graph: 対象 SCIGraph
        max_nodes: 出力上限ノード数

    Returns:
        Mermaid テキスト
    """
    G = graph.G
    lines = ["graph LR"]

    # ノード定義
    node_list = list(G.nodes(data=True))[:max_nodes]
    node_ids = set()
    for nid, attrs in node_list:
        node_type = attrs.get("node_type", "")
        safe_id = nid.replace(" ", "_").replace(":", "_").replace("(", "").replace(")", "")
        node_ids.add(nid)

        if attrs.get("sanctioned", False):
            lines.append(f'    {safe_id}["{nid} ⚠"]:::sanctioned')
        elif node_type == NODE_COMPANY:
            lines.append(f'    {safe_id}["{nid}"]:::company')
        elif node_type == NODE_PERSON:
            lines.append(f'    {safe_id}("{nid}"):::person')
        elif node_type == NODE_PRODUCT:
            lines.append(f'    {safe_id}{{"{nid}"}}:::product')
        elif node_type == NODE_LOCATION:
            lines.append(f'    {safe_id}>"{nid}"]:::location')
        else:
            lines.append(f'    {safe_id}["{nid}"]')

    # エッジ定義
    for src, dst, attrs in G.edges(data=True):
        if src not in node_ids or dst not in node_ids:
            continue
        safe_src = src.replace(" ", "_").replace(":", "_").replace("(", "").replace(")", "")
        safe_dst = dst.replace(" ", "_").replace(":", "_").replace("(", "").replace(")", "")
        edge_type = attrs.get("edge_type", "")
        label = edge_type.replace("_", " ")
        lines.append(f'    {safe_src} -->|{label}| {safe_dst}')

    # スタイル
    lines.append("")
    lines.append("    classDef company fill:#4A90D9,color:#fff")
    lines.append("    classDef person fill:#E67E22,color:#fff")
    lines.append("    classDef product fill:#2ECC71,color:#fff")
    lines.append("    classDef location fill:#9B59B6,color:#fff")
    lines.append("    classDef sanctioned fill:#FF0000,color:#fff,stroke:#000,stroke-width:3px")

    return "\n".join(lines)


def generate_risk_highlights(graph: SCIGraph) -> list:
    """グラフ内のリスクハイライト情報を生成する（UI向け）。

    制裁ノード、高リスクノード、未確認取引等をリストアップ。

    Returns:
        [{"type": "warning"|"danger"|"info", "message": str, "node_id": str}, ...]
    """
    highlights = []

    # 制裁ノード
    for node_info in graph.get_sanctioned_nodes():
        highlights.append({
            "type": "danger",
            "message": f"制裁対象: {node_info['id']} ({node_info.get('node_type', '')})",
            "node_id": node_info["id"],
        })

    # 高リスクノード（制裁以外でスコア50超）
    for nid, attrs in graph.G.nodes(data=True):
        risk = attrs.get("risk_score", 0)
        if risk >= 50 and not attrs.get("sanctioned", False):
            highlights.append({
                "type": "warning",
                "message": f"高リスク: {nid} (スコア={risk})",
                "node_id": nid,
            })

    # PEP
    for nid, attrs in graph.G.nodes(data=True):
        if attrs.get("is_pep", False):
            highlights.append({
                "type": "warning",
                "message": f"PEP（政治的要人）: {nid}",
                "node_id": nid,
            })

    # 未確認取引
    unconfirmed = 0
    for src, dst, attrs in graph.G.edges(data=True):
        if attrs.get("edge_type") == "SUPPLIES" and not attrs.get("confirmed", False):
            prob = attrs.get("probability", 0)
            if prob < 0.5:
                unconfirmed += 1
    if unconfirmed > 0:
        highlights.append({
            "type": "info",
            "message": f"未確認の推定取引関係: {unconfirmed}件（確度<50%）",
            "node_id": "",
        })

    return highlights


# ---------------------------------------------------------------------------
# CLI デモ
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    g = SCIGraph()
    g.add_company("Toyota Motor", country="JP", risk_score=10)
    g.add_company("Denso", country="JP", risk_score=15)
    g.add_company("Shell Co", country="VG", risk_score=70, sanctioned=True)
    g.add_person("John Doe", nationality="US")
    g.add_person("Oligarch X", nationality="RU", sanctioned=True)
    g.add_product("Battery", hs_code="8507")
    g.add_location("Nagoya", country_code="JP")

    g.add_supply_relation("Denso", "Toyota Motor", confirmed=True)
    g.add_ownership("Oligarch X", "Shell Co", share_pct=100)
    g.add_directorship("John Doe", "Toyota Motor", role="CFO")
    g.add_operates_in("Toyota Motor", "Nagoya", facility_type="factory")
    g.add_product_relation("Denso", "Battery")

    d3 = to_d3_json(g)
    print("=== D3 JSON ===")
    print(json.dumps(d3, indent=2, ensure_ascii=False))

    print("\n=== Mermaid ===")
    print(to_mermaid(g))

    print("\n=== リスクハイライト ===")
    for h in generate_risk_highlights(g):
        print(f"  [{h['type']}] {h['message']}")
