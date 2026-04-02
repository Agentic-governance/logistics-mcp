"""INFORM Risk Index - ライブAPI
EU JRC (Joint Research Centre) INFORM災害リスク指標
https://drmkc.jrc.ec.europa.eu/inform-index/
APIキー不要
"""
import requests

INFORM_API = "https://drmkc.jrc.ec.europa.eu/inform-index/API/InformAPI"
WORKFLOW_ID = 503  # INFORM Risk 2025

# ISO3マッピング
COUNTRY_ISO3 = {
    "japan": "JPN", "china": "CHN", "united states": "USA", "usa": "USA",
    "south korea": "KOR", "korea": "KOR", "taiwan": "TWN",
    "thailand": "THA", "vietnam": "VNM", "indonesia": "IDN",
    "malaysia": "MYS", "singapore": "SGP", "philippines": "PHL",
    "india": "IND", "bangladesh": "BGD", "myanmar": "MMR",
    "pakistan": "PAK", "afghanistan": "AFG", "nepal": "NPL",
    "germany": "DEU", "australia": "AUS", "russia": "RUS",
    "ukraine": "UKR", "turkey": "TUR", "brazil": "BRA",
    "mexico": "MEX", "nigeria": "NGA", "egypt": "EGY",
    "south africa": "ZAF", "ethiopia": "ETH", "kenya": "KEN",
    "yemen": "YEM", "syria": "SYR", "iraq": "IRQ",
    "sudan": "SDN", "south sudan": "SSD", "somalia": "SOM",
    "haiti": "HTI", "colombia": "COL", "venezuela": "VEN",
    "cambodia": "KHM", "iran": "IRN", "north korea": "PRK",
    "united kingdom": "GBR", "france": "FRA", "italy": "ITA",
    "canada": "CAN", "saudi arabia": "SAU", "uae": "ARE",
    "sri lanka": "LKA", "myanmar": "MMR", "laos": "LAO",
    "libya": "LBY", "lebanon": "LBN", "jordan": "JOR",
    "mozambique": "MOZ", "madagascar": "MDG", "niger": "NER",
    "chad": "TCD", "mali": "MLI", "burkina faso": "BFA",
    "central african republic": "CAF",
}

# 主要指標ID
KEY_INDICATORS = {
    "INFORM": "INFORM Risk (overall)",
    "HA": "Hazard & Exposure",
    "VU": "Vulnerability",
    "CC": "Lack of Coping Capacity",
    "HA.HUM": "Human Hazard",
    "HA.NAT": "Natural Hazard",
}


def _resolve_iso3(location: str) -> str:
    loc = location.lower().strip()
    if loc in COUNTRY_ISO3:
        return COUNTRY_ISO3[loc]
    for name, code in COUNTRY_ISO3.items():
        if loc in name or name in loc:
            return code
    if len(loc) == 3 and loc.isalpha():
        return loc.upper()
    return ""


def fetch_inform_scores(iso3: str) -> dict:
    """INFORMリスクスコアをAPIから取得"""
    url = f"{INFORM_API}/countries/Scores/"
    params = {"WorkflowId": WORKFLOW_ID}

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # ISO3でフィルタ
        country_data = [d for d in data if d.get("Iso3") == iso3]
        if not country_data:
            return {}

        scores = {}
        for d in country_data:
            ind_id = d.get("IndicatorId", "")
            if ind_id in KEY_INDICATORS:
                scores[ind_id] = {
                    "name": KEY_INDICATORS[ind_id],
                    "score": d.get("IndicatorScore"),
                    "year": d.get("ValidityYear"),
                }

        return scores
    except Exception:
        return {}


def get_inform_risk_live(location: str) -> dict:
    """INFORMライブAPI経由のリスク評価"""
    iso3 = _resolve_iso3(location)
    if not iso3:
        return {"score": 0, "evidence": []}

    scores = fetch_inform_scores(iso3)
    if not scores:
        return {"score": 0, "evidence": ["INFORMデータ取得不可"]}

    overall = scores.get("INFORM", {}).get("score", 0) or 0
    hazard = scores.get("HA", {}).get("score", 0) or 0
    vulnerability = scores.get("VU", {}).get("score", 0) or 0
    coping = scores.get("CC", {}).get("score", 0) or 0

    # 0-10スケールを0-100に変換
    risk_score = min(100, int(overall * 10))

    evidence = [
        f"[INFORM] 総合リスク: {overall:.1f}/10",
        f"[INFORM] 災害曝露: {hazard:.1f}/10, 脆弱性: {vulnerability:.1f}/10, 対処能力不足: {coping:.1f}/10",
    ]

    return {"score": risk_score, "evidence": evidence}
