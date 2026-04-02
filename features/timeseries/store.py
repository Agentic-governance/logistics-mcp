"""リスクスコア時系列ストレージ
SQLiteバックエンド（デフォルト）
"""
import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

DEFAULT_DB_PATH = os.getenv("SQLITE_DB_PATH", "data/timeseries.db")

class RiskTimeSeriesStore:
    """リスクスコアの時系列保存・取得"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "data", exist_ok=True)
        self._init_db()

    def _init_db(self):
        """DBスキーマ初期化"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    location TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    overall_score REAL,
                    dimension TEXT,
                    score REAL,
                    data_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_location_timestamp ON risk_scores(location, timestamp)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    location TEXT NOT NULL,
                    date TEXT NOT NULL,
                    overall_score REAL,
                    scores_json TEXT,
                    evidence_count INTEGER,
                    UNIQUE(location, date)
                )
            """)
            conn.commit()

    def store_score(self, location: str, score_dict: dict, timestamp: Optional[datetime] = None):
        """スコアを保存"""
        ts = timestamp or datetime.utcnow()
        with sqlite3.connect(self.db_path) as conn:
            # Store overall score
            conn.execute(
                "INSERT INTO risk_scores (location, timestamp, overall_score, dimension, score, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                (location, ts.isoformat(), score_dict.get("overall_score", 0), "overall",
                 score_dict.get("overall_score", 0), json.dumps(score_dict, default=str))
            )
            # Store each dimension
            for dim, val in score_dict.get("scores", {}).items():
                if val > 0:
                    conn.execute(
                        "INSERT INTO risk_scores (location, timestamp, overall_score, dimension, score, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                        (location, ts.isoformat(), score_dict.get("overall_score", 0), dim, val, None)
                    )
            conn.commit()

    def get_history(self, location: str, start_date: str, end_date: str, dimensions: list = None) -> list:
        """指定期間のスコア履歴を取得"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM risk_scores WHERE location = ? AND timestamp >= ? AND timestamp <= ?"
            params = [location, start_date, end_date]
            if dimensions:
                placeholders = ",".join("?" * len(dimensions))
                query += f" AND dimension IN ({placeholders})"
                params.extend(dimensions)
            query += " ORDER BY timestamp ASC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_latest(self, location: str) -> dict:
        """最新スコアを取得"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM risk_scores WHERE location = ? AND dimension = 'overall' ORDER BY timestamp DESC LIMIT 1",
                (location,)
            ).fetchone()
            if row:
                result = dict(row)
                if result.get("data_json"):
                    result["data"] = json.loads(result["data_json"])
                return result
            return {}

    def store_daily_summary(self, location: str, score_dict: dict, date: str = None):
        """日次サマリーを保存"""
        d = date or datetime.utcnow().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO risk_summaries (location, date, overall_score, scores_json, evidence_count) VALUES (?, ?, ?, ?, ?)",
                (location, d, score_dict.get("overall_score", 0),
                 json.dumps(score_dict.get("scores", {})),
                 len(score_dict.get("evidence", [])))
            )
            conn.commit()
