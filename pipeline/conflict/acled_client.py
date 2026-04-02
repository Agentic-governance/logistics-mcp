"""ACLED - Armed Conflict Location & Event Data
武力紛争・政治暴力イベント（抗議活動含む）
https://acleddata.com/
無料アカウント登録でAPIキー取得可能
"""
import requests
import os
from datetime import datetime, timedelta

ACLED_API_BASE = "https://api.acleddata.com/acled/read"
ACLED_KEY = os.getenv("ACLED_API_KEY", "")
ACLED_EMAIL = os.getenv("ACLED_EMAIL", "")

# 紛争リスク高い地域（APIキーなしのフォールバック用）
HIGH_CONFLICT_REGIONS = {
    "ukraine": 95, "russia": 60, "myanmar": 90, "syria": 85,
    "yemen": 90, "sudan": 85, "ethiopia": 75, "somalia": 80,
    "iraq": 65, "afghanistan": 80, "mali": 70, "burkina faso": 75,
    "niger": 65, "nigeria": 60, "democratic republic of congo": 80,
    "drc": 80, "congo": 70, "palestine": 85, "israel": 60,
    "libya": 70, "haiti": 65, "pakistan": 55, "mozambique": 55,
    "cameroon": 50, "central african republic": 70, "car": 70,
    "south sudan": 75, "chad": 55, "lebanon": 60, "taiwan": 40,
}


def fetch_conflict_events(country: str = None, days_back: int = 30, limit: int = 500) -> list[dict]:
    """ACLED APIから紛争イベントを取得"""
    if not ACLED_KEY or not ACLED_EMAIL:
        return []

    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params = {
        "key": ACLED_KEY,
        "email": ACLED_EMAIL,
        "event_date": f"{since}|{datetime.utcnow().strftime('%Y-%m-%d')}",
        "event_date_where": "BETWEEN",
        "limit": limit,
        "fields": "event_id_cnty|event_date|event_type|sub_event_type|actor1|actor2|country|admin1|admin2|location|latitude|longitude|fatalities|notes",
    }

    if country:
        params["country"] = country

    try:
        resp = requests.get(ACLED_API_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for event in data.get("data", []):
            results.append({
                "event_id": event.get("event_id_cnty", ""),
                "date": event.get("event_date", ""),
                "event_type": event.get("event_type", ""),
                "sub_type": event.get("sub_event_type", ""),
                "actor1": event.get("actor1", ""),
                "actor2": event.get("actor2", ""),
                "country": event.get("country", ""),
                "admin1": event.get("admin1", ""),
                "location": event.get("location", ""),
                "lat": _safe_float(event.get("latitude")),
                "lon": _safe_float(event.get("longitude")),
                "fatalities": int(event.get("fatalities", 0) or 0),
                "notes": event.get("notes", ""),
            })

        return results
    except Exception as e:
        print(f"ACLED API error: {e}")
        return []


def get_conflict_risk_for_location(location: str) -> dict:
    """紛争・政治リスク評価"""
    location_lower = location.lower()

    # ACLED APIがあれば使用
    events = fetch_conflict_events(country=location, days_back=30)

    if events:
        battles = [e for e in events if e["event_type"] in ("Battles", "Explosions/Remote violence")]
        violence_against_civilians = [e for e in events if e["event_type"] == "Violence against civilians"]
        protests = [e for e in events if e["event_type"] in ("Protests", "Riots")]
        total_fatalities = sum(e["fatalities"] for e in events)

        # スコア算出
        score = 0
        score += min(40, len(battles) * 2)
        score += min(20, len(violence_against_civilians) * 3)
        score += min(15, len(protests))
        score += min(25, total_fatalities // 10)
        score = min(100, score)

        evidence = [
            f"ACLED: 直近30日間に{len(events)}件の紛争・暴力イベント",
            f"  戦闘: {len(battles)}件, 市民への暴力: {len(violence_against_civilians)}件",
            f"  抗議・暴動: {len(protests)}件, 死者数: {total_fatalities}人",
        ]

        return {
            "score": score,
            "event_count": len(events),
            "fatalities": total_fatalities,
            "events": events[:10],
            "evidence": evidence,
        }

    # フォールバック: ハードコードされたリスクスコア
    for region, risk_score in HIGH_CONFLICT_REGIONS.items():
        if region in location_lower or location_lower in region:
            return {
                "score": risk_score,
                "event_count": 0,
                "evidence": [f"[静的評価] {location}は紛争リスクの高い地域 (スコア: {risk_score})"],
            }

    return {"score": 0, "event_count": 0, "evidence": []}


def _safe_float(val) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
