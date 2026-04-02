"""GraphQL Schema for Supply Chain Risk Intelligence
strawberry-graphql ベースの GraphQL エンドポイント。
24次元リスクスコア、制裁スクリーニング、リスクダッシュボードを提供。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional

import strawberry
from strawberry.fastapi import GraphQLRouter

from config.constants import PRIORITY_COUNTRIES, RISK_THRESHOLDS


@strawberry.type
class CompanyType:
    """企業リスクスコア"""
    name: str
    country: str
    risk_score: int
    risk_level: str


@strawberry.type
class SanctionsResultType:
    """制裁スクリーニング結果"""
    company_name: str
    matched: bool
    match_score: float
    source: str
    matched_entity: str
    screened_at: str


@strawberry.type
class PersonType:
    """人物チェック結果"""
    name: str
    is_pep: bool
    sanctions_hit: bool


@strawberry.type
class SupplyChainPathType:
    """サプライチェーンパス"""
    path: list[str]
    total_risk: float
    hops: int


@strawberry.type
class DimensionScoreType:
    """個別次元スコア"""
    dimension: str
    score: int
    weight: float


@strawberry.type
class RiskDetailType:
    """詳細リスクスコア"""
    name: str
    country: str
    risk_score: int
    risk_level: str
    dimensions: list[DimensionScoreType]
    evidence_count: int


@strawberry.type
class Query:
    @strawberry.field(description="国名を指定してリスクスコアを取得")
    def company(self, name: str) -> CompanyType:
        """Get risk score for a company by country name."""
        from scoring.engine import calculate_risk_score

        score = calculate_risk_score(
            f"gql_{name}", f"GraphQL: {name}",
            country=name, location=name,
        )
        d = score.to_dict()
        return CompanyType(
            name=name,
            country=name,
            risk_score=d["overall_score"],
            risk_level=d["risk_level"],
        )

    @strawberry.field(description="企業/個人の制裁リストスクリーニング")
    def search_sanctions(
        self,
        entity_name: str,
        country: str = "",
    ) -> SanctionsResultType:
        """Screen entity against sanctions lists."""
        from pipeline.sanctions.screener import screen_entity
        from datetime import datetime

        result = screen_entity(entity_name, country if country else None)
        return SanctionsResultType(
            company_name=entity_name,
            matched=result.matched,
            match_score=result.match_score,
            source=result.source or "",
            matched_entity=result.matched_entity or "",
            screened_at=datetime.utcnow().isoformat(),
        )

    @strawberry.field(description="優先監視対象国のリスクダッシュボード")
    def risk_dashboard(self, limit: int = 10) -> list[CompanyType]:
        """Get risk scores for priority countries."""
        from scoring.engine import calculate_risk_score

        results = []
        countries = PRIORITY_COUNTRIES[:limit]
        for country in countries:
            try:
                score = calculate_risk_score(
                    f"dash_{country}", f"Dashboard: {country}",
                    country=country, location=country,
                )
                d = score.to_dict()
                results.append(CompanyType(
                    name=country,
                    country=country,
                    risk_score=d["overall_score"],
                    risk_level=d["risk_level"],
                ))
            except Exception:
                results.append(CompanyType(
                    name=country,
                    country=country,
                    risk_score=0,
                    risk_level="UNKNOWN",
                ))
        results.sort(key=lambda c: -c.risk_score)
        return results

    @strawberry.field(description="国の詳細リスク評価（全24次元）")
    def risk_detail(self, country: str) -> RiskDetailType:
        """Get detailed risk breakdown for a country."""
        from scoring.engine import calculate_risk_score, SupplierRiskScore

        score = calculate_risk_score(
            f"detail_{country}", f"Detail: {country}",
            country=country, location=country,
        )
        d = score.to_dict()

        dimensions = []
        for dim, val in d.get("scores", {}).items():
            weight = SupplierRiskScore.WEIGHTS.get(dim, 0.0)
            dimensions.append(DimensionScoreType(
                dimension=dim,
                score=val if isinstance(val, int) else int(val),
                weight=weight,
            ))
        dimensions.sort(key=lambda x: -x.score)

        return RiskDetailType(
            name=country,
            country=country,
            risk_score=d["overall_score"],
            risk_level=d["risk_level"],
            dimensions=dimensions,
            evidence_count=len(d.get("evidence", [])),
        )

    @strawberry.field(description="PEP/制裁チェック（人物）")
    def person_check(self, name: str) -> PersonType:
        """Check person against sanctions/PEP lists."""
        from pipeline.sanctions.screener import screen_entity

        result = screen_entity(name, None)
        return PersonType(
            name=name,
            is_pep=False,  # PEP list not yet integrated
            sanctions_hit=result.matched,
        )

    @strawberry.field(description="2拠点間の最短経路リスク検索")
    def search_path(
        self,
        origin: str,
        destination: str,
        max_hops: int = 5,
    ) -> SupplyChainPathType:
        """Search supply chain path risk between two locations."""
        from features.route_risk.analyzer import RouteRiskAnalyzer

        analyzer = RouteRiskAnalyzer()
        result = analyzer.analyze_route(origin, destination)

        if "error" in result:
            return SupplyChainPathType(
                path=[origin, destination],
                total_risk=0.0,
                hops=0,
            )

        # チョークポイント経由の経路を構築
        path_nodes = [origin]
        for cp in result.get("chokepoints_passed", []):
            path_nodes.append(cp.get("name", ""))
        path_nodes.append(destination)

        return SupplyChainPathType(
            path=path_nodes,
            total_risk=float(result.get("route_risk", 0)),
            hops=len(path_nodes) - 1,
        )


schema = strawberry.Schema(query=Query)
graphql_router = GraphQLRouter(schema)
