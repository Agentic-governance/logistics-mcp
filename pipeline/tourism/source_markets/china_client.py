"""中国アウトバウンド統計クライアント (A-1)
ソース:
  1. NBS英語API: https://data.stats.gov.cn/english/easyquery.htm
  2. World Bank ST.INT.DPRT フォールバック
  3. ハードコード既知値（2019年1.55億人、2024年コロナ前80-90%回復）

上位目的地: 香港・マカオ・台湾・タイ・日本・韓国
"""
import requests
from datetime import datetime
from typing import Optional

WB_API_BASE = "https://api.worldbank.org/v2"


class ChinaSourceMarketClient:
    """中国アウトバウンド統計"""

    ISO3 = "CHN"
    NAME = "China"

    # 年次アウトバウンド出国者数（実績 + 推計）
    # NBS / CNTA 公表値ベース
    ANNUAL_DATA = {
        2019: 154_630_000,  # コロナ前ピーク（NBS公表1.55億人）
        2020: 20_334_000,   # コロナ激減
        2021: 25_622_000,
        2022: 42_920_000,
        2023: 87_260_000,   # 回復期
        2024: 130_000_000,  # コロナ前80-90%水準（推計）
        2025: 145_000_000,  # 推計
    }

    # 月別シーズナリティ比率（春節・国慶節ピーク）
    MONTHLY_RATIO = {
        1: 0.090, 2: 0.100, 3: 0.075, 4: 0.080,
        5: 0.085, 6: 0.075, 7: 0.095, 8: 0.090,
        9: 0.075, 10: 0.100, 11: 0.070, 12: 0.065,
    }

    # 目的地別シェア（中国アウトバウンド全体に対する割合, 2024年推計）
    # 香港・マカオ含む「出境」ベースのため国際旅行のみだとシェアが変わる
    DESTINATION_SHARES = {
        2024: {
            "HKG": {"name": "Hong Kong", "visitors": 43_900_000, "share_pct": 33.8},
            "MAC": {"name": "Macau", "visitors": 22_800_000, "share_pct": 17.5},
            "TWN": {"name": "Taiwan", "visitors": 2_770_284, "share_pct": 2.1},
            "THA": {"name": "Thailand", "visitors": 6_700_000, "share_pct": 5.2},
            "JPN": {"name": "Japan", "visitors": 6_962_800, "share_pct": 5.4},
            "KOR": {"name": "South Korea", "visitors": 4_800_000, "share_pct": 3.7},
            "SGP": {"name": "Singapore", "visitors": 2_100_000, "share_pct": 1.6},
            "MYS": {"name": "Malaysia", "visitors": 3_200_000, "share_pct": 2.5},
            "VNM": {"name": "Vietnam", "visitors": 2_800_000, "share_pct": 2.2},
            "IDN": {"name": "Indonesia", "visitors": 1_500_000, "share_pct": 1.2},
        },
        2023: {
            "HKG": {"name": "Hong Kong", "visitors": 26_900_000, "share_pct": 30.8},
            "MAC": {"name": "Macau", "visitors": 17_100_000, "share_pct": 19.6},
            "TWN": {"name": "Taiwan", "visitors": 252_000, "share_pct": 0.3},
            "THA": {"name": "Thailand", "visitors": 3_500_000, "share_pct": 4.0},
            "JPN": {"name": "Japan", "visitors": 2_425_900, "share_pct": 2.8},
            "KOR": {"name": "South Korea", "visitors": 2_100_000, "share_pct": 2.4},
        },
        2019: {
            "HKG": {"name": "Hong Kong", "visitors": 51_000_000, "share_pct": 33.0},
            "MAC": {"name": "Macau", "visitors": 28_600_000, "share_pct": 18.5},
            "TWN": {"name": "Taiwan", "visitors": 2_714_065, "share_pct": 1.8},
            "THA": {"name": "Thailand", "visitors": 10_994_721, "share_pct": 7.1},
            "JPN": {"name": "Japan", "visitors": 9_594_394, "share_pct": 6.2},
            "KOR": {"name": "South Korea", "visitors": 6_023_021, "share_pct": 3.9},
            "VNM": {"name": "Vietnam", "visitors": 5_800_000, "share_pct": 3.8},
            "SGP": {"name": "Singapore", "visitors": 3_627_000, "share_pct": 2.3},
            "MYS": {"name": "Malaysia", "visitors": 3_114_000, "share_pct": 2.0},
            "IDN": {"name": "Indonesia", "visitors": 2_072_000, "share_pct": 1.3},
        },
    }

    # ------------------------------------------------------------------
    # 一次API取得
    # ------------------------------------------------------------------

    def _fetch_nbs(self, year=None):
        """NBS英語APIから出国者数を取得（try/except必須）"""
        try:
            url = "https://data.stats.gov.cn/english/easyquery.htm"
            params = {
                "m": "QueryData",
                "dbcode": "hgnd",
                "rowcode": "zb",
                "colcode": "sj",
                "wds": "[]",
                "dfwds": '[{"wdcode":"zb","valuecode":"A0P01"}]',
            }
            resp = requests.get(
                url, params=params, timeout=10,
                headers={"User-Agent": "SCRI/1.3.0"}
            )
            if resp.status_code == 200:
                data = resp.json()
                # NBS APIレスポンス: returndata.datanodes[].data.data
                nodes = data.get("returndata", {}).get("datanodes", [])
                results = {}
                for node in nodes:
                    val = node.get("data", {}).get("data", 0)
                    wds = node.get("wds", [])
                    for w in wds:
                        if w.get("wdcode") == "sj":
                            yr = int(w.get("valuecode", "0")[:4])
                            if val and val > 0:
                                results[yr] = int(val * 10000)  # 万人単位→人
                if results:
                    return results
        except Exception as e:
            print(f"[ChinaSourceMarket] NBS API error: {e}")
        return None

    def _fetch_worldbank(self, years=10):
        """World Bank ST.INT.DPRT フォールバック"""
        try:
            url = f"{WB_API_BASE}/country/CN/indicator/ST.INT.DPRT"
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
            print(f"[ChinaSourceMarket] World Bank API error: {e}")
        return None

    def _get_annual_value(self, year):
        """年次データを取得（NBS → WB → ハードコード）"""
        # NBS
        nbs = self._fetch_nbs(year)
        if nbs and year in nbs:
            return nbs[year], "NBS (data.stats.gov.cn)"

        # World Bank
        wb = self._fetch_worldbank()
        if wb and year in wb:
            return wb[year], "World Bank WDI (ST.INT.DPRT)"

        # ハードコードフォールバック
        if year in self.ANNUAL_DATA:
            return self.ANNUAL_DATA[year], "hardcoded (NBS/CNTA公表値ベース)"

        # 最新ハードコード
        if self.ANNUAL_DATA:
            latest_yr = max(self.ANNUAL_DATA.keys())
            return self.ANNUAL_DATA[latest_yr], f"hardcoded (latest={latest_yr})"

        return None, "no_data"

    # ------------------------------------------------------------------
    # 共通インターフェース
    # ------------------------------------------------------------------

    async def get_outbound_stats(self, year=None, month=None):
        """中国アウトバウンド出国者数

        Args:
            year: 対象年（Noneなら最新利用可能年）
            month: 対象月（Noneなら年間合計）

        Returns:
            dict: {country, year, month, departures, source, recovery_rate}
        """
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

        # コロナ前比較（回復率）
        pre_covid = self.ANNUAL_DATA.get(2019, 154_630_000)
        recovery_rate = round(departures / pre_covid * 100, 1) if pre_covid else None

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
            }

        return {
            "country": self.ISO3,
            "country_name": self.NAME,
            "year": year,
            "month": None,
            "departures": departures,
            "source": source,
            "recovery_rate_vs_2019": recovery_rate,
        }

    async def get_historical(self, years_back=5):
        """年次トレンド（過去N年分）

        Returns:
            list[dict]: [{year, departures, source, yoy_change_pct}]
        """
        current_year = datetime.now().year
        start_year = current_year - years_back

        # APIデータ取得試行
        api_data = self._fetch_worldbank(years=years_back + 2)

        results = []
        prev_val = None
        for yr in sorted(self.ANNUAL_DATA.keys()):
            if yr < start_year:
                prev_val = self.ANNUAL_DATA[yr]
                continue
            if yr > current_year:
                continue

            # APIデータがあればそちらを優先
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
        """中国人アウトバウンドの目的地別ランキング

        Args:
            year: 対象年（Noneなら最新利用可能年）

        Returns:
            list[dict]: [{rank, destination, destination_name, visitors, share_pct}]
        """
        if year is None:
            year = max(self.DESTINATION_SHARES.keys())

        # 指定年がなければ最近年を使用
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
