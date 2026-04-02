"""Basel AML Index クライアント
Basel Institute on Governance - Anti-Money Laundering Index
https://index.baselgovernance.org/

マネーロンダリング・テロ資金供与リスク指標。
スケール: 0-10 (10 = 最もリスクが高い)。
0-100 スケールに変換して返す。
"""
import requests

BASEL_API_URL = "https://index.baselgovernance.org/api/v1/results"

# Basel AML Index 2023 (静的フォールバック)
# Score: 0-10 scale, higher = riskier
# Source: Basel Institute on Governance, Basel AML Index 2023
BASEL_AML_SCORES = {
    # Very High Risk (7.0+)
    "myanmar": 8.07,
    "haiti": 7.85,
    "democratic republic of congo": 7.71,
    "mozambique": 7.63,
    "tanzania": 7.55,
    "mali": 7.44,
    "nigeria": 7.30,
    "south sudan": 7.27,
    "yemen": 7.22,
    "cambodia": 7.18,
    "madagascar": 7.12,
    "laos": 7.05,
    "senegal": 7.01,
    # High Risk (6.0-6.99)
    "kenya": 6.92,
    "bangladesh": 6.85,
    "vietnam": 6.78,
    "pakistan": 6.73,
    "iran": 6.65,
    "north korea": 6.60,  # Estimated; not in Basel directly
    "ethiopia": 6.55,
    "venezuela": 6.53,
    "nepal": 6.48,
    "uganda": 6.45,
    "somalia": 6.40,  # Estimated
    "paraguay": 6.35,
    "panama": 6.28,
    "sierra leone": 6.22,
    "honduras": 6.18,
    "guatemala": 6.12,
    "bolivia": 6.08,
    "nicaragua": 6.05,
    # Medium-High Risk (5.0-5.99)
    "philippines": 5.95,
    "iraq": 5.88,
    "egypt": 5.82,
    "thailand": 5.75,
    "colombia": 5.68,
    "mexico": 5.62,
    "turkey": 5.55,
    "china": 5.48,
    "indonesia": 5.42,
    "india": 5.35,
    "south africa": 5.28,
    "brazil": 5.22,
    "sri lanka": 5.15,
    "russia": 5.10,
    "argentina": 5.05,
    # Medium Risk (4.0-4.99)
    "ukraine": 4.95,
    "malaysia": 4.82,
    "qatar": 4.75,
    "saudi arabia": 4.68,
    "uae": 4.55,
    "singapore": 4.42,
    "taiwan": 4.35,  # Estimated
    "south korea": 4.28,
    "japan": 4.22,
    "chile": 4.15,
    "poland": 4.10,
    "israel": 4.05,
    "italy": 4.02,
    # Low-Medium Risk (3.0-3.99)
    "united states": 3.95,
    "france": 3.88,
    "spain": 3.82,
    "united kingdom": 3.75,
    "canada": 3.68,
    "germany": 3.55,
    "australia": 3.48,
    "netherlands": 3.42,
    "switzerland": 3.35,
    "ireland": 3.28,
    "belgium": 3.22,
    "austria": 3.15,
    # Low Risk (<3.0)
    "sweden": 2.88,
    "norway": 2.75,
    "denmark": 2.68,
    "finland": 2.55,
    "new zealand": 2.48,
    "estonia": 2.42,
    "slovenia": 2.35,
    "czech republic": 2.28,
    "luxembourg": 2.22,
}


def _resolve_country(location: str) -> str | None:
    """Resolve location string to a Basel AML country key."""
    loc = location.lower().strip()
    # Direct match
    if loc in BASEL_AML_SCORES:
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
        "drc": "democratic republic of congo",
    }
    if loc in aliases:
        return aliases[loc]
    # Partial match
    for country in BASEL_AML_SCORES:
        if country in loc or loc in country:
            return country
    return None



def _try_api() -> dict | None:
    """Try to fetch live data from Basel AML Index API."""
    try:
        resp = requests.get(BASEL_API_URL, timeout=10, headers={
            "User-Agent": "SCRI-Platform/0.6",
            "Accept": "application/json",
        })
        resp.raise_for_status()
        data = resp.json()
        # Parse API response into {country_lower: score} format
        results = {}
        if isinstance(data, list):
            for item in data:
                name = (item.get("country") or item.get("name") or "").lower()
                score = item.get("score") or item.get("overall") or item.get("risk_score")
                if name and score is not None:
                    results[name] = float(score)
        return results if results else None
    except Exception:
        return None


def get_aml_score(location: str) -> dict:
    """Basel AML Index に基づくマネーロンダリングリスクスコアを返す。

    Returns:
        dict: {"score": int 0-100, "evidence": [...]}
        Higher score = higher AML risk.
    """
    country = _resolve_country(location)
    if country is None:
        return {"score": 0, "evidence": []}

    # Try live API first
    source = "static"
    api_data = _try_api()
    if api_data and country in api_data:
        raw_score = api_data[country]
        source = "live"
    elif country in BASEL_AML_SCORES:
        raw_score = BASEL_AML_SCORES[country]
    else:
        return {"score": 0, "evidence": []}

    # Convert 0-10 scale to 0-100
    risk_score = int(raw_score * 10)
    risk_score = max(0, min(100, risk_score))

    # Risk tier labels
    if raw_score >= 7.0:
        tier = "非常に高リスク (Very High Risk)"
    elif raw_score >= 6.0:
        tier = "高リスク (High Risk)"
    elif raw_score >= 5.0:
        tier = "中-高リスク (Medium-High Risk)"
    elif raw_score >= 4.0:
        tier = "中リスク (Medium Risk)"
    elif raw_score >= 3.0:
        tier = "中-低リスク (Medium-Low Risk)"
    else:
        tier = "低リスク (Low Risk)"

    data_label = "ライブAPI" if source == "live" else "静的データ 2023"
    evidence = [
        f"[Basel AML] {location}: AMLスコア {raw_score:.2f}/10.00 ({tier})",
        f"[Basel AML] リスクスコア: {risk_score}/100 (データソース: {data_label})",
    ]

    return {"score": risk_score, "evidence": evidence}
