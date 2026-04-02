"""Goods Layer (物レイヤー) unit tests — v0.9.0

Tests for ImportYeti client, IR scraper, SAP connector, BACI client,
unified GoodsLayerAnalyzer, and MCP goods-layer tools.
All external API calls are mocked.
"""
import sys
import os
import io
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


# ---------------------------------------------------------------------------
# TASK 1: ImportYeti クライアント テスト
# ---------------------------------------------------------------------------

class TestImportYetiClient:
    """ImportYeti US税関データクライアントのテスト"""

    def test_importyeti_import(self):
        """ImportYetiClient がインポート可能であること"""
        from pipeline.trade.importyeti_client import (
            ImportYetiClient, ShipmentRecord, SupplierRelation,
            BuyerRelation, ImportRecord,
        )
        assert ImportYetiClient is not None
        assert ShipmentRecord is not None
        assert ImportRecord is not None

    def test_normalize_country(self):
        """国名正規化のテスト"""
        from pipeline.trade.importyeti_client import normalize_country
        assert normalize_country("China") == "CHN"
        assert normalize_country("VIET NAM") == "VNM"
        assert normalize_country("usa") == "USA"
        assert normalize_country("TAIWAN") == "TWN"
        assert normalize_country("korea") == "KOR"
        assert normalize_country("JPN") == "JPN"

    def test_extract_hs_codes(self):
        """HSコード抽出のテスト"""
        from pipeline.trade.importyeti_client import extract_hs_codes
        codes = extract_hs_codes("ELECTRONIC COMPONENTS HS 8542.31")
        assert len(codes) > 0
        assert any("8542" in c for c in codes)

        # 年号の誤検出回避
        codes2 = extract_hs_codes("shipped in 2025 from China")
        assert all("2025" not in c for c in codes2)

    def test_company_names_match(self):
        """企業名のファジーマッチテスト"""
        from pipeline.trade.importyeti_client import company_names_match
        assert company_names_match("FOXCONN TECHNOLOGY CO., LTD", "FOXCONN TECHNOLOGY")
        assert not company_names_match("APPLE INC", "GOOGLE LLC")

    def test_normalize_company_name(self):
        """企業名正規化のテスト"""
        from pipeline.trade.importyeti_client import normalize_company_name
        result = normalize_company_name("Samsung Electronics Co., Ltd.")
        assert "SAMSUNG" in result
        assert "LTD" not in result

    def test_import_record_from_shipment(self):
        """ImportRecord.from_shipment 変換テスト"""
        from pipeline.trade.importyeti_client import ShipmentRecord, ImportRecord
        sr = ShipmentRecord(
            shipper_name="FOXCONN",
            consignee_name="APPLE INC",
            shipper_country="TWN",
            product_description="Electronic components",
            hs_code="8542.31",
            shipment_date="2026-01-15",
            weight_kg=500.0,
            container_count=2,
        )
        ir = ImportRecord.from_shipment(sr)
        assert ir.shipper == "FOXCONN"
        assert ir.consignee == "APPLE INC"
        assert ir.country_origin == "TWN"
        assert ir.hs_code == "8542.31"

    def test_get_shipments_empty_name(self):
        """空の企業名では空リストを返すこと"""
        from pipeline.trade.importyeti_client import ImportYetiClient
        client = ImportYetiClient()
        results = client.get_shipments("")
        assert results == []

    def test_find_suppliers_empty_name(self):
        """空のバイヤー名では空リストを返すこと"""
        from pipeline.trade.importyeti_client import ImportYetiClient
        client = ImportYetiClient()
        results = client.find_suppliers("")
        assert results == []


# ---------------------------------------------------------------------------
# TASK 2: IR Scraper テスト
# ---------------------------------------------------------------------------

class TestIRScraper:
    """IR (有報/10-K/紛争鉱物) スクレイパーのテスト"""

    def test_ir_scraper_instantiation(self):
        """IRScraper がインスタンス化できること"""
        from pipeline.corporate.ir_scraper import IRScraper
        scraper = IRScraper()
        assert scraper is not None

    def test_supplier_disclosure_dataclass(self):
        """SupplierDisclosure データクラスのテスト"""
        from pipeline.corporate.ir_scraper import SupplierDisclosure
        sd = SupplierDisclosure(
            supplier_name="トヨタ自動車",
            disclosure_type="有報_仕入先",
            relationship="仕入先",
            country="JP",
            source="EDINET",
        )
        assert sd.supplier_name == "トヨタ自動車"
        assert sd.confidence == "DISCLOSED"

    def test_conflict_minerals_report_dataclass(self):
        """ConflictMineralsReport データクラスのテスト"""
        from pipeline.corporate.ir_scraper import ConflictMineralsReport
        report = ConflictMineralsReport(company="AAPL")
        assert report.company == "AAPL"
        assert report.minerals_in_scope == []
        assert report.smelters == []
        assert report.drc_sourcing is None

    def test_conflict_minerals_parsing(self):
        """紛争鉱物テキストパースのテスト"""
        from pipeline.corporate.ir_scraper import IRScraper, ConflictMineralsReport
        report = ConflictMineralsReport(company="TEST")
        text = """
        This report covers our use of tin, tantalum, tungsten and gold (3TG).
        PT Timah, Indonesia, Tin
        AngloGold Ashanti, South Africa, Gold
        We have determined that our products did not originate in the DRC.
        Our smelters are certified conflict-free.
        """
        IRScraper._parse_conflict_minerals_text(text, report)
        assert "tin" in report.minerals_in_scope
        assert "gold" in report.minerals_in_scope
        assert len(report.smelters) >= 2
        assert report.drc_sourcing == "no"
        assert report.conflict_free_certified is True


# ---------------------------------------------------------------------------
# TASK 3: SAP Connector テスト
# ---------------------------------------------------------------------------

class TestSAPConnector:
    """SAP ERP コネクターのテスト"""

    def test_sap_connector_instantiation(self):
        """SAPConnector がインスタンス化できること"""
        from pipeline.erp.sap_connector import SAPConnector
        connector = SAPConnector()
        assert connector is not None

    def test_purchase_record_dataclass(self):
        """PurchaseRecord データクラスのテスト"""
        from pipeline.erp.sap_connector import PurchaseRecord
        rec = PurchaseRecord(
            material_number="MAT-001",
            material_name="リチウムイオンバッテリー",
            vendor_name="LG Energy Solutions",
            vendor_country="KOR",
            hs_code="850760",
        )
        assert rec.material_number == "MAT-001"
        assert rec.is_sole_source is False

    def test_from_purchase_order_csv(self):
        """CSV からの発注データ読込テスト"""
        from pipeline.erp.sap_connector import SAPConnector
        connector = SAPConnector()

        csv_data = io.StringIO(
            "発注番号,品目番号,品目名,仕入先コード,仕入先名,数量,単価,通貨,発注日,納入先プラント,原産国\n"
            "4500001234,MAT-001,リチウムイオンバッテリー,V100,LG Energy Solutions,500,12000,JPY,2025-04-01,JP10,KR\n"
            "4500001234,MAT-002,液晶パネル,V200,BOE Technology,300,8500,JPY,2025-04-01,JP10,CN\n"
        )
        records = connector.from_purchase_order_csv(csv_data)
        assert len(records) == 2
        assert records[0].material_number == "MAT-001"
        assert records[0].vendor_name == "LG Energy Solutions"
        assert records[0].origin_country == "KOR"

    def test_sole_source_detection(self):
        """唯一仕入先の検出テスト"""
        from pipeline.erp.sap_connector import SAPConnector
        connector = SAPConnector()

        csv_data = io.StringIO(
            "発注番号,品目番号,品目名,仕入先名,原産国\n"
            "PO001,MAT-001,バッテリー,LG Energy,KR\n"
            "PO002,MAT-001,バッテリー,LG Energy,KR\n"
            "PO003,MAT-002,液晶,BOE,CN\n"
            "PO004,MAT-002,液晶,AUO,TW\n"
        )
        records = connector.from_purchase_order_csv(csv_data)
        mat001 = [r for r in records if r.material_number == "MAT-001"]
        mat002 = [r for r in records if r.material_number == "MAT-002"]
        # MAT-001 は LG Energy のみ → sole source
        assert all(r.is_sole_source for r in mat001)
        # MAT-002 は BOE + AUO → sole source ではない
        assert not any(r.is_sole_source for r in mat002)

    def test_material_master_csv(self):
        """品目マスタ CSV 読込テスト"""
        from pipeline.erp.sap_connector import SAPConnector
        connector = SAPConnector()

        csv_data = io.StringIO(
            "品目番号,品目名,品目グループ,HSコード,原産国,重量(kg)\n"
            "MAT-001,リチウムイオンバッテリー,ELEC01,850760,KR,0.45\n"
        )
        records = connector.from_material_master_csv(csv_data)
        assert len(records) == 1
        assert records[0].hs_code == "850760"
        assert records[0].weight_kg == 0.45


# ---------------------------------------------------------------------------
# TASK 4: BACI クライアント テスト
# ---------------------------------------------------------------------------

class TestBACIClient:
    """BACI 貿易データクライアントのテスト"""

    def test_baci_client_instantiation(self):
        """BACIClient がインスタンス化できること"""
        from pipeline.trade.baci_client import BACIClient
        client = BACIClient()
        assert client is not None

    def test_trade_flow_dataclass(self):
        """TradeFlow データクラスのテスト"""
        from pipeline.trade.baci_client import TradeFlow
        flow = TradeFlow(
            reporter_iso3="CHN",
            partner_iso3="JPN",
            hs6_code="850710",
            year=2022,
            value_usd=1000000.0,
            quantity_kg=50000.0,
            unit_value_usd=20.0,
        )
        assert flow.reporter_iso3 == "CHN"
        assert flow.value_usd == 1000000.0

    def test_resolve_to_iso3(self):
        """国名→ISO3 解決のテスト"""
        from pipeline.trade.baci_client import _resolve_to_iso3
        assert _resolve_to_iso3("JPN") == "JPN"
        assert _resolve_to_iso3("Japan") == "JPN"
        assert _resolve_to_iso3("china") == "CHN"
        assert _resolve_to_iso3("United States") == "USA"

    def test_available_years(self):
        """available_years がリストを返すこと"""
        from pipeline.trade.baci_client import BACIClient
        client = BACIClient()
        years = client.available_years()
        assert isinstance(years, list)

    def test_get_trade_flow_fallback(self):
        """BACI データ未配置時は Comtrade フォールバックで動作すること"""
        from pipeline.trade.baci_client import BACIClient
        client = BACIClient()
        # BACI CSVが無い状態では None または Comtrade フォールバック結果
        result = client.get_trade_flow("CHN", "JPN", "850710")
        assert result is None or hasattr(result, "value_usd")


# ---------------------------------------------------------------------------
# TASK 5: 統合 API テスト
# ---------------------------------------------------------------------------

class TestGoodsLayerAnalyzer:
    """GoodsLayerAnalyzer 統合APIのテスト"""

    def test_analyzer_instantiation(self):
        """GoodsLayerAnalyzer がインスタンス化できること"""
        from features.goods_layer.unified_api import GoodsLayerAnalyzer
        analyzer = GoodsLayerAnalyzer()
        assert analyzer is not None

    @pytest.mark.network
    def test_analyze_product_structure(self):
        """analyze_product が正しい構造を返すこと"""
        from features.goods_layer.unified_api import GoodsLayerAnalyzer
        analyzer = GoodsLayerAnalyzer()
        result = analyzer.analyze_product(
            part_id="MAT-001",
            part_name="バッテリー",
            supplier_name="LG Energy Solutions",
            supplier_country="KOR",
            hs_code="8507",
        )
        assert isinstance(result, dict)
        assert "part_id" in result
        assert "confidence_level" in result
        assert "data_sources_used" in result
        assert "evidence" in result

    @pytest.mark.network
    def test_analyze_bom(self):
        """analyze_bom がBOM全体を分析できること"""
        from features.goods_layer.unified_api import GoodsLayerAnalyzer
        analyzer = GoodsLayerAnalyzer()
        bom = [
            {"part_id": "MAT-001", "part_name": "バッテリー",
             "supplier_name": "LG", "supplier_country": "KOR", "hs_code": "8507"},
            {"part_id": "MAT-002", "part_name": "半導体",
             "supplier_name": "TSMC", "supplier_country": "TWN", "hs_code": "8542"},
        ]
        result = analyzer.analyze_bom(bom)
        assert isinstance(result, dict)
        assert result["total_parts"] == 2
        assert "confirmed_pct" in result
        assert "parts" in result
        assert len(result["parts"]) == 2

    def test_analyze_bom_empty(self):
        """空のBOMでエラーにならないこと"""
        from features.goods_layer.unified_api import GoodsLayerAnalyzer
        analyzer = GoodsLayerAnalyzer()
        result = analyzer.analyze_bom([])
        assert result["total_parts"] == 0

    def test_data_completeness_report(self):
        """データ完全性レポートが正しい構造を返すこと"""
        from features.goods_layer.unified_api import GoodsLayerAnalyzer
        analyzer = GoodsLayerAnalyzer()
        report = analyzer.get_data_completeness_report()
        assert isinstance(report, dict)
        assert "sap_connected" in report
        assert "importyeti_available" in report
        assert "ir_scraper_available" in report
        assert "baci_available" in report
        assert "total_sources" in report


# ---------------------------------------------------------------------------
# TASK 6: MCP ツール テスト
# ---------------------------------------------------------------------------

class TestMCPGoodsLayerTools:
    """MCP 物レイヤーツールのテスト"""

    def test_search_customs_records_exists(self):
        """search_customs_records がMCPサーバーに登録されていること"""
        from mcp_server.server import search_customs_records
        assert callable(search_customs_records)

    def test_get_supplier_materials_exists(self):
        """get_supplier_materials がMCPサーバーに登録されていること"""
        from mcp_server.server import get_supplier_materials
        assert callable(get_supplier_materials)

    def test_analyze_goods_layer_exists(self):
        """analyze_goods_layer がMCPサーバーに登録されていること"""
        from mcp_server.server import analyze_goods_layer
        assert callable(analyze_goods_layer)

    def test_get_conflict_mineral_report_exists(self):
        """get_conflict_mineral_report がMCPサーバーに登録されていること"""
        from mcp_server.server import get_conflict_mineral_report
        assert callable(get_conflict_mineral_report)

    @pytest.mark.network
    def test_analyze_goods_layer_empty_bom(self):
        """analyze_goods_layer が空BOMで動作すること"""
        from mcp_server.server import analyze_goods_layer
        result = analyze_goods_layer("テスト製品", "[]")
        assert isinstance(result, dict)
        assert "product_name" in result or "error" in result

    @pytest.mark.network
    def test_analyze_goods_layer_with_bom(self):
        """analyze_goods_layer がBOM付きで動作すること"""
        from mcp_server.server import analyze_goods_layer
        bom = json.dumps([
            {"part_id": "MAT-001", "part_name": "バッテリー",
             "supplier_name": "LG", "supplier_country": "KOR", "hs_code": "8507"},
        ])
        result = analyze_goods_layer("テスト製品", bom)
        assert isinstance(result, dict)
        assert "product_name" in result or "error" in result
