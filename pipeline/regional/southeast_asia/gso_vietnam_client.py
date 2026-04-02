"""ベトナム統計総局(GSO) クライアント
General Statistics Office of Vietnam - ベトナムの主要経済統計データを取得
APIキー不要
https://www.gso.gov.vn/en/data-and-statistics/
https://data.gso.gov.vn/ (data portal)
"""
import requests
import time
from datetime import datetime
from typing import Optional

GSO_BASE = "https://www.gso.gov.vn"
GSO_DATA_PORTAL = "https://data.gso.gov.vn"

# ベトナムの主要経済指標 (2024年実績ベース静的データ)
STATIC_VIETNAM_DATA = {
    "gdp_growth": {
        "value": 7.09,
        "unit": "percent",
        "period": "2024",
        "description": "GDP Growth Rate",
    },
    "manufacturing_growth": {
        "value": 8.4,
        "unit": "percent",
        "period": "2024",
        "description": "Manufacturing Sector Growth",
    },
    "total_exports_usd_bn": {
        "value": 405.5,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Exports",
    },
    "total_imports_usd_bn": {
        "value": 380.2,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Imports",
    },
    "trade_balance_usd_bn": {
        "value": 25.3,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Trade Balance (Surplus)",
    },
    "fdi_registered_usd_bn": {
        "value": 38.2,
        "unit": "billion_usd",
        "period": "2024",
        "description": "FDI Registered Capital",
    },
    "fdi_disbursed_usd_bn": {
        "value": 25.4,
        "unit": "billion_usd",
        "period": "2024",
        "description": "FDI Disbursed Capital",
    },
    "cpi_yoy": {
        "value": 3.6,
        "unit": "percent",
        "period": "2024",
        "description": "CPI Year-over-Year",
    },
    "industrial_production_yoy": {
        "value": 8.3,
        "unit": "percent",
        "period": "2024",
        "description": "Industrial Production Index YoY Growth",
    },
    "unemployment_rate": {
        "value": 2.1,
        "unit": "percent",
        "period": "2024-Q4",
        "description": "Unemployment Rate",
    },
    "labor_force_million": {
        "value": 52.5,
        "unit": "million_persons",
        "period": "2024",
        "description": "Labor Force",
    },
    "minimum_wage_usd_month": {
        "value": 207,
        "unit": "usd_per_month",
        "period": "2024",
        "description": "Minimum Wage (Region I, highest tier)",
    },
}

# ベトナムの主要輸出品目
VIETNAM_KEY_EXPORTS = {
    "electronics": {
        "value_usd_bn": 132.8,
        "share_pct": 32.7,
        "description": "Electronics & Components (phones, computers)",
        "period": "2024",
    },
    "textiles_garments": {
        "value_usd_bn": 44.5,
        "share_pct": 11.0,
        "description": "Textiles & Garments",
        "period": "2024",
    },
    "footwear": {
        "value_usd_bn": 24.8,
        "share_pct": 6.1,
        "description": "Footwear",
        "period": "2024",
    },
    "machinery": {
        "value_usd_bn": 52.3,
        "share_pct": 12.9,
        "description": "Machinery & Equipment",
        "period": "2024",
    },
    "wood_products": {
        "value_usd_bn": 16.2,
        "share_pct": 4.0,
        "description": "Wood & Wood Products",
        "period": "2024",
    },
    "seafood": {
        "value_usd_bn": 10.2,
        "share_pct": 2.5,
        "description": "Seafood (shrimp, pangasius)",
        "period": "2024",
    },
}

# 主要FDI投資国
VIETNAM_FDI_SOURCES = {
    "KOR": {"name": "South Korea", "share_pct": 17.8, "cumulative_usd_bn": 86.5},
    "SGP": {"name": "Singapore", "share_pct": 15.2, "cumulative_usd_bn": 73.8},
    "JPN": {"name": "Japan", "share_pct": 13.1, "cumulative_usd_bn": 71.4},
    "TWN": {"name": "Taiwan", "share_pct": 7.8, "cumulative_usd_bn": 38.2},
    "HKG": {"name": "Hong Kong", "share_pct": 6.5, "cumulative_usd_bn": 31.5},
    "CHN": {"name": "China", "share_pct": 5.9, "cumulative_usd_bn": 28.7},
}


def test_connectivity() -> dict:
    """GSO APIサーバーへの疎通テストを実施

    Returns:
        dict: 接続結果
    """
    endpoints = [
        ("GSO Main Site", f"{GSO_BASE}/en/data-and-statistics/"),
        ("GSO Data Portal", f"{GSO_DATA_PORTAL}/"),
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


def fetch_gso_data(endpoint: str = "/api/data") -> dict:
    """GSOデータポータルからデータ取得を試行

    Args:
        endpoint: APIエンドポイントパス

    Returns:
        dict: APIレスポンスまたはエラー
    """
    now = datetime.utcnow().isoformat()
    url = f"{GSO_DATA_PORTAL}{endpoint}"

    try:
        resp = requests.get(url, timeout=15, allow_redirects=True)
        resp.raise_for_status()

        # Check if response is JSON
        content_type = resp.headers.get("Content-Type", "")
        if "json" in content_type or "javascript" in content_type:
            data = resp.json()
            return {
                "data": data,
                "source": "GSO Vietnam Data Portal (live)",
                "timestamp": now,
                "error": None,
            }
        else:
            return {
                "error": "GSO data portal returned non-JSON response (likely HTML page)",
                "source": "GSO Vietnam",
                "timestamp": now,
            }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"GSO API request failed: {str(e)}",
            "source": "GSO Vietnam",
            "timestamp": now,
        }
    except ValueError as e:
        return {
            "error": f"GSO response parse error: {str(e)}",
            "source": "GSO Vietnam",
            "timestamp": now,
        }


def get_vietnam_economic_indicators() -> dict:
    """ベトナムの主要経済指標を取得

    APIが利用可能な場合はリアルタイムデータ、不可の場合は静的データを返す。

    Returns:
        dict: 経済指標データ
    """
    now = datetime.utcnow().isoformat()

    # GSOデータポータルAPI接続を試みる
    api_result = fetch_gso_data()

    if api_result.get("error") is None and api_result.get("data"):
        return {
            "indicators": api_result["data"],
            "source": "GSO Vietnam (live API)",
            "timestamp": now,
            "error": None,
            "country_code": "VNM",
            "country_name": "Vietnam",
        }

    # フォールバック: 静的データ
    return {
        "indicators": STATIC_VIETNAM_DATA,
        "key_exports": VIETNAM_KEY_EXPORTS,
        "fdi_sources": VIETNAM_FDI_SOURCES,
        "source": "GSO Vietnam (static data)",
        "timestamp": now,
        "error": None,
        "country_code": "VNM",
        "country_name": "Vietnam",
    }


def get_vietnam_manufacturing_profile() -> dict:
    """ベトナム製造業プロファイル (サプライチェーンリスク評価用)

    Returns:
        dict: 製造業関連データ
    """
    now = datetime.utcnow().isoformat()

    profile = {
        "manufacturing_growth": STATIC_VIETNAM_DATA["manufacturing_growth"],
        "industrial_production_yoy": STATIC_VIETNAM_DATA["industrial_production_yoy"],
        "labor_force_million": STATIC_VIETNAM_DATA["labor_force_million"],
        "minimum_wage_usd_month": STATIC_VIETNAM_DATA["minimum_wage_usd_month"],
        "unemployment_rate": STATIC_VIETNAM_DATA["unemployment_rate"],
        "fdi_registered_usd_bn": STATIC_VIETNAM_DATA["fdi_registered_usd_bn"],
        "fdi_disbursed_usd_bn": STATIC_VIETNAM_DATA["fdi_disbursed_usd_bn"],
        "key_manufacturing_exports": {
            "electronics": VIETNAM_KEY_EXPORTS["electronics"],
            "textiles_garments": VIETNAM_KEY_EXPORTS["textiles_garments"],
            "footwear": VIETNAM_KEY_EXPORTS["footwear"],
            "machinery": VIETNAM_KEY_EXPORTS["machinery"],
        },
        "supply_chain_advantages": [
            "Low labor costs (minimum wage ~$207/month Region I)",
            "Young workforce (median age ~32)",
            "Growing electronics manufacturing cluster (Samsung, etc.)",
            "Multiple FTAs (CPTPP, EVFTA, RCEP)",
            "Strategic location for China+1 diversification",
        ],
        "supply_chain_risks": [
            "Infrastructure bottlenecks (ports, logistics)",
            "Skilled labor shortage in advanced manufacturing",
            "Typhoon exposure (Central coast)",
            "Power supply constraints during peak demand",
            "Regulatory complexity for foreign investors",
        ],
    }

    return {
        "indicators": profile,
        "source": "GSO Vietnam (static data)",
        "timestamp": now,
        "error": None,
        "country_code": "VNM",
        "focus": "manufacturing_profile",
    }


def get_economic_indicators(country_code: str = "VNM") -> dict:
    """統一インターフェース: ベトナムの経済指標を取得

    Args:
        country_code: 国コード (VNM/VNのみ対応)

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    if country_code.upper() not in ("VNM", "VN"):
        return {
            "indicators": {},
            "source": "GSO Vietnam",
            "timestamp": datetime.utcnow().isoformat(),
            "error": f"GSO client only supports VNM/VN, got: {country_code}",
        }
    return get_vietnam_economic_indicators()


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("GSO Vietnam (General Statistics Office) Client Test")
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
    print("\n[2] Vietnam Economic Indicators")
    result = get_economic_indicators("VNM")
    print(f"  Source: {result['source']}")
    print(f"  Timestamp: {result['timestamp']}")
    if result.get("error"):
        print(f"  Error: {result['error']}")
    print("  Indicators:")
    for key, val in result.get("indicators", {}).items():
        if isinstance(val, dict) and "value" in val:
            print(f"    {key}: {val['value']} {val.get('unit', '')} ({val.get('period', '')})")

    # 3) 製造業プロファイル
    print("\n[3] Vietnam Manufacturing Profile")
    mfg = get_vietnam_manufacturing_profile()
    print(f"  Source: {mfg['source']}")
    indicators = mfg.get("indicators", {})
    for key in ["manufacturing_growth", "labor_force_million", "minimum_wage_usd_month"]:
        val = indicators.get(key, {})
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')} {val.get('unit', '')}")

    # 4) 主要輸出品目
    print("\n[4] Key Exports")
    for key, val in result.get("key_exports", {}).items():
        print(f"    {key}: ${val['value_usd_bn']}B ({val['share_pct']}%)")

    # 5) 不正な国コード
    print("\n[5] Invalid country code test")
    bad = get_economic_indicators("USA")
    print(f"  Error: {bad['error']}")
