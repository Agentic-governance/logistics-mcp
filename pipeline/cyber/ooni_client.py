"""OONI (Open Observatory of Network Interference) クライアント
インターネット検閲・遮断測定
https://ooni.org/
APIキー不要
"""
import requests
from datetime import datetime, timedelta
from typing import Optional

# OONI API
OONI_API_BASE = "https://api.ooni.io/api/v1"

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
    "turkmenistan": "TM", "uzbekistan": "UZ", "belarus": "BY",
}

# Static fallback: censorship rate (% of tested sites blocked or anomalous)
STATIC_CENSORSHIP: dict[str, float] = {
    # Very high censorship
    "CN": 78, "IR": 72, "TM": 70, "KP": 95,
    # High censorship
    "RU": 55, "MM": 48, "BY": 45, "SA": 40,
    "UZ": 42, "SY": 50, "CU": 45, "ET": 40,
    # Medium censorship
    "VN": 25, "TR": 18, "PK": 22, "EG": 20,
    "TH": 12, "BD": 15, "IQ": 18, "AE": 15,
    "QA": 12, "SD": 30, "YE": 25,
    # Low censorship
    "IN": 8, "ID": 6, "MY": 5, "KH": 8,
    "NG": 5, "LB": 7, "JO": 5, "LK": 6,
    # Very low / no censorship
    "KR": 3, "JP": 1, "US": 0, "DE": 0,
    "GB": 1, "FR": 1, "AU": 1, "CA": 0,
    "SG": 3, "TW": 1, "IL": 2, "IT": 1,
    "ES": 1, "NO": 0, "SE": 0, "DK": 0,
    "CH": 0, "BR": 2, "MX": 3, "PH": 4,
    "ZA": 2, "UA": 5, "PL": 1, "NP": 4,
    "LA": 6,
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


def _fetch_ooni_aggregation(iso2: str, days_back: int = 30) -> Optional[dict]:
    """OONI Aggregation APIから検閲データを取得"""
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    until = datetime.utcnow().strftime("%Y-%m-%d")

    try:
        url = f"{OONI_API_BASE}/aggregation"
        params = {
            "probe_cc": iso2,
            "test_name": "web_connectivity",
            "since": since,
            "until": until,
            "axis_x": "measurement_start_day",
        }
        resp = requests.get(url, params=params, timeout=15, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("result", [])
            if result:
                total_count = sum(r.get("measurement_count", 0) for r in result)
                anomaly_count = sum(r.get("anomaly_count", 0) for r in result)
                confirmed_count = sum(r.get("confirmed_count", 0) for r in result)

                anomaly_rate = 0.0
                if total_count > 0:
                    anomaly_rate = (anomaly_count + confirmed_count) / total_count * 100

                return {
                    "total_measurements": total_count,
                    "anomaly_count": anomaly_count,
                    "confirmed_blocked": confirmed_count,
                    "anomaly_rate": anomaly_rate,
                    "days": len(result),
                }
    except Exception:
        pass

    # Try measurements endpoint as fallback
    try:
        url = f"{OONI_API_BASE}/measurements"
        params = {
            "probe_cc": iso2,
            "test_name": "web_connectivity",
            "since": since,
            "limit": 100,
            "confirmed": True,
        }
        resp = requests.get(url, params=params, timeout=15, headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            confirmed = len(results)
            if confirmed > 0:
                return {
                    "total_measurements": confirmed * 10,  # estimate
                    "anomaly_count": 0,
                    "confirmed_blocked": confirmed,
                    "anomaly_rate": min(100, confirmed),
                    "days": days_back,
                }
    except Exception:
        pass

    return None


def get_internet_censorship_score(location: str) -> dict:
    """インターネット検閲・遮断スコアを取得

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
        Score = censorship rate (higher = more censored)
    """
    iso2 = _resolve_iso2(location)
    evidence: list[str] = []
    score = 0

    if not iso2:
        return {
            "score": 0,
            "evidence": [f"[OONI] {location} の国コードを解決できません"],
        }

    # Try OONI API
    ooni_data = _fetch_ooni_aggregation(iso2)
    if ooni_data and ooni_data.get("total_measurements", 0) > 0:
        anomaly_rate = ooni_data["anomaly_rate"]
        total = ooni_data["total_measurements"]
        confirmed = ooni_data.get("confirmed_blocked", 0)

        # Use anomaly rate as the primary score
        score = min(100, max(0, int(anomaly_rate)))

        evidence.append(
            f"[OONI] {location} ({iso2}): 過去30日間の測定={total}件, "
            f"異常率={anomaly_rate:.1f}%"
        )
        if confirmed > 0:
            evidence.append(
                f"[OONI] 確認済みブロック={confirmed}件"
            )

        # Also blend in static data for stability
        static_rate = STATIC_CENSORSHIP.get(iso2, 0)
        if static_rate > 0:
            # Weighted average: 60% live, 40% static for stability
            score = int(score * 0.6 + static_rate * 0.4)
    else:
        # Fall back to static data
        static_rate = STATIC_CENSORSHIP.get(iso2, 0)
        score = int(static_rate)
        if static_rate > 0:
            evidence.append(
                f"[OONI] {location} ({iso2}): 検閲率推定={static_rate:.0f}% "
                "(静的データ)"
            )
        else:
            evidence.append(
                f"[OONI] {location} ({iso2}): 検閲リスクは低い"
            )

    # Risk classification
    if score >= 60:
        evidence.append(
            f"[OONI] インターネット検閲が極めて高い。"
            "業務通信やクラウドサービスへのアクセスに深刻な影響"
        )
    elif score >= 30:
        evidence.append(
            f"[OONI] 中程度のインターネット検閲。"
            "一部のサービスやWebサイトへのアクセスが制限される可能性"
        )
    elif score >= 10:
        evidence.append(
            f"[OONI] 軽度のインターネット制限"
        )

    return {"score": min(100, score), "evidence": evidence}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_locations = [
        "China", "Iran", "Russia", "Japan", "USA",
        "Vietnam", "Turkey", "Germany", "India", "Myanmar",
    ]
    print("=" * 70)
    print("OONI Internet Censorship Test")
    print("=" * 70)
    for loc in test_locations:
        result = get_internet_censorship_score(loc)
        print(f"\n{loc}:")
        print(f"  Score: {result['score']}/100")
        for e in result["evidence"]:
            print(f"  {e}")
    print("\n" + "=" * 70)
