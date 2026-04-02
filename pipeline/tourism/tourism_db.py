"""観光統計専用SQLiteデータベース
data/tourism_stats.db に観光統計4テーブルを管理。
SQLAlchemy不使用、sqlite3直接操作。
"""
import json
import os
import sqlite3
from datetime import datetime


# プロジェクトルートの data/ 配下にDBを配置
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "tourism_stats.db")

# テーブル作成SQL
_CREATE_TABLES = """
-- アウトバウンド統計
CREATE TABLE IF NOT EXISTS outbound_stats(
    source_country TEXT,
    year INT,
    month INT,
    outbound_total INT,
    top_destinations TEXT,  -- JSON
    data_source TEXT,
    retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_country, year, month)
);

-- インバウンド統計（競合含む）
CREATE TABLE IF NOT EXISTS inbound_stats(
    destination TEXT,
    source_country TEXT,
    year INT,
    month INT,
    arrivals INT,
    revenue_usd FLOAT,
    data_source TEXT,
    retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (destination, source_country, year, month)
);

-- 日本インバウンド詳細
CREATE TABLE IF NOT EXISTS japan_inbound(
    source_country TEXT,
    year INT,
    month INT,
    arrivals INT,
    purpose_leisure_pct FLOAT,
    purpose_business_pct FLOAT,
    avg_stay_days FLOAT,
    avg_spend_jpy INT,
    data_source TEXT DEFAULT 'JNTO',
    PRIMARY KEY (source_country, year, month)
);

-- 重力モデル変数
CREATE TABLE IF NOT EXISTS gravity_variables(
    source_country TEXT,
    year INT,
    month INT,
    gdp_source_usd FLOAT,
    exchange_rate_jpy FLOAT,
    flight_supply_index FLOAT,
    visa_free BOOLEAN,
    bilateral_risk INT,
    PRIMARY KEY (source_country, year, month)
);
"""


class TourismDB:
    """観光統計DB操作クラス（sqlite3直接使用）"""

    def __init__(self, db_path=None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        # data/ ディレクトリが無ければ作成
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_tables()

    # ========== 初期化 ==========

    def _conn(self):
        """接続を返す（row_factory付き）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        """テーブルが存在しなければ作成"""
        conn = self._conn()
        try:
            conn.executescript(_CREATE_TABLES)
            conn.commit()
        finally:
            conn.close()

    # ========== UPSERT メソッド ==========

    def upsert_outbound(self, records):
        """アウトバウンド統計を一括 upsert

        records: list[dict] — キー:
            source_country, year, month, outbound_total,
            top_destinations (dict/list→JSON化), data_source
        """
        conn = self._conn()
        try:
            for r in records:
                top_dest = r.get("top_destinations")
                if isinstance(top_dest, (dict, list)):
                    top_dest = json.dumps(top_dest, ensure_ascii=False)
                conn.execute(
                    """INSERT INTO outbound_stats
                       (source_country, year, month, outbound_total, top_destinations, data_source, retrieved_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(source_country, year, month) DO UPDATE SET
                           outbound_total=excluded.outbound_total,
                           top_destinations=excluded.top_destinations,
                           data_source=excluded.data_source,
                           retrieved_at=excluded.retrieved_at
                    """,
                    (
                        r["source_country"], r["year"], r.get("month", 0),
                        r.get("outbound_total"), top_dest,
                        r.get("data_source", "hardcoded"),
                        datetime.utcnow().isoformat(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def upsert_inbound(self, records):
        """インバウンド統計（競合含む）を一括 upsert

        records: list[dict] — キー:
            destination, source_country, year, month,
            arrivals, revenue_usd, data_source
        """
        conn = self._conn()
        try:
            for r in records:
                conn.execute(
                    """INSERT INTO inbound_stats
                       (destination, source_country, year, month, arrivals, revenue_usd, data_source, retrieved_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(destination, source_country, year, month) DO UPDATE SET
                           arrivals=excluded.arrivals,
                           revenue_usd=excluded.revenue_usd,
                           data_source=excluded.data_source,
                           retrieved_at=excluded.retrieved_at
                    """,
                    (
                        r["destination"], r.get("source_country", "ALL"),
                        r["year"], r.get("month", 0),
                        r.get("arrivals"), r.get("revenue_usd"),
                        r.get("data_source", "hardcoded"),
                        datetime.utcnow().isoformat(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def upsert_japan_inbound(self, records):
        """日本インバウンド詳細を一括 upsert

        records: list[dict] — キー:
            source_country, year, month, arrivals,
            purpose_leisure_pct, purpose_business_pct,
            avg_stay_days, avg_spend_jpy, data_source
        """
        conn = self._conn()
        try:
            for r in records:
                conn.execute(
                    """INSERT INTO japan_inbound
                       (source_country, year, month, arrivals,
                        purpose_leisure_pct, purpose_business_pct,
                        avg_stay_days, avg_spend_jpy, data_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(source_country, year, month) DO UPDATE SET
                           arrivals=excluded.arrivals,
                           purpose_leisure_pct=excluded.purpose_leisure_pct,
                           purpose_business_pct=excluded.purpose_business_pct,
                           avg_stay_days=excluded.avg_stay_days,
                           avg_spend_jpy=excluded.avg_spend_jpy,
                           data_source=excluded.data_source
                    """,
                    (
                        r["source_country"], r["year"], r.get("month", 0),
                        r.get("arrivals"),
                        r.get("purpose_leisure_pct"),
                        r.get("purpose_business_pct"),
                        r.get("avg_stay_days"),
                        r.get("avg_spend_jpy"),
                        r.get("data_source", "JNTO"),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def upsert_gravity_variables(self, records):
        """重力モデル変数を一括 upsert

        records: list[dict] — キー:
            source_country, year, month,
            gdp_source_usd, exchange_rate_jpy,
            flight_supply_index, visa_free, bilateral_risk
        """
        conn = self._conn()
        try:
            for r in records:
                conn.execute(
                    """INSERT INTO gravity_variables
                       (source_country, year, month,
                        gdp_source_usd, exchange_rate_jpy,
                        flight_supply_index, visa_free, bilateral_risk)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(source_country, year, month) DO UPDATE SET
                           gdp_source_usd=excluded.gdp_source_usd,
                           exchange_rate_jpy=excluded.exchange_rate_jpy,
                           flight_supply_index=excluded.flight_supply_index,
                           visa_free=excluded.visa_free,
                           bilateral_risk=excluded.bilateral_risk
                    """,
                    (
                        r["source_country"], r["year"], r.get("month", 0),
                        r.get("gdp_source_usd"),
                        r.get("exchange_rate_jpy"),
                        r.get("flight_supply_index"),
                        r.get("visa_free"),
                        r.get("bilateral_risk"),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    # ========== 検索メソッド ==========

    def get_outbound(self, country, year=None, month=None):
        """アウトバウンド統計を検索

        Args:
            country: ISO3国コード
            year: 年（Noneなら全年）
            month: 月（Noneなら全月）

        Returns:
            list[dict]
        """
        sql = "SELECT * FROM outbound_stats WHERE source_country = ?"
        params = [country]
        if year is not None:
            sql += " AND year = ?"
            params.append(year)
        if month is not None:
            sql += " AND month = ?"
            params.append(month)
        sql += " ORDER BY year DESC, month DESC"

        conn = self._conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_japan_inbound(self, country=None, year=None, month=None):
        """日本インバウンド詳細を検索

        Args:
            country: ISO3国コード（Noneなら全市場）
            year: 年（Noneなら全年）
            month: 月（Noneなら全月）

        Returns:
            list[dict]
        """
        sql = "SELECT * FROM japan_inbound WHERE 1=1"
        params = []
        if country is not None:
            sql += " AND source_country = ?"
            params.append(country)
        if year is not None:
            sql += " AND year = ?"
            params.append(year)
        if month is not None:
            sql += " AND month = ?"
            params.append(month)
        sql += " ORDER BY year DESC, month DESC, arrivals DESC"

        conn = self._conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_inbound(self, destination=None, source_country=None, year=None):
        """インバウンド統計を検索

        Args:
            destination: デスティネーションISO3（Noneなら全国）
            source_country: 送客元（Noneなら全体）
            year: 年（Noneなら全年）

        Returns:
            list[dict]
        """
        sql = "SELECT * FROM inbound_stats WHERE 1=1"
        params = []
        if destination is not None:
            sql += " AND destination = ?"
            params.append(destination)
        if source_country is not None:
            sql += " AND source_country = ?"
            params.append(source_country)
        if year is not None:
            sql += " AND year = ?"
            params.append(year)
        sql += " ORDER BY year DESC, arrivals DESC"

        conn = self._conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_gravity_variables(self, country=None, year=None):
        """重力モデル変数を検索

        Args:
            country: ISO3国コード（Noneなら全市場）
            year: 年（Noneなら全年）

        Returns:
            list[dict]
        """
        sql = "SELECT * FROM gravity_variables WHERE 1=1"
        params = []
        if country is not None:
            sql += " AND source_country = ?"
            params.append(country)
        if year is not None:
            sql += " AND year = ?"
            params.append(year)
        sql += " ORDER BY year DESC, source_country"

        conn = self._conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_table_counts(self):
        """全テーブルの行数を返す

        Returns:
            dict: {テーブル名: 行数}
        """
        tables = ["outbound_stats", "inbound_stats", "japan_inbound", "gravity_variables"]
        counts = {}
        conn = self._conn()
        try:
            for t in tables:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {t}").fetchone()
                counts[t] = row["cnt"]
        finally:
            conn.close()
        return counts


# --- 便利関数 ---

def get_tourism_db(db_path=None):
    """TourismDBインスタンスを取得（モジュールレベル関数）"""
    return TourismDB(db_path=db_path)
