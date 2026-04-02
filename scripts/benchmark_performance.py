#!/usr/bin/env python3
"""Performance benchmark for SCRI Platform (Stream 7-C)

Measures timing and memory for core operations:
  1. Single risk score calculation
  2. Bulk risk scores (10 countries)
  3. Sanctions screening
  4. Portfolio analysis (5 entities)

Uses time.perf_counter for high-resolution timing and tracemalloc for
memory profiling. Results are written to reports/v07_STREAM7_benchmark.md.

Usage:
    python scripts/benchmark_performance.py [--live]

    --live    Use live API calls (slow, requires network)
              Default: use mocked scoring for fast benchmarks
"""
import argparse
import os
import sys
import time
import tracemalloc
from datetime import datetime
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Benchmark utilities
# ---------------------------------------------------------------------------

@contextmanager
def measure(label: str):
    """Context manager that measures wall-clock time and peak memory."""
    tracemalloc.start()
    t0 = time.perf_counter()
    result = {"label": label}
    try:
        yield result
    finally:
        t1 = time.perf_counter()
        _, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        result["elapsed_s"] = round(t1 - t0, 4)
        result["peak_mem_mb"] = round(peak_mem / (1024 * 1024), 2)


def _make_mock_score(supplier_id, company_name, country=None, location=None):
    """Deterministic mock score for offline benchmarks."""
    from scoring.engine import SupplierRiskScore, Evidence

    score = SupplierRiskScore(supplier_id=supplier_id, company_name=company_name)
    dims = {
        "geo_risk": 25, "conflict": 20, "political": 30, "compliance": 18,
        "disaster": 22, "weather": 12, "typhoon": 10, "maritime": 28,
        "internet": 14, "climate_risk": 20, "economic": 18, "currency": 15,
        "trade": 30, "energy": 22, "port_congestion": 16, "cyber_risk": 15,
        "legal": 10, "health": 8, "humanitarian": 12, "food_security": 10,
        "labor": 8, "aviation": 5,
    }
    for dim, val in dims.items():
        setattr(score, f"{dim}_score", val)
    score.sanction_score = 0
    score.japan_economy_score = 12
    score.evidence.append(Evidence(
        category="benchmark", severity="info",
        description="Mock score for benchmark", source="benchmark"
    ))
    score.calculate_overall()
    return score


# ---------------------------------------------------------------------------
# Benchmark functions
# ---------------------------------------------------------------------------

def bench_single_risk_score(live: bool) -> dict:
    """Benchmark: single country risk score."""
    from scoring.engine import calculate_risk_score

    if live:
        with measure("single_risk_score (live)") as m:
            result = calculate_risk_score("bench_1", "bench_entity",
                                          country="Japan", location="Japan")
    else:
        with patch("scoring.engine.calculate_risk_score",
                   side_effect=_make_mock_score):
            with measure("single_risk_score (mock)") as m:
                result = calculate_risk_score("bench_1", "bench_entity",
                                              country="Japan", location="Japan")
    m["overall_score"] = result.overall_score
    return m


def bench_bulk_risk_scores(live: bool) -> dict:
    """Benchmark: bulk risk scores for 10 countries."""
    from scoring.engine import calculate_risk_score

    countries = [
        "Japan", "China", "Singapore", "Yemen", "Germany",
        "United States", "India", "Brazil", "Nigeria", "Australia",
    ]

    if live:
        with measure("bulk_risk_scores_10 (live)") as m:
            scores = []
            for i, c in enumerate(countries):
                r = calculate_risk_score(f"bulk_{i}", f"bulk_entity",
                                         country=c, location=c)
                scores.append(r.overall_score)
    else:
        with patch("scoring.engine.calculate_risk_score",
                   side_effect=_make_mock_score):
            with measure("bulk_risk_scores_10 (mock)") as m:
                scores = []
                for i, c in enumerate(countries):
                    r = calculate_risk_score(f"bulk_{i}", f"bulk_entity",
                                             country=c, location=c)
                    scores.append(r.overall_score)

    m["count"] = len(scores)
    m["avg_score"] = round(sum(scores) / len(scores), 1) if scores else 0
    return m


def bench_sanctions_screening(live: bool) -> dict:
    """Benchmark: sanctions screening (always hits DB)."""
    from pipeline.sanctions.screener import screen_entity

    entities = [
        ("Toyota Motor Corporation", "Japan"),
        ("Samsung Electronics", "South Korea"),
        ("Rosoboronexport", "Russia"),
        ("Huawei Technologies", "China"),
        ("Mitsubishi Corporation", "Japan"),
    ]

    with measure("sanctions_screening_5") as m:
        results = []
        for name, country in entities:
            r = screen_entity(name, country)
            results.append({"name": name, "matched": r.matched, "score": r.match_score})

    m["entities_screened"] = len(results)
    m["matches_found"] = sum(1 for r in results if r["matched"])
    return m


def bench_portfolio_analysis(live: bool) -> dict:
    """Benchmark: portfolio analysis on 5 entities."""
    from features.analytics.portfolio_analyzer import PortfolioAnalyzer

    entities = [
        {"name": "entity_jp", "country": "Japan", "tier": 1, "share": 0.30},
        {"name": "entity_cn", "country": "China", "tier": 1, "share": 0.25},
        {"name": "entity_sg", "country": "Singapore", "tier": 2, "share": 0.20},
        {"name": "entity_ye", "country": "Yemen", "tier": 3, "share": 0.15},
        {"name": "entity_de", "country": "Germany", "tier": 1, "share": 0.10},
    ]
    analyzer = PortfolioAnalyzer()

    if live:
        with measure("portfolio_analysis_5 (live)") as m:
            report = analyzer.analyze_portfolio(entities)
    else:
        with patch("features.analytics.portfolio_analyzer.calculate_risk_score",
                   side_effect=_make_mock_score):
            with measure("portfolio_analysis_5 (mock)") as m:
                report = analyzer.analyze_portfolio(entities)

    m["portfolio_score"] = round(report.weighted_portfolio_score, 1)
    m["entities_analyzed"] = len(report.entities)
    return m


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results: list[dict], live: bool) -> str:
    """Generate Markdown report from benchmark results."""
    mode = "LIVE (external APIs)" if live else "MOCK (offline)"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# SCRI Platform Performance Benchmark",
        "",
        f"**Date:** {now}",
        f"**Mode:** {mode}",
        f"**Python:** {sys.version.split()[0]}",
        "",
        "---",
        "",
        "## Results",
        "",
        "| Operation | Time (s) | Peak Memory (MB) | Details |",
        "|-----------|----------|-------------------|---------|",
    ]

    for r in results:
        label = r["label"]
        elapsed = r["elapsed_s"]
        mem = r["peak_mem_mb"]
        details_parts = []
        for k, v in r.items():
            if k not in ("label", "elapsed_s", "peak_mem_mb"):
                details_parts.append(f"{k}={v}")
        details = ", ".join(details_parts) if details_parts else "-"
        lines.append(f"| {label} | {elapsed} | {mem} | {details} |")

    lines += [
        "",
        "---",
        "",
        "## Interpretation",
        "",
        "- **Single risk score**: Time for one country through all 24 dimensions",
        "- **Bulk risk scores**: Sequential scoring of 10 countries",
        "- **Sanctions screening**: 5 entity names fuzzy-matched against sanctions DB",
        "- **Portfolio analysis**: Full portfolio report for 5 entities with ranking",
        "",
        "### Performance Targets",
        "",
        "| Operation | Target (mock) | Target (live) |",
        "|-----------|--------------|---------------|",
        "| Single score | < 0.1s | < 30s |",
        "| Bulk 10 | < 1.0s | < 300s |",
        "| Sanctions 5 | < 2.0s | < 2.0s |",
        "| Portfolio 5 | < 1.0s | < 150s |",
        "",
        "---",
        "",
        f"*Generated by `scripts/benchmark_performance.py` on {now}*",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SCRI Performance Benchmark")
    parser.add_argument("--live", action="store_true",
                        help="Use live API calls (slow)")
    args = parser.parse_args()

    print(f"SCRI Performance Benchmark ({'LIVE' if args.live else 'MOCK'} mode)")
    print("=" * 60)

    results = []

    print("\n[1/4] Single risk score...")
    results.append(bench_single_risk_score(args.live))
    print(f"      {results[-1]['elapsed_s']}s, {results[-1]['peak_mem_mb']} MB")

    print("\n[2/4] Bulk risk scores (10 countries)...")
    results.append(bench_bulk_risk_scores(args.live))
    print(f"      {results[-1]['elapsed_s']}s, {results[-1]['peak_mem_mb']} MB")

    print("\n[3/4] Sanctions screening (5 entities)...")
    results.append(bench_sanctions_screening(args.live))
    print(f"      {results[-1]['elapsed_s']}s, {results[-1]['peak_mem_mb']} MB")

    print("\n[4/4] Portfolio analysis (5 entities)...")
    results.append(bench_portfolio_analysis(args.live))
    print(f"      {results[-1]['elapsed_s']}s, {results[-1]['peak_mem_mb']} MB")

    # Generate report
    report_md = generate_report(results, args.live)

    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "reports")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "v07_STREAM7_benchmark.md")
    with open(report_path, "w") as f:
        f.write(report_md)

    print(f"\n{'=' * 60}")
    print(f"Report written to: {report_path}")
    print(f"Total operations: {len(results)}")


if __name__ == "__main__":
    main()
