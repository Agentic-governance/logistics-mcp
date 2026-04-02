"""AIS船舶追跡クライアント
aisstream.io - 無料リアルタイムAISデータ（WebSocket）
AISHub - 無料AISデータ集約（REST API）
"""
import requests
import json
import os
from datetime import datetime

AISHUB_API_KEY = os.getenv("AISHUB_API_KEY", "")
AISHUB_BASE = "http://data.aishub.net/ws.php"


def fetch_vessels_in_area(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> list[dict]:
    """指定海域の船舶位置を取得（AISHub）"""
    if not AISHUB_API_KEY:
        return []

    params = {
        "username": AISHUB_API_KEY,
        "format": "1",  # JSON
        "output": "json",
        "compress": "0",
        "latmin": lat_min,
        "latmax": lat_max,
        "lonmin": lon_min,
        "lonmax": lon_max,
    }

    try:
        resp = requests.get(AISHUB_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for vessel in data if isinstance(data, list) else data.get("vessels", []):
            results.append({
                "mmsi": vessel.get("MMSI"),
                "name": vessel.get("NAME", ""),
                "imo": vessel.get("IMO"),
                "ship_type": vessel.get("TYPE"),
                "lat": vessel.get("LATITUDE"),
                "lon": vessel.get("LONGITUDE"),
                "speed": vessel.get("SPEED"),
                "heading": vessel.get("HEADING"),
                "destination": vessel.get("DESTINATION", ""),
                "eta": vessel.get("ETA", ""),
                "last_update": vessel.get("TIME", ""),
            })

        return results
    except Exception as e:
        print(f"AISHub error: {e}")
        return []


def get_shipping_lane_congestion(region: str) -> dict:
    """主要航路の混雑状況を推定"""
    # 主要チョークポイントの座標
    CHOKEPOINTS = {
        "suez": {"lat_min": 29.5, "lat_max": 31.5, "lon_min": 32.0, "lon_max": 33.0, "name": "Suez Canal"},
        "malacca": {"lat_min": 1.0, "lat_max": 3.0, "lon_min": 100.0, "lon_max": 104.5, "name": "Strait of Malacca"},
        "hormuz": {"lat_min": 25.5, "lat_max": 27.5, "lon_min": 55.5, "lon_max": 57.5, "name": "Strait of Hormuz"},
        "panama": {"lat_min": 8.5, "lat_max": 9.5, "lon_min": -80.0, "lon_max": -79.0, "name": "Panama Canal"},
        "gibraltar": {"lat_min": 35.5, "lat_max": 36.5, "lon_min": -6.0, "lon_max": -5.0, "name": "Strait of Gibraltar"},
        "taiwan": {"lat_min": 22.0, "lat_max": 26.0, "lon_min": 118.0, "lon_max": 122.0, "name": "Taiwan Strait"},
        "bab_el_mandeb": {"lat_min": 12.0, "lat_max": 13.5, "lon_min": 43.0, "lon_max": 44.5, "name": "Bab el-Mandeb"},
    }

    region_lower = region.lower()
    relevant_chokepoints = {}
    for key, coords in CHOKEPOINTS.items():
        if key in region_lower or region_lower in coords["name"].lower():
            relevant_chokepoints[key] = coords

    if not relevant_chokepoints and not AISHUB_API_KEY:
        return {"score": 0, "chokepoints": list(CHOKEPOINTS.keys()), "evidence": []}

    results = {}
    for key, coords in relevant_chokepoints.items():
        vessels = fetch_vessels_in_area(
            coords["lat_min"], coords["lat_max"],
            coords["lon_min"], coords["lon_max"]
        )
        results[key] = {
            "name": coords["name"],
            "vessel_count": len(vessels),
            "cargo_vessels": len([v for v in vessels if v.get("ship_type") in [70, 71, 72, 73, 74, 79]]),
        }

    return {"chokepoints": results, "evidence": []}
