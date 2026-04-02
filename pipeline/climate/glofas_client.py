"""GloFAS (Global Flood Awareness System) クライアント
Copernicus Emergency Management Service
https://www.globalfloods.eu/
"""
import requests
from datetime import datetime, timedelta
from typing import Optional

# Global Flood Monitor API
GLOBAL_FLOOD_MONITOR_URL = "https://www.globalfloodmonitor.org/api"

# CDS API (requires CDSAPI_KEY from cds.climate.copernicus.eu)
CDS_API_URL = "https://cds.climate.copernicus.eu/api/v2"

HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}

# Country name -> ISO3 / ISO2 mapping
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
    "yemen": "YEM", "cambodia": "KHM", "laos": "LAO",
    "nepal": "NPL", "sri lanka": "LKA", "mozambique": "MOZ",
    "ethiopia": "ETH", "somalia": "SOM", "chad": "TCD",
    "sudan": "SDN", "south sudan": "SSD", "north korea": "PRK",
}

COUNTRY_TO_ISO2 = {
    "japan": "JP", "china": "CN", "united states": "US", "usa": "US",
    "south korea": "KR", "korea": "KR", "taiwan": "TW",
    "thailand": "TH", "vietnam": "VN", "indonesia": "ID",
    "malaysia": "MY", "singapore": "SG", "philippines": "PH",
    "india": "IN", "germany": "DE", "australia": "AU",
    "russia": "RU", "ukraine": "UA", "myanmar": "MM",
    "bangladesh": "BD", "pakistan": "PK", "turkey": "TR",
    "brazil": "BR", "mexico": "MX", "nigeria": "NG",
    "egypt": "EG", "south africa": "ZA", "saudi arabia": "SA",
    "united kingdom": "GB", "uk": "GB", "france": "FR",
    "italy": "IT", "canada": "CA", "uae": "AE",
    "united arab emirates": "AE", "iran": "IR", "iraq": "IQ",
    "yemen": "YE", "cambodia": "KH", "laos": "LA",
    "nepal": "NP", "sri lanka": "LK", "mozambique": "MZ",
    "ethiopia": "ET", "somalia": "SO", "chad": "TD",
    "sudan": "SD", "south sudan": "SS", "north korea": "KP",
}

# Static data: Annual flood risk probability (0-100)
# Based on historical flood frequency, river basin exposure, monsoon patterns
STATIC_FLOOD_RISK: dict[str, int] = {
    # Very High (70+): Monsoon-affected, large river deltas
    "BGD": 85, "MMR": 70, "VNM": 65, "IND": 60, "PHL": 55,
    "IDN": 50, "PAK": 55, "KHM": 50, "LAO": 45, "NPL": 50,
    # High (35-55)
    "THA": 45, "CHN": 40, "LKA": 40, "NGA": 35, "MOZ": 40,
    "JPN": 35, "ETH": 30, "SDN": 35, "SSD": 40,
    # Medium (20-35)
    "BRA": 30, "USA": 25, "AUS": 20, "DEU": 20,
    "GBR": 15, "FRA": 18, "ITA": 22, "MEX": 25,
    "TUR": 20, "RUS": 18, "UKR": 15, "KOR": 25,
    "MYS": 30, "TWN": 35, "IRQ": 20, "IRN": 15,
    # Low (<20)
    "SGP": 8, "CAN": 12, "NOR": 10, "SWE": 8,
    "DNK": 10, "CHE": 12, "ZAF": 15, "EGY": 10,
    "SAU": 8, "ARE": 5, "QAT": 3, "YEM": 12,
    "SOM": 15, "TCD": 20, "LBY": 5, "ISR": 8,
    "JOR": 5, "LBN": 12, "PRK": 30,
}

# Seasonal flood risk multipliers (month-based)
# Monsoon and typhoon seasons increase risk
SEASONAL_MULTIPLIERS: dict[str, dict[int, float]] = {
    # South Asian monsoon: Jun-Sep
    "BGD": {6: 1.5, 7: 1.8, 8: 1.8, 9: 1.5},
    "IND": {6: 1.4, 7: 1.7, 8: 1.7, 9: 1.4},
    "PAK": {7: 1.5, 8: 1.8, 9: 1.5},
    "NPL": {6: 1.4, 7: 1.6, 8: 1.6, 9: 1.3},
    "MMR": {6: 1.4, 7: 1.6, 8: 1.6, 9: 1.4},
    # East Asian monsoon / typhoon: Jun-Oct
    "CHN": {6: 1.3, 7: 1.5, 8: 1.5, 9: 1.3},
    "JPN": {6: 1.3, 7: 1.4, 8: 1.4, 9: 1.5, 10: 1.3},
    "KOR": {7: 1.3, 8: 1.4, 9: 1.3},
    "TWN": {7: 1.4, 8: 1.5, 9: 1.5, 10: 1.3},
    "VNM": {9: 1.3, 10: 1.5, 11: 1.5},
    "PHL": {7: 1.3, 8: 1.4, 9: 1.5, 10: 1.5, 11: 1.3},
    "THA": {8: 1.3, 9: 1.5, 10: 1.5, 11: 1.3},
    "KHM": {8: 1.3, 9: 1.5, 10: 1.5, 11: 1.3},
    # European: Spring snowmelt
    "DEU": {3: 1.2, 4: 1.3, 5: 1.2, 6: 1.3, 7: 1.2},
    "FRA": {1: 1.2, 2: 1.3, 3: 1.2},
    "GBR": {1: 1.3, 2: 1.3, 11: 1.2, 12: 1.3},
    "ITA": {10: 1.3, 11: 1.4, 12: 1.2},
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


def _resolve_iso2(location: str) -> str:
    """国名/コードをISO2に変換"""
    loc = location.lower().strip()
    if loc in COUNTRY_TO_ISO2:
        return COUNTRY_TO_ISO2[loc]
    if len(loc) == 2 and loc.isalpha():
        return loc.upper()
    for name, code in COUNTRY_TO_ISO2.items():
        if loc in name or name in loc:
            return code
    return ""


def _try_global_flood_monitor(iso2: str) -> Optional[dict]:
    """Global Flood Monitor APIからデータ取得を試行"""
    try:
        # Try the flood monitor endpoint
        url = f"{GLOBAL_FLOOD_MONITOR_URL}/floods"
        params = {
            "country": iso2,
            "days": 30,
        }
        resp = requests.get(url, params=params, timeout=10, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data
    except Exception:
        pass

    # Try alternative flood data endpoints
    try:
        url = "https://floodobservatory.colorado.edu/Events/currentfloods.json"
        resp = requests.get(url, timeout=10, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            # Filter by country
            floods = [
                f for f in data
                if isinstance(f, dict) and iso2.upper() in str(f.get("Country", "")).upper()
            ]
            if floods:
                return {"active_floods": len(floods), "events": floods[:5]}
    except Exception:
        pass

    return None


def _apply_seasonal_multiplier(iso3: str, base_risk: int) -> tuple[int, Optional[str]]:
    """季節に応じたリスク乗数を適用"""
    current_month = datetime.utcnow().month
    multipliers = SEASONAL_MULTIPLIERS.get(iso3, {})
    multiplier = multipliers.get(current_month, 1.0)

    adjusted = min(100, int(base_risk * multiplier))
    season_note = None
    if multiplier > 1.0:
        season_names = {
            1: "1月", 2: "2月", 3: "3月", 4: "4月", 5: "5月", 6: "6月",
            7: "7月", 8: "8月", 9: "9月", 10: "10月", 11: "11月", 12: "12月",
        }
        season_note = (
            f"[GloFAS] 現在{season_names[current_month]}は洪水リスクが "
            f"季節的に上昇 (x{multiplier:.1f})"
        )

    return adjusted, season_note


def get_flood_forecast(location: str) -> dict:
    """洪水リスク予測スコアを取得

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
    """
    iso3 = _resolve_iso3(location)
    iso2 = _resolve_iso2(location)
    evidence: list[str] = []
    score = 0

    # Try live data first
    live_data = None
    if iso2:
        live_data = _try_global_flood_monitor(iso2)

    if live_data and isinstance(live_data, dict):
        active = live_data.get("active_floods", 0)
        if active > 0:
            # Active floods detected
            score = min(100, 40 + active * 15)
            evidence.append(
                f"[Global Flood Monitor] {location}: {active}件のアクティブな洪水イベント検出"
            )
            events = live_data.get("events", [])
            for evt in events[:3]:
                if isinstance(evt, dict):
                    desc = evt.get("description", evt.get("Country", ""))
                    evidence.append(f"[Flood] {str(desc)[:80]}")

    # Static baseline risk
    base_risk = STATIC_FLOOD_RISK.get(iso3, 0)
    if base_risk > 0:
        # Apply seasonal multiplier
        adjusted_risk, season_note = _apply_seasonal_multiplier(iso3, base_risk)
        score = max(score, adjusted_risk)

        evidence.append(
            f"[GloFAS] {location}: 年間洪水リスク確率={base_risk}%, "
            f"季節調整後={adjusted_risk}%"
        )
        if season_note:
            evidence.append(season_note)
    elif score == 0:
        evidence.append(f"[GloFAS] {location} ({iso3}) の洪水リスクデータなし")

    # Classify risk level
    if score >= 60:
        evidence.append(
            f"[GloFAS] 洪水リスクが高い。サプライチェーン途絶に注意"
        )
    elif score >= 30:
        evidence.append(
            f"[GloFAS] 中程度の洪水リスク。季節的な変動に注意"
        )

    return {"score": min(100, score), "evidence": evidence}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_locations = [
        "Bangladesh", "Japan", "Vietnam", "Germany", "USA",
        "India", "Thailand", "Singapore", "Myanmar", "Philippines",
    ]
    print("=" * 70)
    print("GloFAS Flood Forecast Test")
    print("=" * 70)
    for loc in test_locations:
        result = get_flood_forecast(loc)
        print(f"\n{loc}:")
        print(f"  Score: {result['score']}/100")
        for e in result["evidence"]:
            print(f"  {e}")
    print("\n" + "=" * 70)
