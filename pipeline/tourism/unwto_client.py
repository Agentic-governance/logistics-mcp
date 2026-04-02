"""UNWTO 観光統計クライアント — World Bank WDI経由
指標:
  ST.INT.ARVL  - インバウンド到着者数
  ST.INT.DPRT  - アウトバウンド出発者数
  ST.INT.RCPT.CD - 観光収入 (USD)
  ST.INT.XPND.CD - 観光支出 (USD)

World Bank API: https://api.worldbank.org/v2/
完全無料・APIキー不要
"""
import requests
from datetime import datetime
from typing import Optional

WB_API_BASE = "https://api.worldbank.org/v2"

# 観光関連指標
TOURISM_INDICATORS = {
    "inbound_arrivals": "ST.INT.ARVL",       # インバウンド到着者数
    "outbound_departures": "ST.INT.DPRT",     # アウトバウンド出発者数
    "tourism_receipts": "ST.INT.RCPT.CD",     # 観光収入 (USD)
    "tourism_expenditure": "ST.INT.XPND.CD",  # 観光支出 (USD)
}

# ISO3 → World Bank用 ISO2 マッピング（頻出国）
ISO3_TO_ISO2 = {
    "JPN": "JP", "CHN": "CN", "KOR": "KR", "TWN": "TW", "HKG": "HK",
    "USA": "US", "GBR": "GB", "FRA": "FR", "DEU": "DE", "ITA": "IT",
    "ESP": "ES", "THA": "TH", "SGP": "SG", "AUS": "AU", "CAN": "CA",
    "IND": "IN", "IDN": "ID", "MYS": "MY", "VNM": "VN", "PHL": "PH",
    "BRA": "BR", "MEX": "MX", "RUS": "RU", "TUR": "TR", "SAU": "SA",
    "ARE": "AE", "EGY": "EG", "ZAF": "ZA", "NGA": "NG", "NZL": "NZ",
    "MMR": "MM", "KHM": "KH", "BGD": "BD", "UKR": "UA",
}

# 日本のインバウンド主要送客国の競合先リスト（デフォルト）
DEFAULT_COMPETITORS = ["JPN", "KOR", "THA", "TWN", "SGP", "IDN", "FRA", "ITA", "ESP"]


def _iso3_to_iso2(iso3):
    """ISO3→ISO2変換（World Bank APIはISO2を使用）"""
    if iso3 in ISO3_TO_ISO2:
        return ISO3_TO_ISO2[iso3]
    # 不明ならそのまま返す（World Bankが3文字も受け付ける場合あり）
    return iso3


def _fetch_wb_indicator(country_iso3, indicator, years=10):
    """World Bank APIから観光指標を取得"""
    iso2 = _iso3_to_iso2(country_iso3)
    url = f"{WB_API_BASE}/country/{iso2}/indicator/{indicator}"
    params = {
        "format": "json",
        "per_page": years,
        "mrv": years,
    }
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
                    "value": item["value"],
                    "country": item.get("country", {}).get("value", ""),
                    "country_code": country_iso3,
                })
        return sorted(results, key=lambda x: x["year"], reverse=True)
    except Exception as e:
        print(f"[UNWTOClient] World Bank API error ({indicator}, {country_iso3}): {e}")
        return []


class UNWTOClient:
    """UNWTO観光統計クライアント（World Bank WDI経由）"""

    # アウトバウンドのハードコードフォールバック（万人単位→実数）
    # 主要送客国の年間アウトバウンド出発者数
    OUTBOUND_FALLBACK = {
        "CHN": {"2019": 154630000, "2023": 87260000, "2024": 110000000},
        "KOR": {"2019": 28714000, "2023": 22674000, "2024": 26000000},
        "TWN": {"2019": 17101000, "2023": 12000000, "2024": 15000000},
        "HKG": {"2019": 10003000, "2023": 8500000, "2024": 9200000},
        "USA": {"2019": 99744000, "2023": 80000000, "2024": 90000000},
        "THA": {"2019": 10752000, "2023": 7000000, "2024": 9000000},
        "SGP": {"2019": 10382000, "2023": 8000000, "2024": 9500000},
        "AUS": {"2019": 11269000, "2023": 9000000, "2024": 10500000},
        "PHL": {"2019": 2616000, "2023": 2200000, "2024": 2500000},
        "MYS": {"2019": 13205000, "2023": 10000000, "2024": 12000000},
        "VNM": {"2019": 5100000, "2023": 4500000, "2024": 5000000},
        "IND": {"2019": 26900000, "2023": 22000000, "2024": 25000000},
        "DEU": {"2019": 99600000, "2023": 85000000, "2024": 92000000},
        "GBR": {"2019": 93086000, "2023": 80000000, "2024": 86000000},
        "FRA": {"2019": 34660000, "2023": 30000000, "2024": 33000000},
        "CAN": {"2019": 32671000, "2023": 27000000, "2024": 30000000},
        "ITA": {"2019": 34500000, "2023": 30000000, "2024": 33000000},
        "IDN": {"2019": 11689000, "2023": 9000000, "2024": 10500000},
    }

    # インバウンド到着者数フォールバック
    INBOUND_FALLBACK = {
        "JPN": {"2019": 31882049, "2023": 25066100, "2024": 36869900},
        "THA": {"2019": 39916000, "2023": 28150000, "2024": 35500000},
        "KOR": {"2019": 17502000, "2023": 11030000, "2024": 16800000},
        "FRA": {"2019": 90900000, "2023": 100000000, "2024": 102000000},
        "ESP": {"2019": 83700000, "2023": 85100000, "2024": 90000000},
        "ITA": {"2019": 64500000, "2023": 57400000, "2024": 62000000},
        "SGP": {"2019": 19100000, "2023": 13600000, "2024": 17000000},
        "TWN": {"2019": 11864000, "2023": 6400000, "2024": 10000000},
        "IDN": {"2019": 16100000, "2023": 11700000, "2024": 14500000},
    }

    async def get_outbound_total(self, country_iso3, year=None):
        """指定国の年間アウトバウンド出発者数を取得

        Args:
            country_iso3: ISO3国コード (例: "CHN")
            year: 対象年（Noneなら最新）

        Returns:
            dict: {"country": str, "year": int, "departures": int, "source": str}
        """
        try:
            data = _fetch_wb_indicator(country_iso3, TOURISM_INDICATORS["outbound_departures"], years=10)
            if data:
                if year:
                    for d in data:
                        if d["year"] == year:
                            return {
                                "country": country_iso3,
                                "year": d["year"],
                                "departures": int(d["value"]),
                                "source": "World Bank WDI (ST.INT.DPRT)",
                            }
                # 最新データ返却
                latest = data[0]
                return {
                    "country": country_iso3,
                    "year": latest["year"],
                    "departures": int(latest["value"]),
                    "source": "World Bank WDI (ST.INT.DPRT)",
                }
        except Exception as e:
            print(f"[UNWTOClient] get_outbound_total error: {e}")

        # フォールバック
        fallback = self.OUTBOUND_FALLBACK.get(country_iso3, {})
        if year and str(year) in fallback:
            return {
                "country": country_iso3,
                "year": year,
                "departures": fallback[str(year)],
                "source": "hardcoded_fallback",
            }
        # 最新の利用可能年
        if fallback:
            latest_year = max(fallback.keys())
            return {
                "country": country_iso3,
                "year": int(latest_year),
                "departures": fallback[latest_year],
                "source": "hardcoded_fallback",
            }
        return {
            "country": country_iso3,
            "year": year or datetime.now().year - 1,
            "departures": None,
            "source": "no_data",
        }

    async def get_inbound_to_japan(self, source_country, years_back=5):
        """指定国から日本へのインバウンド到着者数の推移

        NOTE: World Bank ST.INT.ARVL は国全体の着数のみで、二国間データなし。
        ここでは日本のインバウンド全体×送客国シェアで推定する。
        正確な二国間データはJNTOClientを参照。

        Args:
            source_country: ISO3国コード
            years_back: 取得年数

        Returns:
            list[dict]: 年別の推定訪日者数
        """
        # JNTOハードコードデータで補完（JNTOClient側と連携）
        from .jnto_client import JNTOClient
        jnto = JNTOClient()
        try:
            trend = await jnto.get_annual_trend(source_country, years_back=years_back)
            if trend:
                return trend
        except Exception as e:
            print(f"[UNWTOClient] JNTOClient fallback error: {e}")

        return []

    async def get_destination_share(self, source_country, competitors=None):
        """送客国からの観光客が各デスティネーションに何%行くか推定

        World Bank全体データ×JNTOデータで日本シェアを計算。
        各競合国のインバウンド全体に対する送客国の割合を推定。

        Args:
            source_country: 送客元ISO3
            competitors: 比較先ISO3リスト（デフォルト: DEFAULT_COMPETITORS）

        Returns:
            dict: {destination_iso3: {"arrivals_from_source": int, "share_pct": float}}
        """
        if competitors is None:
            competitors = DEFAULT_COMPETITORS

        # 送客国の全アウトバウンド
        outbound = await self.get_outbound_total(source_country)
        total_outbound = outbound.get("departures") or 0

        result = {}
        for dest in competitors:
            try:
                # 各デスティネーションのインバウンド全体を取得
                inbound_data = _fetch_wb_indicator(dest, TOURISM_INDICATORS["inbound_arrivals"], years=5)
                if inbound_data:
                    total_inbound = int(inbound_data[0]["value"])
                    year = inbound_data[0]["year"]
                else:
                    fb = self.INBOUND_FALLBACK.get(dest, {})
                    if fb:
                        latest_y = max(fb.keys())
                        total_inbound = fb[latest_y]
                        year = int(latest_y)
                    else:
                        continue

                # シェア推定（送客国のアウトバウンドに対する比率は不明なので、
                # 日本の実データがある場合はそれを使い、他国は概算）
                arrivals_from_source = None
                if dest == "JPN":
                    from .jnto_client import JNTOClient
                    jnto = JNTOClient()
                    hist = jnto.HISTORICAL_DATA.get(source_country, {})
                    if hist:
                        latest_y = max(hist.keys())
                        arrivals_from_source = hist[latest_y]

                share_pct = None
                if arrivals_from_source and total_outbound > 0:
                    share_pct = round(arrivals_from_source / total_outbound * 100, 2)

                result[dest] = {
                    "destination": dest,
                    "total_inbound": total_inbound,
                    "arrivals_from_source": arrivals_from_source,
                    "share_pct": share_pct,
                    "year": year,
                }
            except Exception as e:
                print(f"[UNWTOClient] get_destination_share error ({dest}): {e}")
                continue

        return {
            "source_country": source_country,
            "total_outbound": total_outbound,
            "outbound_year": outbound.get("year"),
            "destinations": result,
            "source": "World Bank WDI + JNTO estimates",
        }

    async def batch_get_outbound(self, countries):
        """複数国のアウトバウンド出発者数を一括取得

        Args:
            countries: ISO3コードのリスト

        Returns:
            dict: {iso3: {year, departures, source}}
        """
        result = {}
        for iso3 in countries:
            try:
                data = await self.get_outbound_total(iso3)
                result[iso3] = data
            except Exception as e:
                print(f"[UNWTOClient] batch_get_outbound error ({iso3}): {e}")
                result[iso3] = {"country": iso3, "departures": None, "source": "error"}
        return result


# --- 便利関数（同期版） ---

def get_tourism_profile(country_iso3):
    """国の観光プロファイルを同期で取得"""
    profile = {"country": country_iso3}
    for key, indicator in TOURISM_INDICATORS.items():
        data = _fetch_wb_indicator(country_iso3, indicator, years=5)
        if data:
            profile[key] = {
                "latest_value": data[0]["value"],
                "latest_year": data[0]["year"],
                "trend": [{"year": d["year"], "value": d["value"]} for d in data],
            }
    return profile


def get_tourism_risk_indicators(country_iso3):
    """観光関連リスク指標を同期で算出
    観光依存度が高い国はリスクが高い（パンデミック等で急落）
    """
    score = 0
    evidence = []

    # インバウンド到着者数の推移
    arrivals = _fetch_wb_indicator(country_iso3, TOURISM_INDICATORS["inbound_arrivals"], years=5)
    if arrivals and len(arrivals) >= 2:
        latest = arrivals[0]["value"]
        prev = arrivals[1]["value"]
        if prev > 0:
            change_pct = (latest - prev) / prev * 100
            if change_pct < -30:
                score += 40
                evidence.append(f"インバウンド急減: {change_pct:.1f}%")
            elif change_pct < -10:
                score += 20
                evidence.append(f"インバウンド減少: {change_pct:.1f}%")
            elif change_pct > 30:
                evidence.append(f"インバウンド急増: {change_pct:.1f}%（キャパ超過リスク）")
                score += 10

    # 観光収入
    receipts = _fetch_wb_indicator(country_iso3, TOURISM_INDICATORS["tourism_receipts"], years=3)
    if receipts:
        evidence.append(f"観光収入: ${receipts[0]['value']:,.0f} ({receipts[0]['year']})")

    return {"score": min(100, score), "evidence": evidence, "country": country_iso3}
