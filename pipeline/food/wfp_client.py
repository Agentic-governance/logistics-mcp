"""WFP HungerMap - 食料安全保障モニタリング
世界食糧計画（WFP）のリアルタイム食料安全保障データ
https://hungermap.wfp.org/
APIキー不要
"""
import requests

HUNGERMAP_API = "https://api.hungermapdata.org/v1/foodsecurity/country"


def fetch_food_security(country_iso3: str) -> dict:
    """国の食料安全保障データ取得"""
    try:
        resp = requests.get(f"{HUNGERMAP_API}/{country_iso3.upper()}",
                            timeout=15,
                            headers={"User-Agent": "SupplyChainRiskIntelligence/1.0"})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ISO2 → ISO3 直接マッピング
ISO2_TO_ISO3 = {
    "JP": "JPN", "CN": "CHN", "US": "USA", "KR": "KOR", "TW": "TWN",
    "TH": "THA", "VN": "VNM", "ID": "IDN", "MY": "MYS", "SG": "SGP",
    "PH": "PHL", "IN": "IND", "BD": "BGD", "MM": "MMR", "PK": "PAK",
    "AF": "AFG", "NP": "NPL", "DE": "DEU", "AU": "AUS", "RU": "RUS",
    "UA": "UKR", "TR": "TUR", "BR": "BRA", "MX": "MEX", "NG": "NGA",
    "EG": "EGY", "ZA": "ZAF", "ET": "ETH", "KE": "KEN", "YE": "YEM",
    "SY": "SYR", "IQ": "IRQ", "SD": "SDN", "SS": "SSD", "SO": "SOM",
    "HT": "HTI", "CO": "COL", "VE": "VEN", "KH": "KHM", "LA": "LAO",
    "LK": "LKA", "MG": "MDG", "MZ": "MOZ", "NE": "NER", "TD": "TCD",
    "ML": "MLI", "BF": "BFA", "CF": "CAF", "CD": "COD", "LY": "LBY",
    "LB": "LBN", "PS": "PSE", "HN": "HND", "GT": "GTM", "SV": "SLV",
    "GB": "GBR", "FR": "FRA", "IT": "ITA", "ES": "ESP", "NL": "NLD",
    "SE": "SWE", "CH": "CHE", "AT": "AUT", "PL": "POL", "NO": "NOR",
    "SA": "SAU", "AE": "ARE", "IL": "ISR", "IR": "IRN", "QA": "QAT",
    "KW": "KWT", "OM": "OMN", "BH": "BHR", "JO": "JOR", "MN": "MNG",
    "AR": "ARG", "CL": "CHL", "PE": "PER", "EC": "ECU", "CR": "CRI",
    "CA": "CAN", "BN": "BRN",
}

# ISO3 マッピング (国名 → ISO3)
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
    "cambodia": "KHM", "laos": "LAO", "sri lanka": "LKA",
    "madagascar": "MDG", "mozambique": "MOZ", "niger": "NER",
    "chad": "TCD", "mali": "MLI", "burkina faso": "BFA",
    "central african republic": "CAF", "drc": "COD",
    "democratic republic of congo": "COD", "libya": "LBY",
    "lebanon": "LBN", "palestine": "PSE", "honduras": "HND",
    "guatemala": "GTM", "el salvador": "SLV",
}


def _resolve_iso3(location: str) -> str:
    loc = location.strip()
    # ISO2 → ISO3 直接変換 (最優先)
    if len(loc) == 2 and loc.upper() in ISO2_TO_ISO3:
        return ISO2_TO_ISO3[loc.upper()]
    loc = loc.lower()
    if loc in COUNTRY_ISO3:
        return COUNTRY_ISO3[loc]
    # 完全一致のみ使用 (部分一致は誤マッチの原因)
    if len(loc) == 3 and loc.isalpha():
        return loc.upper()
    # 部分一致は最低4文字以上のクエリに制限
    if len(loc) >= 4:
        for name, code in COUNTRY_ISO3.items():
            if loc in name or name in loc:
                return code
    return ""


def get_food_security_risk(location: str) -> dict:
    """食料安全保障リスク評価"""
    iso3 = _resolve_iso3(location)
    if not iso3:
        return {"score": 0, "evidence": []}

    data = fetch_food_security(iso3)
    if "error" in data or not data:
        return {"score": 0, "evidence": ["WFP食料データ取得不可"]}

    score = 0
    evidence = []

    body = data.get("body", {})
    if not isinstance(body, dict):
        return {"score": 0, "evidence": ["WFP食料データ構造不明"]}

    metrics = body.get("metrics", {})
    if isinstance(metrics, dict):
        # FCS (Food Consumption Score) - prevalence = 食料不足人口の割合
        fcs = metrics.get("fcs", {})
        if isinstance(fcs, dict):
            prevalence = fcs.get("prevalence", 0) or 0
            people = fcs.get("people", 0) or 0
            # prevalence: 0-1 scale (proportion of food insecure population)
            if prevalence > 0.5:
                score = 90
            elif prevalence > 0.3:
                score = 70
            elif prevalence > 0.15:
                score = 50
            elif prevalence > 0.05:
                score = 30
            elif prevalence > 0:
                score = 15
            evidence.append(f"[WFP] 食料不安定人口率: {prevalence*100:.1f}%")
            if people > 0:
                evidence.append(f"[WFP] 食料不安定人口: {people:,.0f}人")

        # rCSI (Reduced Coping Strategy Index) - 対処戦略指数
        rcsi = metrics.get("rcsi", {})
        if isinstance(rcsi, dict):
            rcsi_prevalence = rcsi.get("prevalence", 0) or 0
            rcsi_people = rcsi.get("people", 0) or 0
            if rcsi_prevalence > 0.3:
                score = max(score, 75)
            elif rcsi_prevalence > 0.15:
                score = max(score, 45)
            if rcsi_prevalence > 0:
                evidence.append(f"[WFP] 食料対処戦略使用率: {rcsi_prevalence*100:.1f}% ({rcsi_people:,.0f}人)")

    country_info = body.get("country", {})
    date_str = body.get("date", "")
    if date_str:
        evidence.append(f"[WFP] データ日: {date_str}")

    return {"score": min(100, score), "evidence": evidence}
