"""タイ インバウンド統計クライアント
一次: MOTS (Ministry of Tourism and Sports) 月次Excel
二次: World Bank ST.INT.ARVL
三次: ハードコード実績値

2024年実績: 約3,500万人、中国からのシェア20-25%
"""
import requests
from datetime import datetime
from typing import Optional

# MOTS 統計ページ
MOTS_STATS_URL = "https://www.mots.go.th/news/category/758"

# World Bank API
WB_API_BASE = "https://api.worldbank.org/v2"

# ハードコード年次データ（人数）
ANNUAL_ARRIVALS = {
    "2019": 39800000,
    "2020": 6700000,
    "2021": 428000,
    "2022": 11200000,
    "2023": 28200000,
    "2024": 35000000,
}

# 国籍別シェア推定（2024年ベース、上位送客国）
NATIONALITY_SHARES = {
    "CHN": 0.200,  # 中国: 約700万人
    "MYS": 0.110,  # マレーシア
    "IND": 0.080,  # インド
    "KOR": 0.060,  # 韓国
    "RUS": 0.055,  # ロシア
    "JPN": 0.035,  # 日本: 約120万人
    "USA": 0.030,
    "GBR": 0.025,
    "LAO": 0.025,
    "SGP": 0.022,
    "VNM": 0.020,
    "DEU": 0.018,
    "AUS": 0.017,
    "TWN": 0.015,
    "HKG": 0.012,
    "FRA": 0.012,
    "IDN": 0.011,
    "KHM": 0.010,
    "MMR": 0.010,
    "OTHER": 0.243,
}

# 月別構成比（タイの観光シーズナリティ — 乾季11-2月がピーク）
MONTHLY_RATIO = {
    1: 0.110, 2: 0.100, 3: 0.090, 4: 0.070,
    5: 0.060, 6: 0.055, 7: 0.070, 8: 0.075,
    9: 0.060, 10: 0.080, 11: 0.100, 12: 0.130,
}


def _fetch_wb_arrivals(years=10):
    """World Bank ST.INT.ARVL でタイのインバウンド到着者数を取得"""
    url = f"{WB_API_BASE}/country/TH/indicator/ST.INT.ARVL"
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
        print(f"[ThailandInbound] WB API error: {e}")
        return {}


def _fetch_mots_monthly(year, month):
    """MOTS月次Excelからの取得を試行（スクレイピング）
    MOTSサイトは構造が変わりやすいため、失敗時はNoneを返す
    """
    try:
        # MOTSの月次統計ページからExcelリンクを探索
        resp = requests.get(MOTS_STATS_URL, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SCRI/1.3)"
        })
        if resp.status_code != 200:
            return None
        # Excelリンクのパターンマッチ（サイト構造依存）
        # 実際のExcelパースは openpyxl 等が必要
        # 現時点ではフォールバックに委ねる
        return None
    except Exception as e:
        print(f"[ThailandInbound] MOTS scrape error: {e}")
        return None


class ThailandInboundClient:
    """タイ インバウンド統計クライアント"""

    def __init__(self):
        self._wb_cache = None

    def _get_wb_data(self):
        """WBデータをキャッシュ付きで取得"""
        if self._wb_cache is None:
            self._wb_cache = _fetch_wb_arrivals()
        return self._wb_cache

    def _resolve_annual(self, year):
        """年次インバウンド数を解決（WB → ハードコード）"""
        y_str = str(year)
        # WB API
        wb = self._get_wb_data()
        if y_str in wb:
            return wb[y_str], "world_bank"
        # ハードコード
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
        # MOTS月次データを試行
        mots_data = _fetch_mots_monthly(year, month)
        if mots_data:
            return {
                "destination": "THA",
                "year": year,
                "month": month,
                "arrivals": mots_data,
                "source": "mots_monthly",
            }

        # 年次データから月次推定
        annual, source = self._resolve_annual(year)
        if annual is None:
            return {
                "destination": "THA",
                "year": year,
                "month": month,
                "arrivals": None,
                "source": "no_data",
            }

        ratio = MONTHLY_RATIO.get(month, 1.0 / 12)
        monthly_est = int(annual * ratio)

        return {
            "destination": "THA",
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
                "destination": "THA",
                "source_country": country,
                "year": year,
                "month": month,
                "arrivals": int(base * share),
                "share_pct": round(share * 100, 1),
                "data_source": source,
                "note": "シェア推定値（TAT年次レポートベース）",
            })

        # 降順ソート
        results.sort(key=lambda x: x["arrivals"], reverse=True)
        return results

    async def get_annual_summary(self, year=None):
        """年次サマリー"""
        if year is None:
            year = datetime.now().year
        annual, source = self._resolve_annual(year)
        # 前年比
        prev, _ = self._resolve_annual(year - 1)
        yoy = round(annual / prev * 100 - 100, 1) if annual and prev and prev > 0 else None
        # 2019年比回復率
        pre_covid = ANNUAL_ARRIVALS.get("2019", 39800000)
        recovery = round(annual / pre_covid * 100, 1) if annual else None

        return {
            "destination": "THA",
            "destination_name": "Thailand",
            "year": year,
            "total_arrivals": annual,
            "yoy_pct": yoy,
            "recovery_vs_2019_pct": recovery,
            "source": source,
            "top_markets": ["CHN", "MYS", "IND", "KOR", "RUS"],
            "japan_share_pct": round(NATIONALITY_SHARES.get("JPN", 0) * 100, 1),
        }
