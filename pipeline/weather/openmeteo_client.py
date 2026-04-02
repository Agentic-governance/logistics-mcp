"""Open-Meteo - 統合気象API
天気予報・海洋気象・大気質をキー不要で取得
https://open-meteo.com/
完全無料（非商用10,000コール/日）・APIキー不要
"""
import requests
from datetime import datetime

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# 主要物流拠点の座標
LOCATION_COORDS = {
    "tokyo": (35.68, 139.69), "osaka": (34.69, 135.50), "nagoya": (35.18, 136.91),
    "yokohama": (35.44, 139.64), "kobe": (34.69, 135.20), "fukuoka": (33.59, 130.40),
    "japan": (35.68, 139.69), "shanghai": (31.23, 121.47), "shenzhen": (22.54, 114.06),
    "guangzhou": (23.13, 113.26), "beijing": (39.90, 116.40), "china": (31.23, 121.47),
    "hong kong": (22.32, 114.17), "singapore": (1.35, 103.82),
    "busan": (35.18, 129.08), "south korea": (37.57, 126.98), "korea": (37.57, 126.98),
    "kaohsiung": (22.62, 120.31), "taiwan": (25.03, 121.57),
    "bangkok": (13.76, 100.50), "thailand": (13.76, 100.50),
    "ho chi minh": (10.82, 106.63), "hanoi": (21.03, 105.85), "vietnam": (10.82, 106.63),
    "jakarta": (6.21, 106.85), "indonesia": (-6.21, 106.85),
    "kuala lumpur": (3.14, 101.69), "malaysia": (3.14, 101.69),
    "manila": (14.60, 120.98), "philippines": (14.60, 120.98),
    "mumbai": (19.08, 72.88), "delhi": (28.61, 77.21), "chennai": (13.08, 80.27), "india": (19.08, 72.88),
    "los angeles": (33.94, -118.41), "long beach": (33.77, -118.19),
    "new york": (40.71, -74.01), "united states": (33.94, -118.41), "usa": (33.94, -118.41),
    "rotterdam": (51.92, 4.48), "hamburg": (53.55, 9.99), "germany": (53.55, 9.99),
    "dubai": (25.20, 55.27), "uae": (25.20, 55.27), "jebel ali": (25.01, 55.06),
    "sydney": (33.87, 151.21), "australia": (-33.87, 151.21),
    "suez": (29.97, 32.55), "egypt": (30.04, 31.24),
    "panama": (9.00, -79.52), "malacca": (2.19, 102.25),
    "ukraine": (50.45, 30.52), "russia": (55.76, 37.62), "myanmar": (16.87, 96.20),
    "yemen": (15.35, 44.21), "syria": (33.51, 36.29), "afghanistan": (34.53, 69.17),
    "ethiopia": (9.02, 38.75), "somalia": (2.05, 45.34), "sudan": (15.60, 32.53),
    "nigeria": (6.52, 3.38), "south africa": (-33.92, 18.42), "kenya": (1.29, 36.82),
    "brazil": (-23.55, -46.63), "mexico": (19.43, -99.13), "turkey": (41.01, 28.98),
    "united kingdom": (51.51, -0.13), "france": (48.86, 2.35), "italy": (45.46, 9.19),
    "canada": (49.28, -123.12), "saudi arabia": (21.49, 39.19),
    "pakistan": (24.86, 67.01), "bangladesh": (23.81, 90.41),
    "colombia": (4.71, -74.07), "venezuela": (10.49, -66.88),
    "iraq": (33.31, 44.37), "iran": (35.69, 51.39),
    "north korea": (39.02, 125.75), "haiti": (18.54, -72.34),
    "south sudan": (4.85, 31.58), "libya": (32.90, 13.18),
    "cambodia": (11.56, 104.93), "israel": (32.07, 34.78), "qatar": (25.29, 51.53),
    "sri lanka": (6.93, 79.85), "poland": (52.23, 21.01), "netherlands": (52.37, 4.90),
    "switzerland": (47.38, 8.54), "argentina": (-34.60, -58.38), "chile": (-33.45, -70.67),
}


def _resolve_coords(location: str) -> tuple:
    """地名から座標を解決"""
    loc = location.lower().strip()
    if loc in LOCATION_COORDS:
        return LOCATION_COORDS[loc]
    for name, coords in LOCATION_COORDS.items():
        if loc in name or name in loc:
            return coords
    return None


def fetch_weather_forecast(lat: float, lon: float) -> dict:
    """7日間天気予報取得"""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 7,
    }
    try:
        resp = requests.get(FORECAST_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        results = []
        dates = daily.get("time", [])
        for i, date in enumerate(dates):
            results.append({
                "date": date,
                "weather_code": _safe_idx(daily.get("weather_code"), i),
                "temp_max": _safe_idx(daily.get("temperature_2m_max"), i),
                "temp_min": _safe_idx(daily.get("temperature_2m_min"), i),
                "precip_sum_mm": _safe_idx(daily.get("precipitation_sum"), i),
                "wind_max_kmh": _safe_idx(daily.get("wind_speed_10m_max"), i),
                "precip_prob_pct": _safe_idx(daily.get("precipitation_probability_max"), i),
            })
        return {"location": f"{lat},{lon}", "timezone": data.get("timezone"), "daily": results}
    except Exception as e:
        return {"error": str(e)}


def fetch_marine_weather(lat: float, lon: float) -> dict:
    """海洋気象（波高・うねり・海流）取得"""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wave_height,wave_direction,wave_period,swell_wave_height,swell_wave_direction,swell_wave_period",
        "daily": "wave_height_max,wave_direction_dominant,wave_period_max,swell_wave_height_max",
        "timezone": "auto",
        "forecast_days": 7,
    }
    try:
        resp = requests.get(MARINE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        results = []
        for i, date in enumerate(daily.get("time", [])):
            results.append({
                "date": date,
                "wave_height_max_m": _safe_idx(daily.get("wave_height_max"), i),
                "wave_direction": _safe_idx(daily.get("wave_direction_dominant"), i),
                "wave_period_max_s": _safe_idx(daily.get("wave_period_max"), i),
                "swell_height_max_m": _safe_idx(daily.get("swell_wave_height_max"), i),
            })
        return {"location": f"{lat},{lon}", "daily": results}
    except Exception as e:
        return {"error": str(e)}


def fetch_air_quality(lat: float, lon: float) -> dict:
    """大気質データ取得"""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,us_aqi",
        "timezone": "auto",
        "forecast_days": 3,
    }
    try:
        resp = requests.get(AIR_QUALITY_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        # 直近の値を取得
        if times:
            latest_idx = min(len(times) - 1, 24)  # 直近24時間以内
            return {
                "location": f"{lat},{lon}",
                "time": times[latest_idx] if latest_idx < len(times) else "",
                "us_aqi": _safe_idx(hourly.get("us_aqi"), latest_idx),
                "pm2_5": _safe_idx(hourly.get("pm2_5"), latest_idx),
                "pm10": _safe_idx(hourly.get("pm10"), latest_idx),
                "no2": _safe_idx(hourly.get("nitrogen_dioxide"), latest_idx),
                "so2": _safe_idx(hourly.get("sulphur_dioxide"), latest_idx),
                "o3": _safe_idx(hourly.get("ozone"), latest_idx),
                "co": _safe_idx(hourly.get("carbon_monoxide"), latest_idx),
            }
        return {"error": "no data"}
    except Exception as e:
        return {"error": str(e)}


def get_weather_risk_for_location(lat: float, lon: float, location_name: str = "") -> dict:
    """気象リスクスコア算出"""
    score = 0
    evidence = []

    # 天気予報リスク
    forecast = fetch_weather_forecast(lat, lon)
    if "daily" in forecast:
        for day in forecast["daily"][:3]:  # 3日間
            code = day.get("weather_code", 0) or 0
            wind = day.get("wind_max_kmh", 0) or 0
            precip = day.get("precip_sum_mm", 0) or 0

            # 暴風 (WMO code 95-99: 雷雨/ひょう)
            if code >= 95:
                score = max(score, 70)
                evidence.append(f"[気象] {day['date']}: 激しい雷雨/ひょう予報 (code={code})")
            elif code >= 80:
                score = max(score, 40)
            elif code >= 60:
                score = max(score, 25)

            # 強風
            if wind > 100:
                score = max(score, 80)
                evidence.append(f"[気象] {day['date']}: 暴風 {wind:.0f}km/h")
            elif wind > 60:
                score = max(score, 50)
                evidence.append(f"[気象] {day['date']}: 強風 {wind:.0f}km/h")

            # 大雨
            if precip > 100:
                score = max(score, 60)
                evidence.append(f"[気象] {day['date']}: 大雨 {precip:.0f}mm")
            elif precip > 50:
                score = max(score, 35)

    # 海洋気象リスク
    marine = fetch_marine_weather(lat, lon)
    if "daily" in marine:
        for day in marine["daily"][:3]:
            wave = day.get("wave_height_max_m", 0) or 0
            swell = day.get("swell_height_max_m", 0) or 0
            if wave > 6:
                score = max(score, 70)
                evidence.append(f"[海象] {day['date']}: 高波 {wave:.1f}m（航行危険）")
            elif wave > 4:
                score = max(score, 45)
                evidence.append(f"[海象] {day['date']}: 波高 {wave:.1f}m（航行注意）")

    # 大気質リスク
    aq = fetch_air_quality(lat, lon)
    aqi = aq.get("us_aqi", 0) or 0
    if aqi > 200:
        score = max(score, 50)
        evidence.append(f"[大気質] AQI={aqi}（非常に悪い）- 工場操業停止リスク")
    elif aqi > 150:
        score = max(score, 30)
        evidence.append(f"[大気質] AQI={aqi}（不健康）")

    if not evidence:
        evidence.append(f"[気象] {location_name or f'{lat},{lon}'}: 3日以内に重大気象リスクなし")

    return {"score": min(100, score), "evidence": evidence}


# WMO Weather Code → description
WMO_CODES = {
    0: "快晴", 1: "晴れ", 2: "曇り", 3: "曇天", 45: "霧", 48: "着氷性の霧",
    51: "弱い霧雨", 53: "霧雨", 55: "強い霧雨", 61: "弱い雨", 63: "雨", 65: "強い雨",
    71: "弱い雪", 73: "雪", 75: "強い雪", 80: "にわか雨", 81: "強いにわか雨",
    82: "激しいにわか雨", 85: "弱い吹雪", 86: "強い吹雪",
    95: "雷雨", 96: "雷雨+ひょう(弱)", 99: "雷雨+ひょう(強)",
}


def _safe_idx(lst, idx):
    if lst and idx < len(lst):
        return lst[idx]
    return None


def get_weather_risk_by_name(location: str) -> dict:
    """地名から気象リスクを評価（便利関数）"""
    coords = _resolve_coords(location)
    if not coords:
        return {"score": 0, "evidence": [f"[気象] {location}: 座標不明"]}
    return get_weather_risk_for_location(coords[0], coords[1], location)
