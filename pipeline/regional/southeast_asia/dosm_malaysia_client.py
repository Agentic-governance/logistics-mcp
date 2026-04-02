"""マレーシア統計局(DOSM) OpenDOSM クライアント
Department of Statistics Malaysia - マレーシアの主要経済統計データを取得
APIキー不要
https://open.dosm.gov.my/
https://api.data.gov.my/data-catalogue
"""
import requests
import time
from datetime import datetime
from typing import Optional

DOSM_API_BASE = "https://api.data.gov.my/data-catalogue"
OPEN_DOSM_BASE = "https://open.dosm.gov.my"

# OpenDOSM データセットID
DOSM_DATASETS = {
    "trade_monthly": "trade_monthly",
    "ipi": "ipi",  # Industrial Production Index
    "cpi": "cpi",  # Consumer Price Index
    "lfs": "lfs_month",  # Labour Force Survey
    "gdp_quarterly": "gdp_qtr",
}

# マレーシアの主要経済指標 (2024年実績ベース静的データ)
STATIC_MALAYSIA_DATA = {
    "gdp_growth": {
        "value": 5.1,
        "unit": "percent",
        "period": "2024",
        "description": "GDP Growth Rate",
    },
    "total_exports_usd_bn": {
        "value": 330.8,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Exports",
    },
    "total_imports_usd_bn": {
        "value": 285.4,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Imports",
    },
    "trade_balance_usd_bn": {
        "value": 45.4,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Trade Balance (Surplus)",
    },
    "manufacturing_pmi": {
        "value": 49.5,
        "unit": "index",
        "period": "2024-12",
        "description": "Manufacturing PMI (S&P Global)",
    },
    "cpi_yoy": {
        "value": 1.8,
        "unit": "percent",
        "period": "2024",
        "description": "CPI Year-over-Year",
    },
    "industrial_production_yoy": {
        "value": 4.2,
        "unit": "percent",
        "period": "2024-Q4",
        "description": "Industrial Production Index YoY Growth",
    },
    "unemployment_rate": {
        "value": 3.2,
        "unit": "percent",
        "period": "2024-Q4",
        "description": "Unemployment Rate",
    },
    "fdi_inflow_usd_bn": {
        "value": 13.8,
        "unit": "billion_usd",
        "period": "2024",
        "description": "FDI Inflow",
    },
    "electronics_exports_usd_bn": {
        "value": 118.5,
        "unit": "billion_usd",
        "period": "2024",
        "description": "E&E Exports (Electrical & Electronics)",
    },
    "electronics_export_share_pct": {
        "value": 35.8,
        "unit": "percent",
        "period": "2024",
        "description": "E&E Share of Total Exports",
    },
    "palm_oil_exports_usd_bn": {
        "value": 25.2,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Palm Oil & Products Exports",
    },
    "petroleum_exports_usd_bn": {
        "value": 34.6,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Petroleum Products Exports",
    },
}

# 主要貿易相手国
MALAYSIA_TRADE_PARTNERS = {
    "CHN": {"name": "China", "exports_share_pct": 15.8, "imports_share_pct": 22.1},
    "SGP": {"name": "Singapore", "exports_share_pct": 14.2, "imports_share_pct": 9.8},
    "USA": {"name": "United States", "exports_share_pct": 11.5, "imports_share_pct": 7.2},
    "JPN": {"name": "Japan", "exports_share_pct": 6.8, "imports_share_pct": 7.5},
    "KOR": {"name": "South Korea", "exports_share_pct": 4.2, "imports_share_pct": 5.1},
    "TWN": {"name": "Taiwan", "exports_share_pct": 3.9, "imports_share_pct": 6.8},
    "THA": {"name": "Thailand", "exports_share_pct": 5.1, "imports_share_pct": 5.5},
    "IDN": {"name": "Indonesia", "exports_share_pct": 4.5, "imports_share_pct": 5.2},
}


def test_connectivity() -> dict:
    """OpenDOSM APIサーバーへの疎通テストを実施

    Returns:
        dict: 接続結果
    """
    endpoints = [
        ("OpenDOSM API", f"{DOSM_API_BASE}?id=trade_monthly&limit=1"),
        ("OpenDOSM Portal", f"{OPEN_DOSM_BASE}/"),
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


def fetch_dosm_data(
    dataset_id: str,
    limit: int = 100,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> dict:
    """OpenDOSM APIからデータを取得

    Args:
        dataset_id: データセットID (e.g., "trade_monthly")
        limit: 取得件数上限
        date_start: 開始日 (YYYY-MM-DD)
        date_end: 終了日 (YYYY-MM-DD)

    Returns:
        dict: APIレスポンスまたはエラー
    """
    now = datetime.utcnow().isoformat()

    params: dict = {
        "id": dataset_id,
        "limit": limit,
    }
    if date_start:
        params["date_start"] = date_start
    if date_end:
        params["date_end"] = date_end

    try:
        resp = requests.get(DOSM_API_BASE, params=params, timeout=20)
        resp.raise_for_status()

        data = resp.json()

        if isinstance(data, dict) and data.get("error"):
            return {
                "error": f"OpenDOSM API error: {data.get('error')}",
                "source": "OpenDOSM",
                "timestamp": now,
            }

        return {
            "data": data,
            "source": "OpenDOSM (live API)",
            "timestamp": now,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"OpenDOSM API request failed: {str(e)}",
            "source": "OpenDOSM",
            "timestamp": now,
        }
    except ValueError as e:
        return {
            "error": f"OpenDOSM response parse error: {str(e)}",
            "source": "OpenDOSM",
            "timestamp": now,
        }


def get_malaysia_trade_data() -> dict:
    """マレーシアの月次貿易データを取得

    Returns:
        dict: 貿易統計データ
    """
    now = datetime.utcnow().isoformat()

    result = fetch_dosm_data("trade_monthly", limit=12)

    if result.get("error") is None and result.get("data"):
        data = result["data"]
        # OpenDOSM returns list of records
        if isinstance(data, list) and len(data) > 0:
            return {
                "data": data,
                "source": "OpenDOSM (live API)",
                "timestamp": now,
                "error": None,
            }

    # フォールバック
    return {
        "data": {
            "total_exports_usd_bn": STATIC_MALAYSIA_DATA["total_exports_usd_bn"],
            "total_imports_usd_bn": STATIC_MALAYSIA_DATA["total_imports_usd_bn"],
            "trade_balance_usd_bn": STATIC_MALAYSIA_DATA["trade_balance_usd_bn"],
            "electronics_exports_usd_bn": STATIC_MALAYSIA_DATA["electronics_exports_usd_bn"],
        },
        "source": "OpenDOSM (static fallback)",
        "timestamp": now,
        "error": None,
    }


def get_malaysia_economic_indicators() -> dict:
    """マレーシアの主要経済指標を取得

    OpenDOSM APIからリアルタイムデータを試行、失敗時は静的データにフォールバック。

    Returns:
        dict: 経済指標データ
    """
    now = datetime.utcnow().isoformat()
    indicators: dict = {}
    api_available = False

    # Try fetching live data from OpenDOSM
    for key, dataset_id in DOSM_DATASETS.items():
        result = fetch_dosm_data(dataset_id, limit=1)
        if result.get("error") is None and result.get("data"):
            data = result["data"]
            if isinstance(data, list) and len(data) > 0:
                latest = data[-1]
                indicators[f"{key}_latest"] = latest
                api_available = True

    if api_available:
        # Merge static data for indicators not available from API
        for key, val in STATIC_MALAYSIA_DATA.items():
            if key not in indicators:
                indicators[key] = val

        return {
            "indicators": indicators,
            "trade_partners": MALAYSIA_TRADE_PARTNERS,
            "source": "OpenDOSM (mixed live + static)",
            "timestamp": now,
            "error": None,
            "country_code": "MYS",
            "country_name": "Malaysia",
        }

    # Full fallback to static data
    return {
        "indicators": STATIC_MALAYSIA_DATA,
        "trade_partners": MALAYSIA_TRADE_PARTNERS,
        "source": "OpenDOSM (static fallback)",
        "timestamp": now,
        "error": None,
        "country_code": "MYS",
        "country_name": "Malaysia",
    }


def get_economic_indicators(country_code: str = "MYS") -> dict:
    """統一インターフェース: マレーシアの経済指標を取得

    Args:
        country_code: 国コード (MYS/MYのみ対応)

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    if country_code.upper() not in ("MYS", "MY"):
        return {
            "indicators": {},
            "source": "OpenDOSM",
            "timestamp": datetime.utcnow().isoformat(),
            "error": f"DOSM client only supports MYS/MY, got: {country_code}",
        }
    return get_malaysia_economic_indicators()


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("DOSM Malaysia (OpenDOSM) Client Test")
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
    print("\n[2] Malaysia Economic Indicators")
    result = get_economic_indicators("MYS")
    print(f"  Source: {result['source']}")
    print(f"  Timestamp: {result['timestamp']}")
    if result.get("error"):
        print(f"  Error: {result['error']}")
    print("  Indicators:")
    for key, val in result.get("indicators", {}).items():
        if isinstance(val, dict) and "value" in val:
            print(f"    {key}: {val['value']} {val.get('unit', '')} ({val.get('period', '')})")

    # 3) 貿易相手国
    print("\n[3] Trade Partners")
    for code, partner in result.get("trade_partners", {}).items():
        print(f"    {code} ({partner['name']}): Export {partner['exports_share_pct']}%, Import {partner['imports_share_pct']}%")

    # 4) 貿易データ
    print("\n[4] Trade Data (fetch)")
    trade = get_malaysia_trade_data()
    print(f"  Source: {trade['source']}")

    # 5) 不正な国コード
    print("\n[5] Invalid country code test")
    bad = get_economic_indicators("USA")
    print(f"  Error: {bad['error']}")
