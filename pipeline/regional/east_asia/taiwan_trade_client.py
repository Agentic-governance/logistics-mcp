"""台湾財政部関税署 貿易統計クライアント
Taiwan Bureau of Trade / Customs Administration trade statistics
APIキー不要

台湾の貿易統計データを取得。APIが利用不可の場合は静的データにフォールバック。
半導体貿易 (HS84/85) に特にフォーカス。
"""
import requests
import time
from datetime import datetime
from typing import Optional

# Taiwan trade data endpoints
TAIWAN_CUSTOMS_BASE = "https://portal.sw.nat.gov.tw"
TAIWAN_OPENDATA_BASE = "https://data.gov.tw/api/v2/rest/datastore"
TAIWAN_STAT_BASE = "https://statdb.dgbas.gov.tw"

# 台湾の主要貿易データ (2024年実績ベース静的データ)
STATIC_TAIWAN_TRADE = {
    "total_exports_usd_bn": {
        "value": 478.2,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Exports",
    },
    "total_imports_usd_bn": {
        "value": 388.6,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Imports",
    },
    "trade_balance_usd_bn": {
        "value": 89.6,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Trade Balance (Surplus)",
    },
    "semiconductor_exports_usd_bn": {
        "value": 203.5,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Semiconductor & IC Exports (HS8541/8542)",
    },
    "semiconductor_share_pct": {
        "value": 42.6,
        "unit": "percent",
        "period": "2024",
        "description": "Semiconductor Share of Total Exports",
    },
    "ict_exports_usd_bn": {
        "value": 289.4,
        "unit": "billion_usd",
        "period": "2024",
        "description": "ICT Products Exports (HS84+85)",
    },
    "gdp_growth": {
        "value": 3.9,
        "unit": "percent",
        "period": "2024",
        "description": "GDP Growth Rate",
    },
    "cpi_yoy": {
        "value": 2.2,
        "unit": "percent",
        "period": "2024",
        "description": "CPI Year-over-Year",
    },
    "unemployment_rate": {
        "value": 3.4,
        "unit": "percent",
        "period": "2024-Q4",
        "description": "Unemployment Rate",
    },
    "industrial_production_yoy": {
        "value": 12.5,
        "unit": "percent",
        "period": "2024-Q4",
        "description": "Industrial Production YoY Growth",
    },
}

# 台湾の主要貿易相手国 (2024年)
TAIWAN_TRADE_PARTNERS = {
    "CHN": {
        "exports_usd_bn": 112.4,
        "imports_usd_bn": 65.3,
        "share_pct": 23.5,
        "name": "China (incl. Hong Kong)",
    },
    "USA": {
        "exports_usd_bn": 80.1,
        "imports_usd_bn": 42.7,
        "share_pct": 16.7,
        "name": "United States",
    },
    "JPN": {
        "exports_usd_bn": 31.2,
        "imports_usd_bn": 48.9,
        "share_pct": 6.5,
        "name": "Japan",
    },
    "KOR": {
        "exports_usd_bn": 24.8,
        "imports_usd_bn": 28.1,
        "share_pct": 5.2,
        "name": "South Korea",
    },
    "SGP": {
        "exports_usd_bn": 28.5,
        "imports_usd_bn": 15.2,
        "share_pct": 6.0,
        "name": "Singapore",
    },
    "DEU": {
        "exports_usd_bn": 12.3,
        "imports_usd_bn": 14.8,
        "share_pct": 2.6,
        "name": "Germany",
    },
}

# 半導体サプライチェーン指標
SEMICONDUCTOR_SUPPLY_CHAIN = {
    "tsmc_global_foundry_share_pct": {
        "value": 61.7,
        "period": "2024-Q4",
        "description": "TSMC Global Foundry Market Share",
    },
    "advanced_node_share_pct": {
        "value": 92.0,
        "period": "2024",
        "description": "Taiwan Share of Advanced Nodes (<10nm)",
    },
    "ic_design_exports_usd_bn": {
        "value": 48.2,
        "period": "2024",
        "description": "IC Design Sector Exports",
    },
    "ic_packaging_exports_usd_bn": {
        "value": 22.1,
        "period": "2024",
        "description": "IC Packaging & Testing Exports",
    },
    "equipment_imports_usd_bn": {
        "value": 31.8,
        "period": "2024",
        "description": "Semiconductor Equipment Imports",
    },
}


def test_connectivity() -> dict:
    """台湾政府統計サイトへの疎通テストを実施

    Returns:
        dict: 接続結果
    """
    endpoints = [
        ("Taiwan Customs Portal", "https://web.customs.gov.tw/en/"),
        ("Taiwan Open Data", "https://data.gov.tw/"),
        ("DGBAS Statistics", "https://statdb.dgbas.gov.tw/"),
    ]

    results: dict = {}
    for name, url in endpoints:
        start = time.time()
        try:
            resp = requests.get(url, timeout=10, allow_redirects=True)
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


def fetch_taiwan_opendata(dataset_id: str) -> dict:
    """台湾オープンデータプラットフォームからデータ取得を試行

    Args:
        dataset_id: データセットID

    Returns:
        dict: APIレスポンスまたはエラー
    """
    now = datetime.utcnow().isoformat()
    url = f"{TAIWAN_OPENDATA_BASE}/{dataset_id}"
    params = {"format": "json", "limit": 100}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {
            "data": data,
            "source": "Taiwan Open Data Platform",
            "timestamp": now,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"Taiwan Open Data API request failed: {str(e)}",
            "source": "Taiwan Open Data Platform",
            "timestamp": now,
        }
    except ValueError as e:
        return {
            "error": f"Response parse error: {str(e)}",
            "source": "Taiwan Open Data Platform",
            "timestamp": now,
        }


def get_taiwan_trade_statistics() -> dict:
    """台湾の貿易統計を取得

    Returns:
        dict: 貿易統計データ
    """
    now = datetime.utcnow().isoformat()

    # まずAPIからの取得を試みる
    api_result = fetch_taiwan_opendata("349130000C-000591-001")  # trade statistics dataset

    if api_result.get("error") is None and api_result.get("data"):
        # API成功時はライブデータを使用
        return {
            "indicators": api_result["data"],
            "source": "Taiwan Open Data Platform (live)",
            "timestamp": now,
            "error": None,
            "country_code": "TWN",
            "country_name": "Taiwan",
        }

    # フォールバック: 静的データを返す
    return {
        "indicators": STATIC_TAIWAN_TRADE,
        "trade_partners": TAIWAN_TRADE_PARTNERS,
        "semiconductor_supply_chain": SEMICONDUCTOR_SUPPLY_CHAIN,
        "source": "Taiwan Bureau of Trade (static data)",
        "timestamp": now,
        "error": None,
        "country_code": "TWN",
        "country_name": "Taiwan",
    }


def get_semiconductor_trade_indicators() -> dict:
    """台湾の半導体貿易指標を取得 (サプライチェーンリスク評価用)

    Returns:
        dict: 半導体関連指標
    """
    now = datetime.utcnow().isoformat()

    semiconductor_data = {
        "semiconductor_exports_usd_bn": STATIC_TAIWAN_TRADE["semiconductor_exports_usd_bn"],
        "semiconductor_share_pct": STATIC_TAIWAN_TRADE["semiconductor_share_pct"],
        "ict_exports_usd_bn": STATIC_TAIWAN_TRADE["ict_exports_usd_bn"],
    }
    semiconductor_data.update(SEMICONDUCTOR_SUPPLY_CHAIN)

    return {
        "indicators": semiconductor_data,
        "source": "Taiwan Trade Statistics (static data)",
        "timestamp": now,
        "error": None,
        "country_code": "TWN",
        "focus": "semiconductor_supply_chain",
    }


def get_trade_with_partner(partner_code: str) -> dict:
    """特定の貿易相手国との貿易データを取得

    Args:
        partner_code: 相手国のISO3コード (e.g., "JPN", "USA")

    Returns:
        dict: 二国間貿易データ
    """
    now = datetime.utcnow().isoformat()
    code = partner_code.upper()

    if code in TAIWAN_TRADE_PARTNERS:
        partner = TAIWAN_TRADE_PARTNERS[code]
        return {
            "indicators": {
                "partner_name": partner["name"],
                "partner_code": code,
                "exports_usd_bn": partner["exports_usd_bn"],
                "imports_usd_bn": partner["imports_usd_bn"],
                "trade_share_pct": partner["share_pct"],
                "trade_balance_usd_bn": round(
                    partner["exports_usd_bn"] - partner["imports_usd_bn"], 1
                ),
            },
            "source": "Taiwan Trade Statistics (static data)",
            "timestamp": now,
            "error": None,
        }

    return {
        "indicators": {},
        "source": "Taiwan Trade Statistics",
        "timestamp": now,
        "error": f"No trade data available for partner: {partner_code}",
    }


def get_economic_indicators(country_code: str = "TWN") -> dict:
    """統一インターフェース: 台湾の経済指標を取得

    Args:
        country_code: 国コード (TWN/TWのみ対応)

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    if country_code.upper() not in ("TWN", "TW"):
        return {
            "indicators": {},
            "source": "Taiwan Trade Statistics",
            "timestamp": datetime.utcnow().isoformat(),
            "error": f"Taiwan trade client only supports TWN/TW, got: {country_code}",
        }
    return get_taiwan_trade_statistics()


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("Taiwan Trade Statistics Client Test")
    print("=" * 60)

    # 1) 疎通テスト
    print("\n[1] Connectivity Test")
    conn = test_connectivity()
    for name, status in conn.items():
        reachable = "OK" if status["reachable"] else "FAIL"
        print(f"  {name}: {reachable} (status={status['status_code']}, latency={status['latency_ms']}ms)")
        if status["error"]:
            print(f"    Error: {status['error']}")

    # 2) 貿易統計
    print("\n[2] Taiwan Trade Statistics")
    result = get_economic_indicators("TWN")
    print(f"  Source: {result['source']}")
    print(f"  Timestamp: {result['timestamp']}")
    if result.get("error"):
        print(f"  Error: {result['error']}")
    for key, val in result.get("indicators", {}).items():
        if isinstance(val, dict) and "value" in val:
            print(f"    {key}: {val['value']} {val.get('unit', '')} ({val.get('period', '')})")

    # 3) 半導体貿易指標
    print("\n[3] Semiconductor Trade Indicators")
    semi = get_semiconductor_trade_indicators()
    for key, val in semi.get("indicators", {}).items():
        if isinstance(val, dict) and "value" in val:
            print(f"    {key}: {val['value']} ({val.get('period', '')})")

    # 4) 対日貿易
    print("\n[4] Taiwan-Japan Trade")
    jpn = get_trade_with_partner("JPN")
    for key, val in jpn.get("indicators", {}).items():
        print(f"    {key}: {val}")

    # 5) 不正な国コード
    print("\n[5] Invalid country code test")
    bad = get_economic_indicators("USA")
    print(f"  Error: {bad['error']}")
