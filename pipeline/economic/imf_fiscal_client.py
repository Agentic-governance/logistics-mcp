"""IMF Fiscal Monitor / DataMapper API - Fiscal Indicators
Government debt/GDP, fiscal deficit/GDP, current account/GDP.
https://www.imf.org/external/datamapper/api/v1/
Free API - no key required.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from datetime import datetime

IMF_API_BASE = "https://www.imf.org/external/datamapper/api/v1/"

# Indicator codes
INDICATORS = {
    "debt_gdp": "GGXWDG_NGDP",        # General govt gross debt (% of GDP)
    "deficit_gdp": "GGXCNL_NGDP",      # General govt net lending/borrowing (% of GDP)
    "current_account_gdp": "BCA_NGDPD", # Current account balance (% of GDP)
}

HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}

# Static fallback for major economies (approximate 2024 values)
# Sources: IMF World Economic Outlook, April 2024
FALLBACK_DATA = {
    "JPN": {"debt_gdp": 252.4, "deficit_gdp": -5.6, "current_account_gdp": 3.5},
    "USA": {"debt_gdp": 123.3, "deficit_gdp": -7.1, "current_account_gdp": -3.0},
    "CHN": {"debt_gdp": 83.6, "deficit_gdp": -7.1, "current_account_gdp": 1.4},
    "DEU": {"debt_gdp": 63.7, "deficit_gdp": -1.6, "current_account_gdp": 6.3},
    "GBR": {"debt_gdp": 104.3, "deficit_gdp": -4.6, "current_account_gdp": -3.1},
    "FRA": {"debt_gdp": 110.6, "deficit_gdp": -4.7, "current_account_gdp": -1.0},
    "ITA": {"debt_gdp": 137.3, "deficit_gdp": -4.3, "current_account_gdp": 0.5},
    "CAN": {"debt_gdp": 106.5, "deficit_gdp": -1.4, "current_account_gdp": -0.9},
    "IND": {"debt_gdp": 83.2, "deficit_gdp": -8.8, "current_account_gdp": -1.3},
    "BRA": {"debt_gdp": 87.6, "deficit_gdp": -7.3, "current_account_gdp": -1.5},
    "KOR": {"debt_gdp": 54.3, "deficit_gdp": -2.2, "current_account_gdp": 3.6},
    "AUS": {"debt_gdp": 51.1, "deficit_gdp": -1.3, "current_account_gdp": 1.4},
    "MEX": {"debt_gdp": 53.5, "deficit_gdp": -4.3, "current_account_gdp": -0.8},
    "RUS": {"debt_gdp": 18.9, "deficit_gdp": -1.4, "current_account_gdp": 2.5},
    "IDN": {"debt_gdp": 39.3, "deficit_gdp": -2.3, "current_account_gdp": -0.1},
    "TUR": {"debt_gdp": 34.1, "deficit_gdp": -5.2, "current_account_gdp": -3.6},
    "SAU": {"debt_gdp": 26.2, "deficit_gdp": -1.8, "current_account_gdp": 5.7},
    "ZAF": {"debt_gdp": 73.7, "deficit_gdp": -5.5, "current_account_gdp": -1.9},
    "NGA": {"debt_gdp": 41.8, "deficit_gdp": -5.0, "current_account_gdp": 0.2},
    "EGY": {"debt_gdp": 92.4, "deficit_gdp": -7.5, "current_account_gdp": -3.2},
    "THA": {"debt_gdp": 62.4, "deficit_gdp": -3.3, "current_account_gdp": 1.2},
    "VNM": {"debt_gdp": 37.0, "deficit_gdp": -3.5, "current_account_gdp": 2.1},
    "MYS": {"debt_gdp": 64.3, "deficit_gdp": -4.6, "current_account_gdp": 2.6},
    "SGP": {"debt_gdp": 168.0, "deficit_gdp": 1.2, "current_account_gdp": 19.8},
    "PHL": {"debt_gdp": 60.1, "deficit_gdp": -5.3, "current_account_gdp": -1.5},
    "BGD": {"debt_gdp": 40.5, "deficit_gdp": -5.2, "current_account_gdp": -0.7},
    "TWN": {"debt_gdp": 27.5, "deficit_gdp": -1.0, "current_account_gdp": 13.5},
    "ARE": {"debt_gdp": 30.3, "deficit_gdp": 4.6, "current_account_gdp": 9.2},
    "ARG": {"debt_gdp": 89.5, "deficit_gdp": -4.4, "current_account_gdp": -1.1},
    "CHL": {"debt_gdp": 39.2, "deficit_gdp": -2.6, "current_account_gdp": -3.5},
    "COL": {"debt_gdp": 54.8, "deficit_gdp": -4.5, "current_account_gdp": -2.7},
    "POL": {"debt_gdp": 51.7, "deficit_gdp": -5.0, "current_account_gdp": 1.1},
    "UKR": {"debt_gdp": 84.0, "deficit_gdp": -16.0, "current_account_gdp": -5.5},
    "PAK": {"debt_gdp": 73.5, "deficit_gdp": -7.5, "current_account_gdp": -1.2},
    "SRI": {"debt_gdp": 110.0, "deficit_gdp": -8.3, "current_account_gdp": -1.9},
    "GRC": {"debt_gdp": 161.9, "deficit_gdp": -1.6, "current_account_gdp": -6.3},
    "PRT": {"debt_gdp": 112.4, "deficit_gdp": -0.8, "current_account_gdp": -0.5},
    "ESP": {"debt_gdp": 107.5, "deficit_gdp": -3.2, "current_account_gdp": 2.1},
    "MMR": {"debt_gdp": 57.5, "deficit_gdp": -6.8, "current_account_gdp": -2.0},
    "KHM": {"debt_gdp": 35.1, "deficit_gdp": -4.8, "current_account_gdp": -8.0},
}


def _fetch_indicator(country_iso3: str, indicator_code: str) -> float | None:
    """Fetch a single indicator from IMF DataMapper API."""
    url = f"{IMF_API_BASE}{indicator_code}/{country_iso3}"
    try:
        resp = requests.get(url, timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

        # IMF DataMapper returns {values: {indicator: {country: {year: value}}}}
        values = data.get("values", {})
        indicator_data = values.get(indicator_code, {})
        country_data = indicator_data.get(country_iso3, {})

        if not country_data:
            return None

        # Get most recent year's value
        latest_year = max(country_data.keys(), key=int)
        val = country_data[latest_year]
        if val is not None:
            return float(val)
        return None
    except Exception as e:
        print(f"IMF DataMapper API error ({indicator_code}, {country_iso3}): {e}")
        return None


def _compute_score(debt_gdp: float | None, deficit_gdp: float | None,
                   current_account_gdp: float | None) -> int:
    """Compute fiscal risk score (0-100).

    High debt + large deficit = higher risk.
    """
    score = 0.0

    # Debt/GDP component (weight 40%)
    # <30% = 0, 30-60% = low, 60-90% = medium, 90-120% = high, >120% = very high
    if debt_gdp is not None:
        # Note: Singapore has high gross debt but huge reserves, so this is a
        # simplified metric. Values above 250% are capped at 100 risk.
        debt_risk = max(0.0, min(100.0, (debt_gdp - 30.0) / 220.0 * 100.0))
        score += debt_risk * 0.40

    # Fiscal deficit component (weight 35%)
    # deficit_gdp is net lending/borrowing - negative means deficit
    # 0 or positive = 0 risk, -15% or worse = 100 risk
    if deficit_gdp is not None:
        if deficit_gdp >= 0:
            deficit_risk = 0.0
        else:
            deficit_risk = max(0.0, min(100.0, abs(deficit_gdp) / 15.0 * 100.0))
        score += deficit_risk * 0.35

    # Current account component (weight 25%)
    # Large negative = higher risk, positive or near zero = lower risk
    if current_account_gdp is not None:
        if current_account_gdp >= 0:
            ca_risk = 0.0
        else:
            ca_risk = max(0.0, min(100.0, abs(current_account_gdp) / 10.0 * 100.0))
        score += ca_risk * 0.25

    return min(100, max(0, int(score)))


def get_fiscal_indicators(country_iso3: str) -> dict:
    """Get IMF fiscal indicators for a country.

    Args:
        country_iso3: ISO 3166-1 alpha-3 country code (e.g., 'JPN', 'USA')

    Returns:
        dict with keys: debt_gdp, deficit_gdp, current_account_gdp,
                        score (0-100), evidence (list of str)
    """
    country_iso3 = country_iso3.upper().strip()
    debt_gdp = None
    deficit_gdp = None
    current_account_gdp = None
    evidence = []
    used_fallback = False

    # Try live API first
    debt_gdp = _fetch_indicator(country_iso3, INDICATORS["debt_gdp"])
    deficit_gdp = _fetch_indicator(country_iso3, INDICATORS["deficit_gdp"])
    current_account_gdp = _fetch_indicator(country_iso3, INDICATORS["current_account_gdp"])

    # If all API calls failed, use fallback
    if debt_gdp is None and deficit_gdp is None and current_account_gdp is None:
        fallback = FALLBACK_DATA.get(country_iso3, {})
        if fallback:
            debt_gdp = fallback.get("debt_gdp")
            deficit_gdp = fallback.get("deficit_gdp")
            current_account_gdp = fallback.get("current_account_gdp")
            used_fallback = True
            evidence.append(f"[Static fallback] IMF API unreachable; using cached data for {country_iso3}")

    # Fill individual missing values from fallback
    if not used_fallback:
        fallback = FALLBACK_DATA.get(country_iso3, {})
        if debt_gdp is None and fallback.get("debt_gdp") is not None:
            debt_gdp = fallback["debt_gdp"]
            evidence.append(f"Debt/GDP: using fallback value ({debt_gdp}%)")
        if deficit_gdp is None and fallback.get("deficit_gdp") is not None:
            deficit_gdp = fallback["deficit_gdp"]
            evidence.append(f"Deficit/GDP: using fallback value ({deficit_gdp}%)")
        if current_account_gdp is None and fallback.get("current_account_gdp") is not None:
            current_account_gdp = fallback["current_account_gdp"]
            evidence.append(f"Current account/GDP: using fallback value ({current_account_gdp}%)")

    # Build evidence strings
    source_tag = "IMF DataMapper" if not used_fallback else "Static"
    if debt_gdp is not None:
        evidence.append(f"Government debt: {debt_gdp:.1f}% of GDP [{source_tag}]")
    if deficit_gdp is not None:
        label = "surplus" if deficit_gdp >= 0 else "deficit"
        evidence.append(f"Fiscal {label}: {deficit_gdp:+.1f}% of GDP [{source_tag}]")
    if current_account_gdp is not None:
        label = "surplus" if current_account_gdp >= 0 else "deficit"
        evidence.append(f"Current account {label}: {current_account_gdp:+.1f}% of GDP [{source_tag}]")

    score = _compute_score(debt_gdp, deficit_gdp, current_account_gdp)

    return {
        "debt_gdp": debt_gdp,
        "deficit_gdp": deficit_gdp,
        "current_account_gdp": current_account_gdp,
        "score": score,
        "evidence": evidence,
    }


if __name__ == "__main__":
    for code in ["JPN", "USA", "GRC", "SGP"]:
        result = get_fiscal_indicators(code)
        print(f"\n{code}: score={result['score']}")
        for e in result["evidence"]:
            print(f"  {e}")
