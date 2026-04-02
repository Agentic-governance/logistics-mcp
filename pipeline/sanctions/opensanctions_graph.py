"""OpenSanctions グラフ拡張クライアント
既存の制裁インフラを拡張し、PEP・制裁対象・企業間の
関連エンティティグラフを探索する。

データソース: OpenSanctions API
  https://api.opensanctions.org/search/default?q={name}
  (基本検索はAPIキー不要)

OpenSanctionsは320+のデータソースから制裁対象・PEP・
犯罪関連エンティティを統合し、エンティティ間の関係
（所有構造、役員関係等）をグラフ構造で提供する。

使用例::

    graph = OpenSanctionsGraph()
    related = await graph.get_related_entities("ACME Corp")
    ownership = await graph.get_ownership_structure("ACME Corp")
    network = await graph.check_sanctions_network("John Doe")
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 15  # 秒
RATE_LIMIT_INTERVAL = 2.0  # 秒
USER_AGENT = "SCRI-Platform/1.0 (supply-chain-risk-intelligence)"

OPENSANCTIONS_API_BASE = "https://api.opensanctions.org"
OPENSANCTIONS_SEARCH_URL = f"{OPENSANCTIONS_API_BASE}/search/default"
OPENSANCTIONS_ENTITY_URL = f"{OPENSANCTIONS_API_BASE}/entities"

# エンティティスキーマ → リスクカテゴリ
SCHEMA_TO_TYPE: dict[str, str] = {
    "Person": "Person",
    "Organization": "Company",
    "Company": "Company",
    "LegalEntity": "LegalEntity",
    "Vessel": "Vessel",
    "Aircraft": "Aircraft",
    "Sanction": "Sanction",
    "Position": "PEP",
    "Directorship": "PEP",
    "Ownership": "Ownership",
    "UnknownLink": "Unknown",
    "Family": "Person",
    "Associate": "Person",
}

# トピック → スキーマタイプ
TOPIC_TO_SCHEMA: dict[str, str] = {
    "sanction": "Sanction",
    "debarment": "Sanction",
    "crime": "Crime",
    "crime.fraud": "Crime",
    "crime.terror": "Crime",
    "crime.cyber": "Crime",
    "crime.fin": "Crime",
    "crime.war": "Crime",
    "role.pep": "PEP",
    "role.rca": "PEP",
    "poi": "POI",
}


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class RelatedEntity:
    """関連エンティティ情報"""
    name: str
    entity_type: str  # "Person", "Company", "LegalEntity"
    schema_type: str  # "Sanction", "PEP", "Crime"
    relationship: str  # 関係の種類
    country: str
    datasets: list[str] = field(default_factory=list)


@dataclass
class OwnershipNode:
    """所有構造ノード（再帰的ツリー構造）"""
    name: str
    entity_type: str
    ownership_pct: float
    children: list = field(default_factory=list)  # list[OwnershipNode]


# ---------------------------------------------------------------------------
# メインクライアント
# ---------------------------------------------------------------------------
class OpenSanctionsGraph:
    """OpenSanctions グラフ探索クライアント

    OpenSanctions API を使用してエンティティ間の関連を探索する。
    制裁対象・PEP・犯罪関連のエンティティネットワークを辿り、
    サプライチェーン上の隠れたリスクを検出する。

    機能:
      - 関連エンティティの検索（N-hop グラフ探索）
      - 所有構造（株主ツリー）の取得
      - 制裁ネットワークチェック（2-hop以内の制裁対象検出）

    制限事項:
      - 基本検索APIはキー不要だが、レート制限あり
      - エンティティ詳細はOpenSanctions有料プラン推奨
      - API到達不能時は空結果を返し、クラッシュしない
    """

    def __init__(self):
        """クライアントを初期化する。"""
        self._last_request_time: float = 0.0
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        # 探索済みエンティティのキャッシュ（セッション内）
        self._visited_entities: set[str] = set()

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
    async def _search_entity(self, query: str, limit: int = 10) -> list[dict]:
        """OpenSanctions API でエンティティを検索する。

        Args:
            query: 検索クエリ（エンティティ名）
            limit: 結果の最大件数

        Returns:
            検索結果のエンティティリスト（辞書形式）
        """
        await self._rate_limit()

        params = {
            "q": query,
            "limit": limit,
        }

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers=self._headers,
                follow_redirects=True,
            ) as client:
                resp = await client.get(OPENSANCTIONS_SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                return data.get("results", [])

        except httpx.TimeoutException:
            logger.warning("OpenSanctions APIタイムアウト: query=%s", query)
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "OpenSanctions API HTTPエラー %d: query=%s",
                exc.response.status_code, query,
            )
            return []
        except httpx.HTTPError as exc:
            logger.warning("OpenSanctions API接続エラー: %s", exc)
            return []
        except Exception as exc:
            logger.error("OpenSanctions API予期せぬエラー: %s", exc)
            return []

    async def _get_entity_detail(self, entity_id: str) -> dict:
        """OpenSanctions API でエンティティ詳細を取得する。

        Args:
            entity_id: OpenSanctionsエンティティID

        Returns:
            エンティティ詳細の辞書。取得失敗時は空辞書。
        """
        await self._rate_limit()

        url = f"{OPENSANCTIONS_ENTITY_URL}/{entity_id}"

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                headers=self._headers,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()

        except httpx.TimeoutException:
            logger.warning(
                "OpenSanctions エンティティ詳細タイムアウト: %s", entity_id,
            )
            return {}
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "OpenSanctions エンティティ詳細 HTTPエラー %d: %s",
                exc.response.status_code, entity_id,
            )
            return {}
        except httpx.HTTPError as exc:
            logger.warning("OpenSanctions エンティティ詳細接続エラー: %s", exc)
            return {}
        except Exception as exc:
            logger.error("OpenSanctions エンティティ詳細エラー: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # エンティティ情報の抽出
    # ------------------------------------------------------------------
    def _extract_entity_info(self, entity: dict) -> dict:
        """APIレスポンスからエンティティ情報を抽出する。

        Args:
            entity: OpenSanctions APIのエンティティ辞書

        Returns:
            正規化されたエンティティ情報の辞書
        """
        schema = entity.get("schema", "")
        entity_type = SCHEMA_TO_TYPE.get(schema, "Unknown")

        # トピックからスキーマタイプを判定
        topics = entity.get("topics", [])
        schema_type = "Unknown"
        for topic in topics:
            if topic in TOPIC_TO_SCHEMA:
                schema_type = TOPIC_TO_SCHEMA[topic]
                break

        # 国情報の取得
        properties = entity.get("properties", {})
        countries = properties.get("country", [])
        country = countries[0] if countries else ""

        # データセット情報
        datasets = entity.get("datasets", [])

        return {
            "id": entity.get("id", ""),
            "name": entity.get("caption", entity.get("name", "")),
            "entity_type": entity_type,
            "schema_type": schema_type,
            "schema": schema,
            "country": country,
            "datasets": datasets,
            "topics": topics,
            "properties": properties,
            "score": entity.get("score", 0.0),
        }

    # ------------------------------------------------------------------
    # 関連エンティティの探索
    # ------------------------------------------------------------------
    def _extract_relationships(self, entity: dict) -> list[dict]:
        """エンティティから関連情報を抽出する。

        OpenSanctionsのプロパティから所有関係・役員関係・
        家族関係等を抽出する。

        Args:
            entity: OpenSanctionsエンティティ辞書

        Returns:
            関連情報の辞書リスト
        """
        relationships: list[dict] = []
        properties = entity.get("properties", {})

        # 所有関係
        for owner in properties.get("ownershipOwner", []):
            relationships.append({
                "target": owner,
                "type": "ownership_owner",
                "description": "所有者",
            })
        for asset in properties.get("ownershipAsset", []):
            relationships.append({
                "target": asset,
                "type": "ownership_asset",
                "description": "被所有企業",
            })

        # 役員関係
        for director in properties.get("directorshipDirector", []):
            relationships.append({
                "target": director,
                "type": "directorship",
                "description": "取締役",
            })
        for org in properties.get("directorshipOrganization", []):
            relationships.append({
                "target": org,
                "type": "directorship_org",
                "description": "取締役先組織",
            })

        # 家族・関係者
        for relative in properties.get("relative", []):
            relationships.append({
                "target": relative,
                "type": "family",
                "description": "親族",
            })
        for associate in properties.get("associate", []):
            relationships.append({
                "target": associate,
                "type": "associate",
                "description": "関係者",
            })

        # 制裁対象
        for sanction in properties.get("sanctions", []):
            relationships.append({
                "target": sanction,
                "type": "sanction",
                "description": "制裁",
            })

        return relationships

    # ------------------------------------------------------------------
    # 公開 API メソッド
    # ------------------------------------------------------------------
    async def get_related_entities(
        self,
        entity_name: str,
        max_hops: int = 2,
    ) -> list[RelatedEntity]:
        """関連エンティティを取得する（N-hopグラフ探索）。

        指定エンティティから最大max_hopの範囲内で接続されている
        エンティティを探索する。制裁対象・PEP・犯罪関連の
        エンティティを特定する。

        Args:
            entity_name: 検索するエンティティ名
            max_hops: 最大探索ホップ数（デフォルト2）

        Returns:
            RelatedEntity のリスト。取得失敗時は空リスト。
        """
        self._visited_entities.clear()
        results: list[RelatedEntity] = []

        try:
            # 初回検索
            entities = await self._search_entity(entity_name, limit=5)
            if not entities:
                logger.info(
                    "OpenSanctions: エンティティ未検出: %s", entity_name,
                )
                return []

            # 各検索結果について関連を探索
            for entity in entities:
                info = self._extract_entity_info(entity)
                entity_id = info["id"]

                if entity_id in self._visited_entities:
                    continue
                self._visited_entities.add(entity_id)

                # 直接の検索結果を追加（自身も関連として記録）
                results.append(RelatedEntity(
                    name=info["name"],
                    entity_type=info["entity_type"],
                    schema_type=info["schema_type"],
                    relationship="direct_match",
                    country=info["country"],
                    datasets=info["datasets"],
                ))

                # 関連エンティティを探索（再帰的にhopを辿る）
                if max_hops > 0:
                    related = await self._explore_relationships(
                        entity, current_hop=1, max_hops=max_hops,
                    )
                    results.extend(related)

            logger.info(
                "OpenSanctions: 関連エンティティ %d件検出 (%s, max_hops=%d)",
                len(results), entity_name, max_hops,
            )
            return results

        except Exception as exc:
            logger.error(
                "OpenSanctions 関連エンティティ探索エラー: %s (%s)",
                exc, entity_name,
            )
            return []

    async def _explore_relationships(
        self,
        entity: dict,
        current_hop: int,
        max_hops: int,
    ) -> list[RelatedEntity]:
        """エンティティの関連を再帰的に探索する。

        Args:
            entity: 起点エンティティ辞書
            current_hop: 現在のホップ数
            max_hops: 最大ホップ数

        Returns:
            RelatedEntity のリスト
        """
        results: list[RelatedEntity] = []

        if current_hop > max_hops:
            return results

        relationships = self._extract_relationships(entity)

        for rel in relationships:
            target = rel["target"]
            target_name = ""

            # target が辞書（エンティティ参照）の場合
            if isinstance(target, dict):
                target_name = target.get("caption", target.get("name", ""))
                target_id = target.get("id", "")
            elif isinstance(target, str):
                target_name = target
                target_id = target
            else:
                continue

            if not target_name or target_id in self._visited_entities:
                continue
            self._visited_entities.add(target_id)

            # 関連エンティティの詳細情報を検索
            search_results = await self._search_entity(target_name, limit=1)
            if search_results:
                info = self._extract_entity_info(search_results[0])
                results.append(RelatedEntity(
                    name=info["name"],
                    entity_type=info["entity_type"],
                    schema_type=info["schema_type"],
                    relationship=rel["description"],
                    country=info["country"],
                    datasets=info["datasets"],
                ))

                # さらに深いホップへ
                if current_hop < max_hops:
                    deeper = await self._explore_relationships(
                        search_results[0],
                        current_hop=current_hop + 1,
                        max_hops=max_hops,
                    )
                    results.extend(deeper)
            else:
                # 検索結果なしでも名前は記録
                results.append(RelatedEntity(
                    name=target_name,
                    entity_type="Unknown",
                    schema_type="Unknown",
                    relationship=rel["description"],
                    country="",
                    datasets=[],
                ))

        return results

    async def get_ownership_structure(
        self,
        company_name: str,
    ) -> dict:
        """企業の所有構造（株主ツリー）を取得する。

        OpenSanctionsの所有関係データから株主構造を構築する。

        Args:
            company_name: 企業名

        Returns:
            所有構造情報の辞書:
            - company: 企業名
            - owners: 所有者リスト（OwnershipNode）
            - subsidiaries: 子会社リスト
            - risk_flags: 検出されたリスクフラグ
        """
        result = {
            "company": company_name,
            "owners": [],
            "subsidiaries": [],
            "risk_flags": [],
            "data_source": "opensanctions",
        }

        try:
            entities = await self._search_entity(company_name, limit=3)
            if not entities:
                logger.info(
                    "OpenSanctions: 所有構造データなし: %s", company_name,
                )
                return result

            for entity in entities:
                info = self._extract_entity_info(entity)
                properties = entity.get("properties", {})

                # 所有者の取得
                owners = properties.get("ownershipOwner", [])
                for owner in owners:
                    owner_name = ""
                    if isinstance(owner, dict):
                        owner_name = owner.get("caption", owner.get("name", ""))
                    elif isinstance(owner, str):
                        owner_name = owner

                    if owner_name:
                        # 所有割合の取得（利用可能な場合）
                        share_pct = 0.0
                        shares = properties.get("sharesValue", [])
                        if shares:
                            try:
                                share_pct = float(str(shares[0]).replace("%", ""))
                            except (ValueError, TypeError):
                                share_pct = 0.0

                        node = OwnershipNode(
                            name=owner_name,
                            entity_type="Owner",
                            ownership_pct=share_pct,
                            children=[],
                        )
                        result["owners"].append({
                            "name": node.name,
                            "entity_type": node.entity_type,
                            "ownership_pct": node.ownership_pct,
                        })

                # 子会社の取得
                assets = properties.get("ownershipAsset", [])
                for asset in assets:
                    asset_name = ""
                    if isinstance(asset, dict):
                        asset_name = asset.get("caption", asset.get("name", ""))
                    elif isinstance(asset, str):
                        asset_name = asset

                    if asset_name:
                        result["subsidiaries"].append({
                            "name": asset_name,
                            "entity_type": "Subsidiary",
                        })

                # リスクフラグの判定
                topics = entity.get("topics", [])
                if any("sanction" in t for t in topics):
                    result["risk_flags"].append("SANCTIONED_ENTITY")
                if any("pep" in t for t in topics):
                    result["risk_flags"].append("PEP_CONNECTED")
                if any("crime" in t for t in topics):
                    result["risk_flags"].append("CRIME_LINKED")

            logger.info(
                "OpenSanctions: 所有構造取得完了 (%s, owners=%d, subs=%d)",
                company_name, len(result["owners"]),
                len(result["subsidiaries"]),
            )
            return result

        except Exception as exc:
            logger.error(
                "OpenSanctions 所有構造取得エラー: %s (%s)", exc, company_name,
            )
            return result

    async def check_sanctions_network(
        self,
        entity_name: str,
    ) -> dict:
        """制裁ネットワークチェックを実行する。

        指定エンティティから2ホップ以内に制裁対象が存在するかを
        チェックし、リスク評価結果を返す。

        Args:
            entity_name: チェック対象のエンティティ名

        Returns:
            制裁ネットワークチェック結果の辞書:
            - entity: 対象エンティティ名
            - is_sanctioned: 直接制裁対象か
            - sanctioned_connections: 制裁関連のある接続先
            - risk_level: リスクレベル ("CLEAR", "LOW", "MEDIUM", "HIGH", "CRITICAL")
            - risk_score: リスクスコア (0-100)
            - evidence: 根拠のリスト
        """
        result = {
            "entity": entity_name,
            "is_sanctioned": False,
            "sanctioned_connections": [],
            "risk_level": "CLEAR",
            "risk_score": 0,
            "evidence": [],
            "data_source": "opensanctions",
        }

        try:
            related = await self.get_related_entities(entity_name, max_hops=2)

            if not related:
                result["evidence"].append(
                    f"[OpenSanctions] {entity_name}: データベースに該当なし"
                )
                return result

            sanctioned_entities: list[dict] = []
            pep_connections: list[dict] = []

            for entity in related:
                is_sanctioned = entity.schema_type == "Sanction"
                is_pep = entity.schema_type == "PEP"
                is_crime = entity.schema_type == "Crime"

                if is_sanctioned:
                    sanctioned_entities.append({
                        "name": entity.name,
                        "relationship": entity.relationship,
                        "country": entity.country,
                        "datasets": entity.datasets,
                    })
                if is_pep:
                    pep_connections.append({
                        "name": entity.name,
                        "relationship": entity.relationship,
                        "country": entity.country,
                    })

                # 直接マッチが制裁対象の場合
                if entity.relationship == "direct_match" and is_sanctioned:
                    result["is_sanctioned"] = True
                    result["evidence"].append(
                        f"[OpenSanctions/直接] {entity.name}: "
                        f"制裁対象 (datasets: {', '.join(entity.datasets[:3])})"
                    )

            result["sanctioned_connections"] = sanctioned_entities

            # リスクスコアの算出
            risk_score = 0
            if result["is_sanctioned"]:
                risk_score = 100
                result["risk_level"] = "CRITICAL"
                result["evidence"].append(
                    f"[OpenSanctions] {entity_name}: 直接制裁対象"
                )
            elif sanctioned_entities:
                # 制裁関連の接続がある場合
                risk_score = min(80, 40 + len(sanctioned_entities) * 15)
                result["risk_level"] = "HIGH" if risk_score >= 60 else "MEDIUM"
                for se in sanctioned_entities[:5]:
                    result["evidence"].append(
                        f"[OpenSanctions] 制裁接続: {se['name']} "
                        f"(関係: {se['relationship']}, 国: {se['country']})"
                    )
            elif pep_connections:
                risk_score = min(40, 15 + len(pep_connections) * 10)
                result["risk_level"] = "LOW"
                for pep in pep_connections[:3]:
                    result["evidence"].append(
                        f"[OpenSanctions] PEP接続: {pep['name']} "
                        f"(関係: {pep['relationship']})"
                    )

            result["risk_score"] = risk_score

            logger.info(
                "OpenSanctions: ネットワークチェック完了 (%s, "
                "risk=%s, score=%d, sanctions=%d)",
                entity_name, result["risk_level"],
                risk_score, len(sanctioned_entities),
            )
            return result

        except Exception as exc:
            logger.error(
                "OpenSanctions ネットワークチェックエラー: %s (%s)",
                exc, entity_name,
            )
            result["evidence"].append(
                f"[OpenSanctions] チェックエラー: {exc}"
            )
            return result


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
    async def get_ultimate_beneficial_owner(
        self,
        company_name: str,
    ) -> dict:
        """最終実質的支配者（UBO）を特定する。

        所有構造を再帰的に辿り、最終的な実質的支配者を特定する。
        各所有チェーンの末端（自然人または25%以上保有する法人）を
        UBO候補として抽出する。

        Args:
            company_name: 企業名

        Returns:
            UBO情報の辞書:
            - company: 対象企業名
            - ubos: UBO候補リスト
            - ownership_chain: 所有チェーン
            - risk_flags: リスクフラグ
        """
        result = {
            "company": company_name,
            "ubos": [],
            "ownership_chain": [],
            "risk_flags": [],
            "data_source": "opensanctions",
        }

        try:
            ownership = await self.get_ownership_structure(company_name)

            # 所有者の中から自然人・UBO候補を抽出
            owners = ownership.get("owners", [])
            for owner in owners:
                owner_name = owner.get("name", "")
                if not owner_name:
                    continue

                # 所有者の詳細を検索
                owner_entities = await self._search_entity(owner_name, limit=2)
                for ent in owner_entities:
                    info = self._extract_entity_info(ent)
                    schema = info.get("schema", "")

                    # 自然人 = UBO候補
                    is_person = schema in ("Person", "Family", "Associate")
                    # 25%以上保有 = 有意な支配力
                    pct = owner.get("ownership_pct", 0.0)

                    if is_person or pct >= 25.0:
                        ubo_entry = {
                            "name": info["name"],
                            "entity_type": info["entity_type"],
                            "country": info["country"],
                            "ownership_pct": pct,
                            "is_person": is_person,
                            "topics": info.get("topics", []),
                        }
                        result["ubos"].append(ubo_entry)

                        # リスク判定
                        topics = info.get("topics", [])
                        if any("sanction" in t for t in topics):
                            result["risk_flags"].append(
                                f"UBO_SANCTIONED: {info['name']}"
                            )
                        if any("pep" in t for t in topics):
                            result["risk_flags"].append(
                                f"UBO_IS_PEP: {info['name']}"
                            )

                    # 法人所有者→さらに所有チェーンを辿る
                    if not is_person and owner_name:
                        result["ownership_chain"].append({
                            "entity": owner_name,
                            "entity_type": info["entity_type"],
                            "country": info["country"],
                        })

            # 既存リスクフラグの統合
            result["risk_flags"].extend(ownership.get("risk_flags", []))

            logger.info(
                "OpenSanctions: UBO特定完了 (%s, UBO候補=%d件)",
                company_name, len(result["ubos"]),
            )
            return result

        except Exception as exc:
            logger.error(
                "OpenSanctions UBO特定エラー: %s (%s)", exc, company_name,
            )
            return result

    async def batch_check_entities(
        self,
        entity_names: list,
    ) -> list[dict]:
        """複数エンティティの制裁チェックを一括実行する。

        サプライチェーン上の全取引先を一括でチェックする場合に使用。
        レート制限を遵守しながら順次処理する。

        Args:
            entity_names: エンティティ名のリスト

        Returns:
            制裁チェック結果の辞書リスト（入力順序に対応）
        """
        results: list[dict] = []

        for name in entity_names:
            try:
                check = await self.check_sanctions_network(name)
                results.append(check)
            except Exception as exc:
                logger.error(
                    "OpenSanctions バッチチェックエラー: %s (%s)", exc, name,
                )
                results.append({
                    "entity": name,
                    "is_sanctioned": False,
                    "sanctioned_connections": [],
                    "risk_level": "UNKNOWN",
                    "risk_score": 0,
                    "evidence": [f"[OpenSanctions] チェックエラー: {exc}"],
                    "data_source": "opensanctions",
                })

        # バッチサマリー
        flagged = [r for r in results if r.get("risk_score", 0) > 0]
        logger.info(
            "OpenSanctions: バッチチェック完了 (%d/%d件にリスク検出)",
            len(flagged), len(results),
        )
        return results

    async def get_risk_propagation_score(
        self,
        entity_name: str,
    ) -> dict:
        """エンティティのリスク伝播スコアを算出する。

        関連エンティティのリスクが対象エンティティにどの程度
        伝播するかを、距離（ホップ数）と関係種別で重み付けして算出。

        リスク伝播モデル:
          - 直接制裁対象: 100
          - 1ホップ先の制裁接続: 50 (所有関係), 30 (取締役), 20 (親族)
          - 2ホップ先: 上記の30%

        Args:
            entity_name: エンティティ名

        Returns:
            リスク伝播スコア辞書
        """
        # 関係種別の重み（1ホップ時）
        RELATION_WEIGHTS = {
            "ownership_owner": 0.50,
            "ownership_asset": 0.50,
            "directorship": 0.30,
            "directorship_org": 0.30,
            "family": 0.20,
            "associate": 0.15,
            "sanction": 1.00,
            "direct_match": 1.00,
        }

        result = {
            "entity": entity_name,
            "propagated_risk_score": 0,
            "risk_level": "CLEAR",
            "risk_paths": [],
            "data_source": "opensanctions",
        }

        try:
            related = await self.get_related_entities(entity_name, max_hops=2)
            if not related:
                return result

            total_risk = 0.0
            paths: list[dict] = []

            for ent in related:
                base_risk = 0.0
                if ent.schema_type == "Sanction":
                    base_risk = 100.0
                elif ent.schema_type == "Crime":
                    base_risk = 60.0
                elif ent.schema_type == "PEP":
                    base_risk = 20.0

                if base_risk <= 0:
                    continue

                # ホップ距離による減衰
                # direct_match = 0ホップ, それ以外は関係辿り = 1-2ホップ
                if ent.relationship == "direct_match":
                    hop_decay = 1.0
                else:
                    hop_decay = 0.5  # 簡略化: 1ホップ先として計算

                # 関係種別の重み
                rel_type = ent.relationship
                weight = RELATION_WEIGHTS.get(rel_type, 0.10)

                propagated = base_risk * hop_decay * weight
                total_risk += propagated

                if propagated > 5:
                    paths.append({
                        "name": ent.name,
                        "relationship": rel_type,
                        "base_risk": base_risk,
                        "propagated_risk": round(propagated, 1),
                    })

            score = min(100, int(total_risk))
            result["propagated_risk_score"] = score
            result["risk_paths"] = sorted(
                paths, key=lambda x: x["propagated_risk"], reverse=True,
            )[:10]

            if score >= 80:
                result["risk_level"] = "CRITICAL"
            elif score >= 60:
                result["risk_level"] = "HIGH"
            elif score >= 40:
                result["risk_level"] = "MEDIUM"
            elif score >= 20:
                result["risk_level"] = "LOW"
            else:
                result["risk_level"] = "CLEAR"

            logger.info(
                "OpenSanctions: リスク伝播スコア算出完了 (%s, score=%d)",
                entity_name, score,
            )
            return result

        except Exception as exc:
            logger.error(
                "OpenSanctions リスク伝播スコアエラー: %s (%s)",
                exc, entity_name,
            )
            return result


# ---------------------------------------------------------------------------
# スタンドアロン便利関数
# ---------------------------------------------------------------------------
async def check_entity_sanctions(entity_name: str) -> dict:
    """エンティティの制裁ネットワークチェックのショートカット関数。"""
    graph = OpenSanctionsGraph()
    return await graph.check_sanctions_network(entity_name)


async def batch_sanctions_check(entity_names: list) -> list[dict]:
    """複数エンティティの一括制裁チェックのショートカット関数。"""
    graph = OpenSanctionsGraph()
    return await graph.batch_check_entities(entity_names)


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
        print("OpenSanctions グラフ探索クライアント -- 動作確認")
        print("=" * 60)

        graph = OpenSanctionsGraph()

        test_entity = "Rosneft"
        print(f"\n--- 関連エンティティ検索: {test_entity} ---")
        related = await graph.get_related_entities(test_entity, max_hops=1)
        print(f"  検出: {len(related)}件")
        for ent in related[:10]:
            print(
                f"  {ent.name} [{ent.entity_type}/{ent.schema_type}] "
                f"関係: {ent.relationship}, 国: {ent.country}"
            )

        print(f"\n--- 所有構造: {test_entity} ---")
        ownership = await graph.get_ownership_structure(test_entity)
        print(f"  所有者: {len(ownership['owners'])}件")
        print(f"  子会社: {len(ownership['subsidiaries'])}件")
        print(f"  リスクフラグ: {ownership['risk_flags']}")

        print(f"\n--- 制裁ネットワークチェック: {test_entity} ---")
        network = await graph.check_sanctions_network(test_entity)
        print(f"  直接制裁: {network['is_sanctioned']}")
        print(f"  リスクレベル: {network['risk_level']}")
        print(f"  リスクスコア: {network['risk_score']}")
        for ev in network["evidence"]:
            print(f"  {ev}")

    asyncio.run(_demo())
