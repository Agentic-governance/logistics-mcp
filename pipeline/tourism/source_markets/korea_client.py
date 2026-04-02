"""韓国アウトバウンド統計クライアント (A-2)
ソース:
  1. KTO (Korea Tourism Organization) / KOSIS API
  2. World Bank ST.INT.DPRT フォールバック
  3. ハードコード既知値（2024年日本向け約860万人＝アウトバウンドの20-25%）

韓国は日本最大の訪日市場（2024年約880万人）。
"""
import requests
from datetime import datetime
from typing import Optional

WB_API_BASE = "https://api.worldbank.org/v2"


class KoreaSourceMarketClient:
    """韓国アウトバウンド統計"""

    ISO3 = "KOR"
    NAME = "South Korea"

    # 年次アウトバウンド出国者数（KTO公表値ベース）
    ANNUAL_DATA = {
        2017: 26_496_447,
        2018: 28_695_983,
        2019: 28_714_247,  # コロナ前ピーク
        2020: 4_276_342,
        2021: 1_222_230,
        2022: 6_555_370,
        2023: 27_200_000,  # ほぼコロナ前水準に回復
        2024: 32_500_000,  # コロナ前超え（KTO速報ベース）
        2025: 34_000_000,  # 推計
    }

    # 月別シーズナリティ比率
    MONTHLY_RATIO = {
        1: 0.080, 2: 0.070, 3: 0.085, 4: 0.085,
        5: 0.085, 6: 0.085, 7: 0.100, 8: 0.095,
        9: 0.080, 10: 0.090, 11: 0.080, 12: 0.065,
    }

    # 目的地別シェア（韓国アウトバウンド全体に対する割合）
    DESTINATION_SHARES = {
        2024: {
            "JPN": {"name": "Japan", "visitors": 8_818_500, "share_pct": 27.1},
            "VNM": {"name": "Vietnam", "visitors": 3_600_000, "share_pct": 11.1},
            "THA": {"name": "Thailand", "visitors": 2_500_000, "share_pct": 7.7},
            "CHN": {"name": "China", "visitors": 2_300_000, "share_pct": 7.1},
            "PHL": {"name": "Philippines", "visitors": 2_100_000, "share_pct": 6.5},
            "USA": {"name": "United States", "visitors": 2_000_000, "share_pct": 6.2},
            "TWN": {"name": "Taiwan", "visitors": 1_200_000, "share_pct": 3.7},
            "SGP": {"name": "Singapore", "visitors": 900_000, "share_pct": 2.8},
            "IDN": {"name": "Indonesia", "visitors": 850_000, "share_pct": 2.6},
            "MYS": {"name": "Malaysia", "visitors": 800_000, "share_pct": 2.5},
            "AUS": {"name": "Australia", "visitors": 500_000, "share_pct": 1.5},
            "GUM": {"name": "Guam", "visitors": 480_000, "share_pct": 1.5},
        },
        2023: {
            "JPN": {"name": "Japan", "visitors": 6_958_500, "share_pct": 25.6},
            "VNM": {"name": "Vietnam", "visitors": 2_800_000, "share_pct": 10.3},
            "THA": {"name": "Thailand", "visitors": 1_900_000, "share_pct": 7.0},
            "CHN": {"name": "China", "visitors": 1_500_000, "share_pct": 5.5},
            "PHL": {"name": "Philippines", "visitors": 1_600_000, "share_pct": 5.9},
            "USA": {"name": "United States", "visitors": 1_800_000, "share_pct": 6.6},
        },
        2019: {
            "JPN": {"name": "Japan", "visitors": 5_584_597, "share_pct": 19.4},
            "VNM": {"name": "Vietnam", "visitors": 4_290_000, "share_pct": 14.9},
            "THA": {"name": "Thailand", "visitors": 1_890_000, "share_pct": 6.6},
            "CHN": {"name": "China", "visitors": 4_169_353, "share_pct": 14.5},
            "PHL": {"name": "Philippines", "visitors": 1_989_000, "share_pct": 6.9},
            "USA": {"name": "United States", "visitors": 2_356_000, "share_pct": 8.2},
            "TWN": {"name": "Taiwan", "visitors": 1_241_661, "share_pct": 4.3},
        },
    }

    # ------------------------------------------------------------------
    # API取得
    # ------------------------------------------------------------------

    def _fetch_kto(self):
        """KTO / KOSIS APIからデータ取得"""
        try:
            # KTO公開統計ページ（APIキー不要エンドポイント探索）
            url = "https://datalab.visitkorea.or.kr/datalab/portal/dep/getDepTourChart.do"
            params = {"startYmd": "2023", "endYmd": "2025"}
            resp = requests.get(
                url, params=params, timeout=10,
                headers={"User-Agent": "SCRI/1.3.0"}
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    # KTOレスポンスパース（JSONフォーマットが不定のためスキップ可）
                    if isinstance(data, dict) and data.get("items"):
                        results = {}
                        for item in data["items"]:
                            yr = item.get("year")
                            val = item.get("touNum") or item.get("value")
                            if yr and val:
                                results[int(yr)] = int(val)
                        if results:
                            return results
                except (ValueError, KeyError):
                    pass
        except Exception as e:
            print(f"[KoreaSourceMarket] KTO API error: {e}")
        return None

    def _fetch_worldbank(self, years=10):
        """World Bank ST.INT.DPRT フォールバック"""
        try:
            url = f"{WB_API_BASE}/country/KR/indicator/ST.INT.DPRT"
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
            print(f"[KoreaSourceMarket] World Bank API error: {e}")
        return None

    def _get_annual_value(self, year):
        """年次データ取得（KTO → WB → ハードコード）"""
        kto = self._fetch_kto()
        if kto and year in kto:
            return kto[year], "KTO (visitkorea.or.kr)"

        wb = self._fetch_worldbank()
        if wb and year in wb:
            return wb[year], "World Bank WDI (ST.INT.DPRT)"

        if year in self.ANNUAL_DATA:
            return self.ANNUAL_DATA[year], "hardcoded (KTO公表値ベース)"

        if self.ANNUAL_DATA:
            latest_yr = max(self.ANNUAL_DATA.keys())
            return self.ANNUAL_DATA[latest_yr], f"hardcoded (latest={latest_yr})"

        return None, "no_data"

    # ------------------------------------------------------------------
    # 共通インターフェース
    # ------------------------------------------------------------------

    async def get_outbound_stats(self, year=None, month=None):
        """韓国アウトバウンド出国者数"""
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

        pre_covid = self.ANNUAL_DATA.get(2019, 28_714_247)
        recovery_rate = round(departures / pre_covid * 100, 1) if pre_covid else None

        # 日本向けシェア推計
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
        """韓国人アウトバウンドの目的地別ランキング"""
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
