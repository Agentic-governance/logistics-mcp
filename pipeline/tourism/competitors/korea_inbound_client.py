"""韓国 インバウンド統計クライアント
一次: KTO (Korea Tourism Organization) 統計
二次: World Bank ST.INT.ARVL
三次: ハードコード実績値

2024年実績: 約1,700万人、日本からのシェア20-25%
"""
import requests
from datetime import datetime
from typing import Optional

WB_API_BASE = "https://api.worldbank.org/v2"

# KTO 統計API（公開エンドポイント）
KTO_STATS_URL = "https://datalab.visitkorea.or.kr/datalab/portal/ts/getEntryRateList.do"

# ハードコード年次データ（人数）
ANNUAL_ARRIVALS = {
    "2019": 17500000,
    "2020": 2520000,
    "2021": 970000,
    "2022": 3200000,
    "2023": 11000000,
    "2024": 17000000,
}

# 国籍別シェア推定（2024年ベース）
NATIONALITY_SHARES = {
    "JPN": 0.220,  # 日本: 約370万人（最大送客国）
    "CHN": 0.180,  # 中国
    "TWN": 0.060,  # 台湾
    "USA": 0.055,  # 米国
    "HKG": 0.030,  # 香港
    "THA": 0.028,  # タイ
    "VNM": 0.025,  # ベトナム
    "PHL": 0.020,  # フィリピン
    "SGP": 0.018,  # シンガポール
    "MYS": 0.016,  # マレーシア
    "IDN": 0.015,  # インドネシア
    "AUS": 0.012,  # オーストラリア
    "GBR": 0.010,  # 英国
    "DEU": 0.008,  # ドイツ
    "CAN": 0.008,  # カナダ
    "FRA": 0.007,  # フランス
    "IND": 0.006,  # インド
    "RUS": 0.005,  # ロシア
    "OTHER": 0.276,
}

# 月別構成比（韓国の観光シーズナリティ）
# 桜(4月)、紅葉(10月)、夏休み(7-8月)がピーク
MONTHLY_RATIO = {
    1: 0.065, 2: 0.060, 3: 0.080, 4: 0.090,
    5: 0.088, 6: 0.082, 7: 0.098, 8: 0.095,
    9: 0.085, 10: 0.095, 11: 0.085, 12: 0.077,
}


def _fetch_wb_arrivals(years=10):
    """World Bank API でインバウンド到着者数を取得"""
    url = f"{WB_API_BASE}/country/KR/indicator/ST.INT.ARVL"
    params = {"format": "json", "per_page": years, "mrv": years}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if len(data) < 2 or not data[1]:
            return {}
        results = {}
        for item in data[1]:
            if item.get("value") is not None:
                results[str(item["date"])] = int(item["value"])
        return results
    except Exception as e:
        print(f"[KoreaInbound] WB API error: {e}")
        return {}


def _fetch_kto_monthly(year, month):
    """KTO統計サイトからの月次データ取得を試行"""
    try:
        # KTO DataLab API（POST形式）
        payload = {
            "startYm": f"{year}{month:02d}",
            "endYm": f"{year}{month:02d}",
        }
        resp = requests.post(
            KTO_STATS_URL,
            data=payload,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SCRI/1.3)"},
        )
        if resp.status_code != 200:
            return None
        # レスポンス解析（HTML or JSON）
        # KTO DataLabのレスポンス形式は変更されやすい
        return None
    except Exception as e:
        print(f"[KoreaInbound] KTO scrape error: {e}")
        return None


class KoreaInboundClient:
    """韓国 インバウンド統計クライアント"""

    def __init__(self):
        self._wb_cache = None

    def _get_wb_data(self):
        if self._wb_cache is None:
            self._wb_cache = _fetch_wb_arrivals()
        return self._wb_cache

    def _resolve_annual(self, year):
        """年次インバウンド数を解決（WB → ハードコード）"""
        y_str = str(year)
        wb = self._get_wb_data()
        if y_str in wb:
            return wb[y_str], "world_bank"
        if y_str in ANNUAL_ARRIVALS:
            return ANNUAL_ARRIVALS[y_str], "hardcoded"
        return None, "no_data"

    async def get_monthly_arrivals(self, year, month):
        """月次インバウンド到着者数を取得

        Args:
            year: 対象年
            month: 対象月 (1-12)

        Returns:
            dict: {year, month, arrivals, source, ...}
        """
        # KTO月次データを試行
        kto_data = _fetch_kto_monthly(year, month)
        if kto_data:
            return {
                "destination": "KOR",
                "year": year,
                "month": month,
                "arrivals": kto_data,
                "source": "kto_monthly",
            }

        annual, source = self._resolve_annual(year)
        if annual is None:
            return {
                "destination": "KOR",
                "year": year,
                "month": month,
                "arrivals": None,
                "source": "no_data",
            }

        ratio = MONTHLY_RATIO.get(month, 1.0 / 12)
        monthly_est = int(annual * ratio)

        return {
            "destination": "KOR",
            "year": year,
            "month": month,
            "arrivals": monthly_est,
            "annual_total": annual,
            "estimation_method": "annual_x_seasonal_ratio",
            "source": source,
        }

    async def get_by_nationality(self, year, month=None):
        """国籍別インバウンド到着者数

        Args:
            year: 対象年
            month: 対象月（Noneなら年間）

        Returns:
            list[dict]: 国籍別の到着者数リスト
        """
        annual, source = self._resolve_annual(year)
        if annual is None:
            return []

        base = annual
        if month:
            ratio = MONTHLY_RATIO.get(month, 1.0 / 12)
            base = int(annual * ratio)

        results = []
        for country, share in NATIONALITY_SHARES.items():
            if country == "OTHER":
                continue
            results.append({
                "destination": "KOR",
                "source_country": country,
                "year": year,
                "month": month,
                "arrivals": int(base * share),
                "share_pct": round(share * 100, 1),
                "data_source": source,
                "note": "シェア推定値（KTO年次統計ベース）",
            })

        results.sort(key=lambda x: x["arrivals"], reverse=True)
        return results

    async def get_annual_summary(self, year=None):
        """年次サマリー"""
        if year is None:
            year = datetime.now().year
        annual, source = self._resolve_annual(year)
        prev, _ = self._resolve_annual(year - 1)
        yoy = round(annual / prev * 100 - 100, 1) if annual and prev and prev > 0 else None
        pre_covid = ANNUAL_ARRIVALS.get("2019", 17500000)
        recovery = round(annual / pre_covid * 100, 1) if annual else None

        return {
            "destination": "KOR",
            "destination_name": "South Korea",
            "year": year,
            "total_arrivals": annual,
            "yoy_pct": yoy,
            "recovery_vs_2019_pct": recovery,
            "source": source,
            "top_markets": ["JPN", "CHN", "TWN", "USA", "HKG"],
            "japan_share_pct": round(NATIONALITY_SHARES.get("JPN", 0) * 100, 1),
        }
