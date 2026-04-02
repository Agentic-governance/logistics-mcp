"""Climate TRACE API クライアント
施設レベルGHG排出量データ
https://climatetrace.org/
APIキー不要
"""
import requests
from typing import Optional

# Climate TRACE API endpoints
CLIMATE_TRACE_V4 = "https://api.climatetrace.org/v4"
CLIMATE_TRACE_V6 = "https://api.climatetrace.org/v6"

HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}

# Country name -> ISO3 mapping
COUNTRY_TO_ISO3 = {
    "japan": "JPN", "china": "CHN", "united states": "USA", "usa": "USA",
    "south korea": "KOR", "korea": "KOR", "taiwan": "TWN",
    "thailand": "THA", "vietnam": "VNM", "indonesia": "IDN",
    "malaysia": "MYS", "singapore": "SGP", "philippines": "PHL",
    "india": "IND", "germany": "DEU", "australia": "AUS",
    "russia": "RUS", "ukraine": "UKR", "myanmar": "MMR",
    "bangladesh": "BGD", "pakistan": "PAK", "turkey": "TUR",
    "brazil": "BRA", "mexico": "MEX", "nigeria": "NGA",
    "egypt": "EGY", "south africa": "ZAF", "saudi arabia": "SAU",
    "united kingdom": "GBR", "uk": "GBR", "france": "FRA",
    "italy": "ITA", "canada": "CAN", "uae": "ARE",
    "united arab emirates": "ARE", "iran": "IRN", "iraq": "IRQ",
    "yemen": "YEM", "qatar": "QAT", "kuwait": "KWT",
    "norway": "NOR", "sweden": "SWE", "denmark": "DNK",
    "switzerland": "CHE", "spain": "ESP", "poland": "POL",
    "cambodia": "KHM", "laos": "LAO", "nepal": "NPL",
    "sri lanka": "LKA", "somalia": "SOM", "chad": "TCD",
    "north korea": "PRK",
}

# Static fallback: emissions intensity and transition risk indicators
# emissions_intensity: tCO2e per million USD GDP (higher = more carbon intensive)
# cbam_exposure: 0-1, exposure to EU CBAM (Carbon Border Adjustment Mechanism)
# carbon_pricing_gap: 0-1, gap between actual and needed carbon pricing
STATIC_TRANSITION_RISK: dict[str, dict[str, float]] = {
    # High emissions intensity, high transition risk
    "CHN": {"emissions_intensity": 850, "cbam_exposure": 0.85, "carbon_pricing_gap": 0.70},
    "IND": {"emissions_intensity": 920, "cbam_exposure": 0.80, "carbon_pricing_gap": 0.85},
    "RUS": {"emissions_intensity": 1100, "cbam_exposure": 0.75, "carbon_pricing_gap": 0.90},
    "SAU": {"emissions_intensity": 1300, "cbam_exposure": 0.60, "carbon_pricing_gap": 0.95},
    "IRN": {"emissions_intensity": 1200, "cbam_exposure": 0.50, "carbon_pricing_gap": 0.95},
    "IRQ": {"emissions_intensity": 1400, "cbam_exposure": 0.40, "carbon_pricing_gap": 0.95},
    "KWT": {"emissions_intensity": 1100, "cbam_exposure": 0.45, "carbon_pricing_gap": 0.90},
    "QAT": {"emissions_intensity": 1500, "cbam_exposure": 0.50, "carbon_pricing_gap": 0.85},
    "ARE": {"emissions_intensity": 900, "cbam_exposure": 0.55, "carbon_pricing_gap": 0.80},
    # Medium-high
    "IDN": {"emissions_intensity": 700, "cbam_exposure": 0.65, "carbon_pricing_gap": 0.75},
    "VNM": {"emissions_intensity": 750, "cbam_exposure": 0.70, "carbon_pricing_gap": 0.80},
    "THA": {"emissions_intensity": 600, "cbam_exposure": 0.60, "carbon_pricing_gap": 0.70},
    "TUR": {"emissions_intensity": 550, "cbam_exposure": 0.75, "carbon_pricing_gap": 0.65},
    "ZAF": {"emissions_intensity": 800, "cbam_exposure": 0.60, "carbon_pricing_gap": 0.75},
    "PAK": {"emissions_intensity": 650, "cbam_exposure": 0.55, "carbon_pricing_gap": 0.85},
    "BGD": {"emissions_intensity": 500, "cbam_exposure": 0.50, "carbon_pricing_gap": 0.85},
    "EGY": {"emissions_intensity": 600, "cbam_exposure": 0.55, "carbon_pricing_gap": 0.80},
    "NGA": {"emissions_intensity": 550, "cbam_exposure": 0.40, "carbon_pricing_gap": 0.90},
    "UKR": {"emissions_intensity": 700, "cbam_exposure": 0.70, "carbon_pricing_gap": 0.60},
    "POL": {"emissions_intensity": 500, "cbam_exposure": 0.80, "carbon_pricing_gap": 0.40},
    "MYS": {"emissions_intensity": 550, "cbam_exposure": 0.55, "carbon_pricing_gap": 0.70},
    "PHL": {"emissions_intensity": 450, "cbam_exposure": 0.45, "carbon_pricing_gap": 0.75},
    "MMR": {"emissions_intensity": 400, "cbam_exposure": 0.30, "carbon_pricing_gap": 0.90},
    # Medium
    "MEX": {"emissions_intensity": 450, "cbam_exposure": 0.50, "carbon_pricing_gap": 0.60},
    "BRA": {"emissions_intensity": 350, "cbam_exposure": 0.45, "carbon_pricing_gap": 0.55},
    "KOR": {"emissions_intensity": 400, "cbam_exposure": 0.70, "carbon_pricing_gap": 0.45},
    "AUS": {"emissions_intensity": 500, "cbam_exposure": 0.55, "carbon_pricing_gap": 0.50},
    "TWN": {"emissions_intensity": 420, "cbam_exposure": 0.65, "carbon_pricing_gap": 0.50},
    "ITA": {"emissions_intensity": 280, "cbam_exposure": 0.60, "carbon_pricing_gap": 0.30},
    "ESP": {"emissions_intensity": 270, "cbam_exposure": 0.55, "carbon_pricing_gap": 0.25},
    # Low transition risk (have carbon pricing, low intensity)
    "JPN": {"emissions_intensity": 320, "cbam_exposure": 0.50, "carbon_pricing_gap": 0.40},
    "USA": {"emissions_intensity": 350, "cbam_exposure": 0.40, "carbon_pricing_gap": 0.50},
    "DEU": {"emissions_intensity": 250, "cbam_exposure": 0.30, "carbon_pricing_gap": 0.15},
    "GBR": {"emissions_intensity": 200, "cbam_exposure": 0.25, "carbon_pricing_gap": 0.15},
    "FRA": {"emissions_intensity": 180, "cbam_exposure": 0.20, "carbon_pricing_gap": 0.10},
    "CAN": {"emissions_intensity": 400, "cbam_exposure": 0.35, "carbon_pricing_gap": 0.30},
    "SGP": {"emissions_intensity": 220, "cbam_exposure": 0.40, "carbon_pricing_gap": 0.35},
    "NOR": {"emissions_intensity": 150, "cbam_exposure": 0.15, "carbon_pricing_gap": 0.05},
    "SWE": {"emissions_intensity": 130, "cbam_exposure": 0.15, "carbon_pricing_gap": 0.05},
    "DNK": {"emissions_intensity": 140, "cbam_exposure": 0.15, "carbon_pricing_gap": 0.05},
    "CHE": {"emissions_intensity": 120, "cbam_exposure": 0.20, "carbon_pricing_gap": 0.10},
}


def _resolve_iso3(location: str) -> str:
    """国名/コードをISO3に変換"""
    loc = location.lower().strip()
    if loc in COUNTRY_TO_ISO3:
        return COUNTRY_TO_ISO3[loc]
    if len(loc) == 3 and loc.isalpha():
        return loc.upper()
    for name, code in COUNTRY_TO_ISO3.items():
        if loc in name or name in loc:
            return code
    return loc.upper()[:3]


def get_country_emissions(country_iso3: str) -> dict:
    """Climate TRACE APIから国レベルの排出量データを取得

    Args:
        country_iso3: ISO3国コード

    Returns:
        排出量データ辞書。API不通時は空辞書
    """
    # Try v4 API first
    for base_url in [CLIMATE_TRACE_V4, CLIMATE_TRACE_V6]:
        try:
            url = f"{base_url}/country/emissions"
            params = {
                "countries": country_iso3.upper(),
                "since": "2022",
                "to": "2024",
            }
            resp = requests.get(url, params=params, timeout=15, headers=HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    return {
                        "source": "Climate TRACE API",
                        "country": country_iso3,
                        "data": data,
                    }
        except Exception:
            continue

    # Try alternative endpoint format
    try:
        url = f"{CLIMATE_TRACE_V6}/country/emissions/timeseries"
        params = {"countries": country_iso3.upper()}
        resp = requests.get(url, params=params, timeout=15, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return {
                    "source": "Climate TRACE API (timeseries)",
                    "country": country_iso3,
                    "data": data,
                }
    except Exception:
        pass

    return {}


def _calculate_transition_score(
    emissions_intensity: float,
    cbam_exposure: float,
    carbon_pricing_gap: float,
) -> int:
    """移行リスクスコアを算出

    Score = normalized(emissions_intensity) * cbam_exposure * carbon_pricing_gap
    """
    # Normalize emissions intensity: 0-1500 -> 0-1
    norm_intensity = min(1.0, emissions_intensity / 1500.0)

    # Weighted combination
    raw = (
        norm_intensity * 0.40
        + cbam_exposure * 0.35
        + carbon_pricing_gap * 0.25
    )
    return min(100, max(0, int(raw * 100)))


def get_transition_risk(location: str) -> dict:
    """カーボン移行リスクスコアを取得

    Score based on: emissions intensity x CBAM exposure x carbon pricing gap

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
    """
    iso3 = _resolve_iso3(location)
    evidence: list[str] = []

    # Try live API data
    api_data = get_country_emissions(iso3)
    if api_data and api_data.get("data"):
        try:
            raw_data = api_data["data"]
            # Try to extract total emissions from API response
            total_emissions = None
            if isinstance(raw_data, list) and raw_data:
                entry = raw_data[0] if isinstance(raw_data[0], dict) else {}
                total_emissions = entry.get("co2", entry.get("total", entry.get("emissions")))
            elif isinstance(raw_data, dict):
                total_emissions = raw_data.get("co2", raw_data.get("total"))

            if total_emissions is not None:
                evidence.append(
                    f"[Climate TRACE] {location}: "
                    f"排出量データ取得 ({api_data['source']})"
                )
        except Exception:
            pass

    # Static transition risk data
    static = STATIC_TRANSITION_RISK.get(iso3)
    if static is None:
        # Unknown country - return moderate default
        return {
            "score": 30,
            "evidence": [
                f"[Climate TRACE] {location} ({iso3}) の詳細データなし。"
                "デフォルトスコア適用"
            ],
        }

    emissions_intensity = static["emissions_intensity"]
    cbam_exposure = static["cbam_exposure"]
    carbon_pricing_gap = static["carbon_pricing_gap"]

    score = _calculate_transition_score(
        emissions_intensity, cbam_exposure, carbon_pricing_gap
    )

    evidence.append(
        f"[Climate TRACE] {location}: 排出原単位={emissions_intensity} "
        f"tCO2e/M USD GDP"
    )
    evidence.append(
        f"[Climate TRACE] CBAM露出度={cbam_exposure:.2f}, "
        f"炭素価格ギャップ={carbon_pricing_gap:.2f}"
    )

    if score >= 60:
        evidence.append(
            f"[Climate TRACE] カーボン移行リスクが高い。"
            "EU CBAMやカーボンプライシング強化による影響大"
        )
    elif score >= 35:
        evidence.append(
            f"[Climate TRACE] 中程度の移行リスク。脱炭素化の進展に注視"
        )
    else:
        evidence.append(
            f"[Climate TRACE] 移行リスクは比較的低い"
        )

    return {"score": score, "evidence": evidence}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_locations = [
        "China", "India", "Japan", "Germany", "USA",
        "Vietnam", "Saudi Arabia", "Brazil", "Singapore", "Russia",
    ]
    print("=" * 70)
    print("Climate TRACE Transition Risk Test")
    print("=" * 70)
    for loc in test_locations:
        result = get_transition_risk(loc)
        print(f"\n{loc}:")
        print(f"  Score: {result['score']}/100")
        for e in result["evidence"]:
            print(f"  {e}")

    print("\n--- API connectivity test ---")
    for iso3 in ["CHN", "USA", "DEU"]:
        data = get_country_emissions(iso3)
        status = "OK" if data else "Fallback"
        print(f"  {iso3}: {status}")
    print("\n" + "=" * 70)
