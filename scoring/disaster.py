"""災害リスク統合スコアリング
GDACS + USGS + NASA FIRMS + 気象庁API + 静的リスクマッピング
"""
import requests

JMA_WARNINGS_URL = "https://www.jma.go.jp/bosai/warning/data/warning/{area_code}.json"

# 主要工業地帯の気象庁地域コード
LOCATION_TO_AREA = {
    "愛知": "230000", "三重": "240000", "静岡": "220000",
    "大阪": "270000", "兵庫": "280000", "福岡": "400000",
    "神奈川": "140000", "埼玉": "110000", "千葉": "120000",
    "東京": "130000", "北海道": "016000", "宮城": "040000",
    "広島": "340000", "岡山": "330000", "熊本": "430000",
    "新潟": "150000", "長野": "200000",
}

# 高リスク地域（地震・台風・洪水）
HIGH_RISK_REGIONS = {
    "台湾": 55, "taiwan": 55, "philippines": 55, "フィリピン": 55,
    "bangladesh": 55, "バングラデシュ": 55, "nepal": 50, "ネパール": 50,
    "haiti": 60, "ハイチ": 60, "indonesia": 45, "インドネシア": 45,
    "pakistan": 45, "パキスタン": 45,
}
MEDIUM_RISK_REGIONS = {
    "thailand": 35, "タイ": 35, "vietnam": 35, "ベトナム": 35,
    "china": 30, "中国": 30, "india": 30, "インド": 30,
    "mexico": 30, "メキシコ": 30, "turkey": 35, "トルコ": 35,
}

# 主要都市の座標マッピング（USGS/FIRMS検索用）
LOCATION_COORDS = {
    "東京": (35.68, 139.69), "大阪": (34.69, 135.50), "愛知": (35.18, 136.91),
    "台湾": (23.70, 120.96), "taiwan": (23.70, 120.96),
    "tokyo": (35.68, 139.69), "osaka": (34.69, 135.50),
    "bangkok": (13.76, 100.50), "manila": (14.60, 120.98),
    "jakarta": (-6.21, 106.85), "ho chi minh": (10.82, 106.63),
    "shanghai": (31.23, 121.47), "shenzhen": (22.54, 114.06),
    "mumbai": (19.08, 72.88), "delhi": (28.61, 77.21),
    "istanbul": (41.01, 28.98), "mexico city": (19.43, -99.13),
    "são paulo": (-23.55, -46.63), "sao paulo": (-23.55, -46.63),
    "surabaya": (-7.25, 112.75), "bandung": (-6.91, 107.61),
    "semarang": (-6.97, 110.42), "medan": (3.59, 98.67),
    "indonesia": (-6.21, 106.85), "インドネシア": (-6.21, 106.85),
}


def get_disaster_score(location: str) -> tuple[int, list[str]]:
    """統合災害リスクスコア算出"""
    evidence = []
    score = 0
    location_lower = location.lower()

    # --- 1. GDACS: グローバル災害アラート ---
    try:
        from pipeline.disaster.gdacs_client import get_disaster_risk_for_location
        coords = _get_coords(location)
        lat, lon = coords if coords else (None, None)
        gdacs = get_disaster_risk_for_location(location, lat=lat, lon=lon)
        if gdacs.get("score", 0) > 0:
            score = max(score, gdacs["score"])
            evidence.extend(gdacs.get("evidence", []))
    except Exception as e:
        evidence.append(f"GDACS取得エラー: {e}")

    # --- 2. USGS: 地震データ ---
    try:
        coords = _get_coords(location)
        if coords:
            from pipeline.disaster.usgs_client import get_earthquake_risk_for_location
            usgs = get_earthquake_risk_for_location(location, lat=coords[0], lon=coords[1])
            if usgs.get("score", 0) > 0:
                score = max(score, usgs["score"])
                evidence.extend(usgs.get("evidence", []))
    except Exception as e:
        evidence.append(f"USGS取得エラー: {e}")

    # --- 2b. BMKG: インドネシア地震データ ---
    if any(k in location_lower for k in ("indonesia", "インドネシア", "jakarta", "surabaya", "bandung", "semarang", "medan")):
        try:
            from pipeline.disaster.bmkg_client import get_indonesia_earthquake_risk
            coords = _get_coords(location)
            lat, lon = (coords[0], coords[1]) if coords else (None, None)
            bmkg = get_indonesia_earthquake_risk(lat=lat, lon=lon)
            if bmkg.get("score", 0) > 0:
                score = max(score, bmkg["score"])
                evidence.extend(bmkg.get("evidence", []))
        except Exception:
            pass

    # --- 3. NASA FIRMS: 火災検知 ---
    try:
        coords = _get_coords(location)
        if coords:
            from pipeline.disaster.firms_client import get_fire_risk_for_location
            fires = get_fire_risk_for_location(location, lat=coords[0], lon=coords[1])
            if fires.get("score", 0) > 0:
                # 火災は他の災害より影響小さめ（直接インフラ被害でない限り）
                fire_score = fires["score"] // 2
                score = max(score, fire_score)
                evidence.extend(fires.get("evidence", []))
    except Exception as e:
        pass  # FIRMS is optional (requires MAP_KEY)

    # --- 4. 気象庁: 日本国内の警報 ---
    for loc_key, area_code in LOCATION_TO_AREA.items():
        if loc_key in location:
            try:
                resp = requests.get(JMA_WARNINGS_URL.format(area_code=area_code), timeout=5)
                data = resp.json()
                warnings = data.get("areaTypes", [])
                if warnings:
                    score = max(score, 60)
                    evidence.append(f"気象庁: {location}に現在警報発令中")
            except Exception:
                pass

    # --- 5. 静的リスクマッピング（フォールバック） ---
    if score == 0:
        for region, risk_val in HIGH_RISK_REGIONS.items():
            if region in location_lower:
                score = max(score, risk_val)
                evidence.append(f"{location}は自然災害高リスク地域（台風・洪水・地震）")
                break

    if score == 0:
        for region, risk_val in MEDIUM_RISK_REGIONS.items():
            if region in location_lower:
                score = max(score, risk_val)
                evidence.append(f"{location}は中程度の自然災害リスク地域")
                break

    return score, evidence


def _get_coords(location: str):
    """ロケーション名から座標を取得"""
    loc = location.lower().strip()
    if loc in LOCATION_COORDS:
        return LOCATION_COORDS[loc]
    for key, coords in LOCATION_COORDS.items():
        if key in loc or loc in key:
            return coords
    return None
