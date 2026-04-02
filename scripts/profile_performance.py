#!/usr/bin/env python3
"""パフォーマンスプロファイリングスクリプト

以下の処理時間を計測してレポートを生成:
  1. get_risk_score (単件): cold/warm cache
  2. analyze_bom: Tier推定あり/なし
  3. bulk_assess: 10/50カ国

出力: reports/v10_performance.md
"""
import sys
import os
import time
import statistics
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def timer(func, *args, **kwargs):
    """関数実行時間を計測（秒）"""
    start = time.perf_counter()
    try:
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        return elapsed, result, None
    except Exception as e:
        elapsed = time.perf_counter() - start
        return elapsed, None, str(e)


def profile_risk_score():
    """1. get_risk_score 単件計測（cold / warm）"""
    print("\n[1] get_risk_score プロファイリング...")
    from scoring.engine import calculate_risk_score

    test_locations = ["Japan", "United States", "China", "Germany", "Indonesia"]
    results = {"cold": [], "warm": []}

    # Cold run（初回呼び出し - データ取得含む）
    for loc in test_locations:
        elapsed, _, err = timer(
            calculate_risk_score,
            supplier_id=f"perf_{loc}",
            company_name=f"perf_{loc}",
            country=loc,
            location=loc,
        )
        results["cold"].append({"location": loc, "time_s": elapsed, "error": err})
        print(f"  Cold {loc}: {elapsed:.2f}s {'(error: ' + err + ')' if err else ''}")

    # Warm run（2回目 - キャッシュヒット期待）
    for loc in test_locations:
        elapsed, _, err = timer(
            calculate_risk_score,
            supplier_id=f"perf_{loc}",
            company_name=f"perf_{loc}",
            country=loc,
            location=loc,
        )
        results["warm"].append({"location": loc, "time_s": elapsed, "error": err})
        print(f"  Warm {loc}: {elapsed:.2f}s {'(error: ' + err + ')' if err else ''}")

    return results


def profile_bom_analysis():
    """2. analyze_bom 計測（Tier推定あり/なし）"""
    print("\n[2] analyze_bom プロファイリング...")

    sample_bom = [
        {"part_id": "P001", "part_name": "Battery Cell", "supplier_name": "Samsung SDI",
         "supplier_country": "South Korea", "material": "battery", "hs_code": "8507",
         "quantity": 100, "unit_cost_usd": 45.0, "is_critical": True},
        {"part_id": "P002", "part_name": "Controller IC", "supplier_name": "Texas Instruments",
         "supplier_country": "United States", "material": "semiconductor", "hs_code": "8542",
         "quantity": 200, "unit_cost_usd": 12.0, "is_critical": True},
        {"part_id": "P003", "part_name": "Steel Casing", "supplier_name": "Nippon Steel",
         "supplier_country": "Japan", "material": "steel", "hs_code": "7209",
         "quantity": 50, "unit_cost_usd": 30.0, "is_critical": False},
        {"part_id": "P004", "part_name": "Copper Wire", "supplier_name": "Freeport McMoRan",
         "supplier_country": "Indonesia", "material": "copper", "hs_code": "7408",
         "quantity": 500, "unit_cost_usd": 5.0, "is_critical": False},
        {"part_id": "P005", "part_name": "LCD Display", "supplier_name": "BOE Technology",
         "supplier_country": "China", "material": "display", "hs_code": "9013",
         "quantity": 100, "unit_cost_usd": 25.0, "is_critical": True},
    ]

    results = {"without_tier": None, "with_tier": None}

    try:
        from features.goods_layer.bom_analyzer import BOMAnalyzer
        analyzer = BOMAnalyzer()

        # Tier推定なし
        elapsed, res, err = timer(analyzer.analyze, sample_bom, "TestProduct", infer_tiers=False)
        results["without_tier"] = {"time_s": elapsed, "error": err}
        print(f"  BOM分析 (Tier推定なし): {elapsed:.2f}s {'(error: ' + err + ')' if err else ''}")

        # Tier推定あり
        elapsed, res, err = timer(analyzer.analyze, sample_bom, "TestProduct", infer_tiers=True)
        results["with_tier"] = {"time_s": elapsed, "error": err}
        print(f"  BOM分析 (Tier推定あり): {elapsed:.2f}s {'(error: ' + err + ')' if err else ''}")

    except ImportError as e:
        print(f"  BOMAnalyzer import error: {e}")
        results["error"] = str(e)
    except Exception as e:
        print(f"  BOM分析エラー: {e}")
        results["error"] = str(e)

    return results


def profile_bulk_assess():
    """3. bulk_assess 計測（10/50カ国）"""
    print("\n[3] bulk_assess プロファイリング...")
    from scoring.engine import calculate_risk_score

    countries_10 = ["Japan", "United States", "China", "Germany", "India",
                    "Brazil", "Indonesia", "Vietnam", "Thailand", "Singapore"]
    countries_50 = [
        "Japan", "United States", "China", "Germany", "India", "Brazil",
        "Indonesia", "Vietnam", "Thailand", "Singapore", "South Korea",
        "Taiwan", "Malaysia", "Philippines", "Myanmar", "Cambodia",
        "United Kingdom", "France", "Italy", "Canada", "Australia",
        "Russia", "Ukraine", "Poland", "Netherlands", "Switzerland",
        "Turkey", "Saudi Arabia", "UAE", "Iran", "Iraq", "Israel",
        "Qatar", "Yemen", "South Africa", "Nigeria", "Kenya", "Ethiopia",
        "Egypt", "South Sudan", "Somalia", "Mexico", "Colombia",
        "Venezuela", "Argentina", "Chile", "Bangladesh", "Pakistan",
        "Sri Lanka", "North Korea",
    ]

    results = {}

    # 10カ国
    print(f"  10カ国バッチ開始...")
    elapsed_10, _, _ = timer(_bulk_score, countries_10)
    results["10_countries"] = {"time_s": elapsed_10, "per_country_s": elapsed_10 / 10}
    print(f"  10カ国: {elapsed_10:.2f}s (avg {elapsed_10/10:.2f}s/country)")

    # 50カ国
    print(f"  50カ国バッチ開始...")
    elapsed_50, _, _ = timer(_bulk_score, countries_50)
    results["50_countries"] = {"time_s": elapsed_50, "per_country_s": elapsed_50 / 50}
    print(f"  50カ国: {elapsed_50:.2f}s (avg {elapsed_50/50:.2f}s/country)")

    return results


def _bulk_score(countries):
    """複数国のリスクスコアを一括計算"""
    from scoring.engine import calculate_risk_score
    results = []
    for c in countries:
        try:
            score = calculate_risk_score(
                supplier_id=f"bulk_{c}", company_name=f"bulk_{c}",
                country=c, location=c,
            )
            results.append({"location": c, "overall": score.overall_risk})
        except Exception as e:
            results.append({"location": c, "error": str(e)})
    return results


def generate_report(risk_score_results, bom_results, bulk_results):
    """結果をMarkdownレポートとして出力"""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# SCRI v1.0 パフォーマンスプロファイリングレポート",
        f"\n実行日時: {now}",
        "",
        "## 1. get_risk_score（単件）",
        "",
        "### Cold Run（初回呼び出し）",
        "| Location | Time (s) | Status |",
        "|----------|----------|--------|",
    ]

    for r in risk_score_results["cold"]:
        status = "Error" if r["error"] else "OK"
        lines.append(f"| {r['location']} | {r['time_s']:.2f} | {status} |")

    cold_times = [r["time_s"] for r in risk_score_results["cold"] if not r["error"]]
    if cold_times:
        lines.append(f"\n**Cold平均: {statistics.mean(cold_times):.2f}s** / 中央値: {statistics.median(cold_times):.2f}s")

    lines.extend([
        "",
        "### Warm Run（2回目呼び出し）",
        "| Location | Time (s) | Status |",
        "|----------|----------|--------|",
    ])

    for r in risk_score_results["warm"]:
        status = "Error" if r["error"] else "OK"
        lines.append(f"| {r['location']} | {r['time_s']:.2f} | {status} |")

    warm_times = [r["time_s"] for r in risk_score_results["warm"] if not r["error"]]
    if warm_times:
        lines.append(f"\n**Warm平均: {statistics.mean(warm_times):.2f}s** / 中央値: {statistics.median(warm_times):.2f}s")

    if cold_times and warm_times:
        speedup = statistics.mean(cold_times) / statistics.mean(warm_times) if statistics.mean(warm_times) > 0 else 0
        lines.append(f"\n**キャッシュ効果: {speedup:.1f}x 高速化**")

    # BOM分析
    lines.extend(["", "## 2. BOM分析", ""])
    if "error" in bom_results:
        lines.append(f"エラー: {bom_results['error']}")
    else:
        if bom_results.get("without_tier"):
            t = bom_results["without_tier"]
            lines.append(f"- **Tier推定なし**: {t['time_s']:.2f}s {'(Error)' if t.get('error') else ''}")
        if bom_results.get("with_tier"):
            t = bom_results["with_tier"]
            lines.append(f"- **Tier推定あり**: {t['time_s']:.2f}s {'(Error)' if t.get('error') else ''}")
        if bom_results.get("without_tier") and bom_results.get("with_tier"):
            if not bom_results["without_tier"].get("error") and not bom_results["with_tier"].get("error"):
                overhead = bom_results["with_tier"]["time_s"] - bom_results["without_tier"]["time_s"]
                lines.append(f"- **Tier推定オーバーヘッド**: {overhead:.2f}s")

    # バルクアセス
    lines.extend(["", "## 3. バルクアセス（bulk_assess）", ""])
    for key, data in bulk_results.items():
        label = key.replace("_", " ")
        lines.append(f"- **{label}**: {data['time_s']:.2f}s total / {data['per_country_s']:.2f}s per country")

    if "10_countries" in bulk_results and "50_countries" in bulk_results:
        ratio = bulk_results["50_countries"]["time_s"] / bulk_results["10_countries"]["time_s"] if bulk_results["10_countries"]["time_s"] > 0 else 0
        lines.append(f"- **スケーリング係数**: 5x国数で {ratio:.1f}x 時間")

    # サマリ
    lines.extend([
        "",
        "## サマリ",
        "",
        "| メトリック | 値 |",
        "|-----------|-----|",
    ])
    if cold_times:
        lines.append(f"| Cold単件平均 | {statistics.mean(cold_times):.2f}s |")
    if warm_times:
        lines.append(f"| Warm単件平均 | {statistics.mean(warm_times):.2f}s |")
    if "10_countries" in bulk_results:
        lines.append(f"| 10カ国バッチ | {bulk_results['10_countries']['time_s']:.2f}s |")
    if "50_countries" in bulk_results:
        lines.append(f"| 50カ国バッチ | {bulk_results['50_countries']['time_s']:.2f}s |")

    lines.append("")

    report_path = os.path.join(REPORTS_DIR, "v10_performance.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nレポート出力: {report_path}")
    return report_path


def main():
    print("=" * 60)
    print("SCRI v1.0 パフォーマンスプロファイリング")
    print("=" * 60)

    risk_results = profile_risk_score()
    bom_results = profile_bom_analysis()
    bulk_results = profile_bulk_assess()

    report_path = generate_report(risk_results, bom_results, bulk_results)
    print(f"\n完了: {report_path}")


if __name__ == "__main__":
    main()
