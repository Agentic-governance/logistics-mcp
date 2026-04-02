"""World Bank Open Data - 経済指標
GDP成長率、インフレ率、政治安定性指標等
https://data.worldbank.org/
完全無料・APIキー不要
"""
import requests
from datetime import datetime

WB_API_BASE = "https://api.worldbank.org/v2"

# 主要指標コード
INDICATORS = {
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",         # GDP成長率 (%)
    "inflation": "FP.CPI.TOTL.ZG",               # インフレ率 (%)
    "political_stability": "PV.EST",              # 政治安定性 (-2.5〜+2.5)
    "rule_of_law": "RL.EST",                      # 法の支配 (-2.5〜+2.5)
    "regulatory_quality": "RQ.EST",               # 規制の質 (-2.5〜+2.5)
    "control_of_corruption": "CC.EST",            # 汚職の制御 (-2.5〜+2.5)
    "trade_pct_gdp": "NE.TRD.GNFS.ZS",          # 貿易額/GDP (%)
    "logistics_performance": "LP.LPI.OVRL.XQ",   # 物流パフォーマンス (1-5)
    "ease_of_business": "IC.BUS.DFRN.XQ",        # ビジネスのしやすさ (0-100)
}

# ISO 3166-1 alpha-2 → alpha-3 のよく使う国マッピング
COUNTRY_MAPPING = {
    "japan": "JPN", "jp": "JPN",
    "china": "CHN", "cn": "CHN",
    "united states": "USA", "us": "USA", "usa": "USA",
    "germany": "DEU", "de": "DEU",
    "taiwan": "TWN", "tw": "TWN",
    "south korea": "KOR", "korea": "KOR", "kr": "KOR",
    "india": "IND", "in": "IND",
    "vietnam": "VNM", "vn": "VNM",
    "thailand": "THA", "th": "THA",
    "indonesia": "IDN", "id": "IDN",
    "malaysia": "MYS", "my": "MYS",
    "singapore": "SGP", "sg": "SGP",
    "philippines": "PHL", "ph": "PHL",
    "bangladesh": "BGD", "bd": "BGD",
    "mexico": "MEX", "mx": "MEX",
    "brazil": "BRA", "br": "BRA",
    "russia": "RUS", "ru": "RUS",
    "ukraine": "UKR", "ua": "UKR",
    "turkey": "TUR", "tr": "TUR",
    "united kingdom": "GBR", "uk": "GBR", "gb": "GBR",
    "france": "FRA", "fr": "FRA",
    "italy": "ITA", "it": "ITA",
    "canada": "CAN", "ca": "CAN",
    "australia": "AUS", "au": "AUS",
    "saudi arabia": "SAU", "sa": "SAU",
    "united arab emirates": "ARE", "uae": "ARE",
    "egypt": "EGY", "eg": "EGY",
    "south africa": "ZAF", "za": "ZAF",
    "nigeria": "NGA", "ng": "NGA",
    "myanmar": "MMR", "mm": "MMR",
    "cambodia": "KHM", "kh": "KHM",
}


def _resolve_country_code(location: str) -> str:
    """国名/コードをISO3に変換"""
    loc = location.lower().strip()
    if loc in COUNTRY_MAPPING:
        return COUNTRY_MAPPING[loc]
    # 3文字コードならそのまま
    if len(loc) == 3 and loc.isalpha():
        return loc.upper()
    # 部分一致
    for name, code in COUNTRY_MAPPING.items():
        if loc in name or name in loc:
            return code
    return loc.upper()[:3]


def fetch_indicator(country_code: str, indicator: str, years: int = 5) -> list[dict]:
    """World Bank APIから指標データを取得"""
    url = f"{WB_API_BASE}/country/{country_code}/indicator/{indicator}"
    params = {
        "format": "json",
        "per_page": years,
        "mrv": years,  # most recent values
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if len(data) < 2 or not data[1]:
            return []

        results = []
        for item in data[1]:
            if item.get("value") is not None:
                results.append({
                    "year": item.get("date"),
                    "value": item["value"],
                    "indicator": item.get("indicator", {}).get("id", ""),
                    "indicator_name": item.get("indicator", {}).get("value", ""),
                    "country": item.get("country", {}).get("value", ""),
                })
        return results
    except Exception as e:
        print(f"World Bank API error ({indicator}): {e}")
        return []


def get_economic_profile(location: str) -> dict:
    """国の経済プロファイルを取得"""
    country_code = _resolve_country_code(location)
    profile = {"country_code": country_code}

    for key, indicator_code in INDICATORS.items():
        data = fetch_indicator(country_code, indicator_code, years=3)
        if data:
            latest = data[0]
            profile[key] = {
                "value": latest["value"],
                "year": latest["year"],
                "indicator_name": latest["indicator_name"],
            }

    return profile


def get_economic_risk_for_location(location: str) -> dict:
    """経済リスクスコア算出"""
    country_code = _resolve_country_code(location)
    score = 0
    evidence = []

    # 政治安定性 (-2.5〜+2.5)
    stability_data = fetch_indicator(country_code, INDICATORS["political_stability"], years=1)
    if stability_data:
        val = stability_data[0]["value"]
        # -2.5=最悪 → 100, +2.5=最良 → 0
        stability_score = max(0, min(100, int((2.5 - val) / 5.0 * 100)))
        score += stability_score * 0.3
        evidence.append(f"政治安定性指標: {val:.2f} (世銀 {stability_data[0]['year']})")

    # インフレ率
    inflation_data = fetch_indicator(country_code, INDICATORS["inflation"], years=1)
    if inflation_data:
        val = inflation_data[0]["value"]
        if val > 50:
            inflation_score = 100  # ハイパーインフレ
        elif val > 20:
            inflation_score = 80
        elif val > 10:
            inflation_score = 50
        elif val > 5:
            inflation_score = 25
        else:
            inflation_score = 0
        score += inflation_score * 0.2
        evidence.append(f"インフレ率: {val:.1f}% (世銀 {inflation_data[0]['year']})")

    # 法の支配
    rule_data = fetch_indicator(country_code, INDICATORS["rule_of_law"], years=1)
    if rule_data:
        val = rule_data[0]["value"]
        rule_score = max(0, min(100, int((2.5 - val) / 5.0 * 100)))
        score += rule_score * 0.2
        evidence.append(f"法の支配指標: {val:.2f} (世銀 {rule_data[0]['year']})")

    # 汚職の制御
    corruption_data = fetch_indicator(country_code, INDICATORS["control_of_corruption"], years=1)
    if corruption_data:
        val = corruption_data[0]["value"]
        corruption_score = max(0, min(100, int((2.5 - val) / 5.0 * 100)))
        score += corruption_score * 0.15
        evidence.append(f"汚職制御指標: {val:.2f} (世銀 {corruption_data[0]['year']})")

    # GDP成長率（マイナスはリスク）
    gdp_data = fetch_indicator(country_code, INDICATORS["gdp_growth"], years=1)
    if gdp_data:
        val = gdp_data[0]["value"]
        if val < -5:
            gdp_score = 80
        elif val < -2:
            gdp_score = 50
        elif val < 0:
            gdp_score = 30
        else:
            gdp_score = 0
        score += gdp_score * 0.15
        evidence.append(f"GDP成長率: {val:.1f}% (世銀 {gdp_data[0]['year']})")

    score = min(100, int(score))

    return {
        "score": score,
        "country_code": country_code,
        "evidence": evidence,
    }
