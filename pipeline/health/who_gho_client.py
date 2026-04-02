"""WHO Global Health Observatory (GHO) - Health Indicators
Life expectancy, under-5 mortality, health infrastructure.
https://ghoapi.azureedge.net/api/
Free API - no key required.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from datetime import datetime

GHO_API_BASE = "https://ghoapi.azureedge.net/api/"

# Indicator codes
INDICATORS = {
    "life_expectancy": "WHOSIS_000001",
    "under5_mortality": "MDG_0000000026",
    "health_infra": "WHS9_96",
}

HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}

# Static fallback data for when API is unreachable
# Sources: WHO World Health Statistics 2024
FALLBACK_DATA = {
    "JPN": {"life_expectancy": 84.3, "under5_mortality": 2.0, "health_infra": 92.0},
    "USA": {"life_expectancy": 77.5, "under5_mortality": 6.0, "health_infra": 88.0},
    "CHN": {"life_expectancy": 78.2, "under5_mortality": 6.8, "health_infra": 75.0},
    "DEU": {"life_expectancy": 81.7, "under5_mortality": 3.3, "health_infra": 90.0},
    "GBR": {"life_expectancy": 81.4, "under5_mortality": 3.8, "health_infra": 89.0},
    "FRA": {"life_expectancy": 82.5, "under5_mortality": 3.6, "health_infra": 88.0},
    "IND": {"life_expectancy": 70.8, "under5_mortality": 27.2, "health_infra": 55.0},
    "BRA": {"life_expectancy": 75.3, "under5_mortality": 13.4, "health_infra": 62.0},
    "KOR": {"life_expectancy": 83.7, "under5_mortality": 2.7, "health_infra": 91.0},
    "AUS": {"life_expectancy": 83.3, "under5_mortality": 3.2, "health_infra": 90.0},
    "CAN": {"life_expectancy": 82.4, "under5_mortality": 4.3, "health_infra": 89.0},
    "MEX": {"life_expectancy": 75.0, "under5_mortality": 12.7, "health_infra": 60.0},
    "RUS": {"life_expectancy": 73.2, "under5_mortality": 4.6, "health_infra": 68.0},
    "IDN": {"life_expectancy": 71.7, "under5_mortality": 20.2, "health_infra": 52.0},
    "TUR": {"life_expectancy": 78.6, "under5_mortality": 8.0, "health_infra": 72.0},
    "SAU": {"life_expectancy": 77.6, "under5_mortality": 6.2, "health_infra": 78.0},
    "ZAF": {"life_expectancy": 64.9, "under5_mortality": 28.5, "health_infra": 55.0},
    "NGA": {"life_expectancy": 52.7, "under5_mortality": 109.8, "health_infra": 30.0},
    "EGY": {"life_expectancy": 72.0, "under5_mortality": 18.1, "health_infra": 58.0},
    "THA": {"life_expectancy": 78.7, "under5_mortality": 7.8, "health_infra": 73.0},
    "VNM": {"life_expectancy": 75.4, "under5_mortality": 19.5, "health_infra": 60.0},
    "MYS": {"life_expectancy": 76.2, "under5_mortality": 7.3, "health_infra": 72.0},
    "SGP": {"life_expectancy": 83.9, "under5_mortality": 2.4, "health_infra": 93.0},
    "PHL": {"life_expectancy": 71.1, "under5_mortality": 24.8, "health_infra": 50.0},
    "BGD": {"life_expectancy": 72.4, "under5_mortality": 26.9, "health_infra": 42.0},
    "TWN": {"life_expectancy": 81.3, "under5_mortality": 3.8, "health_infra": 88.0},
    "MMR": {"life_expectancy": 66.7, "under5_mortality": 43.5, "health_infra": 35.0},
    "KHM": {"life_expectancy": 69.8, "under5_mortality": 24.0, "health_infra": 38.0},
    "UKR": {"life_expectancy": 73.6, "under5_mortality": 7.5, "health_infra": 62.0},
    "PAK": {"life_expectancy": 66.5, "under5_mortality": 63.3, "health_infra": 40.0},
    "ETH": {"life_expectancy": 65.0, "under5_mortality": 49.0, "health_infra": 28.0},
    "AFG": {"life_expectancy": 62.0, "under5_mortality": 56.9, "health_infra": 22.0},
    "YEM": {"life_expectancy": 63.4, "under5_mortality": 55.4, "health_infra": 20.0},
    "SYR": {"life_expectancy": 72.7, "under5_mortality": 16.0, "health_infra": 30.0},
    "IRQ": {"life_expectancy": 70.6, "under5_mortality": 23.1, "health_infra": 45.0},
    "SDN": {"life_expectancy": 65.3, "under5_mortality": 56.1, "health_infra": 25.0},
    "SOM": {"life_expectancy": 56.5, "under5_mortality": 112.4, "health_infra": 15.0},
    "LBY": {"life_expectancy": 72.9, "under5_mortality": 10.6, "health_infra": 50.0},
    "LBN": {"life_expectancy": 78.9, "under5_mortality": 6.5, "health_infra": 65.0},
    "ARE": {"life_expectancy": 78.7, "under5_mortality": 6.6, "health_infra": 82.0},
    "ITA": {"life_expectancy": 83.5, "under5_mortality": 2.8, "health_infra": 89.0},
}


def _fetch_indicator(country_iso3: str, indicator_code: str) -> float | None:
    """Fetch a single indicator from WHO GHO API for a country."""
    url = f"{GHO_API_BASE}{indicator_code}"
    params = {
        "$filter": f"SpatialDim eq '{country_iso3}'",
        "$orderby": "TimeDim desc",
        "$top": 1,
    }
    try:
        resp = requests.get(url, params=params, timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        values = data.get("value", [])
        if values:
            val = values[0].get("NumericValue")
            if val is not None:
                return float(val)
        return None
    except Exception as e:
        print(f"WHO GHO API error ({indicator_code}, {country_iso3}): {e}")
        return None


def _compute_score(life_expectancy: float, under5_mortality: float, health_infra: float) -> int:
    """Compute composite health risk score (0-100).

    Higher mortality, lower life expectancy, lower health infra = higher risk.
    """
    score = 0.0

    # Life expectancy component (weight 35%)
    # 85+ = 0 risk, 50 or below = 100 risk
    if life_expectancy is not None:
        le_risk = max(0.0, min(100.0, (85.0 - life_expectancy) / 35.0 * 100.0))
        score += le_risk * 0.35

    # Under-5 mortality component (weight 35%)
    # 0 = 0 risk, 120+ = 100 risk (per 1000 live births)
    if under5_mortality is not None:
        u5_risk = max(0.0, min(100.0, under5_mortality / 120.0 * 100.0))
        score += u5_risk * 0.35

    # Health infrastructure component (weight 30%)
    # 100 = 0 risk, 0 = 100 risk
    if health_infra is not None:
        hi_risk = max(0.0, min(100.0, (100.0 - health_infra)))
        score += hi_risk * 0.30

    return min(100, max(0, int(score)))


def get_health_indicators(country_iso3: str) -> dict:
    """Get WHO health indicators for a country.

    Args:
        country_iso3: ISO 3166-1 alpha-3 country code (e.g., 'JPN', 'USA')

    Returns:
        dict with keys: life_expectancy, under5_mortality, health_infra,
                        score (0-100), evidence (list of str)
    """
    country_iso3 = country_iso3.upper().strip()
    life_expectancy = None
    under5_mortality = None
    health_infra = None
    evidence = []
    used_fallback = False

    # Try live API first
    life_expectancy = _fetch_indicator(country_iso3, INDICATORS["life_expectancy"])
    under5_mortality = _fetch_indicator(country_iso3, INDICATORS["under5_mortality"])
    health_infra = _fetch_indicator(country_iso3, INDICATORS["health_infra"])

    # If all API calls failed, use fallback
    if life_expectancy is None and under5_mortality is None and health_infra is None:
        fallback = FALLBACK_DATA.get(country_iso3, {})
        if fallback:
            life_expectancy = fallback.get("life_expectancy")
            under5_mortality = fallback.get("under5_mortality")
            health_infra = fallback.get("health_infra")
            used_fallback = True
            evidence.append(f"[Static fallback] WHO GHO API unreachable; using cached data for {country_iso3}")

    # Fill individual missing values from fallback
    if not used_fallback:
        fallback = FALLBACK_DATA.get(country_iso3, {})
        if life_expectancy is None and fallback.get("life_expectancy"):
            life_expectancy = fallback["life_expectancy"]
            evidence.append(f"Life expectancy: using fallback value ({life_expectancy})")
        if under5_mortality is None and fallback.get("under5_mortality"):
            under5_mortality = fallback["under5_mortality"]
            evidence.append(f"Under-5 mortality: using fallback value ({under5_mortality})")
        if health_infra is None and fallback.get("health_infra"):
            health_infra = fallback["health_infra"]
            evidence.append(f"Health infra: using fallback value ({health_infra})")

    # Build evidence strings
    source_tag = "WHO GHO" if not used_fallback else "Static"
    if life_expectancy is not None:
        evidence.append(f"Life expectancy: {life_expectancy:.1f} years [{source_tag}]")
    if under5_mortality is not None:
        evidence.append(f"Under-5 mortality rate: {under5_mortality:.1f} per 1,000 [{source_tag}]")
    if health_infra is not None:
        evidence.append(f"Health infrastructure index: {health_infra:.1f}/100 [{source_tag}]")

    score = _compute_score(
        life_expectancy if life_expectancy is not None else 75.0,
        under5_mortality if under5_mortality is not None else 30.0,
        health_infra if health_infra is not None else 60.0,
    )

    return {
        "life_expectancy": life_expectancy,
        "under5_mortality": under5_mortality,
        "health_infra": health_infra,
        "score": score,
        "evidence": evidence,
    }


if __name__ == "__main__":
    import json
    for code in ["JPN", "USA", "NGA", "AFG"]:
        result = get_health_indicators(code)
        print(f"\n{code}: score={result['score']}")
        for e in result["evidence"]:
            print(f"  {e}")
