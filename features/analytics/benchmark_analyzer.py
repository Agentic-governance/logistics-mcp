"""ベンチマーク分析エンジン
業界平均・地域平均・競合他社との比較分析。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from scoring.engine import calculate_risk_score, SupplierRiskScore


# 業種別参照プロファイル
INDUSTRY_PROFILES: dict[str, dict] = {
    "automotive": {
        "typical_countries": ["JP", "DE", "KR", "MX", "CN", "IN"],
        "critical_dimensions": ["trade", "labor", "disaster", "maritime"],
        "risk_tolerance": "MEDIUM",
    },
    "semiconductor": {
        "typical_countries": ["TW", "KR", "JP", "NL", "US"],
        "critical_dimensions": ["trade", "political", "port_congestion"],
        "risk_tolerance": "LOW",
    },
    "pharma": {
        "typical_countries": ["IN", "CN", "DE", "US", "CH"],
        "critical_dimensions": ["compliance", "labor", "health"],
        "risk_tolerance": "LOW",
    },
    "apparel": {
        "typical_countries": ["BD", "VN", "IN", "PK", "ET"],
        "critical_dimensions": ["labor", "compliance", "political"],
        "risk_tolerance": "HIGH",
    },
    "energy": {
        "typical_countries": ["SA", "AE", "RU", "US", "NO"],
        "critical_dimensions": ["conflict", "political", "energy", "sanctions"],
        "risk_tolerance": "HIGH",
    },
    # STREAM D-5: 10 新規業界プロファイル
    "aerospace": {
        "description": "航空宇宙 (Boeing/Airbus型)",
        "typical_countries": ["US", "FR", "DE", "GB", "JP", "CA"],
        "critical_dimensions": ["compliance", "sanctions", "trade"],
        "critical_materials": ["titanium", "carbon_fiber", "avionics"],
        "regulatory": ["ITAR", "EAR"],
        "weight_overrides": {"compliance": 0.12, "sanctions": 0.10},
        "risk_tolerance": "LOW",
    },
    "food_beverage": {
        "description": "食品・飲料",
        "typical_countries": ["US", "BR", "IN", "ID", "MY", "TH"],
        "critical_dimensions": ["food_security", "health", "climate_risk"],
        "critical_materials": ["grain", "sugar", "palm_oil"],
        "regulatory": ["FSMA", "EU_Novel_Food"],
        "weight_overrides": {"food_security": 0.15, "health": 0.10},
        "risk_tolerance": "MEDIUM",
    },
    "chemical": {
        "description": "化学工業",
        "typical_countries": ["US", "DE", "CN", "JP", "KR", "SA"],
        "critical_dimensions": ["compliance", "climate_risk", "labor"],
        "critical_materials": ["ethylene", "propylene", "chlorine"],
        "regulatory": ["REACH", "RoHS", "TSCA"],
        "weight_overrides": {"compliance": 0.12, "climate_risk": 0.08},
        "risk_tolerance": "MEDIUM",
    },
    "medical_device": {
        "description": "医療機器",
        "typical_countries": ["US", "DE", "JP", "IE", "CH", "IL"],
        "critical_dimensions": ["compliance", "health", "trade"],
        "critical_materials": ["titanium", "silicone", "sensors"],
        "regulatory": ["FDA_510k", "CE_MDR", "PMDA"],
        "weight_overrides": {"compliance": 0.12, "health": 0.10},
        "risk_tolerance": "LOW",
    },
    "construction": {
        "description": "建設・建材",
        "typical_countries": ["CN", "US", "IN", "JP", "DE", "TR"],
        "critical_dimensions": ["economic", "trade", "climate_risk"],
        "critical_materials": ["steel", "cement", "copper"],
        "regulatory": ["local_building_codes"],
        "weight_overrides": {"economic": 0.10, "disaster": 0.08},
        "risk_tolerance": "HIGH",
    },
    "telecom": {
        "description": "通信・テレコム",
        "typical_countries": ["US", "CN", "KR", "JP", "FI", "SE"],
        "critical_dimensions": ["cyber_risk", "sanctions", "trade"],
        "critical_materials": ["rare_earth", "fiber_optic", "semiconductor"],
        "regulatory": ["FCC", "GDPR", "NIS2"],
        "weight_overrides": {"cyber_risk": 0.12, "sanctions": 0.08},
        "risk_tolerance": "LOW",
    },
    "defense": {
        "description": "防衛・軍需",
        "typical_countries": ["US", "GB", "FR", "DE", "IL", "KR"],
        "critical_dimensions": ["sanctions", "compliance", "conflict"],
        "critical_materials": ["rare_earth", "steel", "electronics"],
        "regulatory": ["ITAR", "EAR", "CFIUS"],
        "weight_overrides": {"sanctions": 0.15, "compliance": 0.12},
        "risk_tolerance": "LOW",
    },
    "textile": {
        "description": "繊維・アパレル",
        "typical_countries": ["CN", "BD", "VN", "IN", "TR", "PK"],
        "critical_dimensions": ["labor", "compliance", "climate_risk"],
        "critical_materials": ["cotton", "polyester", "dyes"],
        "regulatory": ["UFLPA", "EU_Due_Diligence"],
        "weight_overrides": {"labor": 0.15, "compliance": 0.10},
        "risk_tolerance": "HIGH",
    },
    "mining": {
        "description": "鉱業・資源",
        "typical_countries": ["AU", "BR", "ZA", "CL", "CD", "CN"],
        "critical_dimensions": ["climate_risk", "conflict", "labor"],
        "critical_materials": ["iron_ore", "copper", "gold", "lithium"],
        "regulatory": ["Dodd_Frank_1502", "EU_Conflict_Minerals"],
        "weight_overrides": {"climate_risk": 0.10, "conflict": 0.10},
        "risk_tolerance": "HIGH",
    },
    "logistics": {
        "description": "物流・運輸",
        "typical_countries": ["SG", "NL", "AE", "CN", "US", "DE"],
        "critical_dimensions": ["maritime", "port_congestion", "energy"],
        "critical_materials": ["fuel", "containers"],
        "regulatory": ["IMO", "SOLAS"],
        "weight_overrides": {"maritime": 0.12, "port_congestion": 0.10, "energy": 0.08},
        "risk_tolerance": "MEDIUM",
    },
}

# 地域→国マッピング
REGION_MAP: dict[str, list[str]] = {
    "east_asia": ["JP", "CN", "KR", "TW", "MN"],
    "southeast_asia": ["VN", "TH", "ID", "PH", "MY", "SG", "MM", "KH", "LA", "BN"],
    "europe": ["DE", "FR", "GB", "IT", "ES", "NL", "PL", "SE", "CH", "AT"],
    "middle_east": ["SA", "AE", "IL", "TR", "IR", "IQ", "QA", "KW", "OM", "BH"],
    "africa": ["ZA", "NG", "KE", "ET", "EG", "GH", "TZ", "CI", "SN", "MA"],
    "americas": ["US", "CA", "MX", "BR", "AR", "CL", "CO", "PE", "EC", "CR"],
}


@dataclass
class DimensionBenchmark:
    """次元別ベンチマーク結果"""
    dimension: str
    entity_score: int
    benchmark_median: float
    benchmark_mean: float
    benchmark_std: float
    relative_position: str  # "above_average" | "average" | "below_average"
    is_critical: bool
    percentile_rank: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "entity_score": self.entity_score,
            "benchmark_median": round(self.benchmark_median, 1),
            "benchmark_mean": round(self.benchmark_mean, 1),
            "benchmark_std": round(self.benchmark_std, 1),
            "relative_position": self.relative_position,
            "is_critical": self.is_critical,
            "percentile_rank": round(self.percentile_rank, 1) if self.percentile_rank is not None else None,
        }


@dataclass
class BenchmarkReport:
    """業界ベンチマークレポート"""
    entity_name: str
    entity_country: str
    industry: str
    entity_overall: int
    industry_median: float
    dimension_benchmarks: list[DimensionBenchmark]
    risk_tolerance: str
    sample_countries: list[str]
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "entity_name": self.entity_name,
            "entity_country": self.entity_country,
            "industry": self.industry,
            "entity_overall": self.entity_overall,
            "industry_median": round(self.industry_median, 1),
            "risk_tolerance": self.risk_tolerance,
            "sample_countries": self.sample_countries,
            "dimension_benchmarks": [d.to_dict() for d in self.dimension_benchmarks],
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class PeerBenchmarkReport:
    """競合他社ベンチマークレポート"""
    target_name: str
    target_country: str
    target_overall: int
    peer_count: int
    percentile_overall: float
    dimension_rankings: list[dict]
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "target_name": self.target_name,
            "target_country": self.target_country,
            "target_overall": self.target_overall,
            "peer_count": self.peer_count,
            "percentile_overall": round(self.percentile_overall, 1),
            "dimension_rankings": self.dimension_rankings,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class RegionalBaseline:
    """地域ベースライン"""
    region: str
    countries: list[str]
    sample_size: int
    overall_mean: float
    overall_median: float
    overall_std: float
    dimension_stats: dict[str, dict]
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "region": self.region,
            "countries": self.countries,
            "sample_size": self.sample_size,
            "overall_mean": round(self.overall_mean, 1),
            "overall_median": round(self.overall_median, 1),
            "overall_std": round(self.overall_std, 1),
            "dimension_stats": {
                k: {kk: round(vv, 1) for kk, vv in v.items()}
                for k, v in self.dimension_stats.items()
            },
            "generated_at": self.generated_at.isoformat(),
        }


def _get_scores_for_country(country: str) -> Optional[dict]:
    """国のリスクスコアを取得"""
    try:
        result = calculate_risk_score(
            f"bench_{country}", country, country=country, location=country,
        )
        return result.to_dict()
    except Exception:
        return None


def _relative_position(score: int, median: float, std: float) -> str:
    """平均との相対位置を判定"""
    if std == 0:
        return "average"
    z = (score - median) / std
    if z > 0.5:
        return "above_average"
    if z < -0.5:
        return "below_average"
    return "average"


# 地域ベースラインキャッシュ
_regional_cache: dict[str, tuple[RegionalBaseline, datetime]] = {}
_CACHE_TTL_HOURS = 6


class BenchmarkAnalyzer:
    """業界・地域・競合ベンチマーク分析エンジン"""

    def benchmark_against_industry(
        self,
        target_entity: dict,
    ) -> BenchmarkReport:
        """ターゲットのスコアを業界標準国群の中央値と比較。

        Args:
            target_entity: {"name": ..., "country": ..., "industry": "automotive"}

        Returns:
            BenchmarkReport with dimension-level comparison.
        """
        name = target_entity.get("name", "Unknown")
        country = target_entity.get("country", "")
        industry = target_entity.get("industry", "")

        profile = INDUSTRY_PROFILES.get(industry)
        if not profile:
            available = list(INDUSTRY_PROFILES.keys())
            raise ValueError(f"Unknown industry '{industry}'. Available: {available}")

        critical_dims = profile["critical_dimensions"]
        sample_countries = profile["typical_countries"]

        # ターゲットスコア取得
        target_result = _get_scores_for_country(country)
        if not target_result:
            raise ValueError(f"Could not get scores for country: {country}")

        target_scores = target_result.get("scores", {})
        target_overall = target_result.get("overall_score", 0)

        # 業界標準国群スコア取得
        benchmark_data: list[dict] = []
        for c in sample_countries:
            result = _get_scores_for_country(c)
            if result:
                benchmark_data.append(result)

        if not benchmark_data:
            raise ValueError("Could not get benchmark data for any industry country")

        # 次元別ベンチマーク算出
        dims = sorted(SupplierRiskScore.WEIGHTS.keys())
        benchmarks: list[DimensionBenchmark] = []
        industry_overalls = [d.get("overall_score", 0) for d in benchmark_data]

        for dim in dims:
            values = [d.get("scores", {}).get(dim, 0) for d in benchmark_data]
            arr = np.array(values, dtype=float)
            median_val = float(np.median(arr))
            mean_val = float(np.mean(arr))
            std_val = float(np.std(arr))

            entity_val = target_scores.get(dim, 0)
            is_critical = dim in critical_dims

            benchmarks.append(DimensionBenchmark(
                dimension=dim,
                entity_score=entity_val,
                benchmark_median=median_val,
                benchmark_mean=mean_val,
                benchmark_std=std_val,
                relative_position=_relative_position(entity_val, median_val, std_val),
                is_critical=is_critical,
            ))

        return BenchmarkReport(
            entity_name=name,
            entity_country=country,
            industry=industry,
            entity_overall=target_overall,
            industry_median=float(np.median(industry_overalls)),
            dimension_benchmarks=benchmarks,
            risk_tolerance=profile["risk_tolerance"],
            sample_countries=sample_countries,
        )

    def benchmark_against_peers(
        self,
        target_entity: dict,
        peer_entities: list[dict],
    ) -> PeerBenchmarkReport:
        """競合他社リストとの百分位ランク比較。

        Args:
            target_entity: {"name": ..., "country": ...}
            peer_entities: [{"name": ..., "country": ...}, ...]

        Returns:
            PeerBenchmarkReport with percentile rankings.
        """
        target_name = target_entity.get("name", "Unknown")
        target_country = target_entity.get("country", "")

        # 全エンティティのスコア取得
        target_result = _get_scores_for_country(target_country)
        if not target_result:
            raise ValueError(f"Could not get scores for: {target_country}")

        peer_results: list[dict] = []
        for peer in peer_entities:
            result = _get_scores_for_country(peer.get("country", ""))
            if result:
                peer_results.append(result)

        if not peer_results:
            raise ValueError("Could not get scores for any peer")

        target_scores = target_result.get("scores", {})
        target_overall = target_result.get("overall_score", 0)

        # overall百分位ランク
        all_overalls = [target_overall] + [p.get("overall_score", 0) for p in peer_results]
        all_overalls_sorted = sorted(all_overalls)
        target_rank_overall = all_overalls_sorted.index(target_overall) + 1
        percentile_overall = (target_rank_overall / len(all_overalls)) * 100

        # 次元別ランキング
        dims = sorted(SupplierRiskScore.WEIGHTS.keys())
        rankings: list[dict] = []
        for dim in dims:
            all_vals = [target_scores.get(dim, 0)] + [
                p.get("scores", {}).get(dim, 0) for p in peer_results
            ]
            sorted_vals = sorted(all_vals)
            rank = sorted_vals.index(target_scores.get(dim, 0)) + 1
            rankings.append({
                "dimension": dim,
                "score": target_scores.get(dim, 0),
                "rank": rank,
                "total": len(all_vals),
                "percentile": round((rank / len(all_vals)) * 100, 1),
            })

        return PeerBenchmarkReport(
            target_name=target_name,
            target_country=target_country,
            target_overall=target_overall,
            peer_count=len(peer_results),
            percentile_overall=percentile_overall,
            dimension_rankings=rankings,
        )

    def benchmark_bom_against_industry(
        self,
        bom_result: dict,
        industry: str,
    ) -> dict:
        """BOM分析結果を同業他社リスクと比較。

        Args:
            bom_result: BOMAnalyzer.analyze_bom().to_dict() の出力
            industry: 業種キー（INDUSTRY_PROFILES のキー）

        Returns:
            {
                "your_confirmed_risk": float,
                "industry_median_risk": float,
                "percentile_rank": float,
                "worst_dimension_vs_peers": dict,
                "best_practice_companies": list,
                "dimension_comparison": list,
                "risk_gap_analysis": dict,
            }
        """
        profile = INDUSTRY_PROFILES.get(industry)
        if not profile:
            available = list(INDUSTRY_PROFILES.keys())
            raise ValueError(f"Unknown industry '{industry}'. Available: {available}")

        # BOM の confirmed_risk を取得
        your_risk = bom_result.get("confirmed_risk_score", bom_result.get("full_risk_score", 0))

        # 業界標準国群のリスクスコアを取得
        sample_countries = profile["typical_countries"]
        critical_dims = profile["critical_dimensions"]
        industry_scores: list[dict] = []
        industry_overalls: list[float] = []

        for c in sample_countries:
            result = _get_scores_for_country(c)
            if result:
                industry_scores.append(result)
                industry_overalls.append(result.get("overall_score", 0))

        if not industry_scores:
            raise ValueError(f"業界 '{industry}' のベンチマークデータ取得に失敗しました")

        industry_overalls_arr = np.array(industry_overalls, dtype=float)
        industry_median = float(np.median(industry_overalls_arr))

        # 百分位ランク: BOMリスクが業界内でどの位置にいるか
        rank = float(np.sum(industry_overalls_arr < your_risk))
        percentile = (rank / len(industry_overalls_arr)) * 100

        # 次元別比較: BOM 内部品のリスクスコアを業界平均と比較
        dims = sorted(SupplierRiskScore.WEIGHTS.keys())
        dimension_comparison = []
        worst_gap = {"dimension": "", "gap": 0.0}

        # BOM 部品の国別リスクを次元別に集約
        bom_dim_scores: dict[str, list[float]] = {d: [] for d in dims}
        for part in bom_result.get("part_risks", []):
            country = part.get("supplier_country", "")
            if not country:
                continue
            country_result = _get_scores_for_country(country)
            if country_result:
                for d in dims:
                    val = country_result.get("scores", {}).get(d, 0)
                    bom_dim_scores[d].append(val)

        for dim in dims:
            # 業界ベンチマーク
            bench_values = [
                s.get("scores", {}).get(dim, 0) for s in industry_scores
            ]
            bench_arr = np.array(bench_values, dtype=float)
            bench_median = float(np.median(bench_arr))
            bench_mean = float(np.mean(bench_arr))

            # BOM スコア
            bom_vals = bom_dim_scores.get(dim, [])
            bom_avg = float(np.mean(bom_vals)) if bom_vals else 0.0

            gap = bom_avg - bench_median
            is_critical = dim in critical_dims

            dimension_comparison.append({
                "dimension": dim,
                "your_score": round(bom_avg, 1),
                "industry_median": round(bench_median, 1),
                "industry_mean": round(bench_mean, 1),
                "gap": round(gap, 1),
                "is_critical": is_critical,
                "assessment": (
                    "業界平均より良好" if gap < -5 else
                    "業界平均並み" if abs(gap) <= 5 else
                    "業界平均より悪い"
                ),
            })

            if gap > worst_gap["gap"]:
                worst_gap = {"dimension": dim, "gap": round(gap, 1)}

        # ベストプラクティス企業（低リスク国）
        best_practice = sorted(
            [{"country": c, "risk_score": s.get("overall_score", 0)}
             for c, s in zip(sample_countries, industry_scores)],
            key=lambda x: x["risk_score"],
        )[:3]

        # リスクギャップ分析
        gap_analysis = {
            "overall_gap": round(your_risk - industry_median, 1),
            "position": (
                "業界平均より低リスク" if your_risk < industry_median - 5 else
                "業界平均並み" if abs(your_risk - industry_median) <= 5 else
                "業界平均より高リスク"
            ),
            "critical_dimension_gaps": [
                d for d in dimension_comparison
                if d["is_critical"] and d["gap"] > 5
            ],
        }

        return {
            "your_confirmed_risk": round(your_risk, 1),
            "industry": industry,
            "industry_median_risk": round(industry_median, 1),
            "percentile_rank": round(percentile, 1),
            "worst_dimension_vs_peers": worst_gap,
            "best_practice_companies": best_practice,
            "dimension_comparison": dimension_comparison,
            "risk_gap_analysis": gap_analysis,
            "risk_tolerance": profile["risk_tolerance"],
            "sample_countries": sample_countries,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def compute_regional_baseline(
        self,
        region: str,
    ) -> RegionalBaseline:
        """地域内全国の平均・中央値・標準偏差を次元別に算出。

        Args:
            region: "east_asia" | "southeast_asia" | "europe" | "middle_east" | "africa" | "americas"

        Returns:
            RegionalBaseline with per-dimension statistics.
        """
        # キャッシュチェック
        if region in _regional_cache:
            cached, cached_at = _regional_cache[region]
            from datetime import timedelta
            if datetime.utcnow() - cached_at < timedelta(hours=_CACHE_TTL_HOURS):
                return cached

        countries = REGION_MAP.get(region)
        if not countries:
            available = list(REGION_MAP.keys())
            raise ValueError(f"Unknown region '{region}'. Available: {available}")

        # 全国のスコア取得
        country_data: list[dict] = []
        for c in countries:
            result = _get_scores_for_country(c)
            if result:
                country_data.append(result)

        if not country_data:
            raise ValueError(f"Could not get scores for any country in {region}")

        overalls = np.array([d.get("overall_score", 0) for d in country_data], dtype=float)

        dims = sorted(SupplierRiskScore.WEIGHTS.keys())
        dim_stats: dict[str, dict] = {}
        for dim in dims:
            values = np.array(
                [d.get("scores", {}).get(dim, 0) for d in country_data],
                dtype=float,
            )
            dim_stats[dim] = {
                "mean": float(np.mean(values)),
                "median": float(np.median(values)),
                "std": float(np.std(values)),
                "min": float(np.min(values)),
                "max": float(np.max(values)),
            }

        baseline = RegionalBaseline(
            region=region,
            countries=[c for c in countries if _get_scores_for_country(c) is not None],
            sample_size=len(country_data),
            overall_mean=float(np.mean(overalls)),
            overall_median=float(np.median(overalls)),
            overall_std=float(np.std(overalls)),
            dimension_stats=dim_stats,
        )

        _regional_cache[region] = (baseline, datetime.utcnow())
        return baseline
