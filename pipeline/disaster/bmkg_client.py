"""BMKG (インドネシア気象気候地球物理庁)
インドネシアの地震・津波・気象データ
https://data.bmkg.go.id/
APIキー不要
"""
import requests
from math import radians, sin, cos, sqrt, atan2

BMKG_RECENT = "https://data.bmkg.go.id/DataMKG/TEWS/gempaterkini.json"
BMKG_LATEST = "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json"
BMKG_FELT = "https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json"


def fetch_recent_earthquakes() -> list[dict]:
    """インドネシア周辺の最近の地震"""
    try:
        resp = requests.get(BMKG_RECENT, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        quakes = data.get("Infogempa", {}).get("gempa", [])
        results = []
        for q in quakes:
            coords = q.get("Coordinates", "").split(",")
            lat = float(coords[0]) if len(coords) > 0 else None
            lon = float(coords[1]) if len(coords) > 1 else None
            results.append({
                "date": q.get("Tanggal", ""),
                "datetime": q.get("DateTime", ""),
                "magnitude": float(q.get("Magnitude", 0)),
                "depth_km": q.get("Kedalaman", "").replace(" km", ""),
                "lat": lat, "lon": lon,
                "region": q.get("Wilayah", ""),
                "potential": q.get("Potensi", ""),
            })
        return results
    except Exception:
        return []


def fetch_felt_earthquakes() -> list[dict]:
    """体感地震（有感地震）"""
    try:
        resp = requests.get(BMKG_FELT, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        quakes = data.get("Infogempa", {}).get("gempa", [])
        results = []
        for q in quakes:
            coords = q.get("Coordinates", "").split(",")
            lat = float(coords[0]) if len(coords) > 0 else None
            lon = float(coords[1]) if len(coords) > 1 else None
            results.append({
                "date": q.get("Tanggal", ""),
                "magnitude": float(q.get("Magnitude", 0)),
                "lat": lat, "lon": lon,
                "region": q.get("Wilayah", ""),
                "felt": q.get("Dirasakan", ""),
            })
        return results
    except Exception:
        return []


def get_indonesia_earthquake_risk(lat: float = None, lon: float = None) -> dict:
    """インドネシア地震リスク評価"""
    score = 0
    evidence = []

    quakes = fetch_recent_earthquakes()
    if not quakes:
        return {"score": 0, "evidence": []}

    R = 6371
    for q in quakes:
        mag = q.get("magnitude", 0)
        qlat, qlon = q.get("lat"), q.get("lon")

        if lat and lon and qlat and qlon:
            dlat = radians(qlat - lat)
            dlon = radians(qlon - lon)
            a = sin(dlat/2)**2 + cos(radians(lat)) * cos(radians(qlat)) * sin(dlon/2)**2
            distance = R * 2 * atan2(sqrt(a), sqrt(1-a))

            if distance < 300:
                if mag >= 7.0:
                    score = max(score, 95)
                    evidence.append(f"[BMKG] M{mag} 距離{distance:.0f}km ({q['region']})")
                elif mag >= 6.0:
                    score = max(score, 75)
                    evidence.append(f"[BMKG] M{mag} 距離{distance:.0f}km ({q['region']})")
                elif mag >= 5.0:
                    score = max(score, 50)
                    evidence.append(f"[BMKG] M{mag} 距離{distance:.0f}km ({q['region']})")
        else:
            # Without coordinates, just check magnitude
            if mag >= 7.0:
                score = max(score, 60)
                evidence.append(f"[BMKG] M{mag} ({q['region']})")
            elif mag >= 6.0:
                score = max(score, 35)

    if quakes and not evidence:
        evidence.append(f"[BMKG] インドネシア周辺: 直近{len(quakes)}件の地震（接近なし）")

    return {"score": score, "evidence": evidence}
