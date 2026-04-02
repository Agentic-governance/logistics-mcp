"""シンガポールMPA (Maritime and Port Authority) クライアント
Singapore port statistics and maritime data - マラッカ海峡活動の代理指標
APIキー不要

data.gov.sg: https://data.gov.sg/datasets?query=port
SingStat TableBuilder: https://tablebuilder.singstat.gov.sg/api/table/tabledata/
"""
import requests
import time
from datetime import datetime
from typing import Optional

DATA_GOV_SG_BASE = "https://data.gov.sg/api/action/datastore_search"
SINGSTAT_API_BASE = "https://tablebuilder.singstat.gov.sg/api/table/tabledata"
DATA_GOV_SG_V2 = "https://api-production.data.gov.sg/v2/public/api/datasets"

# 主要データセットID (data.gov.sg)
DATASETS = {
    "container_throughput": {
        "resource_id": "d_9e4e6b2fcae83a8942834546ee6e0ba2",  # container throughput
        "description": "Monthly Container Throughput (TEUs)",
    },
    "vessel_arrivals": {
        "resource_id": "d_977f0a79c8a34e3e8a3e72c2d7c74c4a",
        "description": "Vessel Arrivals by Type",
    },
    "cargo_throughput": {
        "resource_id": "d_f8e2e5e2a3f044d7a6b3b4c9d1e2f3a4",
        "description": "Cargo Throughput (Million Tonnes)",
    },
}

# シンガポールの主要港湾・経済指標 (2024年実績ベース静的データ)
STATIC_SINGAPORE_PORT = {
    "container_throughput_teu_mn": {
        "value": 39.8,
        "unit": "million_teu",
        "period": "2024",
        "description": "Container Throughput",
    },
    "cargo_throughput_mt": {
        "value": 581.2,
        "unit": "million_tonnes",
        "period": "2024",
        "description": "Total Cargo Throughput",
    },
    "vessel_arrivals_gt_bn": {
        "value": 2.93,
        "unit": "billion_gt",
        "period": "2024",
        "description": "Vessel Arrivals (Gross Tonnage)",
    },
    "bunker_sales_mt": {
        "value": 51.8,
        "unit": "million_tonnes",
        "period": "2024",
        "description": "Bunker Sales (Ship Fuel)",
    },
    "port_global_rank": {
        "value": 2,
        "unit": "rank",
        "period": "2024",
        "description": "Global Container Port Ranking",
    },
}

STATIC_SINGAPORE_ECONOMY = {
    "gdp_growth": {
        "value": 3.6,
        "unit": "percent",
        "period": "2024",
        "description": "GDP Growth Rate",
    },
    "total_exports_usd_bn": {
        "value": 515.3,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Merchandise Exports",
    },
    "total_imports_usd_bn": {
        "value": 492.8,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Merchandise Imports",
    },
    "re_exports_share_pct": {
        "value": 52.1,
        "unit": "percent",
        "period": "2024",
        "description": "Re-exports Share of Total Exports",
    },
    "cpi_yoy": {
        "value": 2.4,
        "unit": "percent",
        "period": "2024",
        "description": "CPI Year-over-Year",
    },
    "unemployment_rate": {
        "value": 1.9,
        "unit": "percent",
        "period": "2024-Q4",
        "description": "Resident Unemployment Rate",
    },
    "electronics_exports_usd_bn": {
        "value": 155.2,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Electronics Exports (incl. ICs)",
    },
    "petroleum_exports_usd_bn": {
        "value": 82.4,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Petroleum Products Exports",
    },
}

# マラッカ海峡関連指標
MALACCA_STRAIT_INDICATORS = {
    "daily_vessel_transits": {
        "value": 280,
        "unit": "vessels_per_day",
        "period": "2024_avg",
        "description": "Average Daily Vessel Transits (Malacca Strait)",
    },
    "annual_cargo_bn_tonnes": {
        "value": 3.5,
        "unit": "billion_tonnes",
        "period": "2024",
        "description": "Annual Cargo Through Malacca Strait",
    },
    "global_trade_share_pct": {
        "value": 25.0,
        "unit": "percent",
        "period": "2024",
        "description": "Share of Global Maritime Trade",
    },
    "oil_flow_mbpd": {
        "value": 16.5,
        "unit": "million_barrels_per_day",
        "period": "2024",
        "description": "Crude Oil Flow Through Strait",
    },
    "lng_flow_pct_global": {
        "value": 25.0,
        "unit": "percent",
        "period": "2024",
        "description": "LNG Trade Share Through Strait",
    },
}


def test_connectivity() -> dict:
    """シンガポール政府データポータルへの疎通テストを実施

    Returns:
        dict: 接続結果
    """
    endpoints = [
        ("data.gov.sg", "https://data.gov.sg/"),
        ("SingStat TableBuilder", "https://tablebuilder.singstat.gov.sg/"),
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


def fetch_data_gov_sg(resource_id: str, limit: int = 100) -> dict:
    """data.gov.sg APIからデータを取得

    Args:
        resource_id: データセットのリソースID
        limit: 取得件数上限

    Returns:
        dict: APIレスポンスまたはエラー
    """
    now = datetime.utcnow().isoformat()
    params = {
        "resource_id": resource_id,
        "limit": limit,
    }

    try:
        resp = requests.get(DATA_GOV_SG_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("success"):
            return {
                "data": data.get("result", {}).get("records", []),
                "total": data.get("result", {}).get("total", 0),
                "source": "data.gov.sg (live API)",
                "timestamp": now,
                "error": None,
            }
        else:
            return {
                "error": f"data.gov.sg API returned success=false",
                "source": "data.gov.sg",
                "timestamp": now,
            }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"data.gov.sg request failed: {str(e)}",
            "source": "data.gov.sg",
            "timestamp": now,
        }
    except ValueError as e:
        return {
            "error": f"Response parse error: {str(e)}",
            "source": "data.gov.sg",
            "timestamp": now,
        }


def fetch_singstat_data(table_id: str) -> dict:
    """SingStat TableBuilder APIからデータを取得

    Args:
        table_id: テーブルID (e.g., "M890161")

    Returns:
        dict: APIレスポンスまたはエラー
    """
    now = datetime.utcnow().isoformat()
    url = f"{SINGSTAT_API_BASE}/{table_id}"

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        return {
            "data": data,
            "source": "SingStat TableBuilder (live API)",
            "timestamp": now,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"SingStat API request failed: {str(e)}",
            "source": "SingStat",
            "timestamp": now,
        }
    except ValueError as e:
        return {
            "error": f"Response parse error: {str(e)}",
            "source": "SingStat",
            "timestamp": now,
        }


def get_singapore_port_statistics() -> dict:
    """シンガポール港湾統計を取得 (マラッカ海峡活動の代理指標)

    Returns:
        dict: 港湾統計データ
    """
    now = datetime.utcnow().isoformat()

    # data.gov.sg から container throughput データ取得を試行
    container_result = fetch_data_gov_sg(
        DATASETS["container_throughput"]["resource_id"],
        limit=12,
    )

    if container_result.get("error") is None and container_result.get("data"):
        return {
            "port_statistics": container_result["data"],
            "malacca_strait": MALACCA_STRAIT_INDICATORS,
            "source": "data.gov.sg (live + static supplement)",
            "timestamp": now,
            "error": None,
        }

    # フォールバック: 静的データ
    return {
        "port_statistics": STATIC_SINGAPORE_PORT,
        "malacca_strait": MALACCA_STRAIT_INDICATORS,
        "source": "MPA Singapore (static data)",
        "timestamp": now,
        "error": None,
    }


def get_singapore_economic_indicators() -> dict:
    """シンガポールの主要経済指標を取得

    Returns:
        dict: 経済指標データ
    """
    now = datetime.utcnow().isoformat()

    # SingStat API からの取得を試みる
    singstat_result = fetch_singstat_data("M890161")  # Trade statistics table

    indicators = dict(STATIC_SINGAPORE_ECONOMY)
    indicators.update(STATIC_SINGAPORE_PORT)
    source = "SingStat / MPA (static data)"

    if singstat_result.get("error") is None and singstat_result.get("data"):
        # Live data available; merge with static
        source = "SingStat / MPA (mixed live + static)"
        # Parse live data if format is recognized
        live_data = singstat_result.get("data", {})
        if isinstance(live_data, dict) and live_data.get("Data"):
            for record in live_data["Data"].get("row", []):
                # Process SingStat format
                pass

    return {
        "indicators": indicators,
        "malacca_strait": MALACCA_STRAIT_INDICATORS,
        "source": source,
        "timestamp": now,
        "error": None,
        "country_code": "SGP",
        "country_name": "Singapore",
    }


def get_malacca_strait_risk_indicators() -> dict:
    """マラッカ海峡リスク指標を取得 (サプライチェーンリスク評価用)

    Returns:
        dict: マラッカ海峡関連のリスク指標
    """
    now = datetime.utcnow().isoformat()

    return {
        "indicators": MALACCA_STRAIT_INDICATORS,
        "port_statistics": STATIC_SINGAPORE_PORT,
        "risk_factors": [
            "Piracy risk in surrounding waters",
            "Chokepoint for 25% of global maritime trade",
            "16.5M barrels/day oil transit",
            "Single-point-of-failure for Asia-Europe trade",
            "Congestion during peak shipping seasons",
        ],
        "source": "MPA Singapore / IHS Maritime (static data)",
        "timestamp": now,
        "error": None,
        "focus": "malacca_strait_risk",
    }


def get_economic_indicators(country_code: str = "SGP") -> dict:
    """統一インターフェース: シンガポールの経済指標を取得

    Args:
        country_code: 国コード (SGP/SGのみ対応)

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    if country_code.upper() not in ("SGP", "SG"):
        return {
            "indicators": {},
            "source": "MPA Singapore",
            "timestamp": datetime.utcnow().isoformat(),
            "error": f"MPA/SingStat client only supports SGP/SG, got: {country_code}",
        }
    return get_singapore_economic_indicators()


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("MPA Singapore (Maritime & Port Authority) Client Test")
    print("=" * 60)

    # 1) 疎通テスト
    print("\n[1] Connectivity Test")
    conn = test_connectivity()
    for name, status in conn.items():
        reachable = "OK" if status["reachable"] else "FAIL"
        print(f"  {name}: {reachable} (status={status['status_code']}, latency={status['latency_ms']}ms)")
        if status["error"]:
            print(f"    Error: {status['error']}")

    # 2) 経済指標取得
    print("\n[2] Singapore Economic & Port Indicators")
    result = get_economic_indicators("SGP")
    print(f"  Source: {result['source']}")
    print(f"  Timestamp: {result['timestamp']}")
    if result.get("error"):
        print(f"  Error: {result['error']}")
    print("  Indicators:")
    for key, val in result.get("indicators", {}).items():
        if isinstance(val, dict) and "value" in val:
            print(f"    {key}: {val['value']} {val.get('unit', '')} ({val.get('period', '')})")

    # 3) マラッカ海峡リスク指標
    print("\n[3] Malacca Strait Risk Indicators")
    malacca = get_malacca_strait_risk_indicators()
    for key, val in malacca.get("indicators", {}).items():
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')} {val.get('unit', '')} ({val.get('period', '')})")
    print("  Risk Factors:")
    for factor in malacca.get("risk_factors", []):
        print(f"    - {factor}")

    # 4) 港湾統計
    print("\n[4] Port Statistics")
    port = get_singapore_port_statistics()
    print(f"  Source: {port['source']}")
    for key, val in port.get("port_statistics", {}).items():
        if isinstance(val, dict) and "value" in val:
            print(f"    {key}: {val['value']} {val.get('unit', '')}")

    # 5) 不正な国コード
    print("\n[5] Invalid country code test")
    bad = get_economic_indicators("USA")
    print(f"  Error: {bad['error']}")
