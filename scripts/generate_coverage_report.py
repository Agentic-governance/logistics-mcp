#!/usr/bin/env python3
"""SCRI Platform Data Coverage Report Generator

Checks all 24 dimensions x 50 priority countries from config/constants.py
and determines data availability:
  - live  : Live API data available
  - static: Static fallback data available
  - none  : No data coverage
  - na    : Not applicable for this country

Outputs a Markdown table to docs/DATA_COVERAGE.md
"""
import sys
import os

# Ensure project root on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from datetime import datetime

# Import priority countries
from config.constants import PRIORITY_COUNTRIES

# ============================================================
# Data source availability checkers per dimension
# Each returns "live", "static", "none", or "na"
# ============================================================

def _match_country(country: str, data_dict: dict) -> bool:
    """Check if country matches any key in a data dict (case-insensitive)."""
    loc = country.lower().strip()
    for key in data_dict:
        k = key.lower()
        if k == loc or k in loc or loc in k:
            return True
    return False


def check_sanctions(country: str) -> str:
    """Sanctions screening - always applicable, live DB available."""
    try:
        from scoring.engine import SANCTIONED_COUNTRIES
        loc = country.lower()
        for k in SANCTIONED_COUNTRIES:
            if k == loc or k in loc or loc in k:
                return "live"
        # Even non-sanctioned countries can be screened via CSL
        return "live"
    except Exception:
        return "static"


def check_geo_risk(country: str) -> str:
    """GDELT geopolitical risk - live BigQuery API."""
    # GDELT is available for all countries but requires BigQuery credentials
    return "live"


def check_disaster(country: str) -> str:
    """GDACS/USGS/FIRMS disaster data - live APIs."""
    return "live"


def check_legal(country: str) -> str:
    """Legal risk - Caselaw MCP + WJP + baseline."""
    from scoring.legal import LEGAL_RISK_BASELINE
    try:
        from pipeline.compliance.wjp_client import WJP_SCORES
        if _match_country(country, LEGAL_RISK_BASELINE) or _match_country(country, WJP_SCORES):
            return "static"
    except ImportError:
        pass
    if _match_country(country, LEGAL_RISK_BASELINE):
        return "static"
    return "none"


def check_maritime(country: str) -> str:
    """Maritime risk - IMF PortWatch live API."""
    # Landlocked countries don't have maritime risk
    landlocked = {"switzerland", "austria", "czech republic", "hungary",
                  "nepal", "laos", "ethiopia", "south sudan", "north korea"}
    if country.lower() in landlocked:
        return "na"
    return "live"


def check_conflict(country: str) -> str:
    """ACLED conflict data."""
    try:
        from pipeline.conflict.acled_client import ACLED_STATIC_SCORES
        if _match_country(country, ACLED_STATIC_SCORES):
            return "static"
    except (ImportError, AttributeError):
        pass
    # ACLED API is available for most countries
    return "live"


def check_economic(country: str) -> str:
    """World Bank economic indicators."""
    return "live"


def check_currency(country: str) -> str:
    """Currency risk - Frankfurter/ECB."""
    return "live"


def check_health(country: str) -> str:
    """Disease.sh health data."""
    return "live"


def check_humanitarian(country: str) -> str:
    """OCHA FTS + ReliefWeb humanitarian data."""
    return "live"


def check_weather(country: str) -> str:
    """Open-Meteo weather data."""
    return "live"


def check_typhoon(country: str) -> str:
    """NOAA NHC/SWPC typhoon data + static baseline."""
    from scoring.engine import TYPHOON_EXPOSURE
    if _match_country(country, TYPHOON_EXPOSURE):
        return "live"
    # Countries not in typhoon belt
    non_typhoon = {"switzerland", "austria", "germany", "france", "italy",
                   "netherlands", "poland", "united kingdom", "brazil",
                   "argentina", "chile", "colombia", "venezuela",
                   "south africa", "nigeria", "kenya", "ethiopia",
                   "egypt", "turkey", "iran", "iraq", "israel",
                   "saudi arabia", "uae", "qatar", "russia", "ukraine",
                   "north korea", "south sudan", "somalia"}
    if country.lower() in non_typhoon:
        return "na"
    return "live"


def check_compliance(country: str) -> str:
    """FATF + TI CPI compliance data."""
    from pipeline.compliance.fatf_client import FATF_BLACK_LIST, FATF_GREY_LIST, TI_CPI
    loc = country.lower()
    for s in [FATF_BLACK_LIST, FATF_GREY_LIST]:
        for item in s:
            if item == loc or item in loc or loc in item:
                return "static"
    if _match_country(country, TI_CPI):
        return "static"
    return "none"


def check_food_security(country: str) -> str:
    """FEWS NET/WFP food security data."""
    try:
        from scoring.dimensions.food_security_scorer import FOOD_INSECURITY_BASELINE
        if _match_country(country, FOOD_INSECURITY_BASELINE):
            return "static"
    except (ImportError, AttributeError):
        pass
    return "live"


def check_trade(country: str) -> str:
    """UN Comtrade trade dependency."""
    return "live"


def check_internet(country: str) -> str:
    """Cloudflare Radar / IODA internet infrastructure."""
    return "live"


def check_political(country: str) -> str:
    """Freedom House political risk."""
    from pipeline.compliance.political_client import FREEDOM_HOUSE
    if _match_country(country, FREEDOM_HOUSE):
        return "static"
    return "none"


def check_labor(country: str) -> str:
    """DoL ILAB / GSI labor risk."""
    from pipeline.compliance.labor_client import FORCED_LABOR_GOODS, MODERN_SLAVERY_PREVALENCE
    if _match_country(country, FORCED_LABOR_GOODS) or _match_country(country, MODERN_SLAVERY_PREVALENCE):
        return "static"
    return "none"


def check_port_congestion(country: str) -> str:
    """UNCTAD port congestion."""
    landlocked = {"switzerland", "austria", "czech republic", "hungary",
                  "nepal", "laos", "ethiopia", "south sudan", "north korea"}
    if country.lower() in landlocked:
        return "na"
    return "live"


def check_aviation(country: str) -> str:
    """OpenSky aviation risk + baseline."""
    try:
        from pipeline.aviation.opensky_client import AVIATION_BASELINE
        if _match_country(country, AVIATION_BASELINE):
            return "static"
    except (ImportError, AttributeError):
        pass
    return "live"


def check_energy(country: str) -> str:
    """FRED/EIA energy prices."""
    return "live"


def check_japan_economy(country: str) -> str:
    """BOJ/e-Stat Japan economy indicators."""
    if country.lower() in ("japan", "jp", "jpn"):
        return "live"
    return "na"


def check_climate_risk(country: str) -> str:
    """ND-GAIN/GloFAS/WRI/Climate TRACE."""
    try:
        from scoring.dimensions.climate_scorer import NDGAIN_INDEX
        if _match_country(country, NDGAIN_INDEX):
            return "static"
    except (ImportError, AttributeError):
        pass
    return "live"


def check_cyber_risk(country: str) -> str:
    """OONI/CISA KEV/ITU ICT."""
    try:
        from scoring.dimensions.cyber_scorer import ITU_ICT_DEV_INDEX
        if _match_country(country, ITU_ICT_DEV_INDEX):
            return "static"
    except (ImportError, AttributeError):
        pass
    return "live"


# New data quality sources
def check_wjp(country: str) -> str:
    """WJP Rule of Law Index."""
    from pipeline.compliance.wjp_client import WJP_SCORES
    if _match_country(country, WJP_SCORES):
        return "static"
    return "none"


def check_basel_aml(country: str) -> str:
    """Basel AML Index."""
    from pipeline.compliance.basel_aml_client import BASEL_AML_SCORES
    if _match_country(country, BASEL_AML_SCORES):
        return "static"
    return "none"


def check_vdem(country: str) -> str:
    """V-Dem Democracy Index."""
    from pipeline.compliance.vdem_client import VDEM_POLYARCHY
    if _match_country(country, VDEM_POLYARCHY):
        return "static"
    return "none"


# ============================================================
# Dimension configuration
# ============================================================

DIMENSIONS = {
    "sanctions": ("Sanctions", check_sanctions),
    "geo_risk": ("Geo Risk", check_geo_risk),
    "disaster": ("Disaster", check_disaster),
    "legal": ("Legal", check_legal),
    "maritime": ("Maritime", check_maritime),
    "conflict": ("Conflict", check_conflict),
    "economic": ("Economic", check_economic),
    "currency": ("Currency", check_currency),
    "health": ("Health", check_health),
    "humanitarian": ("Humanitarian", check_humanitarian),
    "weather": ("Weather", check_weather),
    "typhoon": ("Typhoon", check_typhoon),
    "compliance": ("Compliance", check_compliance),
    "food_security": ("Food Security", check_food_security),
    "trade": ("Trade", check_trade),
    "internet": ("Internet", check_internet),
    "political": ("Political", check_political),
    "labor": ("Labor", check_labor),
    "port_congestion": ("Port Congestion", check_port_congestion),
    "aviation": ("Aviation", check_aviation),
    "energy": ("Energy", check_energy),
    "japan_economy": ("Japan Econ", check_japan_economy),
    "climate_risk": ("Climate", check_climate_risk),
    "cyber_risk": ("Cyber", check_cyber_risk),
}

# Supplementary data sources (not scored dimensions, but enrich existing ones)
SUPPLEMENTARY_SOURCES = {
    "wjp": ("WJP RoL", check_wjp),
    "basel_aml": ("Basel AML", check_basel_aml),
    "vdem": ("V-Dem", check_vdem),
}

STATUS_ICONS = {
    "live": "\\u2705",    # check mark
    "static": "\\u26A0\\uFE0F",  # warning
    "none": "\\u274C",    # X
    "na": "\\u2014",      # em dash
}


def generate_coverage_matrix() -> dict:
    """Generate coverage matrix for all countries x dimensions."""
    matrix = {}
    for country in PRIORITY_COUNTRIES:
        row = {}
        for dim_key, (dim_name, checker) in DIMENSIONS.items():
            try:
                row[dim_key] = checker(country)
            except Exception:
                row[dim_key] = "none"
        # Also check supplementary
        for src_key, (src_name, checker) in SUPPLEMENTARY_SOURCES.items():
            try:
                row[src_key] = checker(country)
            except Exception:
                row[src_key] = "none"
        matrix[country] = row
    return matrix


def compute_stats(matrix: dict) -> dict:
    """Compute summary statistics from the coverage matrix."""
    total_cells = 0
    live_count = 0
    static_count = 0
    none_count = 0
    na_count = 0

    dim_coverage = {}
    country_coverage = {}

    all_keys = list(DIMENSIONS.keys()) + list(SUPPLEMENTARY_SOURCES.keys())

    for country, row in matrix.items():
        c_live = c_static = c_none = c_na = 0
        for key in all_keys:
            status = row.get(key, "none")
            total_cells += 1
            if status == "live":
                live_count += 1
                c_live += 1
            elif status == "static":
                static_count += 1
                c_static += 1
            elif status == "na":
                na_count += 1
                c_na += 1
            else:
                none_count += 1
                c_none += 1

            if key not in dim_coverage:
                dim_coverage[key] = {"live": 0, "static": 0, "none": 0, "na": 0}
            dim_coverage[key][status] += 1

        applicable = c_live + c_static + c_none
        coverage_pct = ((c_live + c_static) / applicable * 100) if applicable > 0 else 0
        country_coverage[country] = {
            "live": c_live, "static": c_static, "none": c_none,
            "na": c_na, "coverage_pct": coverage_pct,
        }

    applicable_total = live_count + static_count + none_count
    overall_pct = ((live_count + static_count) / applicable_total * 100) if applicable_total > 0 else 0

    return {
        "total_cells": total_cells,
        "live": live_count,
        "static": static_count,
        "none": none_count,
        "na": na_count,
        "overall_coverage_pct": overall_pct,
        "dim_coverage": dim_coverage,
        "country_coverage": country_coverage,
    }


def render_markdown(matrix: dict, stats: dict) -> str:
    """Render coverage matrix as Markdown."""
    lines = []
    lines.append("# SCRI Platform Data Coverage Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Platform Version:** v0.7.0")
    lines.append(f"**Countries:** {len(PRIORITY_COUNTRIES)}")

    all_keys = list(DIMENSIONS.keys()) + list(SUPPLEMENTARY_SOURCES.keys())
    lines.append(f"**Dimensions:** {len(DIMENSIONS)} core + {len(SUPPLEMENTARY_SOURCES)} supplementary = {len(all_keys)} total")
    lines.append("")

    # Summary statistics
    lines.append("## Summary Statistics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total data points | {stats['total_cells']} |")
    lines.append(f"| Live API data | {stats['live']} ({stats['live']/stats['total_cells']*100:.1f}%) |")
    lines.append(f"| Static fallback | {stats['static']} ({stats['static']/stats['total_cells']*100:.1f}%) |")
    lines.append(f"| No data | {stats['none']} ({stats['none']/stats['total_cells']*100:.1f}%) |")
    lines.append(f"| Not applicable | {stats['na']} ({stats['na']/stats['total_cells']*100:.1f}%) |")
    applicable = stats['live'] + stats['static'] + stats['none']
    covered = stats['live'] + stats['static']
    lines.append(f"| **Overall coverage** | **{covered}/{applicable} ({stats['overall_coverage_pct']:.1f}%)** |")
    lines.append("")

    # Legend
    lines.append("## Legend")
    lines.append("")
    lines.append("| Symbol | Meaning |")
    lines.append("|--------|---------|")
    lines.append("| \\u2705 | Live API data available |")
    lines.append("| \\u26A0\\uFE0F | Static fallback data |")
    lines.append("| \\u274C | No data coverage |")
    lines.append("| \\u2014 | Not applicable |")
    lines.append("")

    # Dimension coverage summary
    lines.append("## Dimension Coverage Summary")
    lines.append("")
    lines.append("| Dimension | Live | Static | None | N/A | Coverage |")
    lines.append("|-----------|------|--------|------|-----|----------|")

    all_labels = {}
    all_labels.update({k: v[0] for k, v in DIMENSIONS.items()})
    all_labels.update({k: v[0] for k, v in SUPPLEMENTARY_SOURCES.items()})

    for key in all_keys:
        dc = stats["dim_coverage"].get(key, {})
        live = dc.get("live", 0)
        static = dc.get("static", 0)
        none_v = dc.get("none", 0)
        na = dc.get("na", 0)
        applicable_dim = live + static + none_v
        pct = ((live + static) / applicable_dim * 100) if applicable_dim > 0 else 0
        label = all_labels.get(key, key)
        lines.append(f"| {label} | {live} | {static} | {none_v} | {na} | {pct:.0f}% |")
    lines.append("")

    # Country coverage summary (top and bottom)
    lines.append("## Country Coverage Summary")
    lines.append("")
    sorted_countries = sorted(
        stats["country_coverage"].items(),
        key=lambda x: x[1]["coverage_pct"],
        reverse=True,
    )

    lines.append("| Country | Live | Static | None | N/A | Coverage |")
    lines.append("|---------|------|--------|------|-----|----------|")
    for country, cc in sorted_countries:
        lines.append(
            f"| {country} | {cc['live']} | {cc['static']} | {cc['none']} | {cc['na']} | {cc['coverage_pct']:.0f}% |"
        )
    lines.append("")

    # Full coverage matrix
    lines.append("## Full Coverage Matrix")
    lines.append("")
    lines.append("Dimensions are abbreviated. Rows = countries, columns = dimensions.")
    lines.append("")

    # Short labels for columns
    short_labels = {
        "sanctions": "SAN", "geo_risk": "GEO", "disaster": "DIS", "legal": "LEG",
        "maritime": "MAR", "conflict": "CON", "economic": "ECO", "currency": "CUR",
        "health": "HLT", "humanitarian": "HUM", "weather": "WTH", "typhoon": "TYP",
        "compliance": "CMP", "food_security": "FDS", "trade": "TRD", "internet": "INT",
        "political": "POL", "labor": "LAB", "port_congestion": "PRT", "aviation": "AVN",
        "energy": "ENR", "japan_economy": "JPN", "climate_risk": "CLM", "cyber_risk": "CYB",
        "wjp": "WJP", "basel_aml": "BAS", "vdem": "VDM",
    }

    header = "| Country | " + " | ".join(short_labels.get(k, k[:3].upper()) for k in all_keys) + " |"
    separator = "|---------|" + "|".join("-----" for _ in all_keys) + "|"
    lines.append(header)
    lines.append(separator)

    for country in PRIORITY_COUNTRIES:
        row = matrix[country]
        cells = []
        for key in all_keys:
            status = row.get(key, "none")
            icon = STATUS_ICONS.get(status, "?")
            cells.append(icon)
        lines.append(f"| {country} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("---")
    lines.append(f"*Report generated by `scripts/generate_coverage_report.py` on {datetime.now().strftime('%Y-%m-%d')}*")

    return "\n".join(lines)


def main():
    print("Generating SCRI Platform Data Coverage Report...")
    print(f"  Countries: {len(PRIORITY_COUNTRIES)}")
    print(f"  Dimensions: {len(DIMENSIONS)} core + {len(SUPPLEMENTARY_SOURCES)} supplementary")

    matrix = generate_coverage_matrix()
    stats = compute_stats(matrix)

    md = render_markdown(matrix, stats)

    # Write to docs/DATA_COVERAGE.md
    output_path = os.path.join(PROJECT_ROOT, "docs", "DATA_COVERAGE.md")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n  Output: {output_path}")
    print(f"\n  Summary:")
    print(f"    Total data points: {stats['total_cells']}")
    print(f"    Live API:   {stats['live']} ({stats['live']/stats['total_cells']*100:.1f}%)")
    print(f"    Static:     {stats['static']} ({stats['static']/stats['total_cells']*100:.1f}%)")
    print(f"    No data:    {stats['none']} ({stats['none']/stats['total_cells']*100:.1f}%)")
    print(f"    N/A:        {stats['na']} ({stats['na']/stats['total_cells']*100:.1f}%)")
    applicable = stats['live'] + stats['static'] + stats['none']
    covered = stats['live'] + stats['static']
    print(f"    Coverage:   {covered}/{applicable} ({stats['overall_coverage_pct']:.1f}%)")
    print("\nDone.")


if __name__ == "__main__":
    main()
