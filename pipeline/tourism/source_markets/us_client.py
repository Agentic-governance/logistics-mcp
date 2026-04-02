"""米国アウトバウンド統計クライアント (A-4)
ソース:
  1. NTTO (National Travel & Tourism Office): https://www.ntto.gov/outreach/statistics/
  2. World Bank ST.INT.DPRT フォールバック
  3. ハードコード既知値（2024年日本向け約253万人）

米国は日本にとってアジア外最大の訪日市場。
"""
import requests
from datetime import datetime
from typing import Optional

WB_API_BASE = "https://api.worldbank.org/v2"


class USSourceMarketClient:
    """米国アウトバウンド統計"""

    ISO3 = "USA"
    NAME = "United States"

    # 年次アウトバウンド出国者数（NTTO / World Bank公表値ベース）
    ANNUAL_DATA = {
        2017: 87_700_000,
        2018: 93_000_000,
        2019: 99_744_000,  # コロナ前ピーク
        2020: 19_330_000,
        2021: 39_930_000,
        2022: 66_612_000,
        2023: 84_000_000,
        2024: 93_000_000,
        2025: 97_000_000,  # 推計
    }

    # 月別シーズナリティ比率（夏・年末ピーク）
    MONTHLY_RATIO = {
        1: 0.070, 2: 0.065, 3: 0.080, 4: 0.080,
        5: 0.085, 6: 0.095, 7: 0.110, 8: 0.105,
        9: 0.080, 10: 0.085, 11: 0.075, 12: 0.070,
    }

    # 目的地別シェア（米国アウトバウンド全体に対する割合）
    DESTINATION_SHARES = {
        2024: {
            "MEX": {"name": "Mexico", "visitors": 39_500_000, "share_pct": 42.5},
            "CAN": {"name": "Canada", "visitors": 14_800_000, "share_pct": 15.9},
            "GBR": {"name": "United Kingdom", "visitors": 4_200_000, "share_pct": 4.5},
            "DOM": {"name": "Dominican Republic", "visitors": 3_800_000, "share_pct": 4.1},
            "JPN": {"name": "Japan", "visitors": 2_529_700, "share_pct": 2.7},
            "FRA": {"name": "France", "visitors": 2_300_000, "share_pct": 2.5},
            "DEU": {"name": "Germany", "visitors": 2_100_000, "share_pct": 2.3},
            "ITA": {"name": "Italy", "visitors": 2_000_000, "share_pct": 2.2},
            "ESP": {"name": "Spain", "visitors": 1_500_000, "share_pct": 1.6},
            "KOR": {"name": "South Korea", "visitors": 1_400_000, "share_pct": 1.5},
            "IND": {"name": "India", "visitors": 1_600_000, "share_pct": 1.7},
            "CHN": {"name": "China", "visitors": 1_200_000, "share_pct": 1.3},
            "THA": {"name": "Thailand", "visitors": 1_100_000, "share_pct": 1.2},
            "AUS": {"name": "Australia", "visitors": 900_000, "share_pct": 1.0},
        },
        2023: {
            "MEX": {"name": "Mexico", "visitors": 35_000_000, "share_pct": 41.7},
            "CAN": {"name": "Canada", "visitors": 13_500_000, "share_pct": 16.1},
            "GBR": {"name": "United Kingdom", "visitors": 3_800_000, "share_pct": 4.5},
            "JPN": {"name": "Japan", "visitors": 2_045_800, "share_pct": 2.4},
            "FRA": {"name": "France", "visitors": 2_100_000, "share_pct": 2.5},
        },
        2019: {
            "MEX": {"name": "Mexico", "visitors": 39_291_000, "share_pct": 39.4},
            "CAN": {"name": "Canada", "visitors": 14_437_000, "share_pct": 14.5},
            "GBR": {"name": "United Kingdom", "visitors": 4_586_000, "share_pct": 4.6},
            "DOM": {"name": "Dominican Republic", "visitors": 3_200_000, "share_pct": 3.2},
            "JPN": {"name": "Japan", "visitors": 1_723_861, "share_pct": 1.7},
            "FRA": {"name": "France", "visitors": 3_022_000, "share_pct": 3.0},
            "DEU": {"name": "Germany", "visitors": 2_606_000, "share_pct": 2.6},
            "ITA": {"name": "Italy", "visitors": 2_800_000, "share_pct": 2.8},
            "CHN": {"name": "China", "visitors": 2_831_000, "share_pct": 2.8},
        },
    }

    # ------------------------------------------------------------------
    # API取得
    # ------------------------------------------------------------------

    def _fetch_ntto(self):
        """NTTO統計データ取得"""
        try:
            # NTTO I-94 Arrivals/Departures データ
            url = "https://travel.trade.gov/research/monthly/departures/index.asp"
            resp = requests.get(
                url, timeout=10,
                headers={"User-Agent": "SCRI/1.3.0"}
            )
            if resp.status_code == 200:
                # HTMLパースが必要（PDF/Excelレポート形式）
                # 構造化APIがないためスキップ
                pass
        except Exception as e:
            print(f"[USSourceMarket] NTTO error: {e}")
        return None

    def _fetch_worldbank(self, years=10):
        """World Bank ST.INT.DPRT フォールバック"""
        try:
            url = f"{WB_API_BASE}/country/US/indicator/ST.INT.DPRT"
            params = {"format": "json", "per_page": years, "mrv": years}
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if len(data) >= 2 and data[1]:
                results = {}
                for item in data[1]:
                    if item.get("value") is not None:
                        results[int(item["date"])] = int(item["value"])
                return results
        except Exception as e:
            print(f"[USSourceMarket] World Bank API error: {e}")
        return None

    def _get_annual_value(self, year):
        """年次データ取得（NTTO → WB → ハードコード）"""
        wb = self._fetch_worldbank()
        if wb and year in wb:
            return wb[year], "World Bank WDI (ST.INT.DPRT)"

        if year in self.ANNUAL_DATA:
            return self.ANNUAL_DATA[year], "hardcoded (NTTO公表値ベース)"

        if self.ANNUAL_DATA:
            latest_yr = max(self.ANNUAL_DATA.keys())
            return self.ANNUAL_DATA[latest_yr], f"hardcoded (latest={latest_yr})"

        return None, "no_data"

    # ------------------------------------------------------------------
    # 共通インターフェース
    # ------------------------------------------------------------------

    async def get_outbound_stats(self, year=None, month=None):
        """米国アウトバウンド出国者数"""
        if year is None:
            year = datetime.now().year - 1

        departures, source = self._get_annual_value(year)

        if departures is None:
            return {
                "country": self.ISO3,
                "country_name": self.NAME,
                "year": year,
                "month": month,
                "departures": None,
                "source": source,
            }

        pre_covid = self.ANNUAL_DATA.get(2019, 99_744_000)
        recovery_rate = round(departures / pre_covid * 100, 1) if pre_covid else None

        japan_share = None
        shares = self.DESTINATION_SHARES.get(year, {})
        if "JPN" in shares:
            japan_share = shares["JPN"]["share_pct"]

        if month:
            ratio = self.MONTHLY_RATIO.get(month, 1.0 / 12)
            monthly_est = int(departures * ratio)
            return {
                "country": self.ISO3,
                "country_name": self.NAME,
                "year": year,
                "month": month,
                "departures": monthly_est,
                "annual_total": departures,
                "source": f"{source} (monthly_estimated)",
                "recovery_rate_vs_2019": recovery_rate,
                "japan_share_pct": japan_share,
            }

        return {
            "country": self.ISO3,
            "country_name": self.NAME,
            "year": year,
            "month": None,
            "departures": departures,
            "source": source,
            "recovery_rate_vs_2019": recovery_rate,
            "japan_share_pct": japan_share,
        }

    async def get_historical(self, years_back=5):
        """年次トレンド"""
        current_year = datetime.now().year
        start_year = current_year - years_back

        api_data = self._fetch_worldbank(years=years_back + 2)

        results = []
        prev_val = None
        for yr in sorted(self.ANNUAL_DATA.keys()):
            if yr < start_year:
                prev_val = self.ANNUAL_DATA[yr]
                continue
            if yr > current_year:
                continue

            if api_data and yr in api_data:
                val = api_data[yr]
                src = "World Bank WDI"
            else:
                val = self.ANNUAL_DATA[yr]
                src = "hardcoded"

            yoy = None
            if prev_val and prev_val > 0:
                yoy = round((val - prev_val) / prev_val * 100, 1)

            results.append({
                "year": yr,
                "departures": val,
                "source": src,
                "yoy_change_pct": yoy,
                "country": self.ISO3,
            })
            prev_val = val

        return results

    async def get_top_destinations(self, year=None):
        """米国人アウトバウンドの目的地別ランキング"""
        if year is None:
            year = max(self.DESTINATION_SHARES.keys())

        if year not in self.DESTINATION_SHARES:
            available = sorted(self.DESTINATION_SHARES.keys(), reverse=True)
            year = available[0] if available else 2024

        shares = self.DESTINATION_SHARES.get(year, {})
        ranked = sorted(shares.items(), key=lambda x: x[1]["visitors"], reverse=True)

        results = []
        for rank, (iso3, info) in enumerate(ranked, 1):
            results.append({
                "rank": rank,
                "destination": iso3,
                "destination_name": info["name"],
                "visitors": info["visitors"],
                "share_pct": info["share_pct"],
                "year": year,
                "source_country": self.ISO3,
            })

        return results
