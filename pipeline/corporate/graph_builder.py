"""
Tier-N企業グラフ構築（NetworkX）
概念: 直接取引先(Tier-1)の株主・関連企業をグラフ化してTier-2/3リスクを推定。
データソース: OpenCorporates, 有価証券報告書（EDINETから取得可）
"""
import networkx as nx
import requests
import json
from typing import Optional


OPENCORPORATES_API = "https://api.opencorporates.com/v0.4"


def build_supply_chain_graph(
    company_name: str,
    country_code: str = "jp",
    depth: int = 2,
) -> nx.DiGraph:
    """
    企業の関連会社グラフを構築。
    depth=2でTier-2まで、depth=3でTier-3まで辿る。
    """
    G = nx.DiGraph()
    G.add_node(company_name, tier=0, type="target")

    _expand_node(G, company_name, country_code, current_depth=0, max_depth=depth)

    return G


def _expand_node(G: nx.DiGraph, company_name: str, country_code: str, current_depth: int, max_depth: int):
    if current_depth >= max_depth:
        return

    # OpenCorporatesで関連企業検索
    officers = _get_officers(company_name, country_code)

    for officer in officers[:10]:  # 上位10社に絞る
        related_name = officer.get("company_name")
        if not related_name or related_name == company_name:
            continue

        tier = current_depth + 1
        G.add_node(related_name, tier=tier, type="supplier")
        G.add_edge(company_name, related_name, relationship=officer.get("role", "related"))

        if current_depth + 1 < max_depth:
            _expand_node(G, related_name, country_code, current_depth + 1, max_depth)


def _get_officers(company_name: str, country_code: str) -> list[dict]:
    """OpenCorporatesから役員・関連会社情報取得"""
    try:
        resp = requests.get(
            f"{OPENCORPORATES_API}/companies/search",
            params={"q": company_name, "jurisdiction_code": country_code, "per_page": 1},
            timeout=10
        )
        data = resp.json()
        companies = data.get("results", {}).get("companies", [])
        if not companies:
            return []

        company_number = companies[0]["company"]["company_number"]
        jurisdiction = companies[0]["company"]["jurisdiction_code"]

        # 役員情報取得
        officers_resp = requests.get(
            f"{OPENCORPORATES_API}/companies/{jurisdiction}/{company_number}/officers",
            timeout=10
        )
        officers_data = officers_resp.json()
        return officers_data.get("results", {}).get("officers", [])
    except Exception:
        return []


def graph_to_visualization_data(G: nx.DiGraph) -> dict:
    """フロントエンド可視化用JSONに変換"""
    nodes = []
    for node, attrs in G.nodes(data=True):
        nodes.append({
            "id": node,
            "label": node,
            "tier": attrs.get("tier", 0),
            "type": attrs.get("type", "unknown"),
        })

    edges = []
    for src, dst, attrs in G.edges(data=True):
        edges.append({
            "source": src,
            "target": dst,
            "relationship": attrs.get("relationship", "related"),
        })

    return {"nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges)}
