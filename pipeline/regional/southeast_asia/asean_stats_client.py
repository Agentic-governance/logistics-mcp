"""ASEAN統計データポータル クライアント
ASEAN Stats Data Portal - ASEAN 10カ国の経済・貿易データ
APIキー不要

https://data.aseanstats.org/
No formal REST API exists (confirmed in research).
Implement with static ASEAN-10 trade/economic data from latest available year.
"""
import requests
import time
from datetime import datetime
from typing import Optional

ASEAN_STATS_BASE = "https://data.aseanstats.org"

# ASEAN 10カ国の基本情報
ASEAN_MEMBERS = {
    "BRN": {"name": "Brunei Darussalam", "iso2": "BN", "joined": 1984},
    "KHM": {"name": "Cambodia", "iso2": "KH", "joined": 1999},
    "IDN": {"name": "Indonesia", "iso2": "ID", "joined": 1967},
    "LAO": {"name": "Lao PDR", "iso2": "LA", "joined": 1997},
    "MYS": {"name": "Malaysia", "iso2": "MY", "joined": 1967},
    "MMR": {"name": "Myanmar", "iso2": "MM", "joined": 1997},
    "PHL": {"name": "Philippines", "iso2": "PH", "joined": 1967},
    "SGP": {"name": "Singapore", "iso2": "SG", "joined": 1967},
    "THA": {"name": "Thailand", "iso2": "TH", "joined": 1967},
    "VNM": {"name": "Vietnam", "iso2": "VN", "joined": 1995},
}

# ASEAN-10 経済指標 (2024年実績/推定ベース)
ASEAN_ECONOMIC_DATA = {
    "BRN": {
        "gdp_usd_bn": 15.1,
        "gdp_growth_pct": 2.8,
        "population_mn": 0.45,
        "gdp_per_capita_usd": 33_556,
        "exports_usd_bn": 11.2,
        "imports_usd_bn": 6.8,
        "fdi_inflow_usd_bn": 0.6,
        "inflation_pct": 1.5,
        "unemployment_pct": 5.2,
        "key_exports": ["Oil & Gas", "Petrochemicals", "Machinery"],
    },
    "KHM": {
        "gdp_usd_bn": 33.5,
        "gdp_growth_pct": 5.8,
        "population_mn": 17.2,
        "gdp_per_capita_usd": 1_948,
        "exports_usd_bn": 22.8,
        "imports_usd_bn": 26.2,
        "fdi_inflow_usd_bn": 3.8,
        "inflation_pct": 2.5,
        "unemployment_pct": 0.3,
        "key_exports": ["Garments", "Electronics", "Agricultural Products"],
    },
    "IDN": {
        "gdp_usd_bn": 1_371.0,
        "gdp_growth_pct": 5.05,
        "population_mn": 277.5,
        "gdp_per_capita_usd": 4_942,
        "exports_usd_bn": 264.8,
        "imports_usd_bn": 221.5,
        "fdi_inflow_usd_bn": 21.6,
        "inflation_pct": 2.3,
        "unemployment_pct": 4.8,
        "key_exports": ["Palm Oil", "Coal", "Nickel", "Textiles", "Electronics"],
    },
    "LAO": {
        "gdp_usd_bn": 15.8,
        "gdp_growth_pct": 4.5,
        "population_mn": 7.5,
        "gdp_per_capita_usd": 2_107,
        "exports_usd_bn": 8.2,
        "imports_usd_bn": 7.5,
        "fdi_inflow_usd_bn": 1.2,
        "inflation_pct": 25.2,
        "unemployment_pct": 2.1,
        "key_exports": ["Electricity (Hydropower)", "Mining", "Agriculture"],
    },
    "MYS": {
        "gdp_usd_bn": 415.4,
        "gdp_growth_pct": 5.1,
        "population_mn": 33.9,
        "gdp_per_capita_usd": 12_254,
        "exports_usd_bn": 330.8,
        "imports_usd_bn": 285.4,
        "fdi_inflow_usd_bn": 13.8,
        "inflation_pct": 1.8,
        "unemployment_pct": 3.2,
        "key_exports": ["Electronics", "Palm Oil", "Petroleum", "Chemicals"],
    },
    "MMR": {
        "gdp_usd_bn": 59.4,
        "gdp_growth_pct": 1.0,
        "population_mn": 54.8,
        "gdp_per_capita_usd": 1_084,
        "exports_usd_bn": 11.8,
        "imports_usd_bn": 15.2,
        "fdi_inflow_usd_bn": 1.4,
        "inflation_pct": 16.5,
        "unemployment_pct": 3.0,
        "key_exports": ["Natural Gas", "Garments", "Agricultural Products"],
    },
    "PHL": {
        "gdp_usd_bn": 435.7,
        "gdp_growth_pct": 5.6,
        "population_mn": 115.6,
        "gdp_per_capita_usd": 3_768,
        "exports_usd_bn": 80.2,
        "imports_usd_bn": 128.5,
        "fdi_inflow_usd_bn": 9.2,
        "inflation_pct": 3.2,
        "unemployment_pct": 3.8,
        "key_exports": ["Electronics (Semiconductors)", "BPO Services", "Agricultural Products"],
    },
    "SGP": {
        "gdp_usd_bn": 497.5,
        "gdp_growth_pct": 3.6,
        "population_mn": 5.9,
        "gdp_per_capita_usd": 84_322,
        "exports_usd_bn": 515.3,
        "imports_usd_bn": 492.8,
        "fdi_inflow_usd_bn": 141.2,
        "inflation_pct": 2.4,
        "unemployment_pct": 1.9,
        "key_exports": ["Electronics", "Petroleum", "Chemicals", "Pharmaceuticals"],
    },
    "THA": {
        "gdp_usd_bn": 512.2,
        "gdp_growth_pct": 2.7,
        "population_mn": 71.8,
        "gdp_per_capita_usd": 7_132,
        "exports_usd_bn": 290.5,
        "imports_usd_bn": 278.8,
        "fdi_inflow_usd_bn": 9.5,
        "inflation_pct": 0.4,
        "unemployment_pct": 1.0,
        "key_exports": ["Automobiles", "Electronics", "Rubber", "Rice", "Petrochemicals"],
    },
    "VNM": {
        "gdp_usd_bn": 465.8,
        "gdp_growth_pct": 7.09,
        "population_mn": 100.3,
        "gdp_per_capita_usd": 4_644,
        "exports_usd_bn": 405.5,
        "imports_usd_bn": 380.2,
        "fdi_inflow_usd_bn": 25.4,
        "inflation_pct": 3.6,
        "unemployment_pct": 2.1,
        "key_exports": ["Electronics", "Textiles", "Footwear", "Seafood", "Machinery"],
    },
}

# ASEAN全体のサマリー統計
ASEAN_AGGREGATE = {
    "total_gdp_usd_tn": {
        "value": 3.82,
        "unit": "trillion_usd",
        "period": "2024",
        "description": "ASEAN Combined GDP",
    },
    "total_population_mn": {
        "value": 684.9,
        "unit": "million",
        "period": "2024",
        "description": "ASEAN Total Population",
    },
    "total_exports_usd_tn": {
        "value": 1.94,
        "unit": "trillion_usd",
        "period": "2024",
        "description": "ASEAN Total Exports",
    },
    "total_imports_usd_tn": {
        "value": 1.84,
        "unit": "trillion_usd",
        "period": "2024",
        "description": "ASEAN Total Imports",
    },
    "total_fdi_inflow_usd_bn": {
        "value": 227.7,
        "unit": "billion_usd",
        "period": "2024",
        "description": "ASEAN Total FDI Inflow",
    },
    "avg_gdp_growth_pct": {
        "value": 4.3,
        "unit": "percent",
        "period": "2024",
        "description": "ASEAN Average GDP Growth",
    },
    "intra_asean_trade_share_pct": {
        "value": 21.5,
        "unit": "percent",
        "period": "2024",
        "description": "Intra-ASEAN Trade as Share of Total Trade",
    },
    "global_gdp_share_pct": {
        "value": 3.6,
        "unit": "percent",
        "period": "2024",
        "description": "ASEAN Share of Global GDP",
    },
}

# ASEAN主要貿易相手地域
ASEAN_DIALOGUE_PARTNERS_TRADE = {
    "CHN": {
        "name": "China",
        "trade_usd_bn": 912.5,
        "share_pct": 24.1,
        "description": "ASEAN's largest trading partner",
    },
    "USA": {
        "name": "United States",
        "trade_usd_bn": 452.8,
        "share_pct": 12.0,
        "description": "Key export destination",
    },
    "EU": {
        "name": "European Union",
        "trade_usd_bn": 318.5,
        "share_pct": 8.4,
        "description": "Major trade & investment partner",
    },
    "JPN": {
        "name": "Japan",
        "trade_usd_bn": 278.3,
        "share_pct": 7.4,
        "description": "Major investor and trade partner",
    },
    "KOR": {
        "name": "South Korea",
        "trade_usd_bn": 198.5,
        "share_pct": 5.2,
        "description": "Growing trade & investment partner",
    },
    "IND": {
        "name": "India",
        "trade_usd_bn": 131.2,
        "share_pct": 3.5,
        "description": "Emerging trade partner",
    },
    "AUS": {
        "name": "Australia",
        "trade_usd_bn": 98.5,
        "share_pct": 2.6,
        "description": "Resources & services partner",
    },
}


def test_connectivity() -> dict:
    """ASEAN統計ポータルへの疎通テストを実施

    Returns:
        dict: 接続結果
    """
    start = time.time()
    try:
        resp = requests.get(
            f"{ASEAN_STATS_BASE}/",
            timeout=15,
            allow_redirects=True,
        )
        latency = (time.time() - start) * 1000
        return {
            "reachable": resp.status_code < 500,
            "status_code": resp.status_code,
            "latency_ms": round(latency, 1),
            "error": None,
            "note": "No formal REST API available; data portal is web-only",
        }
    except requests.exceptions.RequestException as e:
        return {
            "reachable": False,
            "status_code": None,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "error": str(e),
        }


def get_asean_overview() -> dict:
    """ASEAN 10カ国の経済概況を取得

    Returns:
        dict: ASEAN全体のサマリーおよび各国データ
    """
    now = datetime.utcnow().isoformat()

    return {
        "aggregate": ASEAN_AGGREGATE,
        "members": {
            code: {
                "name": ASEAN_MEMBERS[code]["name"],
                **data,
            }
            for code, data in ASEAN_ECONOMIC_DATA.items()
        },
        "dialogue_partners_trade": ASEAN_DIALOGUE_PARTNERS_TRADE,
        "source": "ASEAN Stats (static data - no REST API available)",
        "timestamp": now,
        "error": None,
    }


def get_country_data(country_code: str) -> dict:
    """ASEAN加盟国の個別経済データを取得

    Args:
        country_code: ISO3国コード (e.g., "VNM", "THA")

    Returns:
        dict: 当該国の経済データ
    """
    now = datetime.utcnow().isoformat()
    code = country_code.upper()

    # ISO2→ISO3変換
    for iso3, info in ASEAN_MEMBERS.items():
        if info["iso2"] == code:
            code = iso3
            break

    if code not in ASEAN_ECONOMIC_DATA:
        return {
            "indicators": {},
            "source": "ASEAN Stats",
            "timestamp": now,
            "error": f"Country not found in ASEAN members: {country_code}",
        }

    member_info = ASEAN_MEMBERS[code]
    econ_data = ASEAN_ECONOMIC_DATA[code]

    return {
        "indicators": {
            "name": member_info["name"],
            "iso3": code,
            "iso2": member_info["iso2"],
            "asean_joined": member_info["joined"],
            **econ_data,
        },
        "source": "ASEAN Stats (static data)",
        "timestamp": now,
        "error": None,
    }


def get_asean_supply_chain_ranking() -> dict:
    """ASEAN加盟国のサプライチェーン関連指標ランキング

    Returns:
        dict: 各指標でのランキング
    """
    now = datetime.utcnow().isoformat()

    # GDP規模ランキング
    gdp_ranking = sorted(
        ASEAN_ECONOMIC_DATA.items(),
        key=lambda x: x[1]["gdp_usd_bn"],
        reverse=True,
    )

    # 輸出額ランキング
    export_ranking = sorted(
        ASEAN_ECONOMIC_DATA.items(),
        key=lambda x: x[1]["exports_usd_bn"],
        reverse=True,
    )

    # GDP成長率ランキング
    growth_ranking = sorted(
        ASEAN_ECONOMIC_DATA.items(),
        key=lambda x: x[1]["gdp_growth_pct"],
        reverse=True,
    )

    # FDI受入額ランキング
    fdi_ranking = sorted(
        ASEAN_ECONOMIC_DATA.items(),
        key=lambda x: x[1]["fdi_inflow_usd_bn"],
        reverse=True,
    )

    def _format_ranking(ranking: list, value_key: str) -> list[dict]:
        return [
            {
                "rank": i + 1,
                "country_code": code,
                "country_name": ASEAN_MEMBERS[code]["name"],
                "value": data[value_key],
            }
            for i, (code, data) in enumerate(ranking)
        ]

    return {
        "rankings": {
            "gdp_size": _format_ranking(gdp_ranking, "gdp_usd_bn"),
            "export_volume": _format_ranking(export_ranking, "exports_usd_bn"),
            "gdp_growth": _format_ranking(growth_ranking, "gdp_growth_pct"),
            "fdi_inflow": _format_ranking(fdi_ranking, "fdi_inflow_usd_bn"),
        },
        "source": "ASEAN Stats (static data)",
        "timestamp": now,
        "error": None,
    }


def get_economic_indicators(country_code: str = "ASEAN") -> dict:
    """統一インターフェース: ASEAN経済指標を取得

    Args:
        country_code: 国コード ("ASEAN"で全体概況、個別ISO3コードで加盟国データ)

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    now = datetime.utcnow().isoformat()

    if country_code.upper() == "ASEAN":
        overview = get_asean_overview()
        return {
            "indicators": overview["aggregate"],
            "members": overview["members"],
            "source": overview["source"],
            "timestamp": now,
            "error": None,
        }

    # 個別国データ
    code = country_code.upper()
    # Check if it's an ASEAN member
    is_member = code in ASEAN_ECONOMIC_DATA
    if not is_member:
        # Try ISO2 lookup
        for iso3, info in ASEAN_MEMBERS.items():
            if info["iso2"] == code:
                is_member = True
                break

    if not is_member:
        return {
            "indicators": {},
            "source": "ASEAN Stats",
            "timestamp": now,
            "error": f"Country {country_code} is not an ASEAN member. Use 'ASEAN' for overview.",
        }

    return get_country_data(country_code)


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("ASEAN Stats Data Portal Client Test")
    print("=" * 60)

    # 1) 疎通テスト
    print("\n[1] Connectivity Test")
    conn = test_connectivity()
    print(f"  Reachable: {conn['reachable']}")
    print(f"  Status Code: {conn['status_code']}")
    print(f"  Latency: {conn['latency_ms']} ms")
    if conn.get("note"):
        print(f"  Note: {conn['note']}")
    if conn["error"]:
        print(f"  Error: {conn['error']}")

    # 2) ASEAN概況
    print("\n[2] ASEAN Overview")
    overview = get_economic_indicators("ASEAN")
    print(f"  Source: {overview['source']}")
    print("  Aggregate Indicators:")
    for key, val in overview.get("indicators", {}).items():
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')} {val.get('unit', '')}")

    # 3) 各国GDP
    print("\n[3] ASEAN Members (by GDP)")
    members = overview.get("members", {})
    sorted_members = sorted(members.items(), key=lambda x: x[1].get("gdp_usd_bn", 0), reverse=True)
    for code, data in sorted_members:
        print(f"    {code} ({data['name']}): GDP ${data['gdp_usd_bn']}B, Growth {data['gdp_growth_pct']}%")

    # 4) 個別国データ
    print("\n[4] Vietnam (individual)")
    vnm = get_economic_indicators("VNM")
    indicators = vnm.get("indicators", {})
    print(f"  Name: {indicators.get('name')}")
    print(f"  GDP: ${indicators.get('gdp_usd_bn')}B")
    print(f"  Exports: ${indicators.get('exports_usd_bn')}B")
    print(f"  Key Exports: {indicators.get('key_exports')}")

    # 5) ランキング
    print("\n[5] Supply Chain Rankings")
    rankings = get_asean_supply_chain_ranking()
    print("  GDP Growth Ranking:")
    for entry in rankings["rankings"]["gdp_growth"]:
        print(f"    #{entry['rank']} {entry['country_code']} ({entry['country_name']}): {entry['value']}%")

    # 6) 不正な国コード
    print("\n[6] Non-ASEAN country test")
    bad = get_economic_indicators("USA")
    print(f"  Error: {bad['error']}")
