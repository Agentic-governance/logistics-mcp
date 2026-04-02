#!/usr/bin/env python3
"""重力モデル変数の補完スクリプト
20カ国 × 2019-2025の年次データを生成し、gravity_variables テーブルに投入。

GDP成長率調整、COVID期フライト調整を適用。
tfi列がなければ ALTER TABLE ADD COLUMN。

外部API呼び出しなし。全データはハードコード。

使い方:
    .venv311/bin/python scripts/populate_gravity_variables.py
"""
import os
import sqlite3
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from pipeline.tourism.tourism_db import TourismDB

# ==========================================================================
# 2024年ベースデータ（20カ国）
# gdp: 十億USD, pop_m: 百万人, distance_km: 東京からの距離
# flight_idx_2024: 航空供給指数(2019=100), exr_jpy: 対円レート
# visa_free: ビザ免除, bilateral_risk: 二国間リスク(0-100)
# tfi: Trade Facilitation Index (0-2, WTO)
# ==========================================================================
GRAVITY_VARS_2024 = {
    "KOR": {"gdp": 1780, "pop_m": 51.7, "distance_km": 1160, "flight_idx": 105, "exr_jpy": 0.112, "visa_free": True, "bilateral_risk": 15, "tfi": 1.72},
    "CHN": {"gdp": 18300, "pop_m": 1412, "distance_km": 2100, "flight_idx": 85, "exr_jpy": 21.0, "visa_free": False, "bilateral_risk": 45, "tfi": 1.45},
    "TWN": {"gdp": 820, "pop_m": 23.6, "distance_km": 2100, "flight_idx": 95, "exr_jpy": 4.70, "visa_free": True, "bilateral_risk": 12, "tfi": 1.65},
    "HKG": {"gdp": 398, "pop_m": 7.5, "distance_km": 2900, "flight_idx": 95, "exr_jpy": 19.3, "visa_free": True, "bilateral_risk": 18, "tfi": 1.85},
    "USA": {"gdp": 28800, "pop_m": 335, "distance_km": 10850, "flight_idx": 95, "exr_jpy": 0.0066, "visa_free": True, "bilateral_risk": 10, "tfi": 1.74},
    "THA": {"gdp": 540, "pop_m": 72, "distance_km": 4600, "flight_idx": 90, "exr_jpy": 4.20, "visa_free": True, "bilateral_risk": 8, "tfi": 1.52},
    "AUS": {"gdp": 1750, "pop_m": 26.5, "distance_km": 7820, "flight_idx": 88, "exr_jpy": 99.0, "visa_free": True, "bilateral_risk": 8, "tfi": 1.78},
    "SGP": {"gdp": 490, "pop_m": 5.9, "distance_km": 5310, "flight_idx": 95, "exr_jpy": 112, "visa_free": True, "bilateral_risk": 5, "tfi": 1.92},
    "MYS": {"gdp": 420, "pop_m": 34, "distance_km": 5300, "flight_idx": 82, "exr_jpy": 32.0, "visa_free": True, "bilateral_risk": 8, "tfi": 1.55},
    "PHL": {"gdp": 465, "pop_m": 117, "distance_km": 3000, "flight_idx": 85, "exr_jpy": 2.70, "visa_free": True, "bilateral_risk": 12, "tfi": 1.35},
    "VNM": {"gdp": 460, "pop_m": 100, "distance_km": 3600, "flight_idx": 92, "exr_jpy": 0.0060, "visa_free": True, "bilateral_risk": 10, "tfi": 1.30},
    "IND": {"gdp": 3800, "pop_m": 1440, "distance_km": 5850, "flight_idx": 100, "exr_jpy": 1.80, "visa_free": False, "bilateral_risk": 15, "tfi": 1.28},
    "IDN": {"gdp": 1420, "pop_m": 277, "distance_km": 5800, "flight_idx": 88, "exr_jpy": 0.0095, "visa_free": True, "bilateral_risk": 10, "tfi": 1.38},
    "DEU": {"gdp": 4600, "pop_m": 84, "distance_km": 9350, "flight_idx": 90, "exr_jpy": 163, "visa_free": True, "bilateral_risk": 5, "tfi": 1.82},
    "FRA": {"gdp": 3150, "pop_m": 68, "distance_km": 9720, "flight_idx": 85, "exr_jpy": 163, "visa_free": True, "bilateral_risk": 5, "tfi": 1.68},
    "GBR": {"gdp": 3450, "pop_m": 68, "distance_km": 9560, "flight_idx": 88, "exr_jpy": 190, "visa_free": True, "bilateral_risk": 5, "tfi": 1.80},
    "CAN": {"gdp": 2140, "pop_m": 40, "distance_km": 10350, "flight_idx": 85, "exr_jpy": 110, "visa_free": True, "bilateral_risk": 5, "tfi": 1.76},
    "ITA": {"gdp": 2250, "pop_m": 59, "distance_km": 9850, "flight_idx": 82, "exr_jpy": 163, "visa_free": True, "bilateral_risk": 5, "tfi": 1.58},
    "RUS": {"gdp": 1860, "pop_m": 144, "distance_km": 7480, "flight_idx": 15, "exr_jpy": 1.60, "visa_free": False, "bilateral_risk": 65, "tfi": 1.18},
    "SAU": {"gdp": 1069, "pop_m": 36, "distance_km": 8800, "flight_idx": 60, "exr_jpy": 40.0, "visa_free": False, "bilateral_risk": 20, "tfi": 1.40},
}

# ==========================================================================
# GDP成長率（年次変動推定、2019=ベース）
# ==========================================================================
GDP_GROWTH_FACTORS = {
    # year: factor relative to 2024
    2019: 0.88,  # 2019→2024の平均年成長を逆算
    2020: 0.82,  # コロナショック
    2021: 0.85,  # 回復途上
    2022: 0.92,  # 回復
    2023: 0.96,  # 回復
    2024: 1.00,
    2025: 1.03,  # 見込み
}

# ==========================================================================
# COVID期フライト調整（2019=100ベース）
# ==========================================================================
FLIGHT_COVID_FACTORS = {
    # year: multiplier relative to 2024 flight_idx
    2019: 1.05,   # 2019は2024比やや高い（パンデミック前フル稼働）
    2020: 0.15,   # 激減
    2021: 0.08,   # 最低
    2022: 0.35,   # 回復開始
    2023: 0.82,   # 大幅回復
    2024: 1.00,
    2025: 1.05,   # 完全回復+新規路線
}

# USD/JPY 年間平均レート
USDJPY_ANNUAL = {
    2019: 109.0,
    2020: 106.8,
    2021: 109.8,
    2022: 131.5,
    2023: 140.5,
    2024: 151.0,
    2025: 148.0,
}


def _ensure_tfi_column(db):
    """gravity_variables テーブルに tfi 列がなければ追加"""
    conn = sqlite3.connect(db.db_path)
    try:
        cur = conn.execute("PRAGMA table_info(gravity_variables)")
        columns = [row[1] for row in cur.fetchall()]
        if "tfi" not in columns:
            conn.execute("ALTER TABLE gravity_variables ADD COLUMN tfi FLOAT")
            conn.commit()
            print("  gravity_variables テーブルに tfi 列を追加しました")
        else:
            print("  tfi 列は既に存在します")
    finally:
        conn.close()


def generate_gravity_records():
    """2019-2025の年次重力変数レコードを生成"""
    records = []
    years = [2019, 2020, 2021, 2022, 2023, 2024, 2025]

    for iso3, base in GRAVITY_VARS_2024.items():
        for year in years:
            gdp_factor = GDP_GROWTH_FACTORS.get(year, 1.0)
            flight_factor = FLIGHT_COVID_FACTORS.get(year, 1.0)
            usdjpy = USDJPY_ANNUAL.get(year, 151.0)

            # GDP調整
            gdp_usd = base["gdp"] * gdp_factor * 1e9  # 十億USD → USD

            # フライト指数調整
            flight_idx = base["flight_idx"] * flight_factor

            # 為替レート（exr_jpyはソース通貨/JPYの概算 — USDBJPYから比例調整）
            exr_jpy = usdjpy * base["exr_jpy"]  # 概算

            records.append({
                "source_country": iso3,
                "year": year,
                "month": 0,  # 年次データ
                "gdp_source_usd": gdp_usd,
                "exchange_rate_jpy": exr_jpy,
                "flight_supply_index": round(flight_idx, 1),
                "visa_free": base["visa_free"],
                "bilateral_risk": base["bilateral_risk"],
                "tfi": base["tfi"],
            })

    return records


def main():
    print("=" * 60)
    print("重力モデル変数補完スクリプト")
    print("=" * 60)

    db = TourismDB()
    print(f"\nDB: {db.db_path}")

    # tfi列追加
    _ensure_tfi_column(db)

    # レコード生成
    records = generate_gravity_records()
    print(f"\n生成レコード数: {len(records)} (20カ国 × 7年)")

    # DB投入（tfi列を含むカスタムupsert）
    conn = sqlite3.connect(db.db_path)
    try:
        for r in records:
            conn.execute(
                """INSERT INTO gravity_variables
                   (source_country, year, month,
                    gdp_source_usd, exchange_rate_jpy,
                    flight_supply_index, visa_free, bilateral_risk, tfi)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_country, year, month) DO UPDATE SET
                       gdp_source_usd=excluded.gdp_source_usd,
                       exchange_rate_jpy=excluded.exchange_rate_jpy,
                       flight_supply_index=excluded.flight_supply_index,
                       visa_free=excluded.visa_free,
                       bilateral_risk=excluded.bilateral_risk,
                       tfi=excluded.tfi
                """,
                (
                    r["source_country"], r["year"], r.get("month", 0),
                    r["gdp_source_usd"], r["exchange_rate_jpy"],
                    r["flight_supply_index"], r["visa_free"],
                    r["bilateral_risk"], r.get("tfi"),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"gravity_variables テーブルに {len(records)} 行 upsert 完了")

    # 検証
    print("\n--- 検証: 韓国 (KOR) 全年次データ ---")
    kor = db.get_gravity_variables(country="KOR")
    for row in sorted(kor, key=lambda x: x["year"]):
        gdp_b = row["gdp_source_usd"] / 1e9
        print(f"  {row['year']}: GDP=${gdp_b:.0f}B  EXR={row['exchange_rate_jpy']:.1f}  "
              f"Flight={row['flight_supply_index']:.0f}  Visa={'Y' if row['visa_free'] else 'N'}  "
              f"Risk={row['bilateral_risk']}")

    # 最終件数
    counts = db.get_table_counts()
    print(f"\ngravity_variables テーブル総件数: {counts.get('gravity_variables', 'N/A')} 行")
    print("\n完了。")


if __name__ == "__main__":
    main()
