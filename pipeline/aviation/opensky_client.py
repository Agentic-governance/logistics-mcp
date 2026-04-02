"""OpenSky Network - 航空交通モニタリング
リアルタイム航空機追跡データ
https://opensky-network.org/
APIキー不要（レート制限: 匿名10秒/コール、認証5秒/コール）
"""
import requests
from datetime import datetime, timedelta

OPENSKY_BASE = "https://opensky-network.org/api"

# 主要空港のICAO/IATA コード + 座標
MAJOR_AIRPORTS = {
    "tokyo": {"icao": "RJTT", "iata": "HND", "name": "東京羽田", "lat": 35.55, "lon": 139.78},
    "narita": {"icao": "RJAA", "iata": "NRT", "name": "成田", "lat": 35.76, "lon": 140.39},
    "osaka": {"icao": "RJBB", "iata": "KIX", "name": "関西国際", "lat": 34.43, "lon": 135.24},
    "shanghai": {"icao": "ZSPD", "iata": "PVG", "name": "上海浦東", "lat": 31.14, "lon": 121.81},
    "beijing": {"icao": "ZBAD", "iata": "PKX", "name": "北京大興", "lat": 39.51, "lon": 116.41},
    "hong kong": {"icao": "VHHH", "iata": "HKG", "name": "香港", "lat": 22.31, "lon": 113.91},
    "singapore": {"icao": "WSSS", "iata": "SIN", "name": "チャンギ", "lat": 1.36, "lon": 103.99},
    "incheon": {"icao": "RKSI", "iata": "ICN", "name": "仁川", "lat": 37.46, "lon": 126.44},
    "taipei": {"icao": "RCTP", "iata": "TPE", "name": "桃園", "lat": 25.08, "lon": 121.23},
    "bangkok": {"icao": "VTBS", "iata": "BKK", "name": "スワンナプーム", "lat": 13.69, "lon": 100.75},
    "dubai": {"icao": "OMDB", "iata": "DXB", "name": "ドバイ", "lat": 25.25, "lon": 55.36},
    "los angeles": {"icao": "KLAX", "iata": "LAX", "name": "ロサンゼルス", "lat": 33.94, "lon": -118.41},
    "frankfurt": {"icao": "EDDF", "iata": "FRA", "name": "フランクフルト", "lat": 50.03, "lon": 8.57},
    "sydney": {"icao": "YSSY", "iata": "SYD", "name": "シドニー", "lat": -33.95, "lon": 151.18},
    "mumbai": {"icao": "VABB", "iata": "BOM", "name": "ムンバイ", "lat": 19.09, "lon": 72.87},
    "hanoi": {"icao": "VVNB", "iata": "HAN", "name": "ノイバイ", "lat": 21.22, "lon": 105.81},
    "jakarta": {"icao": "WIII", "iata": "CGK", "name": "スカルノ・ハッタ", "lat": -6.13, "lon": 106.66},
    "kuala lumpur": {"icao": "WMKK", "iata": "KUL", "name": "KLIA", "lat": 2.74, "lon": 101.70},
    "manila": {"icao": "RPLL", "iata": "MNL", "name": "ニノイ・アキノ", "lat": 14.51, "lon": 121.02},
}

# Extended airports for country-level lookups
MAJOR_AIRPORTS.update({
    "london": {"icao": "EGLL", "iata": "LHR", "name": "ヒースロー", "lat": 51.47, "lon": -0.46},
    "paris": {"icao": "LFPG", "iata": "CDG", "name": "シャルル・ド・ゴール", "lat": 49.01, "lon": 2.55},
    "milan": {"icao": "LIMC", "iata": "MXP", "name": "マルペンサ", "lat": 45.63, "lon": 8.72},
    "toronto": {"icao": "CYYZ", "iata": "YYZ", "name": "ピアソン", "lat": 43.68, "lon": -79.63},
    "moscow": {"icao": "UUEE", "iata": "SVO", "name": "シェレメーチエヴォ", "lat": 55.97, "lon": 37.41},
    "sao paulo": {"icao": "SBGR", "iata": "GRU", "name": "グアルーリョス", "lat": -23.43, "lon": -46.47},
    "johannesburg": {"icao": "FAOR", "iata": "JNB", "name": "O.R.タンボ", "lat": -26.14, "lon": 28.24},
    "yangon": {"icao": "VYYY", "iata": "RGN", "name": "ヤンゴン", "lat": 16.91, "lon": 96.13},
    "phnom penh": {"icao": "VDPP", "iata": "PNH", "name": "プノンペン", "lat": 11.55, "lon": 104.84},
    "riyadh": {"icao": "OERK", "iata": "RUH", "name": "キング・ハーリド", "lat": 24.96, "lon": 46.70},
    "tehran": {"icao": "OIIE", "iata": "IKA", "name": "イマーム・ホメイニー", "lat": 35.42, "lon": 51.15},
    "baghdad": {"icao": "ORBI", "iata": "BGW", "name": "バグダッド", "lat": 33.26, "lon": 44.23},
    "istanbul": {"icao": "LTFM", "iata": "IST", "name": "イスタンブール", "lat": 41.26, "lon": 28.74},
    "tel aviv": {"icao": "LLBG", "iata": "TLV", "name": "ベン・グリオン", "lat": 32.01, "lon": 34.89},
    "doha": {"icao": "OTHH", "iata": "DOH", "name": "ハマド", "lat": 25.27, "lon": 51.61},
    "sanaa": {"icao": "OYSN", "iata": "SAH", "name": "サナア", "lat": 15.48, "lon": 44.22},
    "pyongyang": {"icao": "ZKPY", "iata": "FNJ", "name": "平壌", "lat": 39.22, "lon": 125.67},
    "dhaka": {"icao": "VGHS", "iata": "DAC", "name": "ハズラット・シャージャラル", "lat": 23.84, "lon": 90.40},
    "karachi": {"icao": "OPKC", "iata": "KHI", "name": "ジンナー", "lat": 24.91, "lon": 67.16},
    "colombo": {"icao": "VCBI", "iata": "CMB", "name": "バンダーラナーヤカ", "lat": 7.18, "lon": 79.88},
    "lagos": {"icao": "DNMM", "iata": "LOS", "name": "ムルタラ・ムハンマド", "lat": 6.58, "lon": 3.32},
    "addis ababa": {"icao": "HAAB", "iata": "ADD", "name": "ボレ", "lat": 8.98, "lon": 38.80},
    "nairobi": {"icao": "HKJK", "iata": "NBO", "name": "ジョモ・ケニヤッタ", "lat": -1.32, "lon": 36.93},
    "cairo": {"icao": "HECA", "iata": "CAI", "name": "カイロ", "lat": 30.12, "lon": 31.41},
    "juba": {"icao": "HJJJ", "iata": "JUB", "name": "ジュバ", "lat": 4.87, "lon": 31.60},
    "mogadishu": {"icao": "HCMM", "iata": "MGQ", "name": "モガディシュ", "lat": 2.01, "lon": 45.30},
    "kyiv": {"icao": "UKBB", "iata": "KBP", "name": "ボリースピリ", "lat": 50.34, "lon": 30.89},
    "warsaw": {"icao": "EPWA", "iata": "WAW", "name": "ショパン", "lat": 52.17, "lon": 20.97},
    "amsterdam": {"icao": "EHAM", "iata": "AMS", "name": "スキポール", "lat": 52.31, "lon": 4.76},
    "zurich": {"icao": "LSZH", "iata": "ZRH", "name": "チューリッヒ", "lat": 47.46, "lon": 8.55},
    "mexico city": {"icao": "MMMX", "iata": "MEX", "name": "ベニート・フアレス", "lat": 19.44, "lon": -99.07},
    "bogota": {"icao": "SKBO", "iata": "BOG", "name": "エル・ドラード", "lat": 4.70, "lon": -74.15},
    "caracas": {"icao": "SVMI", "iata": "CCS", "name": "シモン・ボリバル", "lat": 10.60, "lon": -66.99},
    "buenos aires": {"icao": "SAEZ", "iata": "EZE", "name": "エセイサ", "lat": -34.82, "lon": -58.54},
    "santiago": {"icao": "SCEL", "iata": "SCL", "name": "アルトゥーロ・メリノ・ベニテス", "lat": -33.39, "lon": -70.79},
})

# Country → main cargo/logistics airport mapping
COUNTRY_AIRPORTS = {
    "japan": "tokyo", "united states": "los angeles", "usa": "los angeles",
    "germany": "frankfurt", "united kingdom": "london", "france": "paris",
    "italy": "milan", "canada": "toronto", "china": "shanghai",
    "india": "mumbai", "russia": "moscow", "brazil": "sao paulo",
    "south africa": "johannesburg", "indonesia": "jakarta",
    "vietnam": "hanoi", "thailand": "bangkok", "malaysia": "kuala lumpur",
    "singapore": "singapore", "philippines": "manila", "myanmar": "yangon",
    "cambodia": "phnom penh", "saudi arabia": "riyadh", "uae": "dubai",
    "iran": "tehran", "iraq": "baghdad", "turkey": "istanbul",
    "israel": "tel aviv", "qatar": "doha", "yemen": "sanaa",
    "south korea": "incheon", "taiwan": "taipei", "north korea": "pyongyang",
    "bangladesh": "dhaka", "pakistan": "karachi", "sri lanka": "colombo",
    "nigeria": "lagos", "ethiopia": "addis ababa", "kenya": "nairobi",
    "egypt": "cairo", "south sudan": "juba", "somalia": "mogadishu",
    "ukraine": "kyiv", "poland": "warsaw", "netherlands": "amsterdam",
    "switzerland": "zurich", "mexico": "mexico city", "colombia": "bogota",
    "venezuela": "caracas", "argentina": "buenos aires", "chile": "santiago",
    "australia": "sydney",
}

# Static aviation connectivity risk (lower connectivity = higher risk)
# Score 0-100: 0=excellent connectivity, 100=very poor
AVIATION_BASELINE = {
    "Japan": 2, "United States": 2, "Germany": 3, "United Kingdom": 3, "France": 3,
    "Italy": 5, "Canada": 4, "China": 5, "India": 15, "Russia": 12,
    "Brazil": 10, "South Africa": 12, "Indonesia": 15, "Vietnam": 18, "Thailand": 10,
    "Malaysia": 8, "Singapore": 2, "Philippines": 18, "Myanmar": 35, "Cambodia": 30,
    "Saudi Arabia": 8, "UAE": 3, "Iran": 25, "Iraq": 35, "Turkey": 8,
    "Israel": 10, "Qatar": 4, "Yemen": 55, "South Korea": 3, "Taiwan": 5,
    "North Korea": 70, "Bangladesh": 28, "Pakistan": 22, "Sri Lanka": 20,
    "Nigeria": 25, "Ethiopia": 20, "Kenya": 18, "Egypt": 15, "South Sudan": 60,
    "Somalia": 55, "Ukraine": 40, "Poland": 8, "Netherlands": 3, "Switzerland": 4,
    "Mexico": 10, "Colombia": 15, "Venezuela": 30, "Argentina": 12, "Chile": 12,
    "Australia": 5,
}


def fetch_flights_in_area(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> list[dict]:
    """指定エリアの飛行中航空機数を取得"""
    url = f"{OPENSKY_BASE}/states/all"
    params = {
        "lamin": lat_min, "lamax": lat_max,
        "lomin": lon_min, "lomax": lon_max,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        states = data.get("states", [])
        results = []
        for s in states[:100]:  # max 100
            results.append({
                "icao24": s[0] if len(s) > 0 else "",
                "callsign": (s[1] or "").strip() if len(s) > 1 else "",
                "origin_country": s[2] if len(s) > 2 else "",
                "lat": s[6] if len(s) > 6 else None,
                "lon": s[5] if len(s) > 5 else None,
                "altitude_m": s[7] if len(s) > 7 else None,
                "velocity_ms": s[9] if len(s) > 9 else None,
                "on_ground": s[8] if len(s) > 8 else None,
            })
        return results
    except Exception:
        return []


def fetch_airport_departures(icao: str, hours_back: int = 12) -> list[dict]:
    """空港の出発便一覧"""
    end = int(datetime.utcnow().timestamp())
    begin = end - hours_back * 3600
    url = f"{OPENSKY_BASE}/flights/departure"
    params = {"airport": icao, "begin": begin, "end": end}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def fetch_airport_arrivals(icao: str, hours_back: int = 12) -> list[dict]:
    """空港の到着便一覧"""
    end = int(datetime.utcnow().timestamp())
    begin = end - hours_back * 3600
    url = f"{OPENSKY_BASE}/flights/arrival"
    params = {"airport": icao, "begin": begin, "end": end}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def _resolve_airport(location: str) -> dict:
    loc = location.lower().strip()
    # Direct airport match
    if loc in MAJOR_AIRPORTS:
        return MAJOR_AIRPORTS[loc]
    for name, info in MAJOR_AIRPORTS.items():
        if loc in name or name in loc:
            return info
        if loc == info["iata"].lower() or loc == info["icao"].lower():
            return info
    # Country → airport mapping
    airport_key = COUNTRY_AIRPORTS.get(loc)
    if airport_key and airport_key in MAJOR_AIRPORTS:
        return MAJOR_AIRPORTS[airport_key]
    return {}


def get_aviation_activity(location: str) -> dict:
    """航空交通活動状況"""
    airport = _resolve_airport(location)
    if not airport:
        return {"flights_in_area": 0, "airport": None}

    lat, lon = airport["lat"], airport["lon"]
    # 空港周辺2度のエリア
    flights = fetch_flights_in_area(lat - 1, lat + 1, lon - 1, lon + 1)

    return {
        "airport": airport,
        "flights_in_area": len(flights),
        "sample_flights": flights[:10],
    }


def get_aviation_risk_for_location(location: str) -> dict:
    """航空リスク評価（異常な交通量変化検知）"""
    activity = get_aviation_activity(location)
    airport = activity.get("airport")
    score = 0
    evidence = []

    if not airport:
        # Static fallback for country-level
        for country, baseline in AVIATION_BASELINE.items():
            if country.lower() == location.lower() or location.lower() in country.lower() or country.lower() in location.lower():
                return {
                    "score": baseline,
                    "evidence": [f"[航空] {country}: 航空接続性リスクスコア {baseline}/100（ベースライン）"],
                }
        return {"score": 0, "evidence": []}

    flights_count = activity.get("flights_in_area", 0)

    if flights_count == 0:
        score = 40
        evidence.append(f"[航空] {airport['name']}: 周辺に飛行中の航空機なし（空域閉鎖の可能性）")
    elif flights_count < 5:
        score = 20
        evidence.append(f"[航空] {airport['name']}: 周辺航空機{flights_count}機（通常より少ない可能性）")
    else:
        evidence.append(f"[航空] {airport['name']}: 周辺航空機{flights_count}機（正常範囲）")

    return {"score": score, "evidence": evidence, "details": activity}
