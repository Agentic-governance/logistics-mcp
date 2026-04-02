"""グラフ自動構築パイプライン v2（SCIGraphBuilder）

BOM分析結果 → Tier推定 → 所有構造 → 役員 → 通関確定 の
ワンコールパイプラインで統合知識グラフを構築する。

既存の graph_builder.py / person_company_graph.py のパターンを踏襲しつつ、
SCIGraph（MultiDiGraph）に統合する。
"""

import logging
import asyncio
from typing import Optional

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx が必要です: pip install networkx")

from features.graph.unified_graph import SCIGraph, NODE_COMPANY, NODE_LOCATION

logger = logging.getLogger(__name__)


class SCIGraphBuilder:
    """統合知識グラフの自動構築パイプライン

    以下の手順でグラフを段階的に構築する:
    1. BOM分析結果からサプライヤー・製品ノードを構築
    2. 所有構造（UBO/OpenOwnership）で企業間関係を追加
    3. 役員情報（Wikidata/OpenCorporates）で人物ノードを追加
    4. 通関データ（ImportYeti）で取引を確定
    """

    def __init__(self):
        pass

    async def build_from_bom(self, bom_result: dict) -> SCIGraph:
        """BOM分析結果から初期グラフを構築する。

        Args:
            bom_result: BOMAnalyzer.analyze_bom().to_dict() の結果

        Returns:
            サプライヤー・製品・拠点を含む SCIGraph
        """
        graph = SCIGraph()

        product_name = bom_result.get("product_name", "Unknown Product")
        graph.add_product(f"product:{product_name}", name=product_name)

        part_risks = bom_result.get("part_risks", [])
        for part in part_risks:
            part_id = part.get("part_id", "")
            part_name = part.get("part_name", part_id)
            supplier_name = part.get("supplier_name", "")
            supplier_country = part.get("supplier_country", "")
            hs_code = part.get("hs_code", "")
            tier = part.get("tier", 1)
            risk_score = part.get("risk_score", 0)

            # 部品ノード
            part_node_id = f"part:{part_id}" if part_id else f"part:{part_name}"
            graph.add_product(part_node_id, name=part_name, hs_code=hs_code, tier=tier)
            graph.add_bom_relation(f"product:{product_name}", part_node_id)

            # サプライヤーノード
            if supplier_name:
                graph.add_company(
                    supplier_name,
                    country=supplier_country,
                    risk_score=risk_score,
                )
                graph.add_product_relation(supplier_name, part_node_id)

                # 拠点ノード（サプライヤー国）
                if supplier_country:
                    loc_id = f"loc:{supplier_country}"
                    graph.add_location(loc_id, country_code=supplier_country)
                    graph.add_operates_in(supplier_name, loc_id, facility_type="production")

        # 集中度リスク情報
        concentrations = bom_result.get("concentration_risks", bom_result.get("concentrations", []))
        for conc in concentrations:
            if isinstance(conc, dict):
                country = conc.get("country", "")
                if country:
                    loc_id = f"loc:{country}"
                    if loc_id not in graph.G:
                        graph.add_location(loc_id, country_code=country)

        # Tier-2 推定
        tier2_risks = bom_result.get("tier2_risks", bom_result.get("hidden_risks", []))
        for t2 in tier2_risks:
            if isinstance(t2, dict):
                t2_country = t2.get("likely_origin_country", t2.get("country", ""))
                t2_name = t2.get("supplier_name", t2.get("origin", ""))
                if t2_name:
                    graph.add_company(t2_name, country=t2_country)
                    # Tier-2はサプライ関係を推定（confirmed=False）
                    parent = t2.get("parent_supplier", "")
                    if parent and parent in graph.G:
                        graph.add_supply_relation(
                            t2_name, parent,
                            probability=t2.get("probability", 0.5),
                            confirmed=False,
                            source="tier2_inference",
                        )

        logger.info("BOMグラフ構築完了: ノード=%d, エッジ=%d", graph.node_count(), graph.edge_count())
        return graph

    async def enrich_with_ownership(self, graph: SCIGraph) -> SCIGraph:
        """所有構造（UBO）情報でグラフを拡充する。

        OpenOwnership / ICIJ データを使って企業の実質的支配者を追加。

        Args:
            graph: 拡充対象の SCIGraph

        Returns:
            UBO関係が追加された SCIGraph
        """
        try:
            from pipeline.corporate.openownership_client import OpenOwnershipClient
        except ImportError:
            logger.warning("OpenOwnershipClient が利用不可。所有構造スキップ。")
            return graph

        oo_client = OpenOwnershipClient()

        # 企業ノードについてUBO検索
        companies = graph.get_nodes_by_type(NODE_COMPANY)
        for company_info in companies:
            company_name = company_info.get("id", "")
            if not company_name:
                continue

            try:
                ubo_records = oo_client.search_ubo(company_name)
                if not ubo_records:
                    continue

                for ubo in ubo_records:
                    if hasattr(ubo, "person_name"):
                        person_name = ubo.person_name
                        nationality = ubo.nationality
                        ownership_pct = ubo.ownership_pct
                        is_pep = ubo.is_pep
                        sanctions_hit = ubo.sanctions_hit
                    elif isinstance(ubo, dict):
                        person_name = ubo.get("person_name", ubo.get("name", ""))
                        nationality = ubo.get("nationality", "")
                        ownership_pct = ubo.get("ownership_pct", 0.0)
                        is_pep = ubo.get("is_pep", False)
                        sanctions_hit = ubo.get("sanctions_hit", False)
                    else:
                        continue

                    if not person_name:
                        continue

                    graph.add_person(
                        person_name,
                        nationality=nationality,
                        is_pep=is_pep,
                        sanctioned=sanctions_hit,
                    )
                    graph.add_ownership(person_name, company_name, share_pct=ownership_pct)

                logger.debug("UBO追加: %s → %d件", company_name, len(ubo_records))
            except Exception as e:
                logger.warning("UBO検索失敗 (%s): %s", company_name, e)

        logger.info("所有構造エンリッチ完了: ノード=%d, エッジ=%d", graph.node_count(), graph.edge_count())
        return graph

    async def enrich_with_directors(self, graph: SCIGraph) -> SCIGraph:
        """役員情報でグラフを拡充する。

        Wikidata から経営幹部・取締役情報を取得し、人物ノードと
        取締役関係エッジを追加する。

        Args:
            graph: 拡充対象の SCIGraph

        Returns:
            役員関係が追加された SCIGraph
        """
        try:
            from pipeline.corporate.wikidata_client import WikidataClient
        except ImportError:
            logger.warning("WikidataClient が利用不可。役員情報スキップ。")
            return graph

        wd_client = WikidataClient()

        companies = graph.get_nodes_by_type(NODE_COMPANY)
        for company_info in companies:
            company_name = company_info.get("id", "")
            if not company_name or company_name.startswith("loc:"):
                continue

            try:
                result = wd_client.get_company_people(company_name)
                if not result:
                    continue

                executives = result.get("executives", []) if isinstance(result, dict) else []
                board_members = result.get("board_members", []) if isinstance(result, dict) else []

                for exec_data in executives:
                    name = exec_data.get("name", "") if isinstance(exec_data, dict) else getattr(exec_data, "name", "")
                    if not name:
                        continue
                    nationality = exec_data.get("nationality", "") if isinstance(exec_data, dict) else getattr(exec_data, "nationality", "")
                    position = exec_data.get("position", "Executive") if isinstance(exec_data, dict) else getattr(exec_data, "position", "Executive")

                    graph.add_person(name, nationality=nationality)
                    graph.add_directorship(name, company_name, role=position)

                for member in board_members:
                    name = member.get("name", "") if isinstance(member, dict) else getattr(member, "name", "")
                    if not name:
                        continue
                    role = member.get("board_role", "Director") if isinstance(member, dict) else getattr(member, "board_role", "Director")

                    graph.add_person(name)
                    graph.add_directorship(name, company_name, role=role)

                    # 兼任先企業
                    other_boards = member.get("other_boards", []) if isinstance(member, dict) else getattr(member, "other_boards", [])
                    for other_co in (other_boards or []):
                        if other_co and other_co != company_name:
                            graph.add_company(other_co)
                            graph.add_directorship(name, other_co, role="Board Member (兼任)")

                logger.debug("役員追加: %s → 幹部%d名, 取締役%d名",
                             company_name, len(executives), len(board_members))
            except Exception as e:
                logger.warning("役員検索失敗 (%s): %s", company_name, e)

        logger.info("役員エンリッチ完了: ノード=%d, エッジ=%d", graph.node_count(), graph.edge_count())
        return graph

    async def enrich_with_customs(self, graph: SCIGraph, buyer_company: str = "") -> SCIGraph:
        """通関データ（ImportYeti）で取引関係を確定する。

        既存のサプライ関係に対して通関データで裏付けを取り、
        confirmed=True に更新する。新たなサプライヤーも追加。

        Args:
            graph: 拡充対象の SCIGraph
            buyer_company: バイヤー企業名（空の場合は全企業ノードを探索）

        Returns:
            通関確定済みの SCIGraph
        """
        try:
            from pipeline.trade.importyeti_client import get_customs_supplier_evidence
        except ImportError:
            logger.warning("ImportYetiClient が利用不可。通関確定スキップ。")
            return graph

        # バイヤー企業リスト
        if buyer_company:
            target_companies = [buyer_company]
        else:
            target_companies = [
                n["id"] for n in graph.get_nodes_by_type(NODE_COMPANY)
                if not n["id"].startswith("loc:")
            ][:10]  # 上限10社

        for company_name in target_companies:
            try:
                evidence = get_customs_supplier_evidence(company_name)
                if not evidence or not isinstance(evidence, dict):
                    continue

                suppliers = evidence.get("suppliers", evidence.get("results", []))
                for supplier in suppliers:
                    if isinstance(supplier, dict):
                        s_name = supplier.get("supplier_name", supplier.get("name", ""))
                        s_country = supplier.get("country", "")
                        hs_code = supplier.get("hs_code", "")
                        shipments = supplier.get("shipment_count", 0)
                    else:
                        continue

                    if not s_name:
                        continue

                    # サプライヤーノードを追加/更新
                    graph.add_company(s_name, country=s_country)

                    # 確定済みサプライ関係を追加
                    graph.add_supply_relation(
                        s_name, company_name,
                        probability=1.0,
                        confirmed=True,
                        hs_code=hs_code,
                        source="importyeti",
                    )

                    # 拠点
                    if s_country:
                        loc_id = f"loc:{s_country}"
                        if loc_id not in graph.G:
                            graph.add_location(loc_id, country_code=s_country)
                        graph.add_operates_in(s_name, loc_id)

                logger.debug("通関確定: %s → %d件のサプライヤー", company_name, len(suppliers))
            except Exception as e:
                logger.warning("通関データ取得失敗 (%s): %s", company_name, e)

        logger.info("通関エンリッチ完了: ノード=%d, エッジ=%d", graph.node_count(), graph.edge_count())
        return graph

    async def enrich_with_sanctions(self, graph: SCIGraph) -> SCIGraph:
        """制裁リストでノードの制裁フラグを更新する。

        全企業・人物ノードについて制裁スクリーニングを実行し、
        マッチした場合は sanctioned=True を設定する。

        Args:
            graph: 拡充対象の SCIGraph

        Returns:
            制裁フラグ更新済みの SCIGraph
        """
        try:
            from pipeline.sanctions.screener import screen_entity
        except ImportError:
            logger.warning("制裁スクリーナーが利用不可。制裁チェックスキップ。")
            return graph

        # 企業 + 人物ノードをスクリーニング
        targets = graph.get_nodes_by_type(NODE_COMPANY) + graph.get_nodes_by_type("person")
        screened = 0
        matched = 0

        for node_info in targets:
            nid = node_info.get("id", "")
            if not nid or nid.startswith("loc:") or nid.startswith("part:") or nid.startswith("product:"):
                continue

            try:
                country = node_info.get("country", node_info.get("nationality", ""))
                result = screen_entity(nid, country or None)
                screened += 1

                if result.matched:
                    graph.G.nodes[nid]["sanctioned"] = True
                    graph.G.nodes[nid]["sanction_source"] = result.source
                    graph.G.nodes[nid]["sanction_score"] = result.match_score
                    matched += 1
                    logger.info("制裁マッチ: %s (source=%s, score=%s)", nid, result.source, result.match_score)
            except Exception as e:
                logger.warning("制裁スクリーニング失敗 (%s): %s", nid, e)

        logger.info("制裁スクリーニング完了: %d件中%d件マッチ", screened, matched)
        return graph

    async def build_full_graph(
        self,
        bom_input: str,
        buyer_company: str = "",
        include_people: bool = True,
    ) -> SCIGraph:
        """BOM→Tier推定→所有構造→役員→通関確定のワンコールパイプライン。

        Args:
            bom_input: BOM JSON文字列 or BOM分析結果の辞書
            buyer_company: バイヤー企業名
            include_people: 所有者・役員の人物ノードを含めるか

        Returns:
            完全構築済みの SCIGraph
        """
        import json as _json

        # BOM入力をパース
        if isinstance(bom_input, str):
            try:
                bom_data = _json.loads(bom_input)
            except (ValueError, TypeError):
                # JSON文字列ではない場合、BOM分析を実行
                try:
                    from features.analytics.bom_analyzer import BOMAnalyzer, BOMNode
                    analyzer = BOMAnalyzer()
                    # シンプルなテキスト入力の場合のフォールバック
                    bom_data = {"product_name": bom_input, "part_risks": []}
                except ImportError:
                    bom_data = {"product_name": bom_input, "part_risks": []}
        elif isinstance(bom_input, dict):
            bom_data = bom_input
        else:
            bom_data = {"product_name": "Unknown", "part_risks": []}

        # Step 1: BOMからグラフ構築
        logger.info("Step 1/5: BOMグラフ構築開始")
        graph = await self.build_from_bom(bom_data)

        # バイヤーノードを追加
        if buyer_company:
            graph.add_company(buyer_company)
            # 全Tier-1サプライヤーとバイヤーを接続
            for part in bom_data.get("part_risks", []):
                supplier = part.get("supplier_name", "")
                if supplier and supplier in graph.G:
                    graph.add_supply_relation(
                        supplier, buyer_company,
                        probability=0.9,
                        confirmed=False,
                        source="bom",
                    )

        # Step 2: 制裁スクリーニング
        logger.info("Step 2/5: 制裁スクリーニング")
        graph = await self.enrich_with_sanctions(graph)

        # Step 3: 所有構造
        if include_people:
            logger.info("Step 3/5: 所有構造エンリッチ")
            graph = await self.enrich_with_ownership(graph)

        # Step 4: 役員情報
        if include_people:
            logger.info("Step 4/5: 役員情報エンリッチ")
            graph = await self.enrich_with_directors(graph)

        # Step 5: 通関確定
        logger.info("Step 5/5: 通関データ確定")
        graph = await self.enrich_with_customs(graph, buyer_company)

        logger.info("フルグラフ構築完了: ノード=%d, エッジ=%d",
                     graph.node_count(), graph.edge_count())
        return graph


# ---------------------------------------------------------------------------
# 同期ラッパー（MCP ツールから呼び出し用）
# ---------------------------------------------------------------------------
def build_full_graph_sync(
    bom_input,
    buyer_company: str = "",
    include_people: bool = True,
) -> SCIGraph:
    """build_full_graph の同期版ラッパー。"""
    builder = SCIGraphBuilder()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 既にイベントループ内の場合は新スレッドで実行
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    builder.build_full_graph(bom_input, buyer_company, include_people),
                )
                return future.result(timeout=120)
        else:
            return loop.run_until_complete(
                builder.build_full_graph(bom_input, buyer_company, include_people)
            )
    except RuntimeError:
        return asyncio.run(
            builder.build_full_graph(bom_input, buyer_company, include_people)
        )


# ---------------------------------------------------------------------------
# CLI デモ
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    # テスト用BOM結果
    test_bom = {
        "product_name": "EV Battery Pack",
        "part_risks": [
            {
                "part_id": "P001",
                "part_name": "Lithium Cell",
                "supplier_name": "CATL",
                "supplier_country": "China",
                "hs_code": "8507",
                "tier": 1,
                "risk_score": 35,
            },
            {
                "part_id": "P002",
                "part_name": "Cobalt Cathode",
                "supplier_name": "Umicore",
                "supplier_country": "Belgium",
                "hs_code": "2822",
                "tier": 1,
                "risk_score": 25,
            },
        ],
    }

    graph = asyncio.run(SCIGraphBuilder().build_from_bom(test_bom))
    print(json.dumps(graph.to_dict(), indent=2, ensure_ascii=False, default=str))
