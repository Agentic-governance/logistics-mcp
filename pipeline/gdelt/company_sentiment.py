"""GDELT 企業センチメント分析クライアント
既存の monitor.py（国レベル）を拡張し、
企業固有のセンチメント分析とネガティブイベント検出を行う。

データソース: GDELT Doc API v2
  https://api.gdeltproject.org/api/v2/doc/doc

GDELTは世界中のニュースメディアをリアルタイムで処理し、
エンティティ・テーマ・トーン（感情）を抽出する。
本モジュールは企業名で検索し、報道のセンチメント時系列と
ネガティブイベント（労働問題、腐敗、環境等）を検出する。

使用例::

    client = CompanySentimentClient()
    timeline = await client.get_sentiment_timeline("Toyota Motor", days=90)
    events = await client.detect_negative_events("Toyota Motor", days=30)
    risk = await client.get_company_risk_from_news("Toyota Motor")
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 15  # 秒
RATE_LIMIT_INTERVAL = 2.0  # 秒
USER_AGENT = "SCRI-Platform/1.0 (supply-chain-risk-intelligence)"

# GDELT Doc API v2 エンドポイント
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# ネガティブイベントカテゴリ分類キーワード
NEGATIVE_CATEGORIES: dict[str, list[str]] = {
    "LABOR_VIOLATION": [
        "labor violation", "labor dispute", "worker abuse", "forced labor",
        "child labor", "wage theft", "strike", "protest worker",
        "working condition", "sweatshop", "labor rights",
        "労働違反", "強制労働", "児童労働",
    ],
    "CORRUPTION": [
        "corruption", "bribery", "fraud", "money laundering",
        "embezzlement", "kickback", "scandal", "indictment",
        "汚職", "賄賂", "不正",
    ],
    "ENVIRONMENT": [
        "pollution", "environmental violation", "toxic waste",
        "oil spill", "deforestation", "emission", "carbon",
        "environmental damage", "contamination", "hazardous",
        "環境汚染", "有害物質",
    ],
    "SAFETY": [
        "product recall", "safety violation", "accident", "explosion",
        "fire factory", "workplace injury", "safety hazard",
        "defective", "quality issue", "recall",
        "リコール", "事故", "品質問題",
    ],
    "SANCTIONS": [
        "sanction", "embargo", "trade ban", "export control",
        "blacklist", "entity list", "denied party",
        "制裁", "輸出規制",
    ],
}


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class SentimentPoint:
    """センチメント時系列の1データポイント"""
    date: str  # ISO 8601 形式
    tone: float  # -10 to +10
    article_count: int
    positive_pct: float
    negative_pct: float


@dataclass
class NegativeEvent:
    """検出されたネガティブイベント"""
    date: str
    headline: str
    source: str
    category: str  # LABOR_VIOLATION, CORRUPTION, ENVIRONMENT, SAFETY, SANCTIONS
    tone: float
    url: str


# ---------------------------------------------------------------------------
# メインクライアント
# ---------------------------------------------------------------------------
class CompanySentimentClient:
    """GDELT Doc API v2 企業センチメントクライアント

    GDELT Doc API v2 を使用して企業固有のニュースセンチメントを
    分析する。報道トーンの時系列推移とネガティブイベントの
    検出を行い、サプライチェーンリスク評価に使用する。

    機能:
      - センチメント時系列（トーン推移・記事数推移）
      - ネガティブイベント検出（カテゴリ分類付き）
      - 企業リスクスコア算出（0-100）

    制限事項:
      - GDELT Doc API はAPIキー不要だがレート制限あり
      - 過去1年程度のデータが利用可能
      - 企業名の表記揺れにより検索漏れの可能性あり
      - API到達不能時は空結果を返し、クラッシュしない
    """

    def __init__(self):
        """クライアントを初期化する。"""
        self._last_request_time: float = 0.0
        self._headers = {
            "User-Agent": USER_AGENT,
        }

    # ------------------------------------------------------------------
    # レート制限
    # ------------------------------------------------------------------
    async def _rate_limit(self) -> None:
        """リクエスト間のレート制限を適用する。"""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < RATE_LIMIT_INTERVAL:
            wait = RATE_LIMIT_INTERVAL - elapsed
            logger.debug("レート制限: %.1f秒待機", wait)
            await asyncio.sleep(wait)
        self._last_request_time = time.monotonic()

    # ------------------------------------------------------------------
    # HTTP リクエスト
    # ------------------------------------------------------------------
    async def _fetch_gdelt(
        self,
        query: str,
        mode: str = "artlist",
        max_records: int = 75,
        timespan: str = "",
        start_date: str = "",
        end_date: str = "",
        tone_filter: str = "",
        sort: str = "datedesc",
        format_: str = "json",
    ) -> dict:
        """GDELT Doc API v2 にリクエストを送信する。

        Args:
            query: 検索クエリ（企業名等）
            mode: レスポンスモード（"artlist", "timelinetone",
                  "timelinevolinfo" 等）
            max_records: 最大レコード数
            timespan: 期間指定（例: "90d", "1y"）
            start_date: 開始日（"YYYYMMDDHHMMSS"形式）
            end_date: 終了日（"YYYYMMDDHHMMSS"形式）
            tone_filter: トーンフィルタ（例: "tone<-5" でネガティブのみ）
            sort: ソート順
            format_: レスポンス形式（"json", "csv"）

        Returns:
            パースされた JSON レスポンス。エラー時は空辞書。
        """
        await self._rate_limit()

        params = {
            "query": query,
            "mode": mode,
            "maxrecords": str(max_records),
            "sort": sort,
            "format": format_,
        }

        if timespan:
            params["timespan"] = timespan
        if start_date:
            params["startdatetime"] = start_date
        if end_date:
            params["enddatetime"] = end_date
        if tone_filter:
            params["tonefilter"] = tone_filter

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers=self._headers,
                follow_redirects=True,
            ) as client:
                resp = await client.get(GDELT_DOC_API, params=params)
                resp.raise_for_status()

                # GDELT APIはJSONを返すが、空の場合やエラーの場合はテキスト
                content_type = resp.headers.get("content-type", "")
                if "json" in content_type or resp.text.strip().startswith(("{", "[")):
                    return resp.json()
                else:
                    logger.debug(
                        "GDELT API非JSONレスポンス: %s", resp.text[:200],
                    )
                    return {}

        except httpx.TimeoutException:
            logger.warning("GDELT Doc APIタイムアウト: query=%s", query)
            return {}
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "GDELT Doc API HTTPエラー %d: query=%s",
                exc.response.status_code, query,
            )
            return {}
        except httpx.HTTPError as exc:
            logger.warning("GDELT Doc API接続エラー: %s", exc)
            return {}
        except Exception as exc:
            logger.error("GDELT Doc API予期せぬエラー: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # センチメント分析
    # ------------------------------------------------------------------
    def _classify_negative_category(self, text: str) -> str:
        """テキストからネガティブイベントカテゴリを分類する。

        Args:
            text: ヘッドラインまたは記事テキスト

        Returns:
            カテゴリ名。一致なしの場合は "OTHER"。
        """
        text_lower = text.lower()
        for category, keywords in NEGATIVE_CATEGORIES.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    return category
        return "OTHER"

    # ------------------------------------------------------------------
    # 公開 API メソッド
    # ------------------------------------------------------------------
    async def get_sentiment_timeline(
        self,
        company_name: str,
        days: int = 90,
    ) -> list[SentimentPoint]:
        """企業のセンチメント時系列を取得する。

        指定された企業に関するニュース報道のトーン（感情）推移を
        日次で取得する。

        Args:
            company_name: 企業名（例: "Toyota Motor"）
            days: 取得期間（日数、デフォルト90）

        Returns:
            SentimentPoint のリスト（日付昇順）。取得失敗時は空リスト。
        """
        try:
            # GDELT query: 企業名を引用符で囲んでフレーズ検索
            query = f'"{company_name}"'
            timespan = f"{days}d"

            # timelinetone モードでトーン時系列を取得
            data = await self._fetch_gdelt(
                query=query,
                mode="timelinetone",
                timespan=timespan,
                max_records=250,
            )

            if not data:
                logger.warning(
                    "GDELT: センチメント時系列データなし (%s)", company_name,
                )
                return []

            # timelinetone レスポンスパース
            timeline = data.get("timeline", [])
            if not timeline:
                # 代替構造を試行
                timeline = data if isinstance(data, list) else []

            results: list[SentimentPoint] = []

            for series in timeline:
                # 各シリーズ内のデータポイント
                data_points = series.get("data", [])
                if not data_points and isinstance(series, dict):
                    data_points = [series]

                for point in data_points:
                    date_str = point.get("date", "")
                    value = point.get("value", 0.0)

                    # 日付の正規化
                    if date_str and len(date_str) >= 8:
                        try:
                            dt = datetime.strptime(date_str[:8], "%Y%m%d")
                            iso_date = dt.strftime("%Y-%m-%d")
                        except ValueError:
                            iso_date = date_str
                    else:
                        iso_date = date_str

                    # トーン値の解析
                    tone = 0.0
                    article_count = 0
                    try:
                        tone = float(value)
                    except (ValueError, TypeError):
                        pass

                    # artcount が利用可能な場合
                    article_count = int(point.get("norm", point.get("count", 0)))

                    # ポジティブ/ネガティブ比率の推定
                    positive_pct = max(0.0, (tone + 10) / 20 * 100)
                    negative_pct = max(0.0, 100 - positive_pct)

                    results.append(SentimentPoint(
                        date=iso_date,
                        tone=tone,
                        article_count=article_count,
                        positive_pct=round(positive_pct, 1),
                        negative_pct=round(negative_pct, 1),
                    ))

            # 日付順にソート
            results.sort(key=lambda p: p.date)

            logger.info(
                "GDELT: センチメント時系列 %d件取得 (%s, %d日間)",
                len(results), company_name, days,
            )
            return results

        except Exception as exc:
            logger.error(
                "GDELT センチメント時系列取得エラー: %s (%s)", exc, company_name,
            )
            return []

    async def detect_negative_events(
        self,
        company_name: str,
        days: int = 30,
    ) -> list[NegativeEvent]:
        """ネガティブイベントを検出する。

        企業に関するネガティブな報道（トーン < -5）を検索し、
        カテゴリ分類して返す。

        Args:
            company_name: 企業名
            days: 検索期間（日数、デフォルト30）

        Returns:
            NegativeEvent のリスト（日付降順）。取得失敗時は空リスト。
        """
        try:
            query = f'"{company_name}"'
            timespan = f"{days}d"

            # ネガティブトーンのみ取得 (tone < -5)
            data = await self._fetch_gdelt(
                query=query,
                mode="artlist",
                timespan=timespan,
                tone_filter="-100:-5",
                max_records=75,
                sort="toneasc",
            )

            if not data:
                logger.info(
                    "GDELT: ネガティブイベントなし (%s, %d日間)",
                    company_name, days,
                )
                return []

            # artlist レスポンスパース
            articles = data.get("articles", [])
            if not articles:
                return []

            results: list[NegativeEvent] = []

            for article in articles:
                title = article.get("title", "")
                url = article.get("url", "")
                source = article.get("domain", article.get("source", ""))
                date_str = article.get("seendate", "")
                tone = 0.0

                # トーン値の取得
                try:
                    tone = float(article.get("tone", 0))
                except (ValueError, TypeError):
                    pass

                # 日付の正規化
                iso_date = ""
                if date_str:
                    try:
                        # GDELT seendate format: "20240115T120000Z"
                        if "T" in date_str:
                            dt = datetime.strptime(
                                date_str[:15], "%Y%m%dT%H%M%S"
                            )
                        else:
                            dt = datetime.strptime(date_str[:8], "%Y%m%d")
                        iso_date = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        iso_date = date_str

                # カテゴリ分類
                category = self._classify_negative_category(title)

                results.append(NegativeEvent(
                    date=iso_date,
                    headline=title,
                    source=source,
                    category=category,
                    tone=tone,
                    url=url,
                ))

            # トーンの昇順（最もネガティブが先）
            results.sort(key=lambda e: e.tone)

            logger.info(
                "GDELT: ネガティブイベント %d件検出 (%s, %d日間)",
                len(results), company_name, days,
            )
            return results

        except Exception as exc:
            logger.error(
                "GDELT ネガティブイベント検出エラー: %s (%s)", exc, company_name,
            )
            return []

    async def get_company_risk_from_news(
        self,
        company_name: str,
    ) -> dict:
        """ニュース報道から企業リスクスコアを算出する。

        直近30日間のセンチメントとネガティブイベントを統合し、
        0-100のリスクスコアを算出する。

        スコアリング基準:
          - 平均トーン: ネガティブほどスコア増加
          - ネガティブ記事比率: 高いほどスコア増加
          - 深刻カテゴリ: SANCTIONS, LABOR_VIOLATION は加重
          - 記事数: 報道量に応じた信頼度補正

        Args:
            company_name: 企業名

        Returns:
            リスク評価結果の辞書:
            - company: 企業名
            - risk_score: リスクスコア (0-100)
            - risk_level: リスクレベル
            - avg_tone: 平均トーン
            - negative_event_count: ネガティブイベント数
            - top_categories: 上位カテゴリ
            - evidence: 根拠リスト
        """
        result = {
            "company": company_name,
            "risk_score": 0,
            "risk_level": "LOW",
            "avg_tone": 0.0,
            "negative_event_count": 0,
            "top_categories": [],
            "evidence": [],
            "data_source": "gdelt_doc_api_v2",
        }

        try:
            # センチメント時系列（30日）とネガティブイベントを並行取得
            timeline_task = self.get_sentiment_timeline(company_name, days=30)
            events_task = self.detect_negative_events(company_name, days=30)

            timeline, events = await asyncio.gather(
                timeline_task, events_task,
                return_exceptions=True,
            )

            # 例外処理
            if isinstance(timeline, Exception):
                logger.warning(
                    "GDELT: センチメント時系列取得で例外: %s", timeline,
                )
                timeline = []
            if isinstance(events, Exception):
                logger.warning(
                    "GDELT: ネガティブイベント検出で例外: %s", events,
                )
                events = []

            # --- センチメントからのスコア算出 ---
            tone_score = 0
            if timeline:
                tones = [p.tone for p in timeline if p.tone != 0]
                if tones:
                    avg_tone = sum(tones) / len(tones)
                    result["avg_tone"] = round(avg_tone, 2)

                    # トーンが負の場合、リスクスコアに寄与
                    # -10 → 50点, -5 → 25点, 0 → 0点
                    tone_score = max(0, int(-avg_tone * 5))
                    tone_score = min(50, tone_score)

                    if avg_tone < -5:
                        result["evidence"].append(
                            f"[GDELT] 報道トーン平均: {avg_tone:.2f}（著しくネガティブ）"
                        )
                    elif avg_tone < -2:
                        result["evidence"].append(
                            f"[GDELT] 報道トーン平均: {avg_tone:.2f}（ネガティブ傾向）"
                        )

            # --- ネガティブイベントからのスコア算出 ---
            event_score = 0
            if events:
                result["negative_event_count"] = len(events)

                # カテゴリ別集計
                category_counts: dict[str, int] = {}
                for event in events:
                    cat = event.category
                    category_counts[cat] = category_counts.get(cat, 0) + 1

                # 上位カテゴリ
                sorted_categories = sorted(
                    category_counts.items(), key=lambda x: x[1], reverse=True
                )
                result["top_categories"] = [
                    {"category": cat, "count": cnt}
                    for cat, cnt in sorted_categories[:5]
                ]

                # イベント数によるスコア
                event_score = min(30, len(events) * 3)

                # 深刻カテゴリのボーナス
                critical_categories = {"SANCTIONS", "LABOR_VIOLATION", "CORRUPTION"}
                for cat, cnt in category_counts.items():
                    if cat in critical_categories:
                        event_score += min(20, cnt * 5)

                event_score = min(50, event_score)

                for cat, cnt in sorted_categories[:3]:
                    result["evidence"].append(
                        f"[GDELT] ネガティブイベント: {cat} ({cnt}件)"
                    )

            # --- 総合リスクスコア ---
            risk_score = min(100, tone_score + event_score)
            result["risk_score"] = risk_score

            # リスクレベル判定
            if risk_score >= 80:
                result["risk_level"] = "CRITICAL"
            elif risk_score >= 60:
                result["risk_level"] = "HIGH"
            elif risk_score >= 40:
                result["risk_level"] = "MEDIUM"
            elif risk_score >= 20:
                result["risk_level"] = "LOW"
            else:
                result["risk_level"] = "MINIMAL"

            if not result["evidence"]:
                result["evidence"].append(
                    f"[GDELT] {company_name}: 直近30日間に顕著なネガティブ報道なし"
                )

            logger.info(
                "GDELT: 企業リスクスコア算出完了 (%s, score=%d, level=%s)",
                company_name, risk_score, result["risk_level"],
            )
            return result

        except Exception as exc:
            logger.error(
                "GDELT 企業リスクスコア算出エラー: %s (%s)", exc, company_name,
            )
            result["evidence"].append(
                f"[GDELT] リスクスコア算出エラー: {exc}"
            )
            return result


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
    async def get_volume_weighted_sentiment(
        self,
        company_name: str,
        days: int = 30,
    ) -> dict:
        """記事量で重み付けしたセンチメントスコアを算出する。

        単純な平均トーンではなく、記事数（報道量）で重み付けした
        センチメントスコアを算出する。報道量が多い日ほど
        スコアへの影響が大きくなる。

        Args:
            company_name: 企業名
            days: 取得期間（日数、デフォルト30）

        Returns:
            重み付けセンチメント辞書:
            - company: 企業名
            - weighted_tone: 記事量重み付けトーン
            - simple_tone: 単純平均トーン
            - total_articles: 総記事数
            - daily_avg_articles: 1日平均記事数
            - tone_volatility: トーンの標準偏差
            - trend_direction: トレンド方向（UP/DOWN/STABLE）
        """
        result = {
            "company": company_name,
            "weighted_tone": 0.0,
            "simple_tone": 0.0,
            "total_articles": 0,
            "daily_avg_articles": 0.0,
            "tone_volatility": 0.0,
            "trend_direction": "STABLE",
            "data_source": "gdelt_doc_api_v2",
        }

        try:
            timeline = await self.get_sentiment_timeline(company_name, days)
            if not timeline:
                return result

            # 記事量で重み付けしたトーン
            weighted_sum = 0.0
            total_weight = 0
            tones: list[float] = []

            for point in timeline:
                count = max(1, point.article_count)
                weighted_sum += point.tone * count
                total_weight += count
                tones.append(point.tone)

            if total_weight > 0:
                result["weighted_tone"] = round(weighted_sum / total_weight, 3)

            if tones:
                result["simple_tone"] = round(sum(tones) / len(tones), 3)
                result["total_articles"] = total_weight
                result["daily_avg_articles"] = round(
                    total_weight / max(1, len(tones)), 1,
                )

                # トーンの標準偏差（ボラティリティ）
                mean_tone = sum(tones) / len(tones)
                variance = sum((t - mean_tone) ** 2 for t in tones) / len(tones)
                result["tone_volatility"] = round(variance ** 0.5, 3)

                # トレンド方向（前半 vs 後半の比較）
                mid = len(tones) // 2
                if mid > 0:
                    first_half = sum(tones[:mid]) / mid
                    second_half = sum(tones[mid:]) / len(tones[mid:])
                    diff = second_half - first_half
                    if diff > 1.0:
                        result["trend_direction"] = "UP"
                    elif diff < -1.0:
                        result["trend_direction"] = "DOWN"

            logger.info(
                "GDELT: 重み付けセンチメント算出完了 (%s, weighted=%.2f)",
                company_name, result["weighted_tone"],
            )
            return result

        except Exception as exc:
            logger.error(
                "GDELT 重み付けセンチメントエラー: %s (%s)", exc, company_name,
            )
            return result

    async def detect_sentiment_spike(
        self,
        company_name: str,
        days: int = 90,
        threshold_sigma: float = 2.0,
    ) -> list[dict]:
        """センチメントの急変（スパイク）を検出する。

        過去データの平均・標準偏差に対して閾値（σ）を超える
        トーン変動を「スパイク」として検出する。

        Args:
            company_name: 企業名
            days: 分析期間（日数）
            threshold_sigma: スパイク閾値（標準偏差の倍数、デフォルト2.0）

        Returns:
            スパイクイベントのリスト:
            - date: 日付
            - tone: トーン値
            - deviation_sigma: 平均からの偏差（σ単位）
            - direction: "NEGATIVE_SPIKE" or "POSITIVE_SPIKE"
            - article_count: 当日記事数
        """
        try:
            timeline = await self.get_sentiment_timeline(company_name, days)
            if len(timeline) < 7:
                return []

            tones = [p.tone for p in timeline if p.tone != 0]
            if not tones:
                return []

            mean_tone = sum(tones) / len(tones)
            variance = sum((t - mean_tone) ** 2 for t in tones) / len(tones)
            sigma = variance ** 0.5

            if sigma < 0.1:
                return []

            spikes: list[dict] = []
            for point in timeline:
                if point.tone == 0:
                    continue
                deviation = (point.tone - mean_tone) / sigma
                if abs(deviation) >= threshold_sigma:
                    direction = (
                        "NEGATIVE_SPIKE" if deviation < 0 else "POSITIVE_SPIKE"
                    )
                    spikes.append({
                        "date": point.date,
                        "tone": point.tone,
                        "deviation_sigma": round(deviation, 2),
                        "direction": direction,
                        "article_count": point.article_count,
                    })

            spikes.sort(key=lambda x: abs(x["deviation_sigma"]), reverse=True)

            logger.info(
                "GDELT: スパイク検出 %d件 (%s, %d日間, σ=%.1f)",
                len(spikes), company_name, days, threshold_sigma,
            )
            return spikes

        except Exception as exc:
            logger.error(
                "GDELT スパイク検出エラー: %s (%s)", exc, company_name,
            )
            return []

    async def get_multilingual_sentiment(
        self,
        company_name: str,
        alt_names: Optional[list] = None,
        days: int = 30,
    ) -> dict:
        """多言語（英語+日本語+現地語）のセンチメントを統合する。

        企業の表記揺れ（英語名、日本語名、略称等）を考慮し、
        複数のクエリ結果を統合してより網羅的なセンチメントを返す。

        Args:
            company_name: 主要企業名（英語推奨）
            alt_names: 代替名称リスト（日本語名等）
            days: 取得期間（日数）

        Returns:
            統合センチメント辞書:
            - company: 企業名
            - queries_used: 使用したクエリ一覧
            - combined_tone: 統合トーン
            - articles_by_query: クエリ別記事数
            - negative_events: 全クエリ統合ネガティブイベント
        """
        queries = [company_name]
        if alt_names:
            queries.extend(alt_names)

        result = {
            "company": company_name,
            "queries_used": queries,
            "combined_tone": 0.0,
            "total_articles": 0,
            "articles_by_query": {},
            "negative_events": [],
            "data_source": "gdelt_doc_api_v2",
        }

        try:
            all_tones: list[float] = []
            all_counts: list[int] = []
            seen_urls: set[str] = set()

            for query in queries:
                timeline = await self.get_sentiment_timeline(query, days)
                events = await self.detect_negative_events(query, days)

                query_articles = 0
                for point in timeline:
                    all_tones.append(point.tone)
                    all_counts.append(point.article_count)
                    query_articles += point.article_count

                result["articles_by_query"][query] = query_articles

                # ネガティブイベントの重複排除（URL基準）
                for evt in events:
                    if evt.url not in seen_urls:
                        seen_urls.add(evt.url)
                        result["negative_events"].append({
                            "date": evt.date,
                            "headline": evt.headline,
                            "source": evt.source,
                            "category": evt.category,
                            "tone": evt.tone,
                            "query": query,
                        })

            # 統合トーン（記事数重み付け）
            weighted_sum = sum(
                t * max(1, c) for t, c in zip(all_tones, all_counts)
            )
            total_weight = sum(max(1, c) for c in all_counts)
            if total_weight > 0:
                result["combined_tone"] = round(weighted_sum / total_weight, 3)
            result["total_articles"] = total_weight

            # ネガティブイベントをトーン昇順でソート
            result["negative_events"].sort(key=lambda x: x["tone"])

            logger.info(
                "GDELT: 多言語センチメント統合完了 (%s, queries=%d, events=%d)",
                company_name, len(queries), len(result["negative_events"]),
            )
            return result

        except Exception as exc:
            logger.error(
                "GDELT 多言語センチメントエラー: %s (%s)", exc, company_name,
            )
            return result


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
async def get_company_news_risk(company_name: str) -> dict:
    """企業ニュースリスク取得のショートカット関数。"""
    client = CompanySentimentClient()
    return await client.get_company_risk_from_news(company_name)


async def get_company_sentiment_spikes(
    company_name: str, days: int = 90,
) -> list[dict]:
    """企業のセンチメントスパイク検出のショートカット関数。"""
    client = CompanySentimentClient()
    return await client.detect_sentiment_spike(company_name, days)


# ---------------------------------------------------------------------------
# メイン（動作確認用）
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    async def _demo():
        print("=" * 60)
        print("GDELT 企業センチメント分析クライアント -- 動作確認")
        print("=" * 60)

        client = CompanySentimentClient()
        test_company = "Toyota Motor"

        print(f"\n--- センチメント時系列: {test_company} (30日) ---")
        timeline = await client.get_sentiment_timeline(test_company, days=30)
        print(f"  データポイント: {len(timeline)}件")
        for point in timeline[:5]:
            print(
                f"  {point.date}: tone={point.tone:.2f}, "
                f"articles={point.article_count}"
            )

        print(f"\n--- ネガティブイベント: {test_company} (30日) ---")
        events = await client.detect_negative_events(test_company, days=30)
        print(f"  検出: {len(events)}件")
        for event in events[:5]:
            print(
                f"  [{event.category}] {event.headline[:60]}... "
                f"(tone={event.tone:.1f})"
            )

        print(f"\n--- 企業リスクスコア: {test_company} ---")
        risk = await client.get_company_risk_from_news(test_company)
        print(f"  リスクスコア: {risk['risk_score']}/100")
        print(f"  リスクレベル: {risk['risk_level']}")
        print(f"  平均トーン: {risk['avg_tone']}")
        for ev in risk["evidence"]:
            print(f"  {ev}")

    asyncio.run(_demo())
