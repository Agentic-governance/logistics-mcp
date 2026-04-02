"""中国国家統計局(NBS) クライアント
National Bureau of Statistics of China - 中国の主要経済統計データを取得
APIキー不要(セッションベース)
https://data.stats.gov.cn/english/easyquery.htm

Rate limit: 1 req/sec (time.sleep で制御)
"""
import requests
import time
from datetime import datetime
from typing import Optional

NBS_BASE = "https://data.stats.gov.cn/english/easyquery.htm"

# NBS indicator codes (zb=指標コード)
NBS_INDICATORS = {
    "pmi_manufacturing": {
        "dbcode": "hgyd",
        "zb_code": "A0B01",
        "description": "Manufacturing PMI",
    },
    "pmi_non_manufacturing": {
        "dbcode": "hgyd",
        "zb_code": "A0B02",
        "description": "Non-Manufacturing PMI",
    },
    "industrial_production": {
        "dbcode": "hgyd",
        "zb_code": "A020101",
        "description": "Industrial Value Added YoY Growth (%)",
    },
    "total_exports": {
        "dbcode": "hgyd",
        "zb_code": "A0802",
        "description": "Total Exports (USD 100 million)",
    },
    "total_imports": {
        "dbcode": "hgyd",
        "zb_code": "A0803",
        "description": "Total Imports (USD 100 million)",
    },
    "cpi": {
        "dbcode": "hgyd",
        "zb_code": "A010101",
        "description": "CPI Year-over-Year (%)",
    },
    "ppi": {
        "dbcode": "hgyd",
        "zb_code": "A010301",
        "description": "PPI Year-over-Year (%)",
    },
    "fixed_asset_investment": {
        "dbcode": "hgyd",
        "zb_code": "A0501",
        "description": "Fixed Asset Investment YoY Growth (%)",
    },
    "retail_sales": {
        "dbcode": "hgyd",
        "zb_code": "A0701",
        "description": "Retail Sales YoY Growth (%)",
    },
    "fdi_utilized": {
        "dbcode": "hgyd",
        "zb_code": "A0901",
        "description": "FDI Actually Utilized (USD 100 million)",
    },
}

# 最新の静的フォールバックデータ (2024年実績)
STATIC_CHINA_DATA = {
    "pmi_manufacturing": {
        "value": 50.1,
        "unit": "index",
        "period": "2024-12",
        "description": "Manufacturing PMI",
    },
    "pmi_non_manufacturing": {
        "value": 52.2,
        "unit": "index",
        "period": "2024-12",
        "description": "Non-Manufacturing PMI",
    },
    "industrial_production_yoy": {
        "value": 5.8,
        "unit": "percent",
        "period": "2024",
        "description": "Industrial Value Added YoY Growth",
    },
    "total_exports_usd_bn": {
        "value": 3577.0,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Exports",
    },
    "total_imports_usd_bn": {
        "value": 2592.0,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Imports",
    },
    "trade_balance_usd_bn": {
        "value": 985.0,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Trade Balance (Surplus)",
    },
    "cpi_yoy": {
        "value": 0.2,
        "unit": "percent",
        "period": "2024",
        "description": "CPI Year-over-Year",
    },
    "ppi_yoy": {
        "value": -2.2,
        "unit": "percent",
        "period": "2024",
        "description": "PPI Year-over-Year",
    },
    "gdp_growth": {
        "value": 5.0,
        "unit": "percent",
        "period": "2024",
        "description": "GDP Growth Rate",
    },
    "fixed_asset_investment_yoy": {
        "value": 3.2,
        "unit": "percent",
        "period": "2024",
        "description": "Fixed Asset Investment YoY Growth",
    },
    "retail_sales_yoy": {
        "value": 3.5,
        "unit": "percent",
        "period": "2024",
        "description": "Retail Sales YoY Growth",
    },
    "fdi_utilized_usd_bn": {
        "value": 98.7,
        "unit": "billion_usd",
        "period": "2024",
        "description": "FDI Actually Utilized",
    },
    "unemployment_rate": {
        "value": 5.1,
        "unit": "percent",
        "period": "2024-12",
        "description": "Surveyed Urban Unemployment Rate",
    },
}

# NBS APIへのリクエスト間隔 (秒)
_last_request_time: float = 0.0
RATE_LIMIT_SECONDS: float = 1.0


def _rate_limit() -> None:
    """レートリミット制御: 前回リクエストから1秒以上空ける"""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


def test_connectivity() -> dict:
    """NBS APIサーバーへの疎通テストを実施

    Returns:
        dict: 接続結果
    """
    start = time.time()
    try:
        # NBS uses session-based access, test the main page
        resp = requests.get(
            "https://data.stats.gov.cn/english/",
            timeout=15,
            allow_redirects=True,
        )
        latency = (time.time() - start) * 1000
        return {
            "reachable": resp.status_code < 500,
            "status_code": resp.status_code,
            "latency_ms": round(latency, 1),
            "error": None,
        }
    except requests.exceptions.Timeout:
        return {
            "reachable": False,
            "status_code": None,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "error": "Connection timed out (NBS may be slow from overseas)",
        }
    except requests.exceptions.RequestException as e:
        return {
            "reachable": False,
            "status_code": None,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "error": str(e),
        }


def fetch_nbs_data(
    dbcode: str = "hgyd",
    zb_code: str = "A0B01",
    last_n: int = 12,
) -> dict:
    """NBS EasyQuery APIからデータを取得

    Args:
        dbcode: データベースコード (hgyd=月次, hgjd=四半期, hgnd=年次)
        zb_code: 指標コード (e.g., "A0B01"=PMI)
        last_n: 取得する直近期間数

    Returns:
        dict: APIレスポンスまたはエラー
    """
    now = datetime.utcnow().isoformat()
    _rate_limit()

    # NBS EasyQuery API uses POST with specific parameters
    params = {
        "m": "QueryData",
        "dbcode": dbcode,
        "rowcode": "zb",
        "colcode": "sj",
        "wds": "[]",
        "dfwds": f'[{{"wdcode":"zb","valuecode":"{zb_code}"}}]',
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SupplyChainRisk/1.0)",
        "Accept": "application/json",
        "Referer": "https://data.stats.gov.cn/english/easyquery.htm",
    }

    try:
        resp = requests.get(
            NBS_BASE,
            params=params,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()

        data = resp.json()

        if data.get("returncode") != 200 and data.get("returncode") is not None:
            return {
                "error": f"NBS API error: code={data.get('returncode')}, msg={data.get('returndata', '')}",
                "source": "NBS China",
                "timestamp": now,
            }

        # Parse the data nodes
        data_nodes = data.get("returndata", {}).get("datanodes", [])
        wdnodes = data.get("returndata", {}).get("wdnodes", [])

        parsed: list[dict] = []
        for node in data_nodes[-last_n:]:
            wds = node.get("wds", [])
            period = ""
            for wd in wds:
                if wd.get("wdcode") == "sj":
                    period = wd.get("valuecode", "")
            parsed.append({
                "value": node.get("data", {}).get("data"),
                "has_data": node.get("data", {}).get("hasdata", False),
                "period": period,
            })

        return {
            "data": parsed,
            "source": "NBS China (live API)",
            "timestamp": now,
            "error": None,
        }

    except requests.exceptions.RequestException as e:
        return {
            "error": f"NBS API request failed: {str(e)}",
            "source": "NBS China",
            "timestamp": now,
        }
    except (ValueError, KeyError) as e:
        return {
            "error": f"NBS API response parse error: {str(e)}",
            "source": "NBS China",
            "timestamp": now,
        }


def get_china_economic_indicators() -> dict:
    """中国の主要経済指標を取得

    APIからリアルタイムデータ取得を試行し、失敗時は静的データにフォールバック。

    Returns:
        dict: 経済指標データ
    """
    now = datetime.utcnow().isoformat()
    indicators: dict = {}
    errors: list[str] = []
    live_count = 0

    # APIからデータ取得を試行 (最初の指標だけで接続テスト)
    test_result = fetch_nbs_data(dbcode="hgyd", zb_code="A0B01", last_n=1)

    if test_result.get("error"):
        # API接続失敗 → 全て静的データ
        return {
            "indicators": STATIC_CHINA_DATA,
            "source": "NBS China (static fallback - API unavailable)",
            "timestamp": now,
            "error": f"API connection failed: {test_result['error']}",
            "country_code": "CHN",
            "country_name": "China",
        }

    # API接続成功 → 各指標を取得
    for key, config in NBS_INDICATORS.items():
        _rate_limit()
        result = fetch_nbs_data(
            dbcode=config["dbcode"],
            zb_code=config["zb_code"],
            last_n=1,
        )
        if result.get("error") or not result.get("data"):
            errors.append(f"{key}: {result.get('error', 'No data')}")
            if key in STATIC_CHINA_DATA:
                indicators[key] = STATIC_CHINA_DATA[key]
                indicators[key]["source_note"] = "static_fallback"
        else:
            data_points = result["data"]
            if data_points and data_points[0].get("has_data"):
                indicators[key] = {
                    "value": data_points[0]["value"],
                    "period": data_points[0]["period"],
                    "description": config["description"],
                    "source_note": "live_api",
                }
                live_count += 1
            elif key in STATIC_CHINA_DATA:
                indicators[key] = STATIC_CHINA_DATA[key]
                indicators[key]["source_note"] = "static_fallback"

    # 静的データで不足分を補完
    for key, static_val in STATIC_CHINA_DATA.items():
        if key not in indicators:
            indicators[key] = static_val

    source = "NBS China (live API)" if live_count > 0 else "NBS China (static fallback)"
    if errors and live_count > 0:
        source = f"NBS China (mixed: {live_count} live, {len(errors)} fallback)"

    return {
        "indicators": indicators,
        "source": source,
        "timestamp": now,
        "error": "; ".join(errors) if errors else None,
        "country_code": "CHN",
        "country_name": "China",
    }


def get_china_pmi() -> dict:
    """中国PMI (製造業・非製造業) を取得

    Returns:
        dict: PMIデータ
    """
    now = datetime.utcnow().isoformat()

    manufacturing = fetch_nbs_data(dbcode="hgyd", zb_code="A0B01", last_n=6)
    _rate_limit()
    non_manufacturing = fetch_nbs_data(dbcode="hgyd", zb_code="A0B02", last_n=6)

    result: dict = {"source": "NBS China", "timestamp": now, "error": None}

    if manufacturing.get("error") and non_manufacturing.get("error"):
        result["manufacturing_pmi"] = STATIC_CHINA_DATA["pmi_manufacturing"]
        result["non_manufacturing_pmi"] = STATIC_CHINA_DATA["pmi_non_manufacturing"]
        result["source"] = "NBS China (static fallback)"
        result["error"] = manufacturing["error"]
    else:
        if manufacturing.get("data"):
            result["manufacturing_pmi"] = manufacturing["data"]
        else:
            result["manufacturing_pmi"] = STATIC_CHINA_DATA["pmi_manufacturing"]

        if non_manufacturing.get("data"):
            result["non_manufacturing_pmi"] = non_manufacturing["data"]
        else:
            result["non_manufacturing_pmi"] = STATIC_CHINA_DATA["pmi_non_manufacturing"]

    return result


def get_economic_indicators(country_code: str = "CHN") -> dict:
    """統一インターフェース: 中国の経済指標を取得

    Args:
        country_code: 国コード (CHN/CNのみ対応)

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    if country_code.upper() not in ("CHN", "CN"):
        return {
            "indicators": {},
            "source": "NBS China",
            "timestamp": datetime.utcnow().isoformat(),
            "error": f"NBS client only supports CHN/CN, got: {country_code}",
        }
    return get_china_economic_indicators()


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("NBS China (National Bureau of Statistics) Client Test")
    print("=" * 60)

    # 1) 疎通テスト
    print("\n[1] Connectivity Test")
    conn = test_connectivity()
    print(f"  Reachable: {conn['reachable']}")
    print(f"  Status Code: {conn['status_code']}")
    print(f"  Latency: {conn['latency_ms']} ms")
    if conn["error"]:
        print(f"  Error: {conn['error']}")

    # 2) 経済指標取得
    print("\n[2] China Economic Indicators")
    result = get_economic_indicators("CHN")
    print(f"  Source: {result['source']}")
    print(f"  Timestamp: {result['timestamp']}")
    if result.get("error"):
        print(f"  Error: {result['error']}")
    print("  Indicators:")
    for key, val in result.get("indicators", {}).items():
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')} {val.get('unit', '')} ({val.get('period', '')})")
        else:
            print(f"    {key}: {val}")

    # 3) 不正な国コード
    print("\n[3] Invalid country code test")
    bad = get_economic_indicators("USA")
    print(f"  Error: {bad['error']}")
