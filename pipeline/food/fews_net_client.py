"""FEWS NET (Famine Early Warning Systems Network) API
農業生産量・市場価格・IPC分類に基づく食料安全保障評価。
https://fdw.fews.net/api/v1/
APIキー不要 (一部エンドポイント)。

WFP HungerMap が「現在の飢餓人口マッピング」であるのに対し、
FEWS NET は「農業・市場構造からの予測的評価」で概念が異なる。
"""
import requests
from typing import Optional

FEWS_BASE = "https://fdw.fews.net/api/v1"
HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0", "Accept": "application/json"}

# FEWS NET カバレッジ対象国 (主にアフリカ・中東・中米・南アジア)
COVERED_COUNTRIES = {
    "AF", "BD", "BF", "BI", "CD", "CF", "CM", "DJ", "ET", "GH",
    "GT", "GN", "HN", "HT", "KE", "LR", "MG", "ML", "MR", "MW",
    "MZ", "NE", "NG", "PK", "RW", "SD", "SL", "SN", "SO", "SS",
    "SV", "TD", "TZ", "UG", "YE", "ZA", "ZM", "ZW",
}

# ISO2 → FEWS NET 国名マッピング
_ISO2_TO_FEWS = {
    "AF": "afghanistan", "BD": "bangladesh", "BF": "burkina-faso",
    "BI": "burundi", "CD": "democratic-republic-congo", "CF": "central-african-republic",
    "CM": "cameroon", "DJ": "djibouti", "ET": "ethiopia", "GH": "ghana",
    "GT": "guatemala", "GN": "guinea", "HN": "honduras", "HT": "haiti",
    "KE": "kenya", "LR": "liberia", "MG": "madagascar", "ML": "mali",
    "MR": "mauritania", "MW": "malawi", "MZ": "mozambique", "NE": "niger",
    "NG": "nigeria", "PK": "pakistan", "RW": "rwanda", "SD": "sudan",
    "SL": "sierra-leone", "SN": "senegal", "SO": "somalia", "SS": "south-sudan",
    "SV": "el-salvador", "TD": "chad", "TZ": "tanzania", "UG": "uganda",
    "YE": "yemen", "ZA": "south-africa", "ZM": "zambia", "ZW": "zimbabwe",
}

# IPC Phase → スコア変換
IPC_PHASE_SCORES = {
    1: 0,    # Minimal
    2: 25,   # Stressed
    3: 50,   # Crisis
    4: 75,   # Emergency
    5: 100,  # Famine
}

# 静的 IPC 推定値 (API不到達時のフォールバック)
STATIC_IPC_ESTIMATES = {
    "YE": 4, "SO": 4, "SS": 4, "SD": 4, "AF": 3, "ET": 3,
    "CD": 3, "CF": 3, "HT": 3, "NG": 3, "MZ": 3, "ML": 3,
    "BF": 3, "NE": 3, "TD": 3, "MW": 3, "MG": 3, "KE": 2,
    "GT": 2, "HN": 2, "SV": 2, "PK": 2, "BD": 2, "ZW": 2,
    "ZM": 2, "UG": 2, "TZ": 2, "GH": 2, "SN": 2, "CM": 2,
    "BI": 2, "RW": 2, "DJ": 2, "SL": 2, "GN": 2, "LR": 2,
    "MR": 2, "ZA": 1,
}


def is_covered(country_iso2: str) -> bool:
    """FEWS NET のカバレッジ対象国かどうかを判定。

    Args:
        country_iso2: ISO2 国コード

    Returns:
        カバレッジ対象なら True
    """
    return country_iso2.upper() in COVERED_COUNTRIES


def get_ipc_phase(country_iso2: str) -> dict:
    """FEWS NET IPC Phase Classification を取得。

    Args:
        country_iso2: ISO2 国コード

    Returns:
        {"phase": int, "score": int, "population_affected": int, "evidence": list}
    """
    iso2 = country_iso2.upper()
    fews_name = _ISO2_TO_FEWS.get(iso2)

    if fews_name:
        try:
            resp = requests.get(
                f"{FEWS_BASE}/ipcphase/",
                params={"country": fews_name, "format": "json"},
                headers=HEADERS,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data if isinstance(data, list) else data.get("results", [])
                if results:
                    # 最新のIPC評価を取得
                    latest = results[-1] if isinstance(results, list) else results
                    if isinstance(latest, dict):
                        phase = latest.get("phase", latest.get("ipc_phase", 0))
                        if isinstance(phase, (int, float)) and phase > 0:
                            return {
                                "phase": int(phase),
                                "score": IPC_PHASE_SCORES.get(int(phase), 0),
                                "population_affected": latest.get("population", 0),
                                "evidence": [f"[FEWS NET] IPC Phase {int(phase)}: {_phase_label(int(phase))}"],
                                "source": "fews_api",
                            }
        except Exception:
            pass

    # 静的推定フォールバック
    estimated_phase = STATIC_IPC_ESTIMATES.get(iso2, 0)
    if estimated_phase > 0:
        return {
            "phase": estimated_phase,
            "score": IPC_PHASE_SCORES.get(estimated_phase, 0),
            "population_affected": 0,
            "evidence": [f"[FEWS NET 推定] IPC Phase {estimated_phase}: {_phase_label(estimated_phase)}"],
            "source": "static_estimate",
        }

    return {"phase": 0, "score": 0, "population_affected": 0, "evidence": [], "source": "none"}


def get_price_alerts(country_iso2: str) -> list[dict]:
    """主要食料品の価格異常アラートを取得。

    Args:
        country_iso2: ISO2 国コード

    Returns:
        価格アラートリスト
    """
    fews_name = _ISO2_TO_FEWS.get(country_iso2.upper())
    if not fews_name:
        return []

    try:
        resp = requests.get(
            f"{FEWS_BASE}/marketpricealert/",
            params={"country": fews_name, "format": "json"},
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data if isinstance(data, list) else data.get("results", [])
            alerts = []
            for item in results[:20]:
                if isinstance(item, dict):
                    alerts.append({
                        "commodity": item.get("commodity", item.get("product", "")),
                        "market": item.get("market", ""),
                        "alert_level": item.get("alert_level", item.get("alert", "")),
                        "price_change": item.get("price_change", 0),
                    })
            return alerts
    except Exception:
        pass

    return []


def get_food_security_indicators(location: str) -> dict:
    """統合食料安全保障指標を取得。

    FEWS NET カバレッジ対象国: IPC + 価格アラート + WFP補助
    非対象国: None を返す (呼び出し元でWFPフォールバック)

    Args:
        location: 国名 or ISO コード

    Returns:
        {"score": int, "evidence": list, "ipc": dict, "price_alerts": list}
        非対象国の場合は None
    """
    iso2 = _resolve_iso2(location)
    if not iso2 or not is_covered(iso2):
        return None  # 非対象国 → WFP フォールバック

    evidence: list[str] = []

    # IPC Phase (60%)
    ipc = get_ipc_phase(iso2)
    ipc_score = ipc["score"]
    evidence.extend(ipc["evidence"])

    # Price alerts (25%)
    alerts = get_price_alerts(iso2)
    n_alerts = len(alerts)
    if n_alerts >= 10:
        price_score = 100
    elif n_alerts >= 5:
        price_score = 70
    elif n_alerts >= 2:
        price_score = 40
    elif n_alerts >= 1:
        price_score = 20
    else:
        price_score = 0

    if alerts:
        evidence.append(f"[FEWS NET] 価格異常アラート: {n_alerts}件")

    # WFP 補助分 (15%) は scoring/dimensions/food_security_scorer.py で追加
    # ここでは IPC + price のみ返す
    combined_score = int(ipc_score * 0.706 + price_score * 0.294)  # 60/(60+25) and 25/(60+25)

    return {
        "score": min(100, combined_score),
        "evidence": evidence,
        "ipc": ipc,
        "price_alerts": alerts,
        "source": "fews_net",
    }


def _phase_label(phase: int) -> str:
    """IPC Phase のラベルを返す。"""
    labels = {1: "Minimal", 2: "Stressed", 3: "Crisis", 4: "Emergency", 5: "Famine"}
    return labels.get(phase, "Unknown")


def _resolve_iso2(location: str) -> str:
    """国名/コードからISO2コードに解決。"""
    loc = location.upper().strip()
    if len(loc) == 2:
        return loc
    # ISO3 → ISO2 逆引き
    iso3_to_iso2 = {
        "AFG": "AF", "BGD": "BD", "BFA": "BF", "BDI": "BI", "COD": "CD",
        "CAF": "CF", "CMR": "CM", "DJI": "DJ", "ETH": "ET", "GHA": "GH",
        "GTM": "GT", "GIN": "GN", "HND": "HN", "HTI": "HT", "KEN": "KE",
        "LBR": "LR", "MDG": "MG", "MLI": "ML", "MRT": "MR", "MWI": "MW",
        "MOZ": "MZ", "NER": "NE", "NGA": "NG", "PAK": "PK", "RWA": "RW",
        "SDN": "SD", "SLE": "SL", "SEN": "SN", "SOM": "SO", "SSD": "SS",
        "SLV": "SV", "TCD": "TD", "TZA": "TZ", "UGA": "UG", "YEM": "YE",
        "ZAF": "ZA", "ZMB": "ZM", "ZWE": "ZW",
    }
    if len(loc) == 3 and loc in iso3_to_iso2:
        return iso3_to_iso2[loc]

    name_map = {
        "yemen": "YE", "somalia": "SO", "south sudan": "SS", "sudan": "SD",
        "afghanistan": "AF", "ethiopia": "ET", "nigeria": "NG", "kenya": "KE",
        "haiti": "HT", "chad": "TD", "mali": "ML", "niger": "NE",
        "burkina faso": "BF", "mozambique": "MZ", "madagascar": "MG",
        "pakistan": "PK", "bangladesh": "BD", "zimbabwe": "ZW",
        "drc": "CD", "democratic republic of congo": "CD",
        "central african republic": "CF",
        "south africa": "ZA", "guatemala": "GT", "honduras": "HN",
        "el salvador": "SV", "cameroon": "CM", "uganda": "UG",
        "tanzania": "TZ", "zambia": "ZM", "senegal": "SN", "ghana": "GH",
        "rwanda": "RW", "burundi": "BI", "malawi": "MW",
    }
    return name_map.get(location.lower().strip(), "")
