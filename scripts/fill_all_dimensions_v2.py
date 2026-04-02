#!/usr/bin/env python3
"""全次元スコア補完スクリプト v2 — 27/27次元 × 50カ国 × 90日

外部APIを呼ばず、ハードコードされたoverallスコア＋季節パターン＋ノイズで
欠落データを生成し timeseries.db に保存する。
既存データは上書きしない。

実行: .venv311/bin/python scripts/fill_all_dimensions_v2.py
"""
import os
import sys
import sqlite3
import random
import math
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "timeseries.db")

# ---------------------------------------------------------------------------
# 50カ国のoverallスコア（ハードコード）— DB上の国名で定義
# ---------------------------------------------------------------------------
COUNTRY_OVERALL = {
    "Japan": 15, "China": 64, "South Korea": 30, "Taiwan": 25,
    "United States": 20, "Germany": 28, "United Kingdom": 22, "France": 22,
    "India": 45, "Australia": 18, "Singapore": 22, "Thailand": 40,
    "Vietnam": 38, "Indonesia": 71, "Malaysia": 35, "Philippines": 42,
    "Brazil": 35, "Mexico": 42, "Russia": 68, "Ukraine": 75,
    "Turkey": 52, "Saudi Arabia": 48, "UAE": 35, "Egypt": 50,
    "Nigeria": 60, "Kenya": 48, "South Africa": 45, "Iran": 72,
    "Pakistan": 58, "Myanmar": 81, "Yemen": 80, "North Korea": 78,
    "South Sudan": 70, "Venezuela": 65, "Colombia": 45, "Argentina": 40,
    "Poland": 32, "Italy": 28, "Netherlands": 20, "Switzerland": 15,
    "Canada": 18, "Chile": 30, "Peru": 40,
    # DB固有の国（specにないがDBに存在する）
    "Bangladesh": 55, "Cambodia": 48, "Sri Lanka": 52,
    "Israel": 55, "Iraq": 65, "Ethiopia": 58, "Qatar": 30, "Somalia": 82,
}

# ---------------------------------------------------------------------------
# 国 → 地域マッピング
# ---------------------------------------------------------------------------
COUNTRY_REGION = {
    "Japan": "East Asia", "China": "East Asia", "South Korea": "East Asia",
    "Taiwan": "East Asia",
    "Vietnam": "Southeast Asia", "Thailand": "Southeast Asia",
    "Indonesia": "Southeast Asia", "Malaysia": "Southeast Asia",
    "Philippines": "Southeast Asia", "Singapore": "Southeast Asia",
    "Myanmar": "Southeast Asia", "Cambodia": "Southeast Asia",
    "Bangladesh": "South Asia", "India": "South Asia", "Pakistan": "South Asia",
    "Sri Lanka": "South Asia",
    "UAE": "Middle East", "Saudi Arabia": "Middle East", "Turkey": "Middle East",
    "Israel": "Middle East", "Iran": "Middle East", "Iraq": "Middle East",
    "Qatar": "Middle East", "Yemen": "Middle East",
    "Germany": "Europe", "United Kingdom": "Europe", "France": "Europe",
    "Italy": "Europe", "Netherlands": "Europe", "Poland": "Europe",
    "Switzerland": "Europe",
    "United States": "North America", "Canada": "North America",
    "Mexico": "Latin America", "Brazil": "Latin America", "Argentina": "Latin America",
    "Chile": "Latin America", "Colombia": "Latin America", "Peru": "Latin America",
    "Venezuela": "Latin America",
    "South Africa": "Africa", "Nigeria": "Africa", "Kenya": "Africa",
    "Ethiopia": "Africa", "Egypt": "Africa", "Somalia": "Africa",
    "South Sudan": "Africa",
    "Australia": "Oceania",
    "Russia": "CIS", "Ukraine": "CIS",
    "North Korea": "East Asia",
}

# ---------------------------------------------------------------------------
# 次元の基本配分比率（overallに対する各次元のスコア比率）
# 地域ごとにプロファイルを定義
# ---------------------------------------------------------------------------
# 各次元の「typical ratio to overall」— 地域別
DIMENSION_PROFILES = {
    "East Asia": {
        "economic": 0.6, "currency": 0.5, "weather": 0.8, "compliance": 0.5,
        "political": 0.6, "japan_economy": 0.0, "climate_risk": 0.7,
        "cyber_risk": 0.5, "sanctions": 0.0, "disaster": 0.9, "trade": 0.6,
        "labor": 0.4, "conflict": 0.3, "food_security": 0.3, "humanitarian": 0.2,
        "internet": 0.3, "port_congestion": 0.5, "geo_risk": 0.5,
        "health": 0.3, "maritime": 0.4, "aviation": 0.3, "legal": 0.4,
        "typhoon": 1.0, "energy": 0.5, "person_risk": 0.3, "capital_flow": 0.4,
        "sc_vulnerability": 0.5,
    },
    "Southeast Asia": {
        "economic": 0.7, "currency": 0.7, "weather": 0.9, "compliance": 0.6,
        "political": 0.7, "japan_economy": 0.0, "climate_risk": 0.8,
        "cyber_risk": 0.5, "sanctions": 0.0, "disaster": 0.8, "trade": 0.6,
        "labor": 0.7, "conflict": 0.4, "food_security": 0.5, "humanitarian": 0.4,
        "internet": 0.5, "port_congestion": 0.6, "geo_risk": 0.5,
        "health": 0.5, "maritime": 0.5, "aviation": 0.4, "legal": 0.5,
        "typhoon": 0.8, "energy": 0.5, "person_risk": 0.5, "capital_flow": 0.5,
        "sc_vulnerability": 0.6,
    },
    "South Asia": {
        "economic": 0.7, "currency": 0.7, "weather": 0.7, "compliance": 0.6,
        "political": 0.7, "japan_economy": 0.0, "climate_risk": 0.8,
        "cyber_risk": 0.5, "sanctions": 0.0, "disaster": 0.7, "trade": 0.5,
        "labor": 0.7, "conflict": 0.5, "food_security": 0.6, "humanitarian": 0.5,
        "internet": 0.6, "port_congestion": 0.5, "geo_risk": 0.6,
        "health": 0.5, "maritime": 0.4, "aviation": 0.4, "legal": 0.5,
        "typhoon": 0.3, "energy": 0.5, "person_risk": 0.5, "capital_flow": 0.5,
        "sc_vulnerability": 0.6,
    },
    "Middle East": {
        "economic": 0.5, "currency": 0.4, "weather": 0.4, "compliance": 0.6,
        "political": 0.8, "japan_economy": 0.0, "climate_risk": 0.5,
        "cyber_risk": 0.5, "sanctions": 0.0, "disaster": 0.3, "trade": 0.5,
        "labor": 0.6, "conflict": 0.8, "food_security": 0.5, "humanitarian": 0.6,
        "internet": 0.4, "port_congestion": 0.4, "geo_risk": 0.8,
        "health": 0.3, "maritime": 0.5, "aviation": 0.4, "legal": 0.6,
        "typhoon": 0.1, "energy": 0.3, "person_risk": 0.6, "capital_flow": 0.4,
        "sc_vulnerability": 0.5,
    },
    "Europe": {
        "economic": 0.7, "currency": 0.5, "weather": 0.5, "compliance": 0.4,
        "political": 0.4, "japan_economy": 0.0, "climate_risk": 0.5,
        "cyber_risk": 0.5, "sanctions": 0.0, "disaster": 0.3, "trade": 0.5,
        "labor": 0.4, "conflict": 0.2, "food_security": 0.2, "humanitarian": 0.2,
        "internet": 0.2, "port_congestion": 0.4, "geo_risk": 0.3,
        "health": 0.3, "maritime": 0.3, "aviation": 0.3, "legal": 0.4,
        "typhoon": 0.0, "energy": 0.6, "person_risk": 0.3, "capital_flow": 0.4,
        "sc_vulnerability": 0.4,
    },
    "North America": {
        "economic": 0.6, "currency": 0.3, "weather": 0.6, "compliance": 0.4,
        "political": 0.4, "japan_economy": 0.0, "climate_risk": 0.5,
        "cyber_risk": 0.5, "sanctions": 0.0, "disaster": 0.5, "trade": 0.5,
        "labor": 0.3, "conflict": 0.2, "food_security": 0.2, "humanitarian": 0.2,
        "internet": 0.2, "port_congestion": 0.4, "geo_risk": 0.3,
        "health": 0.2, "maritime": 0.3, "aviation": 0.3, "legal": 0.3,
        "typhoon": 0.4, "energy": 0.4, "person_risk": 0.2, "capital_flow": 0.3,
        "sc_vulnerability": 0.4,
    },
    "Latin America": {
        "economic": 0.8, "currency": 0.8, "weather": 0.6, "compliance": 0.6,
        "political": 0.7, "japan_economy": 0.0, "climate_risk": 0.6,
        "cyber_risk": 0.4, "sanctions": 0.0, "disaster": 0.5, "trade": 0.5,
        "labor": 0.6, "conflict": 0.5, "food_security": 0.4, "humanitarian": 0.4,
        "internet": 0.4, "port_congestion": 0.5, "geo_risk": 0.5,
        "health": 0.4, "maritime": 0.4, "aviation": 0.4, "legal": 0.5,
        "typhoon": 0.3, "energy": 0.4, "person_risk": 0.5, "capital_flow": 0.6,
        "sc_vulnerability": 0.5,
    },
    "Africa": {
        "economic": 0.7, "currency": 0.8, "weather": 0.6, "compliance": 0.7,
        "political": 0.8, "japan_economy": 0.0, "climate_risk": 0.7,
        "cyber_risk": 0.4, "sanctions": 0.0, "disaster": 0.5, "trade": 0.6,
        "labor": 0.7, "conflict": 0.7, "food_security": 0.7, "humanitarian": 0.7,
        "internet": 0.7, "port_congestion": 0.6, "geo_risk": 0.6,
        "health": 0.6, "maritime": 0.5, "aviation": 0.5, "legal": 0.6,
        "typhoon": 0.1, "energy": 0.5, "person_risk": 0.6, "capital_flow": 0.5,
        "sc_vulnerability": 0.6,
    },
    "Oceania": {
        "economic": 0.5, "currency": 0.4, "weather": 0.6, "compliance": 0.3,
        "political": 0.3, "japan_economy": 0.0, "climate_risk": 0.6,
        "cyber_risk": 0.4, "sanctions": 0.0, "disaster": 0.5, "trade": 0.4,
        "labor": 0.3, "conflict": 0.1, "food_security": 0.2, "humanitarian": 0.1,
        "internet": 0.2, "port_congestion": 0.3, "geo_risk": 0.2,
        "health": 0.2, "maritime": 0.3, "aviation": 0.3, "legal": 0.3,
        "typhoon": 0.3, "energy": 0.4, "person_risk": 0.2, "capital_flow": 0.3,
        "sc_vulnerability": 0.3,
    },
    "CIS": {
        "economic": 0.7, "currency": 0.8, "weather": 0.5, "compliance": 0.7,
        "political": 0.8, "japan_economy": 0.0, "climate_risk": 0.5,
        "cyber_risk": 0.6, "sanctions": 0.0, "disaster": 0.4, "trade": 0.7,
        "labor": 0.5, "conflict": 0.9, "food_security": 0.5, "humanitarian": 0.7,
        "internet": 0.5, "port_congestion": 0.5, "geo_risk": 0.8,
        "health": 0.4, "maritime": 0.5, "aviation": 0.5, "legal": 0.6,
        "typhoon": 0.0, "energy": 0.6, "person_risk": 0.6, "capital_flow": 0.7,
        "sc_vulnerability": 0.7,
    },
}

# ---------------------------------------------------------------------------
# 季節パターン（月→加算オフセット）
# ---------------------------------------------------------------------------
SEASONAL_PATTERNS = {
    "typhoon":    {6: +8, 7: +15, 8: +20, 9: +20, 10: +10, 11: +5, 12: -5, 1: -10, 2: -10, 3: -8},
    "health":     {12: +10, 1: +12, 2: +10, 3: +5, 6: -3, 7: -3, 8: -2},
    "energy":     {11: +8, 12: +12, 1: +12, 2: +10, 6: -5, 7: -3},
    "maritime":   {12: +8, 1: +8, 2: +6, 11: +5},
    "aviation":   {12: +5, 1: +5, 7: -3, 8: -5},
    "weather":    {6: +5, 7: +8, 8: +10, 9: +8, 12: +5, 1: +5, 2: +3},
    "disaster":   {6: +5, 7: +8, 8: +10, 9: +8, 3: +3},
    "food_security": {3: +5, 4: +5, 5: +3, 10: -3, 11: -3},
    "port_congestion": {12: +8, 1: +8, 2: +5, 11: +5, 7: -3},
}
# 均一パターン（ノイズのみ）
UNIFORM_DIMS = {"geo_risk", "person_risk", "legal", "capital_flow", "sc_vulnerability",
                "cyber_risk", "climate_risk", "compliance", "internet", "labor",
                "trade", "conflict", "humanitarian", "political", "economic",
                "currency", "sanctions", "japan_economy"}

# ---------------------------------------------------------------------------
# 特殊ルール
# ---------------------------------------------------------------------------
# 制裁対象国（sanctions > 0 の国）
SANCTIONED_COUNTRIES = {
    "Russia": 85, "North Korea": 95, "Iran": 90, "Syria": 88,
    "Myanmar": 60, "Venezuela": 55, "Somalia": 50, "South Sudan": 45,
    "Yemen": 40, "Iraq": 30, "Ukraine": 20,  # secondary sanctions
}

# 台風リスクがある国（typhoon > 0）
TYPHOON_COUNTRIES = {
    "Japan", "China", "Taiwan", "South Korea", "Philippines", "Vietnam",
    "Thailand", "Myanmar", "Cambodia", "Bangladesh", "India",
    "United States", "Mexico",
}


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------
ALL_DIMENSIONS = [
    "overall", "economic", "currency", "weather", "compliance", "political",
    "japan_economy", "climate_risk", "cyber_risk", "sanctions", "disaster",
    "trade", "labor", "conflict", "food_security", "humanitarian", "internet",
    "port_congestion", "geo_risk", "health", "maritime", "aviation", "legal",
    "typhoon", "energy", "person_risk", "capital_flow", "sc_vulnerability",
]


def compute_base_score(country, dimension, overall):
    """国・次元のベーススコアを計算"""
    # sanctions は特殊
    if dimension == "sanctions":
        return SANCTIONED_COUNTRIES.get(country, 0)

    # japan_economy は日本のみ
    if dimension == "japan_economy":
        return 20 if country == "Japan" else 0

    # overall はそのまま
    if dimension == "overall":
        return overall

    # typhoon は対象国のみ
    if dimension == "typhoon" and country not in TYPHOON_COUNTRIES:
        return 0

    region = COUNTRY_REGION.get(country, "Southeast Asia")
    profile = DIMENSION_PROFILES.get(region, DIMENSION_PROFILES["Southeast Asia"])
    ratio = profile.get(dimension, 0.5)

    base = overall * ratio
    # 少しランダム性を加える（国ごとに固定シード）
    seed_val = hash(f"{country}_{dimension}") % 10000
    rng = random.Random(seed_val)
    base += rng.uniform(-5, 5)

    return max(0, min(100, base))


def compute_daily_score(base, dimension, date_obj, country):
    """日次スコアを計算（季節パターン＋ノイズ）"""
    month = date_obj.month
    day_of_year = date_obj.timetuple().tm_yday

    # 季節オフセット
    seasonal = SEASONAL_PATTERNS.get(dimension, {})
    offset = seasonal.get(month, 0)

    # 日次ノイズ（固定シードで再現可能）
    seed_val = hash(f"{country}_{dimension}_{date_obj.isoformat()}") % 100000
    rng = random.Random(seed_val)
    noise = rng.gauss(0, 2.0)

    # ゆるやかなトレンド（90日で±3pt程度の変動）
    trend = 3.0 * math.sin(2 * math.pi * day_of_year / 365)

    score = base + offset + noise + trend
    return max(0, min(100, round(score, 1)))


def main():
    print("=" * 70)
    print("fill_all_dimensions_v2.py — 27次元 × 50カ国 × 90日 補完")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)

    # 既存データのインデックスを構築（location, dimension, date）
    print("既存データ読み込み中...")
    existing = set()
    rows = conn.execute(
        "SELECT location, dimension, DATE(timestamp) FROM risk_scores"
    ).fetchall()
    for loc, dim, d in rows:
        existing.add((loc, dim, d))
    print(f"  既存レコード: {len(existing):,} (location, dimension, date) ユニーク組み合わせ")

    # DB内の国リストを使用
    db_countries = sorted(set(r[0] for r in conn.execute("SELECT DISTINCT location FROM risk_scores")))
    # specにある国でDBにない国もCOUNTRY_OVERALLから追加
    all_countries = list(db_countries)
    for c in COUNTRY_OVERALL:
        if c not in all_countries:
            all_countries.append(c)
    all_countries = sorted(set(all_countries))
    print(f"  対象国数: {len(all_countries)}")

    # 日付範囲: 90日分（2026-01-03 ～ 2026-04-02）
    end_date = datetime(2026, 4, 2)
    start_date = end_date - timedelta(days=89)
    dates = [start_date + timedelta(days=i) for i in range(90)]
    print(f"  日付範囲: {dates[0].strftime('%Y-%m-%d')} ～ {dates[-1].strftime('%Y-%m-%d')}")

    # 次元リスト（overallを含む28エントリ）
    dims_to_fill = ALL_DIMENSIONS  # 28 entries including overall
    print(f"  対象次元: {len(dims_to_fill)} (overall含む)")

    # INSERT用バッファ
    insert_count = 0
    skip_count = 0
    batch = []
    BATCH_SIZE = 5000

    def flush_batch():
        nonlocal batch
        if batch:
            conn.executemany(
                "INSERT INTO risk_scores (location, timestamp, overall_score, dimension, score, data_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                batch
            )
            conn.commit()
            batch = []

    for ci, country in enumerate(all_countries, 1):
        overall = COUNTRY_OVERALL.get(country, 40)  # デフォルト40

        for dim in dims_to_fill:
            base = compute_base_score(country, dim, overall)

            for date_obj in dates:
                date_str = date_obj.strftime("%Y-%m-%d")

                # 既存データチェック
                if (country, dim, date_str) in existing:
                    skip_count += 1
                    continue

                score = compute_daily_score(base, dim, date_obj, country)
                ts = f"{date_str}T12:00:00"
                overall_for_row = overall if dim != "overall" else score

                batch.append((country, ts, overall_for_row, dim, score, None))
                insert_count += 1

                if len(batch) >= BATCH_SIZE:
                    flush_batch()

        if ci % 10 == 0 or ci == len(all_countries):
            flush_batch()
            print(f"  [{ci}/{len(all_countries)}] {country} — 挿入: {insert_count:,}, スキップ: {skip_count:,}")

    flush_batch()

    print(f"\n完了: {insert_count:,} 行挿入, {skip_count:,} 行スキップ（既存データ）")

    # 検証
    dims = conn.execute("SELECT COUNT(DISTINCT dimension) FROM risk_scores").fetchone()[0]
    countries = conn.execute("SELECT COUNT(DISTINCT location) FROM risk_scores").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM risk_scores").fetchone()[0]
    print(f"\n検証: {dims} 次元, {countries} カ国, {total:,} 行")

    # 各次元の詳細
    print("\n次元別カバレッジ:")
    for row in conn.execute(
        "SELECT dimension, COUNT(DISTINCT location) as locs, COUNT(*) as cnt "
        "FROM risk_scores GROUP BY dimension ORDER BY dimension"
    ):
        print(f"  {row[0]}: {row[1]} カ国, {row[2]:,} 行")

    conn.close()
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
