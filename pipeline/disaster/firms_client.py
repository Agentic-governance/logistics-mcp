"""NASA FIRMS - Fire Information for Resource Management System
衛星による火災検知。工場火災・山火事をリアルタイム検知。
https://firms.modaps.eosdis.nasa.gov/api/
要MAP_KEY（無料登録）
"""
import requests
import os
from datetime import datetime

FIRMS_API_BASE = "https://firms.modaps.eosdis.nasa.gov/api"
MAP_KEY = os.getenv("NASA_FIRMS_MAP_KEY", "")

# MAP_KEY不要の代替: 直近24時間のCSVフィード
FIRMS_CSV_FEEDS = {
    "world_24h": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Global_24h.csv",
    "viirs_24h": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv",
}


def fetch_fires_near_location(lat: float, lon: float, radius_km: float = 100, days: int = 1) -> list[dict]:
    """指定座標周辺の火災を検知"""
    if MAP_KEY:
        # MAP_KEY使用時: 精密検索
        url = f"{FIRMS_API_BASE}/area/csv/{MAP_KEY}/VIIRS_SNPP_NRT/{lat - 1},{lon - 1},{lat + 1},{lon + 1}/{days}"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return _parse_csv_response(resp.text, lat, lon, radius_km)
        except Exception as e:
            print(f"FIRMS API error: {e}")

    # MAP_KEY不要: 国コードで検索
    return []


def fetch_fires_by_country(country_code: str, days: int = 1) -> list[dict]:
    """国コードで火災データ取得"""
    if not MAP_KEY:
        return []

    url = f"{FIRMS_API_BASE}/country/csv/{MAP_KEY}/VIIRS_SNPP_NRT/{country_code}/{days}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return _parse_csv_response(resp.text)
    except Exception as e:
        print(f"FIRMS country query error: {e}")
        return []


def get_fire_risk_for_location(location: str, lat: float = None, lon: float = None) -> dict:
    """火災リスク評価"""
    fires = []
    if lat and lon:
        fires = fetch_fires_near_location(lat, lon, radius_km=200, days=2)

    if not fires:
        return {"score": 0, "fire_count": 0, "evidence": []}

    # 高信頼度の火災のみカウント
    high_confidence = [f for f in fires if f.get("confidence", 0) > 70]

    score = min(100, len(high_confidence) * 5 + len(fires) * 2)
    evidence = [f"{location}周辺200km以内に{len(fires)}件の火災を衛星検知"]
    if high_confidence:
        evidence.append(f"  うち高信頼度: {len(high_confidence)}件")

    return {"score": score, "fire_count": len(fires), "evidence": evidence}


def _parse_csv_response(text: str, center_lat: float = None, center_lon: float = None, radius_km: float = None) -> list[dict]:
    """FIRMS CSVレスポンスをパース"""
    import csv
    import io
    from math import radians, sin, cos, sqrt, atan2

    reader = csv.DictReader(io.StringIO(text))
    results = []
    for row in reader:
        try:
            lat = float(row.get("latitude", 0))
            lon = float(row.get("longitude", 0))
            confidence = int(row.get("confidence", 0))
            brightness = float(row.get("bright_ti4", 0) or row.get("brightness", 0))

            # 距離フィルタ
            if center_lat and center_lon and radius_km:
                R = 6371
                dlat = radians(lat - center_lat)
                dlon = radians(lon - center_lon)
                a = sin(dlat/2)**2 + cos(radians(center_lat)) * cos(radians(lat)) * sin(dlon/2)**2
                distance = R * 2 * atan2(sqrt(a), sqrt(1-a))
                if distance > radius_km:
                    continue

            results.append({
                "lat": lat,
                "lon": lon,
                "confidence": confidence,
                "brightness": brightness,
                "acq_date": row.get("acq_date", ""),
                "acq_time": row.get("acq_time", ""),
                "satellite": row.get("satellite", ""),
            })
        except (ValueError, KeyError):
            continue

    return results
