"""ITU ICT Development Index クライアント
インフラ成熟度指標
https://www.itu.int/en/ITU-D/Statistics/Pages/IDI/default.aspx
"""
import requests
from typing import Optional

HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}

# Country name -> ISO2 mapping
COUNTRY_TO_ISO2 = {
    "japan": "JP", "china": "CN", "united states": "US", "usa": "US",
    "south korea": "KR", "korea": "KR", "taiwan": "TW",
    "thailand": "TH", "vietnam": "VN", "indonesia": "ID",
    "malaysia": "MY", "singapore": "SG", "philippines": "PH",
    "india": "IN", "germany": "DE", "australia": "AU",
    "russia": "RU", "ukraine": "UA", "myanmar": "MM",
    "bangladesh": "BD", "pakistan": "PK", "turkey": "TR",
    "brazil": "BR", "mexico": "MX", "nigeria": "NG",
    "egypt": "EG", "south africa": "ZA", "saudi arabia": "SA",
    "united kingdom": "GB", "uk": "GB", "france": "FR",
    "italy": "IT", "canada": "CA", "uae": "AE",
    "united arab emirates": "AE", "iran": "IR", "iraq": "IQ",
    "yemen": "YE", "syria": "SY", "cuba": "CU",
    "north korea": "KP", "ethiopia": "ET", "sudan": "SD",
    "cambodia": "KH", "laos": "LA", "nepal": "NP",
    "sri lanka": "LK", "qatar": "QA", "jordan": "JO",
    "lebanon": "LB", "israel": "IL", "spain": "ES",
    "norway": "NO", "sweden": "SE", "denmark": "DK",
    "switzerland": "CH", "poland": "PL",
    "somalia": "SO", "chad": "TD", "south sudan": "SS",
    "mozambique": "MZ", "madagascar": "MG",
    "new zealand": "NZ", "iceland": "IS",
}

# Static data: ICT Development Index (IDI score 0-100, higher = more developed)
# Based on ITU ICT Development Index and World Bank Digital Development indicators
# Components: ICT access, ICT use, ICT skills
STATIC_IDI: dict[str, float] = {
    # Tier 1: Most developed (85+)
    "KR": 95, "JP": 93, "SG": 92, "DK": 91, "CH": 90,
    "IS": 94, "NO": 90, "SE": 89, "NL": 89,
    # Tier 2: Highly developed (80-90)
    "DE": 88, "US": 87, "GB": 86, "AU": 85, "FR": 84,
    "CA": 83, "NZ": 84, "FI": 89, "IL": 82,
    "TW": 86, "IT": 80, "ES": 81, "PL": 78,
    # Tier 3: Above average (60-80)
    "AE": 78, "QA": 75, "SA": 72, "RU": 70,
    "CN": 70, "MY": 68, "CL": 66, "AR": 65,
    "TR": 56, "BR": 58, "MX": 55,
    # Tier 4: Developing (40-60)
    "TH": 62, "JO": 60, "LB": 55, "UA": 58,
    "VN": 52, "LK": 50, "PH": 40, "EG": 45,
    "ID": 48, "IQ": 42, "IR": 50, "CU": 45,
    "KH": 38, "LA": 35,
    # Tier 5: Least developed (<40)
    "IN": 42, "BD": 30, "MM": 25, "PK": 22,
    "NP": 28, "NG": 32, "GH": 35, "KE": 33,
    "ZA": 55, "ET": 18, "SD": 20, "YE": 12,
    "SY": 20, "SO": 8, "TD": 10, "SS": 7,
    "MZ": 15, "MG": 12, "KP": 5,
}


def _resolve_iso2(location: str) -> str:
    """国名/コードをISO2に変換"""
    loc = location.lower().strip()
    if loc in COUNTRY_TO_ISO2:
        return COUNTRY_TO_ISO2[loc]
    if len(loc) == 2 and loc.isalpha():
        return loc.upper()
    for name, code in COUNTRY_TO_ISO2.items():
        if loc in name or name in loc:
            return code
    return ""


def _try_itu_api(iso2: str) -> Optional[float]:
    """ITUデータポータルからICTデータ取得を試行"""
    try:
        # ITU datahub API
        url = "https://datahub.itu.int/data/API/indicator/11.1"
        params = {"countries": iso2}
        resp = requests.get(url, params=params, timeout=10, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                # Get latest value
                latest = max(data, key=lambda x: x.get("year", 0))
                val = latest.get("value")
                if val is not None:
                    return float(val)
    except Exception:
        pass

    # Try World Bank ICT indicator as proxy
    try:
        url = f"https://api.worldbank.org/v2/country/{iso2}/indicator/IT.NET.USER.ZS"
        params = {"format": "json", "mrv": 1}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) >= 2 and data[1]:
                val = data[1][0].get("value")
                if val is not None:
                    # Internet user % as proxy for ICT development (not exact but correlated)
                    return float(val)
    except Exception:
        pass

    return None


def _get_idi_score(iso2: str) -> Optional[float]:
    """IDIスコアを取得 (API -> static fallback)"""
    # Try API
    api_val = _try_itu_api(iso2)
    if api_val is not None:
        # Normalize to 0-100 if needed
        if api_val <= 10:
            return api_val * 10  # Old IDI scale was 0-10
        return min(100, api_val)

    # Static fallback
    return STATIC_IDI.get(iso2)


def get_ict_maturity(location: str) -> dict:
    """ICTインフラ成熟度スコアを取得

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
        Score = 100 - idi_score (low maturity = high risk)
    """
    iso2 = _resolve_iso2(location)

    if not iso2:
        return {
            "score": 50,
            "evidence": [
                f"[ITU IDI] {location} の国コードを解決できません。"
                "デフォルトスコア適用"
            ],
        }

    idi = _get_idi_score(iso2)

    if idi is None:
        return {
            "score": 50,
            "evidence": [
                f"[ITU IDI] {location} ({iso2}) のデータなし。"
                "デフォルトスコア適用"
            ],
        }

    # Score = 100 - IDI (invert: low development = high risk)
    score = min(100, max(0, int(100 - idi)))

    evidence: list[str] = []
    evidence.append(
        f"[ITU IDI] {location} ({iso2}): ICT発展度={idi:.0f}/100"
    )

    # Maturity classification
    if idi >= 80:
        maturity = "非常に高い"
        evidence.append(
            f"[ITU IDI] ICTインフラが高度に整備。サイバーリスクへの基盤は堅固"
        )
    elif idi >= 60:
        maturity = "高い"
        evidence.append(
            f"[ITU IDI] ICTインフラは概ね整備されている"
        )
    elif idi >= 40:
        maturity = "中程度"
        evidence.append(
            f"[ITU IDI] ICTインフラに改善余地あり。"
            "デジタルサプライチェーンの信頼性に注意"
        )
    elif idi >= 20:
        maturity = "低い"
        evidence.append(
            f"[ITU IDI] ICTインフラが未整備。"
            "デジタル通信やシステム連携に重大なリスク"
        )
    else:
        maturity = "非常に低い"
        evidence.append(
            f"[ITU IDI] ICTインフラが極めて脆弱。"
            "基本的な通信すら不安定な可能性"
        )

    evidence.append(f"[ITU IDI] ICT成熟度レベル: {maturity}")

    return {"score": score, "evidence": evidence}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_locations = [
        "South Korea", "Japan", "Germany", "USA", "China",
        "India", "Vietnam", "Bangladesh", "Myanmar", "Yemen",
    ]
    print("=" * 70)
    print("ITU ICT Development Index Test")
    print("=" * 70)
    for loc in test_locations:
        result = get_ict_maturity(loc)
        print(f"\n{loc}:")
        print(f"  Score (risk): {result['score']}/100")
        for e in result["evidence"]:
            print(f"  {e}")
    print("\n" + "=" * 70)
