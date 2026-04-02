"""Goods Layer 統合API — 4データソースの優先度付き統合分析

SAP ERP、ImportYeti（US税関）、IR（有報/10-K）、BACI/Comtrade の
4つのデータソースを優先度順に照合し、部品・BOM 単位でサプライヤー情報を
確認度付きで返す。

優先度:
  1. SAP ERP エクスポート     → CONFIRMED (実際の発注データ)
  2. ImportYeti US税関データ    → CONFIRMED (実際の船荷証券)
  3. IR / 有報・10-K 開示     → PARTIALLY_CONFIRMED (公開開示情報)
  4. BACI / Comtrade 貿易データ → INFERRED (統計的推定)

Usage::

    from features.goods_layer.unified_api import GoodsLayerAnalyzer

    analyzer = GoodsLayerAnalyzer()
    result = analyzer.analyze_product(
        part_id="MAT-001",
        part_name="リチウムイオンバッテリー",
        supplier_name="LG Energy Solutions",
        supplier_country="KOR",
        hs_code="8507",
    )
    print(result["confidence_level"])   # "CONFIRMED" / "PARTIALLY_CONFIRMED" / "INFERRED"

    bom_result = analyzer.analyze_bom([
        {"part_id": "MAT-001", "part_name": "バッテリー",
         "supplier_name": "LG", "supplier_country": "KOR", "hs_code": "8507"},
        {"part_id": "MAT-002", "part_name": "半導体",
         "supplier_name": "TSMC", "supplier_country": "TWN", "hs_code": "8542"},
    ])

    report = analyzer.get_data_completeness_report()
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# プロジェクトルート解決
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# オプション依存のインポート (各データソースクライアント)
# ---------------------------------------------------------------------------
try:
    from pipeline.erp.sap_connector import SAPConnector, PurchaseRecord
    _HAS_SAP = True
except ImportError:
    _HAS_SAP = False
    SAPConnector = None  # type: ignore[assignment,misc]
    PurchaseRecord = None  # type: ignore[assignment,misc]

try:
    from pipeline.trade.importyeti_client import (
        ImportYetiClient,
        SupplierRelation,
        company_names_match,
        normalize_company_name,
    )
    _HAS_IMPORTYETI = True
except ImportError:
    _HAS_IMPORTYETI = False
    ImportYetiClient = None  # type: ignore[assignment,misc]

try:
    from pipeline.corporate.ir_scraper import IRScraper, SupplierDisclosure
    _HAS_IR = True
except ImportError:
    _HAS_IR = False
    IRScraper = None  # type: ignore[assignment,misc]

try:
    from pipeline.trade.baci_client import BACIClient
    _HAS_BACI = True
except ImportError:
    _HAS_BACI = False
    BACIClient = None  # type: ignore[assignment,misc]

try:
    from features.analytics.tier_inference import TierInferenceEngine
    _HAS_TIER_INFERENCE = True
except ImportError:
    _HAS_TIER_INFERENCE = False
    TierInferenceEngine = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
CONFIDENCE_CONFIRMED = "CONFIRMED"
CONFIDENCE_PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
CONFIDENCE_INFERRED = "INFERRED"

SOURCE_SAP = "SAP_ERP"
SOURCE_IMPORTYETI = "ImportYeti_US_Customs"
SOURCE_IR_EDINET = "IR_EDINET"
SOURCE_IR_SEC = "IR_SEC_10K"
SOURCE_BACI = "BACI"
SOURCE_COMTRADE = "Comtrade"


# ---------------------------------------------------------------------------
# GoodsLayerAnalyzer
# ---------------------------------------------------------------------------
class GoodsLayerAnalyzer:
    """Goods Layer 統合分析クラス

    4つのデータソースクライアントを優先度付きで統合し、
    部品単位・BOM単位でサプライヤー情報を確認度付きで返す。

    優先度: SAP > ImportYeti > IR/有報 > BACI/Comtrade

    各データソースのクライアントはコンストラクタでオプショナルに受け取る。
    未指定の場合はデフォルトインスタンスを生成する。
    依存ライブラリがインストールされていない場合は該当ソースをスキップする。
    """

    def __init__(
        self,
        sap_connector: Optional[Any] = None,
        importyeti_client: Optional[Any] = None,
        ir_scraper: Optional[Any] = None,
        baci_client: Optional[Any] = None,
    ) -> None:
        """統合分析クラスを初期化する。

        Args:
            sap_connector: SAPConnector インスタンス (省略時はデフォルト生成)
            importyeti_client: ImportYetiClient インスタンス (省略時はデフォルト生成)
            ir_scraper: IRScraper インスタンス (省略時はデフォルト生成)
            baci_client: BACIClient インスタンス (省略時はデフォルト生成)
        """
        # SAP Connector
        if sap_connector is not None:
            self._sap_connector = sap_connector
        elif _HAS_SAP:
            try:
                self._sap_connector = SAPConnector()
            except Exception as e:
                logger.warning("SAPConnector の初期化に失敗: %s", e)
                self._sap_connector = None
        else:
            self._sap_connector = None

        # ImportYeti Client
        if importyeti_client is not None:
            self._importyeti_client = importyeti_client
        elif _HAS_IMPORTYETI:
            try:
                self._importyeti_client = ImportYetiClient()
            except Exception as e:
                logger.warning("ImportYetiClient の初期化に失敗: %s", e)
                self._importyeti_client = None
        else:
            self._importyeti_client = None

        # IR Scraper
        if ir_scraper is not None:
            self._ir_scraper = ir_scraper
        elif _HAS_IR:
            try:
                self._ir_scraper = IRScraper()
            except Exception as e:
                logger.warning("IRScraper の初期化に失敗: %s", e)
                self._ir_scraper = None
        else:
            self._ir_scraper = None

        # BACI Client
        if baci_client is not None:
            self._baci_client = baci_client
        elif _HAS_BACI:
            try:
                self._baci_client = BACIClient()
            except Exception as e:
                logger.warning("BACIClient の初期化に失敗: %s", e)
                self._baci_client = None
        else:
            self._baci_client = None

        # Tier Inference Engine (BACI/Comtrade ベースの推定用)
        if _HAS_TIER_INFERENCE:
            try:
                self._tier_engine = TierInferenceEngine()
            except Exception as e:
                logger.warning("TierInferenceEngine の初期化に失敗: %s", e)
                self._tier_engine = None
        else:
            self._tier_engine = None

        # メモ化キャッシュ
        self._cache: dict[str, Any] = {}

        # SAP 発注データキャッシュ (from_purchase_order_csv で読み込んだデータ)
        self._sap_purchase_records: list[Any] = []

        logger.info(
            "GoodsLayerAnalyzer 初期化完了: SAP=%s, ImportYeti=%s, IR=%s, BACI=%s",
            self._sap_connector is not None,
            self._importyeti_client is not None,
            self._ir_scraper is not None,
            self._baci_client is not None,
        )

    # ------------------------------------------------------------------
    # SAP データ管理
    # ------------------------------------------------------------------
    def load_sap_data(
        self,
        purchase_csv_path: str,
        column_mapping: Optional[dict[str, str]] = None,
    ) -> int:
        """SAP 発注データ CSV をロードし、内部キャッシュに格納する。

        Args:
            purchase_csv_path: EKKO/EKPO エクスポート CSV のファイルパス
            column_mapping: カスタムカラムマッピング (省略可)

        Returns:
            ロードされたレコード数
        """
        if self._sap_connector is None:
            logger.warning("SAPConnector が利用不可のため、SAPデータをロードできません")
            return 0

        try:
            records = self._sap_connector.from_purchase_order_csv(
                purchase_csv_path, column_mapping=column_mapping,
            )
            self._sap_purchase_records = records
            logger.info("SAPデータロード完了: %d 件", len(records))
            return len(records)
        except Exception as e:
            logger.error("SAPデータロード失敗: %s", e)
            return 0

    def _has_sap_data(self) -> bool:
        """SAP 発注データが読み込まれているかを返す。"""
        return len(self._sap_purchase_records) > 0

    # ------------------------------------------------------------------
    # 公開API: analyze_product
    # ------------------------------------------------------------------
    def analyze_product(
        self,
        part_id: str,
        part_name: str,
        supplier_name: str,
        supplier_country: str,
        hs_code: str = "",
    ) -> dict:
        """単一部品のサプライヤー情報を優先度付きで分析する。

        データソース優先度:
          1. SAP ERP データ (confirmed)
          2. ImportYeti US税関データ (confirmed)
          3. IR / 有報・10-K (partially confirmed)
          4. BACI / Comtrade 貿易統計 (inferred)

        Args:
            part_id: 部品番号
            part_name: 部品名
            supplier_name: サプライヤー名
            supplier_country: サプライヤー国 (ISO3コードまたは国名)
            hs_code: HSコード (省略可、4桁または6桁)

        Returns:
            分析結果の辞書:
              - part_id (str)
              - part_name (str)
              - confirmed_suppliers (list[dict])
              - inferred_suppliers (list[dict])
              - confirmed_pct (float)
              - data_sources_used (list[str])
              - confidence_level (str): CONFIRMED / PARTIALLY_CONFIRMED / INFERRED
              - evidence (list[str])
        """
        # キャッシュチェック
        cache_key = f"product:{part_id}:{supplier_name}:{supplier_country}:{hs_code}"
        if cache_key in self._cache:
            logger.debug("キャッシュヒット: %s", cache_key)
            return self._cache[cache_key]

        confirmed_suppliers: list[dict] = []
        inferred_suppliers: list[dict] = []
        data_sources_used: list[str] = []
        evidence: list[str] = []
        confidence_level = CONFIDENCE_INFERRED  # デフォルト

        # ---------------------------------------------------------------
        # 1. SAP ERP データ照合
        # ---------------------------------------------------------------
        sap_match = self._check_sap_source(part_id, part_name, supplier_name)
        if sap_match is not None:
            confirmed_suppliers.append(sap_match)
            data_sources_used.append(SOURCE_SAP)
            evidence.append(
                f"[SAP/確認済] {sap_match.get('supplier_name', supplier_name)} "
                f"({sap_match.get('supplier_country', supplier_country)}) "
                f"- 発注実績あり"
            )
            confidence_level = CONFIDENCE_CONFIRMED

        # ---------------------------------------------------------------
        # 2. ImportYeti US税関データ照合
        # ---------------------------------------------------------------
        if confidence_level != CONFIDENCE_CONFIRMED:
            iy_match = self._check_importyeti_source(supplier_name, hs_code)
            if iy_match is not None:
                confirmed_suppliers.append(iy_match)
                data_sources_used.append(SOURCE_IMPORTYETI)
                evidence.extend(iy_match.get("evidence", []))
                confidence_level = CONFIDENCE_CONFIRMED
        elif self._importyeti_client is not None:
            # SAP で確認済みでも補強エビデンスとして ImportYeti を追加
            iy_match = self._check_importyeti_source(supplier_name, hs_code)
            if iy_match is not None:
                data_sources_used.append(SOURCE_IMPORTYETI)
                evidence.extend(iy_match.get("evidence", []))

        # ---------------------------------------------------------------
        # 3. IR / 有報・10-K 開示情報照合
        # ---------------------------------------------------------------
        if confidence_level not in (CONFIDENCE_CONFIRMED,):
            ir_match = self._check_ir_source(supplier_name)
            if ir_match is not None:
                confirmed_suppliers.append(ir_match)
                data_sources_used.append(ir_match.get("source", SOURCE_IR_EDINET))
                evidence.extend(ir_match.get("evidence", []))
                confidence_level = CONFIDENCE_PARTIALLY_CONFIRMED

        # ---------------------------------------------------------------
        # 4. BACI / Comtrade 貿易統計による推定
        # ---------------------------------------------------------------
        if hs_code and confidence_level == CONFIDENCE_INFERRED:
            baci_results = self._check_baci_comtrade_source(
                supplier_country, hs_code,
            )
            if baci_results:
                inferred_suppliers.extend(baci_results)
                data_sources_used.append(SOURCE_BACI)
                for br in baci_results:
                    evidence.append(
                        f"[BACI/推定] {br.get('country', '不明')} "
                        f"(シェア: {br.get('trade_share', 0):.1%}, "
                        f"HS: {hs_code})"
                    )
                confidence_level = CONFIDENCE_INFERRED

        # データソースなしの場合
        if not data_sources_used:
            evidence.append(
                f"[注意] {part_name} ({part_id}) に関するデータソースが見つかりません"
            )

        # 確認率の算出
        total_suppliers = len(confirmed_suppliers) + len(inferred_suppliers)
        confirmed_pct = (
            len(confirmed_suppliers) / total_suppliers * 100.0
            if total_suppliers > 0
            else 0.0
        )

        result = {
            "part_id": part_id,
            "part_name": part_name,
            "confirmed_suppliers": confirmed_suppliers,
            "inferred_suppliers": inferred_suppliers,
            "confirmed_pct": round(confirmed_pct, 1),
            "data_sources_used": data_sources_used,
            "confidence_level": confidence_level,
            "evidence": evidence,
        }

        # キャッシュ格納
        self._cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # 公開API: analyze_bom
    # ------------------------------------------------------------------
    def analyze_bom(self, bom_parts: list[dict]) -> dict:
        """BOM (部品表) 全体を分析する。

        各部品に対して analyze_product を実行し、BOM 全体の統計を集約する。

        Args:
            bom_parts: 部品辞書のリスト。各辞書は以下のキーを含む:
                - part_id (str): 部品番号
                - part_name (str): 部品名
                - supplier_name (str): サプライヤー名
                - supplier_country (str): サプライヤー国
                - hs_code (str, optional): HSコード

        Returns:
            BOM分析結果の辞書:
              - total_parts (int)
              - confirmed_parts (int)
              - inferred_parts (int)
              - confirmed_pct (float)
              - parts (list[dict]): 各部品の analyze_product 結果
              - data_sources_summary (dict): ソースごとの利用回数
              - risk_summary (dict): リスクサマリー
        """
        if not bom_parts:
            return {
                "total_parts": 0,
                "confirmed_parts": 0,
                "inferred_parts": 0,
                "confirmed_pct": 0.0,
                "parts": [],
                "data_sources_summary": {},
                "risk_summary": {},
            }

        parts_results: list[dict] = []
        confirmed_count = 0
        inferred_count = 0
        source_counts: dict[str, int] = {}

        for part in bom_parts:
            try:
                result = self.analyze_product(
                    part_id=part.get("part_id", ""),
                    part_name=part.get("part_name", ""),
                    supplier_name=part.get("supplier_name", ""),
                    supplier_country=part.get("supplier_country", ""),
                    hs_code=part.get("hs_code", ""),
                )
                parts_results.append(result)

                # 確認度の集計
                if result["confidence_level"] in (
                    CONFIDENCE_CONFIRMED,
                    CONFIDENCE_PARTIALLY_CONFIRMED,
                ):
                    confirmed_count += 1
                else:
                    inferred_count += 1

                # データソース集計
                for src in result.get("data_sources_used", []):
                    source_counts[src] = source_counts.get(src, 0) + 1

            except Exception as e:
                logger.error(
                    "部品分析エラー: %s (%s): %s",
                    part.get("part_id", "?"),
                    part.get("part_name", "?"),
                    e,
                )
                parts_results.append({
                    "part_id": part.get("part_id", ""),
                    "part_name": part.get("part_name", ""),
                    "confirmed_suppliers": [],
                    "inferred_suppliers": [],
                    "confirmed_pct": 0.0,
                    "data_sources_used": [],
                    "confidence_level": CONFIDENCE_INFERRED,
                    "evidence": [f"[エラー] 分析失敗: {e}"],
                })
                inferred_count += 1

        total = len(bom_parts)
        confirmed_pct = (confirmed_count / total * 100.0) if total > 0 else 0.0

        # リスクサマリー
        confidence_breakdown = {
            CONFIDENCE_CONFIRMED: sum(
                1 for p in parts_results
                if p["confidence_level"] == CONFIDENCE_CONFIRMED
            ),
            CONFIDENCE_PARTIALLY_CONFIRMED: sum(
                1 for p in parts_results
                if p["confidence_level"] == CONFIDENCE_PARTIALLY_CONFIRMED
            ),
            CONFIDENCE_INFERRED: sum(
                1 for p in parts_results
                if p["confidence_level"] == CONFIDENCE_INFERRED
            ),
        }

        # サプライヤー国の集計
        supplier_countries: dict[str, int] = {}
        for part in bom_parts:
            country = part.get("supplier_country", "")
            if country:
                supplier_countries[country] = supplier_countries.get(country, 0) + 1

        risk_summary = {
            "confidence_breakdown": confidence_breakdown,
            "supplier_countries": supplier_countries,
            "unique_countries": len(supplier_countries),
            "data_coverage": round(
                sum(
                    1 for p in parts_results if p.get("data_sources_used")
                ) / total * 100.0,
                1,
            ) if total > 0 else 0.0,
        }

        return {
            "total_parts": total,
            "confirmed_parts": confirmed_count,
            "inferred_parts": inferred_count,
            "confirmed_pct": round(confirmed_pct, 1),
            "parts": parts_results,
            "data_sources_summary": source_counts,
            "risk_summary": risk_summary,
        }

    # ------------------------------------------------------------------
    # 公開API: get_data_completeness_report
    # ------------------------------------------------------------------
    def get_data_completeness_report(self) -> dict:
        """利用可能なデータソースの完全性レポートを返す。

        Returns:
            データソースの利用可否と統計情報の辞書:
              - sap_connected (bool)
              - importyeti_available (bool)
              - ir_scraper_available (bool)
              - baci_available (bool)
              - comtrade_cache_available (bool)
              - total_sources (int)
              - confirmed_sources (int)
        """
        sap_connected = self._sap_connector is not None
        importyeti_available = self._importyeti_client is not None
        ir_scraper_available = self._ir_scraper is not None
        baci_available = self._baci_client is not None

        # Comtrade キャッシュの存在チェック
        comtrade_cache_dir = os.path.join(_PROJECT_ROOT, "data", "comtrade_cache")
        comtrade_cache_available = False
        try:
            if os.path.isdir(comtrade_cache_dir):
                cache_files = [
                    f for f in os.listdir(comtrade_cache_dir)
                    if f.endswith(".json")
                ]
                comtrade_cache_available = len(cache_files) > 0
        except OSError:
            pass

        # 確認済みソース数 (SAP + ImportYeti は confirmed とみなす)
        confirmed_sources = sum([
            sap_connected and self._has_sap_data(),
            importyeti_available,
        ])

        total_sources = sum([
            sap_connected,
            importyeti_available,
            ir_scraper_available,
            baci_available,
            comtrade_cache_available,
        ])

        return {
            "sap_connected": sap_connected,
            "importyeti_available": importyeti_available,
            "ir_scraper_available": ir_scraper_available,
            "baci_available": baci_available,
            "comtrade_cache_available": comtrade_cache_available,
            "total_sources": total_sources,
            "confirmed_sources": confirmed_sources,
        }

    # ------------------------------------------------------------------
    # 内部: SAP ソース照合
    # ------------------------------------------------------------------
    def _check_sap_source(
        self,
        part_id: str,
        part_name: str,
        supplier_name: str,
    ) -> Optional[dict]:
        """SAP 発注データからサプライヤーを照合する。

        品目番号の完全一致、正規化一致、ファジーマッチ (品目名) の順で照合。

        Returns:
            マッチした場合はサプライヤー情報辞書、なければ None
        """
        if not self._has_sap_data():
            return None

        try:
            # 品目番号で検索
            for pr in self._sap_purchase_records:
                # 正規化した品目番号で照合
                norm_part = _normalize_id(part_id)
                norm_mat = _normalize_id(pr.material_number)
                if norm_part and norm_mat and norm_part == norm_mat:
                    return {
                        "supplier_name": pr.vendor_name,
                        "supplier_country": pr.vendor_country or pr.origin_country,
                        "source": SOURCE_SAP,
                        "confidence": CONFIDENCE_CONFIRMED,
                        "sap_material_number": pr.material_number,
                        "sap_po_number": pr.po_number,
                        "hs_code": pr.hs_code,
                        "is_sole_source": pr.is_sole_source,
                    }

            # 品目名でファジーマッチ (RapidFuzz利用可能時)
            if _HAS_IMPORTYETI and part_name:
                for pr in self._sap_purchase_records:
                    if pr.material_name and company_names_match(
                        part_name, pr.material_name,
                    ):
                        return {
                            "supplier_name": pr.vendor_name,
                            "supplier_country": (
                                pr.vendor_country or pr.origin_country
                            ),
                            "source": SOURCE_SAP,
                            "confidence": CONFIDENCE_CONFIRMED,
                            "sap_material_number": pr.material_number,
                            "sap_po_number": pr.po_number,
                            "hs_code": pr.hs_code,
                            "is_sole_source": pr.is_sole_source,
                        }

        except Exception as e:
            logger.error("SAP データ照合エラー: %s", e)

        return None

    # ------------------------------------------------------------------
    # 内部: ImportYeti ソース照合
    # ------------------------------------------------------------------
    def _check_importyeti_source(
        self,
        supplier_name: str,
        hs_code: str = "",
    ) -> Optional[dict]:
        """ImportYeti US税関データからサプライヤー関係を照合する。

        Returns:
            マッチした場合はサプライヤー情報辞書、なければ None
        """
        if self._importyeti_client is None:
            return None

        if not supplier_name or not supplier_name.strip():
            return None

        try:
            # サプライヤーの出荷情報を取得
            shipments = self._importyeti_client.get_shipments(
                supplier_name, limit=10,
            )

            if shipments:
                # 出荷データが見つかった場合、サプライヤーの存在を確認
                evidence_items = [
                    f"[US税関/確認済] {supplier_name} の出荷データ "
                    f"{len(shipments)} 件を確認",
                ]

                # HS コードフィルタ (あれば)
                if hs_code:
                    hs_matched = [
                        s for s in shipments
                        if hs_code in (s.hs_code or "")
                    ]
                    if hs_matched:
                        evidence_items.append(
                            f"[US税関] HS {hs_code} に関連する出荷: "
                            f"{len(hs_matched)} 件"
                        )

                # 代表的な出荷情報
                first = shipments[0]
                desc_preview = (
                    first.product_description[:60]
                    if first.product_description
                    else "N/A"
                )
                evidence_items.append(
                    f"[US税関] 出荷元: {first.shipper_name} "
                    f"({first.shipper_country}), "
                    f"品目: {desc_preview}"
                )

                return {
                    "supplier_name": supplier_name,
                    "supplier_country": first.shipper_country,
                    "source": SOURCE_IMPORTYETI,
                    "confidence": CONFIDENCE_CONFIRMED,
                    "shipment_count": len(shipments),
                    "evidence": evidence_items,
                }

        except Exception as e:
            logger.debug("ImportYeti 照合でエラー (非致命的): %s", e)

        return None

    # ------------------------------------------------------------------
    # 内部: IR ソース照合
    # ------------------------------------------------------------------
    def _check_ir_source(
        self,
        supplier_name: str,
    ) -> Optional[dict]:
        """IR (有報/10-K) からサプライヤー開示情報を照合する。

        Returns:
            マッチした場合はサプライヤー情報辞書、なければ None
        """
        if self._ir_scraper is None:
            return None

        if not supplier_name or not supplier_name.strip():
            return None

        try:
            # 企業名の判定: 日本語を含むかでEDINET/SECを切り替え
            is_jp = any(
                "\u4e00" <= ch <= "\u9fff" or "\u30a0" <= ch <= "\u30ff"
                for ch in supplier_name
            )

            disclosures: list = []
            source_label = SOURCE_IR_EDINET

            if is_jp:
                disclosures = self._ir_scraper.scrape_edinet_suppliers(
                    supplier_name,
                )
                source_label = SOURCE_IR_EDINET
            else:
                # 短い英字文字列はティッカーとみなして SEC 検索
                cleaned = supplier_name.replace("-", "").replace(".", "")
                if cleaned.isalpha() and len(cleaned) <= 6:
                    disclosures = self._ir_scraper.scrape_sec_10k_suppliers(
                        supplier_name,
                    )
                    source_label = SOURCE_IR_SEC

                if not disclosures:
                    disclosures = self._ir_scraper.scrape_edinet_suppliers(
                        supplier_name,
                    )
                    source_label = SOURCE_IR_EDINET

            if disclosures:
                evidence_items = []
                for d in disclosures[:5]:
                    evidence_items.append(
                        f"[IR/{d.source}] {d.supplier_name} "
                        f"({d.relationship}) - {d.disclosure_type} "
                        f"[{d.confidence}]"
                    )

                return {
                    "supplier_name": supplier_name,
                    "source": source_label,
                    "confidence": CONFIDENCE_PARTIALLY_CONFIRMED,
                    "disclosed_suppliers": [
                        {
                            "name": d.supplier_name,
                            "relationship": d.relationship,
                            "disclosure_type": d.disclosure_type,
                            "country": d.country,
                        }
                        for d in disclosures[:10]
                    ],
                    "evidence": evidence_items,
                }

        except Exception as e:
            logger.debug("IR スクレイパー照合でエラー (非致命的): %s", e)

        return None

    # ------------------------------------------------------------------
    # 内部: BACI / Comtrade ソース照合
    # ------------------------------------------------------------------
    def _check_baci_comtrade_source(
        self,
        supplier_country: str,
        hs_code: str,
    ) -> list[dict]:
        """BACI/Comtrade 貿易統計からサプライヤー国を推定する。

        TierInferenceEngine を使用して、指定国の指定 HS コードの
        輸入元国を貿易シェアベースで推定する。

        Returns:
            推定サプライヤーの辞書リスト
        """
        results: list[dict] = []

        # BACIClient 経由の上位輸出国取得
        if self._baci_client is not None and hs_code:
            try:
                top_exporters = self._baci_client.get_top_exporters(
                    hs_code, top_n=5,
                )
                for exp in top_exporters:
                    results.append({
                        "country": exp.country_iso3,
                        "country_name": exp.country_name,
                        "trade_share": round(
                            exp.world_share_pct / 100.0, 4,
                        ),
                        "export_value_usd": exp.export_value_usd,
                        "source": SOURCE_BACI,
                        "confidence": CONFIDENCE_INFERRED,
                    })
                if results:
                    return results
            except Exception as e:
                logger.debug("BACI 照合でエラー (非致命的): %s", e)

        # TierInferenceEngine によるフォールバック
        if self._tier_engine is not None and hs_code and supplier_country:
            try:
                tier2 = self._tier_engine.infer_tier2(
                    tier1_country=supplier_country,
                    hs_code=hs_code,
                    min_share=0.02,
                )
                for t in tier2:
                    source_label = (
                        SOURCE_COMTRADE
                        if t.source == "comtrade"
                        else SOURCE_BACI
                    )
                    results.append({
                        "country": t.country,
                        "trade_share": t.trade_share,
                        "trade_value_usd": t.trade_value_usd,
                        "source": source_label,
                        "confidence": CONFIDENCE_INFERRED,
                        "tier": t.tier,
                    })
            except Exception as e:
                logger.debug("TierInference 照合でエラー (非致命的): %s", e)

        return results


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def _normalize_id(raw_id: str) -> str:
    """品目番号を比較用に正規化する。

    先頭ゼロ除去、ハイフン・スペース・アンダースコア除去、大文字化。
    """
    if not raw_id:
        return ""
    cleaned = raw_id.strip().upper()
    cleaned = cleaned.replace("-", "").replace(" ", "").replace("_", "")
    cleaned = cleaned.lstrip("0") or "0"
    return cleaned
