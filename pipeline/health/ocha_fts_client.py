"""OCHA Financial Tracking Service (FTS) API
人道支援の資金動員規模・充足率を取得する。
https://fts.unocha.org/api/v2/
APIキー不要。
"""
import requests
from datetime import datetime
from typing import Optional

FTS_BASE = "https://fts.unocha.org/api/v2"
HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0", "Accept": "application/json"}

# ISO2 → ISO3 マッピング (FTS API は ISO3 を使用)
_ISO2_TO_ISO3 = {
    "AF": "AFG", "BD": "BGD", "BF": "BFA", "BI": "BDI", "BR": "BRA",
    "CD": "COD", "CF": "CAF", "CH": "CHE", "CM": "CMR", "CN": "CHN",
    "CO": "COL", "DE": "DEU", "DJ": "DJI", "EG": "EGY", "ET": "ETH",
    "FR": "FRA", "GB": "GBR", "GH": "GHA", "GT": "GTM", "HN": "HND",
    "HT": "HTI", "ID": "IDN", "IL": "ISR", "IN": "IND", "IQ": "IRQ",
    "IR": "IRN", "IT": "ITA", "JO": "JOR", "JP": "JPN", "KE": "KEN",
    "KH": "KHM", "KR": "KOR", "LB": "LBN", "LK": "LKA", "LY": "LBY",
    "MA": "MAR", "MG": "MDG", "ML": "MLI", "MM": "MMR", "MX": "MEX",
    "MZ": "MOZ", "NE": "NER", "NG": "NGA", "NL": "NLD", "NO": "NOR",
    "PH": "PHL", "PK": "PAK", "PS": "PSE", "RU": "RUS", "RW": "RWA",
    "SA": "SAU", "SD": "SDN", "SG": "SGP", "SL": "SLE", "SN": "SEN",
    "SO": "SOM", "SS": "SSD", "SV": "SLV", "SY": "SYR", "TD": "TCD",
    "TH": "THA", "TN": "TUN", "TR": "TUR", "TW": "TWN", "TZ": "TZA",
    "UA": "UKR", "UG": "UGA", "US": "USA", "VE": "VEN", "VN": "VNM",
    "YE": "YEM", "ZA": "ZAF", "ZM": "ZMB", "ZW": "ZWE",
    "AE": "ARE", "OM": "OMN", "QA": "QAT", "KW": "KWT", "BH": "BHR",
    "MY": "MYS", "LA": "LAO", "BN": "BRN", "MN": "MNG",
}


def _to_iso3(code: str) -> str:
    """ISO2 → ISO3 変換。ISO3 が渡された場合はそのまま返す。"""
    code = code.upper().strip()
    if len(code) == 3:
        return code
    return _ISO2_TO_ISO3.get(code, code)


def get_active_emergencies(country_iso: str) -> list[dict]:
    """国別のアクティブ緊急事態を取得。

    Args:
        country_iso: ISO2 or ISO3 国コード

    Returns:
        緊急事態リスト
    """
    iso3 = _to_iso3(country_iso)
    year = datetime.utcnow().year
    try:
        resp = requests.get(
            f"{FTS_BASE}/fts/flow/custom-search",
            params={
                "groupby": "plan",
                "filterBy": f"destinationLocationTypes:admin0,destinationCountryISO3:{iso3}",
                "year": year,
            },
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        requirements = data.get("data", {}).get("requirements", {})
        if isinstance(requirements, dict):
            objects = requirements.get("objects", [])
            return [
                {
                    "name": obj.get("name", ""),
                    "id": obj.get("id"),
                    "year": year,
                    "totalFunding": obj.get("totalFunding", 0),
                    "revisedRequirements": obj.get("revisedRequirements", 0),
                }
                for obj in objects
                if isinstance(obj, dict)
            ]
        return []
    except Exception:
        return []


def get_funding_gap(country_iso: str) -> dict:
    """国別の人道支援資金ギャップを算出。

    Args:
        country_iso: ISO2 or ISO3 国コード

    Returns:
        {"requested": float, "funded": float, "gap_ratio": float, "emergencies": int}
    """
    emergencies = get_active_emergencies(country_iso)

    total_requested = 0.0
    total_funded = 0.0
    for e in emergencies:
        req = e.get("revisedRequirements", 0) or 0
        fund = e.get("totalFunding", 0) or 0
        total_requested += req
        total_funded += fund

    gap_ratio = 0.0
    if total_requested > 0:
        gap_ratio = (total_requested - total_funded) / total_requested

    return {
        "requested": total_requested,
        "funded": total_funded,
        "gap_ratio": max(0.0, min(1.0, gap_ratio)),
        "emergencies": len(emergencies),
    }


# 人道危機の静的リスクマッピング (FTS APIフォールバック)
HUMANITARIAN_FUNDING_RISK = {
    "yemen": 90, "syria": 85, "afghanistan": 85, "sudan": 85,
    "south sudan": 85, "somalia": 80, "ethiopia": 75,
    "democratic republic of congo": 80, "drc": 80,
    "myanmar": 75, "haiti": 70, "ukraine": 65,
    "central african republic": 70, "car": 70,
    "burkina faso": 65, "niger": 60, "mali": 65,
    "nigeria": 50, "mozambique": 55, "chad": 60,
    "libya": 50, "iraq": 45, "palestine": 80,
    "lebanon": 50, "pakistan": 40, "bangladesh": 40,
}


def get_humanitarian_indicators(location: str) -> dict:
    """統合人道危機指標を取得。

    OCHA FTS 資金ギャップ + アクティブ緊急事態。

    Args:
        location: 国名 or ISO コード

    Returns:
        {"score": int, "evidence": list[str], "funding_gap": dict}
    """
    evidence: list[str] = []

    # FTS API経由でデータ取得試行
    iso = _resolve_location(location)
    if iso:
        funding = get_funding_gap(iso)
        gap_ratio = funding["gap_ratio"]
        n_emergencies = funding["emergencies"]

        if funding["requested"] > 0 or n_emergencies > 0:
            # 資金ギャップスコア (50%)
            gap_score = int(gap_ratio * 100)

            # アクティブ緊急事態スコア (30%)
            if n_emergencies >= 5:
                emergency_score = 100
            elif n_emergencies >= 3:
                emergency_score = 80
            elif n_emergencies >= 1:
                emergency_score = 40 + n_emergencies * 10
            else:
                emergency_score = 0

            # ReliefWeb レポート数は scoring/dimensions/humanitarian_scorer.py で追加 (20%)
            score = int(gap_score * 0.625 + emergency_score * 0.375)  # 50/(50+30) and 30/(50+30)

            if funding["requested"] > 0:
                evidence.append(
                    f"[OCHA FTS] 資金要請: ${funding['requested']/1e6:.0f}M, "
                    f"調達: ${funding['funded']/1e6:.0f}M, "
                    f"ギャップ: {gap_ratio*100:.0f}%"
                )
            if n_emergencies > 0:
                evidence.append(f"[OCHA FTS] アクティブ緊急事態: {n_emergencies}件")

            return {
                "score": min(100, score),
                "evidence": evidence,
                "funding_gap": funding,
                "source": "ocha_fts",
            }

    # フォールバック: 静的リスクマップ
    location_lower = location.lower().strip()
    for region, risk_score in HUMANITARIAN_FUNDING_RISK.items():
        if region in location_lower or location_lower in region:
            return {
                "score": risk_score,
                "evidence": [f"[静的評価] {location}は人道危機リスク地域 (FTS: {risk_score})"],
                "funding_gap": {"gap_ratio": risk_score / 100},
                "source": "static",
            }

    return {"score": 0, "evidence": [], "funding_gap": {}, "source": "none"}


def _resolve_location(location: str) -> str:
    """国名/コードからISO2コードに解決。"""
    loc = location.upper().strip()
    if len(loc) == 2 and loc in _ISO2_TO_ISO3:
        return loc
    if len(loc) == 3:
        # ISO3 → ISO2 逆引き
        for iso2, iso3 in _ISO2_TO_ISO3.items():
            if iso3 == loc:
                return iso2
        return loc

    # 国名からの解決
    name_map = {
        "japan": "JP", "china": "CN", "korea": "KR", "south korea": "KR",
        "united states": "US", "usa": "US", "germany": "DE", "india": "IN",
        "vietnam": "VN", "thailand": "TH", "indonesia": "ID", "malaysia": "MY",
        "singapore": "SG", "philippines": "PH", "myanmar": "MM", "taiwan": "TW",
        "yemen": "YE", "syria": "SY", "afghanistan": "AF", "sudan": "SD",
        "south sudan": "SS", "somalia": "SO", "ethiopia": "ET", "nigeria": "NG",
        "ukraine": "UA", "russia": "RU", "turkey": "TR", "iraq": "IQ",
        "brazil": "BR", "mexico": "MX", "haiti": "HT", "pakistan": "PK",
        "bangladesh": "BD", "kenya": "KE", "south africa": "ZA", "egypt": "EG",
        "drc": "CD", "democratic republic of congo": "CD", "palestine": "PS",
        "lebanon": "LB", "libya": "LY", "chad": "TD", "mali": "ML",
        "burkina faso": "BF", "niger": "NE", "mozambique": "MZ",
        "central african republic": "CF", "colombia": "CO",
    }
    return name_map.get(location.lower().strip(), "")
