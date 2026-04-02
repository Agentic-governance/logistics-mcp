#!/usr/bin/env python3
"""観光統計DB初期データ取込スクリプト
過去5年分（2021-2025）のハードコードデータを一括投入。
外部API呼び出しなし — 全データは各クライアントの内蔵データから構成。

使い方:
    .venv311/bin/python scripts/bootstrap_tourism_stats.py
"""
import json
import os
import sys

# プロジェクトルートをパスに追加
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from pipeline.tourism.tourism_db import TourismDB

# ========== 定数 ==========

YEARS = [2021, 2022, 2023, 2024, 2025]

# ========== 1. JNTO 日本インバウンド — 20市場×5年 ==========
# データソース: pipeline/tourism/jnto_client.py HISTORICAL_DATA
# 年間値を年次レコード（month=0）として格納
# purpose/stay/spend は市場特性に基づく推定値

_JNTO_ANNUAL = {
    "CHN": {"2021": 24300,   "2022": 189400,  "2023": 2425900, "2024": 6962800, "2025": 7800000},
    "KOR": {"2021": 37200,   "2022": 1012600, "2023": 6958500, "2024": 8818500, "2025": 9200000},
    "TWN": {"2021": 15800,   "2022": 331200,  "2023": 4202400, "2024": 5364600, "2025": 5600000},
    "HKG": {"2021": 8900,    "2022": 253600,  "2023": 2114100, "2024": 2596600, "2025": 2800000},
    "USA": {"2021": 63800,   "2022": 632200,  "2023": 2045800, "2024": 2529700, "2025": 2700000},
    "THA": {"2021": 5100,    "2022": 168300,  "2023": 990200,  "2024": 1105400, "2025": 1200000},
    "SGP": {"2021": 3200,    "2022": 132500,  "2023": 568400,  "2024": 708900,  "2025": 780000},
    "AUS": {"2021": 8200,    "2022": 175600,  "2023": 601200,  "2024": 782600,  "2025": 850000},
    "PHL": {"2021": 4800,    "2022": 110300,  "2023": 622200,  "2024": 801500,  "2025": 880000},
    "MYS": {"2021": 3400,    "2022": 85600,   "2023": 412300,  "2024": 523500,  "2025": 570000},
    "VNM": {"2021": 5600,    "2022": 98700,   "2023": 478900,  "2024": 614600,  "2025": 680000},
    "IND": {"2021": 8100,    "2022": 52300,   "2023": 203700,  "2024": 267900,  "2025": 310000},
    "DEU": {"2021": 9500,    "2022": 68400,   "2023": 254600,  "2024": 321000,  "2025": 350000},
    "GBR": {"2021": 12200,   "2022": 98700,   "2023": 358200,  "2024": 470300,  "2025": 510000},
    "FRA": {"2021": 8600,    "2022": 72100,   "2023": 303800,  "2024": 395200,  "2025": 430000},
    "CAN": {"2021": 10500,   "2022": 85200,   "2023": 318400,  "2024": 408800,  "2025": 440000},
    "ITA": {"2021": 5200,    "2022": 48600,   "2023": 181200,  "2024": 236500,  "2025": 260000},
    "IDN": {"2021": 3900,    "2022": 72800,   "2023": 315700,  "2024": 412800,  "2025": 450000},
    "RUS": {"2021": 3200,    "2022": 5400,    "2023": 18600,   "2024": 25000,   "2025": 30000},
    "ESP": {"2021": 4100,    "2022": 35200,   "2023": 137800,  "2024": 178200,  "2025": 195000},
}

# 市場別の訪問目的・滞在・支出の推定値
# leisure_pct, business_pct, avg_stay_days, avg_spend_jpy
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
    "ESP": (73.0, 12.0, 8.0, 172000),
}


def _build_japan_inbound_records():
    """JNTO日本インバウンドレコードを生成（20市場×5年=100行）"""
    records = []
    for iso3, annual in _JNTO_ANNUAL.items():
        profile = _MARKET_PROFILE.get(iso3, (70.0, 15.0, 6.0, 150000))
        for yr in YEARS:
            arrivals = annual.get(str(yr))
            if arrivals is None:
                continue
            records.append({
                "source_country": iso3,
                "year": yr,
                "month": 0,  # 年次データ
                "arrivals": arrivals,
                "purpose_leisure_pct": profile[0],
                "purpose_business_pct": profile[1],
                "avg_stay_days": profile[2],
                "avg_spend_jpy": profile[3],
                "data_source": "JNTO",
            })
    return records


# ========== 2. アウトバウンド統計 — 15市場×5年 ==========
# データソース: pipeline/tourism/country_outbound_clients.py ANNUAL_DATA + WorldBankTourismClient._ALL_ANNUAL

_OUTBOUND_ANNUAL = {
    "CHN": {"2021": 25622000,  "2022": 42920000,  "2023": 87260000,  "2024": 110000000, "2025": 130000000},
    "KOR": {"2021": 1222230,   "2022": 6555370,   "2023": 22674000,  "2024": 26000000,  "2025": 28000000},
    "TWN": {"2021": 489890,    "2022": 1485208,   "2023": 12000000,  "2024": 15000000,  "2025": 16500000},
    "HKG": {"2021": 850000,    "2022": 2500000,   "2023": 8500000,   "2024": 9200000,   "2025": 10000000},
    "USA": {"2021": 39930000,  "2022": 66612000,  "2023": 80000000,  "2024": 90000000,  "2025": 95000000},
    "THA": {"2021": 700000,    "2022": 2800000,   "2023": 7000000,   "2024": 9000000,   "2025": 10000000},
    "SGP": {"2021": 1200000,   "2022": 3600000,   "2023": 8000000,   "2024": 9500000,   "2025": 10000000},
    "AUS": {"2021": 1234000,   "2022": 5678000,   "2023": 9000000,   "2024": 10500000,  "2025": 11000000},
    "PHL": {"2021": 440000,    "2022": 1100000,   "2023": 2200000,   "2024": 2500000,   "2025": 2700000},
    "MYS": {"2021": 1500000,   "2022": 4500000,   "2023": 10000000,  "2024": 12000000,  "2025": 13000000},
    "VNM": {"2021": 900000,    "2022": 2200000,   "2023": 4500000,   "2024": 5000000,   "2025": 5500000},
    "IND": {"2021": 5500000,   "2022": 12000000,  "2023": 22000000,  "2024": 25000000,  "2025": 27000000},
    "DEU": {"2021": 25000000,  "2022": 55000000,  "2023": 85000000,  "2024": 92000000,  "2025": 96000000},
    "GBR": {"2021": 22000000,  "2022": 48000000,  "2023": 80000000,  "2024": 86000000,  "2025": 90000000},
    "FRA": {"2021": 12000000,  "2022": 22000000,  "2023": 30000000,  "2024": 33000000,  "2025": 35000000},
}

# 各市場のトップ渡航先（概算、日本を含む）
_TOP_DESTINATIONS = {
    "CHN": ["THA", "JPN", "KOR", "SGP", "MYS", "USA", "AUS"],
    "KOR": ["JPN", "THA", "VNM", "PHL", "USA", "CHN", "SGP"],
    "TWN": ["JPN", "KOR", "THA", "HKG", "USA", "VNM", "SGP"],
    "HKG": ["JPN", "KOR", "TWN", "THA", "SGP", "GBR", "USA"],
    "USA": ["MEX", "CAN", "GBR", "FRA", "ITA", "JPN", "DEU"],
    "THA": ["JPN", "KOR", "SGP", "MYS", "HKG", "CHN", "USA"],
    "SGP": ["MYS", "THA", "IDN", "JPN", "AUS", "KOR", "HKG"],
    "AUS": ["NZL", "IDN", "USA", "GBR", "THA", "JPN", "SGP"],
    "PHL": ["JPN", "KOR", "USA", "SGP", "HKG", "THA", "MYS"],
    "MYS": ["THA", "SGP", "IDN", "JPN", "AUS", "KOR", "CHN"],
    "VNM": ["THA", "KOR", "JPN", "SGP", "MYS", "USA", "CHN"],
    "IND": ["UAE", "USA", "THA", "SGP", "GBR", "MYS", "JPN"],
    "DEU": ["ESP", "ITA", "AUT", "TUR", "FRA", "GRC", "USA"],
    "GBR": ["ESP", "FRA", "ITA", "USA", "PRT", "GRC", "TUR"],
    "FRA": ["ESP", "ITA", "PRT", "GBR", "DEU", "GRC", "USA"],
}


def _build_outbound_records():
    """アウトバウンド統計レコードを生成（15市場×5年=75行）"""
    records = []
    for iso3, annual in _OUTBOUND_ANNUAL.items():
        dests = _TOP_DESTINATIONS.get(iso3, [])
        for yr in YEARS:
            total = annual.get(str(yr))
            if total is None:
                continue
            records.append({
                "source_country": iso3,
                "year": yr,
                "month": 0,  # 年次データ
                "outbound_total": total,
                "top_destinations": dests,
                "data_source": "WorldBank/hardcoded",
            })
    return records


# ========== 3. 競合インバウンド — 6カ国×5年 ==========
# データソース: pipeline/tourism/competitor_stats_client.py COMPETITORS + JAPAN_INBOUND

_COMPETITOR_INBOUND = {
    "THA": {"2021": 428000,    "2022": 11150000,  "2023": 28150000,  "2024": 35500000, "2025": 38000000},
    "KOR": {"2021": 967000,    "2022": 3200000,   "2023": 11030000,  "2024": 16800000, "2025": 18000000},
    "SGP": {"2021": 330000,    "2022": 6300000,   "2023": 13600000,  "2024": 17000000, "2025": 18500000},
    "IDN": {"2021": 1557000,   "2022": 5500000,   "2023": 11700000,  "2024": 14500000, "2025": 16000000},
    "FRA": {"2021": 48400000,  "2022": 80000000,  "2023": 100000000, "2024": 102000000,"2025": 105000000},
    "ESP": {"2021": 31200000,  "2022": 72000000,  "2023": 85100000,  "2024": 90000000, "2025": 93000000},
}

# 日本自身のインバウンド（比較用）
_JAPAN_INBOUND_TOTAL = {
    "2021": 245900,   "2022": 3832100, "2023": 25066100, "2024": 36869900, "2025": 40000000,
}

# 観光収入概算（十億USD）
_REVENUE_ESTIMATES = {
    "THA": {"2021": 0.5, "2022": 11.5, "2023": 33.0, "2024": 42.0, "2025": 48.0},
    "KOR": {"2021": 0.8, "2022": 3.5,  "2023": 13.0, "2024": 19.5, "2025": 22.0},
    "SGP": {"2021": 0.4, "2022": 7.5,  "2023": 17.0, "2024": 22.0, "2025": 25.0},
    "IDN": {"2021": 1.0, "2022": 5.0,  "2023": 12.0, "2024": 16.0, "2025": 19.0},
    "FRA": {"2021": 35.0,"2022": 58.0, "2023": 72.0, "2024": 75.0, "2025": 78.0},
    "ESP": {"2021": 22.0,"2022": 52.0, "2023": 68.0, "2024": 74.0, "2025": 78.0},
    "JPN": {"2021": 0.2, "2022": 3.4,  "2023": 36.0, "2024": 55.0, "2025": 62.0},
}


def _build_competitor_inbound_records():
    """競合インバウンドレコードを生成（6カ国+日本 ×5年=35行）"""
    records = []

    # 競合6カ国
    for dest, annual in _COMPETITOR_INBOUND.items():
        for yr in YEARS:
            arrivals = annual.get(str(yr))
            if arrivals is None:
                continue
            revenue = _REVENUE_ESTIMATES.get(dest, {}).get(str(yr))
            records.append({
                "destination": dest,
                "source_country": "ALL",
                "year": yr,
                "month": 0,
                "arrivals": arrivals,
                "revenue_usd": revenue * 1e9 if revenue else None,  # 十億USD→USD
                "data_source": "WorldBank/hardcoded",
            })

    # 日本自身
    for yr in YEARS:
        yr_str = str(yr)
        arrivals = _JAPAN_INBOUND_TOTAL.get(yr_str)
        revenue = _REVENUE_ESTIMATES.get("JPN", {}).get(yr_str)
        if arrivals:
            records.append({
                "destination": "JPN",
                "source_country": "ALL",
                "year": yr,
                "month": 0,
                "arrivals": arrivals,
                "revenue_usd": revenue * 1e9 if revenue else None,
                "data_source": "JNTO/hardcoded",
            })

    return records


# ========== 4. 重力モデル変数 — 15市場×5年 ==========
# GDP: World Bank概算（名目GDP、十億USD）
# 為替: 年間平均 USD/JPY
# フライト供給指数: 2019=100ベース (pipeline/tourism/flight_supply_client.py CAPACITY_INDEX)
# ビザ免除: 2025年時点のステータス
# 二国間リスク: SCRI scoring engine の大まかな推定値(0-100)

_GRAVITY_DATA = {
    "CHN": {
        "gdp": {"2021": 17734, "2022": 17963, "2023": 17795, "2024": 18300, "2025": 18800},
        "visa_free": False,
        "bilateral_risk": 45,
        "flight_idx": {"2021": 8, "2022": 15, "2023": 65, "2024": 85, "2025": 92},
    },
    "KOR": {
        "gdp": {"2021": 1811, "2022": 1665, "2023": 1713, "2024": 1780, "2025": 1850},
        "visa_free": True,
        "bilateral_risk": 15,
        "flight_idx": {"2021": 12, "2022": 35, "2023": 88, "2024": 105, "2025": 110},
    },
    "TWN": {
        "gdp": {"2021": 775, "2022": 761, "2023": 790, "2024": 820, "2025": 855},
        "visa_free": True,
        "bilateral_risk": 12,
        "flight_idx": {"2021": 8, "2022": 20, "2023": 75, "2024": 95, "2025": 100},
    },
    "HKG": {
        "gdp": {"2021": 369, "2022": 361, "2023": 382, "2024": 398, "2025": 415},
        "visa_free": True,
        "bilateral_risk": 18,
        "flight_idx": {"2021": 8, "2022": 25, "2023": 80, "2024": 95, "2025": 100},
    },
    "USA": {
        "gdp": {"2021": 23315, "2022": 25463, "2023": 27361, "2024": 28800, "2025": 30000},
        "visa_free": True,
        "bilateral_risk": 10,
        "flight_idx": {"2021": 25, "2022": 55, "2023": 85, "2024": 95, "2025": 100},
    },
    "THA": {
        "gdp": {"2021": 506, "2022": 495, "2023": 515, "2024": 540, "2025": 565},
        "visa_free": True,
        "bilateral_risk": 8,
        "flight_idx": {"2021": 10, "2022": 40, "2023": 80, "2024": 90, "2025": 95},
    },
    "SGP": {
        "gdp": {"2021": 397, "2022": 424, "2023": 464, "2024": 490, "2025": 515},
        "visa_free": True,
        "bilateral_risk": 5,
        "flight_idx": {"2021": 15, "2022": 45, "2023": 85, "2024": 95, "2025": 100},
    },
    "AUS": {
        "gdp": {"2021": 1553, "2022": 1676, "2023": 1688, "2024": 1750, "2025": 1820},
        "visa_free": True,
        "bilateral_risk": 8,
        "flight_idx": {"2021": 10, "2022": 40, "2023": 78, "2024": 88, "2025": 93},
    },
    "PHL": {
        "gdp": {"2021": 394, "2022": 404, "2023": 437, "2024": 465, "2025": 495},
        "visa_free": True,
        "bilateral_risk": 12,
        "flight_idx": {"2021": 12, "2022": 35, "2023": 75, "2024": 85, "2025": 90},
    },
    "MYS": {
        "gdp": {"2021": 373, "2022": 407, "2023": 400, "2024": 420, "2025": 445},
        "visa_free": True,
        "bilateral_risk": 8,
        "flight_idx": {"2021": 10, "2022": 30, "2023": 70, "2024": 82, "2025": 88},
    },
    "VNM": {
        "gdp": {"2021": 366, "2022": 409, "2023": 430, "2024": 460, "2025": 490},
        "visa_free": True,
        "bilateral_risk": 10,
        "flight_idx": {"2021": 8, "2022": 30, "2023": 78, "2024": 92, "2025": 98},
    },
    "IND": {
        "gdp": {"2021": 3150, "2022": 3385, "2023": 3550, "2024": 3800, "2025": 4100},
        "visa_free": False,
        "bilateral_risk": 15,
        "flight_idx": {"2021": 12, "2022": 38, "2023": 80, "2024": 100, "2025": 115},
    },
    "DEU": {
        "gdp": {"2021": 4259, "2022": 4082, "2023": 4456, "2024": 4600, "2025": 4750},
        "visa_free": True,
        "bilateral_risk": 5,
        "flight_idx": {"2021": 20, "2022": 50, "2023": 80, "2024": 90, "2025": 95},
    },
    "GBR": {
        "gdp": {"2021": 3124, "2022": 3070, "2023": 3332, "2024": 3450, "2025": 3570},
        "visa_free": True,
        "bilateral_risk": 5,
        "flight_idx": {"2021": 18, "2022": 48, "2023": 78, "2024": 88, "2025": 93},
    },
    "FRA": {
        "gdp": {"2021": 2958, "2022": 2782, "2023": 3031, "2024": 3150, "2025": 3260},
        "visa_free": True,
        "bilateral_risk": 5,
        "flight_idx": {"2021": 15, "2022": 42, "2023": 75, "2024": 85, "2025": 90},
    },
}

# USD/JPY 年間平均レート
_USDJPY = {
    "2021": 109.8, "2022": 131.5, "2023": 140.5, "2024": 151.0, "2025": 148.0,
}


def _build_gravity_records():
    """重力モデル変数レコードを生成（15市場×5年=75行）"""
    records = []
    for iso3, data in _GRAVITY_DATA.items():
        for yr in YEARS:
            yr_str = str(yr)
            gdp = data["gdp"].get(yr_str)
            if gdp is None:
                continue
            fx = _USDJPY.get(yr_str, 140.0)
            flight_idx = data["flight_idx"].get(yr_str)
            records.append({
                "source_country": iso3,
                "year": yr,
                "month": 0,
                "gdp_source_usd": gdp * 1e9,  # 十億USD → USD
                "exchange_rate_jpy": fx,
                "flight_supply_index": flight_idx,
                "visa_free": data["visa_free"],
                "bilateral_risk": data["bilateral_risk"],
            })
    return records


# ========== メイン ==========

def main():
    print("=" * 60)
    print("観光統計DB 初期データ取込（bootstrap）")
    print("=" * 60)

    db = TourismDB()
    print(f"\nDB: {db.db_path}")

    # 1. JNTO日本インバウンド
    japan_inbound = _build_japan_inbound_records()
    db.upsert_japan_inbound(japan_inbound)
    print(f"  japan_inbound: {len(japan_inbound)} 行投入")

    # 2. アウトバウンド
    outbound = _build_outbound_records()
    db.upsert_outbound(outbound)
    print(f"  outbound_stats: {len(outbound)} 行投入")

    # 3. 競合インバウンド
    inbound = _build_competitor_inbound_records()
    db.upsert_inbound(inbound)
    print(f"  inbound_stats: {len(inbound)} 行投入")

    # 4. 重力モデル変数
    gravity = _build_gravity_records()
    db.upsert_gravity_variables(gravity)
    print(f"  gravity_variables: {len(gravity)} 行投入")

    # 結果表示
    counts = db.get_table_counts()
    print("\n--- テーブル別件数 ---")
    total = 0
    for table, count in counts.items():
        print(f"  {table}: {count} 行")
        total += count
    print(f"  合計: {total} 行")

    # サンプルデータ表示
    print("\n--- サンプル: 日本インバウンド 2024年 上位5市場 ---")
    sample = db.get_japan_inbound(year=2024)
    for row in sample[:5]:
        print(f"  {row['source_country']}: {row['arrivals']:>12,} 人"
              f"  (leisure {row['purpose_leisure_pct']}%, stay {row['avg_stay_days']}d,"
              f" spend ¥{row['avg_spend_jpy']:,})")

    print("\n--- サンプル: 競合インバウンド 2024年 ---")
    sample_comp = db.get_inbound(year=2024)
    for row in sample_comp[:7]:
        rev_str = f"${row['revenue_usd']/1e9:.1f}B" if row['revenue_usd'] else "N/A"
        print(f"  {row['destination']}: {row['arrivals']:>12,} 人  収入 {rev_str}")

    print("\n完了。")
    return counts


if __name__ == "__main__":
    main()
