"""ICIJ Offshore Leaks DB クライアント
パナマ文書・パンドラ文書等のオフショアリーク情報を検索する。

データソース: https://offshoreleaks.icij.org/
API: https://offshoreleaks.icij.org/api/v1/search?q={name}
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ICIJ_API_BASE = "https://offshoreleaks.icij.org/api/v1"
RATE_LIMIT_INTERVAL = 1.0  # 1 req/sec
REQUEST_TIMEOUT = 15  # seconds
USER_AGENT = "SCRI-Platform/1.0 (supply-chain-risk-research)"

# エンティティタイプマッピング
ENTITY_TYPES = {
    "officer": "Officer",
    "entity": "Entity",
    "intermediary": "Intermediary",
    "address": "Address",
    "other": "Other",
}

# データソース名マッピング
DATA_SOURCES = {
    "panama_papers": "Panama Papers",
    "pandora_papers": "Pandora Papers",
    "paradise_papers": "Paradise Papers",
    "bahamas_leaks": "Bahamas Leaks",
    "offshore_leaks": "Offshore Leaks",
}


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
class _RateLimiter:
    """シンプルなレートリミッター"""

    def __init__(self):
        self._last_request: float = 0.0

    def wait(self):
        now = time.monotonic()
        diff = now - self._last_request
        if diff < RATE_LIMIT_INTERVAL:
            time.sleep(RATE_LIMIT_INTERVAL - diff)
        self._last_request = time.monotonic()


_rate = _RateLimiter()


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------
@dataclass
class LeakRecord:
    """オフショアリーク検索結果レコード"""
    entity_name: str
    entity_type: str    # "Officer", "Entity", "Intermediary", "Address"
    jurisdiction: str
    linked_to: str
    data_source: str    # "Panama Papers", "Pandora Papers", etc.
    node_id: str


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def _api_get(path: str, params: Optional[dict] = None) -> dict:
    """ICIJ API にGETリクエストを送信する。

    レートリミット付き。API不達時は空dictを返す。
    """
    _rate.wait()
    url = f"{ICIJ_API_BASE}/{path.lstrip('/')}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.warning("ICIJ API タイムアウト: %s", url)
        return {}
    except requests.exceptions.ConnectionError:
        logger.warning("ICIJ API 接続エラー: %s", url)
        return {}
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        logger.warning("ICIJ API HTTPエラー (%s): %s", status, url)
        return {}
    except ValueError:
        logger.warning("ICIJ API JSON パースエラー: %s", url)
        return {}
    except Exception as e:
        logger.warning("ICIJ API 予期しないエラー: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------
def _parse_search_results(data: dict, type_filter: str = "") -> list[LeakRecord]:
    """API応答からLeakRecordリストを生成する。"""
    records: list[LeakRecord] = []

    # API応答の形式に応じてパース
    # 形式1: {"results": [...]}  形式2: {"data": [...]}  形式3: リスト直接
    raw_results = data.get("results", data.get("data", data.get("nodes", [])))
    if isinstance(data, list):
        raw_results = data

    if not isinstance(raw_results, list):
        return records

    for item in raw_results:
        if not isinstance(item, dict):
            continue

        # エンティティ名
        entity_name = (
            item.get("name", "")
            or item.get("entity_name", "")
            or item.get("caption", "")
            or ""
        )
        if not entity_name:
            continue

        # エンティティタイプ
        raw_type = str(
            item.get("type", "")
            or item.get("entity_type", "")
            or item.get("schema", "")
        ).lower()
        entity_type = ENTITY_TYPES.get(raw_type, raw_type.capitalize() or "Other")

        # タイプフィルタ
        if type_filter and entity_type.lower() != type_filter.lower():
            continue

        # 法域
        jurisdiction = (
            item.get("jurisdiction", "")
            or item.get("jurisdiction_description", "")
            or item.get("country", "")
            or ""
        )

        # 関連先
        linked_to = (
            item.get("linked_to", "")
            or item.get("connected_to", "")
            or item.get("related_entity", "")
            or ""
        )

        # データソース
        raw_source = str(
            item.get("source", "")
            or item.get("sourceID", "")
            or item.get("data_source", "")
            or item.get("dataset", "")
        ).lower().replace(" ", "_")
        data_source = DATA_SOURCES.get(raw_source, raw_source.replace("_", " ").title() or "Unknown")

        # ノードID
        node_id = str(
            item.get("node_id", "")
            or item.get("id", "")
            or item.get("nodeID", "")
            or ""
        )

        records.append(LeakRecord(
            entity_name=entity_name,
            entity_type=entity_type,
            jurisdiction=jurisdiction,
            linked_to=linked_to,
            data_source=data_source,
            node_id=node_id,
        ))

    return records


# ---------------------------------------------------------------------------
# ICIJClient
# ---------------------------------------------------------------------------
class ICIJClient:
    """ICIJ Offshore Leaks Database クライアント"""

    # ---- Sync API ---------------------------------------------------------

    def search_entity_sync(self, name: str) -> list[LeakRecord]:
        """企業名・人物名でオフショアリーク検索（同期版）。"""
        try:
            data = _api_get("search", params={"q": name})
            if not data:
                logger.info("ICIJ: '%s' のリーク情報が見つかりません", name)
                return []
            results = _parse_search_results(data)
            logger.info("ICIJ: '%s' で %d 件のリーク情報を取得", name, len(results))
            return results
        except Exception as e:
            logger.warning("ICIJ 検索エラー (%s): %s", name, e)
            return []

    def search_officer_sync(self, name: str) -> list[LeakRecord]:
        """人物名（Officer）でオフショアリーク検索（同期版）。"""
        try:
            # Officer専用エンドポイントを試行
            data = _api_get("search", params={"q": name, "type": "officer"})
            if not data:
                # フォールバック: 通常検索 + フィルタ
                data = _api_get("search", params={"q": name})
            if not data:
                return []
            return _parse_search_results(data, type_filter="Officer")
        except Exception as e:
            logger.warning("ICIJ Officer検索エラー (%s): %s", name, e)
            return []

    def search_company_sync(self, name: str) -> list[LeakRecord]:
        """企業名（Entity）でオフショアリーク検索（同期版）。"""
        try:
            # Entity専用エンドポイントを試行
            data = _api_get("search", params={"q": name, "type": "entity"})
            if not data:
                # フォールバック: 通常検索 + フィルタ
                data = _api_get("search", params={"q": name})
            if not data:
                return []
            return _parse_search_results(data, type_filter="Entity")
        except Exception as e:
            logger.warning("ICIJ Entity検索エラー (%s): %s", name, e)
            return []

    def get_offshore_risk_score_sync(self, company_name: str) -> dict:
        """企業のオフショアリスクスコアを算出する（同期版）。

        ICIJリーク情報のヒット数、法域、データソース多様性を基に
        0（クリーン）〜100（高度に複雑なオフショア構造）のスコアを返す。

        スコアリングロジック:
          - ヒット0件: 0点
          - ヒット1件: 20点ベース
          - 追加ヒット毎: +10点（上限+40）
          - タックスヘイブン法域ヒット: +15点
          - 複数データソース（パナマ+パンドラ等）: +15点
          - Officer + Entity 両方ヒット: +10点

        Returns:
            {
                "company_name": str,
                "score": float,
                "hit_count": int,
                "jurisdictions": [...],
                "data_sources": [...],
                "entity_types": [...],
                "evidence": [...],
            }
        """
        # タックスヘイブン法域
        TAX_HAVEN_JURISDICTIONS = {
            "british virgin islands", "bvi", "cayman islands", "bermuda",
            "panama", "bahamas", "jersey", "guernsey", "isle of man",
            "mauritius", "seychelles", "marshall islands", "samoa",
            "vanuatu", "belize", "liechtenstein", "monaco",
            "turks and caicos", "anguilla", "gibraltar", "labuan",
            "nevis", "st. kitts", "aruba", "curaçao", "curacao",
        }

        try:
            records = self.search_entity_sync(company_name)

            if not records:
                return {
                    "company_name": company_name,
                    "score": 0.0,
                    "hit_count": 0,
                    "jurisdictions": [],
                    "data_sources": [],
                    "entity_types": [],
                    "evidence": [],
                }

            jurisdictions = set()
            data_sources = set()
            entity_types = set()
            evidence: list[str] = []
            has_tax_haven = False

            for r in records:
                if r.jurisdiction:
                    jurisdictions.add(r.jurisdiction)
                    if r.jurisdiction.lower().strip() in TAX_HAVEN_JURISDICTIONS:
                        has_tax_haven = True
                if r.data_source:
                    data_sources.add(r.data_source)
                if r.entity_type:
                    entity_types.add(r.entity_type)

            # スコア算出
            hit_count = len(records)
            score = 0.0

            # ベーススコア: ヒット数ベース
            if hit_count >= 1:
                score = 20.0
            if hit_count > 1:
                score += min((hit_count - 1) * 10, 40)

            # タックスヘイブン法域ボーナス
            if has_tax_haven:
                score += 15.0
                evidence.append(
                    f"[オフショア] タックスヘイブン法域でのヒット検出: "
                    f"{', '.join(j for j in jurisdictions if j.lower().strip() in TAX_HAVEN_JURISDICTIONS)}"
                )

            # 複数データソースボーナス（パナマ文書+パンドラ文書等）
            if len(data_sources) >= 2:
                score += 15.0
                evidence.append(
                    f"[オフショア] 複数リークソースでヒット: {', '.join(sorted(data_sources))}"
                )

            # Officer + Entity 両方ヒットボーナス
            types_lower = {t.lower() for t in entity_types}
            if "officer" in types_lower and "entity" in types_lower:
                score += 10.0
                evidence.append(
                    "[オフショア] 企業体(Entity)と役員(Officer)の両方でリーク情報ヒット"
                )

            score = min(score, 100.0)

            if not evidence:
                evidence.append(
                    f"[オフショア] {company_name}: ICIJ Offshore Leaksで{hit_count}件ヒット "
                    f"(法域: {', '.join(sorted(jurisdictions)) or '不明'})"
                )

            return {
                "company_name": company_name,
                "score": score,
                "hit_count": hit_count,
                "jurisdictions": sorted(jurisdictions),
                "data_sources": sorted(data_sources),
                "entity_types": sorted(entity_types),
                "evidence": evidence,
            }
        except Exception as e:
            logger.warning("オフショアリスクスコア算出エラー (%s): %s", company_name, e)
            return {
                "company_name": company_name,
                "score": 0.0,
                "hit_count": 0,
                "jurisdictions": [],
                "data_sources": [],
                "entity_types": [],
                "evidence": [],
                "error": str(e),
            }

    # ---- Async API --------------------------------------------------------

    async def search_entity(self, name: str) -> list[LeakRecord]:
        """企業名・人物名でオフショアリーク検索"""
        return await asyncio.to_thread(self.search_entity_sync, name)

    async def search_officer(self, name: str) -> list[LeakRecord]:
        """人物名（Officer）でオフショアリーク検索"""
        return await asyncio.to_thread(self.search_officer_sync, name)

    async def search_company(self, name: str) -> list[LeakRecord]:
        """企業名（Entity）でオフショアリーク検索"""
        return await asyncio.to_thread(self.search_company_sync, name)

    async def get_offshore_risk_score(self, company_name: str) -> dict:
        """企業のオフショアリスクスコアを算出する"""
        return await asyncio.to_thread(self.get_offshore_risk_score_sync, company_name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ICIJ Offshore Leaks Client")
    parser.add_argument("name", help="検索名（企業名または人物名）")
    parser.add_argument("--type", choices=["entity", "officer", "company", "all"],
                        default="all", help="検索タイプ")
    args = parser.parse_args()

    client = ICIJClient()

    if args.type == "officer":
        results = client.search_officer_sync(args.name)
    elif args.type in ("company", "entity"):
        results = client.search_company_sync(args.name)
    else:
        results = client.search_entity_sync(args.name)

    for r in results:
        print(f"  [{r.entity_type}] {r.entity_name} — {r.jurisdiction} "
              f"({r.data_source}) [node: {r.node_id}]")
        if r.linked_to:
            print(f"    -> linked to: {r.linked_to}")
    if not results:
        print("  (リーク情報なし)")
