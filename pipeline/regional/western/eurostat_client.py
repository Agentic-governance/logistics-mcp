"""Eurostat COMEXT貿易統計 クライアント
European Statistical Office - EU貿易統計データ (JSON-stat format)
APIキー不要

Base: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/
Dataset: ext_lt_maineu (EU trade with main partners)
Focus: EU-Japan trade flows
"""
import requests
import time
from datetime import datetime
from typing import Optional

EUROSTAT_API_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

# Eurostat dataset codes
DATASETS = {
    "ext_lt_maineu": "EU trade with main partners (monthly)",
    "ext_lt_mainez": "EU trade with main partners (EU extra-zone)",
    "sts_inpr_m": "Industrial Production Index (monthly)",
    "prc_hicp_manr": "HICP (Harmonised CPI) annual rate",
    "ei_bsin_m_r2": "Business Climate Indicator",
}

# Eurostat partner codes
PARTNER_CODES = {
    "JP": "Japan",
    "CN": "China",
    "US": "United States",
    "KR": "South Korea",
    "IN": "India",
    "UK": "United Kingdom",
    "CH": "Switzerland",
    "RU": "Russia",
    "TR": "Turkey",
    "BR": "Brazil",
    "AU": "Australia",
    "MX": "Mexico",
    "SG": "Singapore",
    "TW": "Taiwan",
    "VN": "Vietnam",
    "TH": "Thailand",
    "MY": "Malaysia",
    "ID": "Indonesia",
}

# EU-Japan 貿易データ (2024年実績ベース静的データ)
STATIC_EU_JAPAN_TRADE = {
    "eu_exports_to_japan_eur_bn": {
        "value": 68.5,
        "unit": "billion_eur",
        "period": "2024",
        "description": "EU Exports to Japan",
    },
    "eu_imports_from_japan_eur_bn": {
        "value": 72.8,
        "unit": "billion_eur",
        "period": "2024",
        "description": "EU Imports from Japan",
    },
    "eu_japan_trade_balance_eur_bn": {
        "value": -4.3,
        "unit": "billion_eur",
        "period": "2024",
        "description": "EU-Japan Trade Balance (EU perspective)",
    },
    "japan_share_eu_trade_pct": {
        "value": 3.1,
        "unit": "percent",
        "period": "2024",
        "description": "Japan Share of EU External Trade",
    },
}

# EU全体の貿易指標
STATIC_EU_TRADE = {
    "eu_total_exports_eur_tn": {
        "value": 2.55,
        "unit": "trillion_eur",
        "period": "2024",
        "description": "EU Total Extra-EU Exports",
    },
    "eu_total_imports_eur_tn": {
        "value": 2.42,
        "unit": "trillion_eur",
        "period": "2024",
        "description": "EU Total Extra-EU Imports",
    },
    "eu_trade_balance_eur_bn": {
        "value": 130.0,
        "unit": "billion_eur",
        "period": "2024",
        "description": "EU Extra-EU Trade Balance",
    },
    "eu_industrial_production_yoy": {
        "value": -1.8,
        "unit": "percent",
        "period": "2024-Q4",
        "description": "EU Industrial Production YoY Growth",
    },
    "eu_hicp_yoy": {
        "value": 2.4,
        "unit": "percent",
        "period": "2024-12",
        "description": "EU HICP (Harmonised CPI) YoY",
    },
    "eu_gdp_growth": {
        "value": 0.8,
        "unit": "percent",
        "period": "2024",
        "description": "EU GDP Growth Rate",
    },
    "eu_unemployment_rate": {
        "value": 5.9,
        "unit": "percent",
        "period": "2024-12",
        "description": "EU Unemployment Rate",
    },
}

# EU主要貿易相手国 (2024年)
EU_TRADE_PARTNERS = {
    "CN": {
        "name": "China",
        "exports_eur_bn": 223.5,
        "imports_eur_bn": 512.8,
        "share_pct": 16.1,
    },
    "US": {
        "name": "United States",
        "exports_eur_bn": 502.5,
        "imports_eur_bn": 312.4,
        "share_pct": 17.8,
    },
    "UK": {
        "name": "United Kingdom",
        "exports_eur_bn": 342.8,
        "imports_eur_bn": 195.2,
        "share_pct": 11.8,
    },
    "CH": {
        "name": "Switzerland",
        "exports_eur_bn": 182.4,
        "imports_eur_bn": 138.5,
        "share_pct": 7.0,
    },
    "JP": {
        "name": "Japan",
        "exports_eur_bn": 68.5,
        "imports_eur_bn": 72.8,
        "share_pct": 3.1,
    },
    "KR": {
        "name": "South Korea",
        "exports_eur_bn": 58.2,
        "imports_eur_bn": 62.5,
        "share_pct": 2.6,
    },
    "IN": {
        "name": "India",
        "exports_eur_bn": 52.8,
        "imports_eur_bn": 58.1,
        "share_pct": 2.4,
    },
    "TR": {
        "name": "Turkey",
        "exports_eur_bn": 82.5,
        "imports_eur_bn": 78.2,
        "share_pct": 3.5,
    },
}


def test_connectivity() -> dict:
    """Eurostat APIサーバーへの疎通テストを実施

    Returns:
        dict: 接続結果
    """
    start = time.time()
    # Test with a simple query to the API
    test_url = f"{EUROSTAT_API_BASE}/ext_lt_maineu"
    params = {
        "partner": "JP",
        "flow": "1",
        "sinceTimePeriod": "2024M01",
        "untilTimePeriod": "2024M01",
    }

    try:
        resp = requests.get(test_url, params=params, timeout=15)
        latency = (time.time() - start) * 1000
        return {
            "reachable": resp.status_code < 500,
            "status_code": resp.status_code,
            "latency_ms": round(latency, 1),
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "reachable": False,
            "status_code": None,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "error": str(e),
        }


def fetch_eurostat_data(
    dataset: str,
    params: Optional[dict] = None,
) -> dict:
    """Eurostat JSON-stat APIからデータを取得

    Args:
        dataset: データセットコード (e.g., "ext_lt_maineu")
        params: クエリパラメータ

    Returns:
        dict: APIレスポンス (JSON-stat format) またはエラー
    """
    now = datetime.utcnow().isoformat()
    url = f"{EUROSTAT_API_BASE}/{dataset}"

    try:
        resp = requests.get(url, params=params or {}, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # JSON-stat format parsing
        if "value" in data:
            return {
                "data": data,
                "source": "Eurostat (live API, JSON-stat)",
                "timestamp": now,
                "error": None,
            }
        elif "error" in data:
            return {
                "error": f"Eurostat API error: {data.get('error', {}).get('label', 'Unknown')}",
                "source": "Eurostat",
                "timestamp": now,
            }
        else:
            return {
                "data": data,
                "source": "Eurostat (live API)",
                "timestamp": now,
                "error": None,
            }

    except requests.exceptions.RequestException as e:
        return {
            "error": f"Eurostat API request failed: {str(e)}",
            "source": "Eurostat",
            "timestamp": now,
        }
    except ValueError as e:
        return {
            "error": f"Eurostat response parse error: {str(e)}",
            "source": "Eurostat",
            "timestamp": now,
        }


def _parse_jsonstat_values(data: dict) -> list[dict]:
    """JSON-stat形式のレスポンスを解析してレコードリストに変換

    Args:
        data: JSON-stat形式データ

    Returns:
        list: パースされたレコードリスト
    """
    values = data.get("value", {})
    dimensions = data.get("dimension", {})
    sizes = data.get("size", [])

    if not values or not dimensions:
        return []

    # Extract dimension labels
    dim_ids = data.get("id", [])
    records: list[dict] = []

    # Simple extraction: time period values
    time_dim = None
    for dim_id in dim_ids:
        dim = dimensions.get(dim_id, {})
        if dim.get("category", {}).get("label"):
            cat_labels = dim["category"]["label"]
            cat_index = dim["category"].get("index", {})

            if dim_id in ("time", "TIME_PERIOD"):
                time_dim = cat_labels

    for idx_str, val in values.items():
        idx = int(idx_str)
        record: dict = {"value": val, "index": idx}
        records.append(record)

    return records


def get_eu_japan_trade() -> dict:
    """EU-Japan貿易フローを取得

    Returns:
        dict: EU-Japan間の貿易データ
    """
    now = datetime.utcnow().isoformat()

    # Try live API for exports (flow=1) and imports (flow=2)
    export_params = {
        "partner": "JP",
        "flow": "1",  # 1 = exports
        "sinceTimePeriod": "2024M01",
    }
    import_params = {
        "partner": "JP",
        "flow": "2",  # 2 = imports
        "sinceTimePeriod": "2024M01",
    }

    export_result = fetch_eurostat_data("ext_lt_maineu", export_params)
    import_result = fetch_eurostat_data("ext_lt_maineu", import_params)

    if export_result.get("error") is None and import_result.get("error") is None:
        return {
            "exports": export_result.get("data", {}),
            "imports": import_result.get("data", {}),
            "source": "Eurostat COMEXT (live API)",
            "timestamp": now,
            "error": None,
        }

    # Fallback to static data
    return {
        "indicators": STATIC_EU_JAPAN_TRADE,
        "source": "Eurostat (static fallback)",
        "timestamp": now,
        "error": None,
    }


def get_eu_trade_with_partner(partner_code: str) -> dict:
    """特定の相手国とのEU貿易データを取得

    Args:
        partner_code: 相手国のISO2コード (e.g., "JP", "CN")

    Returns:
        dict: 二国間貿易データ
    """
    now = datetime.utcnow().isoformat()
    code = partner_code.upper()

    # First try live API
    params = {
        "partner": code,
        "flow": "1,2",  # exports and imports
        "sinceTimePeriod": "2024M01",
    }
    result = fetch_eurostat_data("ext_lt_maineu", params)

    if result.get("error") is None and result.get("data"):
        return {
            "data": result["data"],
            "source": "Eurostat COMEXT (live API)",
            "timestamp": now,
            "error": None,
        }

    # Fallback to static
    if code in EU_TRADE_PARTNERS:
        partner = EU_TRADE_PARTNERS[code]
        return {
            "indicators": {
                "partner_name": partner["name"],
                "partner_code": code,
                "exports_eur_bn": partner["exports_eur_bn"],
                "imports_eur_bn": partner["imports_eur_bn"],
                "trade_share_pct": partner["share_pct"],
                "trade_balance_eur_bn": round(
                    partner["exports_eur_bn"] - partner["imports_eur_bn"], 1
                ),
            },
            "source": "Eurostat (static fallback)",
            "timestamp": now,
            "error": None,
        }

    return {
        "indicators": {},
        "source": "Eurostat",
        "timestamp": now,
        "error": f"No trade data available for partner: {partner_code}",
    }


def get_eu_economic_indicators() -> dict:
    """EUの主要経済指標を取得

    Returns:
        dict: EU経済指標データ
    """
    now = datetime.utcnow().isoformat()

    # Try live data for industrial production
    ipi_result = fetch_eurostat_data("sts_inpr_m", {
        "geo": "EU27_2020",
        "nace_r2": "B-D",
        "s_adj": "SCA",
        "unit": "PCH_SM",
        "sinceTimePeriod": "2024M01",
    })

    indicators = dict(STATIC_EU_TRADE)

    if ipi_result.get("error") is None and ipi_result.get("data"):
        values = ipi_result["data"].get("value", {})
        if values:
            # Get latest value
            max_key = max(values.keys(), key=int) if values else None
            if max_key:
                indicators["eu_industrial_production_yoy_live"] = {
                    "value": values[max_key],
                    "unit": "percent",
                    "period": "live",
                    "description": "EU Industrial Production (live)",
                    "source_note": "live_api",
                }

    source = "Eurostat (static data)"
    if any(v.get("source_note") == "live_api" for v in indicators.values() if isinstance(v, dict)):
        source = "Eurostat (mixed live + static)"

    return {
        "indicators": indicators,
        "eu_japan_trade": STATIC_EU_JAPAN_TRADE,
        "trade_partners": EU_TRADE_PARTNERS,
        "source": source,
        "timestamp": now,
        "error": None,
        "region": "EU",
        "region_name": "European Union",
    }


def get_economic_indicators(country_code: str = "EU") -> dict:
    """統一インターフェース: EU経済指標を取得

    Args:
        country_code: 地域/国コード ("EU"でEU全体)

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    code = country_code.upper()
    if code in ("EU", "EU27", "EUR"):
        return get_eu_economic_indicators()

    # 個別パートナー国との貿易
    if code in PARTNER_CODES or code in EU_TRADE_PARTNERS:
        return get_eu_trade_with_partner(code)

    return {
        "indicators": {},
        "source": "Eurostat",
        "timestamp": datetime.utcnow().isoformat(),
        "error": f"Use 'EU' for EU indicators or a partner code (JP, CN, US, etc.) for bilateral trade. Got: {country_code}",
    }


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("Eurostat COMEXT Trade Statistics Client Test")
    print("=" * 60)

    # 1) 疎通テスト
    print("\n[1] Connectivity Test")
    conn = test_connectivity()
    print(f"  Reachable: {conn['reachable']}")
    print(f"  Status Code: {conn['status_code']}")
    print(f"  Latency: {conn['latency_ms']} ms")
    if conn["error"]:
        print(f"  Error: {conn['error']}")

    # 2) EU経済指標
    print("\n[2] EU Economic Indicators")
    result = get_economic_indicators("EU")
    print(f"  Source: {result['source']}")
    print(f"  Timestamp: {result['timestamp']}")
    if result.get("error"):
        print(f"  Error: {result['error']}")
    print("  Indicators:")
    for key, val in result.get("indicators", {}).items():
        if isinstance(val, dict) and "value" in val:
            print(f"    {key}: {val['value']} {val.get('unit', '')} ({val.get('period', '')})")

    # 3) EU-Japan貿易
    print("\n[3] EU-Japan Trade")
    jp_trade = get_eu_japan_trade()
    print(f"  Source: {jp_trade['source']}")
    for key, val in jp_trade.get("indicators", {}).items():
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')} {val.get('unit', '')} ({val.get('period', '')})")

    # 4) EU主要貿易相手国
    print("\n[4] EU Trade Partners")
    for code, partner in result.get("trade_partners", {}).items():
        balance = partner["exports_eur_bn"] - partner["imports_eur_bn"]
        print(f"    {code} ({partner['name']}): Exp {partner['exports_eur_bn']}B, Imp {partner['imports_eur_bn']}B, Balance {balance:+.1f}B EUR")

    # 5) 個別パートナー
    print("\n[5] EU-China Trade (individual)")
    cn = get_economic_indicators("CN")
    for key, val in cn.get("indicators", {}).items():
        print(f"    {key}: {val}")

    # 6) 不正なコード
    print("\n[6] Invalid code test")
    bad = get_economic_indicators("XYZ")
    print(f"  Error: {bad['error']}")
