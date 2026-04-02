"""時系列DBセットアップスクリプト
SQLite DBを初期化し、必要なテーブルを作成する。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.timeseries.store import RiskTimeSeriesStore


def main():
    db_path = os.environ.get("TIMESERIES_DB_PATH", "./data/timeseries.db")
    print(f"Initializing timeseries DB at: {db_path}")

    store = RiskTimeSeriesStore(db_path=db_path)
    print("Tables created successfully:")
    print("  - risk_scores")
    print("  - risk_summaries")
    print()

    # Verify
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    conn.close()

    print(f"Verified {len(tables)} tables: {[t[0] for t in tables]}")
    print("Done.")


if __name__ == "__main__":
    main()
