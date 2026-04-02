"""競合デスティネーション統計クライアント
日本の競合8カ国(THA, KOR, TWN, SGP, IDN, FRA, ITA, ESP)のインバウンド統計。
World Bank ST.INT.ARVL をメインソースとし、各国観光庁データで補完。
"""
import requests
from datetime import datetime
from typing import Optional

WB_API_BASE = "https://api.worldbank.org/v2"

# ISO3→ISO2
_ISO3_TO_ISO2 = {
    "THA": "TH", "KOR": "KR", "TWN": "TW", "SGP": "SG",
    "IDN": "ID", "FRA": "FR", "ITA": "IT", "ESP": "ES",
    "JPN": "JP", "MYS": "MY", "VNM": "VN", "HKG": "HK",
    "CHN": "CN", "USA": "US", "AUS": "AU", "DEU": "DE",
    "GBR": "GB", "CAN": "CA", "IND": "IN", "NZL": "NZ",
}


def _fetch_wb_inbound(country_iso3, years=10):
    """World Bank ST.INT.ARVL（インバウンド到着者数）を取得"""
    iso2 = _ISO3_TO_ISO2.get(country_iso3, country_iso3)
    url = f"{WB_API_BASE}/country/{iso2}/indicator/ST.INT.ARVL"
    params = {"format": "json", "per_page": years, "mrv": years}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if len(data) < 2 or not data[1]:
            return []
        results = []
        for item in data[1]:
            if item.get("value") is not None:
                results.append({
                    "year": int(item["date"]),
                    "arrivals": int(item["value"]),
                })
        return sorted(results, key=lambda x: x["year"], reverse=True)
    except Exception as e:
        print(f"[CompetitorStats] WB API error ({country_iso3}): {e}")
        return []


class CompetitorStatsClient:
    """競合デスティネーション統計"""

    # 競合8カ国 + 日本の基本情報
    COMPETITORS = {
        "THA": {
            "name": "Thailand",
            "tourism_authority": "TAT (Tourism Authority of Thailand)",
            "strength": "コスパ、ビーチ、食文化",
            "inbound_fallback": {
                "2019": 39916000, "2023": 28150000, "2024": 35500000, "2025": 38000000,
            },
        },
        "KOR": {
            "name": "South Korea",
            "tourism_authority": "KTO (Korea Tourism Organization)",
            "strength": "K-POP文化、美容、ショッピング",
            "inbound_fallback": {
                "2019": 17502000, "2023": 11030000, "2024": 16800000, "2025": 18000000,
            },
        },
        "TWN": {
            "name": "Taiwan",
            "tourism_authority": "Taiwan Tourism Administration",
            "strength": "夜市文化、自然景観、温泉",
            "inbound_fallback": {
                "2019": 11864000, "2023": 6400000, "2024": 10000000, "2025": 11500000,
            },
        },
        "SGP": {
            "name": "Singapore",
            "tourism_authority": "STB (Singapore Tourism Board)",
            "strength": "都市観光、MICE、マルチカルチャー",
            "inbound_fallback": {
                "2019": 19100000, "2023": 13600000, "2024": 17000000, "2025": 18500000,
            },
        },
        "IDN": {
            "name": "Indonesia",
            "tourism_authority": "Ministry of Tourism & Creative Economy",
            "strength": "バリ島、自然、ダイビング",
            "inbound_fallback": {
                "2019": 16100000, "2023": 11700000, "2024": 14500000, "2025": 16000000,
            },
        },
        "FRA": {
            "name": "France",
            "tourism_authority": "Atout France",
            "strength": "文化遺産、ガストロノミー、ファッション",
            "inbound_fallback": {
                "2019": 90900000, "2023": 100000000, "2024": 102000000, "2025": 105000000,
            },
        },
        "ITA": {
            "name": "Italy",
            "tourism_authority": "ENIT",
            "strength": "世界遺産数1位、食文化、芸術",
            "inbound_fallback": {
                "2019": 64500000, "2023": 57400000, "2024": 62000000, "2025": 65000000,
            },
        },
        "ESP": {
            "name": "Spain",
            "tourism_authority": "Turespana",
            "strength": "ビーチ、建築、フィエスタ文化",
            "inbound_fallback": {
                "2019": 83700000, "2023": 85100000, "2024": 90000000, "2025": 93000000,
            },
        },
    }

    # 日本のインバウンド（比較基準）
    JAPAN_INBOUND = {
        "2019": 31882049, "2023": 25066100, "2024": 36869900, "2025": 40000000,
    }

    # 送客国別の各デスティネーションシェア推定（%）
    # source_country → {destination: share%}
    # 主に中国・韓国からの送客先構成
    SOURCE_DESTINATION_SHARES = {
        "CHN": {
            "JPN": 5.0, "THA": 8.0, "KOR": 3.5, "TWN": 1.5,
            "SGP": 2.0, "IDN": 1.5, "FRA": 1.0, "ITA": 0.5, "ESP": 0.3,
        },
        "KOR": {
            "JPN": 32.0, "THA": 5.0, "TWN": 2.0, "SGP": 2.5,
            "IDN": 1.5, "FRA": 1.0, "ITA": 0.8, "ESP": 0.5,
        },
        "USA": {
            "JPN": 2.5, "THA": 1.0, "KOR": 1.5, "TWN": 0.5,
            "SGP": 0.5, "IDN": 0.5, "FRA": 5.0, "ITA": 3.0, "ESP": 2.5,
        },
        "TWN": {
            "JPN": 35.0, "THA": 5.0, "KOR": 3.0, "SGP": 2.0,
            "IDN": 1.5, "FRA": 0.5, "ITA": 0.3, "ESP": 0.2,
        },
    }

    def _get_inbound(self, country_iso3, year=None):
        """インバウンド到着者数を取得（WB → フォールバック）"""
        wb_data = _fetch_wb_inbound(country_iso3, years=10)
        if wb_data:
            if year:
                for d in wb_data:
                    if d["year"] == year:
                        return d["arrivals"], d["year"], "World Bank WDI"
            return wb_data[0]["arrivals"], wb_data[0]["year"], "World Bank WDI"

        # フォールバック
        if country_iso3 == "JPN":
            fallback = self.JAPAN_INBOUND
        else:
            comp = self.COMPETITORS.get(country_iso3, {})
            fallback = comp.get("inbound_fallback", {})

        if year and str(year) in fallback:
            return fallback[str(year)], year, "hardcoded_fallback"
        if fallback:
            latest_y = max(fallback.keys())
            return fallback[latest_y], int(latest_y), "hardcoded_fallback"
        return None, year, "no_data"

    async def get_competitor_inbound(self, competitor_iso3, source_country="", year=None, month=None):
        """競合国のインバウンド統計を取得

        Args:
            competitor_iso3: 競合国ISO3
            source_country: 送客元ISO3（空なら全体）
            year: 対象年
            month: 対象月（Noneなら年間）

        Returns:
            dict: インバウンド統計
        """
        comp_info = self.COMPETITORS.get(competitor_iso3, {})
        arrivals, data_year, source = self._get_inbound(competitor_iso3, year)

        result = {
            "destination": competitor_iso3,
            "destination_name": comp_info.get("name", competitor_iso3),
            "year": data_year,
            "total_inbound": arrivals,
            "source": source,
        }

        if month and arrivals:
            # 月別推定（シーズナリティは国により異なるが簡易的に÷12）
            monthly_ratios = self._get_monthly_ratio(competitor_iso3)
            ratio = monthly_ratios.get(month, 1.0 / 12)
            result["month"] = month
            result["monthly_inbound"] = int(arrivals * ratio)

        # 送客元指定時：シェア推定
        if source_country and arrivals:
            shares = self.SOURCE_DESTINATION_SHARES.get(source_country, {})
            share_pct = shares.get(competitor_iso3)
            if share_pct:
                from .country_outbound_clients import get_client_for_country
                client = get_client_for_country(source_country)
                try:
                    outbound = await client.get_outbound_monthly(year=data_year)
                    total_out = outbound.get("departures")
                    if total_out:
                        estimated_from_source = int(total_out * share_pct / 100)
                        result["from_source_country"] = {
                            "source": source_country,
                            "estimated_arrivals": estimated_from_source,
                            "share_pct": share_pct,
                        }
                except Exception as e:
                    print(f"[CompetitorStats] outbound lookup error: {e}")

        return result

    async def get_relative_performance(self, base_year=None):
        """日本と競合国のインバウンド比較

        Args:
            base_year: 基準年（Noneなら最新）

        Returns:
            dict: 各国のインバウンド数と日本比
        """
        # 日本のデータ
        jpn_arrivals, jpn_year, jpn_source = self._get_inbound("JPN", base_year)
        if not jpn_arrivals:
            jpn_arrivals = self.JAPAN_INBOUND.get("2024", 36869900)
            jpn_year = 2024

        results = {
            "base_country": "JPN",
            "base_arrivals": jpn_arrivals,
            "base_year": jpn_year,
            "competitors": {},
        }

        for iso3, info in self.COMPETITORS.items():
            arrivals, data_year, source = self._get_inbound(iso3, base_year)
            if arrivals:
                ratio = round(arrivals / jpn_arrivals, 3) if jpn_arrivals else None

                # 2019年からの回復率
                pre_covid, _, _ = self._get_inbound(iso3, 2019)
                recovery_pct = None
                if pre_covid and pre_covid > 0:
                    recovery_pct = round(arrivals / pre_covid * 100, 1)

                results["competitors"][iso3] = {
                    "name": info["name"],
                    "arrivals": arrivals,
                    "year": data_year,
                    "ratio_to_japan": ratio,
                    "recovery_vs_2019_pct": recovery_pct,
                    "strength": info.get("strength", ""),
                    "source": source,
                }

        # 日本自身の回復率
        jpn_2019 = self.JAPAN_INBOUND.get("2019", 31882049)
        results["japan_recovery_vs_2019_pct"] = round(jpn_arrivals / jpn_2019 * 100, 1) if jpn_2019 else None

        return results

    async def calculate_diversion_index(self, source_country, period_months=12):
        """転換指数 — 送客国の観光客が日本から競合国にどれだけ流れているか

        diversion_index > 1.0: 日本からの転換が進行
        diversion_index < 1.0: 日本への集中が強化

        Args:
            source_country: 送客元ISO3
            period_months: 分析期間（月数）

        Returns:
            dict: 転換指数と詳細
        """
        shares = self.SOURCE_DESTINATION_SHARES.get(source_country, {})
        if not shares:
            return {
                "source_country": source_country,
                "diversion_index": None,
                "note": "送客元のシェアデータなし",
            }

        japan_share = shares.get("JPN", 0)
        competitor_total_share = sum(
            v for k, v in shares.items() if k != "JPN"
        )

        # 転換指数: 競合合計シェア / 日本シェア
        diversion_index = None
        if japan_share > 0:
            diversion_index = round(competitor_total_share / japan_share, 3)

        # 各競合の詳細
        competitor_details = {}
        for iso3, share in shares.items():
            if iso3 == "JPN":
                continue
            comp_info = self.COMPETITORS.get(iso3, {})
            competitor_details[iso3] = {
                "name": comp_info.get("name", iso3),
                "share_pct": share,
                "relative_to_japan": round(share / japan_share, 3) if japan_share > 0 else None,
            }

        # 最新データで実際のインバウンド数も取得
        from .jnto_client import JNTOClient
        jnto = JNTOClient()
        japan_arrivals_from_source = None
        hist = jnto.HISTORICAL_DATA.get(source_country, {})
        if hist:
            latest_y = max(hist.keys())
            japan_arrivals_from_source = hist[latest_y]

        return {
            "source_country": source_country,
            "japan_share_pct": japan_share,
            "competitor_total_share_pct": competitor_total_share,
            "diversion_index": diversion_index,
            "japan_arrivals_from_source": japan_arrivals_from_source,
            "interpretation": (
                "日本への集中が強い" if diversion_index and diversion_index < 1.0
                else "競合への転換が進行中" if diversion_index and diversion_index > 2.0
                else "均衡状態"
            ),
            "competitors": competitor_details,
            "period_months": period_months,
            "note": "シェア推定値ベース（各国観光庁公表二国間データで精度向上可能）",
        }

    def _get_monthly_ratio(self, country_iso3):
        """国別の月次インバウンド比率"""
        # 国ごとの観光シーズナリティ
        ratios = {
            "THA": {
                1: 0.110, 2: 0.100, 3: 0.090, 4: 0.070, 5: 0.060, 6: 0.055,
                7: 0.070, 8: 0.075, 9: 0.060, 10: 0.080, 11: 0.100, 12: 0.130,
            },
            "FRA": {
                1: 0.050, 2: 0.055, 3: 0.065, 4: 0.080, 5: 0.090, 6: 0.110,
                7: 0.130, 8: 0.130, 9: 0.100, 10: 0.075, 11: 0.060, 12: 0.055,
            },
            "ESP": {
                1: 0.045, 2: 0.050, 3: 0.065, 4: 0.080, 5: 0.095, 6: 0.115,
                7: 0.135, 8: 0.135, 9: 0.095, 10: 0.075, 11: 0.055, 12: 0.055,
            },
            "ITA": {
                1: 0.045, 2: 0.050, 3: 0.065, 4: 0.085, 5: 0.095, 6: 0.110,
                7: 0.130, 8: 0.130, 9: 0.100, 10: 0.080, 11: 0.060, 12: 0.050,
            },
        }
        return ratios.get(country_iso3, {m: 1.0 / 12 for m in range(1, 13)})


# --- 便利関数（同期版） ---

def get_competitor_summary():
    """競合サマリーを同期で取得"""
    client = CompetitorStatsClient()
    summary = {}
    for iso3, info in client.COMPETITORS.items():
        arrivals, year, source = client._get_inbound(iso3)
        jpn_arr = client.JAPAN_INBOUND.get(str(year), client.JAPAN_INBOUND.get("2024"))
        summary[iso3] = {
            "name": info["name"],
            "inbound": arrivals,
            "year": year,
            "ratio_to_japan": round(arrivals / jpn_arr, 2) if arrivals and jpn_arr else None,
            "strength": info.get("strength", ""),
        }
    return summary
