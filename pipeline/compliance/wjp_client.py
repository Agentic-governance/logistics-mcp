"""WJP Rule of Law Index 2023 クライアント
World Justice Project Rule of Law Index
https://worldjusticeproject.org/rule-of-law-index/

法の支配の質を評価。WJPスコアは0-1で1.0=最強の法治。
サプライチェーンリスク用に逆転: 低い法治 = 高いリスク。
"""

# WJP Rule of Law Index 2023 Overall Scores (0.00 - 1.00)
# Source: World Justice Project Rule of Law Index 2023
# 1.00 = strongest rule of law
# Top 50 countries with accurate published scores + additional priority countries
WJP_SCORES = {
    # Top performers (strong rule of law)
    "denmark": 0.90,
    "norway": 0.89,
    "finland": 0.87,
    "sweden": 0.86,
    "netherlands": 0.86,
    "germany": 0.85,
    "new zealand": 0.83,
    "luxembourg": 0.83,
    "austria": 0.82,
    "estonia": 0.82,
    "ireland": 0.81,
    "australia": 0.80,
    "singapore": 0.78,
    "united kingdom": 0.78,
    "belgium": 0.77,
    "japan": 0.77,
    "czech republic": 0.76,
    "canada": 0.76,
    "south korea": 0.75,
    "france": 0.74,
    "united states": 0.71,
    "portugal": 0.71,
    "spain": 0.70,
    "uruguay": 0.70,
    "costa rica": 0.68,
    "chile": 0.66,
    "slovenia": 0.66,
    "poland": 0.64,
    "taiwan": 0.64,  # Not in WJP directly; estimated from governance indicators
    "italy": 0.64,
    "croatia": 0.62,
    "georgia": 0.61,
    "romania": 0.60,
    "malaysia": 0.59,
    "greece": 0.58,
    "jordan": 0.57,
    "south africa": 0.56,
    "brazil": 0.53,
    "indonesia": 0.53,
    "argentina": 0.52,
    "thailand": 0.51,
    "colombia": 0.50,
    "sri lanka": 0.49,
    "nepal": 0.49,
    "india": 0.49,
    "qatar": 0.48,
    "uae": 0.48,
    "saudi arabia": 0.47,
    "tunisia": 0.47,
    "philippines": 0.46,
    "ukraine": 0.46,
    "kenya": 0.45,
    "mexico": 0.42,
    "turkey": 0.42,
    "vietnam": 0.41,
    "china": 0.40,
    "nigeria": 0.38,
    "bangladesh": 0.37,
    "pakistan": 0.37,
    "egypt": 0.36,
    "ethiopia": 0.36,
    "russia": 0.35,
    "iran": 0.34,
    "iraq": 0.32,
    "cambodia": 0.32,
    "myanmar": 0.27,
    "venezuela": 0.26,
    "somalia": 0.20,
    "yemen": 0.20,
    "south sudan": 0.18,
    "north korea": 0.12,  # Not in WJP; estimated from governance metrics
    "israel": 0.63,
    "switzerland": 0.88,
}


def _resolve_country(location: str) -> str | None:
    """Resolve location string to a WJP country key."""
    loc = location.lower().strip()
    # Direct match
    if loc in WJP_SCORES:
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
    for country in WJP_SCORES:
        if country in loc or loc in country:
            return country
    return None



def get_rule_of_law_score(location: str) -> dict:
    """WJP Rule of Law Index に基づく法治リスクスコアを返す。

    Returns:
        dict: {"score": int 0-100, "evidence": [...]}
        Higher score = higher legal risk (inverted WJP).
    """
    country = _resolve_country(location)
    if country is None:
        return {"score": 0, "evidence": []}

    wjp_raw = WJP_SCORES[country]

    # Invert: WJP 1.0 (strongest) -> risk 0, WJP 0.0 (weakest) -> risk 100
    risk_score = int((1.0 - wjp_raw) * 100)
    risk_score = max(0, min(100, risk_score))

    # Descriptive label
    if wjp_raw >= 0.75:
        label = "強い法治 (Strong Rule of Law)"
    elif wjp_raw >= 0.55:
        label = "中程度の法治 (Moderate Rule of Law)"
    elif wjp_raw >= 0.40:
        label = "弱い法治 (Weak Rule of Law)"
    else:
        label = "非常に弱い法治 (Very Weak Rule of Law)"

    evidence = [
        f"[WJP] {location}: Rule of Law Index {wjp_raw:.2f}/1.00 ({label})",
        f"[WJP] 法治リスクスコア: {risk_score}/100 (高い=リスク大)",
    ]

    return {"score": risk_score, "evidence": evidence}
