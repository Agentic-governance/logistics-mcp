"""GDACS - Global Disaster Alert and Coordination System
リアルタイム災害アラート（地震・津波・洪水・台風）
https://www.gdacs.org/
完全無料・APIキー不要
"""
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

GDACS_RSS_URL = "https://www.gdacs.org/xml/rss.xml"
GDACS_GEOJSON_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"

HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}


@dataclass
class DisasterEvent:
    event_id: str
    event_type: str  # EQ/TC/FL/VO/DR/WF (earthquake/cyclone/flood/volcano/drought/wildfire)
    title: str
    description: str
    severity: str  # Green/Orange/Red
    alert_score: float
    country: Optional[str]
    lat: float
    lon: float
    event_date: str
    source: str = "GDACS"
    url: Optional[str] = None


def fetch_gdacs_alerts() -> list[DisasterEvent]:
    """GDACS RSSフィードから最新災害アラートを取得"""
    resp = requests.get(GDACS_RSS_URL, timeout=30, headers=HEADERS)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    events = []

    ns = {"gdacs": "http://www.gdacs.org"}

    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        description = item.findtext("description", "")
        link = item.findtext("link", "")
        pub_date = item.findtext("pubDate", "")

        event_type = item.findtext("gdacs:eventtype", "", ns)
        alert_level = item.findtext("gdacs:alertlevel", "Green", ns)
        severity_text = item.findtext("gdacs:severity", "", ns)
        country = item.findtext("gdacs:country", "", ns)
        event_id = item.findtext("gdacs:eventid", "", ns)

        # Geo coordinates
        lat_text = item.findtext("gdacs:lat", "0", ns) or item.findtext("{http://www.w3.org/2003/01/geo/wgs84_pos#}lat", "0")
        lon_text = item.findtext("gdacs:lon", "0", ns) or item.findtext("{http://www.w3.org/2003/01/geo/wgs84_pos#}long", "0")

        try:
            lat = float(lat_text)
            lon = float(lon_text)
        except (ValueError, TypeError):
            lat, lon = 0.0, 0.0

        # Alert score: Red=3, Orange=2, Green=1
        alert_score = {"Red": 3.0, "Orange": 2.0, "Green": 1.0}.get(alert_level, 0.5)

        events.append(DisasterEvent(
            event_id=event_id or f"gdacs_{len(events)}",
            event_type=event_type,
            title=title,
            description=description,
            severity=alert_level,
            alert_score=alert_score,
            country=country,
            lat=lat,
            lon=lon,
            event_date=pub_date,
            url=link,
        ))

    return events


def get_disaster_risk_for_location(location: str, lat: float = None, lon: float = None, radius_km: float = 500) -> dict:
    """指定地域の災害リスクスコアを算出"""
    events = fetch_gdacs_alerts()

    relevant = []
    for event in events:
        # 国名マッチ
        if location and event.country and location.lower() in event.country.lower():
            relevant.append(event)
        # 座標が近い場合
        elif lat and lon and event.lat and event.lon:
            from math import radians, sin, cos, sqrt, atan2
            R = 6371  # km
            dlat = radians(event.lat - lat)
            dlon = radians(event.lon - lon)
            a = sin(dlat/2)**2 + cos(radians(lat)) * cos(radians(event.lat)) * sin(dlon/2)**2
            distance = R * 2 * atan2(sqrt(a), sqrt(1-a))
            if distance <= radius_km:
                relevant.append(event)

    if not relevant:
        return {"score": 0, "events": [], "evidence": []}

    # スコア算出
    max_alert = max(e.alert_score for e in relevant)
    red_count = sum(1 for e in relevant if e.severity == "Red")
    orange_count = sum(1 for e in relevant if e.severity == "Orange")

    score = min(100, int(max_alert * 25 + red_count * 20 + orange_count * 10))

    evidence = []
    for event in relevant[:5]:
        evidence.append(f"[GDACS {event.severity}] {event.title}")

    return {
        "score": score,
        "event_count": len(relevant),
        "events": [{"id": e.event_id, "type": e.event_type, "title": e.title,
                     "severity": e.severity, "country": e.country} for e in relevant[:10]],
        "evidence": evidence,
    }
