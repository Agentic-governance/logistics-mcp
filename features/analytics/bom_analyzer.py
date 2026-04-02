"""BOM (Bill of Materials) リスク分析エンジン
部品表を入力にして、各部品のサプライヤー国リスクを評価。
Tier-2+ 推定オプションにより、Tier-1 では見えない隠れたリスクも算出。

confirmed_risk_score: Tier-1 情報のみで算出したリスク
full_risk_score: Tier-2/3 推定を含む総合リスク
hidden_risk_delta: full_risk - confirmed_risk (推定による追加リスク)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class BOMNode:
    """BOM の 1 行 = 1 部品"""
    part_id: str
    part_name: str
    supplier_name: str
    supplier_country: str
    material: str = ""
    hs_code: str = ""
    tier: int = 1
    quantity: float = 1.0
    unit_cost_usd: float = 0.0
    is_critical: bool = False
    # 推定で追加されたか
    is_inferred: bool = False
    confidence: float = 1.0
    # STREAM 4: 評判スクリーニング結果
    reputation_result: Optional[dict] = None


@dataclass
class BOMRiskResult:
    """BOM リスク分析結果"""
    product_name: str
    total_parts: int
    unique_countries: int
    confirmed_risk_score: float
    full_risk_score: float
    hidden_risk_delta: float
    resilience_score: float
    concentration_hhi: float
    critical_bottlenecks: list[dict]
    mitigations: list[str]
    part_risks: list[dict]
    inferred_parts: list[dict]
    timestamp: str
    financial_exposure: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "product_name": self.product_name,
            "total_parts": self.total_parts,
            "unique_countries": self.unique_countries,
            "confirmed_risk_score": round(self.confirmed_risk_score, 1),
            "full_risk_score": round(self.full_risk_score, 1),
            "hidden_risk_delta": round(self.hidden_risk_delta, 1),
            "resilience_score": round(self.resilience_score, 1),
            "concentration_hhi": round(self.concentration_hhi, 4),
            "critical_bottlenecks": self.critical_bottlenecks,
            "mitigations": self.mitigations,
            "part_risks": self.part_risks,
            "inferred_parts": self.inferred_parts,
            "financial_exposure": self.financial_exposure,
            "timestamp": self.timestamp,
        }


class BOMAnalyzer:
    """BOM リスク分析"""

    def __init__(self):
        self._score_cache: dict[str, int] = {}

    def _get_country_risk(self, country: str) -> int:
        """国リスクスコアを取得（キャッシュ付き）"""
        if country in self._score_cache:
            return self._score_cache[country]

        try:
            from scoring.engine import calculate_risk_score
            score = calculate_risk_score(
                f"bom_{country.lower().replace(' ', '_')}",
                f"BOM: {country}",
                country=country,
                location=country,
            )
            risk = score.overall_score
        except Exception:
            risk = 0

        self._score_cache[country] = risk
        return risk

    def analyze_bom(
        self,
        bom: list[BOMNode],
        product_name: str = "Product",
        include_tier2_inference: bool = False,
    ) -> BOMRiskResult:
        """BOM のリスク分析を実行。

        Args:
            bom: BOMNode のリスト
            product_name: 製品名
            include_tier2_inference: True で Tier-2/3 推定を含める

        Returns:
            BOMRiskResult
        """
        if not bom:
            return BOMRiskResult(
                product_name=product_name,
                total_parts=0, unique_countries=0,
                confirmed_risk_score=0, full_risk_score=0,
                hidden_risk_delta=0, resilience_score=100,
                concentration_hhi=0, critical_bottlenecks=[],
                mitigations=[], part_risks=[], inferred_parts=[],
                timestamp=datetime.utcnow().isoformat(),
            )

        # 1. 各部品の国リスクを算出
        part_risks = []
        total_cost = sum(n.quantity * n.unit_cost_usd for n in bom) or 1.0

        for node in bom:
            risk = self._get_country_risk(node.supplier_country)
            cost_weight = (node.quantity * node.unit_cost_usd) / total_cost if total_cost > 0 else 1.0 / len(bom)

            part_risks.append({
                "part_id": node.part_id,
                "part_name": node.part_name,
                "supplier_name": node.supplier_name,
                "supplier_country": node.supplier_country,
                "material": node.material,
                "tier": node.tier,
                "risk_score": risk,
                "cost_weight": round(cost_weight, 4),
                "is_critical": node.is_critical,
                "is_inferred": node.is_inferred,
                "confidence": node.confidence,
            })

        # 2. Confirmed risk (Tier-1 only, cost-weighted)
        confirmed_parts = [p for p in part_risks if not p["is_inferred"]]
        if confirmed_parts:
            total_weight = sum(p["cost_weight"] for p in confirmed_parts)
            if total_weight > 0:
                confirmed_risk = sum(
                    p["risk_score"] * p["cost_weight"] / total_weight
                    for p in confirmed_parts
                )
            else:
                confirmed_risk = sum(p["risk_score"] for p in confirmed_parts) / len(confirmed_parts)
        else:
            confirmed_risk = 0

        # 3. Tier-2/3 inference
        inferred_parts = []
        if include_tier2_inference:
            inferred_parts = self._run_tier_inference(bom)
            # Add inferred parts to part_risks
            for ip in inferred_parts:
                part_risks.append(ip)

        # 4. Full risk (includes inferred)
        if part_risks:
            # Peak amplification: highest risk contributes extra
            all_risks = [p["risk_score"] for p in part_risks]
            peak_risk = max(all_risks) if all_risks else 0

            # Weighted average of all parts
            all_weights = sum(p["cost_weight"] for p in part_risks)
            if all_weights > 0:
                weighted_avg = sum(
                    p["risk_score"] * p["cost_weight"] / all_weights
                    for p in part_risks
                )
            else:
                weighted_avg = sum(all_risks) / len(all_risks)

            full_risk = weighted_avg * 0.7 + peak_risk * 0.3
        else:
            full_risk = confirmed_risk

        hidden_delta = full_risk - confirmed_risk

        # 5. Country concentration (HHI)
        countries = [p["supplier_country"] for p in part_risks]
        country_shares = {}
        for c in countries:
            country_shares[c] = country_shares.get(c, 0) + 1
        total = len(countries) or 1
        hhi = sum((count / total) ** 2 for count in country_shares.values())

        # 6. Critical bottlenecks
        bottlenecks = self.find_critical_bottlenecks(part_risks)

        # 7. Mitigations
        mitigations = self.suggest_mitigations(part_risks, hhi, bottlenecks)

        # 8. Resilience score
        resilience = self.generate_resilience_score(
            confirmed_risk, full_risk, hhi, len(set(countries)), len(bottlenecks),
        )

        # 9. Financial exposure (STREAM 5-C)
        financial_exposure = self._calculate_financial_exposure(part_risks)

        return BOMRiskResult(
            product_name=product_name,
            total_parts=len(bom),
            unique_countries=len(set(countries)),
            confirmed_risk_score=confirmed_risk,
            full_risk_score=full_risk,
            hidden_risk_delta=hidden_delta,
            resilience_score=resilience,
            concentration_hhi=hhi,
            critical_bottlenecks=bottlenecks,
            mitigations=mitigations,
            part_risks=part_risks,
            inferred_parts=inferred_parts,
            financial_exposure=financial_exposure,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _run_tier_inference(self, bom: list[BOMNode]) -> list[dict]:
        """BOM の各部品に対して Tier-2/3 推定を実行"""
        try:
            from features.analytics.tier_inference import (
                TierInferenceEngine, MATERIAL_TO_HS,
            )
        except ImportError:
            return []

        engine = TierInferenceEngine()
        inferred = []
        seen = set()

        for node in bom:
            if node.tier != 1:
                continue

            hs_code = node.hs_code
            if not hs_code and node.material:
                hs_code = MATERIAL_TO_HS.get(node.material.lower(), "")
            if not hs_code:
                continue

            # Tier-2
            tier2 = engine.infer_tier2(node.supplier_country, hs_code, node.material)
            for t2 in tier2:
                dedupe = f"{t2.country}|{hs_code}|2"
                if dedupe in seen:
                    continue
                seen.add(dedupe)

                risk = self._get_country_risk(t2.country)

                inferred.append({
                    "part_id": f"inferred_t2_{node.part_id}_{t2.country}",
                    "part_name": f"{node.material or node.part_name} (Tier-2 inferred)",
                    "supplier_name": f"Inferred: {t2.country}",
                    "supplier_country": t2.country,
                    "material": node.material,
                    "tier": 2,
                    "risk_score": risk,
                    "cost_weight": round(node.quantity * node.unit_cost_usd * t2.trade_share / max(1, sum(n.quantity * n.unit_cost_usd for n in bom)), 4),
                    "is_critical": False,
                    "is_inferred": True,
                    "confidence": t2.confidence,
                    "trade_share": round(t2.trade_share, 4),
                    "source": t2.source,
                })

        return inferred

    def _calculate_financial_exposure(self, part_risks: list[dict]) -> Optional[dict]:
        """BOM 全部品の財務エクスポージャーを算出 (STREAM 5-C)"""
        try:
            from features.analytics.cost_impact_analyzer import CostImpactAnalyzer
            analyzer = CostImpactAnalyzer()
            return analyzer.estimate_bom_financial_exposure(
                bom_parts=part_risks,
                scenario="disaster",
                duration_days=60,
            )
        except Exception:
            return None

    def calculate_product_risk(
        self,
        bom: list[BOMNode],
        product_name: str = "Product",
    ) -> dict:
        """Tier-1 のみと Tier-2 推定込みの両方のリスクを返す。

        Returns:
            {
                "confirmed_risk": float,
                "full_risk": float,
                "hidden_risk_delta": float,
            }
        """
        confirmed = self.analyze_bom(bom, product_name, include_tier2_inference=False)
        full = self.analyze_bom(bom, product_name, include_tier2_inference=True)

        return {
            "product_name": product_name,
            "confirmed_risk": round(confirmed.confirmed_risk_score, 1),
            "full_risk": round(full.full_risk_score, 1),
            "hidden_risk_delta": round(full.full_risk_score - confirmed.confirmed_risk_score, 1),
            "confirmed_parts": confirmed.total_parts,
            "inferred_parts_added": len(full.inferred_parts),
        }

    # 制裁・高リスク国リスト
    SANCTIONED_COUNTRIES = [
        "Russia", "China", "Iran", "North Korea",
        "Myanmar", "Syria", "Venezuela", "Cuba", "Belarus",
    ]

    def find_critical_bottlenecks(self, part_risks: list[dict]) -> list[dict]:
        """クリティカルなボトルネックを検出。

        条件:
        - 単一国に依存 (代替なし) → bottleneck_type: "single_source"
        - 高リスク国 (risk >= 60) → bottleneck_type: "high_risk_country"
        - クリティカル部品指定 → bottleneck_type: "critical_designation"
        - コスト集中 (単一部品がBOM総額の25%超) → bottleneck_type: "cost_concentration"
        - 制裁対象国からの調達 → bottleneck_type: "sanctioned_country"
        """
        bottlenecks = []

        # 総コスト算出 (cost_concentration 判定用)
        total_cost = sum(
            p.get("cost_weight", 0) for p in part_risks
        ) or 1.0

        # Group by material
        material_countries: dict[str, list[dict]] = {}
        for p in part_risks:
            mat = p.get("material", p.get("part_name", ""))
            if mat not in material_countries:
                material_countries[mat] = []
            material_countries[mat].append(p)

        for mat, parts in material_countries.items():
            countries = set(p["supplier_country"] for p in parts if not p.get("is_inferred"))
            max_risk = max((p["risk_score"] for p in parts), default=0)

            is_bottleneck = False
            reasons = []
            bottleneck_types = []

            if len(countries) == 1:
                is_bottleneck = True
                reasons.append(f"単一国依存: {list(countries)[0]}")
                bottleneck_types.append("single_source")

            if max_risk >= 60:
                is_bottleneck = True
                reasons.append(f"高リスク国 (score={max_risk})")
                bottleneck_types.append("high_risk_country")

            if any(p.get("is_critical") for p in parts):
                is_bottleneck = True
                reasons.append("クリティカル部品指定")
                bottleneck_types.append("critical_designation")

            # NEW: cost_concentration — 単一部品のコストウェイトが25%超
            for p in parts:
                if not p.get("is_inferred") and p.get("cost_weight", 0) > 0.25:
                    is_bottleneck = True
                    pct = round(p["cost_weight"] * 100, 1)
                    reasons.append(f"コスト集中: {p['part_name']} ({pct}%)")
                    if "cost_concentration" not in bottleneck_types:
                        bottleneck_types.append("cost_concentration")

            # NEW: sanctioned_country — 制裁・高リスク国リストに該当
            sanctioned_hits = countries & set(self.SANCTIONED_COUNTRIES)
            if sanctioned_hits:
                is_bottleneck = True
                reasons.append(f"制裁対象国: {', '.join(sorted(sanctioned_hits))}")
                bottleneck_types.append("sanctioned_country")

            if is_bottleneck:
                bottlenecks.append({
                    "material": mat,
                    "countries": list(countries),
                    "max_risk_score": max_risk,
                    "reasons": reasons,
                    "bottleneck_type": bottleneck_types,
                    "affected_parts": [p["part_id"] for p in parts if not p.get("is_inferred")],
                })

        bottlenecks.sort(key=lambda x: -x["max_risk_score"])
        return bottlenecks

    def suggest_mitigations(
        self,
        part_risks: list[dict],
        hhi: float,
        bottlenecks: list[dict],
    ) -> list[str]:
        """リスク緩和策を提案"""
        suggestions = []

        # High concentration
        if hhi > 0.25:
            top_country = max(
                set(p["supplier_country"] for p in part_risks),
                key=lambda c: sum(1 for p in part_risks if p["supplier_country"] == c),
            )
            suggestions.append(
                f"地理的集中リスク (HHI={hhi:.3f}): {top_country} への依存度を分散してください。"
            )

        # Single source bottlenecks
        single_source = [b for b in bottlenecks if len(b["countries"]) == 1]
        if single_source:
            mats = ", ".join(b["material"] for b in single_source[:3])
            suggestions.append(
                f"単一国ソース: {mats} のセカンドソースを確保してください。"
            )

        # High-risk countries
        high_risk = [p for p in part_risks if p["risk_score"] >= 60 and not p.get("is_inferred")]
        if high_risk:
            countries = set(p["supplier_country"] for p in high_risk)
            suggestions.append(
                f"高リスク調達国 ({', '.join(countries)}): 代替サプライヤーの検討、または安全在庫の積み増しを推奨。"
            )

        # Inferred high risk
        inferred_high = [p for p in part_risks if p.get("is_inferred") and p["risk_score"] >= 50]
        if inferred_high:
            countries = set(p["supplier_country"] for p in inferred_high)
            suggestions.append(
                f"Tier-2 推定リスク ({', '.join(countries)}): "
                "Tier-1 サプライヤーに上流調達先の開示を要求し、リスクの実態を確認してください。"
            )

        if not suggestions:
            suggestions.append("現時点で重大なリスク集中は検出されていません。定期監視を継続してください。")

        return suggestions

    def generate_resilience_score(
        self,
        confirmed_risk: float,
        full_risk: float,
        hhi: float,
        n_countries: int,
        n_bottlenecks: int,
    ) -> float:
        """サプライチェーンレジリエンス・スコアを算出 (0-100, 高い=良い)。

        指標:
        - リスクスコアの低さ (40%)
        - 地理的分散度 (30%)
        - ボトルネックの少なさ (30%)
        """
        # Risk factor: 100 - risk = resilience from risk perspective
        risk_factor = max(0, 100 - full_risk)

        # Diversification factor
        if hhi < 0.1:
            div_factor = 100  # Very well diversified
        elif hhi < 0.25:
            div_factor = 70
        elif hhi < 0.5:
            div_factor = 40
        else:
            div_factor = 10  # Highly concentrated

        # Country bonus
        div_factor = min(100, div_factor + n_countries * 3)

        # Bottleneck penalty
        bottleneck_factor = max(0, 100 - n_bottlenecks * 20)

        resilience = risk_factor * 0.4 + div_factor * 0.3 + bottleneck_factor * 0.3
        return min(100, max(0, resilience))
