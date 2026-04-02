"""WRI Aqueduct 水リスク クライアント
World Resources Institute - Water Risk Atlas
https://www.wri.org/aqueduct
"""
import requests
from typing import Optional

# Resource Watch API (WRI)
RESOURCE_WATCH_API = "https://api.resourcewatch.org/v1/query"

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
    "yemen": "YEM", "libya": "LBY", "qatar": "QAT",
    "israel": "ISR", "jordan": "JOR", "lebanon": "LBN",
    "spain": "ESP", "norway": "NOR", "sweden": "SWE",
    "denmark": "DNK", "switzerland": "CHE",
    "cambodia": "KHM", "laos": "LAO", "nepal": "NPL",
    "sri lanka": "LKA", "mozambique": "MOZ", "ethiopia": "ETH",
    "somalia": "SOM", "chad": "TCD", "sudan": "SDN",
    "south sudan": "SSD", "north korea": "PRK",
}

# Static data: Overall water risk score 0-5 (higher = more risk)
# Based on WRI Aqueduct 4.0 country-level baseline water stress
STATIC_WATER_RISK: dict[str, float] = {
    # Extremely High (4+)
    "YEM": 4.8, "LBY": 4.7, "QAT": 4.5, "ISR": 4.4, "LBN": 4.3,
    "IRN": 4.1, "JOR": 4.0, "SAU": 4.2, "ARE": 3.8, "KWT": 4.6,
    "BHR": 4.5, "PSE": 4.0, "SYR": 4.3,
    # High (3-4)
    "IND": 3.9, "PAK": 3.8, "TUR": 3.5, "EGY": 3.6,
    "CHN": 3.1, "ZAF": 3.0, "IRQ": 3.4, "AFG": 3.3,
    # Medium-High (2-3)
    "MEX": 2.8, "AUS": 2.5, "THA": 2.3, "USA": 2.2,
    "KOR": 2.1, "ESP": 2.0, "ITA": 2.3, "UKR": 2.0,
    "MYS": 1.9, "PHL": 2.0, "BGD": 2.4, "MMR": 1.8,
    "ETH": 2.6, "NGA": 2.3, "SDN": 3.2, "SSD": 2.8,
    "SOM": 3.5, "TCD": 3.0, "MOZ": 2.2,
    # Low-Medium (1-2)
    "JPN": 1.8, "DEU": 1.7, "VNM": 1.6, "IDN": 1.4,
    "FRA": 1.3, "GBR": 1.2, "TWN": 1.7, "SGP": 1.5,
    "LKA": 1.6, "KHM": 1.5, "LAO": 1.3, "NPL": 1.5,
    # Low (<1)
    "BRA": 0.9, "CAN": 0.8, "RUS": 0.7, "NOR": 0.5,
    "SWE": 0.6, "DNK": 0.8, "CHE": 0.7,
    "PRK": 2.5,
}

# ISO3 -> Country name for evidence messages
ISO3_TO_NAME: dict[str, str] = {v: k.title() for k, v in COUNTRY_TO_ISO3.items()}


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


def _try_resource_watch_api(iso3: str) -> Optional[float]:
    """Resource Watch API経由でAqueductデータ取得を試行"""
    try:
        # Try known Aqueduct dataset IDs on Resource Watch
        dataset_ids = [
            "d4778fee-30aa-4bbd-8e5b-a1f4e3205619",  # Aqueduct Water Risk
        ]
        for dataset_id in dataset_ids:
            sql = (
                f"SELECT * FROM \"{dataset_id}\" "
                f"WHERE iso_a3 = '{iso3}' LIMIT 1"
            )
            resp = requests.get(
                RESOURCE_WATCH_API,
                params={"sql": sql},
                timeout=10,
                headers=HEADERS,
            )
            if resp.status_code == 200:
                data = resp.json()
                rows = data.get("data", [])
                if rows:
                    row = rows[0]
                    # Try different possible field names
                    for field in ["bws_raw", "bws_score", "ows_raw", "w_awr_def_tot_cat"]:
                        val = row.get(field)
                        if val is not None:
                            return float(val)
    except Exception:
        pass
    return None


def _get_water_risk_score(iso3: str) -> Optional[float]:
    """水リスクスコアを取得 (API -> static fallback)"""
    # Try API first
    api_val = _try_resource_watch_api(iso3)
    if api_val is not None:
        return api_val

    # Static fallback
    return STATIC_WATER_RISK.get(iso3)


def _risk_category(score_0to5: float) -> str:
    """0-5スケールのリスクカテゴリ"""
    if score_0to5 >= 4.0:
        return "極めて高い (Extremely High)"
    elif score_0to5 >= 3.0:
        return "高い (High)"
    elif score_0to5 >= 2.0:
        return "中〜高 (Medium-High)"
    elif score_0to5 >= 1.0:
        return "低〜中 (Low-Medium)"
    else:
        return "低い (Low)"


def get_water_risk(location: str) -> dict:
    """水リスクスコアを取得

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
        Score = water_risk_raw * 20 (convert 0-5 to 0-100)
    """
    iso3 = _resolve_iso3(location)
    raw = _get_water_risk_score(iso3)

    if raw is None:
        return {
            "score": 0,
            "evidence": [f"[WRI Aqueduct] {location} ({iso3}) のデータなし"],
        }

    # Convert 0-5 scale to 0-100
    score = min(100, max(0, int(raw * 20)))
    category = _risk_category(raw)

    evidence = [
        f"[WRI Aqueduct] {location}: 水リスクスコア={raw:.1f}/5.0 ({category})",
    ]

    # Additional context for high-risk areas
    if raw >= 3.0:
        evidence.append(
            f"[WRI Aqueduct] 水ストレスが高く、産業用水の安定供給にリスク"
        )
    if raw >= 4.0:
        evidence.append(
            f"[WRI Aqueduct] 極度の水不足地域。サプライチェーン途絶の可能性"
        )

    return {"score": score, "evidence": evidence}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_locations = [
        "Japan", "China", "India", "Yemen", "Germany",
        "USA", "Qatar", "Brazil", "Australia", "Singapore",
    ]
    print("=" * 70)
    print("WRI Aqueduct Water Risk Test")
    print("=" * 70)
    for loc in test_locations:
        result = get_water_risk(loc)
        print(f"\n{loc}:")
        print(f"  Score: {result['score']}/100")
        for e in result["evidence"]:
            print(f"  {e}")
    print("\n" + "=" * 70)
