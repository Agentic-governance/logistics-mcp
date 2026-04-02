"""ILO ILOSTAT クライアント (SDMX REST API)
International Labour Organization - 労働関連統計データ
APIキー不要

SDMX API: https://sdmx.ilo.org/rest/data/ILO,DF_EAP_DWAP_SEX_AGE_RT/{country}
Returns XML - parse with xml.etree.ElementTree (lxml optional)
"""
import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

ILOSTAT_SDMX_BASE = "https://sdmx.ilo.org/rest"
ILOSTAT_API_BASE = "https://rplumber.ilo.org/data/indicator"

# ILO indicator dataflow codes (SDMX)
ILO_INDICATORS = {
    "labor_participation": {
        "dataflow": "DF_EAP_DWAP_SEX_AGE_RT",
        "description": "Labour Force Participation Rate (%)",
        "sdg": False,
    },
    "unemployment": {
        "dataflow": "DF_UNE_DEAP_SEX_AGE_RT",
        "description": "Unemployment Rate by Sex and Age (%)",
        "sdg": False,
    },
    "employment_by_sector": {
        "dataflow": "DF_EMP_TEMP_SEX_EC2_NB",
        "description": "Employment by Economic Activity",
        "sdg": False,
    },
    "child_labor": {
        "dataflow": "DF_SDG_0871_SEX_AGE_RT",
        "description": "SDG 8.7.1 - Child Labour (%)",
        "sdg": True,
    },
    "working_poverty": {
        "dataflow": "DF_SDG_0111_SEX_AGE_RT",
        "description": "SDG 1.1.1 - Working Poverty Rate (%)",
        "sdg": True,
    },
    "labor_rights": {
        "dataflow": "DF_SDG_0882_SRC_RT",
        "description": "SDG 8.8.2 - Labour Rights Compliance",
        "sdg": True,
    },
}

# ILO indicator codes for the alternative REST API
ILO_REST_INDICATORS = {
    "EAP_DWAP_SEX_AGE_RT": "Labour Force Participation Rate",
    "UNE_DEAP_SEX_AGE_RT": "Unemployment Rate",
    "EMP_TEMP_SEX_EC2_NB": "Employment by Sector",
    "SDG_0871_SEX_AGE_RT": "Child Labour",
    "SDG_0852_NOC_RT": "Labour Rights (Freedom of Association)",
}

# SDMX XML namespaces
SDMX_NS = {
    "message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "generic": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic",
    "common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}

# 静的フォールバックデータ (主要国の労働指標, 2023-2024年)
STATIC_LABOR_DATA = {
    "JPN": {
        "labor_participation_rate": 63.1,
        "unemployment_rate": 2.5,
        "manufacturing_employment_pct": 15.8,
        "youth_unemployment_rate": 4.1,
        "child_labor_pct": 0.0,
        "min_wage_usd_hr": 7.2,
        "period": "2024",
    },
    "CHN": {
        "labor_participation_rate": 67.5,
        "unemployment_rate": 5.1,
        "manufacturing_employment_pct": 27.5,
        "youth_unemployment_rate": 14.9,
        "child_labor_pct": 7.5,
        "min_wage_usd_hr": 3.1,
        "period": "2024",
    },
    "VNM": {
        "labor_participation_rate": 76.8,
        "unemployment_rate": 2.1,
        "manufacturing_employment_pct": 22.4,
        "youth_unemployment_rate": 7.8,
        "child_labor_pct": 5.4,
        "min_wage_usd_hr": 1.2,
        "period": "2024",
    },
    "THA": {
        "labor_participation_rate": 68.2,
        "unemployment_rate": 1.0,
        "manufacturing_employment_pct": 16.5,
        "youth_unemployment_rate": 5.2,
        "child_labor_pct": 3.9,
        "min_wage_usd_hr": 2.8,
        "period": "2024",
    },
    "IDN": {
        "labor_participation_rate": 69.4,
        "unemployment_rate": 4.8,
        "manufacturing_employment_pct": 14.6,
        "youth_unemployment_rate": 13.5,
        "child_labor_pct": 4.0,
        "min_wage_usd_hr": 1.5,
        "period": "2024",
    },
    "MYS": {
        "labor_participation_rate": 70.2,
        "unemployment_rate": 3.2,
        "manufacturing_employment_pct": 17.2,
        "youth_unemployment_rate": 11.8,
        "child_labor_pct": 2.4,
        "min_wage_usd_hr": 3.5,
        "period": "2024",
    },
    "PHL": {
        "labor_participation_rate": 65.4,
        "unemployment_rate": 3.8,
        "manufacturing_employment_pct": 8.2,
        "youth_unemployment_rate": 8.5,
        "child_labor_pct": 3.3,
        "min_wage_usd_hr": 2.1,
        "period": "2024",
    },
    "KHM": {
        "labor_participation_rate": 82.1,
        "unemployment_rate": 0.3,
        "manufacturing_employment_pct": 25.8,
        "youth_unemployment_rate": 1.2,
        "child_labor_pct": 10.1,
        "min_wage_usd_hr": 1.1,
        "period": "2024",
    },
    "MMR": {
        "labor_participation_rate": 61.2,
        "unemployment_rate": 3.0,
        "manufacturing_employment_pct": 11.5,
        "youth_unemployment_rate": 5.8,
        "child_labor_pct": 9.3,
        "min_wage_usd_hr": 0.6,
        "period": "2024",
    },
    "BGD": {
        "labor_participation_rate": 58.5,
        "unemployment_rate": 4.2,
        "manufacturing_employment_pct": 21.5,
        "youth_unemployment_rate": 10.8,
        "child_labor_pct": 4.3,
        "min_wage_usd_hr": 0.4,
        "period": "2024",
    },
    "IND": {
        "labor_participation_rate": 55.2,
        "unemployment_rate": 4.0,
        "manufacturing_employment_pct": 12.1,
        "youth_unemployment_rate": 23.2,
        "child_labor_pct": 5.7,
        "min_wage_usd_hr": 0.8,
        "period": "2024",
    },
    "KOR": {
        "labor_participation_rate": 64.5,
        "unemployment_rate": 2.8,
        "manufacturing_employment_pct": 16.2,
        "youth_unemployment_rate": 6.5,
        "child_labor_pct": 0.0,
        "min_wage_usd_hr": 7.0,
        "period": "2024",
    },
    "NGA": {
        "labor_participation_rate": 55.0,
        "unemployment_rate": 33.3,
        "manufacturing_employment_pct": 7.2,
        "youth_unemployment_rate": 42.5,
        "child_labor_pct": 30.5,
        "min_wage_usd_hr": 0.2,
        "period": "2024",
    },
    "ZAF": {
        "labor_participation_rate": 59.8,
        "unemployment_rate": 32.1,
        "manufacturing_employment_pct": 10.8,
        "youth_unemployment_rate": 45.5,
        "child_labor_pct": 5.9,
        "min_wage_usd_hr": 1.8,
        "period": "2024",
    },
    "ETH": {
        "labor_participation_rate": 78.5,
        "unemployment_rate": 3.5,
        "manufacturing_employment_pct": 5.2,
        "youth_unemployment_rate": 5.8,
        "child_labor_pct": 39.7,
        "min_wage_usd_hr": 0.1,
        "period": "2024",
    },
    "KEN": {
        "labor_participation_rate": 72.3,
        "unemployment_rate": 5.7,
        "manufacturing_employment_pct": 7.8,
        "youth_unemployment_rate": 13.8,
        "child_labor_pct": 26.2,
        "min_wage_usd_hr": 0.5,
        "period": "2024",
    },
    "EGY": {
        "labor_participation_rate": 42.8,
        "unemployment_rate": 6.9,
        "manufacturing_employment_pct": 12.5,
        "youth_unemployment_rate": 25.1,
        "child_labor_pct": 7.0,
        "min_wage_usd_hr": 1.0,
        "period": "2024",
    },
}


def test_connectivity() -> dict:
    """ILOSTAT SDMX APIサーバーへの疎通テストを実施

    Returns:
        dict: 接続結果
    """
    start = time.time()
    try:
        # Test SDMX endpoint with a minimal query
        resp = requests.get(
            f"{ILOSTAT_SDMX_BASE}/dataflow/ILO",
            headers={"Accept": "application/xml"},
            timeout=15,
        )
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


def fetch_ilostat_sdmx(
    dataflow: str,
    country_iso3: str,
    start_period: Optional[str] = None,
) -> dict:
    """ILOSTAT SDMX APIからデータを取得 (XML形式)

    Args:
        dataflow: データフローID (e.g., "DF_EAP_DWAP_SEX_AGE_RT")
        country_iso3: ISO3国コード (e.g., "JPN")
        start_period: 開始期間 (e.g., "2020")

    Returns:
        dict: パースされたデータまたはエラー
    """
    now = datetime.utcnow().isoformat()
    url = f"{ILOSTAT_SDMX_BASE}/data/ILO,{dataflow}/{country_iso3}"

    params: dict = {}
    if start_period:
        params["startPeriod"] = start_period

    headers = {
        "Accept": "application/vnd.sdmx.genericdata+xml;version=2.1",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()

        # Parse XML
        root = ET.fromstring(resp.content)

        # Extract observations from SDMX generic data format
        observations: list[dict] = []
        for obs in root.iter("{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic}Obs"):
            obs_data: dict = {}
            dim_elem = obs.find(
                "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic}ObsDimension"
            )
            val_elem = obs.find(
                "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic}ObsValue"
            )

            if dim_elem is not None:
                obs_data["period"] = dim_elem.get("value", "")
            if val_elem is not None:
                try:
                    obs_data["value"] = float(val_elem.get("value", ""))
                except ValueError:
                    obs_data["value"] = val_elem.get("value", "")

            # Get attributes
            attrs_elem = obs.find(
                "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic}Attributes"
            )
            if attrs_elem is not None:
                for attr in attrs_elem:
                    attr_id = attr.get("id", "")
                    attr_val = attr.get("value", "")
                    obs_data[attr_id] = attr_val

            if obs_data:
                observations.append(obs_data)

        return {
            "data": observations,
            "source": "ILOSTAT SDMX (live API)",
            "timestamp": now,
            "error": None,
        }

    except requests.exceptions.RequestException as e:
        return {
            "error": f"ILOSTAT SDMX request failed: {str(e)}",
            "source": "ILOSTAT",
            "timestamp": now,
        }
    except ET.ParseError as e:
        return {
            "error": f"ILOSTAT XML parse error: {str(e)}",
            "source": "ILOSTAT",
            "timestamp": now,
        }


def fetch_ilostat_rest(
    indicator: str,
    country_iso3: str,
) -> dict:
    """ILOSTAT REST APIからデータを取得 (JSON形式, alternative)

    Args:
        indicator: 指標コード (e.g., "EAP_DWAP_SEX_AGE_RT")
        country_iso3: ISO3国コード

    Returns:
        dict: パースされたデータまたはエラー
    """
    now = datetime.utcnow().isoformat()
    url = f"{ILOSTAT_API_BASE}/?id={indicator}&ref_area={country_iso3}&timefrom=2020&format=.json"

    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        return {
            "data": data,
            "source": "ILOSTAT REST (live API)",
            "timestamp": now,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"ILOSTAT REST request failed: {str(e)}",
            "source": "ILOSTAT",
            "timestamp": now,
        }
    except ValueError as e:
        return {
            "error": f"ILOSTAT response parse error: {str(e)}",
            "source": "ILOSTAT",
            "timestamp": now,
        }


def get_labor_indicators(country_iso3: str) -> dict:
    """特定国の労働関連指標を取得

    SDMX APIからリアルタイムデータを試行し、失敗時は静的データにフォールバック。

    Args:
        country_iso3: ISO3国コード (e.g., "JPN", "VNM")

    Returns:
        dict: 労働指標データ
    """
    now = datetime.utcnow().isoformat()
    code = country_iso3.upper()

    # Try SDMX API for labor participation rate
    sdmx_result = fetch_ilostat_sdmx("DF_EAP_DWAP_SEX_AGE_RT", code, "2020")

    if sdmx_result.get("error") is None and sdmx_result.get("data"):
        observations = sdmx_result["data"]
        if observations:
            # Get latest observation
            latest = observations[-1]
            indicators = {
                "labor_participation_rate": {
                    "value": latest.get("value"),
                    "period": latest.get("period"),
                    "source_note": "live_sdmx",
                },
            }

            # Supplement with static data
            if code in STATIC_LABOR_DATA:
                static = STATIC_LABOR_DATA[code]
                for key in ["unemployment_rate", "manufacturing_employment_pct",
                            "youth_unemployment_rate", "child_labor_pct", "min_wage_usd_hr"]:
                    if key in static:
                        indicators[key] = {
                            "value": static[key],
                            "period": static.get("period", "2024"),
                            "source_note": "static_supplement",
                        }

            return {
                "indicators": indicators,
                "source": "ILOSTAT SDMX (mixed live + static)",
                "timestamp": now,
                "error": None,
                "country_code": code,
            }

    # Full fallback to static data
    if code in STATIC_LABOR_DATA:
        static = STATIC_LABOR_DATA[code]
        indicators = {
            key: {
                "value": val,
                "unit": "percent" if "pct" in key or "rate" in key else ("usd" if "usd" in key else ""),
                "period": static.get("period", "2024"),
            }
            for key, val in static.items()
            if key != "period"
        }

        return {
            "indicators": indicators,
            "source": "ILOSTAT (static fallback)",
            "timestamp": now,
            "error": None,
            "country_code": code,
        }

    return {
        "indicators": {},
        "source": "ILOSTAT",
        "timestamp": now,
        "error": f"No labor data available for country: {country_iso3}",
        "country_code": code,
    }


def get_supply_chain_labor_risk(country_iso3: str) -> dict:
    """サプライチェーン労働リスク評価

    Args:
        country_iso3: ISO3国コード

    Returns:
        dict: 労働リスクスコアとエビデンス
    """
    now = datetime.utcnow().isoformat()
    code = country_iso3.upper()

    if code not in STATIC_LABOR_DATA:
        return {
            "score": 0,
            "evidence": [],
            "source": "ILOSTAT",
            "timestamp": now,
            "error": f"No data for {code}",
        }

    data = STATIC_LABOR_DATA[code]
    score = 0
    evidence: list[str] = []

    # Child labor risk
    child_labor = data.get("child_labor_pct", 0)
    if child_labor > 20:
        score += 40
        evidence.append(f"High child labor rate: {child_labor}%")
    elif child_labor > 10:
        score += 25
        evidence.append(f"Elevated child labor rate: {child_labor}%")
    elif child_labor > 5:
        score += 10
        evidence.append(f"Moderate child labor rate: {child_labor}%")

    # Low wages risk (exploitation potential)
    min_wage = data.get("min_wage_usd_hr", 0)
    if min_wage < 0.5:
        score += 20
        evidence.append(f"Very low minimum wage: ${min_wage}/hr")
    elif min_wage < 1.5:
        score += 10
        evidence.append(f"Low minimum wage: ${min_wage}/hr")

    # High unemployment (vulnerability)
    unemployment = data.get("unemployment_rate", 0)
    if unemployment > 20:
        score += 20
        evidence.append(f"Very high unemployment: {unemployment}%")
    elif unemployment > 10:
        score += 10
        evidence.append(f"High unemployment: {unemployment}%")

    score = min(100, score)

    return {
        "score": score,
        "evidence": evidence,
        "source": "ILOSTAT (static data)",
        "timestamp": now,
        "error": None,
        "country_code": code,
    }


def get_economic_indicators(country_code: str) -> dict:
    """統一インターフェース: 労働関連経済指標を取得

    Args:
        country_code: ISO3国コード

    Returns:
        dict: {"indicators": {...}, "source": str, "timestamp": str, "error": str|None}
    """
    return get_labor_indicators(country_code)


# ---------- テスト ----------
if __name__ == "__main__":
    print("=" * 60)
    print("ILOSTAT (ILO Statistics) Client Test")
    print("=" * 60)

    # 1) 疎通テスト
    print("\n[1] Connectivity Test")
    conn = test_connectivity()
    print(f"  Reachable: {conn['reachable']}")
    print(f"  Status Code: {conn['status_code']}")
    print(f"  Latency: {conn['latency_ms']} ms")
    if conn["error"]:
        print(f"  Error: {conn['error']}")

    # 2) 日本の労働指標
    print("\n[2] Japan Labor Indicators")
    result = get_labor_indicators("JPN")
    print(f"  Source: {result['source']}")
    if result.get("error"):
        print(f"  Error: {result['error']}")
    for key, val in result.get("indicators", {}).items():
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')} ({val.get('period', '')})")
        else:
            print(f"    {key}: {val}")

    # 3) ベトナムの労働指標
    print("\n[3] Vietnam Labor Indicators")
    vnm = get_labor_indicators("VNM")
    for key, val in vnm.get("indicators", {}).items():
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')} ({val.get('period', '')})")

    # 4) 労働リスク評価
    print("\n[4] Supply Chain Labor Risk Scores")
    for country in ["JPN", "VNM", "BGD", "NGA", "ETH", "KHM"]:
        risk = get_supply_chain_labor_risk(country)
        print(f"  {country}: Score={risk['score']}")
        for ev in risk.get("evidence", []):
            print(f"    - {ev}")

    # 5) 統一インターフェース
    print("\n[5] Unified Interface Test")
    unified = get_economic_indicators("CHN")
    print(f"  Source: {unified['source']}")
    for key, val in unified.get("indicators", {}).items():
        if isinstance(val, dict):
            print(f"    {key}: {val.get('value')}")

    # 6) 未知の国コード
    print("\n[6] Unknown country code test")
    unknown = get_economic_indicators("XYZ")
    print(f"  Error: {unknown.get('error')}")
