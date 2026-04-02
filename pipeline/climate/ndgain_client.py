"""ND-GAIN (Notre Dame Global Adaptation Initiative) Index クライアント
気候変動脆弱性・適応能力の評価
https://gain.nd.edu/
データ: vulnerability (0-1, lower=better), readiness (0-1, higher=better)
"""
import requests
import csv
import io
from typing import Optional

# CSV download URLs to try
NDGAIN_CSV_URLS = [
    "https://gain.nd.edu/assets/522870/nd_gain_countryindex.csv",
    "https://raw.githubusercontent.com/NGAGitHub/ND-GAIN/main/gain/gain.csv",
]

HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}

# Country name -> ISO3 mapping (shared across modules)
COUNTRY_TO_ISO3 = {
    "japan": "JPN", "china": "CHN", "united states": "USA", "usa": "USA",
    "south korea": "KOR", "korea": "KOR", "taiwan": "TWN",
    "thailand": "THA", "vietnam": "VNM", "indonesia": "IDN",
    "malaysia": "MYS", "singapore": "SGP", "philippines": "PHL",
    "india": "IND", "germany": "DEU", "australia": "AUS",
    "russia": "RUS", "ukraine": "UKR", "myanmar": "MMR",
    "bangladesh": "BGD", "pakistan": "PAK", "turkey": "TUR",
    "brazil": "BRA", "mexico": "MEX", "nigeria": "NGA",
    "egypt": "EGY", "south africa": "ZAF", "saudi arabia": "SAU",
    "united kingdom": "GBR", "uk": "GBR", "france": "FRA",
    "italy": "ITA", "canada": "CAN", "uae": "ARE",
    "united arab emirates": "ARE", "iran": "IRN", "iraq": "IRQ",
    "somalia": "SOM", "chad": "TCD", "yemen": "YEM",
    "cambodia": "KHM", "laos": "LAO", "nepal": "NPL",
    "sri lanka": "LKA", "mozambique": "MOZ", "ethiopia": "ETH",
    "sudan": "SDN", "south sudan": "SSD", "libya": "LBY",
    "jordan": "JOR", "lebanon": "LBN", "qatar": "QAT",
    "israel": "ISR", "spain": "ESP", "norway": "NOR",
    "sweden": "SWE", "denmark": "DNK", "switzerland": "CHE",
    "north korea": "PRK",
}

# Static fallback data (2023 values, selected countries)
# vulnerability: higher = more vulnerable (0-1 scale)
# readiness: higher = more ready to adapt (0-1 scale)
STATIC_VULNERABILITY: dict[str, float] = {
    "SOM": 0.67, "TCD": 0.64, "YEM": 0.61, "MMR": 0.55,
    "BGD": 0.52, "PAK": 0.50, "IND": 0.47, "IDN": 0.44,
    "VNM": 0.43, "PHL": 0.45, "NGA": 0.48, "ETH": 0.53,
    "SDN": 0.60, "SSD": 0.62, "MOZ": 0.54, "KHM": 0.46,
    "LAO": 0.47, "NPL": 0.49, "LKA": 0.42,
    "CHN": 0.38, "THA": 0.37, "TUR": 0.36, "MEX": 0.35,
    "BRA": 0.33, "ZAF": 0.42, "RUS": 0.31, "EGY": 0.40,
    "IRN": 0.43, "IRQ": 0.50, "LBN": 0.45, "JOR": 0.38,
    "SAU": 0.35, "QAT": 0.30, "ARE": 0.28,
    "KOR": 0.28, "JPN": 0.27, "USA": 0.25, "SGP": 0.24,
    "DEU": 0.22, "AUS": 0.23, "GBR": 0.21, "FRA": 0.22,
    "CAN": 0.20, "NOR": 0.18, "SWE": 0.19, "CHE": 0.19,
    "ITA": 0.24, "ESP": 0.25, "TWN": 0.26, "MYS": 0.34,
    "UKR": 0.40, "LBY": 0.52, "ISR": 0.27, "DNK": 0.18,
    "PRK": 0.58,
}

STATIC_READINESS: dict[str, float] = {
    "SGP": 0.77, "DEU": 0.74, "NOR": 0.76, "SWE": 0.75,
    "DNK": 0.76, "CHE": 0.75, "JPN": 0.70, "USA": 0.68,
    "KOR": 0.67, "AUS": 0.69, "GBR": 0.71, "FRA": 0.68,
    "CAN": 0.70, "ITA": 0.60, "ESP": 0.61, "ISR": 0.65,
    "TWN": 0.63, "ARE": 0.62, "QAT": 0.58, "SAU": 0.52,
    "MYS": 0.50, "CHN": 0.46, "THA": 0.42, "IDN": 0.39,
    "TUR": 0.44, "MEX": 0.40, "BRA": 0.42, "ZAF": 0.38,
    "IND": 0.36, "VNM": 0.38, "PHL": 0.35, "EGY": 0.33,
    "RUS": 0.35, "UKR": 0.30, "LKA": 0.32, "KHM": 0.28,
    "BGD": 0.29, "PAK": 0.26, "NGA": 0.24, "ETH": 0.20,
    "NPL": 0.27, "LAO": 0.26, "MOZ": 0.20, "LBN": 0.28,
    "JOR": 0.40, "IRN": 0.25, "IRQ": 0.20, "LBY": 0.18,
    "SDN": 0.15, "SSD": 0.10, "MMR": 0.22, "YEM": 0.15,
    "SOM": 0.12, "TCD": 0.14, "PRK": 0.10,
}

# Cached live data (populated on first successful download)
_live_data_cache: dict[str, dict[str, float]] = {}


def _resolve_iso3(location: str) -> str:
    """国名/コードをISO3に変換"""
    loc = location.lower().strip()
    if loc in COUNTRY_TO_ISO3:
        return COUNTRY_TO_ISO3[loc]
    # 3文字コードならそのまま
    if len(loc) == 3 and loc.isalpha():
        return loc.upper()
    # 部分一致
    for name, code in COUNTRY_TO_ISO3.items():
        if loc in name or name in loc:
            return code
    return loc.upper()[:3]


def _try_download_csv() -> dict[str, dict[str, float]]:
    """ND-GAIN CSVデータのダウンロードを試行"""
    global _live_data_cache
    if _live_data_cache:
        return _live_data_cache

    for url in NDGAIN_CSV_URLS:
        try:
            resp = requests.get(url, timeout=15, headers=HEADERS)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            data: dict[str, dict[str, float]] = {}

            for row in reader:
                iso3 = row.get("ISO3", row.get("iso3", "")).upper()
                if not iso3:
                    continue
                # Try to get vulnerability and readiness columns
                vuln = row.get("vulnerability", row.get("Vulnerability"))
                read = row.get("readiness", row.get("Readiness"))
                if vuln is not None and read is not None:
                    try:
                        data[iso3] = {
                            "vulnerability": float(vuln),
                            "readiness": float(read),
                        }
                    except (ValueError, TypeError):
                        continue

            if data:
                _live_data_cache = data
                return data
        except Exception:
            continue

    return {}


def _get_ndgain_data(iso3: str) -> Optional[dict[str, float]]:
    """指定国のND-GAINデータを取得 (live -> static fallback)"""
    # Try live data first
    live = _try_download_csv()
    if iso3 in live:
        return live[iso3]

    # Static fallback
    vuln = STATIC_VULNERABILITY.get(iso3)
    read = STATIC_READINESS.get(iso3)
    if vuln is not None and read is not None:
        return {"vulnerability": vuln, "readiness": read}

    return None


def get_climate_vulnerability(location: str) -> dict:
    """気候変動脆弱性スコアを取得（物理的リスクのみ）

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
        Score = vulnerability * 100 (readiness excluded to avoid governance correlation)
        高スコア = 物理的気候脆弱性が高い
    """
    iso3 = _resolve_iso3(location)
    data = _get_ndgain_data(iso3)

    if data is None:
        return {
            "score": 0,
            "evidence": [f"[ND-GAIN] {location} ({iso3}) のデータなし"],
        }

    vulnerability = data["vulnerability"]

    # Score: vulnerability * 100 (physical exposure only, governance excluded)
    score = min(100, max(0, int(vulnerability * 100)))

    evidence = []
    source = "ND-GAIN (live)" if _live_data_cache else "ND-GAIN (static 2023)"
    evidence.append(
        f"[{source}] {location}: 気候脆弱性={vulnerability:.2f} "
        f"(物理的リスクのみ、ガバナンス指標除外)"
    )

    # Risk level interpretation
    if score >= 50:
        evidence.append(
            f"[ND-GAIN] 高い気候変動物理的脆弱性 (スコア: {score}/100)"
        )
    elif score >= 30:
        evidence.append(
            f"[ND-GAIN] 中程度の気候変動物理的脆弱性 (スコア: {score}/100)"
        )
    else:
        evidence.append(
            f"[ND-GAIN] 比較的低い気候変動物理的脆弱性 (スコア: {score}/100)"
        )

    return {"score": score, "evidence": evidence}



# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_locations = [
        "Japan", "China", "Bangladesh", "Somalia", "Germany",
        "USA", "India", "Vietnam", "Singapore", "Yemen",
    ]
    print("=" * 70)
    print("ND-GAIN Climate Vulnerability Test")
    print("=" * 70)
    for loc in test_locations:
        result = get_climate_vulnerability(loc)
        print(f"\n{loc}:")
        print(f"  Score: {result['score']}/100")
        for e in result["evidence"]:
            print(f"  {e}")
    print("\n" + "=" * 70)
