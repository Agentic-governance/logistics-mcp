"""経済・余暇変数収集クライアント — EconomicLeisureClient
SCRI v1.5.0

World Bank / OECD / ILO / yfinance から経済指標を取得し、
ハードコードの余暇データ（有給休暇・リモートワーク率等）と統合。

外部APIが失敗してもLEISURE_HARDCODEで必ず値を返す。
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ==========================================================================
# ターゲット12カ国 — ISO2 / ISO3 / WB / OECD / ILO コード対応
# ==========================================================================
TARGET_COUNTRIES = {
    "KR": {"iso3": "KOR", "wb": "KOR", "oecd": "KOR", "ilo": "KOR", "ticker": "^KS11",  "name": "韓国"},
    "CN": {"iso3": "CHN", "wb": "CHN", "oecd": "CHN", "ilo": "CHN", "ticker": "000001.SS", "name": "中国"},
    "TW": {"iso3": "TWN", "wb": "TWN", "oecd": "",    "ilo": "",    "ticker": "^TWII", "name": "台湾"},
    "US": {"iso3": "USA", "wb": "USA", "oecd": "USA", "ilo": "USA", "ticker": "^GSPC", "name": "米国"},
    "AU": {"iso3": "AUS", "wb": "AUS", "oecd": "AUS", "ilo": "AUS", "ticker": "^AXJO", "name": "豪州"},
    "TH": {"iso3": "THA", "wb": "THA", "oecd": "",    "ilo": "THA", "ticker": "^SET.BK", "name": "タイ"},
    "HK": {"iso3": "HKG", "wb": "HKG", "oecd": "",    "ilo": "HKG", "ticker": "^HSI",  "name": "香港"},
    "SG": {"iso3": "SGP", "wb": "SGP", "oecd": "",    "ilo": "SGP", "ticker": "^STI",  "name": "シンガポール"},
    "DE": {"iso3": "DEU", "wb": "DEU", "oecd": "DEU", "ilo": "DEU", "ticker": "^GDAXI", "name": "ドイツ"},
    "FR": {"iso3": "FRA", "wb": "FRA", "oecd": "FRA", "ilo": "FRA", "ticker": "^FCHI", "name": "フランス"},
    "GB": {"iso3": "GBR", "wb": "GBR", "oecd": "GBR", "ilo": "GBR", "ticker": "^FTSE", "name": "英国"},
    "IN": {"iso3": "IND", "wb": "IND", "oecd": "IND", "ilo": "IND", "ticker": "^BSESN", "name": "インド"},
}

# ==========================================================================
# 余暇ハードコードデータ（12カ国）
# annual_leave_days: 法定有給休暇日数
# leave_utilization_rate: 有給取得率（0-1）
# annual_working_hours: 年間労働時間
# remote_work_rate: リモートワーク率（0-1）
# ==========================================================================
LEISURE_HARDCODE = {
    "KR": {"annual_leave_days": 15, "leave_utilization_rate": 0.72, "annual_working_hours": 1901, "remote_work_rate": 0.15},
    "CN": {"annual_leave_days": 5,  "leave_utilization_rate": 0.60, "annual_working_hours": 2174, "remote_work_rate": 0.08},
    "TW": {"annual_leave_days": 7,  "leave_utilization_rate": 0.65, "annual_working_hours": 2008, "remote_work_rate": 0.12},
    "US": {"annual_leave_days": 10, "leave_utilization_rate": 0.77, "annual_working_hours": 1811, "remote_work_rate": 0.28},
    "AU": {"annual_leave_days": 20, "leave_utilization_rate": 0.82, "annual_working_hours": 1694, "remote_work_rate": 0.32},
    "TH": {"annual_leave_days": 6,  "leave_utilization_rate": 0.70, "annual_working_hours": 2024, "remote_work_rate": 0.06},
    "HK": {"annual_leave_days": 7,  "leave_utilization_rate": 0.68, "annual_working_hours": 2080, "remote_work_rate": 0.18},
    "SG": {"annual_leave_days": 7,  "leave_utilization_rate": 0.73, "annual_working_hours": 2238, "remote_work_rate": 0.22},
    "DE": {"annual_leave_days": 20, "leave_utilization_rate": 0.96, "annual_working_hours": 1341, "remote_work_rate": 0.25},
    "FR": {"annual_leave_days": 25, "leave_utilization_rate": 0.93, "annual_working_hours": 1490, "remote_work_rate": 0.22},
    "GB": {"annual_leave_days": 28, "leave_utilization_rate": 0.88, "annual_working_hours": 1532, "remote_work_rate": 0.26},
    "IN": {"annual_leave_days": 12, "leave_utilization_rate": 0.55, "annual_working_hours": 2117, "remote_work_rate": 0.10},
}

# ==========================================================================
# 経済指標フォールバック（API失敗時用）
# ==========================================================================
_FALLBACK_GDP_PPP = {
    "KR": 54070, "CN": 25020, "TW": 69500, "US": 83640,
    "AU": 65400, "TH": 22800, "HK": 69800, "SG": 134800,
    "DE": 66200, "FR": 57900, "GB": 56200, "IN": 10200,
}

_FALLBACK_UNEMPLOYMENT = {
    "KR": 2.7, "CN": 5.1, "TW": 3.4, "US": 3.7,
    "AU": 3.9, "TH": 1.1, "HK": 2.9, "SG": 2.0,
    "DE": 3.1, "FR": 7.3, "GB": 4.0, "IN": 7.8,
}

_FALLBACK_CONSUMER_CONFIDENCE = {
    "KR": 99.0, "CN": 97.5, "TW": 100.0, "US": 100.0,
    "AU": 99.5, "TH": 100.5, "HK": 99.0, "SG": 100.5,
    "DE": 96.0, "FR": 99.0, "GB": 98.0, "IN": 101.0,
}


class EconomicLeisureClient:
    """経済・余暇変数収集クライアント

    外部API（World Bank, OECD, ILO, yfinance）からリアルタイムデータ取得を試み、
    失敗時はハードコード値にフォールバック。
    """

    WB_BASE_URL = "https://api.worldbank.org/v2/country/{code}/indicator/{indicator}"
    OECD_BASE_URL = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_MEI@DF_MEI,1.0"
    ILO_BASE_URL = "https://www.ilo.org/ilostat/api/v1/data"
    TIMEOUT = 10

    def __init__(self):
        self._session = None

    @property
    def session(self):
        if self._session is None and REQUESTS_AVAILABLE:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": "SCRI/1.5.0"})
        return self._session

    # ------------------------------------------------------------------
    # World Bank API
    # ------------------------------------------------------------------
    def fetch_world_bank_indicator(
        self, country_code: str, indicator: str = "NY.GDP.PCAP.PP.CD",
        year: int = 2024
    ) -> Optional[float]:
        """World Bank API から指標を取得

        Args:
            country_code: ISO3国コード (e.g. "KOR")
            indicator: WB指標コード
            year: 取得年

        Returns:
            指標値（float）またはNone
        """
        if not REQUESTS_AVAILABLE:
            return None
        try:
            url = self.WB_BASE_URL.format(code=country_code, indicator=indicator)
            params = {"format": "json", "date": str(year), "per_page": 5}
            resp = self.session.get(url, params=params, timeout=self.TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # WB APIは[metadata, data_array]の形式
            if isinstance(data, list) and len(data) > 1 and data[1]:
                for entry in data[1]:
                    if entry.get("value") is not None:
                        return float(entry["value"])
            return None
        except Exception as e:
            logger.warning("World Bank API失敗 (%s/%s): %s", country_code, indicator, e)
            return None

    # ------------------------------------------------------------------
    # OECD 消費者信頼感
    # ------------------------------------------------------------------
    def fetch_oecd_consumer_confidence(self, country_code: str) -> Optional[float]:
        """OECD MEI から消費者信頼感指数を取得

        Args:
            country_code: OECD国コード (e.g. "KOR")

        Returns:
            消費者信頼感指数（100=長期平均）またはNone
        """
        if not REQUESTS_AVAILABLE or not country_code:
            return None
        try:
            # SDMX REST API形式
            url = f"{self.OECD_BASE_URL}/{country_code}.M.CSCICP02.IX.IXNSA"
            headers = {"Accept": "application/json"}
            resp = self.session.get(url, headers=headers, timeout=self.TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # 最新の観測値を取得
            datasets = data.get("dataSets", [{}])
            if datasets:
                observations = datasets[0].get("series", {})
                # 最後の観測値を取得
                for key, series in observations.items():
                    obs = series.get("observations", {})
                    if obs:
                        last_key = max(obs.keys(), key=int)
                        return float(obs[last_key][0])
            return None
        except Exception as e:
            logger.warning("OECD CCI取得失敗 (%s): %s", country_code, e)
            return None

    # ------------------------------------------------------------------
    # ILO 失業率
    # ------------------------------------------------------------------
    def fetch_unemployment_ilo(self, country_code: str) -> Optional[float]:
        """ILO STAT から失業率を取得

        Args:
            country_code: ISO3国コード (e.g. "KOR")

        Returns:
            失業率（%）またはNone
        """
        if not REQUESTS_AVAILABLE or not country_code:
            return None
        try:
            url = f"{self.ILO_BASE_URL}/UNE_DEAP_SEX_AGE_RT"
            params = {
                "ref_area": country_code,
                "sex": "SEX_T",
                "classif1": "AGE_YTHADULT_YGE15",
                "format": "json",
            }
            resp = self.session.get(url, params=params, timeout=self.TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # 最新の値を探す
            if isinstance(data, list) and data:
                latest = max(data, key=lambda x: x.get("time", ""))
                return float(latest.get("value", 0))
            elif isinstance(data, dict):
                records = data.get("data", data.get("dataSets", []))
                if records:
                    return float(records[-1].get("value", 0)) if isinstance(records[-1], dict) else None
            return None
        except Exception as e:
            logger.warning("ILO失業率取得失敗 (%s): %s", country_code, e)
            return None

    # ------------------------------------------------------------------
    # 株価指数 (yfinance)
    # ------------------------------------------------------------------
    def fetch_stock_index(self, ticker: str) -> Optional[float]:
        """yfinance から株価指数の直近終値を取得

        Args:
            ticker: Yahoo Finance ティッカー (e.g. "^GSPC")

        Returns:
            直近終値またはNone
        """
        try:
            import yfinance as yf
            tk = yf.Ticker(ticker)
            hist = tk.history(period="5d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            return None
        except ImportError:
            logger.info("yfinance未インストール — 株価指数スキップ")
            return None
        except Exception as e:
            logger.warning("yfinance取得失敗 (%s): %s", ticker, e)
            return None

    # ------------------------------------------------------------------
    # collect_all_for_country — 全変数並列取得
    # ------------------------------------------------------------------
    def collect_all_for_country(self, iso2: str) -> Dict:
        """指定国の経済・余暇変数を全て収集

        外部APIの取得を並列で試み、失敗時はフォールバック値を使用。

        Args:
            iso2: ISO2国コード (e.g. "KR")

        Returns:
            dict: 全変数を含む辞書
        """
        info = TARGET_COUNTRIES.get(iso2, {})
        wb_code = info.get("wb", iso2)
        oecd_code = info.get("oecd", "")
        ilo_code = info.get("ilo", "")
        ticker = info.get("ticker", "")

        result = {
            "source_country": iso2,
            "country_name": info.get("name", iso2),
            "timestamp": datetime.utcnow().isoformat(),
        }

        # 余暇データ（ハードコード — 常に利用可能）
        leisure = LEISURE_HARDCODE.get(iso2, {})
        result["annual_leave_days"] = leisure.get("annual_leave_days")
        result["leave_utilization_rate"] = leisure.get("leave_utilization_rate")
        result["annual_working_hours"] = leisure.get("annual_working_hours")
        result["remote_work_rate"] = leisure.get("remote_work_rate")

        # 経済指標を並列取得
        api_results = {}

        def _fetch_gdp():
            return "gdp_per_capita_ppp", self.fetch_world_bank_indicator(
                wb_code, "NY.GDP.PCAP.PP.CD", 2024
            )

        def _fetch_cci():
            return "consumer_confidence", self.fetch_oecd_consumer_confidence(oecd_code)

        def _fetch_unemp():
            return "unemployment_rate", self.fetch_unemployment_ilo(ilo_code)

        def _fetch_stock():
            return "stock_index", self.fetch_stock_index(ticker) if ticker else None

        tasks = [_fetch_gdp, _fetch_cci, _fetch_unemp, _fetch_stock]

        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(fn): fn for fn in tasks}
                for future in as_completed(futures, timeout=15):
                    try:
                        key, value = future.result(timeout=12)
                        api_results[key] = value
                    except Exception as e:
                        logger.warning("並列取得タスク失敗: %s", e)
        except Exception as e:
            logger.warning("ThreadPoolExecutor失敗: %s", e)

        # フォールバック付きでマージ
        result["gdp_per_capita_ppp"] = (
            api_results.get("gdp_per_capita_ppp")
            or _FALLBACK_GDP_PPP.get(iso2)
        )
        result["consumer_confidence"] = (
            api_results.get("consumer_confidence")
            or _FALLBACK_CONSUMER_CONFIDENCE.get(iso2)
        )
        result["unemployment_rate"] = (
            api_results.get("unemployment_rate")
            or _FALLBACK_UNEMPLOYMENT.get(iso2)
        )
        result["stock_index"] = api_results.get("stock_index")

        # データソース表示
        result["data_sources"] = {
            "gdp_per_capita_ppp": "worldbank" if api_results.get("gdp_per_capita_ppp") else "hardcoded",
            "consumer_confidence": "oecd" if api_results.get("consumer_confidence") else "hardcoded",
            "unemployment_rate": "ilo" if api_results.get("unemployment_rate") else "hardcoded",
            "stock_index": "yfinance" if api_results.get("stock_index") else "unavailable",
            "leisure": "hardcoded",
        }

        return result

    # ------------------------------------------------------------------
    # collect_all — 全12カ国一括取得
    # ------------------------------------------------------------------
    def collect_all(self) -> Dict[str, Dict]:
        """全12カ国の経済・余暇変数を収集

        Returns:
            {iso2: {変数辞書}}
        """
        results = {}
        for iso2 in TARGET_COUNTRIES:
            logger.info("経済・余暇データ収集: %s", iso2)
            results[iso2] = self.collect_all_for_country(iso2)
        return results


# ========== テスト用 ==========
def _test():
    """動作確認"""
    logging.basicConfig(level=logging.INFO)
    client = EconomicLeisureClient()

    print("=" * 60)
    print("EconomicLeisureClient テスト")
    print("=" * 60)

    # 韓国のデータ取得テスト
    kr = client.collect_all_for_country("KR")
    print(f"\n韓国 ({kr['country_name']}):")
    for k, v in kr.items():
        if k != "data_sources":
            print(f"  {k}: {v}")
    print(f"  データソース: {kr['data_sources']}")


if __name__ == "__main__":
    _test()
