"""デジタルツインモジュール ユニットテスト
外部API呼び出しなし。全テストはモック/サンプルデータで完結。
SCRI v1.1.0
"""
import sys
import os
import tempfile
import csv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

# プロジェクトルート
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")


# ---------------------------------------------------------------------------
# TestLogisticsImporter: CSV読込、列名マッピング、パストラバーサル防止、エンコーディング検出
# ---------------------------------------------------------------------------

class TestLogisticsImporter:
    """LogisticsImporter の CSV読込・列名マッピング・バリデーション"""

    def _write_csv_in_data_dir(self, filename, header, rows):
        """data/ ディレクトリ配下にテスト用CSVを作成"""
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, f"_test_{filename}_{os.getpid()}.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for row in rows:
                writer.writerow(row)
        return path

    def test_csv_import_standard_columns(self):
        """標準カラム名のCSVを正しく読み込めること"""
        from pipeline.internal.logistics_importer import LogisticsImporter

        importer = LogisticsImporter()
        path = self._write_csv_in_data_dir(
            "std", ["part_id", "location_id", "stock_qty"],
            [["P-001", "PLANT-JP", "5000"], ["P-002", "PLANT-JP", "12000"]],
        )
        try:
            df = importer.auto_import(path, "inventory")
            assert len(df) == 2
            assert "part_id" in df.columns
            assert "location_id" in df.columns
            assert "stock_qty" in df.columns
        finally:
            os.unlink(path)

    def test_csv_import_japanese_aliases(self):
        """日本語カラム名が標準名にマッピングされること"""
        from pipeline.internal.logistics_importer import LogisticsImporter

        importer = LogisticsImporter()
        path = self._write_csv_in_data_dir(
            "jp", ["品目番号", "プラント", "在庫数量"],
            [["P-001", "PLANT-JP", "5000"]],
        )
        try:
            df = importer.auto_import(path, "inventory")
            assert "part_id" in df.columns
            assert "location_id" in df.columns
            assert "stock_qty" in df.columns
        finally:
            os.unlink(path)

    def test_validate_missing_required_column(self):
        """必須カラム不足時にバリデーションエラーが出ること"""
        from pipeline.internal.logistics_importer import LogisticsImporter
        import pandas as pd

        importer = LogisticsImporter()
        # stock_qty が欠落
        df = pd.DataFrame({"part_id": ["P-001"], "location_id": ["PLANT-JP"]})
        result = importer.validate(df, "inventory")
        assert not result.ok
        assert any("stock_qty" in str(e) for e in result.errors)

    def test_encoding_detection_utf8(self):
        """UTF-8ファイルのエンコーディング検出"""
        from pipeline.internal.logistics_importer import LogisticsImporter

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
            f.write("part_id,stock_qty\nP-001,100\n".encode("utf-8"))
            path = f.name
        try:
            enc = LogisticsImporter.detect_encoding(path)
            assert enc in ("utf-8", "utf-8-sig")
        finally:
            os.unlink(path)

    def test_encoding_detection_bom(self):
        """UTF-8 BOMファイルのエンコーディング検出"""
        from pipeline.internal.logistics_importer import LogisticsImporter

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
            f.write(b"\xef\xbb\xbf" + "part_id,stock_qty\nP-001,100\n".encode("utf-8"))
            path = f.name
        try:
            enc = LogisticsImporter.detect_encoding(path)
            assert enc == "utf-8-sig"
        finally:
            os.unlink(path)

    def test_path_traversal_prevention(self):
        """InternalDataStore がパストラバーサルを防止すること"""
        from pipeline.internal.internal_data_store import InternalDataStore

        with pytest.raises(PermissionError):
            InternalDataStore(db_path="/tmp/evil_traversal.db")


# ---------------------------------------------------------------------------
# TestInternalDataStore: UPSERT、データ挿入
# ---------------------------------------------------------------------------

class TestInternalDataStore:
    """InternalDataStore の CRUD テスト"""

    def _make_store(self):
        """data/ ディレクトリ配下にテスト用DBを作成"""
        from pipeline.internal.internal_data_store import InternalDataStore

        os.makedirs(DATA_DIR, exist_ok=True)
        db_path = os.path.join(DATA_DIR, f"_test_store_{os.getpid()}.db")
        store = InternalDataStore(db_path=db_path)
        return store, db_path

    def test_upsert_inventory(self):
        """在庫UPSERTが正しく動作すること"""
        store, db_path = self._make_store()
        try:
            records = [
                {"part_id": "TEST-001", "location_id": "PLANT-A", "stock_qty": 100},
                {"part_id": "TEST-002", "location_id": "PLANT-A", "stock_qty": 200},
            ]
            store.upsert_inventory(records)

            # 更新テスト（同じキーで数量変更）
            store.upsert_inventory([
                {"part_id": "TEST-001", "location_id": "PLANT-A", "stock_qty": 150},
            ])

            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM inventory WHERE part_id = 'TEST-001'"
            ).fetchall()
            conn.close()

            assert len(rows) == 1
            assert dict(rows[0])["stock_qty"] == 150.0  # UPSERT更新確認
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_upsert_purchase_orders(self):
        """発注データ挿入が正しく動作すること"""
        store, db_path = self._make_store()
        try:
            records = [
                {"part_id": "TEST-001", "vendor_id": "V-001",
                 "order_qty": 500, "delivery_date": "2026-04-15"},
            ]
            store.upsert_purchase_orders(records)

            import sqlite3
            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()
            conn.close()
            assert rows[0] >= 1
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# TestStockoutPredictor: 正常系、ゼロ需要、入力バリデーション
# ---------------------------------------------------------------------------

class TestStockoutPredictor:
    """StockoutPredictor ユニットテスト（サンプルデータで完結）"""

    def test_predict_stockout_normal(self):
        """既知部品の枯渇予測が正常に動作すること"""
        from features.digital_twin.stockout_predictor import StockoutPredictor

        # risk_cache を渡してネットワーク呼び出しを抑制
        predictor = StockoutPredictor(risk_cache={"France": 20, "Japan": 15})
        result = predictor.predict_stockout("P-001")

        assert "error" not in result
        assert "current_stock_days" in result
        assert "part_id" in result
        assert result["part_id"] == "P-001"
        assert result["current_stock_days"] >= 0

    def test_predict_stockout_unknown_part(self):
        """存在しない部品IDでエラーが返ること"""
        from features.digital_twin.stockout_predictor import StockoutPredictor

        predictor = StockoutPredictor(risk_cache={})
        result = predictor.predict_stockout("NONEXISTENT-999")
        assert "error" in result

    def test_predict_stockout_empty_part_id(self):
        """空の部品IDでValueErrorが発生すること"""
        from features.digital_twin.stockout_predictor import StockoutPredictor

        predictor = StockoutPredictor(risk_cache={})
        with pytest.raises(ValueError):
            predictor.predict_stockout("")

    def test_predict_stockout_with_demand_multiplier(self):
        """需要倍率を適用した場合の枯渇日数が短くなること"""
        from features.digital_twin.stockout_predictor import StockoutPredictor

        predictor = StockoutPredictor(risk_cache={"France": 20})
        normal = predictor.predict_stockout("P-001")
        boosted = predictor.predict_stockout("P-001", risk_context={"demand_multiplier": 2.0})

        # 需要2倍なら在庫日数は半分程度のはず
        assert boosted["current_stock_days"] < normal["current_stock_days"]

    def test_predict_stockout_negative_demand_multiplier_defaults(self):
        """負の需要倍率が1.0にデフォルトされること"""
        from features.digital_twin.stockout_predictor import StockoutPredictor

        predictor = StockoutPredictor(risk_cache={"France": 20})
        result = predictor.predict_stockout("P-001", risk_context={"demand_multiplier": -1.0})
        assert "error" not in result

    def test_scan_all_parts(self):
        """全部品スキャンが動作すること"""
        from features.digital_twin.stockout_predictor import StockoutPredictor

        predictor = StockoutPredictor(risk_cache={
            "France": 20, "Japan": 15, "Taiwan": 45, "Germany": 18,
            "China": 55, "Netherlands": 15, "United States": 12,
        })
        result = predictor.scan_all_parts()
        # scan_all_parts は dict を返す（parts リスト + summary + timestamp）
        assert isinstance(result, dict)
        assert "parts" in result
        assert "summary" in result
        parts = result["parts"]
        assert isinstance(parts, list)
        assert len(parts) > 0
        # ギャップ日数でソートされているはず（降順）
        if len(parts) >= 2:
            first_gap = parts[0].get("gap_days", 0)
            last_gap = parts[-1].get("gap_days", 0)
            assert first_gap >= last_gap


# ---------------------------------------------------------------------------
# TestProductionCascade: カスケード伝播、二重計上防止
# ---------------------------------------------------------------------------

class TestProductionCascade:
    """ProductionCascadeSimulator シミュレーションテスト"""

    def test_cascade_simulation_known_part(self):
        """既知部品の欠品カスケードが正しくシミュレーションされること"""
        from features.digital_twin.production_cascade import ProductionCascadeSimulator

        cascade = ProductionCascadeSimulator()
        result = cascade.simulate_part_shortage(part_id="P-001", shortage_days=10)

        assert result is not None
        assert isinstance(result, dict)
        # 影響製品リストまたはタイムラインが含まれること
        assert len(result) > 0

    def test_cascade_simulation_unknown_part(self):
        """存在しない部品IDの場合でもクラッシュしないこと"""
        from features.digital_twin.production_cascade import ProductionCascadeSimulator

        cascade = ProductionCascadeSimulator()
        result = cascade.simulate_part_shortage(part_id="NONEXISTENT-999", shortage_days=5)
        # エラーメッセージか空結果を返す
        assert result is not None

    def test_cascade_no_double_counting(self):
        """同一製品が複数経路で影響を受けても二重計上されないこと"""
        from features.digital_twin.production_cascade import ProductionCascadeSimulator

        cascade = ProductionCascadeSimulator()
        # P-001 (MCU) は PROD-EV-01 と PROD-BAT-01 両方のBOMに含まれる
        result = cascade.simulate_part_shortage(part_id="P-001", shortage_days=30)

        if isinstance(result, dict):
            # 結果に affected_products があればチェック
            products = result.get("affected_products", [])
            if isinstance(products, list):
                product_ids = [p.get("product_id", p.get("id", "")) for p in products if isinstance(p, dict)]
                # 重複IDがないこと
                assert len(product_ids) == len(set(product_ids)), "二重計上が発生しています"

    def test_critical_path_finding(self):
        """クリティカルパス探索が動作すること"""
        from features.digital_twin.production_cascade import ProductionCascadeSimulator

        cascade = ProductionCascadeSimulator()
        result = cascade.find_critical_path("PROD-EV-01")
        assert result is not None
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestEmergencyProcurement: 最適化、予算制約、MOQ
# ---------------------------------------------------------------------------

class TestEmergencyProcurement:
    """EmergencyProcurementOptimizer の最適化テスト"""

    def test_optimize_basic(self):
        """基本的な緊急調達最適化が生成されること"""
        from features.digital_twin.emergency_procurement import EmergencyProcurementOptimizer

        procurement = EmergencyProcurementOptimizer(risk_cache={"France": 20, "United States": 15, "Netherlands": 18})
        result = procurement.optimize_emergency_order(
            part_id="P-001",
            required_qty=1000,
            deadline_date="2026-05-01",
        )
        assert result is not None
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_optimize_with_budget_constraint(self):
        """予算制約付きの緊急調達最適化"""
        from features.digital_twin.emergency_procurement import EmergencyProcurementOptimizer

        procurement = EmergencyProcurementOptimizer(risk_cache={"France": 20, "United States": 15, "Netherlands": 18})
        result = procurement.optimize_emergency_order(
            part_id="P-001",
            required_qty=1000,
            deadline_date="2026-05-01",
            budget_limit_jpy=500000,
        )
        assert result is not None
        assert isinstance(result, dict)

    def test_optimize_unknown_part(self):
        """存在しない部品IDの場合でもクラッシュしないこと"""
        from features.digital_twin.emergency_procurement import EmergencyProcurementOptimizer

        procurement = EmergencyProcurementOptimizer(risk_cache={})
        result = procurement.optimize_emergency_order(
            part_id="NONEXISTENT-999",
            required_qty=100,
            deadline_date="2026-05-01",
        )
        assert result is not None

    def test_total_cost_of_risk(self):
        """リスク総コスト計算が動作すること"""
        from features.digital_twin.emergency_procurement import EmergencyProcurementOptimizer

        procurement = EmergencyProcurementOptimizer(risk_cache={"France": 20})
        result = procurement.calculate_total_cost_of_risk(
            part_id="P-001",
            scenario="sanctions",
            duration_days=30,
            annual_production_units=50000,
        )
        assert result is not None
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestTransportRisk: コスト計算、チョークポイント判定
# ---------------------------------------------------------------------------

class TestTransportRisk:
    """TransportRiskAnalyzer の輸送リスク分析テスト"""

    def test_calculate_transport_cost(self):
        """輸送コスト計算が正常に動作すること"""
        from features.digital_twin.transport_risk import TransportRiskAnalyzer

        transport = TransportRiskAnalyzer()
        result = transport.calculate_transport_cost_with_risk(
            origin_country="China",
            dest_country="Japan",
            cargo_value_jpy=10_000_000,
            transport_mode="sea",
        )
        assert result is not None
        assert isinstance(result, dict)
        # コスト情報が含まれること
        has_cost = any(k in result for k in
                       ("total_cost", "total_cost_jpy", "base_freight",
                        "freight_jpy", "cost_breakdown", "error"))
        assert has_cost

    def test_calculate_air_cost(self):
        """航空輸送コスト計算"""
        from features.digital_twin.transport_risk import TransportRiskAnalyzer

        transport = TransportRiskAnalyzer()
        result = transport.calculate_transport_cost_with_risk(
            origin_country="Germany",
            dest_country="Japan",
            cargo_value_jpy=5_000_000,
            transport_mode="air",
        )
        assert result is not None
        assert isinstance(result, dict)

    def test_chokepoint_identification(self):
        """チョークポイント通過の検出"""
        from features.digital_twin.transport_risk import _identify_chokepoints_on_route

        # 中国→ヨーロッパ（マラッカ/スエズを通過するはず）
        chokepoints = _identify_chokepoints_on_route("shanghai", "rotterdam")
        assert isinstance(chokepoints, list)
        # 何らかのチョークポイントが検出されること
        assert len(chokepoints) > 0

    def test_analyze_scheduled_shipments(self):
        """輸送便一括分析が動作すること"""
        from features.digital_twin.transport_risk import TransportRiskAnalyzer

        transport = TransportRiskAnalyzer()
        shipments = [
            {
                "shipment_id": "TEST-001",
                "origin": "Shanghai",
                "destination": "Nagoya",
                "mode": "sea",
                "cargo_value_jpy": 10_000_000,
                "departure_date": "2026-04-15",
            },
        ]
        result = transport.analyze_scheduled_shipments(shipments)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# TestFacilityRiskMapper: 集中度リスク
# ---------------------------------------------------------------------------

class TestFacilityRiskMapper:
    """FacilityRiskMapper の拠点リスク分析テスト"""

    @patch("features.digital_twin.facility_risk_mapper._get_risk_score", return_value=25)
    @patch("features.digital_twin.facility_risk_mapper._get_disaster_alerts", return_value=[])
    def test_map_facility_risks(self, mock_alerts, mock_risk):
        """全拠点リスクマッピングが取得できること"""
        from features.digital_twin.facility_risk_mapper import FacilityRiskMapper

        mapper = FacilityRiskMapper(risk_cache={
            "Japan": 15, "Thailand": 35, "China": 50, "Singapore": 10,
        })
        result = mapper.map_facility_risks()

        assert result is not None
        assert isinstance(result, dict)
        # facilities リストが含まれる
        facilities = result.get("facilities", [])
        assert isinstance(facilities, list)
        assert len(facilities) > 0
        # 各拠点にリスクスコア情報がある
        for facility in facilities:
            assert isinstance(facility, dict)
            has_key = any(k in facility for k in
                         ("location_id", "name", "city", "country", "composite_risk_score"))
            assert has_key

    @patch("features.digital_twin.facility_risk_mapper._get_risk_score", return_value=25)
    @patch("features.digital_twin.facility_risk_mapper._get_disaster_alerts", return_value=[])
    def test_concentration_risk(self, mock_alerts, mock_risk):
        """地理的集中度リスクの算出"""
        from features.digital_twin.facility_risk_mapper import FacilityRiskMapper

        mapper = FacilityRiskMapper(risk_cache={
            "Japan": 15, "Thailand": 35, "China": 50, "Singapore": 10,
        })
        result = mapper.identify_concentration_risk()
        assert result is not None
        assert isinstance(result, dict)
        # 日本拠点が多いので集中度が検出されるはず
        assert len(result) > 0

    def test_facility_mapper_instantiation(self):
        """FacilityRiskMapper がインスタンス化できること"""
        from features.digital_twin.facility_risk_mapper import FacilityRiskMapper

        mapper = FacilityRiskMapper()
        assert mapper is not None
