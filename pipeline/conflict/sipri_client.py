"""SIPRI Military Expenditure Data
Military spending as share of GDP, and 3-year trends.
Static dataset approach (SIPRI provides Excel files not easily parseable via API).
Source: SIPRI Military Expenditure Database 2024
https://www.sipri.org/databases/milex
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Military expenditure as % of GDP (2023 estimates)
# Source: SIPRI Yearbook 2024 and SIPRI Fact Sheet April 2024
# trend_3yr: "increasing", "stable", "decreasing" based on 2021-2023 trajectory
MILITARY_EXPENDITURE = {
    "United States": {"gdp_share": 3.4, "trend_3yr": "stable"},
    "China": {"gdp_share": 1.7, "trend_3yr": "increasing"},
    "Russia": {"gdp_share": 5.9, "trend_3yr": "increasing"},
    "India": {"gdp_share": 2.4, "trend_3yr": "stable"},
    "Saudi Arabia": {"gdp_share": 7.1, "trend_3yr": "stable"},
    "United Kingdom": {"gdp_share": 2.3, "trend_3yr": "increasing"},
    "Germany": {"gdp_share": 1.6, "trend_3yr": "increasing"},
    "France": {"gdp_share": 2.1, "trend_3yr": "increasing"},
    "Japan": {"gdp_share": 1.2, "trend_3yr": "increasing"},
    "South Korea": {"gdp_share": 2.8, "trend_3yr": "stable"},
    "Australia": {"gdp_share": 2.0, "trend_3yr": "increasing"},
    "Italy": {"gdp_share": 1.5, "trend_3yr": "increasing"},
    "Canada": {"gdp_share": 1.4, "trend_3yr": "increasing"},
    "Israel": {"gdp_share": 5.3, "trend_3yr": "increasing"},
    "Brazil": {"gdp_share": 1.1, "trend_3yr": "stable"},
    "Turkey": {"gdp_share": 1.3, "trend_3yr": "stable"},
    "Poland": {"gdp_share": 3.9, "trend_3yr": "increasing"},
    "Netherlands": {"gdp_share": 1.7, "trend_3yr": "increasing"},
    "Spain": {"gdp_share": 1.3, "trend_3yr": "increasing"},
    "Taiwan": {"gdp_share": 2.5, "trend_3yr": "increasing"},
    "Pakistan": {"gdp_share": 3.7, "trend_3yr": "stable"},
    "Norway": {"gdp_share": 1.8, "trend_3yr": "increasing"},
    "Sweden": {"gdp_share": 1.6, "trend_3yr": "increasing"},
    "Singapore": {"gdp_share": 3.0, "trend_3yr": "stable"},
    "Greece": {"gdp_share": 3.7, "trend_3yr": "increasing"},
    "Colombia": {"gdp_share": 3.0, "trend_3yr": "stable"},
    "Ukraine": {"gdp_share": 26.9, "trend_3yr": "increasing"},
    "Indonesia": {"gdp_share": 0.8, "trend_3yr": "stable"},
    "Iran": {"gdp_share": 2.5, "trend_3yr": "stable"},
    "Egypt": {"gdp_share": 1.2, "trend_3yr": "stable"},
    "Thailand": {"gdp_share": 1.3, "trend_3yr": "stable"},
    "Vietnam": {"gdp_share": 1.7, "trend_3yr": "stable"},
    "Mexico": {"gdp_share": 0.6, "trend_3yr": "stable"},
    "Nigeria": {"gdp_share": 0.7, "trend_3yr": "stable"},
    "South Africa": {"gdp_share": 0.7, "trend_3yr": "decreasing"},
    "Malaysia": {"gdp_share": 1.0, "trend_3yr": "stable"},
    "Philippines": {"gdp_share": 1.3, "trend_3yr": "increasing"},
    "Bangladesh": {"gdp_share": 1.2, "trend_3yr": "stable"},
    "Algeria": {"gdp_share": 5.6, "trend_3yr": "increasing"},
    "Morocco": {"gdp_share": 4.5, "trend_3yr": "increasing"},
    "Iraq": {"gdp_share": 2.5, "trend_3yr": "stable"},
    "Kuwait": {"gdp_share": 6.1, "trend_3yr": "stable"},
    "Oman": {"gdp_share": 5.2, "trend_3yr": "decreasing"},
    "Chile": {"gdp_share": 1.5, "trend_3yr": "stable"},
    "Romania": {"gdp_share": 2.4, "trend_3yr": "increasing"},
    "Finland": {"gdp_share": 2.5, "trend_3yr": "increasing"},
    "Denmark": {"gdp_share": 2.0, "trend_3yr": "increasing"},
    "Myanmar": {"gdp_share": 3.3, "trend_3yr": "increasing"},
    "Libya": {"gdp_share": 3.0, "trend_3yr": "stable"},
    "Yemen": {"gdp_share": 4.5, "trend_3yr": "stable"},
}

# Country name normalization
COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom",
    "korea": "South Korea", "republic of korea": "South Korea",
    "uae": "United Arab Emirates",
    "drc": "Democratic Republic of Congo",
}


def _resolve_country(country: str) -> str:
    """Resolve country name to standard form."""
    lower = country.lower().strip()
    if lower in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[lower]
    # Try exact match (case-insensitive)
    for name in MILITARY_EXPENDITURE:
        if name.lower() == lower:
            return name
    # Try partial match
    for name in MILITARY_EXPENDITURE:
        if lower in name.lower() or name.lower() in lower:
            return name
    return country


def _compute_score(gdp_share: float, trend_3yr: str) -> int:
    """Compute military expenditure risk score (0-100).

    Very high military spending (>4%) or rapidly increasing spending indicates
    instability, conflict risk, or militarization.
    """
    score = 0.0

    # GDP share component (base score)
    if gdp_share > 10.0:
        score = 90.0  # Wartime levels (e.g., Ukraine)
    elif gdp_share > 6.0:
        score = 75.0
    elif gdp_share > 4.0:
        score = 55.0
    elif gdp_share > 3.0:
        score = 35.0
    elif gdp_share > 2.0:
        score = 20.0
    elif gdp_share > 1.5:
        score = 10.0
    else:
        score = 5.0

    # Trend modifier
    if trend_3yr == "increasing":
        score = min(100.0, score * 1.25)
    elif trend_3yr == "decreasing":
        score = max(0.0, score * 0.8)

    return min(100, max(0, int(score)))


def get_military_expenditure(country: str) -> dict:
    """Get military expenditure data for a country.

    Args:
        country: Country name (e.g., 'Japan', 'United States')

    Returns:
        dict with keys: gdp_share, trend_3yr, score (0-100), evidence (list of str)
    """
    resolved = _resolve_country(country)
    data = MILITARY_EXPENDITURE.get(resolved)

    if data is None:
        return {
            "gdp_share": None,
            "trend_3yr": "unknown",
            "score": 0,
            "evidence": [f"No military expenditure data available for '{country}'"],
        }

    gdp_share = data["gdp_share"]
    trend_3yr = data["trend_3yr"]
    score = _compute_score(gdp_share, trend_3yr)

    evidence = [
        f"Military expenditure: {gdp_share:.1f}% of GDP [SIPRI 2024]",
        f"3-year trend: {trend_3yr}",
    ]

    if gdp_share > 4.0:
        evidence.append(f"WARNING: Very high military spending indicates elevated conflict/instability risk")
    if trend_3yr == "increasing" and gdp_share > 2.0:
        evidence.append(f"NOTE: Rising military expenditure may signal escalating security concerns")

    return {
        "gdp_share": gdp_share,
        "trend_3yr": trend_3yr,
        "score": score,
        "evidence": evidence,
    }


def get_all_countries() -> dict:
    """Return full dataset of military expenditure."""
    return {
        country: {**data, "score": _compute_score(data["gdp_share"], data["trend_3yr"])}
        for country, data in MILITARY_EXPENDITURE.items()
    }


if __name__ == "__main__":
    for country in ["Japan", "United States", "Ukraine", "Saudi Arabia", "Singapore"]:
        result = get_military_expenditure(country)
        print(f"\n{country}: score={result['score']}, gdp_share={result['gdp_share']}%")
        for e in result["evidence"]:
            print(f"  {e}")
