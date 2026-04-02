"""Disease.sh - パンデミック・感染症データ
COVID-19 + 各種感染症データ。完全無料・キー不要。
https://disease.sh/
"""
import requests
from datetime import datetime

DISEASE_BASE = "https://disease.sh/v3/covid-19"

# WHO Disease Outbreak News (DON) - 新興感染症
WHO_DON_URL = "https://www.who.int/feeds/entity/don/en/rss.xml"


def fetch_covid_by_country(country: str) -> dict:
    """国別COVID-19最新データ"""
    try:
        resp = requests.get(f"{DISEASE_BASE}/countries/{country}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "country": data.get("country", ""),
            "cases": data.get("cases", 0),
            "today_cases": data.get("todayCases", 0),
            "deaths": data.get("deaths", 0),
            "today_deaths": data.get("todayDeaths", 0),
            "recovered": data.get("recovered", 0),
            "active": data.get("active", 0),
            "critical": data.get("critical", 0),
            "cases_per_million": data.get("casesPerOneMillion", 0),
            "deaths_per_million": data.get("deathsPerOneMillion", 0),
            "tests": data.get("tests", 0),
            "population": data.get("population", 0),
            "updated": datetime.utcfromtimestamp(data["updated"] / 1000).isoformat() if data.get("updated") else "",
        }
    except Exception as e:
        print(f"Disease.sh error ({country}): {e}")
        return {}


def fetch_covid_global() -> dict:
    """グローバルCOVID-19統計"""
    try:
        resp = requests.get(f"{DISEASE_BASE}/all", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "cases": data.get("cases", 0),
            "today_cases": data.get("todayCases", 0),
            "deaths": data.get("deaths", 0),
            "today_deaths": data.get("todayDeaths", 0),
            "active": data.get("active", 0),
            "critical": data.get("critical", 0),
            "updated": datetime.utcfromtimestamp(data["updated"] / 1000).isoformat() if data.get("updated") else "",
        }
    except Exception as e:
        print(f"Disease.sh global error: {e}")
        return {}


def fetch_influenza_data() -> list[dict]:
    """インフルエンザデータ（Disease.sh経由）"""
    try:
        resp = requests.get(f"https://disease.sh/v3/influenza/ihnnrt/reports", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


# Static health infrastructure risk scores (based on WHO/GHO 2024 data)
# Score 0-100: 0=excellent health infrastructure, 100=critical health risk
HEALTH_RISK_BASELINE = {
    "Japan": 3, "United States": 8, "Germany": 5, "United Kingdom": 6, "France": 7,
    "Italy": 7, "Canada": 5, "China": 15, "India": 35, "Russia": 22,
    "Brazil": 25, "South Africa": 38, "Indonesia": 32, "Vietnam": 28, "Thailand": 22,
    "Malaysia": 18, "Singapore": 3, "Philippines": 33, "Myanmar": 48, "Cambodia": 42,
    "Saudi Arabia": 15, "UAE": 10, "Iran": 28, "Iraq": 45, "Turkey": 20,
    "Israel": 5, "Qatar": 8, "Yemen": 62, "South Korea": 4, "Taiwan": 5,
    "North Korea": 55, "Bangladesh": 42, "Pakistan": 45, "Sri Lanka": 25,
    "Nigeria": 52, "Ethiopia": 58, "Kenya": 42, "Egypt": 32, "South Sudan": 68,
    "Somalia": 72, "Ukraine": 28, "Poland": 8, "Netherlands": 4, "Switzerland": 3,
    "Mexico": 22, "Colombia": 25, "Venezuela": 45, "Argentina": 15, "Chile": 12,
    "Australia": 4,
}


def _resolve_country_for_disease(location: str) -> str:
    """Normalize country name for Disease.sh API."""
    aliases = {
        "united states": "USA", "usa": "USA", "us": "USA",
        "united kingdom": "UK", "uk": "UK", "south korea": "S. Korea",
        "north korea": "N. Korea", "uae": "UAE",
        "taiwan": "Taiwan", "hong kong": "China",
    }
    loc = location.lower().strip()
    return aliases.get(loc, location)


def get_health_risk_for_location(location: str) -> dict:
    """感染症リスク評価"""
    resolved_name = _resolve_country_for_disease(location)
    covid = fetch_covid_by_country(resolved_name)

    if not covid:
        # Fallback to static health infrastructure risk
        for country, baseline_score in HEALTH_RISK_BASELINE.items():
            if country.lower() == location.lower() or location.lower() in country.lower():
                return {
                    "score": baseline_score,
                    "evidence": [
                        f"[健康] {country}: 医療インフラリスクスコア {baseline_score}/100（WHO/GHOベースライン）",
                        "[健康] ライブ感染症データ未取得 - 静的ベースライン使用",
                    ],
                }
        return {"score": 0, "evidence": []}

    score = 0
    evidence = []

    today_cases = covid.get("today_cases", 0)
    today_deaths = covid.get("today_deaths", 0)
    critical = covid.get("critical", 0)
    population = covid.get("population", 1)

    today_per_million = (today_cases / population * 1_000_000) if population else 0
    critical_per_million = (critical / population * 1_000_000) if population else 0

    if today_per_million > 500:
        score = 70
    elif today_per_million > 200:
        score = 50
    elif today_per_million > 50:
        score = 30
    elif today_per_million > 10:
        score = 15
    elif today_cases > 0:
        score = 5
    else:
        # No active cases - use static baseline as minimum
        for country, baseline_score in HEALTH_RISK_BASELINE.items():
            if country.lower() == location.lower() or location.lower() in country.lower():
                score = max(score, baseline_score // 3)  # Dampen static score when API works
                break

    if critical_per_million > 50:
        score = min(100, score + 20)
    elif critical_per_million > 10:
        score = min(100, score + 10)
    elif critical > 1000:
        score = min(100, score + 5)

    if today_deaths > 100:
        score = min(100, score + 15)
    elif today_deaths > 10:
        score = min(100, score + 5)

    evidence.append(f"COVID-19: 本日新規 {today_cases:,}件, 本日死者 {today_deaths:,}人")
    evidence.append(f"  重症者: {critical:,}人, 百万人あたり新規: {today_per_million:.1f}件")

    return {
        "score": min(100, score),
        "covid_data": covid,
        "evidence": evidence,
    }
