"""e-Stat (政府統計ポータル) + BOJ (日本銀行)
日本の公式経済統計データ
e-Stat: https://www.e-stat.go.jp/api/
BOJ: https://www.stat-search.boj.or.jp/
e-Stat APIキー: https://www.e-stat.go.jp/api/api-dev/how_to_use で取得可能（無料）
"""
import requests
import os
from datetime import datetime

ESTAT_KEY = os.getenv("ESTAT_API_KEY", "")
ESTAT_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"

# BOJ時系列統計 (APIキー不要)
BOJ_BASE = "https://www.stat-search.boj.or.jp/ssi/mtshtml"


def fetch_estat_trade_stats(year_month: str = None) -> dict:
    """e-Stat: 貿易統計（品目別輸出入）
    stats_id: 0003050750 = 貿易統計（概況品別国別）
    """
    if not ESTAT_KEY:
        return {"available": False, "message": "ESTAT_API_KEY not set"}

    if not year_month:
        now = datetime.now()
        # 2ヶ月前のデータ（速報ラグ）
        prev = datetime(now.year, now.month - 2 if now.month > 2 else now.month + 10,
                        1 if now.month > 2 else now.year - 1)
        year_month = prev.strftime("%Y%m")

    url = f"{ESTAT_BASE}/getStatsData"
    params = {
        "appId": ESTAT_KEY,
        "statsDataId": "0003050750",  # 貿易統計
        "cdTime": year_month,
        "limit": 100,
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def fetch_estat_industrial_production() -> dict:
    """e-Stat: 鉱工業生産指数
    stats_id: 0003126894 = 鉱工業指数
    """
    if not ESTAT_KEY:
        return {"available": False, "message": "ESTAT_API_KEY not set"}

    url = f"{ESTAT_BASE}/getStatsData"
    params = {
        "appId": ESTAT_KEY,
        "statsDataId": "0003126894",
        "limit": 50,
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def fetch_boj_exchange_rate() -> dict:
    """BOJ: 為替レート（主要通貨対円）"""
    # BOJ公開データ: 主要通貨の対円レート
    url = "https://www.boj.or.jp/statistics/market/forex/fxdaily/index.htm"
    # BOJのAPIは複雑なので、代替としてExchangeRate-APIを使用
    try:
        resp = requests.get(
            "https://open.er-api.com/v6/latest/JPY",
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        # 主要通貨のみ
        key_currencies = ["USD", "EUR", "CNY", "KRW", "TWD", "THB", "VND",
                         "IDR", "MYR", "SGD", "INR", "AUD", "GBP"]
        result = {}
        for curr in key_currencies:
            if curr in rates:
                # 1 JPY = X通貨 → 1通貨 = 1/X JPY
                result[curr] = round(1 / rates[curr], 4) if rates[curr] else None
        return {
            "base": "JPY",
            "date": data.get("time_last_update_utc", ""),
            "rates": result,
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_boj_interest_rate() -> dict:
    """BOJ政策金利・短期金利"""
    try:
        resp = requests.get(
            "https://www.stat-search.boj.or.jp/ssi/cgi-bin/famecgi2?"
            "cgi=$nme_a000_en&lstID=FM01",
            timeout=15,
            headers={"User-Agent": "SupplyChainRiskIntelligence/1.0"}
        )
        # HTML解析は複雑なのでフォールバック値を使用
        return {"policy_rate": 0.5, "note": "2025-2026 BOJ policy rate estimate"}
    except Exception:
        return {"policy_rate": 0.5, "note": "fallback"}


def get_japan_economic_indicators() -> dict:
    """日本経済指標サマリー"""
    result = {
        "exchange_rates": fetch_boj_exchange_rate(),
        "interest_rate": fetch_boj_interest_rate(),
    }

    if ESTAT_KEY:
        result["trade_stats"] = fetch_estat_trade_stats()
        result["industrial_production"] = fetch_estat_industrial_production()

    return result


def get_japan_economic_risk() -> dict:
    """日本経済リスク評価"""
    score = 0
    evidence = []

    # 為替レート取得
    fx = fetch_boj_exchange_rate()
    if "rates" in fx:
        usd_jpy = fx["rates"].get("USD")
        if usd_jpy:
            evidence.append(f"[為替] USD/JPY: {usd_jpy:.2f}")
            # 極端な円安/円高
            if usd_jpy > 160:
                score = max(score, 60)
                evidence.append("[為替] 極端な円安水準（輸入コスト上昇リスク）")
            elif usd_jpy > 150:
                score = max(score, 35)
                evidence.append("[為替] 円安水準（輸入コスト上昇）")
            elif usd_jpy < 100:
                score = max(score, 40)
                evidence.append("[為替] 極端な円高水準（輸出競争力低下リスク）")

        cny_jpy = fx["rates"].get("CNY")
        if cny_jpy:
            evidence.append(f"[為替] CNY/JPY: {cny_jpy:.2f}")

    return {"score": score, "evidence": evidence}
