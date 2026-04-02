"""為替レート・通貨ボラティリティ
Frankfurter API (ECB公式レート) - 完全無料・キー不要
https://www.frankfurter.app/
"""
import requests
from datetime import datetime, timedelta
import statistics

FRANKFURTER_BASE = "https://api.frankfurter.app"

# 主要通貨コード
COUNTRY_CURRENCY = {
    "japan": "JPY", "jpn": "JPY", "jp": "JPY",
    "china": "CNY", "chn": "CNY", "cn": "CNY",
    "united states": "USD", "usa": "USD", "us": "USD",
    "germany": "EUR", "deu": "EUR", "de": "EUR",
    "france": "EUR", "fra": "EUR", "fr": "EUR",
    "italy": "EUR", "ita": "EUR", "it": "EUR",
    "ukraine": "UAH", "ukr": "UAH", "ua": "UAH",
    "united kingdom": "GBP", "gbr": "GBP", "uk": "GBP", "gb": "GBP",
    "south korea": "KRW", "korea": "KRW", "kor": "KRW", "kr": "KRW",
    "taiwan": "TWD", "twn": "TWD", "tw": "TWD",
    "india": "INR", "ind": "INR", "in": "INR",
    "brazil": "BRL", "bra": "BRL", "br": "BRL",
    "russia": "RUB", "rus": "RUB", "ru": "RUB",
    "turkey": "TRY", "tur": "TRY", "tr": "TRY",
    "mexico": "MXN", "mex": "MXN", "mx": "MXN",
    "indonesia": "IDR", "idn": "IDR", "id": "IDR",
    "thailand": "THB", "tha": "THB", "th": "THB",
    "vietnam": "VND",
    "malaysia": "MYR", "mys": "MYR", "my": "MYR",
    "singapore": "SGD", "sgp": "SGD", "sg": "SGD",
    "philippines": "PHP", "phl": "PHP", "ph": "PHP",
    "australia": "AUD", "aus": "AUD", "au": "AUD",
    "canada": "CAD", "can": "CAD", "ca": "CAD",
    "south africa": "ZAR", "zaf": "ZAR", "za": "ZAR",
    "nigeria": "NGN",
    "egypt": "EGP",
    "saudi arabia": "SAR",
    "switzerland": "CHF", "che": "CHF", "ch": "CHF",
    "sweden": "SEK", "swe": "SEK", "se": "SEK",
    "norway": "NOK", "nor": "NOK", "no": "NOK",
    "denmark": "DKK", "dnk": "DKK", "dk": "DKK",
    "poland": "PLN", "pol": "PLN", "pl": "PLN",
    "czech republic": "CZK", "cze": "CZK", "cz": "CZK",
    "hungary": "HUF", "hun": "HUF", "hu": "HUF",
    "romania": "RON", "rou": "RON", "ro": "RON",
    "bulgaria": "BGN", "bgr": "BGN", "bg": "BGN",
}


def _resolve_currency(location: str) -> str:
    """国名から通貨コードを解決"""
    loc = location.lower().strip()
    if loc in COUNTRY_CURRENCY:
        return COUNTRY_CURRENCY[loc]
    for name, code in COUNTRY_CURRENCY.items():
        if loc in name or name in loc:
            return code
    # 3文字ならそのまま通貨コードとして使う
    if len(loc) == 3 and loc.isalpha():
        return loc.upper()
    return ""


def fetch_latest_rate(base: str = "USD", target: str = "JPY") -> dict:
    """最新為替レート取得"""
    try:
        resp = requests.get(f"{FRANKFURTER_BASE}/latest",
                            params={"from": base, "to": target}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "base": data.get("base"),
            "date": data.get("date"),
            "rate": data.get("rates", {}).get(target),
        }
    except Exception as e:
        print(f"Frankfurter API error: {e}")
        return {}


def fetch_historical_rates(base: str = "USD", target: str = "JPY", days: int = 90) -> list[dict]:
    """過去の為替レート取得"""
    end = datetime.utcnow().strftime("%Y-%m-%d")
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        resp = requests.get(f"{FRANKFURTER_BASE}/{start}..{end}",
                            params={"from": base, "to": target}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for date_str, rates in sorted(data.get("rates", {}).items()):
            results.append({
                "date": date_str,
                "rate": rates.get(target),
            })
        return results
    except Exception as e:
        print(f"Frankfurter historical error: {e}")
        return []


def calculate_currency_volatility(base: str = "USD", target: str = "JPY", days: int = 90) -> dict:
    """通貨ボラティリティ算出"""
    rates = fetch_historical_rates(base, target, days)

    if len(rates) < 10:
        return {"volatility": 0, "trend": "unknown", "data_points": len(rates)}

    values = [r["rate"] for r in rates if r["rate"]]
    if not values:
        return {"volatility": 0, "trend": "unknown", "data_points": 0}

    # 日次変動率
    daily_changes = []
    for i in range(1, len(values)):
        if values[i-1] != 0:
            change_pct = (values[i] - values[i-1]) / values[i-1] * 100
            daily_changes.append(change_pct)

    if not daily_changes:
        return {"volatility": 0, "trend": "stable", "data_points": len(values)}

    volatility = statistics.stdev(daily_changes) if len(daily_changes) > 1 else 0
    avg_change = statistics.mean(daily_changes)

    # トレンド判定
    first_half = values[:len(values)//2]
    second_half = values[len(values)//2:]
    first_avg = statistics.mean(first_half)
    second_avg = statistics.mean(second_half)

    change_pct = (second_avg - first_avg) / first_avg * 100 if first_avg else 0

    if change_pct > 5:
        trend = "weakening"  # 対ドルで通貨安
    elif change_pct < -5:
        trend = "strengthening"
    else:
        trend = "stable"

    return {
        "volatility": round(volatility, 4),
        "avg_daily_change_pct": round(avg_change, 4),
        "period_change_pct": round(change_pct, 2),
        "trend": trend,
        "latest_rate": values[-1] if values else None,
        "min_rate": min(values),
        "max_rate": max(values),
        "data_points": len(values),
    }


def get_currency_risk_for_location(location: str) -> dict:
    """通貨リスク評価"""
    currency = _resolve_currency(location)
    if not currency or currency == "USD":
        return {"score": 0, "currency": currency, "evidence": []}

    vol = calculate_currency_volatility("USD", currency, days=90)
    if not vol or vol.get("volatility", 0) == 0:
        return {"score": 0, "currency": currency, "evidence": ["為替データ取得不可"]}

    # ボラティリティベースのスコア算出
    volatility = vol["volatility"]
    score = 0
    if volatility > 3.0:
        score = 90  # 極端なボラティリティ
    elif volatility > 2.0:
        score = 70
    elif volatility > 1.0:
        score = 50
    elif volatility > 0.5:
        score = 30
    elif volatility > 0.3:
        score = 15
    else:
        score = 0

    # 急激な通貨安はリスク追加
    period_change = abs(vol.get("period_change_pct", 0))
    if period_change > 15:
        score = min(100, score + 20)
    elif period_change > 10:
        score = min(100, score + 10)

    evidence = [
        f"通貨: {currency}/USD",
        f"90日間ボラティリティ: {volatility:.4f}%",
        f"期間変動: {vol.get('period_change_pct', 0):.2f}% ({vol.get('trend', 'N/A')})",
        f"レート範囲: {vol.get('min_rate', 'N/A')} - {vol.get('max_rate', 'N/A')}",
    ]

    return {
        "score": score,
        "currency": currency,
        "volatility": vol,
        "evidence": evidence,
    }
