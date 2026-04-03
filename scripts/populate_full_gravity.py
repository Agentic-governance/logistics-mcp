#!/usr/bin/env python3
"""gravity_variables テーブル拡張スクリプト — SCRI v1.5.0

経済・余暇・文化的関心変数を収集し、gravity_variables テーブルに新カラムを追加・投入。

追加カラム:
  gdp_per_capita_ppp, consumer_confidence, unemployment_rate,
  annual_leave_days, leave_utilization_rate, annual_working_hours,
  remote_work_rate, language_learners, restaurant_count,
  japan_travel_trend, travel_momentum_index, outbound_total

TMI計算:
  (leave_utilization_rate + remote_work_rate*2 + (1 - unemployment_rate/15)) / 3

使い方:
    .venv311/bin/python scripts/populate_full_gravity.py
"""
import os
import sqlite3
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from pipeline.tourism.tourism_db import TourismDB
from pipeline.tourism.economic_leisure_client import EconomicLeisureClient, TARGET_COUNTRIES as ECON_COUNTRIES
from pipeline.tourism.cultural_interest_client import CulturalInterestClient

# ==========================================================================
# 新規カラム定義
# ==========================================================================
NEW_COLUMNS = {
    "gdp_per_capita_ppp": "FLOAT",
    "consumer_confidence": "FLOAT",
    "unemployment_rate": "FLOAT",
    "annual_leave_days": "INT",
    "leave_utilization_rate": "FLOAT",
    "annual_working_hours": "INT",
    "remote_work_rate": "FLOAT",
    "language_learners": "INT",
    "restaurant_count": "INT",
    "japan_travel_trend": "FLOAT",
    "travel_momentum_index": "FLOAT",
    "outbound_total": "INT",
}

# ISO2→ISO3マッピング（gravity_variablesはISO3を使用）
ISO2_TO_ISO3 = {
    "KR": "KOR", "CN": "CHN", "TW": "TWN", "US": "USA",
    "AU": "AUS", "TH": "THA", "HK": "HKG", "SG": "SGP",
    "DE": "DEU", "FR": "FRA", "GB": "GBR", "IN": "IND",
}

# アウトバウンド旅行者数推計（2024年、百万人 → 人数）
OUTBOUND_ESTIMATES_2024 = {
    "KOR": 28_500_000,
    "CHN": 130_000_000,
    "TWN": 17_000_000,
    "USA": 93_000_000,
    "AUS": 12_500_000,
    "THA": 12_000_000,
    "HKG": 8_500_000,
    "SGP": 9_200_000,
    "DEU": 75_000_000,
    "FRA": 28_000_000,
    "GBR": 68_000_000,
    "IND": 28_000_000,
}


def ensure_new_columns(db_path):
    """gravity_variables テーブルに不足カラムを ALTER TABLE ADD COLUMN で追加"""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("PRAGMA table_info(gravity_variables)")
        existing = {row[1] for row in cur.fetchall()}

        added = []
        for col_name, col_type in NEW_COLUMNS.items():
            if col_name not in existing:
                conn.execute(f"ALTER TABLE gravity_variables ADD COLUMN {col_name} {col_type}")
                added.append(col_name)

        conn.commit()
        if added:
            print(f"  追加カラム ({len(added)}): {', '.join(added)}")
        else:
            print("  全カラム既存 — スキップ")
    finally:
        conn.close()


def calculate_tmi(leave_util, remote_work, unemployment):
    """Travel Momentum Index (TMI) を計算

    TMI = (leave_utilization + remote_work*2 + (1 - unemployment/15)) / 3

    Args:
        leave_util: 有給取得率 (0-1)
        remote_work: リモートワーク率 (0-1)
        unemployment: 失業率 (%)

    Returns:
        TMI (0-1スケール、高いほど旅行ポテンシャル大)
    """
    if leave_util is None or remote_work is None or unemployment is None:
        return None

    unemp_factor = max(0, 1.0 - unemployment / 15.0)
    tmi = (leave_util + remote_work * 2 + unemp_factor) / 3.0
    return round(tmi, 4)


def main():
    print("=" * 60)
    print("gravity_variables テーブル拡張 — SCRI v1.5.0")
    print("=" * 60)

    db = TourismDB()
    print(f"\nDB: {db.db_path}")

    # 1) カラム追加
    print("\n[1/4] カラム追加...")
    ensure_new_columns(db.db_path)

    # 2) 経済・余暇データ収集
    print("\n[2/4] 経済・余暇データ収集...")
    econ_client = EconomicLeisureClient()
    econ_data = {}
    for iso2 in ECON_COUNTRIES:
        try:
            data = econ_client.collect_all_for_country(iso2)
            econ_data[iso2] = data
            src = data.get("data_sources", {})
            gdp_src = src.get("gdp_per_capita_ppp", "?")
            cci_src = src.get("consumer_confidence", "?")
            print(f"  {iso2}: GDP={data.get('gdp_per_capita_ppp'):.0f} ({gdp_src}), "
                  f"CCI={data.get('consumer_confidence')} ({cci_src}), "
                  f"Unemp={data.get('unemployment_rate')}%")
        except Exception as e:
            print(f"  {iso2}: エラー — {e}")

    # 3) 文化的関心データ収集
    print("\n[3/4] 文化的関心データ収集...")
    cultural_client = CulturalInterestClient()
    cultural_data = {}
    for iso2 in ECON_COUNTRIES:
        try:
            data = cultural_client.collect_cultural_interest(iso2)
            cultural_data[iso2] = data
            print(f"  {iso2}: 学習者={data.get('language_learners'):,}, "
                  f"レストラン={data.get('restaurant_count'):,}, "
                  f"Trends={data.get('japan_travel_trend')}")
        except Exception as e:
            print(f"  {iso2}: エラー — {e}")

    # 4) DB投入
    print("\n[4/4] DB投入...")
    conn = sqlite3.connect(db.db_path)
    upsert_count = 0
    try:
        for iso2 in ECON_COUNTRIES:
            iso3 = ISO2_TO_ISO3.get(iso2, iso2)
            econ = econ_data.get(iso2, {})
            cultural = cultural_data.get(iso2, {})

            # TMI計算
            tmi = calculate_tmi(
                econ.get("leave_utilization_rate"),
                econ.get("remote_work_rate"),
                econ.get("unemployment_rate"),
            )

            outbound = OUTBOUND_ESTIMATES_2024.get(iso3)

            # 2024年のレコードを更新（既存行がなければINSERT）
            year = 2024
            month = 0

            # まず既存レコードの有無を確認
            row = conn.execute(
                "SELECT source_country FROM gravity_variables WHERE source_country=? AND year=? AND month=?",
                (iso3, year, month)
            ).fetchone()

            if row:
                # UPDATE
                conn.execute(
                    """UPDATE gravity_variables SET
                        gdp_per_capita_ppp=?, consumer_confidence=?, unemployment_rate=?,
                        annual_leave_days=?, leave_utilization_rate=?, annual_working_hours=?,
                        remote_work_rate=?, language_learners=?, restaurant_count=?,
                        japan_travel_trend=?, travel_momentum_index=?, outbound_total=?
                    WHERE source_country=? AND year=? AND month=?""",
                    (
                        econ.get("gdp_per_capita_ppp"),
                        econ.get("consumer_confidence"),
                        econ.get("unemployment_rate"),
                        econ.get("annual_leave_days"),
                        econ.get("leave_utilization_rate"),
                        econ.get("annual_working_hours"),
                        econ.get("remote_work_rate"),
                        cultural.get("language_learners"),
                        cultural.get("restaurant_count"),
                        cultural.get("japan_travel_trend"),
                        tmi,
                        outbound,
                        iso3, year, month,
                    ),
                )
            else:
                # INSERT（最低限のカラムで新規行作成）
                conn.execute(
                    """INSERT INTO gravity_variables
                       (source_country, year, month,
                        gdp_per_capita_ppp, consumer_confidence, unemployment_rate,
                        annual_leave_days, leave_utilization_rate, annual_working_hours,
                        remote_work_rate, language_learners, restaurant_count,
                        japan_travel_trend, travel_momentum_index, outbound_total)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        iso3, year, month,
                        econ.get("gdp_per_capita_ppp"),
                        econ.get("consumer_confidence"),
                        econ.get("unemployment_rate"),
                        econ.get("annual_leave_days"),
                        econ.get("leave_utilization_rate"),
                        econ.get("annual_working_hours"),
                        econ.get("remote_work_rate"),
                        cultural.get("language_learners"),
                        cultural.get("restaurant_count"),
                        cultural.get("japan_travel_trend"),
                        tmi,
                        outbound,
                    ),
                )
            upsert_count += 1

        conn.commit()
    finally:
        conn.close()

    print(f"\n  {upsert_count} カ国のデータを投入完了")

    # 検証
    print("\n" + "=" * 60)
    print("検証")
    print("=" * 60)
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT source_country, gdp_per_capita_ppp, consumer_confidence,
                      unemployment_rate, annual_leave_days, leave_utilization_rate,
                      remote_work_rate, language_learners, restaurant_count,
                      travel_momentum_index, outbound_total
               FROM gravity_variables
               WHERE year=2024 AND month=0
                 AND gdp_per_capita_ppp IS NOT NULL
               ORDER BY source_country"""
        ).fetchall()

        print(f"\n{'国':>5} {'GDP/PPP':>10} {'CCI':>6} {'失業率':>6} {'有給':>4} {'取得率':>6} "
              f"{'Remote':>7} {'学習者':>10} {'レストラン':>10} {'TMI':>6} {'出国者':>12}")
        print("-" * 100)
        for r in rows:
            print(f"{r['source_country']:>5} "
                  f"{r['gdp_per_capita_ppp']:>10,.0f} "
                  f"{r['consumer_confidence'] or 0:>6.1f} "
                  f"{r['unemployment_rate'] or 0:>6.1f} "
                  f"{r['annual_leave_days'] or 0:>4d} "
                  f"{(r['leave_utilization_rate'] or 0):>6.2f} "
                  f"{(r['remote_work_rate'] or 0):>7.2f} "
                  f"{(r['language_learners'] or 0):>10,d} "
                  f"{(r['restaurant_count'] or 0):>10,d} "
                  f"{(r['travel_momentum_index'] or 0):>6.3f} "
                  f"{(r['outbound_total'] or 0):>12,d}")

        # 全テーブル件数
        tables = ["outbound_stats", "inbound_stats", "japan_inbound", "gravity_variables"]
        print(f"\n--- テーブル件数 ---")
        for t in tables:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {cnt} 行")

        # gravity_variablesのカラム一覧
        cols = conn.execute("PRAGMA table_info(gravity_variables)").fetchall()
        print(f"\ngravity_variables カラム ({len(cols)}):")
        for c in cols:
            print(f"  {c['name']:>30} {c['type']}")

    finally:
        conn.close()

    print("\n完了。")


if __name__ == "__main__":
    main()
