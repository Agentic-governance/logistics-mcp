"""UN Comtrade Plus - 国際貿易データ
二国間貿易量をHS商品コード別に取得
https://comtradeplus.un.org/
Preview API: キー不要（レート制限あり）
Full API: subscription key必要
"""
import requests
import os

COMTRADE_PREVIEW = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
COMTRADE_FULL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
COMTRADE_KEY = os.getenv("COMTRADE_API_KEY", "")

# UN M49 numeric country codes
COUNTRY_CODES = {
    "japan": 392, "jpn": 392, "jp": 392,
    "china": 156, "chn": 156, "cn": 156,
    "united states": 842, "usa": 842, "us": 842,
    "south korea": 410, "korea": 410, "kor": 410, "kr": 410,
    "taiwan": 490, "twn": 490, "tw": 490,
    "germany": 276, "deu": 276, "de": 276,
    "thailand": 764, "tha": 764, "th": 764,
    "vietnam": 704, "vnm": 704, "vn": 704,
    "indonesia": 360, "idn": 360, "id": 360,
    "malaysia": 458, "mys": 458, "my": 458,
    "singapore": 702, "sgp": 702, "sg": 702,
    "india": 356, "ind": 356, "in": 356,
    "australia": 36, "aus": 36, "au": 36,
    "philippines": 608, "phl": 608, "ph": 608,
    "russia": 643, "rus": 643, "ru": 643,
    "united kingdom": 826, "gbr": 826, "uk": 826,
    "france": 251, "fra": 251, "fr": 251,
    "italy": 381, "ita": 381, "it": 381,
    "canada": 124, "can": 124, "ca": 124,
    "mexico": 484, "mex": 484, "mx": 484,
    "brazil": 76, "bra": 76, "br": 76,
    "saudi arabia": 682, "sau": 682, "sa": 682,
    "uae": 784, "are": 784, "ae": 784,
    "turkey": 792, "tur": 792, "tr": 792,
    "bangladesh": 50, "bgd": 50, "bd": 50,
    "myanmar": 104, "mmr": 104, "mm": 104,
    "cambodia": 116, "khm": 116, "kh": 116,
    "pakistan": 586, "pak": 586, "pk": 586,
    "egypt": 818, "egy": 818, "eg": 818,
    "south africa": 710, "zaf": 710, "za": 710,
    "nigeria": 566, "nga": 566, "ng": 566,
    "kenya": 404, "ken": 404, "ke": 404,
    "ukraine": 804, "ukr": 804, "ua": 804,
}


def _resolve_code(location: str) -> int:
    loc = location.lower().strip()
    if loc in COUNTRY_CODES:
        return COUNTRY_CODES[loc]
    for name, code in COUNTRY_CODES.items():
        if loc in name or name in loc:
            return code
    return 0


def fetch_bilateral_trade(reporter: str, partner: str, year: str = "2023") -> dict:
    """二国間貿易データ取得"""
    reporter_code = _resolve_code(reporter)
    partner_code = _resolve_code(partner)

    if not reporter_code or not partner_code:
        return {"error": "Unknown country code"}

    params = {
        "reporterCode": reporter_code,
        "partnerCode": partner_code,
        "period": year,
        "cmdCode": "TOTAL",
        "flowCode": "M,X",
    }

    # Use full API if key available, otherwise preview
    if COMTRADE_KEY:
        url = COMTRADE_FULL
        headers = {"Ocp-Apim-Subscription-Key": COMTRADE_KEY}
    else:
        url = COMTRADE_PREVIEW
        headers = {}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for record in data.get("data", []):
            flow = record.get("flowCode", "")
            flow_desc = "Export" if flow == "X" else "Import" if flow == "M" else flow
            value = record.get("primaryValue") or record.get("fobvalue") or record.get("cifvalue") or 0
            results.append({
                "year": record.get("refYear"),
                "reporter_code": record.get("reporterCode"),
                "partner_code": record.get("partnerCode"),
                "trade_flow": flow_desc,
                "commodity": record.get("cmdCode", "TOTAL"),
                "trade_value_usd": value,
                "netweight_kg": record.get("netWgt"),
            })

        return {"trade_flows": results}
    except Exception as e:
        return {"error": str(e)}


def fetch_japan_trade_summary(partner: str, year: str = "2023") -> dict:
    """日本と相手国の貿易サマリー"""
    return fetch_bilateral_trade("Japan", partner, year)


def get_trade_dependency_risk(location: str) -> dict:
    """貿易依存リスク評価"""
    trade = fetch_japan_trade_summary(location)

    if "error" in trade or not trade.get("trade_flows"):
        return {"score": 0, "evidence": ["貿易データ取得不可"]}

    imports = [t for t in trade["trade_flows"] if t.get("trade_flow") == "Import"]
    exports = [t for t in trade["trade_flows"] if t.get("trade_flow") == "Export"]

    import_value = sum(t.get("trade_value_usd", 0) or 0 for t in imports)
    export_value = sum(t.get("trade_value_usd", 0) or 0 for t in exports)

    evidence = [
        f"[貿易] 日本→{location}: 輸出 ${export_value/1e9:.1f}B USD",
        f"[貿易] {location}→日本: 輸入 ${import_value/1e9:.1f}B USD",
    ]

    # 貿易規模が大きいほど依存リスクが高い（途絶時の影響大）
    total = import_value + export_value
    if total > 50e9:
        score = 70  # 500億ドル超: 高依存
    elif total > 20e9:
        score = 50
    elif total > 5e9:
        score = 30
    elif total > 1e9:
        score = 15
    else:
        score = 5

    evidence.append(f"[貿易] 二国間貿易総額: ${total/1e9:.1f}B USD (2023)")

    return {"score": score, "evidence": evidence, "import_usd": import_value, "export_usd": export_value}
