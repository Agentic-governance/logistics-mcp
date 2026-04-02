"""Wikidata 経営陣情報クライアント
SPARQL エンドポイント経由で企業の役員・取締役情報を取得する。

データソース: https://query.wikidata.org/sparql
レート制限: 1リクエスト/2秒
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
RATE_LIMIT_INTERVAL = 2.0  # 1 req/2sec (Wikidata 推奨)
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "SCRI-Platform/1.0 (supply-chain-risk-research; Python/requests)"


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
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class Executive:
    """企業経営幹部レコード"""
    name: str
    wikidata_id: str
    position: str        # CEO, CFO, etc.
    company: str
    start_date: str
    end_date: str
    nationality: str


@dataclass
class BoardMember:
    """取締役レコード"""
    name: str
    wikidata_id: str
    company: str
    board_role: str
    other_boards: list[str] = field(default_factory=list)  # 兼任先


# ---------------------------------------------------------------------------
# SPARQL helper
# ---------------------------------------------------------------------------
def _execute_sparql(query: str) -> list[dict]:
    """Wikidata SPARQL クエリを実行し、結果をdictリストで返す。

    レートリミット付き。エラー時は空リストを返す。
    """
    _rate.wait()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/sparql-results+json",
    }
    try:
        resp = requests.get(
            WIKIDATA_SPARQL_ENDPOINT,
            params={"query": query, "format": "json"},
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        bindings = data.get("results", {}).get("bindings", [])
        return bindings
    except requests.exceptions.Timeout:
        logger.warning("Wikidata SPARQL タイムアウト")
        return []
    except requests.exceptions.ConnectionError:
        logger.warning("Wikidata SPARQL 接続エラー")
        return []
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        logger.warning("Wikidata SPARQL HTTPエラー (%s)", status)
        return []
    except ValueError:
        logger.warning("Wikidata SPARQL JSON パースエラー")
        return []
    except Exception as e:
        logger.warning("Wikidata SPARQL 予期しないエラー: %s", e)
        return []


def _extract_value(binding: dict, key: str, default: str = "") -> str:
    """SPARQLバインディングから値を抽出する。"""
    v = binding.get(key, {})
    if isinstance(v, dict):
        return v.get("value", default)
    return default


def _extract_wikidata_id(uri: str) -> str:
    """Wikidata URI (http://www.wikidata.org/entity/Q...) からIDを抽出する。"""
    if "/" in uri:
        return uri.rsplit("/", 1)[-1]
    return uri


# ---------------------------------------------------------------------------
# SPARQL queries
# ---------------------------------------------------------------------------
SPARQL_FIND_COMPANY = """
SELECT ?company ?companyLabel WHERE {{
  ?company wdt:P31/wdt:P279* wd:Q4830453 .
  ?company rdfs:label "{company_name}"@en .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}} LIMIT 5
"""

SPARQL_FIND_COMPANY_FUZZY = """
SELECT ?company ?companyLabel WHERE {{
  ?company wdt:P31/wdt:P279* wd:Q4830453 .
  ?company rdfs:label ?label .
  FILTER(CONTAINS(LCASE(?label), LCASE("{company_name}")))
  FILTER(LANG(?label) = "en" || LANG(?label) = "ja")
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}} LIMIT 5
"""

SPARQL_EXECUTIVES = """
SELECT ?person ?personLabel ?posLabel ?startDate ?endDate ?nationalityLabel WHERE {{
  wd:{company_qid} p:P169 ?stmt .
  ?stmt ps:P169 ?person .
  OPTIONAL {{ ?stmt pq:P580 ?startDate . }}
  OPTIONAL {{ ?stmt pq:P582 ?endDate . }}
  OPTIONAL {{ ?person wdt:P27 ?nationality . }}
  OPTIONAL {{ ?stmt pq:P39 ?pos . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}}
"""

SPARQL_EXECUTIVES_BROAD = """
SELECT ?person ?personLabel ?posLabel ?startDate ?endDate ?nationalityLabel WHERE {{
  {{
    wd:{company_qid} p:P169 ?stmt .
    ?stmt ps:P169 ?person .
    OPTIONAL {{ ?stmt pq:P580 ?startDate . }}
    OPTIONAL {{ ?stmt pq:P582 ?endDate . }}
    OPTIONAL {{ ?person wdt:P27 ?nationality . }}
    OPTIONAL {{ ?stmt pq:P39 ?pos . }}
  }} UNION {{
    ?person wdt:P108 wd:{company_qid} .
    ?person p:P39 ?posStmt .
    ?posStmt ps:P39 ?pos .
    OPTIONAL {{ ?posStmt pq:P580 ?startDate . }}
    OPTIONAL {{ ?posStmt pq:P582 ?endDate . }}
    OPTIONAL {{ ?person wdt:P27 ?nationality . }}
    ?pos wdt:P31/wdt:P279* wd:Q484876 .
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}} LIMIT 50
"""

SPARQL_BOARD_MEMBERS = """
SELECT ?person ?personLabel ?roleLabel WHERE {{
  wd:{company_qid} p:P3320 ?stmt .
  ?stmt ps:P3320 ?person .
  OPTIONAL {{ ?stmt pq:P39 ?role . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}} LIMIT 50
"""

SPARQL_OTHER_BOARDS = """
SELECT ?company ?companyLabel WHERE {{
  ?company p:P3320 ?stmt .
  ?stmt ps:P3320 wd:{person_qid} .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}} LIMIT 20
"""

SPARQL_INTERLOCKING = """
SELECT ?person ?personLabel ?otherCompany ?otherCompanyLabel WHERE {{
  wd:{company_qid} p:P3320 ?stmt1 .
  ?stmt1 ps:P3320 ?person .
  ?otherCompany p:P3320 ?stmt2 .
  ?stmt2 ps:P3320 ?person .
  FILTER(?otherCompany != wd:{company_qid})
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}} LIMIT 100
"""


# ---------------------------------------------------------------------------
# WikidataClient
# ---------------------------------------------------------------------------
class WikidataClient:
    """Wikidata SPARQL クライアント — 企業経営陣・取締役情報取得"""

    def _resolve_company_qid(self, company_name: str) -> Optional[str]:
        """企業名からWikidata QIDを解決する。"""
        # 1. 完全一致検索
        query = SPARQL_FIND_COMPANY.format(company_name=company_name.replace('"', '\\"'))
        results = _execute_sparql(query)
        if results:
            uri = _extract_value(results[0], "company")
            return _extract_wikidata_id(uri)

        # 2. 部分一致検索
        query = SPARQL_FIND_COMPANY_FUZZY.format(company_name=company_name.replace('"', '\\"'))
        results = _execute_sparql(query)
        if results:
            uri = _extract_value(results[0], "company")
            return _extract_wikidata_id(uri)

        logger.info("Wikidata: '%s' の企業IDが見つかりません", company_name)
        return None

    def _get_other_boards(self, person_qid: str) -> list[str]:
        """人物の兼任先企業リストを取得する。"""
        query = SPARQL_OTHER_BOARDS.format(person_qid=person_qid)
        results = _execute_sparql(query)
        boards = []
        for r in results:
            label = _extract_value(r, "companyLabel")
            if label:
                boards.append(label)
        return boards

    # ---- Sync API ---------------------------------------------------------

    def get_executives_sync(self, company_name: str) -> list[Executive]:
        """企業の経営幹部（CEO, CFO等）を返す（同期版）。"""
        try:
            qid = self._resolve_company_qid(company_name)
            if not qid:
                return []

            # まず狭い検索、結果がなければ広い検索
            query = SPARQL_EXECUTIVES.format(company_qid=qid)
            results = _execute_sparql(query)
            if not results:
                query = SPARQL_EXECUTIVES_BROAD.format(company_qid=qid)
                results = _execute_sparql(query)

            executives: list[Executive] = []
            seen: set[str] = set()
            for r in results:
                person_uri = _extract_value(r, "person")
                person_qid = _extract_wikidata_id(person_uri)
                name = _extract_value(r, "personLabel")
                if not name or name == person_qid:  # ラベル未解決はスキップ
                    continue
                if name in seen:
                    continue
                seen.add(name)

                position = _extract_value(r, "posLabel") or "Chief Executive Officer"
                start_date = _extract_value(r, "startDate", "")
                end_date = _extract_value(r, "endDate", "")
                nationality = _extract_value(r, "nationalityLabel", "")

                # 日付のフォーマット調整
                if start_date and "T" in start_date:
                    start_date = start_date.split("T")[0]
                if end_date and "T" in end_date:
                    end_date = end_date.split("T")[0]

                executives.append(Executive(
                    name=name,
                    wikidata_id=person_qid,
                    position=position,
                    company=company_name,
                    start_date=start_date,
                    end_date=end_date,
                    nationality=nationality,
                ))

            logger.info("Wikidata: '%s' の経営幹部 %d 名を取得", company_name, len(executives))
            return executives
        except Exception as e:
            logger.warning("Wikidata 経営幹部取得エラー (%s): %s", company_name, e)
            return []

    def get_board_members_sync(self, company_name: str) -> list[BoardMember]:
        """企業の取締役（Board Members）を返す（同期版）。"""
        try:
            qid = self._resolve_company_qid(company_name)
            if not qid:
                return []

            query = SPARQL_BOARD_MEMBERS.format(company_qid=qid)
            results = _execute_sparql(query)

            members: list[BoardMember] = []
            seen: set[str] = set()
            for r in results:
                person_uri = _extract_value(r, "person")
                person_qid = _extract_wikidata_id(person_uri)
                name = _extract_value(r, "personLabel")
                if not name or name == person_qid:
                    continue
                if name in seen:
                    continue
                seen.add(name)

                role = _extract_value(r, "roleLabel") or "Board Member"

                # 兼任先を取得
                other_boards = self._get_other_boards(person_qid)

                members.append(BoardMember(
                    name=name,
                    wikidata_id=person_qid,
                    company=company_name,
                    board_role=role,
                    other_boards=other_boards,
                ))

            logger.info("Wikidata: '%s' の取締役 %d 名を取得", company_name, len(members))
            return members
        except Exception as e:
            logger.warning("Wikidata 取締役取得エラー (%s): %s", company_name, e)
            return []

    def find_interlocking_directorates_sync(self, company_name: str) -> dict:
        """兼任役員ネットワーク（インターロッキング・ダイレクトレート）を検出する（同期版）。"""
        try:
            qid = self._resolve_company_qid(company_name)
            if not qid:
                return {
                    "company": company_name,
                    "interlocking_directors": [],
                    "connected_companies": [],
                    "total_connections": 0,
                }

            query = SPARQL_INTERLOCKING.format(company_qid=qid)
            results = _execute_sparql(query)

            directors: dict[str, list[str]] = {}  # person_name -> [company_names]
            connected_companies: set[str] = set()

            for r in results:
                person_name = _extract_value(r, "personLabel")
                other_company = _extract_value(r, "otherCompanyLabel")
                if not person_name or not other_company:
                    continue
                # QIDそのままのラベルはスキップ
                if person_name.startswith("Q") and person_name[1:].isdigit():
                    continue
                if other_company.startswith("Q") and other_company[1:].isdigit():
                    continue

                if person_name not in directors:
                    directors[person_name] = []
                if other_company not in directors[person_name]:
                    directors[person_name].append(other_company)
                connected_companies.add(other_company)

            interlocking = [
                {
                    "director_name": name,
                    "shared_companies": companies,
                    "connection_count": len(companies),
                }
                for name, companies in directors.items()
            ]
            interlocking.sort(key=lambda x: x["connection_count"], reverse=True)

            return {
                "company": company_name,
                "interlocking_directors": interlocking,
                "connected_companies": sorted(connected_companies),
                "total_connections": sum(len(c) for c in directors.values()),
            }
        except Exception as e:
            logger.warning("Wikidata 兼任役員検出エラー (%s): %s", company_name, e)
            return {
                "company": company_name,
                "interlocking_directors": [],
                "connected_companies": [],
                "total_connections": 0,
                "error": str(e),
            }

    def get_person_affiliations_sync(self, person_name: str) -> dict:
        """人物名から全企業関係（兼任役員含む）を返す（同期版）。

        Wikidata で人物を検索し、その人物が関与する全企業を列挙する。

        Returns:
            {
                "person_name": str,
                "wikidata_id": str,
                "affiliations": [
                    {"company": str, "role": str, "start_date": str, "end_date": str}
                ],
                "total_affiliations": int,
                "concurrent_roles": int,  # 現在同時に兼任している数
            }
        """
        SPARQL_FIND_PERSON = """
SELECT ?person ?personLabel WHERE {{
  ?person wdt:P31 wd:Q5 .
  ?person rdfs:label "{person_name}"@en .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}} LIMIT 5
"""
        SPARQL_PERSON_AFFILIATIONS = """
SELECT ?company ?companyLabel ?roleLabel ?startDate ?endDate WHERE {{
  {{
    ?company p:P169 ?stmt .
    ?stmt ps:P169 wd:{person_qid} .
    OPTIONAL {{ ?stmt pq:P580 ?startDate . }}
    OPTIONAL {{ ?stmt pq:P582 ?endDate . }}
    OPTIONAL {{ ?stmt pq:P39 ?role . }}
  }} UNION {{
    ?company p:P3320 ?stmt .
    ?stmt ps:P3320 wd:{person_qid} .
    OPTIONAL {{ ?stmt pq:P580 ?startDate . }}
    OPTIONAL {{ ?stmt pq:P582 ?endDate . }}
    OPTIONAL {{ ?stmt pq:P39 ?role . }}
  }} UNION {{
    wd:{person_qid} wdt:P108 ?company .
    wd:{person_qid} p:P39 ?posStmt .
    ?posStmt ps:P39 ?role .
    OPTIONAL {{ ?posStmt pq:P580 ?startDate . }}
    OPTIONAL {{ ?posStmt pq:P582 ?endDate . }}
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}} LIMIT 50
"""
        try:
            # 人物のWikidata IDを解決
            query = SPARQL_FIND_PERSON.format(person_name=person_name.replace('"', '\\"'))
            results = _execute_sparql(query)
            if not results:
                return {
                    "person_name": person_name,
                    "wikidata_id": "",
                    "affiliations": [],
                    "total_affiliations": 0,
                    "concurrent_roles": 0,
                }

            person_uri = _extract_value(results[0], "person")
            person_qid = _extract_wikidata_id(person_uri)

            # 全関連企業を取得
            query = SPARQL_PERSON_AFFILIATIONS.format(person_qid=person_qid)
            aff_results = _execute_sparql(query)

            affiliations: list[dict] = []
            seen_companies: set[str] = set()
            concurrent = 0

            for r in aff_results:
                company_label = _extract_value(r, "companyLabel")
                if not company_label or company_label.startswith("Q"):
                    continue
                if company_label in seen_companies:
                    continue
                seen_companies.add(company_label)

                role = _extract_value(r, "roleLabel") or "関連"
                start_date = _extract_value(r, "startDate", "")
                end_date = _extract_value(r, "endDate", "")
                if start_date and "T" in start_date:
                    start_date = start_date.split("T")[0]
                if end_date and "T" in end_date:
                    end_date = end_date.split("T")[0]

                affiliations.append({
                    "company": company_label,
                    "role": role,
                    "start_date": start_date,
                    "end_date": end_date,
                })

                # 終了日がなければ現任とみなす
                if not end_date:
                    concurrent += 1

            return {
                "person_name": person_name,
                "wikidata_id": person_qid,
                "affiliations": affiliations,
                "total_affiliations": len(affiliations),
                "concurrent_roles": concurrent,
            }
        except Exception as e:
            logger.warning("人物関連企業取得エラー (%s): %s", person_name, e)
            return {
                "person_name": person_name,
                "wikidata_id": "",
                "affiliations": [],
                "total_affiliations": 0,
                "concurrent_roles": 0,
                "error": str(e),
            }

    def find_revolving_door_sync(self, person_name: str) -> dict:
        """天下り（政府機関→民間）パターンを検出する（同期版）。

        Wikidata で人物の職歴を取得し、政府機関に勤務した後に
        民間企業に就任しているケースを検出する。

        Returns:
            {
                "person_name": str,
                "revolving_door_detected": bool,
                "government_positions": [...],
                "private_positions": [...],
                "risk_score": int,  # 0=検出なし, 10-50=天下り検出
            }
        """
        SPARQL_CAREER_HISTORY = """
SELECT ?org ?orgLabel ?posLabel ?startDate ?endDate ?orgType ?orgTypeLabel WHERE {{
  wd:{person_qid} p:P39 ?posStmt .
  ?posStmt ps:P39 ?pos .
  OPTIONAL {{ ?posStmt pq:P580 ?startDate . }}
  OPTIONAL {{ ?posStmt pq:P582 ?endDate . }}
  OPTIONAL {{ ?pos wdt:P2389 ?org . }}
  OPTIONAL {{ ?org wdt:P31 ?orgType . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,ja" . }}
}} LIMIT 50
"""
        # 政府機関キーワード（英語・日本語）
        GOV_KEYWORDS = {
            "ministry", "government", "agency", "bureau", "department",
            "commission", "authority", "regulator", "regulatory",
            "cabinet", "parliament", "congress", "senate",
            "省", "庁", "局", "委員会", "内閣", "国会",
            "central bank", "fed", "日本銀行", "財務省", "金融庁",
        }

        try:
            # まず人物IDを解決
            affiliations = self.get_person_affiliations_sync(person_name)
            person_qid = affiliations.get("wikidata_id", "")

            if not person_qid:
                return {
                    "person_name": person_name,
                    "revolving_door_detected": False,
                    "government_positions": [],
                    "private_positions": [],
                    "risk_score": 0,
                }

            # キャリア履歴取得
            query = SPARQL_CAREER_HISTORY.format(person_qid=person_qid)
            results = _execute_sparql(query)

            gov_positions: list[dict] = []
            private_positions: list[dict] = []

            for r in results:
                org = _extract_value(r, "orgLabel") or ""
                pos = _extract_value(r, "posLabel") or ""
                org_type = _extract_value(r, "orgTypeLabel") or ""
                start = _extract_value(r, "startDate", "")
                end = _extract_value(r, "endDate", "")
                if start and "T" in start:
                    start = start.split("T")[0]
                if end and "T" in end:
                    end = end.split("T")[0]

                combined = f"{org} {pos} {org_type}".lower()
                is_gov = any(kw in combined for kw in GOV_KEYWORDS)

                entry = {
                    "organization": org,
                    "position": pos,
                    "org_type": org_type,
                    "start_date": start,
                    "end_date": end,
                }

                if is_gov:
                    gov_positions.append(entry)
                elif org:
                    private_positions.append(entry)

            # 関連企業情報もフォールバックとして利用
            if not private_positions:
                for aff in affiliations.get("affiliations", []):
                    combined = f"{aff.get('company', '')} {aff.get('role', '')}".lower()
                    is_gov = any(kw in combined for kw in GOV_KEYWORDS)
                    if not is_gov:
                        private_positions.append({
                            "organization": aff.get("company", ""),
                            "position": aff.get("role", ""),
                            "start_date": aff.get("start_date", ""),
                            "end_date": aff.get("end_date", ""),
                        })
                    elif is_gov and not gov_positions:
                        gov_positions.append({
                            "organization": aff.get("company", ""),
                            "position": aff.get("role", ""),
                            "start_date": aff.get("start_date", ""),
                            "end_date": aff.get("end_date", ""),
                        })

            # 天下り検出: 政府機関経験あり + 民間企業あり
            revolving = bool(gov_positions and private_positions)
            risk_score = 0
            if revolving:
                risk_score = 10  # 基本スコア
                # 規制当局出身で同業界に転職していれば高リスク
                if len(gov_positions) >= 2:
                    risk_score += 10
                if len(private_positions) >= 3:
                    risk_score += 10
                risk_score = min(risk_score, 50)

            return {
                "person_name": person_name,
                "revolving_door_detected": revolving,
                "government_positions": gov_positions,
                "private_positions": private_positions,
                "risk_score": risk_score,
            }
        except Exception as e:
            logger.warning("天下り検出エラー (%s): %s", person_name, e)
            return {
                "person_name": person_name,
                "revolving_door_detected": False,
                "government_positions": [],
                "private_positions": [],
                "risk_score": 0,
                "error": str(e),
            }

    # ---- Async API --------------------------------------------------------

    async def get_executives(self, company_name: str) -> list[Executive]:
        """企業の経営幹部（CEO, CFO等）を返す"""
        return await asyncio.to_thread(self.get_executives_sync, company_name)

    async def get_board_members(self, company_name: str) -> list[BoardMember]:
        """企業の取締役を返す"""
        return await asyncio.to_thread(self.get_board_members_sync, company_name)

    async def find_interlocking_directorates(self, company_name: str) -> dict:
        """兼任役員ネットワークを検出する"""
        return await asyncio.to_thread(self.find_interlocking_directorates_sync, company_name)

    async def get_person_affiliations(self, person_name: str) -> dict:
        """人物の全企業関係を取得する"""
        return await asyncio.to_thread(self.get_person_affiliations_sync, person_name)

    async def find_revolving_door(self, person_name: str) -> dict:
        """天下りパターンを検出する"""
        return await asyncio.to_thread(self.find_revolving_door_sync, person_name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Wikidata Executive Info Client")
    parser.add_argument("company", help="企業名（英語推奨）")
    parser.add_argument("--board", action="store_true", help="取締役情報を表示")
    parser.add_argument("--interlock", action="store_true", help="兼任役員ネットワークを表示")
    args = parser.parse_args()

    client = WikidataClient()

    if args.interlock:
        result = client.find_interlocking_directorates_sync(args.company)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.board:
        members = client.get_board_members_sync(args.company)
        for m in members:
            other = f" (兼任: {', '.join(m.other_boards)})" if m.other_boards else ""
            print(f"  {m.name} — {m.board_role}{other}")
        if not members:
            print("  (取締役情報なし)")
    else:
        execs = client.get_executives_sync(args.company)
        for e in execs:
            period = f"{e.start_date or '?'} ~ {e.end_date or '現任'}"
            nat = f" ({e.nationality})" if e.nationality else ""
            print(f"  {e.name}{nat} — {e.position} [{period}]")
        if not execs:
            print("  (経営幹部情報なし)")
