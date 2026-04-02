"""AfDB African Development Bank オープンデータ クライアント
African Development Bank - アフリカ主要国の経済指標データ
APIキー不要

API: https://dataportal.opendataforafrica.org/api/1.0/
Focus: Nigeria, South Africa, Ethiopia, Kenya, Egypt
"""
import requests
import time
from datetime import datetime
from typing import Optional

AFDB_API_BASE = "https://dataportal.opendataforafrica.org/api/1.0"
AFDB_DATA_PORTAL = "https://dataportal.opendataforafrica.org"

# アフリカ主要国の経済指標 (2024年実績/推定ベース)
STATIC_AFRICA_DATA = {
    "NGA": {
        "country_name": "Nigeria",
        "gdp_usd_bn": 362.8,
        "gdp_growth_pct": 3.3,
        "population_mn": 223.8,
        "gdp_per_capita_usd": 1_621,
        "exports_usd_bn": 55.2,
        "imports_usd_bn": 52.8,
        "inflation_pct": 28.9,
        "unemployment_pct": 33.3,
        "fdi_inflow_usd_bn": 3.1,
        "oil_production_mbpd": 1.42,
        "currency": "NGN",
        "exchange_rate_usd": 1550.0,
        "key_exports": ["Crude Oil", "LNG", "Cocoa", "Rubber"],
        "supply_chain_notes": [
            "Africa's largest economy",
            "Major oil & gas producer",
            "Growing tech hub (Lagos)",
            "Infrastructure challenges",
            "Currency volatility (Naira)",
        ],
    },
    "ZAF": {
        "country_name": "South Africa",
        "gdp_usd_bn": 373.2,
        "gdp_growth_pct": 0.6,
        "population_mn": 60.4,
        "gdp_per_capita_usd": 6_179,
        "exports_usd_bn": 113.5,
        "imports_usd_bn": 108.2,
        "inflation_pct": 4.5,
        "unemployment_pct": 32.1,
        "fdi_inflow_usd_bn": 4.2,
        "currency": "ZAR",
        "exchange_rate_usd": 18.5,
        "key_exports": ["Platinum Group Metals", "Gold", "Iron Ore", "Coal", "Automobiles"],
        "supply_chain_notes": [
            "Most industrialized African economy",
            "Critical mineral supplier (PGMs, manganese)",
            "Severe load-shedding (electricity crisis)",
            "Ports: Durban (largest in Africa)",
            "High unemployment constrains domestic market",
        ],
    },
    "ETH": {
        "country_name": "Ethiopia",
        "gdp_usd_bn": 156.1,
        "gdp_growth_pct": 7.2,
        "population_mn": 126.5,
        "gdp_per_capita_usd": 1_234,
        "exports_usd_bn": 4.1,
        "imports_usd_bn": 18.2,
        "inflation_pct": 23.5,
        "unemployment_pct": 3.5,
        "fdi_inflow_usd_bn": 3.8,
        "currency": "ETB",
        "exchange_rate_usd": 128.0,
        "key_exports": ["Coffee", "Cut Flowers", "Textiles", "Leather", "Gold"],
        "supply_chain_notes": [
            "Fastest growing African economy",
            "Hawassa Industrial Park (textile manufacturing)",
            "Landlocked (dependent on Djibouti port)",
            "Large young workforce",
            "Political instability concerns",
        ],
    },
    "KEN": {
        "country_name": "Kenya",
        "gdp_usd_bn": 113.4,
        "gdp_growth_pct": 5.0,
        "population_mn": 55.1,
        "gdp_per_capita_usd": 2_058,
        "exports_usd_bn": 8.5,
        "imports_usd_bn": 21.8,
        "inflation_pct": 6.3,
        "unemployment_pct": 5.7,
        "fdi_inflow_usd_bn": 1.2,
        "currency": "KES",
        "exchange_rate_usd": 155.0,
        "key_exports": ["Tea", "Cut Flowers", "Coffee", "Titanium Ore", "Textiles"],
        "supply_chain_notes": [
            "East Africa's largest economy",
            "Tech hub (Nairobi 'Silicon Savanna')",
            "Key logistics hub: Mombasa port",
            "Geothermal energy leader",
            "Gateway to East African market",
        ],
    },
    "EGY": {
        "country_name": "Egypt",
        "gdp_usd_bn": 347.6,
        "gdp_growth_pct": 3.8,
        "population_mn": 105.2,
        "gdp_per_capita_usd": 3_304,
        "exports_usd_bn": 42.8,
        "imports_usd_bn": 78.5,
        "inflation_pct": 33.7,
        "unemployment_pct": 6.9,
        "fdi_inflow_usd_bn": 9.8,
        "suez_canal_revenue_usd_bn": 7.2,
        "currency": "EGP",
        "exchange_rate_usd": 48.5,
        "key_exports": ["Petroleum", "LNG", "Textiles", "Chemicals", "Agricultural Products"],
        "supply_chain_notes": [
            "Suez Canal: 12-15% of global trade",
            "Large domestic market (105M+)",
            "Growing manufacturing sector",
            "Currency devaluation challenges",
            "Energy exporter (gas, petroleum)",
        ],
    },
    "MAR": {
        "country_name": "Morocco",
        "gdp_usd_bn": 141.5,
        "gdp_growth_pct": 3.2,
        "population_mn": 37.5,
        "gdp_per_capita_usd": 3_773,
        "exports_usd_bn": 50.2,
        "imports_usd_bn": 65.8,
        "inflation_pct": 1.3,
        "unemployment_pct": 11.8,
        "fdi_inflow_usd_bn": 2.5,
        "currency": "MAD",
        "exchange_rate_usd": 10.0,
        "key_exports": ["Automobiles", "Phosphates", "Textiles", "Electronics", "Agriculture"],
        "supply_chain_notes": [
            "Emerging automotive manufacturing hub",
            "World's largest phosphate reserves",
            "Proximity to EU markets",
            "Tangier Med port (major transshipment hub)",
            "Growing aerospace sector",
        ],
    },
    "GHA": {
        "country_name": "Ghana",
        "gdp_usd_bn": 75.8,
        "gdp_growth_pct": 2.8,
        "population_mn": 33.5,
        "gdp_per_capita_usd": 2_263,
        "exports_usd_bn": 18.5,
        "imports_usd_bn": 15.2,
        "inflation_pct": 23.2,
        "unemployment_pct": 14.7,
        "fdi_inflow_usd_bn": 1.5,
        "currency": "GHS",
        "exchange_rate_usd": 15.2,
        "key_exports": ["Gold", "Cocoa", "Oil", "Manganese"],
        "supply_chain_notes": [
            "West Africa's 2nd largest economy",
            "Major gold producer",
            "Stable democracy (governance advantage)",
            "Oil production since 2010",
            "Hosting AfCFTA Secretariat",
        ],
    },
}

# アフリカ大陸全体のサマリー
AFRICA_AGGREGATE = {
    "total_gdp_usd_tn": {
        "value": 3.1,
        "unit": "trillion_usd",
        "period": "2024",
        "description": "Africa Total GDP",
    },
    "total_population_bn": {
        "value": 1.46,
        "unit": "billion",
        "period": "2024",
        "description": "Africa Total Population",
    },
    "avg_gdp_growth_pct": {
        "value": 3.7,
        "unit": "percent",
        "period": "2024",
        "description": "Africa Average GDP Growth",
    },
    "total_fdi_inflow_usd_bn": {
        "value": 48.5,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Africa Total FDI Inflow",
    },
    "median_inflation_pct": {
        "value": 7.1,
        "unit": "percent",
        "period": "2024",
        "description": "Africa Median Inflation Rate",
    },
    "afcfta_members": {
        "value": 54,
        "unit": "countries",
        "period": "2024",
        "description": "AfCFTA (African Continental Free Trade Area) Members",
    },
}


def test_connectivity() -> dict:
    """AfDBデータポータルへの疎通テストを実施

    Returns:
        dict: 接続結果
    """
    endpoints = [
        ("AfDB Data Portal", f"{AFDB_DATA_PORTAL}/"),
        ("AfDB API", f"{AFDB_API_BASE}/data"),
    ]

    results: dict = {}
    for name, url in endpoints:
        start = time.time()
        try:
            resp = requests.get(url, timeout=15, allow_redirects=True)
            latency = (time.time() - start) * 1000
            results[name] = {
                "reachable": resp.status_code < 500,
                "status_code": resp.status_code,
                "latency_ms": round(latency, 1),
                "error": None,
            }
        except requests.exceptions.RequestException as e:
            latency = (time.time() - start) * 1000
            results[name] = {
                "reachable": False,
                "status_code": None,
                "latency_ms": round(latency, 1),
                "error": str(e),
            }

    return results


def fetch_afdb_data(
    dataset: str = "",
    country: str = "",
) -> dict:
    """AfDB APIからデータ取得を試行

    Args:
        dataset: データセット名
        country: 国コード

    Returns:
        dict: APIレスポンスまたはエラー
    """
    now = datetime.utcnow().isoformat()
    url = f"{AFDB_API_BASE}/data"
    params: dict = {}
    if dataset:
        params["dataset"] = dataset
    if country:
        params["country"] = country

    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "json" in content_type:
            data = resp.json()
            return {
                "data": data,
                "source": "AfDB Open Data (live API)",
                "timestamp": now,
                "error": None,
            }
        else:
            return {
                "error": "AfDB API returned non-JSON response",
                "source": "AfDB",
                "timestamp": now,
            }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"AfDB API request failed: {str(e)}",
            "source": "AfDB",
            "timestamp": now,
        }
    except ValueError as e:
        return {
            "error": f"AfDB response parse error: {str(e)}",
            "source": "AfDB",
            "timestamp": now,
        }


def get_africa_overview() -> dict:
    """アフリカ大陸全体の経済概況を取得

    Returns:
        dict: アフリカ全体サマリーと主要国データ
    """
    now = datetime.utcnow().isoformat()

    return {
        "aggregate": AFRICA_AGGREGATE,
        "countries": {
            code: data for code, data in STATIC_AFRICA_DATA.items()
        },
        "source": "AfDB / World Bank (static data)",
        "timestamp": now,
        "error": None,
    }


def get_country_indicators(country_code: str) -> dict:
    """アフリカ各国の経済指標を取得

    Args:
        country_code: ISO3国コード (e.g., "NGA", "ZAF")

    Returns:
        dict: 当該国の経済データ
    """
    now = datetime.utcnow().isoformat()
    code = country_code.upper()

    # ISO2→ISO3変換
    iso2_to_iso3 = {
        "NG": "NGA", "ZA": "ZAF", "ET": "ETH", "KE": "KEN",
        "EG": "EGY", "MA": "MAR", "GH": "GHA",
    }
    if code in iso2_to_iso3:
        code = iso2_to_iso3[code]

    if code not in STATIC_AFRICA_DATA:
        return {
            "indicators": {},
            "source": "AfDB",
            "timestamp": now,
            "error": f"No data for country: {country_code}. Available: {list(STATIC_AFRICA_DATA.keys())}",
        }

    # Try live API first
    api_result = fetch_afdb_data(country=code)
    if api_result.get("error") is None and api_result.get("data"):
        # Merge with static data
        indicators = dict(STATIC_AFRICA_DATA[code])
        indicators["live_data"] = api_result["data"]
        return {
            "indicators": indicators,
            "source": "AfDB (mixed live + static)",
            "timestamp": now,
            "error": None,
            "country_code": code,
        }

    # Static fallback
    return {
        "indicators": STATIC_AFRICA_DATA[code],
        "source": "AfDB / World Bank (static data)",
        "timestamp": now,
        "error": None,
        "country_code": code,
    }


def get_africa_supply_chain_profile() -> dict:
    """アフリカのサプライチェーンプロファイル

    Returns:
        dict: サプライチェーン関連のアフリカ指標
    """
    now = datetime.utcnow().isoformat()

    critical_minerals = {
        "platinum_group_metals": {"top_producer": "ZAF", "global_share_pct": 72.0},
        "cobalt": {"top_producer": "COD", "global_share_pct": 73.0},
        "manganese": {"top_producer": "ZAF", "global_share_pct": 37.0},
        "chromium": {"top_producer": "ZAF", "global_share_pct": 44.0},
        "tantalum": {"top_producer": "COD", "global_share_pct": 38.0},
        "diamonds": {"top_producer": "BWA", "global_share_pct": 22.0},
        "gold": {"top_producer": "GHA", "global_share_pct": 5.8},
        "phosphates": {"top_producer": "MAR", "global_share_pct": 70.0},
    }

    key_trade_routes = {
        "suez_canal": {
            "operator_country": "EGY",
            "global_trade_share_pct": 12.0,
            "annual_vessels": 23_800,
            "risk_level": "HIGH (Houthi disruption 2024)",
        },
        "cape_of_good_hope": {
            "description": "Alternative to Suez Canal",
            "adds_days": 10,
            "risk_level": "MEDIUM (weather, longer transit)",
        },
        "port_of_durban": {
            "country": "ZAF",
            "container_teu_mn": 2.5,
            "description": "Largest port in Africa",
        },
        "tangier_med": {
            "country": "MAR",
            "container_teu_mn": 7.8,
            "description": "Major transshipment hub (Africa-EU)",
        },
        "mombasa": {
            "country": "KEN",
            "container_teu_mn": 1.4,
            "description": "Key East African port",
        },
    }

    return {
        "critical_minerals": critical_minerals,
        "key_trade_routes": key_trade_routes,
        "aggregate": AFRICA_AGGREGATE,
        "source": "AfDB / USGS / Various (static data)",
        "timestamp": now,
        "error": None,
        "focus": "supply_chain_profile",
    }


def get_economic_indicators(country_code: str = "AFRICA") -> dict:
    """統一インターフェース: アフリカ経済指標を取得

    Args:
        country_code: 国コード ("AFRICA"で大陸全体、個別ISO3コードで各国)

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    if country_code.upper() in ("AFRICA", "AFR"):
        overview = get_africa_overview()
        return {
            "indicators": overview["aggregate"],
            "countries": overview["countries"],
            "source": overview["source"],
            "timestamp": overview["timestamp"],
            "error": None,
        }

    return get_country_indicators(country_code)


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("AfDB (African Development Bank) Open Data Client Test")
    print("=" * 60)

    # 1) 疎通テスト
    print("\n[1] Connectivity Test")
    conn = test_connectivity()
    for name, status in conn.items():
        reachable = "OK" if status["reachable"] else "FAIL"
        print(f"  {name}: {reachable} (status={status['status_code']}, latency={status['latency_ms']}ms)")
        if status["error"]:
            print(f"    Error: {status['error']}")

    # 2) アフリカ概況
    print("\n[2] Africa Overview")
    overview = get_economic_indicators("AFRICA")
    print(f"  Source: {overview['source']}")
    print("  Aggregate:")
    for key, val in overview.get("indicators", {}).items():
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')} {val.get('unit', '')}")

    # 3) 主要国GDP
    print("\n[3] Key African Countries (by GDP)")
    countries = overview.get("countries", {})
    sorted_countries = sorted(countries.items(), key=lambda x: x[1].get("gdp_usd_bn", 0), reverse=True)
    for code, data in sorted_countries:
        print(f"    {code} ({data['country_name']}): GDP ${data['gdp_usd_bn']}B, Growth {data['gdp_growth_pct']}%")

    # 4) 個別国データ
    print("\n[4] Nigeria (individual)")
    nga = get_country_indicators("NGA")
    indicators = nga.get("indicators", {})
    print(f"  Name: {indicators.get('country_name')}")
    print(f"  GDP: ${indicators.get('gdp_usd_bn')}B")
    print(f"  Oil Production: {indicators.get('oil_production_mbpd')} Mbpd")
    print(f"  Key Exports: {indicators.get('key_exports')}")

    # 5) サプライチェーンプロファイル
    print("\n[5] Africa Supply Chain Profile")
    profile = get_africa_supply_chain_profile()
    print("  Critical Minerals:")
    for mineral, data in profile.get("critical_minerals", {}).items():
        print(f"    {mineral}: {data['top_producer']} ({data['global_share_pct']}% global share)")
    print("  Key Trade Routes:")
    for route, data in profile.get("key_trade_routes", {}).items():
        print(f"    {route}: {data.get('description', data.get('risk_level', ''))}")

    # 6) エジプト (スエズ運河)
    print("\n[6] Egypt (Suez Canal)")
    egy = get_country_indicators("EGY")
    indicators = egy.get("indicators", {})
    print(f"  Suez Canal Revenue: ${indicators.get('suez_canal_revenue_usd_bn')}B")
    print(f"  Supply Chain Notes: {indicators.get('supply_chain_notes')}")

    # 7) 未知の国コード
    print("\n[7] Unknown country code test")
    bad = get_economic_indicators("XYZ")
    print(f"  Error: {bad.get('error')}")
