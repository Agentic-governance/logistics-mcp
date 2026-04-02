"""制裁リストスクリーニング（ファジーマッチング）"""
import json
import re
from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from pipeline.db import SanctionedEntity, ScreeningLog, engine
from dataclasses import dataclass
from typing import Optional


MATCH_THRESHOLD = 85  # 85%以上でマッチとみなす


def normalize_name(name: str) -> str:
    """エンティティ名を正規化（比較用）。
    小文字化、句読点除去、法的接尾辞の統一、空白正規化。
    """
    s = name.lower().strip()
    # 句読点・特殊文字を除去
    s = re.sub(r"[.,;:'\"\-/\\()&!?]", " ", s)
    # 法的接尾辞の正規化
    s = re.sub(r"\b(co|corp|corporation|inc|incorporated|llc|ltd|limited|gmbh|ag|sa|srl|plc)\b\.?", "", s)
    # 空白正規化
    s = re.sub(r"\s+", " ", s).strip()
    return s


@dataclass
class ScreeningResult:
    query_name: str
    matched: bool
    match_score: float
    matched_entity: Optional[dict]
    source: Optional[str]
    evidence: list[str]


def screen_entity(company_name: str, country: str = None) -> ScreeningResult:
    """
    企業名で制裁リストをスクリーニング。
    ファジーマッチング + エイリアス検索。
    """
    with Session(engine) as session:
        # 全アクティブエンティティを取得（本番はインデックス最適化）
        entities = session.query(SanctionedEntity).filter_by(is_active=True).all()

        best_match = None
        best_score = 0

        for entity in entities:
            # プライマリ名でマッチ
            score = fuzz.token_sort_ratio(company_name.lower(), entity.name_primary.lower())

            # エイリアスでもチェック
            aliases = json.loads(entity.names_aliases or "[]")
            for alias in aliases:
                alias_score = fuzz.token_sort_ratio(company_name.lower(), alias.lower())
                score = max(score, alias_score)

            # 国フィルタ（指定時）
            if country and entity.country and country.lower() not in entity.country.lower():
                score *= 0.8  # 国不一致でスコア減衰

            if score > best_score:
                best_score = score
                best_match = entity

        matched = best_score >= MATCH_THRESHOLD
        evidence = []

        if matched and best_match:
            programs = json.loads(best_match.programs or "[]")
            evidence = [
                f"制裁リスト一致: {best_match.source.upper()}",
                f"マッチ対象: {best_match.name_primary} (類似度: {best_score:.1f}%)",
                f"制裁プログラム: {', '.join(programs)}",
                f"国/地域: {best_match.country or '不明'}",
            ]
            if best_match.reason:
                evidence.append(f"制裁理由: {best_match.reason}")

        # ログ記録
        log = ScreeningLog(
            query_name=company_name,
            query_country=country,
            matched=matched,
            match_score=best_score,
            matched_entity_id=best_match.id if best_match else None,
            matched_source=best_match.source if best_match else None,
        )
        session.add(log)
        session.commit()

        return ScreeningResult(
            query_name=company_name,
            matched=matched,
            match_score=best_score,
            matched_entity={"name": best_match.name_primary, "source": best_match.source, "country": best_match.country} if matched and best_match else None,
            source=best_match.source if matched and best_match else None,
            evidence=evidence,
        )
