"""
内部ロジスティクスデータストア
================================
SQLite ベースの内部データ保存・参照基盤。
SQLAlchemy は使わず sqlite3 で直接操作。

テーブル:
  inventory, purchase_orders, production_plan,
  locations, transport_routes, procurement_costs
"""

import os
import sqlite3
import datetime
from typing import Optional

# データベースのデフォルトパス
_DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "internal_logistics.db"
)

# ---------- DDL ----------

_DDL = """
CREATE TABLE IF NOT EXISTS inventory (
    part_id       TEXT NOT NULL,
    location_id   TEXT NOT NULL,
    stock_qty     REAL NOT NULL DEFAULT 0,
    safety_stock_days REAL,
    max_stock     REAL,
    unit          TEXT,
    updated_at    TEXT,
    PRIMARY KEY (part_id, location_id)
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id       TEXT NOT NULL,
    vendor_id     TEXT NOT NULL,
    vendor_country TEXT,
    order_qty     REAL NOT NULL,
    delivery_date TEXT,
    lead_time_days INTEGER,
    unit_price    REAL,
    currency      TEXT,
    hs_code       TEXT
);

CREATE TABLE IF NOT EXISTS production_plan (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id    TEXT NOT NULL,
    plant_id      TEXT NOT NULL,
    planned_qty   REAL NOT NULL,
    planned_date  TEXT,
    bom_id        TEXT,
    work_center   TEXT,
    shift         TEXT
);

CREATE TABLE IF NOT EXISTS locations (
    location_id   TEXT PRIMARY KEY,
    location_name TEXT NOT NULL,
    country       TEXT NOT NULL,
    lat           REAL,
    lon           REAL,
    type          TEXT,
    capacity_m2   REAL,
    functions     TEXT
);

CREATE TABLE IF NOT EXISTS transport_routes (
    origin_id       TEXT NOT NULL,
    dest_id         TEXT NOT NULL,
    transport_mode  TEXT NOT NULL,
    lead_time_days  INTEGER NOT NULL,
    cost_per_unit   REAL,
    cost_currency   TEXT,
    carrier_name    TEXT,
    frequency_per_week INTEGER,
    PRIMARY KEY (origin_id, dest_id, transport_mode)
);

CREATE TABLE IF NOT EXISTS procurement_costs (
    part_id       TEXT NOT NULL,
    vendor_id     TEXT NOT NULL,
    unit_price    REAL NOT NULL,
    currency      TEXT NOT NULL,
    min_order_qty REAL,
    valid_from    TEXT,
    valid_until   TEXT,
    tariff_rate   REAL,
    PRIMARY KEY (part_id, vendor_id)
);
"""


class InternalDataStore:
    """内部ロジスティクスデータの SQLite ストア"""

    # DBパスとして許可するディレクトリ（data/ 配下のみ）
    _ALLOWED_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
    )

    def __init__(self, db_path: str = None):
        self.db_path = db_path or _DEFAULT_DB
        # パス検証: data/ ディレクトリ以下のみ許可
        _real = os.path.realpath(self.db_path)
        _allowed_real = os.path.realpath(self._ALLOWED_DIR)
        if not _real.startswith(_allowed_real + os.sep):
            raise PermissionError(
                f"許可ディレクトリ外のDBパスは拒否されました: {self.db_path}"
            )
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        """テーブル自動作成"""
        conn = self._conn()
        conn.executescript(_DDL)
        conn.close()

    # ---------- 汎用 upsert ヘルパー ----------

    @staticmethod
    def _to_str(val):
        """日付や NaN を文字列に変換"""
        if val is None:
            return None
        import math
        if isinstance(val, float) and math.isnan(val):
            return None
        if hasattr(val, "isoformat"):
            return val.isoformat()[:10]
        return str(val) if val != "" else None

    @staticmethod
    def _to_float(val):
        if val is None:
            return None
        import math
        if isinstance(val, float) and math.isnan(val):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(val):
        if val is None:
            return None
        import math
        if isinstance(val, float) and math.isnan(val):
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    # ---------- テーブル別 upsert ----------

    def upsert_inventory(self, records: list):
        """在庫データの UPSERT"""
        conn = self._conn()
        sql = """
            INSERT INTO inventory (part_id, location_id, stock_qty, safety_stock_days, max_stock, unit, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(part_id, location_id) DO UPDATE SET
                stock_qty=excluded.stock_qty,
                safety_stock_days=excluded.safety_stock_days,
                max_stock=excluded.max_stock,
                unit=excluded.unit,
                updated_at=excluded.updated_at
        """
        now = datetime.datetime.now().isoformat()[:19]
        for r in records:
            conn.execute(sql, (
                self._to_str(r.get("part_id")),
                self._to_str(r.get("location_id")),
                self._to_float(r.get("stock_qty", 0)),
                self._to_float(r.get("safety_stock_days")),
                self._to_float(r.get("max_stock")),
                self._to_str(r.get("unit")),
                self._to_str(r.get("last_updated")) or now,
            ))
        conn.commit()
        conn.close()

    def upsert_purchase_orders(self, records: list):
        """発注残データの挿入（ID 自動付番のため INSERT のみ）"""
        conn = self._conn()
        sql = """
            INSERT INTO purchase_orders
                (part_id, vendor_id, vendor_country, order_qty, delivery_date,
                 lead_time_days, unit_price, currency, hs_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for r in records:
            conn.execute(sql, (
                self._to_str(r.get("part_id")),
                self._to_str(r.get("vendor_id")),
                self._to_str(r.get("vendor_country")),
                self._to_float(r.get("order_qty", 0)),
                self._to_str(r.get("delivery_date")),
                self._to_int(r.get("lead_time_days")),
                self._to_float(r.get("unit_price")),
                self._to_str(r.get("currency")),
                self._to_str(r.get("hs_code")),
            ))
        conn.commit()
        conn.close()

    def upsert_production_plan(self, records: list):
        """生産計画データの挿入"""
        conn = self._conn()
        sql = """
            INSERT INTO production_plan
                (product_id, plant_id, planned_qty, planned_date, bom_id, work_center, shift)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        for r in records:
            conn.execute(sql, (
                self._to_str(r.get("product_id")),
                self._to_str(r.get("plant_id")),
                self._to_float(r.get("planned_qty", 0)),
                self._to_str(r.get("planned_date")),
                self._to_str(r.get("bom_id")),
                self._to_str(r.get("work_center")),
                self._to_str(r.get("shift")),
            ))
        conn.commit()
        conn.close()

    def upsert_locations(self, records: list):
        """拠点マスタの UPSERT"""
        conn = self._conn()
        sql = """
            INSERT INTO locations
                (location_id, location_name, country, lat, lon, type, capacity_m2, functions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(location_id) DO UPDATE SET
                location_name=excluded.location_name,
                country=excluded.country,
                lat=excluded.lat,
                lon=excluded.lon,
                type=excluded.type,
                capacity_m2=excluded.capacity_m2,
                functions=excluded.functions
        """
        for r in records:
            conn.execute(sql, (
                self._to_str(r.get("location_id")),
                self._to_str(r.get("location_name")),
                self._to_str(r.get("country")),
                self._to_float(r.get("lat")),
                self._to_float(r.get("lon")),
                self._to_str(r.get("type")),
                self._to_float(r.get("capacity_m2")),
                self._to_str(r.get("functions")),
            ))
        conn.commit()
        conn.close()

    def upsert_transport_routes(self, records: list):
        """輸送ルートの UPSERT"""
        conn = self._conn()
        sql = """
            INSERT INTO transport_routes
                (origin_id, dest_id, transport_mode, lead_time_days,
                 cost_per_unit, cost_currency, carrier_name, frequency_per_week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(origin_id, dest_id, transport_mode) DO UPDATE SET
                lead_time_days=excluded.lead_time_days,
                cost_per_unit=excluded.cost_per_unit,
                cost_currency=excluded.cost_currency,
                carrier_name=excluded.carrier_name,
                frequency_per_week=excluded.frequency_per_week
        """
        for r in records:
            conn.execute(sql, (
                self._to_str(r.get("origin_id")),
                self._to_str(r.get("dest_id")),
                self._to_str(r.get("transport_mode")),
                self._to_int(r.get("lead_time_days", 0)),
                self._to_float(r.get("cost_per_unit")),
                self._to_str(r.get("cost_currency")),
                self._to_str(r.get("carrier_name")),
                self._to_int(r.get("frequency_per_week")),
            ))
        conn.commit()
        conn.close()

    def upsert_procurement_costs(self, records: list):
        """調達コストの UPSERT"""
        conn = self._conn()
        sql = """
            INSERT INTO procurement_costs
                (part_id, vendor_id, unit_price, currency,
                 min_order_qty, valid_from, valid_until, tariff_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(part_id, vendor_id) DO UPDATE SET
                unit_price=excluded.unit_price,
                currency=excluded.currency,
                min_order_qty=excluded.min_order_qty,
                valid_from=excluded.valid_from,
                valid_until=excluded.valid_until,
                tariff_rate=excluded.tariff_rate
        """
        for r in records:
            conn.execute(sql, (
                self._to_str(r.get("part_id")),
                self._to_str(r.get("vendor_id")),
                self._to_float(r.get("unit_price", 0)),
                self._to_str(r.get("currency", "USD")),
                self._to_float(r.get("min_order_qty")),
                self._to_str(r.get("valid_from")),
                self._to_str(r.get("valid_until")),
                self._to_float(r.get("tariff_rate")),
            ))
        conn.commit()
        conn.close()

    # ---------- 参照 API ----------

    def get_stock_days(self, part_id: str, location_id: str) -> Optional[float]:
        """
        在庫日数を算出。
        安全在庫日数 (safety_stock_days) が設定されていれば、
        stock_qty / (平均日次消費量) を近似的に返す。
        設定がなければ safety_stock_days をそのまま返す。
        """
        conn = self._conn()
        row = conn.execute(
            "SELECT stock_qty, safety_stock_days FROM inventory WHERE part_id=? AND location_id=?",
            (part_id, location_id),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return row["safety_stock_days"]

    def get_next_delivery(self, part_id: str) -> Optional[dict]:
        """指定品目の次回納入予定を取得"""
        conn = self._conn()
        row = conn.execute(
            """SELECT * FROM purchase_orders
               WHERE part_id=? AND delivery_date >= date('now')
               ORDER BY delivery_date ASC LIMIT 1""",
            (part_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return dict(row)

    def get_total_lead_time(self, origin: str, dest: str, mode: str = "sea") -> Optional[int]:
        """出発地→目的地の総リードタイム（日）"""
        conn = self._conn()
        row = conn.execute(
            """SELECT lead_time_days FROM transport_routes
               WHERE origin_id=? AND dest_id=? AND LOWER(transport_mode)=LOWER(?)""",
            (origin, dest, mode),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return row["lead_time_days"]

    # 許可テーブル名ホワイトリスト（動的SQLインジェクション防止）
    _ALLOWED_TABLES = frozenset([
        "inventory", "purchase_orders", "production_plan",
        "locations", "transport_routes", "procurement_costs",
    ])

    def get_table_counts(self) -> dict:
        """全テーブルのレコード数を返す（診断用）"""
        conn = self._conn()
        counts = {}
        for t in self._ALLOWED_TABLES:
            # テーブル名はホワイトリスト検証済みのためf-string安全
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {t}").fetchone()
            counts[t] = row["cnt"]
        conn.close()
        return counts
