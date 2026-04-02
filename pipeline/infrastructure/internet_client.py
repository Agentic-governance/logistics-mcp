"""インターネット・インフラ障害検知
Cloudflare Radar + IODA (Georgia Tech)
APIキー不要
"""
import requests
from datetime import datetime, timedelta

CLOUDFLARE_RADAR_BASE = "https://api.cloudflare.com/client/v4/radar"
IODA_BASE = "https://api.ioda.inetintel.cc.gatech.edu/v2"


def fetch_internet_outages_cloudflare(country_code: str = None) -> list[dict]:
    """Cloudflare Radar: インターネット障害検知"""
    url = f"{CLOUDFLARE_RADAR_BASE}/annotations/outages"
    params = {"format": "json", "limit": 20}
    if country_code:
        params["location"] = country_code.upper()

    try:
        resp = requests.get(url, params=params, timeout=15,
                            headers={"User-Agent": "SupplyChainRiskIntelligence/1.0"})
        resp.raise_for_status()
        data = resp.json()
        results = []
        for outage in data.get("result", {}).get("annotations", []):
            results.append({
                "id": outage.get("id"),
                "start": outage.get("startDate", ""),
                "end": outage.get("endDate", ""),
                "description": outage.get("description", ""),
                "locations": outage.get("locations", []),
                "scope": outage.get("scope", ""),
                "event_type": outage.get("eventType", ""),
            })
        return results
    except Exception as e:
        return []


def fetch_ioda_country_outages(country_code: str, hours_back: int = 24) -> dict:
    """IODA: 国レベルのインターネット接続障害"""
    end = datetime.utcnow()
    start = end - timedelta(hours=hours_back)

    url = f"{IODA_BASE}/signals/raw/country/{country_code.upper()}"
    params = {
        "from": int(start.timestamp()),
        "until": int(end.timestamp()),
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


# 国コードマッピング
COUNTRY_TO_ISO2 = {
    "japan": "JP", "china": "CN", "united states": "US", "usa": "US",
    "south korea": "KR", "korea": "KR", "taiwan": "TW",
    "thailand": "TH", "vietnam": "VN", "indonesia": "ID",
    "malaysia": "MY", "singapore": "SG", "philippines": "PH",
    "india": "IN", "germany": "DE", "australia": "AU",
    "russia": "RU", "ukraine": "UA", "myanmar": "MM",
    "bangladesh": "BD", "pakistan": "PK", "turkey": "TR",
    "brazil": "BR", "mexico": "MX", "nigeria": "NG",
    "egypt": "EG", "south africa": "ZA",
    "united kingdom": "GB", "france": "FR", "italy": "IT",
    "canada": "CA", "saudi arabia": "SA", "uae": "AE",
}


def _resolve_iso2(location: str) -> str:
    loc = location.lower().strip()
    if loc in COUNTRY_TO_ISO2:
        return COUNTRY_TO_ISO2[loc]
    for name, code in COUNTRY_TO_ISO2.items():
        if loc in name or name in loc:
            return code
    if len(loc) == 2 and loc.isalpha():
        return loc.upper()
    return ""


def get_internet_risk_for_location(location: str) -> dict:
    """インターネットインフラリスク評価"""
    iso2 = _resolve_iso2(location)
    score = 0
    evidence = []

    if iso2:
        outages = fetch_internet_outages_cloudflare(iso2)
        if outages:
            recent = [o for o in outages if not o.get("end")]  # 未解決
            resolved = [o for o in outages if o.get("end")]

            if recent:
                score = max(score, 70)
                for o in recent[:3]:
                    evidence.append(f"[Cloudflare] アクティブ障害: {o.get('description', 'N/A')[:80]}")
            elif resolved:
                score = max(score, 20)
                evidence.append(f"[Cloudflare] 直近に{len(resolved)}件の障害が復旧済み")

    # インフラ脆弱国のフォールバック
    HIGH_RISK_INTERNET = {
        "myanmar": 70, "north korea": 95, "syria": 75,
        "yemen": 65, "ethiopia": 55, "sudan": 60,
        "iran": 60, "cuba": 55, "turkmenistan": 65,
    }
    loc = location.lower()
    for country, risk in HIGH_RISK_INTERNET.items():
        if country in loc or loc in country:
            score = max(score, risk)
            evidence.append(f"[インフラ] {location}はインターネットインフラ脆弱国")
            break

    return {"score": score, "evidence": evidence}
