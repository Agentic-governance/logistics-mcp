"""台風・ハリケーン追跡 + NOAA宇宙天気
NOAA NHC/JTWC: 台風トラッキング
NOAA SWPC: 太陽嵐・地磁気嵐（通信障害リスク）
すべてAPIキー不要
"""
import requests
from datetime import datetime
import json

# NOAA Active Tropical Cyclones (GeoJSON)
NOAA_ACTIVE_STORMS_URL = "https://www.nhc.noaa.gov/CurrentSurfaces.json"
# NOAA Space Weather
SWPC_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
SWPC_ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"
SWPC_SOLAR_WIND_URL = "https://services.swpc.noaa.gov/products/summary/solar-wind-speed.json"


def fetch_active_tropical_cyclones() -> list[dict]:
    """アクティブな熱帯低気圧一覧"""
    # NOAA AT/EP/CP basins + JTWC WP/IO/SH basins
    basins = {
        "AT": "https://www.nhc.noaa.gov/CurrentSurfaces.json",
        "EP": "https://www.nhc.noaa.gov/CurrentSurfaces_ep.json",
    }

    results = []
    for basin, url in basins.items():
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            for storm in data.get("activeStorms", []):
                results.append({
                    "basin": basin,
                    "name": storm.get("name", ""),
                    "classification": storm.get("classification", ""),
                    "lat": storm.get("lat"),
                    "lon": storm.get("lon"),
                    "wind_mph": storm.get("wind"),
                    "pressure_mb": storm.get("pressure"),
                    "movement": storm.get("movement", ""),
                })
        except Exception:
            pass

    return results


def fetch_space_weather() -> dict:
    """太陽活動・地磁気嵐データ"""
    result = {"kp_index": None, "solar_wind_speed": None, "alerts": []}

    # Kp指数（地磁気嵐の強度: 0-9）
    try:
        resp = requests.get(SWPC_KP_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data and len(data) > 1:
            latest = data[-1]
            result["kp_index"] = float(latest[1]) if len(latest) > 1 else None
            result["kp_time"] = latest[0] if latest else ""
    except Exception:
        pass

    # 太陽風速度
    try:
        resp = requests.get(SWPC_SOLAR_WIND_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result["solar_wind_speed"] = data.get("WindSpeed")
    except Exception:
        pass

    # アクティブアラート
    try:
        resp = requests.get(SWPC_ALERTS_URL, timeout=10)
        resp.raise_for_status()
        alerts = resp.json()
        for alert in alerts[:5]:
            result["alerts"].append({
                "product_id": alert.get("product_id", ""),
                "issue_datetime": alert.get("issue_datetime", ""),
                "message": alert.get("message", "")[:200],
            })
    except Exception:
        pass

    return result


def get_typhoon_risk_for_location(lat: float, lon: float, location_name: str = "") -> dict:
    """台風リスク評価"""
    score = 0
    evidence = []

    storms = fetch_active_tropical_cyclones()
    if storms:
        from math import radians, sin, cos, sqrt, atan2
        R = 6371

        for storm in storms:
            slat = storm.get("lat")
            slon = storm.get("lon")
            if slat is None or slon is None:
                continue
            try:
                slat, slon = float(slat), float(slon)
            except (ValueError, TypeError):
                continue

            dlat = radians(slat - lat)
            dlon = radians(slon - lon)
            a = sin(dlat/2)**2 + cos(radians(lat)) * cos(radians(slat)) * sin(dlon/2)**2
            distance = R * 2 * atan2(sqrt(a), sqrt(1-a))

            if distance < 500:
                wind = storm.get("wind_mph", 0) or 0
                if wind > 110:
                    score = max(score, 95)
                elif wind > 74:
                    score = max(score, 80)
                elif wind > 39:
                    score = max(score, 60)
                else:
                    score = max(score, 40)
                evidence.append(
                    f"[台風] {storm['name']} ({storm.get('classification','')}) "
                    f"距離{distance:.0f}km, 風速{wind}mph"
                )
            elif distance < 1000:
                score = max(score, 25)
                evidence.append(f"[台風] {storm['name']} 距離{distance:.0f}km（接近注意）")

    # 宇宙天気
    space = fetch_space_weather()
    kp = space.get("kp_index")
    if kp and kp >= 7:
        score = max(score, 50)
        evidence.append(f"[宇宙天気] Kp={kp:.0f}（強い地磁気嵐 - GPS/通信障害リスク）")
    elif kp and kp >= 5:
        score = max(score, 20)
        evidence.append(f"[宇宙天気] Kp={kp:.0f}（地磁気嵐 - 軽微な通信影響の可能性）")

    return {"score": min(100, score), "evidence": evidence, "active_storms": storms[:5]}
