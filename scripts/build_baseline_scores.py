#!/usr/bin/env python3
"""STREAM 1: Build baseline 24-dimension risk scores for all 50 priority countries.

Calculates risk scores using the scoring engine and stores them in the
timeseries DB. Generates a summary report and error log.
"""
import sys
import os
import time
import traceback
from datetime import datetime

# Ensure project root is on the path so imports work
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config.constants import PRIORITY_COUNTRIES, RISK_THRESHOLDS
from scoring.engine import calculate_risk_score
from features.timeseries.store import RiskTimeSeriesStore

# All 24 dimension keys in the order they appear in SupplierRiskScore.to_dict()
DIMENSION_KEYS = [
    "sanctions", "geo_risk", "disaster", "legal",
    "maritime", "conflict", "economic", "currency",
    "health", "humanitarian", "weather", "typhoon",
    "compliance", "food_security", "trade", "internet",
    "political", "labor", "port_congestion", "aviation",
    "energy", "japan_economy", "climate_risk", "cyber_risk",
]

# Directories for outputs
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
ERRORS_DIR = os.path.join(PROJECT_ROOT, "errors")
REPORT_PATH = os.path.join(REPORTS_DIR, "STREAM1_complete.md")
ERROR_LOG_PATH = os.path.join(ERRORS_DIR, "STREAM1_errors.log")


def classify_risk_level(overall_score: int) -> str:
    """Return risk level string based on score thresholds."""
    if overall_score >= RISK_THRESHOLDS["CRITICAL"]:
        return "CRITICAL"
    if overall_score >= RISK_THRESHOLDS["HIGH"]:
        return "HIGH"
    if overall_score >= RISK_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    if overall_score >= RISK_THRESHOLDS["LOW"]:
        return "LOW"
    return "MINIMAL"


def main():
    start_time = time.time()
    run_timestamp = datetime.utcnow().isoformat()

    # Ensure output directories exist
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(ERRORS_DIR, exist_ok=True)

    # Initialize timeseries store
    store = RiskTimeSeriesStore()

    # Tracking structures
    successes = []          # list of (country, score_dict)
    failures = []           # list of (country, error_message)
    error_details = []      # list of full traceback strings

    total = len(PRIORITY_COUNTRIES)
    print(f"=== STREAM 1: Baseline Risk Score Build ===")
    print(f"Scoring {total} priority countries across 24 dimensions")
    print(f"Started at: {run_timestamp}")
    print(f"{'='*60}")

    for i, country in enumerate(PRIORITY_COUNTRIES, 1):
        print(f"\n[{i}/{total}] Scoring {country}...", end=" ", flush=True)
        country_start = time.time()

        try:
            # Use country name as both supplier_id and company_name for baseline
            supplier_id = f"baseline_{country.lower().replace(' ', '_')}"
            company_name = f"Country Baseline: {country}"

            result = calculate_risk_score(
                supplier_id=supplier_id,
                company_name=company_name,
                country=country,
                location=country,
            )
            score_dict = result.to_dict()

            # Store in timeseries DB
            store.store_score(location=country, score_dict=score_dict)
            store.store_daily_summary(location=country, score_dict=score_dict)

            elapsed = time.time() - country_start
            overall = score_dict["overall_score"]
            level = score_dict["risk_level"]
            successes.append((country, score_dict))
            print(f"OK  score={overall} ({level})  [{elapsed:.1f}s]")

        except Exception as e:
            elapsed = time.time() - country_start
            error_msg = str(e)
            tb = traceback.format_exc()
            failures.append((country, error_msg))
            error_details.append(f"[{datetime.utcnow().isoformat()}] {country}: {error_msg}\n{tb}")
            print(f"FAILED  [{elapsed:.1f}s] -- {error_msg}")

    total_elapsed = time.time() - start_time

    # -------------------------------------------------------------------------
    # Write error log
    # -------------------------------------------------------------------------
    with open(ERROR_LOG_PATH, "w", encoding="utf-8") as ef:
        ef.write(f"STREAM 1 Error Log -- {run_timestamp}\n")
        ef.write(f"{'='*60}\n\n")
        if error_details:
            for detail in error_details:
                ef.write(detail)
                ef.write("\n" + "-" * 40 + "\n\n")
        else:
            ef.write("No errors encountered.\n")

    # -------------------------------------------------------------------------
    # Build summary report
    # -------------------------------------------------------------------------
    success_count = len(successes)
    fail_count = len(failures)

    # Risk level distribution
    level_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "MINIMAL": 0}
    for _, sd in successes:
        lvl = sd.get("risk_level", "MINIMAL")
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    # Top 10 highest risk
    sorted_countries = sorted(successes, key=lambda x: x[1]["overall_score"], reverse=True)
    top10 = sorted_countries[:10]

    # Per-dimension averages
    dim_totals = {d: 0 for d in DIMENSION_KEYS}
    for _, sd in successes:
        scores = sd.get("scores", {})
        for d in DIMENSION_KEYS:
            dim_totals[d] += scores.get(d, 0)

    dim_averages = {}
    if success_count > 0:
        dim_averages = {d: dim_totals[d] / success_count for d in DIMENSION_KEYS}

    # Sort dimensions by average score descending
    sorted_dims = sorted(dim_averages.items(), key=lambda x: x[1], reverse=True)

    # Build markdown report
    lines = []
    lines.append("# STREAM 1: Baseline Risk Score Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.utcnow().isoformat()}")
    lines.append(f"**Runtime:** {total_elapsed:.1f} seconds ({total_elapsed/60:.1f} minutes)")
    lines.append(f"**Platform version:** SCRI v0.4.0")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Success / Failure summary
    lines.append("## Completion Summary")
    lines.append("")
    lines.append(f"- **Successful:** {success_count} / {total}")
    lines.append(f"- **Failed:** {fail_count} / {total}")
    lines.append(f"- **Success rate:** {success_count/total*100:.1f}%")
    lines.append("")

    if failures:
        lines.append("### Failed Countries")
        lines.append("")
        for country, err in failures:
            lines.append(f"- **{country}**: {err}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Risk level distribution
    lines.append("## Score Distribution")
    lines.append("")
    lines.append("| Risk Level | Count | Percentage |")
    lines.append("|------------|-------|------------|")
    for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL"]:
        cnt = level_counts[level]
        pct = (cnt / success_count * 100) if success_count > 0 else 0
        bar = "#" * int(pct / 2)
        lines.append(f"| {level} | {cnt} | {pct:.1f}% {bar} |")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Top 10
    lines.append("## Top 10 Highest Risk Countries")
    lines.append("")
    lines.append("| Rank | Country | Overall Score | Risk Level |")
    lines.append("|------|---------|---------------|------------|")
    for rank, (country, sd) in enumerate(top10, 1):
        lines.append(f"| {rank} | {country} | {sd['overall_score']} | {sd['risk_level']} |")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Per-dimension averages
    lines.append("## Per-Dimension Global Averages")
    lines.append("")
    lines.append("Dimensions sorted by average score (highest risk first):")
    lines.append("")
    lines.append("| Dimension | Average Score | Assessment |")
    lines.append("|-----------|---------------|------------|")
    for dim, avg in sorted_dims:
        assessment = classify_risk_level(int(avg))
        bar = "#" * int(avg / 2)
        lines.append(f"| {dim} | {avg:.1f} | {assessment} {bar} |")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Full country table
    lines.append("## All Country Scores")
    lines.append("")
    lines.append("| Country | Overall | Level |")
    lines.append("|---------|---------|-------|")
    for country, sd in sorted_countries:
        lines.append(f"| {country} | {sd['overall_score']} | {sd['risk_level']} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*Report generated by STREAM 1 build_baseline_scores.py*")

    report_content = "\n".join(lines)

    with open(REPORT_PATH, "w", encoding="utf-8") as rf:
        rf.write(report_content)

    # -------------------------------------------------------------------------
    # Print final summary to console
    # -------------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"STREAM 1 COMPLETE")
    print(f"{'='*60}")
    print(f"  Successes: {success_count}/{total}")
    print(f"  Failures:  {fail_count}/{total}")
    print(f"  Runtime:   {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")
    print(f"\nRisk Distribution:")
    for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL"]:
        print(f"  {level:10s}: {level_counts[level]}")
    if top10:
        print(f"\nTop 5 Highest Risk:")
        for rank, (country, sd) in enumerate(top10[:5], 1):
            print(f"  {rank}. {country}: {sd['overall_score']} ({sd['risk_level']})")
    print(f"\nReport:    {REPORT_PATH}")
    print(f"Error log: {ERROR_LOG_PATH}")


if __name__ == "__main__":
    main()
