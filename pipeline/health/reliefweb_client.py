"""ReliefWeb API - 人道危機・災害レポート
UN OCHA運営。世界中の災害・人道危機レポート。
https://api.reliefweb.int/v1
注: appname登録が必要（RELIEFWEB_APPNAME環境変数）
登録不要の代替: GDACS + USGS でカバー
"""
import requests
import os
from datetime import datetime, timedelta

RELIEFWEB_BASE = "https://api.reliefweb.int/v1"
RELIEFWEB_APPNAME = os.getenv("RELIEFWEB_APPNAME", "")
HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}

# 人道危機の高リスク国（ReliefWeb APIなしのフォールバック）
HUMANITARIAN_RISK_MAP = {
    "syria": 90, "yemen": 90, "afghanistan": 85, "sudan": 85,
    "south sudan": 85, "somalia": 80, "ethiopia": 75,
    "democratic republic of congo": 80, "drc": 80,
    "myanmar": 75, "haiti": 75, "ukraine": 70,
    "central african republic": 70, "car": 70,
    "burkina faso": 65, "niger": 60, "mali": 65,
    "nigeria": 55, "mozambique": 55, "chad": 60,
    "libya": 55, "iraq": 50, "palestine": 80,
    "lebanon": 55, "pakistan": 45, "bangladesh": 45,
    "cameroon": 45, "colombia": 40,
}


def fetch_disasters(country: str = None, days_back: int = 30, limit: int = 50) -> list[dict]:
    """災害レポート取得"""
    if not RELIEFWEB_APPNAME:
        return []

    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00+00:00")

    payload = {
        "appname": RELIEFWEB_APPNAME,
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "date.created", "value": {"from": since}},
            ],
        },
        "fields": {
            "include": ["id", "name", "status", "glide", "primary_country",
                         "primary_type", "date", "url"],
        },
        "sort": ["date.created:desc"],
        "limit": limit,
    }

    if country:
        payload["filter"]["conditions"].append(
            {"field": "primary_country.name", "value": country, "operator": "LIKE"}
        )

    try:
        resp = requests.post(f"{RELIEFWEB_BASE}/disasters",
                             json=payload, timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("data", []):
            fields = item.get("fields", {})
            results.append({
                "id": item.get("id"),
                "name": fields.get("name", ""),
                "status": fields.get("status", ""),
                "glide": fields.get("glide", ""),
                "country": fields.get("primary_country", {}).get("name", "")
                           if isinstance(fields.get("primary_country"), dict) else "",
                "type": fields.get("primary_type", {}).get("name", "")
                        if isinstance(fields.get("primary_type"), dict) else "",
                "date_created": fields.get("date", {}).get("created", "")
                               if isinstance(fields.get("date"), dict) else "",
                "url": fields.get("url", ""),
            })
        return results
    except Exception as e:
        print(f"ReliefWeb disasters error: {e}")
        return []


def fetch_crisis_reports(country: str = None, days_back: int = 7, limit: int = 20) -> list[dict]:
    """人道危機レポート取得"""
    if not RELIEFWEB_APPNAME:
        return []

    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00+00:00")

    payload = {
        "appname": RELIEFWEB_APPNAME,
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "date.created", "value": {"from": since}},
            ],
        },
        "fields": {
            "include": ["id", "title", "source", "primary_country", "date", "url", "format"],
        },
        "sort": ["date.created:desc"],
        "limit": limit,
    }

    if country:
        payload["filter"]["conditions"].append(
            {"field": "primary_country.name", "value": country, "operator": "LIKE"}
        )

    try:
        resp = requests.post(f"{RELIEFWEB_BASE}/reports",
                             json=payload, timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("data", []):
            fields = item.get("fields", {})
            results.append({
                "id": item.get("id"),
                "title": fields.get("title", ""),
                "source": [s.get("name", "") for s in fields.get("source", [])]
                          if isinstance(fields.get("source"), list) else [],
                "country": fields.get("primary_country", {}).get("name", "")
                           if isinstance(fields.get("primary_country"), dict) else "",
                "date_created": fields.get("date", {}).get("created", "")
                               if isinstance(fields.get("date"), dict) else "",
                "format": fields.get("format", {}).get("name", "")
                          if isinstance(fields.get("format"), dict) else "",
                "url": fields.get("url", ""),
            })
        return results
    except Exception as e:
        print(f"ReliefWeb reports error: {e}")
        return []


def get_humanitarian_risk_for_location(location: str) -> dict:
    """人道危機リスク評価"""
    # ReliefWeb API available
    disasters = fetch_disasters(country=location, days_back=90)
    reports = fetch_crisis_reports(country=location, days_back=30)

    if disasters or reports:
        score = 0
        evidence = []

        active_disasters = [d for d in disasters if d.get("status") in ("alert", "ongoing", "current")]
        score += min(40, len(active_disasters) * 15)
        score += min(20, len(disasters) * 3)
        score += min(30, len(reports) * 5)

        high_impact_types = {"Complex Emergency", "Epidemic", "Flood", "Earthquake",
                              "Tropical Cyclone", "Tsunami", "Drought", "Volcano"}
        for d in disasters:
            if d.get("type") in high_impact_types:
                score += 5

        score = min(100, score)

        if active_disasters:
            evidence.append(f"ReliefWeb: アクティブ災害 {len(active_disasters)}件")
            for d in active_disasters[:3]:
                evidence.append(f"  [{d.get('type', 'N/A')}] {d['name']}")

        if reports:
            evidence.append(f"直近30日の人道レポート: {len(reports)}件")

        return {
            "score": score,
            "disaster_count": len(disasters),
            "active_disasters": len(active_disasters) if disasters else 0,
            "report_count": len(reports),
            "disasters": disasters[:10],
            "reports": reports[:10],
            "evidence": evidence,
        }

    # フォールバック: 静的リスクマッピング
    location_lower = location.lower()
    for region, risk_score in HUMANITARIAN_RISK_MAP.items():
        if region in location_lower or location_lower in region:
            return {
                "score": risk_score,
                "disaster_count": 0,
                "report_count": 0,
                "evidence": [f"[静的評価] {location}は人道危機リスクの高い地域 (スコア: {risk_score})"],
            }

    return {"score": 0, "disaster_count": 0, "report_count": 0, "evidence": []}
