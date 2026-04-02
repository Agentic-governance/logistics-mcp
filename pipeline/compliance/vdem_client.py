"""V-Dem Democracy Index クライアント
Varieties of Democracy (V-Dem) Institute
https://v-dem.net/

Electoral Democracy Index (v2x_polyarchy): 0-1スケール
1.0 = 完全な民主主義 = 低リスク
0.0 = 非民主的 = 高リスク
逆転してリスクスコアとして返す。
"""

# V-Dem Electoral Democracy Index (v2x_polyarchy) 2023
# Source: V-Dem Dataset v14 (2024 release, data through 2023)
# Scale: 0.00 - 1.00 (1.00 = fully democratic)
VDEM_POLYARCHY = {
    # Full Democracies (0.80+)
    "denmark": 0.92,
    "sweden": 0.91,
    "norway": 0.90,
    "switzerland": 0.90,
    "costa rica": 0.89,
    "new zealand": 0.88,
    "finland": 0.88,
    "germany": 0.87,
    "netherlands": 0.87,
    "australia": 0.86,
    "canada": 0.86,
    "uruguay": 0.86,
    "austria": 0.85,
    "ireland": 0.85,
    "portugal": 0.85,
    "united kingdom": 0.84,
    "france": 0.83,
    "japan": 0.82,
    "south korea": 0.82,
    "chile": 0.81,
    "taiwan": 0.81,
    "belgium": 0.80,
    "czech republic": 0.80,
    # Democracies (0.60-0.79)
    "united states": 0.79,
    "italy": 0.78,
    "spain": 0.77,
    "poland": 0.75,
    "argentina": 0.74,
    "brazil": 0.73,
    "south africa": 0.72,
    "colombia": 0.70,
    "israel": 0.68,
    "greece": 0.67,
    "indonesia": 0.65,
    "sri lanka": 0.63,
    "mexico": 0.62,
    "nepal": 0.61,
    "singapore": 0.60,
    # Electoral Autocracies (0.30-0.59)
    "india": 0.57,
    "ukraine": 0.55,
    "malaysia": 0.54,
    "philippines": 0.53,
    "kenya": 0.52,
    "nigeria": 0.50,
    "pakistan": 0.49,
    "turkey": 0.47,
    "thailand": 0.44,
    "qatar": 0.42,
    "iraq": 0.40,
    "bangladesh": 0.38,
    "ethiopia": 0.35,
    "uae": 0.33,
    "saudi arabia": 0.31,
    "jordan": 0.30,
    # Closed Autocracies (<0.30)
    "cambodia": 0.29,
    "egypt": 0.27,
    "russia": 0.25,
    "venezuela": 0.24,
    "vietnam": 0.22,
    "iran": 0.20,
    "myanmar": 0.18,
    "china": 0.15,
    "somalia": 0.13,
    "south sudan": 0.11,
    "yemen": 0.10,
    "north korea": 0.04,
    "eritrea": 0.05,
    "syria": 0.08,
}


def _resolve_country(location: str) -> str | None:
    """Resolve location string to a V-Dem country key."""
    loc = location.lower().strip()
    # Direct match
    if loc in VDEM_POLYARCHY:
        return loc
    # Common aliases (check BEFORE partial match)
    aliases = {
        "usa": "united states", "us": "united states",
        "uk": "united kingdom", "gb": "united kingdom",
        "korea": "south korea", "rok": "south korea",
        "dprk": "north korea",
        "holland": "netherlands",
        "burma": "myanmar",
        "persia": "iran",
    }
    if loc in aliases:
        return aliases[loc]
    # Partial match
    for country in VDEM_POLYARCHY:
        if country in loc or loc in country:
            return country
    return None



def get_democracy_score(location: str) -> dict:
    """V-Dem Electoral Democracy Index に基づく民主主義リスクスコアを返す。

    Returns:
        dict: {"score": int 0-100, "evidence": [...]}
        Higher score = higher risk (inverted: 1.0 = fully democratic = low risk).
    """
    country = _resolve_country(location)
    if country is None:
        return {"score": 0, "evidence": []}

    polyarchy = VDEM_POLYARCHY[country]

    # Invert: 1.0 (fully democratic) -> risk 0, 0.0 -> risk 100
    risk_score = int((1.0 - polyarchy) * 100)
    risk_score = max(0, min(100, risk_score))

    # Classification
    if polyarchy >= 0.80:
        regime = "完全民主主義 (Full Democracy)"
    elif polyarchy >= 0.60:
        regime = "民主主義 (Democracy)"
    elif polyarchy >= 0.30:
        regime = "選挙権威主義 (Electoral Autocracy)"
    else:
        regime = "閉鎖的権威主義 (Closed Autocracy)"

    evidence = [
        f"[V-Dem] {location}: Electoral Democracy Index {polyarchy:.2f}/1.00 ({regime})",
        f"[V-Dem] 民主主義リスクスコア: {risk_score}/100 (高い=リスク大)",
    ]

    return {"score": risk_score, "evidence": evidence}
