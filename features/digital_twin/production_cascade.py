"""生産停止カスケードシミュレーター (B-2)
部品欠品→構成品特定→生産停止タイミング→財務影響を連鎖的に算出。
networkxグラフで依存関係を表現し、最長リードタイム経路(critical path)を特定。
"""
from datetime import datetime, timedelta
from typing import Optional
import networkx as nx

# --- InternalDataStore フォールバック ---
try:
    from pipeline.internal.internal_data_store import InternalDataStore
    _store = InternalDataStore()
except Exception:
    _store = None


# ========================================================================
# サンプルBOM構造（InternalDataStore不在時のフォールバック）
# 製品 → サブアセンブリ → 部品 の階層構造
# ========================================================================
SAMPLE_PRODUCTS = {
    "PROD-EV-01": {
        "product_id": "PROD-EV-01",
        "product_name": "EV制御ユニット",
        "daily_production": 200,
        "daily_revenue_jpy": 40_000_000,  # 4千万円/日
        "bom": {
            "ASSY-MCU-BOARD": {
                "assy_name": "MCUボード",
                "parts": ["P-001", "P-002", "P-005", "P-008"],
                "lead_time_days": 5,
            },
            "ASSY-POWER": {
                "assy_name": "パワーモジュール",
                "parts": ["P-004", "P-005"],
                "lead_time_days": 3,
            },
            "ASSY-CONN": {
                "assy_name": "コネクタユニット",
                "parts": ["P-003", "P-007"],
                "lead_time_days": 2,
            },
        },
    },
    "PROD-BAT-01": {
        "product_id": "PROD-BAT-01",
        "product_name": "車載バッテリーパック",
        "daily_production": 100,
        "daily_revenue_jpy": 80_000_000,  # 8千万円/日
        "bom": {
            "ASSY-CELL": {
                "assy_name": "セルモジュール",
                "parts": ["P-006"],
                "lead_time_days": 7,
            },
            "ASSY-BMS": {
                "assy_name": "BMS制御基板",
                "parts": ["P-001", "P-002", "P-007", "P-008"],
                "lead_time_days": 5,
            },
        },
    },
    "PROD-SENSOR-01": {
        "product_id": "PROD-SENSOR-01",
        "product_name": "車載センサーモジュール",
        "daily_production": 500,
        "daily_revenue_jpy": 15_000_000,  # 1.5千万円/日
        "bom": {
            "ASSY-SIGNAL": {
                "assy_name": "信号処理基板",
                "parts": ["P-001", "P-002", "P-008"],
                "lead_time_days": 4,
            },
            "ASSY-INTERFACE": {
                "assy_name": "インターフェース基板",
                "parts": ["P-003", "P-007", "P-005"],
                "lead_time_days": 3,
            },
        },
    },
}

# 部品マスタ（stockout_predictorと共有想定、フォールバック）
SAMPLE_PARTS_MASTER = {
    "P-001": {"part_name": "MCU STM32F4", "supplier_country": "France", "lead_time_days": 45,
              "safety_stock_days": 15, "unit_cost_jpy": 850, "alternative_suppliers": ["TI (US)", "NXP (Netherlands)"]},
    "P-002": {"part_name": "MLCC 0402 10uF", "supplier_country": "Japan", "lead_time_days": 14,
              "safety_stock_days": 7, "unit_cost_jpy": 5, "alternative_suppliers": ["TDK (Japan)", "Samsung EM (South Korea)"]},
    "P-003": {"part_name": "コネクタ USB-C", "supplier_country": "Taiwan", "lead_time_days": 30,
              "safety_stock_days": 10, "unit_cost_jpy": 120, "alternative_suppliers": ["JAE (Japan)"]},
    "P-004": {"part_name": "パワーMOSFET", "supplier_country": "Germany", "lead_time_days": 60,
              "safety_stock_days": 20, "unit_cost_jpy": 450, "alternative_suppliers": ["Rohm (Japan)", "ON Semi (US)"]},
    "P-005": {"part_name": "アルミ電解コンデンサ", "supplier_country": "Japan", "lead_time_days": 10,
              "safety_stock_days": 5, "unit_cost_jpy": 15, "alternative_suppliers": ["Rubycon (Japan)", "Panasonic (Japan)"]},
    "P-006": {"part_name": "リチウム電池セル", "supplier_country": "China", "lead_time_days": 40,
              "safety_stock_days": 14, "unit_cost_jpy": 12000, "alternative_suppliers": ["Samsung SDI (South Korea)", "Panasonic (Japan)"]},
    "P-007": {"part_name": "車載CAN トランシーバ", "supplier_country": "Netherlands", "lead_time_days": 35,
              "safety_stock_days": 12, "unit_cost_jpy": 280, "alternative_suppliers": ["TI (US)", "Microchip (US)"]},
    "P-008": {"part_name": "高精度抵抗器 0.1%", "supplier_country": "United States", "lead_time_days": 20,
              "safety_stock_days": 7, "unit_cost_jpy": 3, "alternative_suppliers": ["KOA (Japan)", "Yageo (Taiwan)"]},
}


def _get_products() -> dict:
    """製品マスタ取得"""
    if _store:
        try:
            products = _store.get_products()
            if products:
                return products
        except Exception:
            pass
    return SAMPLE_PRODUCTS


def _get_part_master(part_id: str) -> dict:
    """部品マスタ取得"""
    if _store:
        try:
            part = _store.get_part(part_id)
            if part:
                return part
        except Exception:
            pass
    return SAMPLE_PARTS_MASTER.get(part_id, {})


class ProductionCascadeSimulator:
    """生産停止カスケードシミュレーター

    部品欠品が製品生産にどのような連鎖的影響を与えるかを分析。
    BOM構造をグラフとして表現し、影響伝播をシミュレート。
    """

    def __init__(self):
        self._products = _get_products()
        self._graph = self._build_dependency_graph()

    def _build_dependency_graph(self) -> nx.DiGraph:
        """BOM構造からnetworkx有向グラフを構築"""
        G = nx.DiGraph()

        for prod_id, prod in self._products.items():
            G.add_node(prod_id, node_type="product", **{
                k: v for k, v in prod.items() if k != "bom"
            })

            for assy_id, assy in prod.get("bom", {}).items():
                G.add_node(assy_id, node_type="assembly",
                           assy_name=assy["assy_name"],
                           lead_time_days=assy.get("lead_time_days", 3))
                G.add_edge(assy_id, prod_id, relation="assembles_into",
                           lead_time_days=assy.get("lead_time_days", 3))

                for part_id in assy.get("parts", []):
                    part_info = _get_part_master(part_id)
                    if part_id not in G:
                        G.add_node(part_id, node_type="part", **part_info)
                    G.add_edge(part_id, assy_id, relation="component_of",
                               lead_time_days=part_info.get("lead_time_days", 30))

        return G

    def simulate_part_shortage(
        self,
        part_id: str,
        shortage_start_date: Optional[str] = None,
        shortage_days: int = 30,
        bom_result: Optional[dict] = None,
    ) -> dict:
        """部品欠品の生産停止カスケードをシミュレート

        Args:
            part_id: 欠品になる部品ID
            shortage_start_date: 欠品開始日 (ISO format, デフォルト=今日)
            shortage_days: 欠品継続日数
            bom_result: BOMAnalyzer結果（外部BOM使用時、将来拡張用）

        Returns:
            dict: カスケード分析結果
        """
        # --- 入力バリデーション ---
        if not part_id or not isinstance(part_id, str):
            raise ValueError("part_id は空でない文字列で指定してください")
        if shortage_days <= 0:
            raise ValueError("shortage_days は正の整数で指定してください")

        if shortage_start_date:
            start_date = datetime.fromisoformat(shortage_start_date).date()
        else:
            start_date = datetime.utcnow().date()

        part_info = _get_part_master(part_id)
        if not part_info:
            return {"error": f"部品 {part_id} が見つかりません"}

        # Step1: 欠品部品を使用する構成品（アセンブリ）特定
        affected_assemblies = []
        if part_id in self._graph:
            for successor in self._graph.successors(part_id):
                node = self._graph.nodes[successor]
                if node.get("node_type") == "assembly":
                    affected_assemblies.append({
                        "assembly_id": successor,
                        "assembly_name": node.get("assy_name", successor),
                        "lead_time_days": node.get("lead_time_days", 3),
                    })

        # Step2: 各構成品→製品への影響
        # 同一製品が複数経路から影響を受ける場合の二重計上を防止
        affected_products = []
        cascade_sequence = []
        day_offset = 0
        seen_product_ids = set()  # 二重計上防止用

        for assy in affected_assemblies:
            assy_id = assy["assembly_id"]
            # このアセンブリを使う製品を特定
            for prod_successor in self._graph.successors(assy_id):
                prod_node = self._graph.nodes[prod_successor]
                if prod_node.get("node_type") == "product":
                    # 安全在庫でどの程度持つか
                    safety_days = part_info.get("safety_stock_days", 0)
                    production_stop_day = safety_days + assy["lead_time_days"]

                    stop_date = start_date + timedelta(days=production_stop_day)
                    daily_revenue = prod_node.get("daily_revenue_jpy", 0)

                    # 同一製品が既に計上済みの場合はスキップ
                    # （複数アセンブリ経由で同じ製品に影響する場合、
                    #   最初に検出された経路のみを計上する）
                    if prod_successor in seen_product_ids:
                        continue
                    seen_product_ids.add(prod_successor)

                    # カスケードイベント記録
                    cascade_sequence.append({
                        "day": 0,
                        "event": f"部品 {part_id} ({part_info.get('part_name', '')}) 欠品開始",
                        "affected_product": None,
                        "daily_revenue_loss": 0,
                    })
                    cascade_sequence.append({
                        "day": safety_days,
                        "event": f"安全在庫枯渇（{assy['assembly_name']}）",
                        "affected_product": prod_successor,
                        "daily_revenue_loss": 0,
                    })
                    cascade_sequence.append({
                        "day": production_stop_day,
                        "event": f"生産停止: {prod_node.get('product_name', prod_successor)}",
                        "affected_product": prod_successor,
                        "daily_revenue_loss": daily_revenue,
                    })

                    # 代替調達の可能性
                    alt_suppliers = part_info.get("alternative_suppliers", [])
                    alt_lead_time = min(
                        part_info.get("lead_time_days", 30) * 1.5,  # 緊急調達は1.5倍
                        shortage_days,
                    )
                    mitigation = []
                    if alt_suppliers:
                        mitigation.append({
                            "action": "代替サプライヤーへの緊急発注",
                            "suppliers": alt_suppliers,
                            "estimated_lead_time_days": int(alt_lead_time),
                            "cost_premium_pct": 30,  # 緊急調達は30%割増想定
                        })
                    mitigation.append({
                        "action": "安全在庫の積増し（予防策）",
                        "recommended_days": max(shortage_days // 2, 14),
                        "additional_cost_jpy": (
                            part_info.get("unit_cost_jpy", 0) *
                            max(shortage_days // 2, 14) * 200  # 仮の日次消費量
                        ),
                    })

                    # 復旧予測日
                    recovery_date = start_date + timedelta(days=shortage_days)

                    # 実際の生産停止日数
                    actual_stop_days = max(0, shortage_days - production_stop_day)
                    total_loss = daily_revenue * actual_stop_days

                    affected_products.append({
                        "product_id": prod_successor,
                        "product_name": prod_node.get("product_name", ""),
                        "affected_assembly": assy["assembly_name"],
                        "safety_stock_buffer_days": safety_days,
                        "production_stop_date": stop_date.isoformat(),
                        "production_stop_days": actual_stop_days,
                        "daily_revenue_loss_jpy": daily_revenue,
                        "total_revenue_loss_jpy": total_loss,
                        "recovery_date": recovery_date.isoformat(),
                        "mitigation_options": mitigation,
                    })

        # 重複イベントを除去してソート
        seen = set()
        unique_cascade = []
        for ev in cascade_sequence:
            key = (ev["day"], ev["event"])
            if key not in seen:
                seen.add(key)
                unique_cascade.append(ev)
        unique_cascade.sort(key=lambda x: x["day"])

        total_revenue_loss = sum(p["total_revenue_loss_jpy"] for p in affected_products)

        return {
            "trigger_part": {
                "part_id": part_id,
                "part_name": part_info.get("part_name", ""),
                "supplier_country": part_info.get("supplier_country", ""),
            },
            "shortage_start_date": start_date.isoformat(),
            "shortage_days": shortage_days,
            "affected_assemblies": len(affected_assemblies),
            "affected_products_count": len(affected_products),
            "cascade_sequence": unique_cascade,
            "affected_products": affected_products,
            "total_revenue_loss_jpy": total_revenue_loss,
            "recovery_date": (start_date + timedelta(days=shortage_days)).isoformat(),
            "calculated_at": datetime.utcnow().isoformat(),
        }

    def find_critical_path(self, product_id: str, production_date: Optional[str] = None) -> dict:
        """最長リードタイム経路（クリティカルパス）の特定

        Args:
            product_id: 製品ID
            production_date: 生産予定日 (ISO format)

        Returns:
            dict: クリティカルパス情報
        """
        if product_id not in self._graph:
            return {"error": f"製品 {product_id} が見つかりません"}

        # 製品ノードへのすべてのパスを探索
        # 部品→アセンブリ→製品のパスで最長のリードタイム合計を持つものがクリティカルパス
        all_paths = []
        part_nodes = [n for n, d in self._graph.nodes(data=True) if d.get("node_type") == "part"]

        # ノード数制限: 大規模グラフでの探索爆発を防止
        _MAX_PART_NODES = 100
        if len(part_nodes) > _MAX_PART_NODES:
            part_nodes = part_nodes[:_MAX_PART_NODES]

        for part_node in part_nodes:
            try:
                for path in nx.all_simple_paths(self._graph, part_node, product_id):
                    total_lt = 0
                    path_details = []
                    for i, node in enumerate(path):
                        node_data = self._graph.nodes[node]
                        lt = node_data.get("lead_time_days", 0)
                        total_lt += lt
                        path_details.append({
                            "node_id": node,
                            "node_name": (node_data.get("part_name") or
                                          node_data.get("assy_name") or
                                          node_data.get("product_name", node)),
                            "node_type": node_data.get("node_type", ""),
                            "lead_time_days": lt,
                        })
                    all_paths.append({
                        "path": path_details,
                        "total_lead_time_days": total_lt,
                    })
            except nx.NetworkXNoPath:
                continue

        if not all_paths:
            return {"error": f"製品 {product_id} への部品パスが見つかりません"}

        # クリティカルパス = 最長リードタイムのパス
        all_paths.sort(key=lambda x: x["total_lead_time_days"], reverse=True)
        critical = all_paths[0]

        prod_date = None
        order_deadline = None
        if production_date:
            prod_date = datetime.fromisoformat(production_date).date()
            order_deadline = prod_date - timedelta(days=critical["total_lead_time_days"])

        return {
            "product_id": product_id,
            "product_name": self._products.get(product_id, {}).get("product_name", ""),
            "critical_path": critical["path"],
            "total_lead_time_days": critical["total_lead_time_days"],
            "production_date": production_date,
            "order_deadline": order_deadline.isoformat() if order_deadline else None,
            "all_paths_count": len(all_paths),
            "all_paths": all_paths[:5],  # 上位5パス
            "calculated_at": datetime.utcnow().isoformat(),
        }

    def calculate_production_resilience(self, plant_id: str = "") -> dict:
        """工場の生産回復力スコア

        評価軸:
        - 単一調達源率: 代替サプライヤーがない部品の割合
        - 安全在庫充足率: 安全在庫がリードタイムの一定割合以上ある部品の割合
        - 代替サプライヤー確立率: 2社以上の代替がある部品の割合

        Returns:
            dict: 回復力スコアと詳細
        """
        # 全部品を分析対象とする
        all_part_ids = set()
        for prod in self._products.values():
            for assy in prod.get("bom", {}).values():
                for pid in assy.get("parts", []):
                    all_part_ids.add(pid)

        total_parts = len(all_part_ids)
        if total_parts == 0:
            return {"error": "分析対象の部品がありません"}

        single_source_count = 0
        adequate_safety_stock = 0
        dual_source_count = 0
        vulnerabilities = []

        for pid in all_part_ids:
            part = _get_part_master(pid)
            if not part:
                continue

            alt_count = len(part.get("alternative_suppliers", []))
            safety_days = part.get("safety_stock_days", 0)
            lead_time = part.get("lead_time_days", 30)

            # 単一調達源チェック
            if alt_count == 0:
                single_source_count += 1
                vulnerabilities.append({
                    "part_id": pid,
                    "part_name": part.get("part_name", ""),
                    "issue": "単一調達源",
                    "severity": "HIGH",
                    "recommendation": f"代替サプライヤーの開拓が急務",
                })

            # 代替2社以上
            if alt_count >= 2:
                dual_source_count += 1

            # 安全在庫充足 (LTの30%以上が目安)
            if safety_days >= lead_time * 0.3:
                adequate_safety_stock += 1
            elif safety_days < lead_time * 0.15:
                vulnerabilities.append({
                    "part_id": pid,
                    "part_name": part.get("part_name", ""),
                    "issue": f"安全在庫不足（{safety_days}日 < LT{lead_time}日の15%={lead_time*0.15:.0f}日）",
                    "severity": "MEDIUM",
                    "recommendation": f"安全在庫を{int(lead_time * 0.3)}日以上に引き上げ推奨",
                })

        # スコア算出 (0-100)
        single_source_rate = single_source_count / total_parts
        safety_stock_rate = adequate_safety_stock / total_parts
        dual_source_rate = dual_source_count / total_parts

        # 回復力スコア = (1-単一調達率)*40 + 安全在庫率*30 + デュアルソース率*30
        resilience_score = int(
            (1 - single_source_rate) * 40 +
            safety_stock_rate * 30 +
            dual_source_rate * 30
        )

        # レベル判定
        if resilience_score >= 80:
            level = "HIGH"
            assessment = "回復力は高い水準です"
        elif resilience_score >= 50:
            level = "MODERATE"
            assessment = "一部に脆弱性があります。改善を推奨します"
        else:
            level = "LOW"
            assessment = "回復力が低く、欠品リスクが高い状態です"

        return {
            "plant_id": plant_id or "ALL",
            "resilience_score": resilience_score,
            "resilience_level": level,
            "assessment": assessment,
            "metrics": {
                "total_unique_parts": total_parts,
                "single_source_parts": single_source_count,
                "single_source_rate": round(single_source_rate, 3),
                "adequate_safety_stock_parts": adequate_safety_stock,
                "safety_stock_rate": round(safety_stock_rate, 3),
                "dual_source_parts": dual_source_count,
                "dual_source_rate": round(dual_source_rate, 3),
            },
            "vulnerabilities": vulnerabilities,
            "calculated_at": datetime.utcnow().isoformat(),
        }


# === 単独動作テスト ===
if __name__ == "__main__":
    import json
    sim = ProductionCascadeSimulator()

    print("=" * 60)
    print("【カスケードシミュレーション: P-001 MCU 60日欠品】")
    result = sim.simulate_part_shortage("P-001", shortage_days=60)
    print(f"影響アセンブリ: {result['affected_assemblies']}件")
    print(f"影響製品: {result['affected_products_count']}件")
    print(f"総損失額: ¥{result['total_revenue_loss_jpy']:,.0f}")
    for ev in result["cascade_sequence"]:
        print(f"  Day{ev['day']:3d}: {ev['event']}")

    print("\n" + "=" * 60)
    print("【クリティカルパス: PROD-EV-01】")
    cp = sim.find_critical_path("PROD-EV-01", "2026-06-01")
    print(f"クリティカルパス長: {cp['total_lead_time_days']}日")
    print(f"発注期限: {cp['order_deadline']}")
    for node in cp["critical_path"]:
        print(f"  → {node['node_name']} ({node['node_type']}, LT={node['lead_time_days']}日)")

    print("\n" + "=" * 60)
    print("【生産回復力スコア】")
    res = sim.calculate_production_resilience("PLANT-JP-NAGOYA")
    print(f"回復力スコア: {res['resilience_score']} ({res['resilience_level']})")
    print(f"評価: {res['assessment']}")
    print(f"脆弱性: {len(res['vulnerabilities'])}件")
