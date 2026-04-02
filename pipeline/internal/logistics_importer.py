"""
内部ロジスティクスデータ 汎用CSVインポーター
==============================================
CSV / Excel / JSON を自動判定し、列名の揺れを吸収して
標準スキーマの DataFrame に変換する。

対応データ種別:
  inventory, purchase_orders, production_plan,
  locations, transport_routes, procurement_costs
"""

import os
import json
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# ---------- 標準スキーマ定義 ----------

STANDARD_SCHEMA = {
    "inventory": {
        "required": ["part_id", "location_id", "stock_qty"],
        "optional": ["safety_stock_days", "max_stock", "unit", "last_updated"],
        "aliases": {
            "part_id":   ["品目番号", "MATNR", "Material", "Part Number", "品番"],
            "location_id": ["プラント", "WERKS", "Plant", "Warehouse", "拠点"],
            "stock_qty": ["在庫数量", "LABST", "Unrestricted Stock", "Qty"],
            "safety_stock_days": ["安全在庫日数", "Safety Stock Days", "SS Days"],
            "max_stock": ["最大在庫", "Max Stock"],
            "unit": ["単位", "Unit", "UoM"],
            "last_updated": ["最終更新", "Last Updated", "Updated"],
        },
    },
    "purchase_orders": {
        "required": ["part_id", "vendor_id", "order_qty", "delivery_date"],
        "optional": ["vendor_country", "unit_price", "currency", "lead_time_days", "hs_code"],
        "aliases": {
            "part_id":   ["品目番号", "MATNR", "Material", "Part Number", "品番"],
            "vendor_id": ["仕入先", "LIFNR", "Vendor", "Supplier"],
            "order_qty": ["発注数量", "MENGE", "Order Qty", "Quantity"],
            "delivery_date": ["納入日", "EINDT", "Delivery Date", "Due Date"],
            "vendor_country": ["仕入先国", "Vendor Country", "Country"],
            "unit_price": ["単価", "Unit Price", "Price", "標準価格"],
            "currency":  ["通貨", "Currency", "Curr"],
            "lead_time_days": ["リードタイム", "Lead Time Days", "LT Days"],
            "hs_code":   ["HSコード", "HS Code", "Tariff Code"],
        },
    },
    "production_plan": {
        "required": ["product_id", "plant_id", "planned_qty", "planned_date"],
        "optional": ["bom_id", "work_center", "shift"],
        "aliases": {
            "product_id":  ["製品番号", "完成品", "MATNR", "Finished Good"],
            "plant_id":    ["プラント", "WERKS", "Plant", "工場"],
            "planned_qty": ["計画数量", "Planned Qty", "MPS Qty"],
            "planned_date": ["計画日", "Planning Date", "Production Date"],
            "bom_id":      ["BOM番号", "BOM ID", "BOM"],
            "work_center": ["作業区", "Work Center", "WC"],
            "shift":       ["シフト", "Shift"],
        },
    },
    "locations": {
        "required": ["location_id", "location_name", "country"],
        "optional": ["lat", "lon", "type", "capacity_m2", "functions"],
        "aliases": {
            "location_id":   ["拠点コード", "WERKS", "Plant", "Warehouse Code"],
            "location_name": ["拠点名", "Name", "Location Name", "拠点名称"],
            "country":       ["国", "Country", "国コード"],
            "lat":           ["緯度", "Latitude", "Lat"],
            "lon":           ["経度", "Longitude", "Lon", "Lng"],
            "type":          ["拠点種別", "Type", "倉庫種別"],
            "capacity_m2":   ["面積", "Capacity m2", "面積(m2)"],
            "functions":     ["機能", "Functions"],
        },
    },
    "transport_routes": {
        "required": ["origin_id", "dest_id", "transport_mode", "lead_time_days"],
        "optional": ["cost_per_unit", "cost_currency", "carrier_name", "frequency_per_week"],
        "aliases": {
            "origin_id":      ["出発地", "Origin", "From"],
            "dest_id":        ["目的地", "Destination", "To"],
            "transport_mode": ["輸送手段", "Mode", "Transport"],
            "lead_time_days": ["リードタイム", "Lead Time Days", "LT Days", "日数"],
            "cost_per_unit":  ["単位コスト", "Cost Per Unit", "Cost"],
            "cost_currency":  ["通貨", "Currency", "Curr"],
            "carrier_name":   ["運送業者", "Carrier", "Carrier Name"],
            "frequency_per_week": ["週頻度", "Frequency", "Freq/Week"],
        },
    },
    "procurement_costs": {
        "required": ["part_id", "vendor_id", "unit_price", "currency"],
        "optional": ["min_order_qty", "valid_from", "valid_until", "tariff_rate"],
        "aliases": {
            "part_id":    ["品目番号", "MATNR", "Material", "Part Number", "品番"],
            "vendor_id":  ["仕入先", "LIFNR", "Vendor", "Supplier"],
            "unit_price": ["単価", "Unit Price", "Price", "標準価格"],
            "currency":   ["通貨", "Currency", "Curr"],
            "min_order_qty": ["最小発注数量", "MOQ", "Min Order Qty"],
            "valid_from":    ["有効開始", "Valid From", "Start Date"],
            "valid_until":   ["有効終了", "Valid Until", "End Date"],
            "tariff_rate":   ["関税率", "Tariff Rate", "Tariff %"],
        },
    },
}


# ---------- バリデーション結果 ----------

@dataclass
class ValidationResult:
    """バリデーション結果"""
    ok: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0

    def __str__(self):
        status = "OK" if self.ok else "NG"
        lines = [f"[{status}] {self.row_count} rows, {self.col_count} cols"]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        return "\n".join(lines)


# ---------- メインクラス ----------

class LogisticsImporter:
    """
    汎用ロジスティクスデータインポーター

    使い方:
        importer = LogisticsImporter()
        df = importer.auto_import("data/sample_inventory.csv", "inventory")
        result = importer.validate(df, "inventory")
    """

    def __init__(self):
        self.schema = STANDARD_SCHEMA

    # ----- エンコーディング検出 -----

    @staticmethod
    def detect_encoding(file_path: str) -> str:
        """
        BOM判定 + try/except でエンコーディングを自動検出。
        chardet不要。
        """
        with open(file_path, "rb") as f:
            head = f.read(4)

        # BOM判定
        if head[:3] == b"\xef\xbb\xbf":
            return "utf-8-sig"
        if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return "utf-16"

        # UTF-8 で読めるか試す
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                f.read(8192)
            return "utf-8"
        except UnicodeDecodeError:
            pass

        # Shift-JIS / CP932
        try:
            with open(file_path, "r", encoding="cp932") as f:
                f.read(8192)
            return "cp932"
        except UnicodeDecodeError:
            pass

        # EUC-JP
        try:
            with open(file_path, "r", encoding="euc-jp") as f:
                f.read(8192)
            return "euc-jp"
        except UnicodeDecodeError:
            pass

        # フォールバック
        return "utf-8"

    # ----- ファイル読み込み -----

    def _read_file(self, file_path: str) -> pd.DataFrame:
        """CSV / Excel / JSON を自動判定して読み込む"""
        ext = Path(file_path).suffix.lower()

        if ext in (".xlsx", ".xls"):
            return pd.read_excel(file_path)
        elif ext == ".json":
            return pd.read_json(file_path)
        else:
            # CSV (デフォルト)
            enc = self.detect_encoding(file_path)
            # 区切り文字を自動推定
            with open(file_path, "r", encoding=enc) as f:
                sample = f.read(2048)
            sep = "\t" if "\t" in sample and "," not in sample else ","
            return pd.read_csv(file_path, encoding=enc, sep=sep)

    # ----- 列名マッピング -----

    def _build_alias_map(self, data_type: str) -> dict:
        """エイリアス → 標準列名 の逆引き辞書を構築"""
        schema = self.schema[data_type]
        alias_map = {}
        all_fields = schema["required"] + schema["optional"]
        aliases_dict = schema.get("aliases", {})

        for std_name in all_fields:
            # 標準名そのものもマッチ対象
            alias_map[std_name.lower()] = std_name
            alias_map[std_name.lower().replace("_", " ")] = std_name
            alias_map[std_name.lower().replace("_", "")] = std_name
            for alias in aliases_dict.get(std_name, []):
                alias_map[alias.lower()] = std_name
                alias_map[alias.lower().replace(" ", "_")] = std_name

        return alias_map

    def _map_columns(self, df: pd.DataFrame, data_type: str) -> pd.DataFrame:
        """DataFrame の列名を標準スキーマに変換"""
        alias_map = self._build_alias_map(data_type)
        rename = {}
        for col in df.columns:
            key = str(col).strip().lower()
            if key in alias_map:
                rename[col] = alias_map[key]
            else:
                # アンダースコア/スペースを除去して再照合
                key2 = key.replace(" ", "").replace("_", "")
                if key2 in alias_map:
                    rename[col] = alias_map[key2]

        if rename:
            df = df.rename(columns=rename)
        return df

    # ----- メイン API -----

    def auto_import(self, file_path: str, data_type: str) -> pd.DataFrame:
        """
        CSV/Excel/JSONを自動判定、列名自動マッピング、標準スキーマ変換。

        Args:
            file_path: 入力ファイルパス
            data_type: データ種別 (inventory, purchase_orders, ...)

        Returns:
            標準列名に変換された DataFrame
        """
        if data_type not in self.schema:
            raise ValueError(
                f"未対応のデータ種別: {data_type}  "
                f"対応: {list(self.schema.keys())}"
            )

        # パストラバーサル防止: data/ ディレクトリ以下のみ許可
        _project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        _allowed_dir = os.path.join(_project_root, "data")
        _real_path = os.path.realpath(file_path)
        if not _real_path.startswith(os.path.realpath(_allowed_dir) + os.sep):
            raise PermissionError(
                f"許可ディレクトリ外へのアクセスは禁止されています: {file_path}"
            )

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"ファイルが見つかりません: {file_path}")

        # 読み込み
        df = self._read_file(file_path)

        # 列名マッピング
        df = self._map_columns(df, data_type)

        # 日付列の変換
        date_cols = [c for c in df.columns if "date" in c.lower() or "updated" in c.lower()]
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        # 数値列の変換
        numeric_hints = [
            "qty", "stock", "price", "cost", "rate", "days",
            "lat", "lon", "capacity", "frequency",
        ]
        for col in df.columns:
            col_lower = col.lower()
            if any(h in col_lower for h in numeric_hints):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    # ----- バリデーション -----

    def validate(self, df: pd.DataFrame, data_type: str) -> ValidationResult:
        """
        必須列・データ型・値域チェック。

        Args:
            df: auto_import() で変換済みの DataFrame
            data_type: データ種別

        Returns:
            ValidationResult
        """
        result = ValidationResult(
            row_count=len(df),
            col_count=len(df.columns),
        )

        schema = self.schema[data_type]

        # 必須列の存在チェック
        for col in schema["required"]:
            if col not in df.columns:
                result.errors.append(f"必須列 '{col}' が見つかりません")
                result.ok = False

        if not result.ok:
            return result

        # 必須列の NULL チェック
        for col in schema["required"]:
            null_count = df[col].isna().sum()
            if null_count > 0:
                result.warnings.append(
                    f"'{col}' に {null_count} 件の NULL があります"
                )

        # 必須列の型チェック: 数値列に文字列が混入している場合はコアース
        numeric_hints = [
            "qty", "stock", "price", "cost", "rate", "days",
            "lat", "lon", "capacity", "frequency",
        ]
        for col in schema["required"]:
            col_lower = col.lower()
            if any(h in col_lower for h in numeric_hints):
                non_numeric = 0
                for val in df[col].dropna():
                    try:
                        float(val)
                    except (ValueError, TypeError):
                        non_numeric += 1
                if non_numeric > 0:
                    result.warnings.append(
                        f"'{col}' に {non_numeric} 件の非数値データがあります（数値に変換を試みます）"
                    )
                    df[col] = pd.to_numeric(df[col], errors="coerce")

        # 数値列の値域チェック
        for col in df.columns:
            col_lower = col.lower()
            if "qty" in col_lower or "stock" in col_lower:
                neg = (df[col].dropna() < 0).sum()
                if neg > 0:
                    result.warnings.append(
                        f"'{col}' に {neg} 件の負値があります"
                    )
            if "price" in col_lower or "cost" in col_lower:
                neg = (pd.to_numeric(df[col], errors="coerce").dropna() < 0).sum()
                if neg > 0:
                    result.warnings.append(
                        f"'{col}' に {neg} 件の負値があります"
                    )
            if col == "lat":
                out = ((df[col].dropna() < -90) | (df[col].dropna() > 90)).sum()
                if out:
                    result.errors.append(f"緯度の範囲外が {out} 件")
                    result.ok = False
            if col == "lon":
                out = ((df[col].dropna() < -180) | (df[col].dropna() > 180)).sum()
                if out:
                    result.errors.append(f"経度の範囲外が {out} 件")
                    result.ok = False

        # 重複チェック（データ種別ごと）
        dup_keys = {
            "inventory": ["part_id", "location_id"],
            "purchase_orders": None,  # ID自動付番のため重複許容
            "production_plan": None,
            "locations": ["location_id"],
            "transport_routes": ["origin_id", "dest_id", "transport_mode"],
            "procurement_costs": ["part_id", "vendor_id"],
        }
        keys = dup_keys.get(data_type)
        if keys and all(k in df.columns for k in keys):
            dups = df.duplicated(subset=keys, keep=False).sum()
            if dups > 0:
                result.warnings.append(
                    f"キー {keys} で {dups} 件の重複があります"
                )

        return result
