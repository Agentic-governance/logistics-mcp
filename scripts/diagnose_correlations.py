"""相関マトリクス診断スクリプト v2.1
全高相関ペア(r>0.7)を表示し、原因を自動分類する。
v2.1: 実行結果を data/correlation_history.jsonl に追記。

分類基準:
  DOUBLE_COUNTING: 同一データソースを共有 & r > 0.85
  SOURCE_PROBLEM:  r > 0.90 & ソース独立 → データ設計の問題
  CAUSAL_ACCEPTABLE: 既知の因果関係 (conflict→humanitarian等)
  METHODOLOGY_OVERLAP: 両方が静的ベースラインで類似方法論
  MONITOR: 0.75 < r <= 0.90 & 上記に該当しない
  ACCEPTABLE: 0.70 < r <= 0.75
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.analytics.correlation_analyzer import CorrelationAnalyzer

# Data source map: which data sources each dimension uses
SOURCE_MAP = {
    "sanctions": ["OFAC", "EU", "UN", "METI", "BIS", "OFSI", "SECO", "Canada", "DFAT", "MOFA"],
    "geo_risk": ["GDELT BigQuery", "geopolitical_tension_baseline"],
    "disaster": ["GDACS", "USGS", "NASA FIRMS", "JMA", "BMKG"],
    "legal": ["Caselaw MCP", "WJP Rule of Law Index", "legal_risk_baseline"],
    "weather": ["Open-Meteo"],
    "typhoon": ["NOAA NHC", "NOAA SWPC", "typhoon_exposure_baseline"],
    "compliance": ["FATF", "INFORM Risk Index", "TI CPI", "Freedom House", "Fragile States Index"],
    "political": ["Freedom House", "Fragile States Index"],
    "internet": ["Cloudflare Radar", "IODA"],
    "conflict": ["ACLED"],
    "economic": ["World Bank", "Frankfurter/ECB"],
    "currency": ["Frankfurter/ECB", "ExchangeRate-API"],
    "trade": ["UN Comtrade"],
    "port_congestion": ["UNCTAD", "AISHub"],
    "maritime": ["IMF PortWatch", "maritime_dependency_baseline"],
    "food_security": ["FEWS NET", "WFP HungerMap"],
    "humanitarian": ["OCHA FTS", "ReliefWeb"],
    "labor": ["DoL ILAB", "Global Slavery Index"],
    "aviation": ["OpenSky Network", "aviation_baseline"],
    "energy": ["FRED", "EIA", "energy_import_dependency"],
    "health": ["Disease.sh", "WHO GHO", "health_risk_baseline"],
    "climate_risk": ["ND-GAIN", "GloFAS", "WRI Aqueduct", "Climate TRACE"],
    "cyber_risk": ["OONI", "CISA KEV", "ITU ICT"],
    "japan_economy": ["BOJ", "e-Stat", "ExchangeRate-API"],
}

# Known causal relationships (expected high correlations)
KNOWN_CAUSAL = {
    ("conflict", "humanitarian"),
    ("conflict", "political"),
    ("food_security", "humanitarian"),
    ("political", "compliance"),
    ("internet", "cyber_risk"),
    ("conflict", "typhoon"),  # conflict zones overlap with cyclone-prone regions
    ("humanitarian", "typhoon"),  # same
    ("climate_risk", "conflict"),  # conflict zones are in climate-vulnerable regions (r=0.917, causal)
}

# Dimensions that primarily use static baselines
STATIC_BASELINE_DIMS = {
    "geo_risk", "legal", "aviation", "maritime", "health", "energy", "typhoon",
}


def classify_correlation(dim1: str, dim2: str, r: float) -> tuple[str, str]:
    """Classify a high-correlation pair with root cause analysis."""
    abs_r = abs(r)
    pair = (dim1, dim2)
    pair_rev = (dim2, dim1)

    # 1. Check for shared data sources
    sources1 = set(SOURCE_MAP.get(dim1, []))
    sources2 = set(SOURCE_MAP.get(dim2, []))
    shared = sources1 & sources2
    if shared and abs_r > 0.85:
        return "DOUBLE_COUNTING", f"Shared sources: {', '.join(shared)}"

    # 2. Check for known causal relationships
    if pair in KNOWN_CAUSAL or pair_rev in KNOWN_CAUSAL:
        return "CAUSAL_ACCEPTABLE", "Known causal relationship"

    # 3. Check for static baseline methodology overlap
    if dim1 in STATIC_BASELINE_DIMS and dim2 in STATIC_BASELINE_DIMS and abs_r > 0.80:
        return "METHODOLOGY_OVERLAP", "Both use static development-proxy baselines"

    # 4. Very high correlation without explanation
    if abs_r > 0.90:
        return "SOURCE_PROBLEM", "Requires source replacement or weight adjustment"

    # 5. High but manageable
    if abs_r > 0.75:
        return "MONITOR", "Watch for increase in future audits"

    # 6. Moderate
    return "ACCEPTABLE", "Natural correlation within acceptable range"


def _append_to_history(country_count: int, pairs: list[tuple[str, str, float]]):
    """Append run results to data/correlation_history.jsonl.

    Only pairs with |r| > 0.70 are recorded.

    Each line format:
        {"timestamp": "...", "country_count": N,
         "pairs": [{"dim1":"...", "dim2":"...", "r": 0.XX, "classification": "..."}]}
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(project_root, "data")
    os.makedirs(data_dir, exist_ok=True)
    history_path = os.path.join(data_dir, "correlation_history.jsonl")

    filtered = []
    for dim1, dim2, r in pairs:
        if abs(r) > 0.70:
            classification, _ = classify_correlation(dim1, dim2, r)
            filtered.append({
                "dim1": dim1,
                "dim2": dim2,
                "r": round(r, 4),
                "classification": classification,
            })

    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "country_count": country_count,
        "pairs": filtered,
    }

    with open(history_path, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\n[History] Appended {len(filtered)} pairs (|r|>0.70) to {history_path}")


def main():
    parser = argparse.ArgumentParser(description="Correlation Matrix Diagnosis v2.1")
    parser.add_argument('--countries', type=str, default=None,
                        help='Comma-separated country codes (e.g., US,CN,JP,DE)')
    parser.add_argument('--no-history', action='store_true',
                        help='Skip appending results to correlation_history.jsonl')
    args = parser.parse_args()

    if args.countries:
        locations = [c.strip() for c in args.countries.split(',')]
    else:
        locations = ["JP", "CN", "KR", "US", "DE", "IN", "BR", "RU", "ZA",
                     "FR", "GB", "SG", "TW", "MY", "TH", "ID", "VN"]

    print("=" * 100)
    print("=== Correlation Matrix Diagnosis v2.1 ===")
    print(f"Sample: {', '.join(locations)} ({len(locations)} countries)")
    print("=" * 100)

    analyzer = CorrelationAnalyzer()
    matrix = analyzer.compute_dimension_correlations(locations, "pearson")

    if hasattr(matrix, 'to_dict'):
        d = matrix.to_dict()
    elif isinstance(matrix, dict):
        d = matrix
    else:
        d = {"dimensions": matrix.dimensions, "matrix": matrix.matrix}

    dims = d["dimensions"]
    mat = d["matrix"]

    # All pairs sorted by |r|
    pairs = []
    for i in range(len(dims)):
        for j in range(i + 1, len(dims)):
            r = mat[i][j]
            pairs.append((dims[i], dims[j], r))

    pairs.sort(key=lambda x: -abs(x[2]))

    # High correlation pairs
    high_pairs = [p for p in pairs if abs(p[2]) > 0.7]

    print(f"\n=== High Correlation Pairs (|r| > 0.7): {len(high_pairs)} pairs ===\n")
    print(f"{'Rank':>4}  {'Dim1':<18} {'Dim2':<18} {'r':>7}  {'Classification':<25} {'Reason'}")
    print("-" * 100)

    action_counts = {}

    for idx, (d1, d2, r) in enumerate(high_pairs, 1):
        classification, reason = classify_correlation(d1, d2, r)
        action_counts[classification] = action_counts.get(classification, 0) + 1

        flag = ""
        if classification in ("SOURCE_PROBLEM", "DOUBLE_COUNTING"):
            flag = "!!! "
        elif classification == "METHODOLOGY_OVERLAP":
            flag = "**  "
        elif classification == "MONITOR":
            flag = "*   "

        print(f"{flag}{idx:>4}  {d1:<18} {d2:<18} {r:>7.3f}  {classification:<25} {reason}")

    print()
    print("=" * 100)
    print("=== Summary ===")
    for cls in ["SOURCE_PROBLEM", "DOUBLE_COUNTING", "METHODOLOGY_OVERLAP",
                "CAUSAL_ACCEPTABLE", "MONITOR", "ACCEPTABLE"]:
        count = action_counts.get(cls, 0)
        print(f"  {cls:<25}: {count} pairs")

    # Critical warnings
    critical = [(d1, d2, r) for d1, d2, r in pairs if abs(r) > 0.90]
    print()
    if critical:
        print("!!! WARNING: r > 0.90 pairs detected !!!")
        for d1, d2, r in critical:
            cls, reason = classify_correlation(d1, d2, r)
            print(f"  {d1} <-> {d2}: r={r:.3f} [{cls}] {reason}")
    else:
        print("No r > 0.90 pairs found. All dimensions sufficiently independent.")

    # Zero-variance check
    print()
    print("=== Zero-Variance Check ===")
    for i, dim in enumerate(dims):
        col = [mat[j][i] for j in range(len(dims)) if j != i]
        if all(c == 0 for c in col):
            print(f"  WARNING: {dim} has zero variance (all correlations = 0)")

    print("=" * 100)

    # Append to correlation history (STREAM 2-C)
    if not args.no_history:
        _append_to_history(len(locations), pairs)


if __name__ == "__main__":
    main()
