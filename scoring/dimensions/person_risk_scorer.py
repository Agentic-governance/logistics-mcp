"""人レイヤー リスクスコアラー
個人（UBO・役員・取締役）のリスクを多面的に評価する。

スコアリングロジック:
  - 制裁ヒット: 即100点
  - PEP（政治的露出者）: +30点
  - オフショアリーク関連: +25点
  - 高リスク国籍: country_risk_score * 0.3
  - 兼任役員の平均リスク: +network_risk * 0.2
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 高リスク国籍スコア（0-100、高い = リスクが高い）
# ---------------------------------------------------------------------------
NATIONALITY_RISK_SCORES: dict[str, int] = {
    # 最高リスク (90+)
    "north korea": 100, "dprk": 100,
    "iran": 95,
    "syria": 90,
    "myanmar": 85,
    "cuba": 85,
    # 高リスク (70-89)
    "russia": 80,
    "venezuela": 78,
    "belarus": 75,
    "libya": 75,
    "somalia": 75,
    "yemen": 73,
    "south sudan": 73,
    "sudan": 72,
    "eritrea": 70,
    "afghanistan": 70,
    "iraq": 68,
    "nicaragua": 65,
    # 中リスク (40-69)
    "pakistan": 55,
    "lebanon": 55,
    "cambodia": 50,
    "laos": 48,
    "nigeria": 55,
    "democratic republic of congo": 55,
    "haiti": 50,
    "mali": 50,
    "panama": 45,
    "bahamas": 42,
    "british virgin islands": 45,
    "cayman islands": 40,
    "seychelles": 42,
    "marshall islands": 40,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class PersonRiskResult:
    """個人リスク評価結果"""
    person_name: str
    total_score: int
    sanctions_score: int = 0
    pep_score: int = 0
    offshore_leak_score: int = 0
    nationality_score: int = 0
    network_score: int = 0
    evidence: list[str] = field(default_factory=list)
    risk_level: str = "LOW"


@dataclass
class OwnershipChainRiskResult:
    """UBOチェーン全体のリスク評価結果"""
    company_name: str
    total_score: int
    max_individual_score: int
    sanctioned_owners: list[str] = field(default_factory=list)
    pep_owners: list[str] = field(default_factory=list)
    offshore_leak_owners: list[str] = field(default_factory=list)
    high_risk_nationality_owners: list[str] = field(default_factory=list)
    individual_scores: list[dict] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    risk_level: str = "LOW"


# ---------------------------------------------------------------------------
# PersonRiskScorer
# ---------------------------------------------------------------------------
class PersonRiskScorer:
    """個人リスクスコアラー — UBO・役員・取締役のリスクを評価"""

    def __init__(self):
        self._sanctions_screener = None
        self._icij_client = None
        self._init_dependencies()

    def _init_dependencies(self):
        """外部依存の遅延初期化。利用不可時はNoneのまま。"""
        try:
            from pipeline.sanctions.screener import screen_entity
            self._sanctions_screener = screen_entity
        except ImportError:
            logger.info("制裁スクリーナーが利用不可。制裁チェックはスキップされます。")

        try:
            from pipeline.corporate.icij_client import ICIJClient
            self._icij_client = ICIJClient()
        except ImportError:
            logger.info("ICIJクライアントが利用不可。オフショアリークチェックはスキップされます。")

    def _check_sanctions(self, person_name: str) -> tuple[bool, list[str]]:
        """制裁リスト照合。ヒットした場合 (True, evidence) を返す。"""
        if not self._sanctions_screener:
            return False, []
        try:
            result = self._sanctions_screener(person_name)
            if result.matched:
                evidence = [
                    f"[制裁] {person_name} が制裁リストにヒット "
                    f"(スコア: {result.match_score}, ソース: {result.source})"
                ]
                return True, evidence
            return False, []
        except Exception as e:
            logger.warning("制裁チェックエラー (%s): %s", person_name, e)
            return False, []

    def _check_pep(self, person_name: str) -> tuple[bool, list[str]]:
        """PEP（政治的露出者）判定。"""
        if not self._sanctions_screener:
            return False, []
        try:
            result = self._sanctions_screener(person_name)
            if result.matched and result.evidence:
                for ev in result.evidence:
                    ev_lower = str(ev).lower()
                    if any(kw in ev_lower for kw in ("pep", "politically exposed", "政治")):
                        return True, [f"[PEP] {person_name} は政治的露出者（PEP）の可能性あり"]
            return False, []
        except Exception as e:
            logger.warning("PEPチェックエラー (%s): %s", person_name, e)
            return False, []

    def _check_offshore_leaks(self, person_name: str) -> tuple[bool, int, list[str]]:
        """オフショアリーク（パナマ文書等）照合。(ヒット有無, 件数, evidence) を返す。"""
        if not self._icij_client:
            return False, 0, []
        try:
            records = self._icij_client.search_entity_sync(person_name)
            if records:
                sources = set(r.data_source for r in records)
                evidence = [
                    f"[オフショアリーク] {person_name} が {len(records)} 件のリーク情報にヒット "
                    f"(ソース: {', '.join(sources)})"
                ]
                return True, len(records), evidence
            return False, 0, []
        except Exception as e:
            logger.warning("オフショアリークチェックエラー (%s): %s", person_name, e)
            return False, 0, []

    def _get_nationality_score(self, nationality: str) -> tuple[int, list[str]]:
        """国籍リスクスコアを算出する。"""
        if not nationality:
            return 0, []
        nat_lower = nationality.lower().strip()
        for country, score in NATIONALITY_RISK_SCORES.items():
            if country in nat_lower or nat_lower in country:
                evidence = [f"[国籍リスク] {nationality} のリスクスコア: {score}/100"]
                return score, evidence
        return 0, []

    def score_person(
        self,
        person_name: str,
        nationality: str = "",
        company_associations: Optional[list] = None,
        graph: Optional[object] = None,
    ) -> dict:
        """個人のリスクスコアを算出する。

        スコアリングロジック:
          - 制裁ヒット: 即100点
          - PEP（政治的露出者）: +30点
          - オフショアリーク関連: +25点
          - 高リスク国籍: country_risk_score * 0.3
          - 兼任役員の平均リスク: +network_risk * 0.2

        Args:
            person_name: 人物名
            nationality: 国籍
            company_associations: 関連企業リスト（グラフ未使用時のフォールバック）
            graph: PersonCompanyGraph インスタンス（ネットワークリスク精密計算用）

        Returns:
            PersonRiskResult の辞書表現
        """
        if company_associations is None:
            company_associations = []

        evidence: list[str] = []
        sanctions_score = 0
        pep_score = 0
        offshore_score = 0
        nationality_score = 0
        network_score = 0

        # --- 1. 制裁チェック (即100点) ---
        is_sanctioned, sanc_evidence = self._check_sanctions(person_name)
        if is_sanctioned:
            sanctions_score = 100
            evidence.extend(sanc_evidence)
            # 制裁ヒットは即時 100 点返却
            result = PersonRiskResult(
                person_name=person_name,
                total_score=100,
                sanctions_score=100,
                evidence=evidence,
                risk_level="CRITICAL",
            )
            return self._result_to_dict(result)

        # --- 2. PEPチェック (+30点) ---
        is_pep, pep_evidence = self._check_pep(person_name)
        if is_pep:
            pep_score = 30
            evidence.extend(pep_evidence)

        # --- 3. オフショアリークチェック (+25点) ---
        has_leak, leak_count, leak_evidence = self._check_offshore_leaks(person_name)
        if has_leak:
            offshore_score = min(25 + (leak_count - 1) * 5, 40)  # 複数ヒットで加算
            evidence.extend(leak_evidence)

        # --- 4. 国籍リスク (country_risk_score * 0.3) ---
        nat_raw, nat_evidence = self._get_nationality_score(nationality)
        nationality_score = int(nat_raw * 0.3)
        evidence.extend(nat_evidence)

        # --- 5. ネットワークリスク (network_risk * 0.2) ---
        # グラフがある場合: 兼任役員の平均リスクスコアを使用
        if graph is not None and hasattr(graph, "get_connected_person_risks"):
            try:
                net_info = graph.get_connected_person_risks(person_name, max_hops=2)
                avg_risk = net_info.get("avg_risk_score", 0.0)
                sanctioned_nearby = net_info.get("sanctioned_count", 0)
                pep_nearby = net_info.get("pep_count", 0)
                connected = net_info.get("connected_persons", [])

                # ネットワークリスク = 接続人物の平均リスク * 0.2
                network_score = int(avg_risk * 0.2)
                # 制裁対象者が近傍にいる場合は追加加算
                if sanctioned_nearby > 0:
                    network_score = min(network_score + 15 * sanctioned_nearby, 30)
                # PEPが近傍にいる場合は追加加算
                if pep_nearby > 0:
                    network_score = min(network_score + 5 * pep_nearby, 30)

                network_score = min(network_score, 30)  # 上限30

                if network_score > 0:
                    evidence.append(
                        f"[ネットワーク] {person_name} の近傍に {len(connected)} 名が接続 "
                        f"(平均リスク: {avg_risk:.1f}, 制裁: {sanctioned_nearby}名, "
                        f"PEP: {pep_nearby}名, ネットワークスコア: {network_score})"
                    )
            except Exception as e:
                logger.warning("ネットワークリスク計算エラー (%s): %s", person_name, e)
                network_score = 0
        elif company_associations:
            # フォールバック: 関連企業数ベースの簡易計算
            network_risk = min(len(company_associations) * 5, 20)
            network_score = int(network_risk * 0.2)
            if network_score > 0:
                evidence.append(
                    f"[ネットワーク] {person_name} は {len(company_associations)} 社と関連 "
                    f"(ネットワークリスク: {network_score})"
                )

        # --- 合計スコア ---
        total = min(100, sanctions_score + pep_score + offshore_score + nationality_score + network_score)

        # リスクレベル判定
        if total >= 80:
            risk_level = "CRITICAL"
        elif total >= 60:
            risk_level = "HIGH"
        elif total >= 40:
            risk_level = "MEDIUM"
        elif total >= 20:
            risk_level = "LOW"
        else:
            risk_level = "MINIMAL"

        result = PersonRiskResult(
            person_name=person_name,
            total_score=total,
            sanctions_score=sanctions_score,
            pep_score=pep_score,
            offshore_leak_score=offshore_score,
            nationality_score=nationality_score,
            network_score=network_score,
            evidence=evidence,
            risk_level=risk_level,
        )
        return self._result_to_dict(result)

    def score_ownership_chain(
        self,
        ubo_records: list,
        company_name: str = "",
        graph: Optional[object] = None,
    ) -> dict:
        """UBOチェーン全体のリスクスコアを算出する。

        各UBOの個人リスクを集計し、チェーン全体のリスクを評価する。

        Args:
            ubo_records: UBORecord のリスト
            company_name: 対象企業名
            graph: PersonCompanyGraph インスタンス（ネットワークリスク精密計算用）

        Returns:
            OwnershipChainRiskResult の辞書表現
        """
        if not ubo_records:
            result = OwnershipChainRiskResult(
                company_name=company_name,
                total_score=0,
                max_individual_score=0,
                evidence=["UBO情報がないため評価不可"],
                risk_level="UNKNOWN",
            )
            return self._chain_result_to_dict(result)

        individual_scores: list[dict] = []
        all_evidence: list[str] = []
        sanctioned_owners: list[str] = []
        pep_owners: list[str] = []
        offshore_owners: list[str] = []
        high_risk_nat_owners: list[str] = []
        max_score = 0

        for ubo in ubo_records:
            # UBORecord or dict 両対応
            if hasattr(ubo, "person_name"):
                name = ubo.person_name
                nationality = ubo.nationality
                is_pep = ubo.is_pep
                is_sanctioned = ubo.sanctions_hit
                ownership_pct = ubo.ownership_pct
            elif isinstance(ubo, dict):
                name = ubo.get("person_name", ubo.get("name", ""))
                nationality = ubo.get("nationality", "")
                is_pep = ubo.get("is_pep", False)
                is_sanctioned = ubo.get("sanctions_hit", False)
                ownership_pct = ubo.get("ownership_pct", 0.0)
            else:
                continue

            # 個人スコア算出（グラフがあればネットワークリスクも精密計算）
            person_result = self.score_person(name, nationality, graph=graph)
            person_score = person_result.get("total_score", 0)

            # 持株比率による重み付け
            if ownership_pct > 0:
                weight = min(ownership_pct / 100.0, 1.0)
                weighted_score = int(person_score * max(weight, 0.3))  # 最低30%重み
            else:
                weighted_score = person_score

            individual_scores.append({
                "person_name": name,
                "nationality": nationality,
                "ownership_pct": ownership_pct,
                "raw_score": person_score,
                "weighted_score": weighted_score,
                "risk_level": person_result.get("risk_level", "UNKNOWN"),
            })

            max_score = max(max_score, weighted_score)
            all_evidence.extend(person_result.get("evidence", []))

            # フラグ集計
            if is_sanctioned or person_result.get("sanctions_score", 0) > 0:
                sanctioned_owners.append(name)
            if is_pep or person_result.get("pep_score", 0) > 0:
                pep_owners.append(name)
            if person_result.get("offshore_leak_score", 0) > 0:
                offshore_owners.append(name)
            nat_score, _ = self._get_nationality_score(nationality)
            if nat_score >= 50:
                high_risk_nat_owners.append(name)

        # 全体スコア: 最大個人スコアを基準に、複数リスク要因で加算
        total_score = max_score
        if len(sanctioned_owners) > 0:
            total_score = 100  # 制裁対象が1人でもいれば即100
        elif len(pep_owners) > 1:
            total_score = min(100, total_score + 10)  # 複数PEP
        elif len(offshore_owners) > 1:
            total_score = min(100, total_score + 5)

        # リスクレベル
        if total_score >= 80:
            risk_level = "CRITICAL"
        elif total_score >= 60:
            risk_level = "HIGH"
        elif total_score >= 40:
            risk_level = "MEDIUM"
        elif total_score >= 20:
            risk_level = "LOW"
        else:
            risk_level = "MINIMAL"

        result = OwnershipChainRiskResult(
            company_name=company_name,
            total_score=total_score,
            max_individual_score=max_score,
            sanctioned_owners=sanctioned_owners,
            pep_owners=pep_owners,
            offshore_leak_owners=offshore_owners,
            high_risk_nationality_owners=high_risk_nat_owners,
            individual_scores=individual_scores,
            evidence=all_evidence,
            risk_level=risk_level,
        )
        return self._chain_result_to_dict(result)

    # ---- Helpers ----------------------------------------------------------

    @staticmethod
    def _result_to_dict(result: PersonRiskResult) -> dict:
        """PersonRiskResult を辞書に変換する。"""
        return {
            "person_name": result.person_name,
            "total_score": result.total_score,
            "sanctions_score": result.sanctions_score,
            "pep_score": result.pep_score,
            "offshore_leak_score": result.offshore_leak_score,
            "nationality_score": result.nationality_score,
            "network_score": result.network_score,
            "evidence": result.evidence,
            "risk_level": result.risk_level,
        }

    @staticmethod
    def _chain_result_to_dict(result: OwnershipChainRiskResult) -> dict:
        """OwnershipChainRiskResult を辞書に変換する。"""
        return {
            "company_name": result.company_name,
            "total_score": result.total_score,
            "max_individual_score": result.max_individual_score,
            "sanctioned_owners": result.sanctioned_owners,
            "pep_owners": result.pep_owners,
            "offshore_leak_owners": result.offshore_leak_owners,
            "high_risk_nationality_owners": result.high_risk_nationality_owners,
            "individual_scores": result.individual_scores,
            "evidence": result.evidence,
            "risk_level": result.risk_level,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Person Risk Scorer")
    parser.add_argument("name", help="人物名")
    parser.add_argument("--nationality", default="", help="国籍")
    args = parser.parse_args()

    scorer = PersonRiskScorer()
    result = scorer.score_person(args.name, args.nationality)
    print(json.dumps(result, indent=2, ensure_ascii=False))
