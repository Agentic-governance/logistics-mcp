"""サプライヤー評判スクリーニング — STREAM 4-A
GDELT v2 Article Search API でニュース記事を検索し、
労働問題・環境・腐敗・安全性カテゴリで評判スコアを算出。
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

# GDELT v2 Doc API (free, no auth required)
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# カテゴリ定義: keyword patterns → reputation penalty
REPUTATION_CATEGORIES = {
    "LABOR_VIOLATION": {
        "keywords": [
            "forced labor", "child labor", "sweatshop", "worker abuse",
            "labor violation", "wage theft", "unsafe working conditions",
            "human trafficking", "modern slavery", "exploitation",
        ],
        "weight": 25,
        "description": "強制労働・児童労働・労働法違反",
    },
    "CORRUPTION": {
        "keywords": [
            "bribery", "corruption", "fraud", "embezzlement",
            "money laundering", "kickback", "bribe", "corrupt",
            "criminal investigation", "indictment",
        ],
        "weight": 20,
        "description": "贈賄・横領・資金洗浄",
    },
    "ENVIRONMENT": {
        "keywords": [
            "pollution", "environmental damage", "toxic waste",
            "oil spill", "deforestation", "environmental violation",
            "carbon emission", "waste dumping", "contamination",
        ],
        "weight": 15,
        "description": "環境汚染・環境法違反",
    },
    "SAFETY": {
        "keywords": [
            "factory fire", "explosion", "accident", "recall",
            "safety violation", "workplace death", "industrial accident",
            "product defect", "hazardous",
        ],
        "weight": 10,
        "description": "工場事故・製品安全・リコール",
    },
    "SANCTIONS": {
        "keywords": [
            "sanctions", "blacklist", "export control", "trade ban",
            "entity list", "sanctioned", "embargo",
        ],
        "weight": 30,
        "description": "制裁・輸出規制",
    },
}

# Rate limit: GDELT allows ~1 request per second
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 1.5  # seconds


def _rate_limit():
    """GDELT API rate limiting"""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


class ReputationResult:
    """評判スクリーニング結果"""

    def __init__(
        self,
        supplier_name: str,
        overall_score: float,
        category_scores: dict,
        article_count: int,
        negative_count: int,
        articles: list,
        screened_at: str,
        source: str = "GDELT",
    ):
        self.supplier_name = supplier_name
        self.overall_score = overall_score
        self.category_scores = category_scores
        self.article_count = article_count
        self.negative_count = negative_count
        self.articles = articles
        self.screened_at = screened_at
        self.source = source

    def to_dict(self) -> dict:
        return {
            "supplier_name": self.supplier_name,
            "reputation_score": round(self.overall_score, 1),
            "risk_level": self._risk_level(),
            "category_scores": self.category_scores,
            "article_count": self.article_count,
            "negative_article_count": self.negative_count,
            "sample_articles": self.articles[:10],
            "screened_at": self.screened_at,
            "source": self.source,
        }

    def _risk_level(self) -> str:
        if self.overall_score >= 60:
            return "HIGH"
        elif self.overall_score >= 30:
            return "MEDIUM"
        elif self.overall_score >= 10:
            return "LOW"
        return "MINIMAL"


class SupplierReputationScreener:
    """GDELT ニュース分析によるサプライヤー評判スクリーニング"""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def screen_supplier(
        self,
        supplier_name: str,
        country: str = "",
        days_back: int = 180,
    ) -> ReputationResult:
        """単一サプライヤーの評判をスクリーニング

        Args:
            supplier_name: 企業名
            country: 国名 (絞り込み用、オプション)
            days_back: 検索対象日数 (デフォルト180日)

        Returns:
            ReputationResult
        """
        articles = self._fetch_gdelt_articles(supplier_name, country, days_back)

        if articles is None:
            # GDELT unavailable → fallback
            return self._fallback_screening(supplier_name, country)

        return self._analyze_articles(supplier_name, articles)

    def batch_screen(
        self,
        suppliers: list[dict],
        days_back: int = 180,
    ) -> list[dict]:
        """複数サプライヤーを一括スクリーニング

        Args:
            suppliers: [{"name": "...", "country": "..."}]
            days_back: 検索対象日数

        Returns:
            結果リスト
        """
        results = []
        for s in suppliers:
            name = s.get("name", s.get("supplier_name", ""))
            country = s.get("country", s.get("supplier_country", ""))
            if not name:
                continue

            result = self.screen_supplier(name, country, days_back)
            results.append(result.to_dict())

        return results

    def _fetch_gdelt_articles(
        self,
        supplier_name: str,
        country: str = "",
        days_back: int = 180,
    ) -> Optional[list[dict]]:
        """GDELT v2 Doc API でニュース記事を取得

        Returns:
            記事リスト、またはAPIエラー時 None
        """
        _rate_limit()

        query = f'"{supplier_name}"'
        if country:
            query += f" {country}"

        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": "75",
            "format": "json",
            "timespan": f"{days_back}d",
        }

        try:
            resp = requests.get(
                GDELT_DOC_API,
                params=params,
                timeout=self.timeout,
            )

            if resp.status_code != 200:
                logger.warning(f"GDELT API returned {resp.status_code} for '{supplier_name}'")
                return None

            data = resp.json()
            raw_articles = data.get("articles", [])

            articles = []
            for art in raw_articles:
                articles.append({
                    "title": art.get("title", ""),
                    "url": art.get("url", ""),
                    "source": art.get("domain", art.get("source", "")),
                    "date": art.get("seendate", ""),
                    "language": art.get("language", ""),
                    "tone": float(art.get("tone", 0)),
                })

            return articles

        except requests.Timeout:
            logger.warning(f"GDELT API timeout for '{supplier_name}'")
            return None
        except requests.ConnectionError:
            logger.warning(f"GDELT API connection error for '{supplier_name}'")
            return None
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"GDELT API parse error for '{supplier_name}': {e}")
            return None
        except Exception as e:
            logger.error(f"GDELT API unexpected error for '{supplier_name}': {e}")
            return None

    def _analyze_articles(
        self,
        supplier_name: str,
        articles: list[dict],
    ) -> ReputationResult:
        """記事内容を分析し、カテゴリ別スコアを算出"""
        category_hits: dict[str, list[dict]] = {cat: [] for cat in REPUTATION_CATEGORIES}
        negative_articles = []

        for art in articles:
            title_lower = art.get("title", "").lower()
            tone = art.get("tone", 0)

            for cat_name, cat_info in REPUTATION_CATEGORIES.items():
                for kw in cat_info["keywords"]:
                    if kw in title_lower:
                        category_hits[cat_name].append(art)
                        if art not in negative_articles:
                            negative_articles.append(art)
                        break

            # Also flag very negative tone articles
            if tone < -5 and art not in negative_articles:
                negative_articles.append(art)

        # カテゴリ別スコア算出
        category_scores = {}
        total_penalty = 0.0

        for cat_name, cat_info in REPUTATION_CATEGORIES.items():
            hits = len(category_hits[cat_name])
            if hits == 0:
                category_scores[cat_name] = {
                    "score": 0,
                    "hits": 0,
                    "description": cat_info["description"],
                }
                continue

            # Logarithmic scaling: diminishing returns for many hits
            import math
            raw_penalty = cat_info["weight"] * math.log2(1 + hits)
            capped_penalty = min(raw_penalty, cat_info["weight"] * 3)

            category_scores[cat_name] = {
                "score": round(capped_penalty, 1),
                "hits": hits,
                "description": cat_info["description"],
                "sample_titles": [a["title"] for a in category_hits[cat_name][:3]],
            }
            total_penalty += capped_penalty

        # Tone adjustment: very negative average tone adds penalty
        if articles:
            avg_tone = sum(a.get("tone", 0) for a in articles) / len(articles)
            if avg_tone < -3:
                total_penalty += min(10, abs(avg_tone))

        # Cap at 100
        overall_score = min(100, total_penalty)

        return ReputationResult(
            supplier_name=supplier_name,
            overall_score=overall_score,
            category_scores=category_scores,
            article_count=len(articles),
            negative_count=len(negative_articles),
            articles=[
                {
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "source": a.get("source", ""),
                    "date": a.get("date", ""),
                    "tone": a.get("tone", 0),
                }
                for a in negative_articles[:15]
            ],
            screened_at=datetime.utcnow().isoformat(),
            source="GDELT",
        )

    def _fallback_screening(
        self,
        supplier_name: str,
        country: str = "",
    ) -> ReputationResult:
        """GDELT 利用不可時のフォールバック

        国ベースのベースラインスコアを返す
        """
        # Country-based baseline reputation risk
        HIGH_RISK_COUNTRIES = {
            "China": 25, "Myanmar": 40, "Bangladesh": 35,
            "Vietnam": 20, "Cambodia": 30, "India": 20,
            "Thailand": 15, "Indonesia": 15, "Iran": 50,
            "North Korea": 60, "Russia": 35, "Syria": 45,
        }

        baseline = HIGH_RISK_COUNTRIES.get(country, 5)

        return ReputationResult(
            supplier_name=supplier_name,
            overall_score=baseline,
            category_scores={
                cat: {"score": 0, "hits": 0, "description": info["description"]}
                for cat, info in REPUTATION_CATEGORIES.items()
            },
            article_count=0,
            negative_count=0,
            articles=[],
            screened_at=datetime.utcnow().isoformat(),
            source="fallback_baseline",
        )
