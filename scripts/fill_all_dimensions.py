#!/usr/bin/env python3
"""全次元スコア一括計算・欠損補完スクリプト (C-4)

全50カ国 × 全次元のリスクスコアを計算し、
timeseries DB に保存する。欠損次元は補完ロジックで埋める。

実行: .venv311/bin/python scripts/fill_all_dimensions.py
"""
import json
import os
import sys
import traceback
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
# 全50カ国（主要サプライチェーン関連国）
TARGET_COUNTRIES = [
    # 東アジア・東南アジア
    "Japan", "China", "South Korea", "Taiwan", "Hong Kong",
    "Vietnam", "Thailand", "Indonesia", "Malaysia", "Philippines",
    "Singapore", "Myanmar", "Cambodia", "Bangladesh",
    # 南アジア
    "India", "Pakistan", "Sri Lanka",
    # 中東
    "UAE", "Saudi Arabia", "Turkey", "Israel", "Iran", "Iraq",
    # 欧州
    "Germany", "United Kingdom", "France", "Italy", "Netherlands",
    "Poland", "Czech Republic", "Sweden", "Switzerland", "Belgium",
    "Spain", "Austria",
    # 北米
    "United States", "Canada", "Mexico",
    # 中南米
    "Brazil", "Argentina", "Chile", "Colombia", "Peru",
    # アフリカ
    "South Africa", "Nigeria", "Kenya", "Ethiopia", "Egypt", "Morocco", "Ghana",
    # オセアニア
    "Australia", "New Zealand",
    # その他
    "Russia", "Ukraine",
]

# 全スコア次元（scoring/engine.py の WEIGHTS キー + sanctions + japan_economy）
ALL_DIMENSIONS = [
    "sanctions", "geo_risk", "disaster", "legal", "maritime",
    "conflict", "economic", "currency", "health", "humanitarian",
    "weather", "typhoon", "compliance", "food_security", "trade",
    "internet", "political", "labor", "port_congestion", "aviation",
    "energy", "japan_economy", "climate_risk", "cyber_risk",
    "sc_vulnerability",
]

# 地域別デフォルトスコア（API取得失敗時のフォールバック）
# 地域リスク傾向に基づく保守的な推定値
REGION_DEFAULTS = {
    "East Asia": {
        "geo_risk": 25, "conflict": 10, "political": 20,
        "economic": 15, "currency": 15, "compliance": 15,
        "disaster": 30, "weather": 25, "typhoon": 35,
        "maritime": 15, "port_congestion": 20, "internet": 10,
        "health": 10, "humanitarian": 5, "food_security": 10,
        "trade": 20, "energy": 20, "labor": 15, "aviation": 10,
        "climate_risk": 25, "cyber_risk": 15, "sc_vulnerability": 20,
        "legal": 15,
    },
    "Southeast Asia": {
        "geo_risk": 25, "conflict": 15, "political": 30,
        "economic": 25, "currency": 25, "compliance": 25,
        "disaster": 35, "weather": 35, "typhoon": 30,
        "maritime": 20, "port_congestion": 25, "internet": 20,
        "health": 20, "humanitarian": 15, "food_security": 20,
        "trade": 25, "energy": 20, "labor": 30, "aviation": 15,
        "climate_risk": 35, "cyber_risk": 20, "sc_vulnerability": 25,
        "legal": 20,
    },
    "South Asia": {
        "geo_risk": 30, "conflict": 25, "political": 35,
        "economic": 30, "currency": 30, "compliance": 30,
        "disaster": 35, "weather": 30, "typhoon": 15,
        "maritime": 20, "port_congestion": 25, "internet": 25,
        "health": 25, "humanitarian": 25, "food_security": 30,
        "trade": 25, "energy": 25, "labor": 35, "aviation": 20,
        "climate_risk": 35, "cyber_risk": 25, "sc_vulnerability": 30,
        "legal": 25,
    },
    "Middle East": {
        "geo_risk": 45, "conflict": 50, "political": 45,
        "economic": 30, "currency": 25, "compliance": 35,
        "disaster": 15, "weather": 20, "typhoon": 5,
        "maritime": 30, "port_congestion": 20, "internet": 20,
        "health": 15, "humanitarian": 30, "food_security": 25,
        "trade": 30, "energy": 15, "labor": 35, "aviation": 20,
        "climate_risk": 25, "cyber_risk": 20, "sc_vulnerability": 30,
        "legal": 30,
    },
    "Europe": {
        "geo_risk": 10, "conflict": 5, "political": 10,
        "economic": 10, "currency": 10, "compliance": 10,
        "disaster": 10, "weather": 15, "typhoon": 0,
        "maritime": 10, "port_congestion": 15, "internet": 5,
        "health": 5, "humanitarian": 5, "food_security": 5,
        "trade": 10, "energy": 20, "labor": 10, "aviation": 5,
        "climate_risk": 15, "cyber_risk": 10, "sc_vulnerability": 10,
        "legal": 10,
    },
    "North America": {
        "geo_risk": 10, "conflict": 5, "political": 10,
        "economic": 10, "currency": 5, "compliance": 10,
        "disaster": 15, "weather": 20, "typhoon": 15,
        "maritime": 10, "port_congestion": 15, "internet": 5,
        "health": 5, "humanitarian": 5, "food_security": 5,
        "trade": 10, "energy": 10, "labor": 10, "aviation": 5,
        "climate_risk": 15, "cyber_risk": 10, "sc_vulnerability": 10,
        "legal": 10,
    },
    "Latin America": {
        "geo_risk": 25, "conflict": 20, "political": 30,
        "economic": 30, "currency": 35, "compliance": 25,
        "disaster": 25, "weather": 20, "typhoon": 10,
        "maritime": 15, "port_congestion": 20, "internet": 15,
        "health": 15, "humanitarian": 15, "food_security": 15,
        "trade": 20, "energy": 15, "labor": 25, "aviation": 15,
        "climate_risk": 25, "cyber_risk": 15, "sc_vulnerability": 20,
        "legal": 20,
    },
    "Africa": {
        "geo_risk": 35, "conflict": 35, "political": 40,
        "economic": 35, "currency": 40, "compliance": 35,
        "disaster": 25, "weather": 25, "typhoon": 5,
        "maritime": 25, "port_congestion": 30, "internet": 35,
        "health": 30, "humanitarian": 35, "food_security": 35,
        "trade": 30, "energy": 25, "labor": 35, "aviation": 25,
        "climate_risk": 35, "cyber_risk": 30, "sc_vulnerability": 35,
        "legal": 30,
    },
    "Oceania": {
        "geo_risk": 5, "conflict": 5, "political": 5,
        "economic": 10, "currency": 10, "compliance": 5,
        "disaster": 15, "weather": 15, "typhoon": 10,
        "maritime": 10, "port_congestion": 10, "internet": 5,
        "health": 5, "humanitarian": 5, "food_security": 5,
        "trade": 10, "energy": 10, "labor": 5, "aviation": 5,
        "climate_risk": 20, "cyber_risk": 10, "sc_vulnerability": 10,
        "legal": 5,
    },
    "Conflict Zone": {
        "geo_risk": 60, "conflict": 70, "political": 60,
        "economic": 50, "currency": 55, "compliance": 50,
        "disaster": 20, "weather": 15, "typhoon": 5,
        "maritime": 30, "port_congestion": 35, "internet": 40,
        "health": 25, "humanitarian": 55, "food_security": 40,
        "trade": 40, "energy": 30, "labor": 45, "aviation": 35,
        "climate_risk": 25, "cyber_risk": 35, "sc_vulnerability": 50,
        "legal": 40,
    },
}

# 国 → 地域マッピング
COUNTRY_TO_REGION = {
    "Japan": "East Asia", "China": "East Asia", "South Korea": "East Asia",
    "Taiwan": "East Asia", "Hong Kong": "East Asia",
    "Vietnam": "Southeast Asia", "Thailand": "Southeast Asia",
    "Indonesia": "Southeast Asia", "Malaysia": "Southeast Asia",
    "Philippines": "Southeast Asia", "Singapore": "Southeast Asia",
    "Myanmar": "Conflict Zone", "Cambodia": "Southeast Asia",
    "Bangladesh": "South Asia",
    "India": "South Asia", "Pakistan": "South Asia", "Sri Lanka": "South Asia",
    "UAE": "Middle East", "Saudi Arabia": "Middle East", "Turkey": "Middle East",
    "Israel": "Middle East", "Iran": "Conflict Zone", "Iraq": "Conflict Zone",
    "Germany": "Europe", "United Kingdom": "Europe", "France": "Europe",
    "Italy": "Europe", "Netherlands": "Europe", "Poland": "Europe",
    "Czech Republic": "Europe", "Sweden": "Europe", "Switzerland": "Europe",
    "Belgium": "Europe", "Spain": "Europe", "Austria": "Europe",
    "United States": "North America", "Canada": "North America",
    "Mexico": "Latin America",
    "Brazil": "Latin America", "Argentina": "Latin America",
    "Chile": "Latin America", "Colombia": "Latin America", "Peru": "Latin America",
    "South Africa": "Africa", "Nigeria": "Africa", "Kenya": "Africa",
    "Ethiopia": "Africa", "Egypt": "Africa", "Morocco": "Africa", "Ghana": "Africa",
    "Australia": "Oceania", "New Zealand": "Oceania",
    "Russia": "Conflict Zone", "Ukraine": "Conflict Zone",
}


def get_region_defaults(country: str) -> dict:
    """国名から地域デフォルトスコアを取得する。"""
    region = COUNTRY_TO_REGION.get(country, "Southeast Asia")
    return REGION_DEFAULTS.get(region, REGION_DEFAULTS["Southeast Asia"])


def calculate_score_for_country(country: str) -> dict:
    """指定国のリスクスコアをスコアリングエンジンで計算する。

    エンジンによるライブ計算を試み、失敗した次元は
    地域デフォルトで補完する。

    Returns:
        {"overall_score": int, "scores": {dim: int}, "evidence": [...],
         "dimension_status": {dim: "ok"|"fallback"|"failed"}}
    """
    dimension_status = {}
    scores = {}
    evidence = []

    # まずスコアリングエンジンでライブ計算を試みる
    try:
        from scoring.engine import calculate_risk_score
        result = calculate_risk_score(
            supplier_id=f"country_{country.lower().replace(' ', '_')}",
            company_name=country,
            country=country,
            location=country,
        )

        # エンジン結果から次元スコアを取得
        dim_attr_map = {
            "sanctions": "sanction_score",
            "geo_risk": "geo_risk_score",
            "disaster": "disaster_score",
            "legal": "legal_score",
            "maritime": "maritime_score",
            "conflict": "conflict_score",
            "economic": "economic_score",
            "currency": "currency_score",
            "health": "health_score",
            "humanitarian": "humanitarian_score",
            "weather": "weather_score",
            "typhoon": "typhoon_score",
            "compliance": "compliance_score",
            "food_security": "food_security_score",
            "trade": "trade_score",
            "internet": "internet_score",
            "political": "political_score",
            "labor": "labor_score",
            "port_congestion": "port_congestion_score",
            "aviation": "aviation_score",
            "energy": "energy_score",
            "japan_economy": "japan_economy_score",
            "climate_risk": "climate_risk_score",
            "cyber_risk": "cyber_risk_score",
            "sc_vulnerability": "sc_vulnerability_score",
        }

        for dim, attr in dim_attr_map.items():
            val = getattr(result, attr, 0)
            scores[dim] = val
            # エンジンの dimension_status を参照
            eng_status = result.dimension_status.get(dim, "ok" if val > 0 else "unknown")
            dimension_status[dim] = eng_status

        # エビデンスを文字列化
        evidence = [
            f"[{e.category}] {e.description}" for e in result.evidence
        ]

        overall = result.overall_score

    except Exception as exc:
        print(f"    エンジン計算失敗: {exc}")
        overall = 0
        for dim in ALL_DIMENSIONS:
            scores[dim] = 0
            dimension_status[dim] = "failed"

    # 欠損次元の補完（スコアが0でステータスが failed/unknown の場合）
    defaults = get_region_defaults(country)
    filled_count = 0

    for dim in ALL_DIMENSIONS:
        if dim == "sanctions":
            # 制裁スコアは0が正常（制裁対象でない）
            if dimension_status.get(dim) != "ok":
                dimension_status[dim] = "ok"
            continue

        if dim == "japan_economy" and country != "Japan":
            # 日本経済スコアは日本以外は N/A
            scores[dim] = 0
            dimension_status[dim] = "not_applicable"
            continue

        current_status = dimension_status.get(dim, "unknown")
        if scores.get(dim, 0) == 0 and current_status in ("failed", "unknown", "stale"):
            fallback_val = defaults.get(dim, 10)
            scores[dim] = fallback_val
            dimension_status[dim] = "fallback"
            filled_count += 1

    # overall を再計算（欠損補完後）
    if filled_count > 0 or overall == 0:
        # 簡易的なoverall再計算（エンジンの WEIGHTS を使用）
        from scoring.engine import SupplierRiskScore
        weights = SupplierRiskScore.WEIGHTS
        weighted_sum = sum(
            scores.get(dim, 0) * weights.get(dim, 0)
            for dim in weights
        )
        sorted_scores = sorted(
            [v for k, v in scores.items() if k in weights],
            reverse=True
        )
        peak = sorted_scores[0] if sorted_scores else 0
        second_peak = sorted_scores[1] if len(sorted_scores) > 1 else 0
        overall = int(weighted_sum * 0.6 + peak * 0.30 + second_peak * 0.10)

        sanction_score = scores.get("sanctions", 0)
        if sanction_score == 100:
            overall = 100
        elif sanction_score > 0:
            overall = min(100, overall + sanction_score // 2)

        overall = min(100, overall)

    return {
        "overall_score": overall,
        "scores": scores,
        "evidence": evidence,
        "dimension_status": dimension_status,
        "filled_count": filled_count,
    }


def main():
    """全50カ国 × 全次元のスコアを計算して保存する。"""
    from features.timeseries.store import RiskTimeSeriesStore

    store = RiskTimeSeriesStore()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    print("=" * 70)
    print("全次元スコア一括計算・欠損補完スクリプト")
    print(f"対象国数: {len(TARGET_COUNTRIES)}")
    print(f"対象次元数: {len(ALL_DIMENSIONS)}")
    print(f"日付: {today}")
    print("=" * 70)

    results = {}
    success_count = 0
    total_filled = 0

    for i, country in enumerate(TARGET_COUNTRIES, 1):
        print(f"\n[{i}/{len(TARGET_COUNTRIES)}] {country}...", flush=True)

        try:
            result = calculate_score_for_country(country)

            # 時系列DBに保存
            store.store_score(country, result)
            store.store_daily_summary(country, result, today)

            results[country] = result
            success_count += 1
            total_filled += result["filled_count"]

            # ステータスサマリー
            ok_dims = sum(1 for s in result["dimension_status"].values() if s == "ok")
            fb_dims = result["filled_count"]
            na_dims = sum(1 for s in result["dimension_status"].values() if s == "not_applicable")

            print(f"  Overall: {result['overall_score']}, "
                  f"OK: {ok_dims}, 補完: {fb_dims}, N/A: {na_dims}")

        except Exception as exc:
            print(f"  [ERROR] {exc}")
            traceback.print_exc()

    # サマリーJSON保存
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(data_dir, exist_ok=True)
    summary_path = os.path.join(data_dir, "all_dimensions_scores.json")

    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "countries": len(TARGET_COUNTRIES),
        "dimensions": len(ALL_DIMENSIONS),
        "success": success_count,
        "total_filled_dimensions": total_filled,
        "scores": {
            country: {
                "overall": r["overall_score"],
                "dimensions": r["scores"],
                "filled": r["filled_count"],
            }
            for country, r in results.items()
        },
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 70}")
    print(f"完了: {success_count}/{len(TARGET_COUNTRIES)} カ国")
    print(f"補完次元数: {total_filled}")
    print(f"保存先: {summary_path}")
    print(f"時系列DB: {store.db_path}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
