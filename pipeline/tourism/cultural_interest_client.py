"""文化的関心変数収集クライアント — CulturalInterestClient
SCRI v1.5.0

日本文化への関心度を示す変数を収集:
- Google Trends（pytrends）
- 日本語学習者数（国際交流基金2021基準の外挿）
- 日本食レストラン数（JFOODO2023基準の外挿）

外部APIが失敗しても必ずハードコード値を返す。
"""
import logging
import math
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ==========================================================================
# 日本語学習者数 — 国際交流基金(JF) 2021年調査ベース
# 出典: 海外日本語教育機関調査2021
# 単位: 人
# ==========================================================================
JF_LANGUAGE_LEARNERS_2021 = {
    "KR": 470_334,   # 韓国 — 最大の学習者数
    "CN": 1_057_318, # 中国 — 絶対数最大
    "TW": 143_632,   # 台湾
    "US": 166_905,   # 米国
    "AU": 405_175,   # 豪州 — 教育制度組込み
    "TH": 183_957,   # タイ — 急成長
    "HK": 24_239,    # 香港
    "SG": 4_590,     # シンガポール
    "DE": 12_700,    # ドイツ
    "FR": 15_868,    # フランス
    "GB": 19_630,    # 英国
    "IN": 271_828,   # インド — 急成長中
}

# 年間成長率推定（2021→2026外挿用）
_LEARNER_GROWTH_RATE = {
    "KR": 0.02,   # 成熟市場、低成長
    "CN": 0.05,   # 高成長
    "TW": 0.03,
    "US": 0.04,   # アニメ・マンガ効果
    "AU": 0.03,
    "TH": 0.06,   # 急成長
    "HK": 0.01,   # 微成長
    "SG": 0.03,
    "DE": 0.03,
    "FR": 0.04,
    "GB": 0.04,
    "IN": 0.08,   # 最も急成長
}

# ==========================================================================
# 日本食レストラン数 — JFOODO 2023年推計ベース
# 出典: 農林水産省/JFOODO 海外日本食レストラン数2023
# 単位: 店舗数
# ==========================================================================
JFOODO_RESTAURANTS_2023 = {
    "KR": 13_200,   # 韓国
    "CN": 73_600,   # 中国 — 最大
    "TW": 8_200,    # 台湾
    "US": 28_100,   # 米国
    "AU": 4_800,    # 豪州
    "TH": 5_600,    # タイ
    "HK": 3_200,    # 香港
    "SG": 1_800,    # シンガポール
    "DE": 3_100,    # ドイツ
    "FR": 4_200,    # フランス
    "GB": 4_500,    # 英国
    "IN": 3_000,    # インド — 急増中
}

# レストラン年間成長率推定（2023→2026外挿用）
_RESTAURANT_GROWTH_RATE = {
    "KR": 0.05,
    "CN": 0.08,
    "TW": 0.04,
    "US": 0.06,
    "AU": 0.05,
    "TH": 0.07,
    "HK": 0.03,
    "SG": 0.04,
    "DE": 0.05,
    "FR": 0.05,
    "GB": 0.05,
    "IN": 0.10,   # 最も急成長
}

# ==========================================================================
# Google Trendsキーワード（日本旅行関連）
# ==========================================================================
_TREND_KEYWORDS = ["Japan travel", "日本旅行", "Japan tourism"]


class CulturalInterestClient:
    """文化的関心変数収集クライアント

    日本文化への関心度を示す3つの主要変数を収集:
    1. Google Trends（Japan travel検索ボリューム）
    2. 日本語学習者数推計
    3. 日本食レストラン数推計
    """

    def __init__(self):
        self._pytrends = None

    # ------------------------------------------------------------------
    # Google Trends
    # ------------------------------------------------------------------
    def fetch_google_trends(self, geo: str = "", keyword: str = "Japan travel") -> Dict:
        """Google Trends から検索ボリュームを取得

        Args:
            geo: 地域コード (e.g. "KR", ""=worldwide)
            keyword: 検索キーワード

        Returns:
            dict: {"interest": 0-100, "data_source": "pytrends"|"unavailable"}
        """
        try:
            from pytrends.request import TrendReq
            if self._pytrends is None:
                self._pytrends = TrendReq(hl="en-US", tz=540)

            self._pytrends.build_payload(
                [keyword],
                timeframe="today 12-m",
                geo=geo,
            )
            df = self._pytrends.interest_over_time()
            if df is not None and not df.empty and keyword in df.columns:
                # 直近3ヶ月の平均値を返す
                recent = df[keyword].tail(12).mean()
                return {"interest": round(float(recent), 1), "data_source": "pytrends"}
            return {"interest": None, "data_source": "unavailable"}

        except ImportError:
            logger.info("pytrends未インストール — Google Trendsスキップ")
            return {"interest": None, "data_source": "unavailable"}
        except Exception as e:
            logger.warning("Google Trends取得失敗 (geo=%s): %s", geo, e)
            return {"interest": None, "data_source": "unavailable"}

    # ------------------------------------------------------------------
    # 日本語学習者数推計
    # ------------------------------------------------------------------
    def get_language_learners_estimate(
        self, iso2: str, target_year: int = 2026
    ) -> Dict:
        """日本語学習者数の推計値を返す

        JF2021年調査値を基準に、年間成長率で外挿。

        Args:
            iso2: ISO2国コード
            target_year: 推計対象年

        Returns:
            dict: {"learners": int, "base_year": 2021, "growth_rate": float, ...}
        """
        base = JF_LANGUAGE_LEARNERS_2021.get(iso2)
        if base is None:
            return {
                "learners": None,
                "base_year": 2021,
                "growth_rate": None,
                "data_source": "unavailable",
            }

        growth = _LEARNER_GROWTH_RATE.get(iso2, 0.03)
        years_diff = target_year - 2021
        estimated = int(base * math.pow(1 + growth, years_diff))

        return {
            "learners": estimated,
            "base_year": 2021,
            "base_value": base,
            "growth_rate": growth,
            "target_year": target_year,
            "data_source": "jf2021_extrapolated",
        }

    # ------------------------------------------------------------------
    # 日本食レストラン数推計
    # ------------------------------------------------------------------
    def get_restaurant_count_estimate(
        self, iso2: str, target_year: int = 2026
    ) -> Dict:
        """日本食レストラン数の推計値を返す

        JFOODO2023年推計値を基準に、年間成長率で外挿。

        Args:
            iso2: ISO2国コード
            target_year: 推計対象年

        Returns:
            dict: {"restaurants": int, "base_year": 2023, "growth_rate": float, ...}
        """
        base = JFOODO_RESTAURANTS_2023.get(iso2)
        if base is None:
            return {
                "restaurants": None,
                "base_year": 2023,
                "growth_rate": None,
                "data_source": "unavailable",
            }

        growth = _RESTAURANT_GROWTH_RATE.get(iso2, 0.05)
        years_diff = target_year - 2023
        estimated = int(base * math.pow(1 + growth, years_diff))

        return {
            "restaurants": estimated,
            "base_year": 2023,
            "base_value": base,
            "growth_rate": growth,
            "target_year": target_year,
            "data_source": "jfoodo2023_extrapolated",
        }

    # ------------------------------------------------------------------
    # collect_cultural_interest — 全変数収集
    # ------------------------------------------------------------------
    def collect_cultural_interest(self, iso2: str, target_year: int = 2026) -> Dict:
        """指定国の文化的関心変数を全て収集

        Args:
            iso2: ISO2国コード
            target_year: 推計対象年

        Returns:
            dict: 全文化的関心変数
        """
        result = {
            "source_country": iso2,
            "target_year": target_year,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Google Trends
        trends = self.fetch_google_trends(geo=iso2)
        result["japan_travel_trend"] = trends.get("interest")
        result["trends_data_source"] = trends.get("data_source")

        # 日本語学習者数
        learners = self.get_language_learners_estimate(iso2, target_year)
        result["language_learners"] = learners.get("learners")
        result["learners_data_source"] = learners.get("data_source")

        # 日本食レストラン数
        restaurants = self.get_restaurant_count_estimate(iso2, target_year)
        result["restaurant_count"] = restaurants.get("restaurants")
        result["restaurants_data_source"] = restaurants.get("data_source")

        return result

    # ------------------------------------------------------------------
    # collect_all — 全カ国一括取得
    # ------------------------------------------------------------------
    def collect_all(self, target_year: int = 2026) -> Dict[str, Dict]:
        """全登録カ国の文化的関心変数を収集

        Returns:
            {iso2: {変数辞書}}
        """
        countries = list(JF_LANGUAGE_LEARNERS_2021.keys())
        results = {}
        for iso2 in countries:
            logger.info("文化的関心データ収集: %s", iso2)
            results[iso2] = self.collect_cultural_interest(iso2, target_year)
        return results


# ========== テスト用 ==========
def _test():
    """動作確認"""
    logging.basicConfig(level=logging.INFO)
    client = CulturalInterestClient()

    print("=" * 60)
    print("CulturalInterestClient テスト")
    print("=" * 60)

    for iso2 in ["KR", "US", "TH", "IN"]:
        data = client.collect_cultural_interest(iso2)
        print(f"\n{iso2}:")
        print(f"  日本語学習者数: {data.get('language_learners'):,}")
        print(f"  日本食レストラン: {data.get('restaurant_count'):,}")
        print(f"  Google Trends: {data.get('japan_travel_trend')}")


if __name__ == "__main__":
    _test()
