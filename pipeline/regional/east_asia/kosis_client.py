"""韓国KOSIS (Korea Statistical Information Service) クライアント
Korean Statistical Information Service - 韓国の主要経済統計データを取得
APIキー要(KOSIS_API_KEY)、ただし疎通テストのみ実施
https://kosis.kr/openapi/
"""
import os
import requests
import time
from datetime import datetime
from typing import Optional

KOSIS_BASE = "https://kosis.kr/openapi/Idx/getIdxKosisDt.do"
KOSIS_LIST_BASE = "https://kosis.kr/openapi/statisticsList.do"

# 主要経済指標テーブル (KOSIS indicator codes)
KOSIS_INDICATORS = {
    "manufacturing_pmi": {
        "orgId": "301",
        "tblId": "DT_512Y001",
        "description": "Manufacturing PMI (Purchasing Managers' Index)",
    },
    "export_import": {
        "orgId": "301",
        "tblId": "DT_512Y010",
        "description": "Export/Import Statistics (Monthly)",
    },
    "cpi": {
        "orgId": "101",
        "tblId": "DT_1J20001",
        "description": "Consumer Price Index",
    },
    "industrial_production": {
        "orgId": "101",
        "tblId": "DT_1C81",
        "description": "Industrial Production Index",
    },
    "unemployment_rate": {
        "orgId": "101",
        "tblId": "DT_1DA7002S",
        "description": "Unemployment Rate (%)",
    },
}

# 最新の静的フォールバックデータ (2024年実績)
STATIC_KOREA_DATA = {
    "manufacturing_pmi": {
        "value": 51.2,
        "unit": "index",
        "period": "2024-Q4",
        "description": "Manufacturing PMI",
    },
    "export_total_usd_bn": {
        "value": 683.8,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Exports",
    },
    "import_total_usd_bn": {
        "value": 632.5,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Total Imports",
    },
    "cpi_yoy": {
        "value": 2.3,
        "unit": "percent",
        "period": "2024",
        "description": "CPI Year-over-Year Change",
    },
    "industrial_production_yoy": {
        "value": 4.1,
        "unit": "percent",
        "period": "2024-Q4",
        "description": "Industrial Production YoY Growth",
    },
    "unemployment_rate": {
        "value": 2.8,
        "unit": "percent",
        "period": "2024-Q4",
        "description": "Unemployment Rate",
    },
    "gdp_growth": {
        "value": 2.2,
        "unit": "percent",
        "period": "2024",
        "description": "GDP Growth Rate",
    },
    "semiconductor_export_usd_bn": {
        "value": 141.8,
        "unit": "billion_usd",
        "period": "2024",
        "description": "Semiconductor Exports (Korea's key export)",
    },
}


def _get_api_key() -> Optional[str]:
    """KOSIS APIキーを取得"""
    key = os.getenv("KOSIS_API_KEY", "")
    return key if key else None


def test_connectivity() -> dict:
    """KOSIS APIサーバーへの疎通テストを実施

    Returns:
        dict: 接続結果 {"reachable": bool, "status_code": int|None, "latency_ms": float, "error": str|None}
    """
    start = time.time()
    try:
        resp = requests.get(
            "https://kosis.kr/openapi/",
            timeout=10,
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
            "error": "Connection timed out",
        }
    except requests.exceptions.RequestException as e:
        return {
            "reachable": False,
            "status_code": None,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "error": str(e),
        }


def fetch_kosis_data(
    org_id: str,
    tbl_id: str,
    start_period: str,
    end_period: str,
    itm_id: str = "T10",
    obj_l1: str = "ALL",
    obj_l2: str = "",
) -> dict:
    """KOSISから統計データを取得

    Args:
        org_id: 統計機関コード (e.g., "101"=統計庁, "301"=韓国銀行)
        tbl_id: 統計テーブルID
        start_period: 開始期間 (e.g., "202301")
        end_period: 終了期間 (e.g., "202412")
        itm_id: 項目ID (default: "T10")
        obj_l1: 分類レベル1 (default: "ALL")
        obj_l2: 分類レベル2 (default: "")

    Returns:
        dict: API応答データまたはエラー情報
    """
    api_key = _get_api_key()
    now = datetime.utcnow().isoformat()

    if not api_key:
        return {
            "error": "KOSIS_API_KEY not set. Set environment variable KOSIS_API_KEY to use this API.",
            "source": "KOSIS",
            "timestamp": now,
        }

    params = {
        "method": "getList",
        "apiKey": api_key,
        "itmId": itm_id,
        "objL1": obj_l1,
        "objL2": obj_l2,
        "format": "json",
        "jsonVD": "Y",
        "prdSe": "M",  # M=月別, Q=四半期, Y=年別
        "startPrdDe": start_period,
        "endPrdDe": end_period,
        "orgId": org_id,
        "tblId": tbl_id,
    }

    try:
        resp = requests.get(KOSIS_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict) and data.get("err"):
            return {
                "error": f"KOSIS API error: {data.get('errMsg', 'Unknown error')}",
                "source": "KOSIS",
                "timestamp": now,
            }

        return {
            "data": data,
            "source": "KOSIS",
            "timestamp": now,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"KOSIS API request failed: {str(e)}",
            "source": "KOSIS",
            "timestamp": now,
        }
    except ValueError as e:
        return {
            "error": f"KOSIS API response parse error: {str(e)}",
            "source": "KOSIS",
            "timestamp": now,
        }


def get_korea_economic_indicators() -> dict:
    """韓国の主要経済指標を取得

    APIキーが設定されている場合はKOSIS APIからリアルタイムデータを取得。
    設定されていない場合は静的データにフォールバック。

    Returns:
        dict: {
            "indicators": {...},
            "source": str,
            "timestamp": str,
            "error": str|None
        }
    """
    now = datetime.utcnow().isoformat()
    api_key = _get_api_key()

    if not api_key:
        # APIキーなし → 静的データを返す
        return {
            "indicators": STATIC_KOREA_DATA,
            "source": "KOSIS (static fallback - API key not set)",
            "timestamp": now,
            "error": None,
            "country_code": "KOR",
            "country_name": "South Korea",
        }

    # APIキーあり → リアルタイムデータ取得を試行
    indicators: dict = {}
    errors: list[str] = []

    for key, config in KOSIS_INDICATORS.items():
        result = fetch_kosis_data(
            org_id=config["orgId"],
            tbl_id=config["tblId"],
            start_period="202401",
            end_period="202412",
        )
        if result.get("error"):
            errors.append(f"{key}: {result['error']}")
            # 個別指標のフォールバック
            if key in STATIC_KOREA_DATA:
                indicators[key] = STATIC_KOREA_DATA[key]
                indicators[key]["source_note"] = "static_fallback"
        else:
            data = result.get("data", [])
            if isinstance(data, list) and len(data) > 0:
                latest = data[-1]
                indicators[key] = {
                    "value": latest.get("DT", latest.get("val", 0)),
                    "period": latest.get("PRD_DE", latest.get("prd", "")),
                    "description": config["description"],
                    "source_note": "live_api",
                }
            elif key in STATIC_KOREA_DATA:
                indicators[key] = STATIC_KOREA_DATA[key]
                indicators[key]["source_note"] = "static_fallback"

    # 静的データで不足分を補完
    for key, static_val in STATIC_KOREA_DATA.items():
        if key not in indicators:
            indicators[key] = static_val

    return {
        "indicators": indicators,
        "source": "KOSIS" if not errors else "KOSIS (partial static fallback)",
        "timestamp": now,
        "error": "; ".join(errors) if errors else None,
        "country_code": "KOR",
        "country_name": "South Korea",
    }


def get_economic_indicators(country_code: str = "KOR") -> dict:
    """統一インターフェース: 韓国の経済指標を取得

    Args:
        country_code: 国コード (KORのみ対応)

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    if country_code.upper() not in ("KOR", "KR"):
        return {
            "indicators": {},
            "source": "KOSIS",
            "timestamp": datetime.utcnow().isoformat(),
            "error": f"KOSIS client only supports KOR/KR, got: {country_code}",
        }
    return get_korea_economic_indicators()


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("KOSIS (Korea Statistical Information Service) Client Test")
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
    print("\n[2] Korea Economic Indicators")
    result = get_economic_indicators("KOR")
    print(f"  Source: {result['source']}")
    print(f"  Timestamp: {result['timestamp']}")
    if result["error"]:
        print(f"  Error: {result['error']}")
    print(f"  Indicators:")
    for key, val in result.get("indicators", {}).items():
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')} {val.get('unit', '')} ({val.get('period', '')})")
        else:
            print(f"    {key}: {val}")

    # 3) 不正な国コード
    print("\n[3] Invalid country code test")
    bad = get_economic_indicators("USA")
    print(f"  Error: {bad['error']}")
