"""エネルギー・コモディティ価格モニタリング
FRED (Federal Reserve Economic Data) - 原油、天然ガス等
EIA (US Energy Information Administration) - エネルギー統計
IMF Primary Commodity Prices - 国際商品価格
すべてAPIキー不要 or 無料キーあり
"""
import requests
import os
from datetime import datetime, timedelta

# FRED API (無料キー: https://fred.stlouisfed.org/docs/api/api_key.html)
FRED_KEY = os.getenv("FRED_API_KEY", "")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# EIA API v2 (無料キー: https://www.eia.gov/opendata/register.php)
EIA_KEY = os.getenv("EIA_API_KEY", "")
EIA_BASE = "https://api.eia.gov/v2"

# 代替: World Bank Commodity Prices (キー不要)
WB_COMMODITY_URL = "https://api.worldbank.org/v2/country/WLD/indicator"

# IMF Primary Commodity Prices (キー不要)
IMF_PCPS_URL = "https://www.imf.org/external/datamapper/api/v1"


def fetch_fred_series(series_id: str, limit: int = 90) -> list[dict]:
    """FREDから時系列データ取得"""
    if not FRED_KEY:
        return []
    params = {
        "series_id": series_id,
        "api_key": FRED_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    try:
        resp = requests.get(FRED_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [
            {"date": o["date"], "value": float(o["value"])}
            for o in data.get("observations", [])
            if o.get("value") != "."
        ]
    except Exception:
        return []


# FRED主要シリーズ
FRED_SERIES = {
    "crude_oil_wti": "DCOILWTICO",      # WTI原油（日次）
    "crude_oil_brent": "DCOILBRENTEU",   # ブレント原油（日次）
    "natural_gas": "DHHNGSP",            # 天然ガス Henry Hub（日次）
    "gold": "GOLDAMGBD228NLBM",          # 金価格
    "copper": "PCOPPUSDM",               # 銅価格（月次）
    "wheat": "PWHEAMTUSDM",              # 小麦価格（月次）
    "corn": "PMAIZMTUSDM",              # トウモロコシ価格（月次）
    "rice": "PRICENPQUSDM",             # 米価格（月次）
    "cotton": "PCOTTINDUSDM",           # 綿花（月次）
    "iron_ore": "PIORECRUSDM",          # 鉄鉱石（月次）
    "aluminum": "PAABORUSDM",           # アルミニウム（月次）
    "nickel": "PNABORUSDM",             # ニッケル（月次）
    "rubber": "PRUBBUSDM",              # 天然ゴム（月次）
    "lng": "PNGASJPUSDM",              # LNG（日本向け、月次）
    "baltic_dry_index": "DBDI",         # バルチック海運指数
}


def fetch_eia_petroleum(series: str = "PET.RWTC.D") -> list[dict]:
    """EIA石油データ取得"""
    if not EIA_KEY:
        return []
    url = f"{EIA_BASE}/petroleum/pri/spt/data/"
    params = {
        "api_key": EIA_KEY,
        "frequency": "daily",
        "data[0]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 90,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", {}).get("data", [])
    except Exception:
        return []


def _calc_price_change(series: list[dict]) -> dict:
    """価格変動率を計算"""
    if len(series) < 2:
        return {"change_1d": 0, "change_7d": 0, "change_30d": 0, "latest": 0}

    latest = series[0]["value"]
    day1 = series[1]["value"] if len(series) > 1 else latest
    day7 = series[min(6, len(series)-1)]["value"] if len(series) > 6 else day1
    day30 = series[min(29, len(series)-1)]["value"] if len(series) > 29 else day7

    def pct(a, b):
        return ((a - b) / b * 100) if b else 0

    return {
        "latest": latest,
        "latest_date": series[0]["date"],
        "change_1d_pct": pct(latest, day1),
        "change_7d_pct": pct(latest, day7),
        "change_30d_pct": pct(latest, day30),
    }


def get_commodity_prices() -> dict:
    """主要コモディティ価格と変動率"""
    if not FRED_KEY:
        return {"available": False, "message": "FRED_API_KEY not set. Get free key at https://fred.stlouisfed.org/docs/api/api_key.html"}

    results = {}
    priority_series = ["crude_oil_wti", "crude_oil_brent", "natural_gas", "gold",
                       "iron_ore", "copper", "wheat", "lng", "baltic_dry_index"]
    for name in priority_series:
        sid = FRED_SERIES.get(name)
        if sid:
            data = fetch_fred_series(sid)
            if data:
                results[name] = _calc_price_change(data)

    return {"available": True, "commodities": results}


def get_energy_risk(country: str = None) -> dict:
    """エネルギー価格リスク評価"""
    prices = get_commodity_prices()
    if not prices.get("available"):
        return _get_energy_risk_static(country)

    score = 0
    evidence = []
    commodities = prices.get("commodities", {})

    # 原油価格急変
    for oil_key in ["crude_oil_wti", "crude_oil_brent"]:
        oil = commodities.get(oil_key, {})
        if oil:
            change_7d = abs(oil.get("change_7d_pct", 0))
            change_30d = abs(oil.get("change_30d_pct", 0))
            if change_7d > 15:
                score = max(score, 80)
                evidence.append(f"[エネルギー] {oil_key}: 7日間{oil['change_7d_pct']:+.1f}%変動（急変）")
            elif change_7d > 8:
                score = max(score, 50)
                evidence.append(f"[エネルギー] {oil_key}: 7日間{oil['change_7d_pct']:+.1f}%変動")
            elif change_30d > 20:
                score = max(score, 40)
                evidence.append(f"[エネルギー] {oil_key}: 30日間{oil['change_30d_pct']:+.1f}%変動")
            if oil.get("latest"):
                evidence.append(f"[エネルギー] {oil_key}: ${oil['latest']:.2f}/barrel ({oil.get('latest_date', '')})")

    # LNG価格
    lng = commodities.get("lng", {})
    if lng and lng.get("latest"):
        change_30d = abs(lng.get("change_30d_pct", 0))
        if change_30d > 25:
            score = max(score, 60)
            evidence.append(f"[エネルギー] LNG(日本向け): 30日間{lng['change_30d_pct']:+.1f}%変動")

    # バルチック海運指数
    bdi = commodities.get("baltic_dry_index", {})
    if bdi and bdi.get("latest"):
        change_7d = abs(bdi.get("change_7d_pct", 0))
        if change_7d > 20:
            score = max(score, 60)
            evidence.append(f"[海運] BDI: 7日間{bdi['change_7d_pct']:+.1f}%変動（海運コスト急変）")
        evidence.append(f"[海運] バルチック海運指数: {bdi['latest']:.0f} ({bdi.get('latest_date', '')})")

    # 鉄鉱石
    iron = commodities.get("iron_ore", {})
    if iron and iron.get("latest"):
        evidence.append(f"[素材] 鉄鉱石: ${iron['latest']:.2f}/ton")

    if not evidence:
        evidence.append("[エネルギー] コモディティ価格データなし")

    return {"score": min(100, score), "evidence": evidence, "prices": commodities}



# Energy import dependency scores (IEA/Our World in Data 2024)
# Higher = more dependent on energy imports = higher supply chain risk
ENERGY_IMPORT_DEPENDENCY = {
    "Japan": 72, "Singapore": 80, "South Korea": 68, "Taiwan": 65,
    "Germany": 55, "Italy": 58, "France": 35, "United Kingdom": 42,
    "Turkey": 65, "India": 45, "China": 30, "Thailand": 52,
    "Vietnam": 40, "Philippines": 50, "Bangladesh": 55, "Pakistan": 60,
    "Sri Lanka": 70, "Indonesia": 35, "Malaysia": 25, "Myanmar": 45,
    "Cambodia": 55, "Poland": 48, "Netherlands": 38, "Switzerland": 38,
    "United States": 15, "Canada": 10, "Australia": 18, "Brazil": 25,
    "Mexico": 20, "Colombia": 22, "Argentina": 28, "Chile": 55,
    "Venezuela": 12, "Russia": 5, "Saudi Arabia": 5, "UAE": 8,
    "Iran": 8, "Iraq": 10, "Qatar": 5, "Israel": 40,
    "Egypt": 30, "Nigeria": 30, "South Africa": 35, "Kenya": 60,
    "Ethiopia": 65, "South Sudan": 70, "Somalia": 75,
    "North Korea": 60, "Ukraine": 55, "Yemen": 65,
}
DEFAULT_ENERGY_SCORE = 45


# フォールバック: FREDキーなしでも使える簡易コモディティ情報
COMMODITY_THRESHOLDS = {
    "crude_oil": {"unit": "USD/barrel", "normal_low": 50, "normal_high": 90,
                  "high_alert": 100, "crisis": 120},
    "natural_gas": {"unit": "USD/MMBtu", "normal_low": 2.0, "normal_high": 5.0,
                    "high_alert": 8.0, "crisis": 12.0},
    "lng_japan": {"unit": "USD/MMBtu", "normal_low": 8, "normal_high": 15,
                  "high_alert": 25, "crisis": 40},
}


# Static fallback for when API keys are not available
def _get_energy_risk_static(country: str = None) -> dict:
    """Country-aware static energy risk. Uses energy import dependency when FRED API unavailable."""
    score = DEFAULT_ENERGY_SCORE  # default for unknown countries
    if country:
        for c, dep in ENERGY_IMPORT_DEPENDENCY.items():
            if c.lower() == country.lower() or country.lower() in c.lower() or c.lower() in country.lower():
                score = dep
                break
    evidence = [
        f"[エネルギー] エネルギー輸入依存度スコア {score}/100（IEA/OWID ベースライン）",
        "[エネルギー] ライブ価格データ未取得（FRED APIキー未設定）",
    ]
    return {"score": score, "evidence": evidence, "prices": {"source": "static_baseline"}}
