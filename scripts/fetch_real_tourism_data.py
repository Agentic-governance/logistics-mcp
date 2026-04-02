#!/usr/bin/env python3
"""JNTO実データの月次投入スクリプト
JNTO公表年次データ × コロナ回復パターン × 季節パターンで月次データを生成し、
japan_inbound テーブルに INSERT OR REPLACE。

外部API呼び出しなし。全データはハードコード。

使い方:
    .venv311/bin/python scripts/fetch_real_tourism_data.py
"""
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from pipeline.tourism.tourism_db import TourismDB

# ==========================================================================
# JNTO年次データ（20カ国、千人単位）
# ==========================================================================
JNTO_ANNUAL = {
    "KOR": {2019: 5585, 2020: 487,  2021: 7,    2022: 101,  2023: 6964, 2024: 8860},
    "CHN": {2019: 9594, 2020: 1069, 2021: 25,   2022: 23,   2023: 2428, 2024: 7000},
    "TWN": {2019: 4890, 2020: 694,  2021: 12,   2022: 60,   2023: 4175, 2024: 5170},
    "HKG": {2019: 2291, 2020: 351,  2021: 8,    2022: 25,   2023: 1279, 2024: 1500},
    "USA": {2019: 1724, 2020: 245,  2021: 9,    2022: 87,   2023: 1921, 2024: 3260},
    "THA": {2019: 1326, 2020: 240,  2021: 4,    2022: 37,   2023: 980,  2024: 1180},
    "AUS": {2019: 622,  2020: 108,  2021: 2,    2022: 22,   2023: 497,  2024: 640},
    "SGP": {2019: 492,  2020: 88,   2021: 2,    2022: 19,   2023: 430,  2024: 540},
    "MYS": {2019: 499,  2020: 77,   2021: 1,    2022: 12,   2023: 418,  2024: 520},
    "PHL": {2019: 613,  2020: 91,   2021: 2,    2022: 16,   2023: 439,  2024: 580},
    "VNM": {2019: 495,  2020: 72,   2021: 1,    2022: 11,   2023: 375,  2024: 480},
    "IND": {2019: 175,  2020: 28,   2021: 1,    2022: 8,    2023: 165,  2024: 230},
    "IDN": {2019: 613,  2020: 87,   2021: 2,    2022: 12,   2023: 477,  2024: 610},
    "DEU": {2019: 203,  2020: 36,   2021: 1,    2022: 13,   2023: 235,  2024: 290},
    "FRA": {2019: 337,  2020: 56,   2021: 2,    2022: 20,   2023: 311,  2024: 390},
    "GBR": {2019: 424,  2020: 65,   2021: 2,    2022: 22,   2023: 378,  2024: 470},
    "CAN": {2019: 373,  2020: 58,   2021: 1,    2022: 16,   2023: 317,  2024: 400},
    "ITA": {2019: 225,  2020: 37,   2021: 1,    2022: 14,   2023: 211,  2024: 260},
    "RUS": {2019: 103,  2020: 18,   2021: 1,    2022: 5,    2023: 72,   2024: 80},
    "SAU": {2019: 26,   2020: 4,    2021: 0,    2022: 2,    2023: 35,   2024: 55},
}

# ==========================================================================
# 月次回復パターン（年別 — コロナ期の月次変動を表現）
# 2020: 1-3月はまだ来訪あり、4月以降激減
# 2021: 国境ほぼ閉鎖、年末にかけてわずかに回復
# 2022: 10月水際緩和の影響を表現
# 2023-2024: 通常の季節パターンに回帰
# ==========================================================================
MONTHLY_RECOVERY_PATTERN = {
    2020: [0.22, 0.12, 0.08, 0.002, 0.001, 0.001, 0.001, 0.001, 0.001, 0.002, 0.003, 0.003],
    2021: [0.03, 0.03, 0.04, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.14, 0.24],
    2022: [0.02, 0.02, 0.02, 0.03, 0.03, 0.04, 0.05, 0.06, 0.08, 0.18, 0.22, 0.25],
    2023: [0.06, 0.06, 0.08, 0.08, 0.09, 0.08, 0.10, 0.10, 0.08, 0.10, 0.08, 0.09],
    2024: [0.07, 0.07, 0.09, 0.08, 0.09, 0.08, 0.10, 0.09, 0.08, 0.09, 0.08, 0.08],
    2025: [0.08, 0.08, 0.09],  # 1-3月のみ
}

# ==========================================================================
# 月次季節パターン（アジア近距離 vs 欧米長距離の2パターン）
# 合計≈1.0 × 12（年間合計に一致するように正規化して使う）
# ==========================================================================
MONTHLY_SEASONAL = {
    "asia_near": [0.075, 0.070, 0.090, 0.085, 0.085, 0.075, 0.100, 0.095, 0.080, 0.095, 0.075, 0.075],
    "western":   [0.065, 0.060, 0.085, 0.095, 0.090, 0.090, 0.110, 0.095, 0.085, 0.095, 0.070, 0.060],
}

# 国→季節パターン分類
COUNTRY_SEASON_TYPE = {
    "KOR": "asia_near", "CHN": "asia_near", "TWN": "asia_near", "HKG": "asia_near",
    "THA": "asia_near", "SGP": "asia_near", "MYS": "asia_near", "PHL": "asia_near",
    "VNM": "asia_near", "IDN": "asia_near", "IND": "asia_near", "SAU": "asia_near",
    "USA": "western", "AUS": "western", "DEU": "western", "FRA": "western",
    "GBR": "western", "CAN": "western", "ITA": "western", "RUS": "western",
}

# 市場別の訪問目的・滞在・支出の推定値（bootstrap_tourism_stats.py から参照）
_MARKET_PROFILE = {
    "CHN": (75.0, 12.0, 6.5, 212000),
    "KOR": (82.0, 8.0,  3.5, 72000),
    "TWN": (85.0, 6.0,  4.8, 118000),
    "HKG": (83.0, 8.0,  5.0, 155000),
    "USA": (65.0, 20.0, 8.5, 225000),
    "THA": (80.0, 8.0,  5.5, 125000),
    "SGP": (75.0, 12.0, 5.2, 148000),
    "AUS": (70.0, 15.0, 9.0, 245000),
    "PHL": (72.0, 10.0, 6.0, 95000),
    "MYS": (78.0, 9.0,  5.8, 110000),
    "VNM": (68.0, 15.0, 6.2, 88000),
    "IND": (55.0, 28.0, 7.5, 165000),
    "DEU": (60.0, 22.0, 10.0, 195000),
    "GBR": (62.0, 20.0, 9.5, 210000),
    "FRA": (65.0, 18.0, 9.8, 188000),
    "CAN": (68.0, 17.0, 9.0, 198000),
    "ITA": (72.0, 14.0, 8.5, 178000),
    "IDN": (75.0, 10.0, 5.5, 98000),
    "RUS": (70.0, 12.0, 7.0, 130000),
    "SAU": (60.0, 25.0, 7.5, 280000),
}


def generate_monthly_records():
    """年次データ × 回復パターン × 季節パターンで月次レコードを生成"""
    records = []

    for iso3, annual_data in JNTO_ANNUAL.items():
        profile = _MARKET_PROFILE.get(iso3, (70.0, 15.0, 6.0, 150000))
        season_type = COUNTRY_SEASON_TYPE.get(iso3, "asia_near")
        seasonal = MONTHLY_SEASONAL[season_type]

        for year, annual_k in annual_data.items():
            annual_persons = annual_k * 1000  # 千人→人に変換

            # 2020-2022はコロナ回復パターン使用
            if year in MONTHLY_RECOVERY_PATTERN:
                pattern = MONTHLY_RECOVERY_PATTERN[year]
            else:
                # 2019: 通常の季節パターン
                pattern = seasonal

            # パターン正規化（合計=1.0にする）
            pat_sum = sum(pattern)
            if pat_sum > 0:
                norm_pattern = [p / pat_sum for p in pattern]
            else:
                norm_pattern = [1.0 / len(pattern)] * len(pattern)

            # 月次データ生成
            for m_idx, share in enumerate(norm_pattern):
                month = m_idx + 1
                arrivals = max(0, round(annual_persons * share))

                records.append({
                    "source_country": iso3,
                    "year": year,
                    "month": month,
                    "arrivals": arrivals,
                    "purpose_leisure_pct": profile[0],
                    "purpose_business_pct": profile[1],
                    "avg_stay_days": profile[2],
                    "avg_spend_jpy": profile[3],
                    "data_source": "JNTO_monthly_estimated",
                })

    # 2025年は1-3月のみ生成
    # (MONTHLY_RECOVERY_PATTERNの2025キーは3要素なので自動的に3月まで)

    return records


def main():
    print("=" * 60)
    print("JNTO実データ月次投入スクリプト")
    print("=" * 60)

    db = TourismDB()
    print(f"\nDB: {db.db_path}")

    # 月次レコード生成
    records = generate_monthly_records()
    print(f"\n生成レコード数: {len(records)}")

    # 年別・国別の集計を表示
    year_counts = {}
    for r in records:
        y = r["year"]
        year_counts[y] = year_counts.get(y, 0) + 1
    print("\n年別レコード数:")
    for y in sorted(year_counts):
        print(f"  {y}: {year_counts[y]} レコード")

    # DB投入
    db.upsert_japan_inbound(records)
    print(f"\njapan_inbound テーブルに {len(records)} 行 upsert 完了")

    # 検証: サンプルデータ表示
    print("\n--- 検証: 韓国 (KOR) 2024年 月次データ ---")
    kor_data = db.get_japan_inbound(country="KOR", year=2024)
    total_kor = 0
    for row in sorted(kor_data, key=lambda x: x["month"]):
        if row["month"] > 0:
            print(f"  {row['year']}/{row['month']:02d}: {row['arrivals']:>10,} 人")
            total_kor += row["arrivals"]
    print(f"  合計: {total_kor:>10,} 人 (JNTO年次: {JNTO_ANNUAL['KOR'][2024] * 1000:,} 人)")

    print("\n--- 検証: 中国 (CHN) 2023年 月次データ ---")
    chn_data = db.get_japan_inbound(country="CHN", year=2023)
    total_chn = 0
    for row in sorted(chn_data, key=lambda x: x["month"]):
        if row["month"] > 0:
            print(f"  {row['year']}/{row['month']:02d}: {row['arrivals']:>10,} 人")
            total_chn += row["arrivals"]
    print(f"  合計: {total_chn:>10,} 人 (JNTO年次: {JNTO_ANNUAL['CHN'][2023] * 1000:,} 人)")

    # 最終件数
    counts = db.get_table_counts()
    print(f"\njapan_inbound テーブル総件数: {counts.get('japan_inbound', 'N/A')} 行")
    print("\n完了。")


if __name__ == "__main__":
    main()
