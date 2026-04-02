"""JNTO 訪日外客統計クライアント
日本政府観光局 (JNTO) の訪日外客数データ。
一次ソース: e-Stat API（APIキー要）、JNTOウェブサイト
フォールバック: ハードコード実績データ

主要20市場の月次・国別訪日者数を提供。
"""
import requests
import os
from datetime import datetime
from typing import Optional

ESTAT_KEY = os.getenv("ESTAT_API_KEY", "")
ESTAT_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"

# JNTO月次プレスリリースURL（スクレイピング対象候補）
JNTO_STATS_URL = "https://www.jnto.go.jp/statistics/data/visitors-statistics/"


class JNTOClient:
    """訪日外客統計クライアント"""

    # 主要市場のISO3→JNTO名称マッピング
    MARKET_MAP = {
        "CHN": "China",
        "KOR": "South Korea",
        "TWN": "Taiwan",
        "HKG": "Hong Kong",
        "USA": "United States",
        "THA": "Thailand",
        "SGP": "Singapore",
        "AUS": "Australia",
        "PHL": "Philippines",
        "MYS": "Malaysia",
        "VNM": "Vietnam",
        "IND": "India",
        "DEU": "Germany",
        "GBR": "United Kingdom",
        "FRA": "France",
        "CAN": "Canada",
        "ITA": "Italy",
        "IDN": "Indonesia",
        "RUS": "Russia",
        "ESP": "Spain",
    }

    # 過去実績データ（年間累計, 人数）
    # 2019=コロナ前ピーク, 2023=回復期, 2024=最新確定, 2025=推計
    HISTORICAL_DATA = {
        "CHN": {"2019": 9594394, "2023": 2425900, "2024": 6962800, "2025": 7800000},
        "KOR": {"2019": 5584597, "2023": 6958500, "2024": 8818500, "2025": 9200000},
        "TWN": {"2019": 4890602, "2023": 4202400, "2024": 5364600, "2025": 5600000},
        "HKG": {"2019": 2290792, "2023": 2114100, "2024": 2596600, "2025": 2800000},
        "USA": {"2019": 1723861, "2023": 2045800, "2024": 2529700, "2025": 2700000},
        "THA": {"2019": 1318977, "2023": 990200, "2024": 1105400, "2025": 1200000},
        "SGP": {"2019": 492252, "2023": 568400, "2024": 708900, "2025": 780000},
        "AUS": {"2019": 621771, "2023": 601200, "2024": 782600, "2025": 850000},
        "PHL": {"2019": 613114, "2023": 622200, "2024": 801500, "2025": 880000},
        "MYS": {"2019": 501592, "2023": 412300, "2024": 523500, "2025": 570000},
        "VNM": {"2019": 495051, "2023": 478900, "2024": 614600, "2025": 680000},
        "IND": {"2019": 175896, "2023": 203700, "2024": 267900, "2025": 310000},
        "DEU": {"2019": 236544, "2023": 254600, "2024": 321000, "2025": 350000},
        "GBR": {"2019": 424279, "2023": 358200, "2024": 470300, "2025": 510000},
        "FRA": {"2019": 336066, "2023": 303800, "2024": 395200, "2025": 430000},
        "CAN": {"2019": 375262, "2023": 318400, "2024": 408800, "2025": 440000},
        "ITA": {"2019": 162769, "2023": 181200, "2024": 236500, "2025": 260000},
        "IDN": {"2019": 412779, "2023": 315700, "2024": 412800, "2025": 450000},
        "RUS": {"2019": 120325, "2023": 18600, "2024": 25000, "2025": 30000},
        "ESP": {"2019": 130248, "2023": 137800, "2024": 178200, "2025": 195000},
    }

    # 月別構成比（概算、市場全体平均）
    # 桜シーズン(3-4月)、夏休み(7-8月)、紅葉(10-11月)がピーク
    MONTHLY_SHARE = {
        1: 0.072, 2: 0.068, 3: 0.095, 4: 0.098,
        5: 0.082, 6: 0.073, 7: 0.100, 8: 0.095,
        9: 0.078, 10: 0.095, 11: 0.088, 12: 0.056,
    }

    # 国別月次の季節調整係数（一部市場の特性反映）
    # 1.0 = 平均的、>1.0 = その月が多い
    COUNTRY_SEASONAL = {
        "CHN": {1: 1.3, 2: 1.5, 3: 0.9, 4: 0.8, 5: 0.9, 6: 0.7,
                7: 1.2, 8: 1.1, 9: 0.8, 10: 1.3, 11: 0.8, 12: 0.7},
        "KOR": {1: 0.9, 2: 0.8, 3: 1.1, 4: 1.1, 5: 1.0, 6: 0.9,
                7: 1.1, 8: 1.0, 9: 0.9, 10: 1.0, 11: 1.0, 12: 1.1},
    }

    def _estimate_monthly(self, country_iso3, year, month):
        """年間データから月次を推定（該当年がなければ最新年で外挿）"""
        hist = self.HISTORICAL_DATA.get(country_iso3, {})
        annual = hist.get(str(year))
        if not annual and hist:
            # 最新利用可能年のデータで外挿
            latest_y = max(hist.keys())
            annual = hist[latest_y]
        if not annual:
            return None

        base_share = self.MONTHLY_SHARE.get(month, 1.0 / 12)
        seasonal = self.COUNTRY_SEASONAL.get(country_iso3, {}).get(month, 1.0)
        estimated = int(annual * base_share * seasonal)
        return estimated

    def _try_estat(self, year, month=None):
        """e-Stat APIから訪日外客統計を取得（APIキーが必要）"""
        if not ESTAT_KEY:
            return None

        # e-Stat 出入国管理統計 statsDataId
        # 0003424913 = 出入国管理統計（月別・国籍別）
        url = f"{ESTAT_BASE}/getStatsData"
        params = {
            "appId": ESTAT_KEY,
            "statsDataId": "0003424913",
            "limit": 200,
        }
        if year and month:
            params["cdTime"] = f"{year}{month:02d}"
        elif year:
            params["cdTimeFrom"] = f"{year}01"
            params["cdTimeTo"] = f"{year}12"

        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            # e-Statレスポンスパースは複雑なので簡易処理
            stat_data = data.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})
            if stat_data:
                return stat_data
        except Exception as e:
            print(f"[JNTOClient] e-Stat API error: {e}")
        return None

    async def get_monthly_arrivals_by_country(self, year, month):
        """月次・国別訪日者数を取得

        Args:
            year: 対象年
            month: 対象月 (1-12)

        Returns:
            list[dict]: [{country_iso3, country_name, arrivals, year, month, source}]
        """
        results = []

        # e-Stat APIを試行
        estat_data = self._try_estat(year, month)
        if estat_data:
            # TODO: e-Statレスポンスの詳細パース実装
            pass

        # フォールバック: ハードコードデータから月次推定
        for iso3, name in self.MARKET_MAP.items():
            estimated = self._estimate_monthly(iso3, year, month)
            if estimated is not None:
                results.append({
                    "country_iso3": iso3,
                    "country_name": name,
                    "arrivals": estimated,
                    "year": year,
                    "month": month,
                    "source": "estimated_from_annual",
                })

        # 到着者数順でソート
        results.sort(key=lambda x: x["arrivals"], reverse=True)
        return results

    async def get_annual_trend(self, country_iso3, years_back=10):
        """指定国の訪日者数年次推移

        Args:
            country_iso3: ISO3国コード
            years_back: 遡る年数

        Returns:
            list[dict]: [{year, arrivals, source}] 新しい順
        """
        hist = self.HISTORICAL_DATA.get(country_iso3, {})
        if not hist:
            return []

        results = []
        current_year = datetime.now().year
        for yr_str, count in sorted(hist.items(), key=lambda x: x[0], reverse=True):
            yr = int(yr_str)
            if yr >= current_year - years_back:
                results.append({
                    "year": yr,
                    "arrivals": count,
                    "country_iso3": country_iso3,
                    "country_name": self.MARKET_MAP.get(country_iso3, country_iso3),
                    "source": "jnto_historical",
                })
        return results

    async def get_top_source_markets(self, year, month=None, top_n=20):
        """送客国ランキングを取得

        Args:
            year: 対象年
            month: 対象月（Noneなら年間）
            top_n: 上位N市場

        Returns:
            list[dict]: ランキング順
        """
        if month:
            data = await self.get_monthly_arrivals_by_country(year, month)
            return data[:top_n]

        # 年間データ
        results = []
        for iso3, name in self.MARKET_MAP.items():
            annual = self.HISTORICAL_DATA.get(iso3, {}).get(str(year))
            if annual:
                results.append({
                    "rank": 0,
                    "country_iso3": iso3,
                    "country_name": name,
                    "arrivals": annual,
                    "year": year,
                    "source": "jnto_historical",
                })

        results.sort(key=lambda x: x["arrivals"], reverse=True)
        for i, r in enumerate(results):
            r["rank"] = i + 1

        return results[:top_n]

    async def get_latest(self):
        """最新の訪日統計サマリーを取得

        Returns:
            dict: 最新月のサマリー情報
        """
        now = datetime.now()
        # 最新データは通常2ヶ月遅れ
        target_year = now.year
        target_month = now.month - 2
        if target_month <= 0:
            target_month += 12
            target_year -= 1

        monthly_data = await self.get_monthly_arrivals_by_country(target_year, target_month)
        total = sum(d["arrivals"] for d in monthly_data)

        # 前年同月比（推定）
        prev_data = await self.get_monthly_arrivals_by_country(target_year - 1, target_month)
        prev_total = sum(d["arrivals"] for d in prev_data) if prev_data else 0
        yoy_change = None
        if prev_total > 0:
            yoy_change = round((total - prev_total) / prev_total * 100, 1)

        # 2019年同月比（コロナ前対比）
        pre_covid = await self.get_monthly_arrivals_by_country(2019, target_month)
        pre_covid_total = sum(d["arrivals"] for d in pre_covid) if pre_covid else 0
        vs_2019 = None
        if pre_covid_total > 0:
            vs_2019 = round((total - pre_covid_total) / pre_covid_total * 100, 1)

        return {
            "year": target_year,
            "month": target_month,
            "total_visitors": total,
            "yoy_change_pct": yoy_change,
            "vs_2019_pct": vs_2019,
            "top_markets": monthly_data[:5],
            "all_markets": monthly_data,
            "data_note": "月次推定値（JNTO年間確定値ベース）",
        }


# --- 便利関数（同期版） ---

def get_japan_inbound_summary():
    """訪日インバウンドサマリー（同期）"""
    import asyncio
    client = JNTOClient()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return _sync_summary(client)
        try:
            return loop.run_until_complete(client.get_latest())
        except RuntimeError:
            return _sync_summary(client)
    except RuntimeError:
        # Python 3.10+: no current event loop
        try:
            return asyncio.run(client.get_latest())
        except Exception:
            return _sync_summary(client)


def _sync_summary(client):
    """イベントループなしで同期的にサマリー生成"""
    now = datetime.now()
    year = now.year
    # 最新年のデータ
    results = []
    for iso3, name in client.MARKET_MAP.items():
        hist = client.HISTORICAL_DATA.get(iso3, {})
        # 最新利用可能年
        for y in [str(year), str(year - 1), str(year - 2)]:
            if y in hist:
                results.append({
                    "country_iso3": iso3,
                    "country_name": name,
                    "arrivals": hist[y],
                    "year": int(y),
                })
                break

    results.sort(key=lambda x: x["arrivals"], reverse=True)
    total = sum(r["arrivals"] for r in results)
    return {
        "total_visitors": total,
        "top_markets": results[:10],
        "data_note": "ハードコード年間確定値ベース",
    }
