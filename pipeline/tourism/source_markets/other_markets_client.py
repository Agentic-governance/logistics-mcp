"""その他市場アウトバウンド統計クライアント群 (A-6)
対象:
  - 香港 (HKTB)
  - シンガポール (STB)
  - インド (MoT)
  - ドイツ (Destatis)
  - フランス (DGE)
  - 英国 (ONS)

World Bankフォールバック中心。各国一次APIは試行のみ。
"""
import requests
from datetime import datetime
from typing import Optional

WB_API_BASE = "https://api.worldbank.org/v2"


def _fetch_worldbank(iso2, years=10):
    """World Bank ST.INT.DPRT 共通取得"""
    try:
        url = f"{WB_API_BASE}/country/{iso2}/indicator/ST.INT.DPRT"
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
        print(f"[OtherMarkets] World Bank API error ({iso2}): {e}")
    return None


class _BaseOtherMarketClient:
    """その他市場共通基底クラス"""

    ISO3 = ""
    ISO2 = ""
    NAME = ""
    ANNUAL_DATA = {}
    MONTHLY_RATIO = {
        1: 0.075, 2: 0.070, 3: 0.080, 4: 0.085,
        5: 0.085, 6: 0.080, 7: 0.100, 8: 0.100,
        9: 0.085, 10: 0.090, 11: 0.080, 12: 0.070,
    }
    DESTINATION_SHARES = {}

    def _get_annual_value(self, year):
        """年次データ取得（WB → ハードコード）"""
        wb = _fetch_worldbank(self.ISO2)
        if wb and year in wb:
            return wb[year], "World Bank WDI (ST.INT.DPRT)"

        if year in self.ANNUAL_DATA:
            return self.ANNUAL_DATA[year], "hardcoded"

        if self.ANNUAL_DATA:
            latest_yr = max(self.ANNUAL_DATA.keys())
            return self.ANNUAL_DATA[latest_yr], f"hardcoded (latest={latest_yr})"

        return None, "no_data"

    async def get_outbound_stats(self, year=None, month=None):
        """アウトバウンド出国者数"""
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

        pre_covid = self.ANNUAL_DATA.get(2019)
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

        api_data = _fetch_worldbank(self.ISO2, years=years_back + 2)

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
        """目的地別ランキング"""
        if year is None:
            year = max(self.DESTINATION_SHARES.keys()) if self.DESTINATION_SHARES else 2024

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


# =====================================================================
# 香港
# =====================================================================

class HongKongSourceMarketClient(_BaseOtherMarketClient):
    """香港アウトバウンド統計（HKTB / World Bank）"""

    ISO3 = "HKG"
    ISO2 = "HK"
    NAME = "Hong Kong"

    ANNUAL_DATA = {
        2019: 10_003_000,
        2020: 1_200_000,
        2021: 800_000,
        2022: 2_500_000,
        2023: 8_500_000,
        2024: 9_800_000,
        2025: 10_200_000,
    }

    MONTHLY_RATIO = {
        1: 0.090, 2: 0.095, 3: 0.080, 4: 0.085,
        5: 0.080, 6: 0.075, 7: 0.095, 8: 0.090,
        9: 0.075, 10: 0.085, 11: 0.075, 12: 0.075,
    }

    DESTINATION_SHARES = {
        2024: {
            "CHN": {"name": "China (Mainland)", "visitors": 4_500_000, "share_pct": 45.9},
            "JPN": {"name": "Japan", "visitors": 2_596_600, "share_pct": 26.5},
            "KOR": {"name": "South Korea", "visitors": 650_000, "share_pct": 6.6},
            "THA": {"name": "Thailand", "visitors": 500_000, "share_pct": 5.1},
            "TWN": {"name": "Taiwan", "visitors": 480_000, "share_pct": 4.9},
            "SGP": {"name": "Singapore", "visitors": 200_000, "share_pct": 2.0},
        },
        2019: {
            "CHN": {"name": "China (Mainland)", "visitors": 5_000_000, "share_pct": 50.0},
            "JPN": {"name": "Japan", "visitors": 2_290_792, "share_pct": 22.9},
            "KOR": {"name": "South Korea", "visitors": 600_000, "share_pct": 6.0},
            "THA": {"name": "Thailand", "visitors": 550_000, "share_pct": 5.5},
            "TWN": {"name": "Taiwan", "visitors": 1_000_000, "share_pct": 10.0},
        },
    }


# =====================================================================
# シンガポール
# =====================================================================

class SingaporeSourceMarketClient(_BaseOtherMarketClient):
    """シンガポールアウトバウンド統計（STB / World Bank）"""

    ISO3 = "SGP"
    ISO2 = "SG"
    NAME = "Singapore"

    ANNUAL_DATA = {
        2019: 10_382_000,
        2020: 1_100_000,
        2021: 600_000,
        2022: 4_500_000,
        2023: 8_000_000,
        2024: 9_500_000,
        2025: 10_000_000,
    }

    MONTHLY_RATIO = {
        1: 0.080, 2: 0.075, 3: 0.085, 4: 0.080,
        5: 0.080, 6: 0.090, 7: 0.095, 8: 0.085,
        9: 0.085, 10: 0.085, 11: 0.080, 12: 0.080,
    }

    DESTINATION_SHARES = {
        2024: {
            "MYS": {"name": "Malaysia", "visitors": 3_200_000, "share_pct": 33.7},
            "IDN": {"name": "Indonesia", "visitors": 1_500_000, "share_pct": 15.8},
            "THA": {"name": "Thailand", "visitors": 1_000_000, "share_pct": 10.5},
            "JPN": {"name": "Japan", "visitors": 708_900, "share_pct": 7.5},
            "AUS": {"name": "Australia", "visitors": 500_000, "share_pct": 5.3},
            "KOR": {"name": "South Korea", "visitors": 450_000, "share_pct": 4.7},
            "CHN": {"name": "China", "visitors": 350_000, "share_pct": 3.7},
            "TWN": {"name": "Taiwan", "visitors": 280_000, "share_pct": 2.9},
        },
        2019: {
            "MYS": {"name": "Malaysia", "visitors": 3_800_000, "share_pct": 36.6},
            "IDN": {"name": "Indonesia", "visitors": 1_700_000, "share_pct": 16.4},
            "THA": {"name": "Thailand", "visitors": 1_100_000, "share_pct": 10.6},
            "JPN": {"name": "Japan", "visitors": 492_252, "share_pct": 4.7},
            "AUS": {"name": "Australia", "visitors": 600_000, "share_pct": 5.8},
            "CHN": {"name": "China", "visitors": 500_000, "share_pct": 4.8},
        },
    }


# =====================================================================
# インド
# =====================================================================

class IndiaSourceMarketClient(_BaseOtherMarketClient):
    """インドアウトバウンド統計（MoT / World Bank）"""

    ISO3 = "IND"
    ISO2 = "IN"
    NAME = "India"

    ANNUAL_DATA = {
        2019: 26_900_000,
        2020: 7_000_000,
        2021: 8_500_000,
        2022: 18_000_000,
        2023: 24_000_000,
        2024: 28_000_000,
        2025: 30_000_000,
    }

    # インドの出国シーズナリティ（ディワリ前後10-11月、夏5-6月）
    MONTHLY_RATIO = {
        1: 0.075, 2: 0.070, 3: 0.075, 4: 0.080,
        5: 0.095, 6: 0.095, 7: 0.085, 8: 0.080,
        9: 0.075, 10: 0.090, 11: 0.095, 12: 0.085,
    }

    DESTINATION_SHARES = {
        2024: {
            "ARE": {"name": "UAE", "visitors": 4_500_000, "share_pct": 16.1},
            "SAU": {"name": "Saudi Arabia", "visitors": 2_500_000, "share_pct": 8.9},
            "USA": {"name": "United States", "visitors": 2_200_000, "share_pct": 7.9},
            "THA": {"name": "Thailand", "visitors": 2_000_000, "share_pct": 7.1},
            "SGP": {"name": "Singapore", "visitors": 1_500_000, "share_pct": 5.4},
            "MYS": {"name": "Malaysia", "visitors": 1_200_000, "share_pct": 4.3},
            "GBR": {"name": "United Kingdom", "visitors": 1_100_000, "share_pct": 3.9},
            "IDN": {"name": "Indonesia (Bali)", "visitors": 800_000, "share_pct": 2.9},
            "VNM": {"name": "Vietnam", "visitors": 500_000, "share_pct": 1.8},
            "JPN": {"name": "Japan", "visitors": 267_900, "share_pct": 1.0},
            "KOR": {"name": "South Korea", "visitors": 250_000, "share_pct": 0.9},
            "AUS": {"name": "Australia", "visitors": 450_000, "share_pct": 1.6},
        },
        2019: {
            "ARE": {"name": "UAE", "visitors": 3_800_000, "share_pct": 14.1},
            "SAU": {"name": "Saudi Arabia", "visitors": 2_800_000, "share_pct": 10.4},
            "USA": {"name": "United States", "visitors": 1_800_000, "share_pct": 6.7},
            "THA": {"name": "Thailand", "visitors": 1_900_000, "share_pct": 7.1},
            "SGP": {"name": "Singapore", "visitors": 1_400_000, "share_pct": 5.2},
            "MYS": {"name": "Malaysia", "visitors": 800_000, "share_pct": 3.0},
            "JPN": {"name": "Japan", "visitors": 175_896, "share_pct": 0.7},
        },
    }


# =====================================================================
# ドイツ
# =====================================================================

class GermanySourceMarketClient(_BaseOtherMarketClient):
    """ドイツアウトバウンド統計（Destatis / World Bank）"""

    ISO3 = "DEU"
    ISO2 = "DE"
    NAME = "Germany"

    ANNUAL_DATA = {
        2019: 99_600_000,
        2020: 28_000_000,
        2021: 35_000_000,
        2022: 72_000_000,
        2023: 90_000_000,
        2024: 95_000_000,
        2025: 98_000_000,
    }

    MONTHLY_RATIO = {
        1: 0.060, 2: 0.060, 3: 0.070, 4: 0.085,
        5: 0.085, 6: 0.100, 7: 0.120, 8: 0.115,
        9: 0.095, 10: 0.085, 11: 0.065, 12: 0.060,
    }

    DESTINATION_SHARES = {
        2024: {
            "ESP": {"name": "Spain", "visitors": 15_000_000, "share_pct": 15.8},
            "ITA": {"name": "Italy", "visitors": 10_500_000, "share_pct": 11.1},
            "AUT": {"name": "Austria", "visitors": 9_000_000, "share_pct": 9.5},
            "TUR": {"name": "Turkey", "visitors": 7_500_000, "share_pct": 7.9},
            "GRC": {"name": "Greece", "visitors": 5_500_000, "share_pct": 5.8},
            "FRA": {"name": "France", "visitors": 5_000_000, "share_pct": 5.3},
            "HRV": {"name": "Croatia", "visitors": 3_000_000, "share_pct": 3.2},
            "NLD": {"name": "Netherlands", "visitors": 2_500_000, "share_pct": 2.6},
            "USA": {"name": "United States", "visitors": 2_300_000, "share_pct": 2.4},
            "THA": {"name": "Thailand", "visitors": 1_000_000, "share_pct": 1.1},
            "JPN": {"name": "Japan", "visitors": 321_000, "share_pct": 0.3},
        },
        2019: {
            "ESP": {"name": "Spain", "visitors": 14_200_000, "share_pct": 14.3},
            "ITA": {"name": "Italy", "visitors": 10_000_000, "share_pct": 10.0},
            "AUT": {"name": "Austria", "visitors": 9_500_000, "share_pct": 9.5},
            "TUR": {"name": "Turkey", "visitors": 5_500_000, "share_pct": 5.5},
            "JPN": {"name": "Japan", "visitors": 236_544, "share_pct": 0.2},
        },
    }


# =====================================================================
# フランス
# =====================================================================

class FranceSourceMarketClient(_BaseOtherMarketClient):
    """フランスアウトバウンド統計（DGE / World Bank）"""

    ISO3 = "FRA"
    ISO2 = "FR"
    NAME = "France"

    ANNUAL_DATA = {
        2019: 34_660_000,
        2020: 10_000_000,
        2021: 14_000_000,
        2022: 26_000_000,
        2023: 32_000_000,
        2024: 34_000_000,
        2025: 35_000_000,
    }

    MONTHLY_RATIO = {
        1: 0.055, 2: 0.060, 3: 0.070, 4: 0.085,
        5: 0.085, 6: 0.100, 7: 0.130, 8: 0.125,
        9: 0.085, 10: 0.080, 11: 0.065, 12: 0.060,
    }

    DESTINATION_SHARES = {
        2024: {
            "ESP": {"name": "Spain", "visitors": 7_000_000, "share_pct": 20.6},
            "ITA": {"name": "Italy", "visitors": 4_500_000, "share_pct": 13.2},
            "PRT": {"name": "Portugal", "visitors": 2_800_000, "share_pct": 8.2},
            "GBR": {"name": "United Kingdom", "visitors": 2_500_000, "share_pct": 7.4},
            "DEU": {"name": "Germany", "visitors": 2_000_000, "share_pct": 5.9},
            "MAR": {"name": "Morocco", "visitors": 1_800_000, "share_pct": 5.3},
            "GRC": {"name": "Greece", "visitors": 1_500_000, "share_pct": 4.4},
            "USA": {"name": "United States", "visitors": 1_200_000, "share_pct": 3.5},
            "THA": {"name": "Thailand", "visitors": 600_000, "share_pct": 1.8},
            "JPN": {"name": "Japan", "visitors": 395_200, "share_pct": 1.2},
        },
        2019: {
            "ESP": {"name": "Spain", "visitors": 7_500_000, "share_pct": 21.6},
            "ITA": {"name": "Italy", "visitors": 4_200_000, "share_pct": 12.1},
            "PRT": {"name": "Portugal", "visitors": 2_600_000, "share_pct": 7.5},
            "JPN": {"name": "Japan", "visitors": 336_066, "share_pct": 1.0},
        },
    }


# =====================================================================
# 英国
# =====================================================================

class UKSourceMarketClient(_BaseOtherMarketClient):
    """英国アウトバウンド統計（ONS / World Bank）"""

    ISO3 = "GBR"
    ISO2 = "GB"
    NAME = "United Kingdom"

    ANNUAL_DATA = {
        2019: 93_086_000,
        2020: 22_000_000,
        2021: 30_000_000,
        2022: 68_000_000,
        2023: 83_000_000,
        2024: 88_000_000,
        2025: 91_000_000,
    }

    MONTHLY_RATIO = {
        1: 0.060, 2: 0.060, 3: 0.075, 4: 0.085,
        5: 0.085, 6: 0.100, 7: 0.115, 8: 0.110,
        9: 0.090, 10: 0.085, 11: 0.070, 12: 0.065,
    }

    DESTINATION_SHARES = {
        2024: {
            "ESP": {"name": "Spain", "visitors": 18_000_000, "share_pct": 20.5},
            "FRA": {"name": "France", "visitors": 9_500_000, "share_pct": 10.8},
            "ITA": {"name": "Italy", "visitors": 5_500_000, "share_pct": 6.3},
            "USA": {"name": "United States", "visitors": 5_000_000, "share_pct": 5.7},
            "PRT": {"name": "Portugal", "visitors": 4_500_000, "share_pct": 5.1},
            "GRC": {"name": "Greece", "visitors": 4_000_000, "share_pct": 4.5},
            "TUR": {"name": "Turkey", "visitors": 3_500_000, "share_pct": 4.0},
            "IRL": {"name": "Ireland", "visitors": 3_200_000, "share_pct": 3.6},
            "DEU": {"name": "Germany", "visitors": 2_500_000, "share_pct": 2.8},
            "NLD": {"name": "Netherlands", "visitors": 2_200_000, "share_pct": 2.5},
            "THA": {"name": "Thailand", "visitors": 1_000_000, "share_pct": 1.1},
            "JPN": {"name": "Japan", "visitors": 470_300, "share_pct": 0.5},
            "AUS": {"name": "Australia", "visitors": 800_000, "share_pct": 0.9},
        },
        2019: {
            "ESP": {"name": "Spain", "visitors": 18_100_000, "share_pct": 19.4},
            "FRA": {"name": "France", "visitors": 10_000_000, "share_pct": 10.7},
            "ITA": {"name": "Italy", "visitors": 5_200_000, "share_pct": 5.6},
            "USA": {"name": "United States", "visitors": 4_900_000, "share_pct": 5.3},
            "JPN": {"name": "Japan", "visitors": 424_279, "share_pct": 0.5},
        },
    }


# =====================================================================
# ファクトリー
# =====================================================================

class OtherMarketClientFactory:
    """その他市場クライアントのファクトリー

    使用例:
        client = OtherMarketClientFactory.get("HKG")
        stats = await client.get_outbound_stats(2024)
    """

    _CLIENTS = {
        "HKG": HongKongSourceMarketClient,
        "SGP": SingaporeSourceMarketClient,
        "IND": IndiaSourceMarketClient,
        "DEU": GermanySourceMarketClient,
        "FRA": FranceSourceMarketClient,
        "GBR": UKSourceMarketClient,
    }

    @classmethod
    def get(cls, iso3):
        """ISO3コードに対応するクライアントを返す"""
        client_cls = cls._CLIENTS.get(iso3)
        if client_cls:
            return client_cls()
        raise ValueError(f"Unknown market: {iso3}. Available: {list(cls._CLIENTS.keys())}")

    @classmethod
    def list_markets(cls):
        """対応市場一覧"""
        return [
            {"iso3": iso3, "name": client_cls.NAME}
            for iso3, client_cls in cls._CLIENTS.items()
        ]

    @classmethod
    async def get_all_stats(cls, year=None):
        """全市場の統計を一括取得"""
        results = {}
        for iso3, client_cls in cls._CLIENTS.items():
            try:
                client = client_cls()
                stats = await client.get_outbound_stats(year)
                results[iso3] = stats
            except Exception as e:
                print(f"[OtherMarkets] Error getting stats for {iso3}: {e}")
                results[iso3] = {"country": iso3, "error": str(e)}
        return results
