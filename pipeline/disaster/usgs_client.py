"""USGS Earthquake API
リアルタイム地震データ。全世界。APIキー不要。
https://earthquake.usgs.gov/fdsnws/event/1/
"""
import requests
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2

USGS_BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"
# Real-time GeoJSON feeds (better performance)
USGS_FEEDS = {
    "significant_month": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson",
    "4.5_week": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson",
    "2.5_day": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
    "all_hour": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
}


def fetch_earthquakes(min_magnitude: float = 4.5, days_back: int = 7) -> list[dict]:
    """指定期間の地震データを取得"""
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)

    params = {
        "format": "geojson",
        "starttime": start.strftime("%Y-%m-%d"),
        "endtime": end.strftime("%Y-%m-%d"),
        "minmagnitude": min_magnitude,
        "orderby": "magnitude",
        "limit": 200,
    }

    resp = requests.get(USGS_BASE, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [0, 0, 0])

        results.append({
            "id": feature.get("id"),
            "magnitude": props.get("mag"),
            "place": props.get("place", ""),
            "time": datetime.utcfromtimestamp(props["time"] / 1000).isoformat() if props.get("time") else None,
            "tsunami": props.get("tsunami", 0),
            "alert": props.get("alert"),  # green/yellow/orange/red
            "significance": props.get("sig", 0),
            "lon": coords[0] if len(coords) > 0 else 0,
            "lat": coords[1] if len(coords) > 1 else 0,
            "depth_km": coords[2] if len(coords) > 2 else 0,
            "url": props.get("url"),
        })

    return results


def fetch_significant_earthquakes() -> list[dict]:
    """直近1ヶ月の重大地震を取得（GeoJSONフィード使用、高パフォーマンス）"""
    resp = requests.get(USGS_FEEDS["significant_month"], timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [0, 0, 0])
        results.append({
            "id": feature.get("id"),
            "magnitude": props.get("mag"),
            "place": props.get("place", ""),
            "time": datetime.utcfromtimestamp(props["time"] / 1000).isoformat() if props.get("time") else None,
            "tsunami": props.get("tsunami", 0),
            "alert": props.get("alert"),
            "significance": props.get("sig", 0),
            "lon": coords[0],
            "lat": coords[1],
            "depth_km": coords[2],
            "url": props.get("url"),
        })

    return results


def get_earthquake_risk_for_location(location: str, lat: float = None, lon: float = None, radius_km: float = 500) -> dict:
    """指定地域の地震リスクを評価"""
    quakes = fetch_earthquakes(min_magnitude=4.0, days_back=30)

    relevant = []
    for q in quakes:
        # 場所名マッチ
        if location and location.lower() in q["place"].lower():
            relevant.append(q)
        # 座標マッチ
        elif lat and lon and q["lat"] and q["lon"]:
            R = 6371
            dlat = radians(q["lat"] - lat)
            dlon = radians(q["lon"] - lon)
            a = sin(dlat/2)**2 + cos(radians(lat)) * cos(radians(q["lat"])) * sin(dlon/2)**2
            distance = R * 2 * atan2(sqrt(a), sqrt(1-a))
            if distance <= radius_km:
                relevant.append(q)

    if not relevant:
        return {"score": 0, "quakes": [], "evidence": []}

    max_mag = max(q["magnitude"] for q in relevant if q["magnitude"])
    big_quakes = [q for q in relevant if q["magnitude"] and q["magnitude"] >= 6.0]
    has_tsunami = any(q["tsunami"] for q in relevant)

    # スコア算出
    score = 0
    if max_mag >= 7.0:
        score = 90
    elif max_mag >= 6.0:
        score = 70
    elif max_mag >= 5.0:
        score = 50
    elif max_mag >= 4.0:
        score = 30

    if has_tsunami:
        score = min(100, score + 20)

    score = min(100, score + len(relevant) * 2)

    evidence = []
    evidence.append(f"直近30日間にM4.0以上の地震{len(relevant)}件（最大M{max_mag:.1f}）")
    if has_tsunami:
        evidence.append("津波警報あり")
    for q in relevant[:3]:
        evidence.append(f"  M{q['magnitude']:.1f} - {q['place']} ({q['time']})")

    return {
        "score": score,
        "quake_count": len(relevant),
        "max_magnitude": max_mag,
        "quakes": relevant[:10],
        "evidence": evidence,
    }
