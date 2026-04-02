"""STREAM 2: Full 24x24 Correlation Matrix Audit with 50 Countries"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from features.timeseries.store import RiskTimeSeriesStore
from config.constants import PRIORITY_COUNTRIES
from scoring.engine import SupplierRiskScore
import numpy as np
import traceback

# All 24 dimension keys (22 weighted + sanctions + japan_economy)
ALL_DIMS = list(SupplierRiskScore.WEIGHTS.keys()) + ["sanctions", "japan_economy"]

# Known data source mapping for double-counting detection
DIM_SOURCES = {
    "geo_risk": ["GDELT"],
    "conflict": ["ACLED"],
    "political": ["Freedom House", "FSI"],
    "compliance": ["FATF", "INFORM", "TI-CPI"],
    "disaster": ["GDACS", "USGS", "FIRMS", "JMA"],
    "weather": ["Open-Meteo"],
    "typhoon": ["NOAA NHC", "NOAA SWPC"],
    "maritime": ["IMF PortWatch"],
    "internet": ["Cloudflare Radar", "IODA"],
    "climate_risk": ["ND-GAIN", "GloFAS", "WRI", "Climate TRACE"],
    "economic": ["World Bank"],
    "currency": ["Frankfurter", "ECB"],
    "trade": ["UN Comtrade"],
    "energy": ["FRED", "EIA"],
    "port_congestion": ["UNCTAD"],
    "cyber_risk": ["OONI", "CISA KEV", "ITU ICT"],
    "legal": ["Caselaw"],
    "health": ["Disease.sh"],
    "humanitarian": ["OCHA FTS", "ReliefWeb"],
    "food_security": ["FEWS NET", "WFP"],
    "labor": ["DoL ILAB", "GSI"],
    "aviation": ["OpenSky"],
    "sanctions": ["OFAC", "EU", "UN", "METI", "BIS", "OFSI", "SECO", "Canada", "DFAT", "MOFA"],
    "japan_economy": ["BOJ", "e-Stat"],
}

# Known causal relationships (upstream -> downstream)
KNOWN_CAUSAL = [
    ("conflict", "humanitarian"),    # Conflict causes humanitarian crises
    ("conflict", "food_security"),   # Conflict disrupts food systems
    ("disaster", "humanitarian"),    # Natural disasters create humanitarian needs
    ("political", "conflict"),       # Political instability leads to conflict
    ("political", "compliance"),     # Political system affects compliance standards
    ("economic", "currency"),        # Economic conditions affect currency
    ("climate_risk", "disaster"),    # Climate change increases disaster frequency
    ("climate_risk", "food_security"), # Climate affects food production
    ("conflict", "geo_risk"),        # Conflict is a component of geopolitical risk
    ("compliance", "labor"),         # Weak compliance correlates with labor issues
]

def shares_source(dim1, dim2):
    """Check if two dimensions share any data source"""
    s1 = set(DIM_SOURCES.get(dim1, []))
    s2 = set(DIM_SOURCES.get(dim2, []))
    return bool(s1 & s2)

def is_known_causal(dim1, dim2):
    """Check if there's a known causal relationship"""
    return (dim1, dim2) in KNOWN_CAUSAL or (dim2, dim1) in KNOWN_CAUSAL

def classify_pair(dim1, dim2, r):
    """Classify a high-correlation pair"""
    if shares_source(dim1, dim2):
        return "DOUBLE_COUNTING"
    if is_known_causal(dim1, dim2):
        return "ACCEPTABLE"
    if abs(r) > 0.90:
        return "SOURCE_PROBLEM"
    return "ACCEPTABLE"

def main():
    errors = []
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    store = RiskTimeSeriesStore()

    # 1. Collect scores for all 50 countries
    score_matrix = []
    valid_countries = []

    for country in PRIORITY_COUNTRIES:
        try:
            latest = store.get_latest(country)
            if latest and "data" in latest and "scores" in latest["data"]:
                scores = latest["data"]["scores"]
                row = [scores.get(dim, 0) for dim in ALL_DIMS]
                score_matrix.append(row)
                valid_countries.append(country)
            else:
                msg = f"No score data found for {country}"
                errors.append(msg)
                print(f"WARNING: {msg}")
        except Exception as e:
            msg = f"Error loading {country}: {e}"
            errors.append(msg)
            print(f"ERROR: {msg}")

    print(f"Loaded scores for {len(valid_countries)}/{len(PRIORITY_COUNTRIES)} countries")

    if len(valid_countries) < 5:
        msg = "Not enough countries with data for correlation analysis"
        errors.append(msg)
        print(f"ERROR: {msg}")
        _write_errors(errors, project_root)
        return

    # 2. Compute correlation matrix
    matrix = np.array(score_matrix)

    # Remove dimensions that are all zeros (no variance)
    active_dims = []
    active_indices = []
    for i, dim in enumerate(ALL_DIMS):
        col = matrix[:, i]
        if np.std(col) > 0:
            active_dims.append(dim)
            active_indices.append(i)
        else:
            msg = f"Zero-variance dimension excluded: {dim} (all values = {col[0]})"
            errors.append(msg)

    active_matrix = matrix[:, active_indices]
    print(f"Active dimensions (non-zero variance): {len(active_dims)}/{len(ALL_DIMS)}")
    print(f"Zero-variance dims: {[d for d in ALL_DIMS if d not in active_dims]}")

    # Pearson correlation
    if len(active_dims) < 2:
        msg = "Not enough active dimensions for correlation"
        errors.append(msg)
        print(f"ERROR: {msg}")
        _write_errors(errors, project_root)
        return

    corr = np.corrcoef(active_matrix.T)

    # 3. Find all pairs with |r| > 0.7
    high_pairs = []
    for i in range(len(active_dims)):
        for j in range(i+1, len(active_dims)):
            r = corr[i][j]
            if np.isnan(r):
                msg = f"NaN correlation between {active_dims[i]} and {active_dims[j]}"
                errors.append(msg)
                continue
            if abs(r) > 0.7:
                dim1, dim2 = active_dims[i], active_dims[j]
                classification = classify_pair(dim1, dim2, r)
                high_pairs.append({
                    "dim1": dim1,
                    "dim2": dim2,
                    "r": round(r, 4),
                    "classification": classification,
                    "reason": _get_reason(dim1, dim2, r, classification),
                })

    high_pairs.sort(key=lambda x: -abs(x["r"]))

    # 4. Generate reports
    reports_dir = os.path.join(project_root, "reports")
    errors_dir = os.path.join(project_root, "errors")
    config_dir = os.path.join(project_root, "config")
    os.makedirs(reports_dir, exist_ok=True)
    os.makedirs(errors_dir, exist_ok=True)
    os.makedirs(config_dir, exist_ok=True)

    # Count by classification
    source_problems = [p for p in high_pairs if p["classification"] == "SOURCE_PROBLEM"]
    double_counting = [p for p in high_pairs if p["classification"] == "DOUBLE_COUNTING"]
    acceptable = [p for p in high_pairs if p["classification"] == "ACCEPTABLE"]

    # Correlation audit report
    report_path = os.path.join(reports_dir, "STREAM2_correlation_audit.md")
    with open(report_path, "w") as f:
        f.write("# STREAM 2: Correlation Audit Report\n\n")
        f.write(f"Generated: {datetime.utcnow().isoformat()}\n\n")
        f.write(f"## Summary\n\n")
        f.write(f"- Countries analyzed: {len(valid_countries)}\n")
        f.write(f"- Active dimensions: {len(active_dims)}\n")
        f.write(f"- High correlation pairs (|r|>0.7): {len(high_pairs)}\n\n")

        f.write(f"### Classification\n\n")
        f.write(f"| Classification | Count | Action |\n")
        f.write(f"|---------------|-------|--------|\n")
        f.write(f"| SOURCE_PROBLEM | {len(source_problems)} | Needs alternative data source |\n")
        f.write(f"| DOUBLE_COUNTING | {len(double_counting)} | Needs source separation |\n")
        f.write(f"| ACCEPTABLE | {len(acceptable)} | No action needed |\n\n")

        f.write(f"### All High-Correlation Pairs\n\n")
        f.write(f"| Dim 1 | Dim 2 | r | Classification | Reason |\n")
        f.write(f"|-------|-------|---|---------------|--------|\n")
        for p in high_pairs:
            f.write(f"| {p['dim1']} | {p['dim2']} | {p['r']:.4f} | {p['classification']} | {p['reason']} |\n")

        if not high_pairs:
            f.write("\n*No high-correlation pairs found above |r|>0.7 threshold.*\n")

        if source_problems:
            f.write(f"\n### SOURCE_PROBLEM Pairs (Action Required)\n\n")
            for p in source_problems:
                f.write(f"#### {p['dim1']} <-> {p['dim2']} (r={p['r']:.4f})\n\n")
                f.write(f"These dimensions should be conceptually independent but show high correlation.\n")
                f.write(f"**Recommendation**: Replace primary data source for one dimension.\n\n")

        if double_counting:
            f.write(f"\n### DOUBLE_COUNTING Pairs (Action Required)\n\n")
            for p in double_counting:
                shared = set(DIM_SOURCES.get(p['dim1'], [])) & set(DIM_SOURCES.get(p['dim2'], []))
                f.write(f"#### {p['dim1']} <-> {p['dim2']} (r={p['r']:.4f})\n\n")
                f.write(f"Shared sources: {shared}\n")
                f.write(f"**Recommendation**: Separate data sources.\n\n")

        # Full correlation matrix heatmap (text-based)
        f.write(f"\n## Full Correlation Matrix (Active Dimensions)\n\n")
        f.write(f"Dimensions: {', '.join(active_dims)}\n\n")
        f.write(f"| | " + " | ".join(d[:6] for d in active_dims) + " |\n")
        f.write(f"|" + "---|" * (len(active_dims) + 1) + "\n")
        for i, dim in enumerate(active_dims):
            row_vals = []
            for j in range(len(active_dims)):
                val = corr[i][j]
                if np.isnan(val):
                    row_vals.append("NaN")
                else:
                    row_vals.append(f"{val:.2f}")
            f.write(f"| {dim[:6]} | " + " | ".join(row_vals) + " |\n")

        # Per-country score summary
        f.write(f"\n## Per-Country Score Summary\n\n")
        f.write(f"| Country | " + " | ".join(d[:6] for d in active_dims) + " |\n")
        f.write(f"|" + "---|" * (len(active_dims) + 1) + "\n")
        for ci, country in enumerate(valid_countries):
            row = [str(int(score_matrix[ci][active_indices[di]])) for di in range(len(active_dims))]
            f.write(f"| {country} | " + " | ".join(row) + " |\n")

    # Accepted correlations YAML
    yaml_path = os.path.join(config_dir, "accepted_correlations.yaml")
    with open(yaml_path, "w") as f:
        f.write("# Accepted high-correlation pairs\n")
        f.write("# These are either causally related or have known explanations\n")
        f.write(f"# Generated: {datetime.utcnow().isoformat()}\n\n")
        f.write("accepted_pairs:\n")
        for p in acceptable:
            f.write(f"  - dim1: {p['dim1']}\n")
            f.write(f"    dim2: {p['dim2']}\n")
            f.write(f"    r: {p['r']}\n")
            f.write(f"    reason: \"{p['reason']}\"\n\n")

    # Write errors log
    _write_errors(errors, project_root)

    # Summary
    print(f"\n=== Correlation Audit Results ===")
    print(f"High-correlation pairs: {len(high_pairs)}")
    print(f"  SOURCE_PROBLEM: {len(source_problems)}")
    print(f"  DOUBLE_COUNTING: {len(double_counting)}")
    print(f"  ACCEPTABLE: {len(acceptable)}")
    print(f"\nReports written to:")
    print(f"  {report_path}")
    print(f"  {yaml_path}")
    if errors:
        print(f"  {os.path.join(errors_dir, 'STREAM2_errors.log')} ({len(errors)} entries)")
    print(f"\nSTREAM 2 correlation audit complete.")

def _get_reason(dim1, dim2, r, classification):
    if classification == "DOUBLE_COUNTING":
        shared = set(DIM_SOURCES.get(dim1, [])) & set(DIM_SOURCES.get(dim2, []))
        return f"Shared sources: {shared}"
    if classification == "ACCEPTABLE":
        if is_known_causal(dim1, dim2):
            return "Known causal relationship"
        return f"Natural correlation (r={r:.3f} < 0.90 threshold)"
    return f"Conceptually independent but r={r:.4f} > 0.90"

def _write_errors(errors, project_root):
    """Write errors to STREAM2_errors.log"""
    errors_dir = os.path.join(project_root, "errors")
    os.makedirs(errors_dir, exist_ok=True)
    error_path = os.path.join(errors_dir, "STREAM2_errors.log")
    with open(error_path, "w") as f:
        f.write(f"STREAM 2: Correlation Audit Error Log\n")
        f.write(f"Generated: {datetime.utcnow().isoformat()}\n")
        f.write(f"{'='*60}\n\n")
        if errors:
            for i, err in enumerate(errors, 1):
                f.write(f"[{i}] {err}\n")
        else:
            f.write("No errors encountered.\n")
        f.write(f"\nTotal errors: {len(errors)}\n")

if __name__ == "__main__":
    main()
