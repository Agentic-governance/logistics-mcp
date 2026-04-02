"""SAP ERP エクスポート CSV/Excel コネクター
SAPテーブル (EKKO/EKPO, EINA/EINE, MARA/MARC) のCSV/Excelエクスポートを
パースし、SCRIプラットフォームの内部データ構造へ変換する。

NOTE: 本モジュールはSAP APIへ直接接続しない。
SAPへの接続はお客様環境に依存するため、ここでは標準的なエクスポートファイル
（CSV/Excel）をインポートする機能のみ提供する。

サンプル CSV フォーマット (EKKO/EKPO 発注データ):
-------------------------------------------------------
発注番号,品目番号,品目名,仕入先コード,仕入先名,数量,単価,通貨,発注日,納入先プラント,原産国
4500001234,MAT-001,リチウムイオンバッテリー,V100,LG Energy Solutions,500,12000,JPY,2025-04-01,JP10,KR
4500001234,MAT-002,液晶パネル 15.6",V200,BOE Technology,300,8500,JPY,2025-04-01,JP10,CN
4500001235,MAT-003,半導体チップ MCU32,V300,TSMC,10000,450,JPY,2025-04-15,JP20,TW
4500001235,MAT-001,リチウムイオンバッテリー,V400,Samsung SDI,200,11800,JPY,2025-04-15,JP20,KR
4500001236,MAT-004,コネクタ USB-C,V500,Amphenol Corp,5000,120,JPY,2025-05-01,JP10,US

サンプル CSV フォーマット (MARA/MARC 品目マスタ):
-------------------------------------------------------
品目番号,品目名,品目グループ,HSコード,原産国,重量(kg)
MAT-001,リチウムイオンバッテリー,ELEC01,850760,KR,0.45
MAT-002,液晶パネル 15.6",ELEC02,901380,CN,0.32

サンプル CSV フォーマット (EINA/EINE 購買情報レコード):
-------------------------------------------------------
品目番号,仕入先名,基準価格,リードタイム(日),最小発注数量,有効期限
MAT-001,LG Energy Solutions,12000,45,100,2026-03-31
MAT-001,Samsung SDI,11800,50,200,2026-03-31
"""
from __future__ import annotations

import csv
import io
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import IO, Optional, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PurchaseRecord:
    """EKKO/EKPO エクスポートから生成される発注レコード"""

    material_number: str
    material_name: str
    vendor_name: str
    vendor_country: str = ""
    hs_code: str = ""
    quantity: float = 0.0
    amount_jpy: float = 0.0
    cost_share: float = 0.0
    lead_time_days: int = 0
    is_sole_source: bool = False
    origin_country: str = ""
    # 内部参照用
    po_number: str = ""
    currency: str = "JPY"
    order_date: str = ""
    plant: str = ""
    vendor_code: str = ""


@dataclass
class MaterialRecord:
    """MARA/MARC エクスポートから生成される品目マスタレコード"""

    material_number: str
    material_name: str = ""
    material_group: str = ""
    hs_code: str = ""
    origin_country: str = ""
    weight_kg: float = 0.0


@dataclass
class InfoRecord:
    """EINA/EINE エクスポートから生成される購買情報レコード"""

    material_number: str
    vendor_name: str = ""
    base_price: float = 0.0
    lead_time_days: int = 0
    min_order_qty: float = 0.0
    valid_until: str = ""


# ---------------------------------------------------------------------------
# Column alias mapping
# ---------------------------------------------------------------------------

STANDARD_COLUMN_ALIASES: dict[str, list[str]] = {
    # --- 発注ヘッダ / 明細 (EKKO/EKPO) ---
    "発注番号": [
        "PO Number", "Purchase Order", "EBELN", "PO", "発注No",
        "発注伝票番号", "注文番号", "購買伝票番号", "購買伝票",
    ],
    "品目番号": [
        "Material", "MATNR", "品目", "部品番号", "Material Number",
        "Mat. No.", "品番", "資材番号", "品目コード", "材料番号",
    ],
    "品目名": [
        "Material Description", "MAKTX", "品名", "品目テキスト",
        "Material Text", "Description", "品目説明", "品目名称",
    ],
    "仕入先コード": [
        "Vendor", "Supplier", "LIFNR", "仕入先", "Vendor Code",
        "Supplier Code", "仕入先番号", "取引先コード",
    ],
    "仕入先名": [
        "Vendor Name", "Supplier Name", "NAME1", "仕入先名称",
        "取引先名", "Vendor Description",
    ],
    "数量": [
        "Quantity", "MENGE", "Qty", "Order Quantity", "発注数量",
        "注文数量", "PO Quantity",
    ],
    "単価": [
        "Unit Price", "NETPR", "Price", "Net Price", "単価(税抜)",
        "基準価格", "Net Value",
    ],
    "通貨": [
        "Currency", "WAERS", "Curr.", "通貨コード", "Currency Key",
    ],
    "発注日": [
        "PO Date", "BEDAT", "Order Date", "Document Date",
        "注文日", "伝票日付", "発注日付",
    ],
    "納入先プラント": [
        "Plant", "WERKS", "プラント", "Delivering Plant",
        "受入プラント", "納入先", "工場",
    ],
    "原産国": [
        "Country of Origin", "HERKL", "原産地国", "Origin Country",
        "原産国コード", "Country", "LAND1", "仕入先国", "サプライヤー国",
    ],
    # --- 品目マスタ (MARA/MARC) ---
    "品目グループ": [
        "Material Group", "MATKL", "品目Gr", "Mat. Group",
        "資材グループ", "品目分類",
    ],
    "HSコード": [
        "HS Code", "Commodity Code", "STAWN", "HS番号",
        "関税番号", "Tariff Code", "統計品目番号",
    ],
    "重量": [
        "Weight", "BRGEW", "Gross Weight", "重量(kg)",
        "総重量", "Net Weight", "NTGEW",
    ],
    # --- 購買情報レコード (EINA/EINE) ---
    "基準価格": [
        "Base Price", "NETPR", "Price", "Info Price",
        "情報価格", "標準価格",
    ],
    "リードタイム": [
        "Lead Time", "APLFZ", "リードタイム(日)", "Planned Deliv. Time",
        "計画納入日数", "Delivery Time", "LT(days)",
    ],
    "最小発注数量": [
        "Min Order Qty", "MINBM", "MOQ", "Minimum Quantity",
        "最小ロット", "最低発注量",
    ],
    "有効期限": [
        "Valid Until", "DATBI", "Validity End", "有効終了日",
        "有効期限日", "End Date",
    ],
}

# ---------------------------------------------------------------------------
# Country code resolution
# ---------------------------------------------------------------------------

# Common country name / SAP code -> ISO 3166-1 alpha-3
_COUNTRY_TO_ISO3: dict[str, str] = {
    # アジア
    "jp": "JPN", "jpn": "JPN", "japan": "JPN", "日本": "JPN",
    "cn": "CHN", "chn": "CHN", "china": "CHN", "中国": "CHN",
    "tw": "TWN", "twn": "TWN", "taiwan": "TWN", "台湾": "TWN",
    "kr": "KOR", "kor": "KOR", "korea": "KOR", "south korea": "KOR", "韓国": "KOR",
    "th": "THA", "tha": "THA", "thailand": "THA", "タイ": "THA",
    "vn": "VNM", "vnm": "VNM", "vietnam": "VNM", "ベトナム": "VNM",
    "id": "IDN", "idn": "IDN", "indonesia": "IDN", "インドネシア": "IDN",
    "my": "MYS", "mys": "MYS", "malaysia": "MYS", "マレーシア": "MYS",
    "sg": "SGP", "sgp": "SGP", "singapore": "SGP", "シンガポール": "SGP",
    "in": "IND", "ind": "IND", "india": "IND", "インド": "IND",
    "ph": "PHL", "phl": "PHL", "philippines": "PHL", "フィリピン": "PHL",
    "mm": "MMR", "mmr": "MMR", "myanmar": "MMR", "ミャンマー": "MMR",
    "kh": "KHM", "khm": "KHM", "cambodia": "KHM", "カンボジア": "KHM",
    "bd": "BGD", "bgd": "BGD", "bangladesh": "BGD", "バングラデシュ": "BGD",
    "pk": "PAK", "pak": "PAK", "pakistan": "PAK", "パキスタン": "PAK",
    # 欧州
    "de": "DEU", "deu": "DEU", "germany": "DEU", "ドイツ": "DEU",
    "fr": "FRA", "fra": "FRA", "france": "FRA", "フランス": "FRA",
    "it": "ITA", "ita": "ITA", "italy": "ITA", "イタリア": "ITA",
    "gb": "GBR", "gbr": "GBR", "uk": "GBR", "united kingdom": "GBR", "英国": "GBR", "イギリス": "GBR",
    "nl": "NLD", "nld": "NLD", "netherlands": "NLD", "オランダ": "NLD",
    "ch": "CHE", "che": "CHE", "switzerland": "CHE", "スイス": "CHE",
    "se": "SWE", "swe": "SWE", "sweden": "SWE", "スウェーデン": "SWE",
    "cz": "CZE", "cze": "CZE", "czech republic": "CZE", "チェコ": "CZE",
    "pl": "POL", "pol": "POL", "poland": "POL", "ポーランド": "POL",
    "hu": "HUN", "hun": "HUN", "hungary": "HUN", "ハンガリー": "HUN",
    "at": "AUT", "aut": "AUT", "austria": "AUT", "オーストリア": "AUT",
    "be": "BEL", "bel": "BEL", "belgium": "BEL", "ベルギー": "BEL",
    # 北米
    "us": "USA", "usa": "USA", "united states": "USA", "アメリカ": "USA", "米国": "USA",
    "ca": "CAN", "can": "CAN", "canada": "CAN", "カナダ": "CAN",
    "mx": "MEX", "mex": "MEX", "mexico": "MEX", "メキシコ": "MEX",
    # その他
    "au": "AUS", "aus": "AUS", "australia": "AUS", "オーストラリア": "AUS",
    "br": "BRA", "bra": "BRA", "brazil": "BRA", "ブラジル": "BRA",
    "ru": "RUS", "rus": "RUS", "russia": "RUS", "ロシア": "RUS",
    "sa": "SAU", "sau": "SAU", "saudi arabia": "SAU", "サウジアラビア": "SAU",
    "ae": "ARE", "are": "ARE", "uae": "ARE", "アラブ首長国連邦": "ARE",
    "tr": "TUR", "tur": "TUR", "turkey": "TUR", "トルコ": "TUR",
    "za": "ZAF", "zaf": "ZAF", "south africa": "ZAF", "南アフリカ": "ZAF",
    "eg": "EGY", "egy": "EGY", "egypt": "EGY", "エジプト": "EGY",
    "ng": "NGA", "nga": "NGA", "nigeria": "NGA", "ナイジェリア": "NGA",
    "ke": "KEN", "ken": "KEN", "kenya": "KEN", "ケニア": "KEN",
    "ua": "UKR", "ukr": "UKR", "ukraine": "UKR", "ウクライナ": "UKR",
    "il": "ISR", "isr": "ISR", "israel": "ISR", "イスラエル": "ISR",
    "ir": "IRN", "irn": "IRN", "iran": "IRN", "イラン": "IRN",
    "kp": "PRK", "prk": "PRK", "north korea": "PRK", "北朝鮮": "PRK",
    "by": "BLR", "blr": "BLR", "belarus": "BLR", "ベラルーシ": "BLR",
    "sy": "SYR", "syr": "SYR", "syria": "SYR", "シリア": "SYR",
    "cu": "CUB", "cub": "CUB", "cuba": "CUB", "キューバ": "CUB",
    "ve": "VEN", "ven": "VEN", "venezuela": "VEN", "ベネズエラ": "VEN",
    "nz": "NZL", "nzl": "NZL", "new zealand": "NZL", "ニュージーランド": "NZL",
}

# ISO3 codes pass through unchanged
for _code in list(set(_COUNTRY_TO_ISO3.values())):
    _COUNTRY_TO_ISO3[_code.lower()] = _code

# Material group -> HS code prefix (fallback mapping)
_MATERIAL_GROUP_TO_HS: dict[str, str] = {
    "ELEC01": "8507",    # 電池
    "ELEC02": "9013",    # 液晶
    "ELEC03": "8542",    # 半導体
    "ELEC04": "8536",    # コネクタ
    "MECH01": "8483",    # 機械部品
    "MECH02": "7318",    # ボルト・ナット
    "CHEM01": "3901",    # プラスチック
    "CHEM02": "2804",    # 化学品
    "METAL01": "7601",   # アルミ
    "METAL02": "7208",   # 鉄鋼
    "RAW01": "2603",     # 鉱石
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _resolve_country_iso3(raw: str) -> str:
    """国名/コードを ISO 3166-1 alpha-3 に正規化する。

    3文字の大文字がそのまま ISO3 として妥当な場合はそのまま返す。
    それ以外は _COUNTRY_TO_ISO3 を参照してマッピングする。
    """
    if not raw or not raw.strip():
        return ""
    cleaned = raw.strip()
    # Already ISO3 format
    if len(cleaned) == 3 and cleaned.isalpha() and cleaned.upper() in _COUNTRY_TO_ISO3.values():
        return cleaned.upper()
    key = cleaned.lower()
    return _COUNTRY_TO_ISO3.get(key, cleaned.upper() if len(cleaned) <= 3 else cleaned)


def _normalize_vendor_name(name: str) -> str:
    """仕入先名を正規化する。

    先頭末尾の空白除去、全角->半角変換 (基本的な文字)、
    株式会社/Co., Ltd. 等の法人格表記をそのまま保持しつつ
    比較しやすい形に整える。
    """
    if not name:
        return ""
    # 全角英数 -> 半角英数 (基本)
    result = name.strip()
    zen = "".join(chr(0xFF01 + i) for i in range(94))
    han = "".join(chr(0x21 + i) for i in range(94))
    table = str.maketrans(zen, han)
    result = result.translate(table)
    # 全角スペース -> 半角
    result = result.replace("\u3000", " ")
    # 連続スペース除去
    while "  " in result:
        result = result.replace("  ", " ")
    return result


def _fuzzy_match_vendor(name1: str, name2: str, threshold: int = 80) -> bool:
    """RapidFuzz を使って仕入先名のファジーマッチを行う。

    RapidFuzz が利用できない場合は単純な文字列比較にフォールバックする。
    """
    n1 = _normalize_vendor_name(name1)
    n2 = _normalize_vendor_name(name2)
    if not n1 or not n2:
        return False
    # 完全一致
    if n1.lower() == n2.lower():
        return True
    try:
        from rapidfuzz import fuzz
        score = fuzz.token_sort_ratio(n1, n2)
        return score >= threshold
    except ImportError:
        # フォールバック: 一方が他方に含まれているか
        return n1.lower() in n2.lower() or n2.lower() in n1.lower()


def _resolve_columns(
    headers: list[str],
    column_mapping: dict[str, str],
) -> dict[str, str]:
    """実際のCSVヘッダー名を標準カラム名にマッピングする。

    1. ユーザー指定の column_mapping を最優先で適用
    2. STANDARD_COLUMN_ALIASES に基づいて自動解決

    Returns:
        {実際のCSVヘッダー名: 標準カラム名} のマッピング
    """
    resolved: dict[str, str] = {}

    # ユーザー指定のマッピングを反転 (標準名 -> CSV名)
    user_reverse = {v: k for k, v in column_mapping.items()} if column_mapping else {}

    for header in headers:
        h_stripped = header.strip()
        # 1. ユーザー指定があればそれを使用
        if h_stripped in column_mapping:
            resolved[h_stripped] = column_mapping[h_stripped]
            continue
        if h_stripped in user_reverse:
            resolved[h_stripped] = h_stripped
            continue
        # 2. 標準名にそのまま一致
        if h_stripped in STANDARD_COLUMN_ALIASES:
            resolved[h_stripped] = h_stripped
            continue
        # 3. エイリアスから検索
        matched = False
        for standard_name, aliases in STANDARD_COLUMN_ALIASES.items():
            if h_stripped in aliases or h_stripped.lower() in [a.lower() for a in aliases]:
                resolved[h_stripped] = standard_name
                matched = True
                break
        if not matched:
            # マッチしなければそのまま保持 (警告のみ)
            resolved[h_stripped] = h_stripped

    return resolved


def _read_file_to_dataframe(
    file_path_or_buffer: Union[str, Path, IO],
    encoding: Optional[str] = None,
) -> "list[dict[str, str]]":
    """CSV/Excel ファイルを読み込み、辞書のリストとして返す。

    pandas が利用可能な場合は pandas を使い、なければ csv モジュールで処理する。
    Shift-JIS と UTF-8 の自動検出も行う。
    """
    # ファイルパスかバッファかを判定
    is_path = isinstance(file_path_or_buffer, (str, Path))

    # Excel判定
    is_excel = False
    if is_path:
        ext = str(file_path_or_buffer).lower()
        is_excel = ext.endswith((".xlsx", ".xls", ".xlsm"))

    # --- pandas 利用 ---
    try:
        import pandas as pd

        if is_excel:
            df = pd.read_excel(file_path_or_buffer, dtype=str)
        elif is_path:
            # エンコーディング自動検出
            enc = encoding
            if not enc:
                enc = _detect_encoding(str(file_path_or_buffer))
            df = pd.read_csv(file_path_or_buffer, dtype=str, encoding=enc)
        else:
            # バッファ (StringIO / BytesIO)
            if isinstance(file_path_or_buffer, io.BytesIO):
                enc = encoding or "utf-8"
                file_path_or_buffer.seek(0)
                content = file_path_or_buffer.read()
                try:
                    text = content.decode(enc)
                except UnicodeDecodeError:
                    text = content.decode("shift_jis", errors="replace")
                df = pd.read_csv(io.StringIO(text), dtype=str)
            else:
                file_path_or_buffer.seek(0)
                df = pd.read_csv(file_path_or_buffer, dtype=str)

        df = df.fillna("")
        return df.to_dict("records")

    except ImportError:
        pass

    # --- csv モジュール フォールバック ---
    if is_excel:
        raise RuntimeError(
            "Excel ファイルの読み込みには pandas + openpyxl が必要です。"
            " pip install pandas openpyxl を実行してください。"
        )

    if is_path:
        enc = encoding or _detect_encoding(str(file_path_or_buffer))
        with open(file_path_or_buffer, "r", encoding=enc, newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    else:
        if isinstance(file_path_or_buffer, io.BytesIO):
            file_path_or_buffer.seek(0)
            content = file_path_or_buffer.read()
            enc = encoding or "utf-8"
            try:
                text = content.decode(enc)
            except UnicodeDecodeError:
                text = content.decode("shift_jis", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            return [dict(row) for row in reader]
        else:
            file_path_or_buffer.seek(0)
            reader = csv.DictReader(file_path_or_buffer)
            return [dict(row) for row in reader]


def _detect_encoding(file_path: str) -> str:
    """ファイルのエンコーディングを検出する (UTF-8 / Shift-JIS)。

    BOMチェック -> UTF-8 試行 -> Shift-JIS フォールバック。
    """
    try:
        with open(file_path, "rb") as f:
            raw = f.read(4096)
        # BOM check
        if raw.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        # UTF-8 decode attempt
        try:
            raw.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass
        # Shift-JIS
        try:
            raw.decode("shift_jis")
            return "shift_jis"
        except UnicodeDecodeError:
            pass
        # CP932 (Shift-JIS superset on Windows)
        try:
            raw.decode("cp932")
            return "cp932"
        except UnicodeDecodeError:
            pass
    except OSError:
        pass
    return "utf-8"


def _safe_float(value: str, default: float = 0.0) -> float:
    """文字列を安全にfloatに変換。カンマ区切りや全角数字にも対応。"""
    if not value or not value.strip():
        return default
    cleaned = value.strip()
    # 全角数字 -> 半角
    zen_digits = "".join(chr(0xFF10 + i) for i in range(10))
    han_digits = "0123456789"
    table = str.maketrans(zen_digits + "\uFF0E\uFF0C", han_digits + ".,")
    cleaned = cleaned.translate(table)
    # カンマ除去 (千位区切り)
    cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def _safe_int(value: str, default: int = 0) -> int:
    """文字列を安全にintに変換。"""
    f = _safe_float(value, float(default))
    return int(f)


def _get_column_value(row: dict, standard_name: str, col_map: dict[str, str]) -> str:
    """マッピング済みの辞書から標準カラム名に対応する値を取得する。

    col_map は {実際ヘッダー: 標準名} なので、逆引きして実際ヘッダーの値を取る。
    """
    for actual_header, mapped_name in col_map.items():
        if mapped_name == standard_name:
            val = row.get(actual_header, "")
            return val.strip() if isinstance(val, str) else str(val).strip() if val else ""
    # col_map にない場合、standard_name がそのままキーとして存在するか
    val = row.get(standard_name, "")
    return val.strip() if isinstance(val, str) else str(val).strip() if val else ""


# ---------------------------------------------------------------------------
# SAPConnector
# ---------------------------------------------------------------------------


class SAPConnector:
    """SAP ERP エクスポートファイルのインポーター。

    SAPテーブルのCSV/Excelエクスポートを読み込み、SCRIプラットフォーム内部の
    データ構造 (PurchaseRecord, MaterialRecord, InfoRecord) に変換する。

    BOMNode との統合メソッド (merge_with_bom) により、発注実績データで
    BOM のリスク分析精度を向上させる。

    Usage:
        connector = SAPConnector()

        # 発注データ取り込み
        purchases = connector.from_purchase_order_csv("ekko_ekpo_export.csv")

        # BOM と統合
        from features.analytics.bom_analyzer import BOMNode
        bom_nodes = [...]  # 既存 BOM データ
        upgraded = connector.merge_with_bom(purchases, bom_nodes)
    """

    def __init__(self) -> None:
        self._vendor_name_cache: dict[str, str] = {}

    # -----------------------------------------------------------------------
    # Public API: from_purchase_order_csv
    # -----------------------------------------------------------------------

    def from_purchase_order_csv(
        self,
        file_path_or_buffer: Union[str, Path, IO],
        column_mapping: Optional[dict[str, str]] = None,
    ) -> list[PurchaseRecord]:
        """EKKO/EKPO エクスポート CSV/Excel から発注レコードを取り込む。

        Args:
            file_path_or_buffer: ファイルパス (str/Path) またはファイルライクオブジェクト
            column_mapping: カスタムカラムマッピング
                            {CSVヘッダー名: 標準カラム名} 形式
                            例: {"Vendor No.": "仕入先コード"}

        Returns:
            PurchaseRecord のリスト

        Raises:
            FileNotFoundError: ファイルが存在しない場合
            RuntimeError: Excel読み込みに必要なライブラリがない場合
        """
        mapping = column_mapping or {}
        rows = _read_file_to_dataframe(file_path_or_buffer)

        if not rows:
            logger.warning("発注データが空です: %s", file_path_or_buffer)
            return []

        # カラムマッピング解決
        headers = list(rows[0].keys())
        col_map = _resolve_columns(headers, mapping)
        logger.debug("カラムマッピング: %s", col_map)

        # レコード生成
        records: list[PurchaseRecord] = []
        for row in rows:
            material_number = _get_column_value(row, "品目番号", col_map)
            if not material_number:
                logger.debug("品目番号が空のため行をスキップ: %s", row)
                continue

            vendor_raw = _get_column_value(row, "仕入先名", col_map)
            vendor_name = self._normalize_and_cache_vendor(vendor_raw)

            origin_raw = _get_column_value(row, "原産国", col_map)
            origin_country = _resolve_country_iso3(origin_raw)

            quantity = _safe_float(_get_column_value(row, "数量", col_map))
            unit_price = _safe_float(_get_column_value(row, "単価", col_map))
            amount = quantity * unit_price

            rec = PurchaseRecord(
                material_number=material_number,
                material_name=_get_column_value(row, "品目名", col_map),
                vendor_name=vendor_name,
                vendor_country=origin_country,
                hs_code=_get_column_value(row, "HSコード", col_map),
                quantity=quantity,
                amount_jpy=amount,
                origin_country=origin_country,
                po_number=_get_column_value(row, "発注番号", col_map),
                currency=_get_column_value(row, "通貨", col_map) or "JPY",
                order_date=_get_column_value(row, "発注日", col_map),
                plant=_get_column_value(row, "納入先プラント", col_map),
                vendor_code=_get_column_value(row, "仕入先コード", col_map),
            )
            records.append(rec)

        if not records:
            return records

        # --- 後処理 ---
        # 1. cost_share 計算 (品目年間金額 / 全体金額)
        total_amount = sum(r.amount_jpy for r in records)
        if total_amount > 0:
            for rec in records:
                rec.cost_share = round(rec.amount_jpy / total_amount, 6)

        # 2. sole-source 判定 (品目ごとにユニーク仕入先数を数える)
        material_vendors: dict[str, set[str]] = {}
        for rec in records:
            key = rec.material_number
            if key not in material_vendors:
                material_vendors[key] = set()
            material_vendors[key].add(rec.vendor_name.lower())

        for rec in records:
            rec.is_sole_source = len(material_vendors.get(rec.material_number, set())) == 1

        # 3. HS コード補完 (品目グループからのフォールバック)
        # 品目マスタの品目グループが取得できる場合に使用
        # (purchase order には品目グループが含まれないことが多いため、
        #  hs_code が空のレコードにはマテリアルグループベースの推定を適用しない)

        logger.info(
            "発注データ取り込み完了: %d 件 (ユニーク品目: %d, ユニーク仕入先: %d)",
            len(records),
            len(material_vendors),
            len({r.vendor_name for r in records}),
        )
        return records

    # -----------------------------------------------------------------------
    # Public API: from_material_master_csv
    # -----------------------------------------------------------------------

    def from_material_master_csv(
        self,
        file_path_or_buffer: Union[str, Path, IO],
        column_mapping: Optional[dict[str, str]] = None,
    ) -> list[MaterialRecord]:
        """MARA/MARC エクスポート CSV/Excel から品目マスタを取り込む。

        Args:
            file_path_or_buffer: ファイルパス (str/Path) またはファイルライクオブジェクト
            column_mapping: カスタムカラムマッピング

        Returns:
            MaterialRecord のリスト
        """
        mapping = column_mapping or {}
        rows = _read_file_to_dataframe(file_path_or_buffer)

        if not rows:
            logger.warning("品目マスタデータが空です: %s", file_path_or_buffer)
            return []

        headers = list(rows[0].keys())
        col_map = _resolve_columns(headers, mapping)

        records: list[MaterialRecord] = []
        for row in rows:
            material_number = _get_column_value(row, "品目番号", col_map)
            if not material_number:
                continue

            material_group = _get_column_value(row, "品目グループ", col_map)
            hs_code = _get_column_value(row, "HSコード", col_map)

            # HS コードが空の場合、品目グループから推定
            if not hs_code and material_group:
                hs_code = _MATERIAL_GROUP_TO_HS.get(material_group, "")

            origin_raw = _get_column_value(row, "原産国", col_map)
            origin_country = _resolve_country_iso3(origin_raw)

            rec = MaterialRecord(
                material_number=material_number,
                material_name=_get_column_value(row, "品目名", col_map),
                material_group=material_group,
                hs_code=hs_code,
                origin_country=origin_country,
                weight_kg=_safe_float(_get_column_value(row, "重量", col_map)),
            )
            records.append(rec)

        logger.info("品目マスタ取り込み完了: %d 件", len(records))
        return records

    # -----------------------------------------------------------------------
    # Public API: from_info_record_csv
    # -----------------------------------------------------------------------

    def from_info_record_csv(
        self,
        file_path_or_buffer: Union[str, Path, IO],
        column_mapping: Optional[dict[str, str]] = None,
    ) -> list[InfoRecord]:
        """EINA/EINE エクスポート CSV/Excel から購買情報レコードを取り込む。

        Args:
            file_path_or_buffer: ファイルパス (str/Path) またはファイルライクオブジェクト
            column_mapping: カスタムカラムマッピング

        Returns:
            InfoRecord のリスト
        """
        mapping = column_mapping or {}
        rows = _read_file_to_dataframe(file_path_or_buffer)

        if not rows:
            logger.warning("購買情報レコードが空です: %s", file_path_or_buffer)
            return []

        headers = list(rows[0].keys())
        col_map = _resolve_columns(headers, mapping)

        records: list[InfoRecord] = []
        for row in rows:
            material_number = _get_column_value(row, "品目番号", col_map)
            if not material_number:
                continue

            vendor_raw = _get_column_value(row, "仕入先名", col_map)
            vendor_name = self._normalize_and_cache_vendor(vendor_raw)

            rec = InfoRecord(
                material_number=material_number,
                vendor_name=vendor_name,
                base_price=_safe_float(_get_column_value(row, "基準価格", col_map)),
                lead_time_days=_safe_int(_get_column_value(row, "リードタイム", col_map)),
                min_order_qty=_safe_float(_get_column_value(row, "最小発注数量", col_map)),
                valid_until=_get_column_value(row, "有効期限", col_map),
            )
            records.append(rec)

        logger.info("購買情報レコード取り込み完了: %d 件", len(records))
        return records

    # -----------------------------------------------------------------------
    # Public API: merge_with_bom
    # -----------------------------------------------------------------------

    def merge_with_bom(
        self,
        purchase_records: list[PurchaseRecord],
        bom_nodes: list,
        fuzzy_threshold: int = 75,
    ) -> list:
        """発注データで BOM ノードを補強する。

        BOM の品目番号と発注データの品目番号をマッチングし、
        一致した BOM ノードを "CONFIRMED_SAP" に昇格させる。

        マッチング戦略:
        1. 完全一致 (material_number)
        2. 正規化一致 (空白・ハイフン除去後)
        3. RapidFuzz によるファジーマッチ (part_name / material_name)

        Args:
            purchase_records: from_purchase_order_csv() で取得した発注レコード
            bom_nodes: BOMNode のリスト (features.analytics.bom_analyzer.BOMNode)
            fuzzy_threshold: ファジーマッチの閾値 (0-100, デフォルト75)

        Returns:
            更新された BOMNode のリスト (入力リストを直接変更して返す)
        """
        if not purchase_records or not bom_nodes:
            return bom_nodes

        # 発注データのインデックス構築
        # key: 正規化した品目番号, value: PurchaseRecord のリスト
        po_by_material: dict[str, list[PurchaseRecord]] = {}
        po_by_name: dict[str, list[PurchaseRecord]] = {}

        for pr in purchase_records:
            norm_num = self._normalize_material_number(pr.material_number)
            if norm_num not in po_by_material:
                po_by_material[norm_num] = []
            po_by_material[norm_num].append(pr)

            norm_name = pr.material_name.strip().lower()
            if norm_name:
                if norm_name not in po_by_name:
                    po_by_name[norm_name] = []
                po_by_name[norm_name].append(pr)

        matched_count = 0

        for node in bom_nodes:
            matched_pr = None

            # Strategy 1: 完全一致 (品目番号)
            norm_part_id = self._normalize_material_number(node.part_id)
            if norm_part_id in po_by_material:
                matched_pr = po_by_material[norm_part_id][0]

            # Strategy 2: 品目名での完全一致
            if matched_pr is None:
                norm_name = node.part_name.strip().lower()
                if norm_name in po_by_name:
                    matched_pr = po_by_name[norm_name][0]

            # Strategy 3: RapidFuzz ファジーマッチ (品目名)
            if matched_pr is None and node.part_name:
                matched_pr = self._fuzzy_match_purchase(
                    node.part_name,
                    purchase_records,
                    threshold=fuzzy_threshold,
                )

            # マッチした場合: BOMNode を更新
            if matched_pr is not None:
                matched_count += 1

                # supplier 情報を更新
                if matched_pr.vendor_name:
                    node.supplier_name = matched_pr.vendor_name
                if matched_pr.vendor_country:
                    node.supplier_country = matched_pr.vendor_country

                # HS コード設定
                if matched_pr.hs_code:
                    node.hs_code = matched_pr.hs_code

                # 素材情報
                if matched_pr.material_name and not node.material:
                    node.material = matched_pr.material_name

                # コスト情報
                if matched_pr.amount_jpy > 0 and matched_pr.quantity > 0:
                    # JPY -> USD 概算 (1 USD = 150 JPY)
                    unit_price_usd = (matched_pr.amount_jpy / matched_pr.quantity) / 150.0
                    node.unit_cost_usd = round(unit_price_usd, 4)

                # sole-source = critical
                if matched_pr.is_sole_source:
                    node.is_critical = True

                # 推定 -> 確認済みに昇格
                node.is_inferred = False
                node.confidence = 1.0

                logger.debug(
                    "BOMNode マッチ: %s (%s) -> SAP %s (%s) [%s]",
                    node.part_id,
                    node.part_name,
                    matched_pr.material_number,
                    matched_pr.vendor_name,
                    matched_pr.vendor_country,
                )

        logger.info(
            "BOM マージ完了: %d/%d ノードがSAPデータで確認 (CONFIRMED_SAP)",
            matched_count,
            len(bom_nodes),
        )
        return bom_nodes

    # -----------------------------------------------------------------------
    # Enrichment: 品目マスタ・購買情報レコードで発注データを補強
    # -----------------------------------------------------------------------

    def enrich_purchases_with_master(
        self,
        purchases: list[PurchaseRecord],
        materials: list[MaterialRecord],
        info_records: Optional[list[InfoRecord]] = None,
    ) -> list[PurchaseRecord]:
        """品目マスタ・購買情報レコードで発注データを補強する。

        - HS コードの補完
        - 原産国の補完
        - リードタイムの設定
        """
        # 品目マスタインデックス
        mat_index: dict[str, MaterialRecord] = {}
        for m in materials:
            mat_index[self._normalize_material_number(m.material_number)] = m

        # 購買情報インデックス (品目番号 + 仕入先名 -> InfoRecord)
        info_index: dict[str, InfoRecord] = {}
        if info_records:
            for ir in info_records:
                key = f"{self._normalize_material_number(ir.material_number)}|{ir.vendor_name.lower()}"
                info_index[key] = ir

        for pr in purchases:
            norm_num = self._normalize_material_number(pr.material_number)

            # 品目マスタから補完
            mat = mat_index.get(norm_num)
            if mat:
                if not pr.hs_code and mat.hs_code:
                    pr.hs_code = mat.hs_code
                if not pr.origin_country and mat.origin_country:
                    pr.origin_country = mat.origin_country
                    pr.vendor_country = mat.origin_country

            # 購買情報レコードから補完
            info_key = f"{norm_num}|{pr.vendor_name.lower()}"
            ir = info_index.get(info_key)
            if ir:
                if ir.lead_time_days > 0:
                    pr.lead_time_days = ir.lead_time_days

        logger.info("発注データ補強完了: %d 件", len(purchases))
        return purchases

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _normalize_and_cache_vendor(self, raw_name: str) -> str:
        """仕入先名を正規化し、キャッシュに格納する。

        同一セッション内で類似名称が出現した場合、先に登録された正規化名を返す。
        これにより「LG Energy Solutions」と「LG ENERGY SOLUTIONS Co.,Ltd.」を
        同一仕入先として扱える。
        """
        if not raw_name or not raw_name.strip():
            return ""

        normalized = _normalize_vendor_name(raw_name)

        # キャッシュヒットチェック (完全一致)
        cache_key = normalized.lower()
        if cache_key in self._vendor_name_cache:
            return self._vendor_name_cache[cache_key]

        # 既存キャッシュとのファジーマッチ
        for cached_key, cached_name in self._vendor_name_cache.items():
            if _fuzzy_match_vendor(normalized, cached_name, threshold=85):
                # 既存の正規化名に統一
                self._vendor_name_cache[cache_key] = cached_name
                return cached_name

        # 新規登録
        self._vendor_name_cache[cache_key] = normalized
        return normalized

    @staticmethod
    def _normalize_material_number(mat_num: str) -> str:
        """品目番号を比較用に正規化する。

        SAPの品目番号は先頭ゼロ埋めや区切り文字の有無が環境によって異なる。
        - 先頭ゼロ除去
        - ハイフン・スペース・アンダースコア除去
        - 大文字化
        """
        if not mat_num:
            return ""
        cleaned = mat_num.strip().upper()
        cleaned = cleaned.replace("-", "").replace(" ", "").replace("_", "")
        cleaned = cleaned.lstrip("0") or "0"
        return cleaned

    @staticmethod
    def _fuzzy_match_purchase(
        part_name: str,
        purchase_records: list[PurchaseRecord],
        threshold: int = 75,
    ) -> Optional[PurchaseRecord]:
        """品目名でファジーマッチして最もスコアの高い発注レコードを返す。"""
        if not part_name:
            return None

        try:
            from rapidfuzz import fuzz, process

            candidates = {
                i: pr.material_name
                for i, pr in enumerate(purchase_records)
                if pr.material_name
            }
            if not candidates:
                return None

            result = process.extractOne(
                part_name,
                candidates,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=threshold,
            )
            if result is not None:
                # result = (matched_string, score, key)
                matched_idx = result[2]
                return purchase_records[matched_idx]

        except ImportError:
            # RapidFuzz なしのフォールバック: 部分文字列マッチ
            part_lower = part_name.strip().lower()
            for pr in purchase_records:
                if pr.material_name and (
                    part_lower in pr.material_name.lower()
                    or pr.material_name.lower() in part_lower
                ):
                    return pr

        return None
