"""需要予測 x サプライリスクの統合分析 — STREAM G-4
需要予測データとサプライチェーンリスクスコアを統合し、
供給不足の確率試算・需要ショックシミュレーション・調達戦略推奨を行う。
"""
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SupplyRiskAssessment:
    """供給リスク評価結果"""
    overall_supply_risk: float   # 0-100
    shortage_probability_pct: float
    affected_parts: list[dict]
    bottleneck_parts: list[dict]
    recommended_actions: list[str]
    scenario_analysis: dict      # best/base/worst case
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "overall_supply_risk": round(self.overall_supply_risk, 1),
            "shortage_probability_pct": round(self.shortage_probability_pct, 1),
            "affected_parts": self.affected_parts,
            "bottleneck_parts": self.bottleneck_parts,
            "recommended_actions": self.recommended_actions,
            "scenario_analysis": self.scenario_analysis,
            "generated_at": self.generated_at,
        }


def _risk_level(score: float) -> str:
    """リスクレベル判定"""
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score >= 20:
        return "LOW"
    return "MINIMAL"


class DemandRiskIntegrator:
    """需要予測 x サプライリスクの統合分析エンジン"""

    # リスクスコア→供給能力低下率のマッピング
    RISK_TO_CAPACITY_REDUCTION = {
        "CRITICAL": 0.50,   # 50%の供給能力低下
        "HIGH": 0.30,       # 30%の供給能力低下
        "MEDIUM": 0.15,     # 15%の供給能力低下
        "LOW": 0.05,        # 5%の供給能力低下
        "MINIMAL": 0.02,    # 2%の供給能力低下
    }

    # シナリオ別の補正係数
    SCENARIO_MULTIPLIERS = {
        "best": 0.5,    # 楽観: リスクの半分が実現
        "base": 1.0,    # 基本: リスクがそのまま実現
        "worst": 1.5,   # 悲観: リスクの1.5倍が実現
    }

    def evaluate_supply_risk_for_forecast(
        self,
        demand_forecast: list[dict],
        bom_result: dict = None,
        risk_scores: dict = None,
    ) -> SupplyRiskAssessment:
        """需要予測に対する供給リスクを評価する。

        「来月の需要が2倍になる見込みだが、希土類磁石の調達リスクが高い場合、
         どのくらいの確率で供給不足になるか」を試算する。

        Args:
            demand_forecast: 需要予測リスト
                [{part_id, part_name, daily_demand, forecast_horizon_days,
                  supplier_country (optional), current_inventory (optional)}]
            bom_result: BOMAnalyzer.analyze_bom() の結果 (to_dict形式)。
                        提供されない場合は demand_forecast 内の情報のみで分析。
            risk_scores: 国別リスクスコア辞書 {country: score_result_dict}。
                         提供されない場合は内部でスコアを取得。

        Returns:
            SupplyRiskAssessment
        """
        try:
            if not demand_forecast:
                return SupplyRiskAssessment(
                    overall_supply_risk=0.0,
                    shortage_probability_pct=0.0,
                    affected_parts=[],
                    bottleneck_parts=[],
                    recommended_actions=["需要予測データが提供されていません"],
                    scenario_analysis={},
                )

            # 各部品のリスク評価
            affected_parts = []
            bottleneck_parts = []
            total_risk_weighted = 0.0
            total_weight = 0.0

            for item in demand_forecast:
                part_risk = self._evaluate_part_risk(item, bom_result, risk_scores)
                affected_parts.append(part_risk)

                if part_risk.get("is_bottleneck", False):
                    bottleneck_parts.append(part_risk)

                # 需要量で重み付け
                weight = item.get("daily_demand", 1.0) * item.get("forecast_horizon_days", 30)
                total_risk_weighted += part_risk.get("supply_risk_score", 0) * weight
                total_weight += weight

            # 総合供給リスク
            overall_risk = total_risk_weighted / total_weight if total_weight > 0 else 0.0
            overall_risk = min(100, max(0, overall_risk))

            # 供給不足確率の試算
            shortage_prob = self._estimate_shortage_probability(
                affected_parts, overall_risk,
            )

            # シナリオ分析
            scenario_analysis = self._run_scenario_analysis(
                affected_parts, overall_risk,
            )

            # 推奨アクション
            recommended_actions = self._generate_procurement_recommendations(
                affected_parts, bottleneck_parts, overall_risk, shortage_prob,
            )

            return SupplyRiskAssessment(
                overall_supply_risk=overall_risk,
                shortage_probability_pct=shortage_prob,
                affected_parts=affected_parts,
                bottleneck_parts=bottleneck_parts,
                recommended_actions=recommended_actions,
                scenario_analysis=scenario_analysis,
            )

        except Exception as e:
            logger.error(f"供給リスク評価エラー: {e}")
            return SupplyRiskAssessment(
                overall_supply_risk=0.0,
                shortage_probability_pct=0.0,
                affected_parts=[],
                bottleneck_parts=[],
                recommended_actions=[f"評価中にエラーが発生しました: {e}"],
                scenario_analysis={},
            )

    def _evaluate_part_risk(
        self,
        item: dict,
        bom_result: dict = None,
        risk_scores: dict = None,
    ) -> dict:
        """個別部品の供給リスクを評価"""
        part_id = item.get("part_id", "unknown")
        part_name = item.get("part_name", "Unknown Part")
        daily_demand = item.get("daily_demand", 0)
        horizon = item.get("forecast_horizon_days", 30)
        supplier_country = item.get("supplier_country", "")
        current_inventory = item.get("current_inventory", 0)

        # BOM結果から部品情報を取得
        bom_risk_score = 0
        if bom_result:
            part_risks = bom_result.get("part_risks", [])
            for pr in part_risks:
                if pr.get("part_id") == part_id or pr.get("part_name") == part_name:
                    bom_risk_score = pr.get("risk_score", 0)
                    if not supplier_country:
                        supplier_country = pr.get("supplier_country", "")
                    break

        # リスクスコアの取得
        country_risk = 0
        if risk_scores and supplier_country:
            country_score = risk_scores.get(supplier_country, {})
            country_risk = country_score.get("overall_score", 0)
        elif bom_risk_score > 0:
            country_risk = bom_risk_score
        elif supplier_country:
            # 内部でスコアを取得（軽量版）
            country_risk = self._get_country_risk_score(supplier_country)

        # 供給リスクスコア計算
        risk_level = _risk_level(country_risk)
        capacity_reduction = self.RISK_TO_CAPACITY_REDUCTION.get(risk_level, 0.02)

        # 需要期間の総需要量
        total_demand = daily_demand * horizon

        # 供給可能量の推定（リスクによる減少）
        estimated_supply = total_demand * (1.0 - capacity_reduction)

        # 不足量
        shortfall = max(0, total_demand - estimated_supply - current_inventory)

        # 在庫カバー日数
        coverage_days = current_inventory / daily_demand if daily_demand > 0 else float("inf")

        # ボトルネック判定
        is_bottleneck = (
            country_risk >= 60
            or shortfall > 0
            or coverage_days < 14
        )

        return {
            "part_id": part_id,
            "part_name": part_name,
            "supplier_country": supplier_country,
            "daily_demand": daily_demand,
            "forecast_horizon_days": horizon,
            "total_demand": round(total_demand, 1),
            "current_inventory": current_inventory,
            "coverage_days": round(coverage_days, 1) if coverage_days != float("inf") else None,
            "country_risk_score": country_risk,
            "risk_level": risk_level,
            "capacity_reduction_pct": round(capacity_reduction * 100, 1),
            "estimated_supply": round(estimated_supply, 1),
            "estimated_shortfall": round(shortfall, 1),
            "supply_risk_score": country_risk,
            "is_bottleneck": is_bottleneck,
        }

    def _get_country_risk_score(self, country: str) -> int:
        """国リスクスコアを取得（簡易版）"""
        try:
            from scoring.engine import calculate_risk_score
            result = calculate_risk_score(
                supplier_id=f"demand_risk_{country.lower().replace(' ', '_')}",
                company_name=f"demand_risk: {country}",
                country=country,
                location=country,
            )
            return result.overall_score
        except Exception:
            return 0

    def _estimate_shortage_probability(
        self,
        affected_parts: list[dict],
        overall_risk: float,
    ) -> float:
        """供給不足の確率を試算する。

        ロジスティック関数でリスクスコアから確率を推定:
        - リスク0  → 確率 ~2%
        - リスク40 → 確率 ~15%
        - リスク60 → 確率 ~40%
        - リスク80 → 確率 ~75%
        - リスク100→ 確率 ~95%
        """
        # ロジスティック関数: P = 1 / (1 + exp(-k*(x - x0)))
        # パラメータ: k=0.08, x0=55 → リスク55で50%
        k = 0.08
        x0 = 55.0
        base_prob = 1.0 / (1.0 + math.exp(-k * (overall_risk - x0)))

        # ボトルネック部品があればさらに確率を上げる
        bottleneck_count = sum(1 for p in affected_parts if p.get("is_bottleneck"))
        bottleneck_boost = min(0.15, bottleneck_count * 0.05)

        probability = min(0.95, base_prob + bottleneck_boost)
        return round(probability * 100, 1)

    def _run_scenario_analysis(
        self,
        affected_parts: list[dict],
        overall_risk: float,
    ) -> dict:
        """ベスト/ベース/ワーストケースのシナリオ分析"""
        scenarios = {}

        for scenario, multiplier in self.SCENARIO_MULTIPLIERS.items():
            adjusted_risk = min(100, overall_risk * multiplier)
            risk_level = _risk_level(adjusted_risk)
            capacity_reduction = self.RISK_TO_CAPACITY_REDUCTION.get(risk_level, 0.02)

            total_demand = sum(
                p.get("total_demand", 0) for p in affected_parts
            )
            total_supply = total_demand * (1.0 - capacity_reduction * multiplier)
            total_shortfall = max(0, total_demand - total_supply)

            shortage_prob = self._estimate_shortage_probability(
                affected_parts, adjusted_risk,
            )

            scenarios[scenario] = {
                "adjusted_risk": round(adjusted_risk, 1),
                "risk_level": risk_level,
                "capacity_reduction_pct": round(capacity_reduction * multiplier * 100, 1),
                "total_demand": round(total_demand, 1),
                "estimated_supply": round(total_supply, 1),
                "estimated_shortfall": round(total_shortfall, 1),
                "shortage_probability_pct": shortage_prob,
            }

        return scenarios

    def _generate_procurement_recommendations(
        self,
        affected_parts: list[dict],
        bottleneck_parts: list[dict],
        overall_risk: float,
        shortage_prob: float,
    ) -> list[str]:
        """調達推奨アクションを生成"""
        recs = []

        if overall_risk >= 80:
            recs.append(
                "緊急対応: 供給リスクがCRITICALレベルです。代替調達先の即時確保と"
                "安全在庫の緊急積み増しを実施してください。"
            )
        elif overall_risk >= 60:
            recs.append(
                "高リスク警告: 代替サプライヤーの選定と安全在庫の見直しを"
                "早急に進めてください。"
            )

        if shortage_prob >= 50:
            recs.append(
                f"供給不足確率が{shortage_prob:.0f}%と高い水準です。"
                "調達量の前倒しまたは代替材料の検討を推奨します。"
            )

        if bottleneck_parts:
            bn_names = ", ".join(
                p.get("part_name", "N/A") for p in bottleneck_parts[:3]
            )
            recs.append(
                f"ボトルネック部品: {bn_names} — "
                "これらの部品のセカンドソース確保が最優先です。"
            )

        # 在庫カバー日数が短い部品
        low_coverage = [
            p for p in affected_parts
            if p.get("coverage_days") is not None and p["coverage_days"] < 14
        ]
        if low_coverage:
            parts_text = ", ".join(
                f"{p['part_name']}({p['coverage_days']:.0f}日)"
                for p in low_coverage[:3]
            )
            recs.append(
                f"在庫カバー不足: {parts_text} — "
                "最低2週間分の安全在庫確保を推奨します。"
            )

        # 高リスク国からの調達
        high_risk_countries = set()
        for p in affected_parts:
            if p.get("country_risk_score", 0) >= 60:
                high_risk_countries.add(p.get("supplier_country", ""))
        high_risk_countries.discard("")

        if high_risk_countries:
            recs.append(
                f"高リスク調達国 ({', '.join(sorted(high_risk_countries))}): "
                "代替国からの調達比率を段階的に引き上げてください。"
            )

        if not recs:
            recs.append(
                "現時点で緊急の供給リスクは検出されていません。"
                "定期的なモニタリングを継続してください。"
            )

        return recs

    def simulate_demand_shock(
        self,
        demand_multiplier: float,
        affected_parts: list[str],
        bom_result: dict = None,
    ) -> dict:
        """需要急増のインパクトをシミュレーションする。

        Args:
            demand_multiplier: 需要倍率 (例: 2.0 = 需要が2倍)
            affected_parts: 影響を受ける部品IDリスト
            bom_result: BOMAnalyzer.analyze_bom() の結果 (to_dict形式)

        Returns:
            シミュレーション結果辞書
        """
        try:
            if not bom_result:
                return {
                    "error": "BOM結果が提供されていません",
                    "demand_multiplier": demand_multiplier,
                }

            part_risks = bom_result.get("part_risks", [])
            if not part_risks:
                return {
                    "error": "BOMに部品リスクデータがありません",
                    "demand_multiplier": demand_multiplier,
                }

            # 影響を受ける部品を特定
            impacted = []
            non_impacted = []
            for pr in part_risks:
                if pr.get("part_id") in affected_parts or pr.get("part_name") in affected_parts:
                    impacted.append(pr)
                else:
                    non_impacted.append(pr)

            if not impacted:
                # 全部品が対象
                impacted = part_risks

            # 需要急増後の影響分析
            impact_analysis = []
            total_shortfall_risk = 0.0

            for part in impacted:
                risk_score = part.get("risk_score", 0)
                risk_level = _risk_level(risk_score)
                capacity_reduction = self.RISK_TO_CAPACITY_REDUCTION.get(risk_level, 0.02)

                # 需要倍率による供給ギャップ
                normal_supply_ratio = 1.0 - capacity_reduction
                demand_ratio = demand_multiplier
                supply_gap = max(0, demand_ratio - normal_supply_ratio)

                # 供給不足確率
                gap_severity = min(100, supply_gap * 50)

                impact_analysis.append({
                    "part_id": part.get("part_id"),
                    "part_name": part.get("part_name"),
                    "supplier_country": part.get("supplier_country"),
                    "risk_score": risk_score,
                    "demand_multiplier": demand_multiplier,
                    "normal_supply_capacity_pct": round((1 - capacity_reduction) * 100, 1),
                    "supply_gap_ratio": round(supply_gap, 2),
                    "shortage_severity": round(gap_severity, 1),
                })

                total_shortfall_risk += gap_severity

            avg_shortfall_risk = (
                total_shortfall_risk / len(impact_analysis)
                if impact_analysis else 0
            )

            # 推奨アクション
            actions = []
            if demand_multiplier >= 2.0:
                actions.append(
                    f"需要が{demand_multiplier}倍に急増した場合、通常の調達プロセスでは"
                    "対応困難です。スポット市場での緊急調達を検討してください。"
                )
            if avg_shortfall_risk >= 50:
                actions.append(
                    "代替材料や代替サプライヤーからの緊急調達を開始してください。"
                )
            if avg_shortfall_risk >= 30:
                actions.append(
                    "顧客への納期延長の事前通知を検討してください。"
                )
            actions.append(
                "在庫バッファの積み増しと調達リードタイムの再確認を推奨します。"
            )

            return {
                "demand_multiplier": demand_multiplier,
                "affected_parts_count": len(impact_analysis),
                "average_shortage_severity": round(avg_shortfall_risk, 1),
                "impact_analysis": impact_analysis,
                "recommended_actions": actions,
                "generated_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"需要ショックシミュレーションエラー: {e}")
            return {
                "error": str(e),
                "demand_multiplier": demand_multiplier,
                "generated_at": datetime.utcnow().isoformat(),
            }

    def recommend_procurement_strategy(
        self,
        demand_forecast: list[dict],
        risk_assessment: SupplyRiskAssessment,
    ) -> list[dict]:
        """需要予測とリスク評価に基づく調達戦略を推奨する。

        Args:
            demand_forecast: 需要予測リスト
            risk_assessment: evaluate_supply_risk_for_forecast() の結果

        Returns:
            調達推奨アクションのリスト
        """
        try:
            strategies = []
            overall_risk = risk_assessment.overall_supply_risk
            shortage_prob = risk_assessment.shortage_probability_pct

            # 1. 在庫戦略
            if overall_risk >= 60 or shortage_prob >= 40:
                buffer_days = 30 if overall_risk >= 80 else 14
                strategies.append({
                    "strategy": "safety_stock_increase",
                    "priority": "HIGH" if overall_risk >= 60 else "MEDIUM",
                    "description": f"安全在庫の積み増し（最低{buffer_days}日分）",
                    "rationale": (
                        f"供給リスク{overall_risk:.0f}/100、"
                        f"供給不足確率{shortage_prob:.0f}%のため、"
                        f"安全在庫を{buffer_days}日分以上確保することを推奨"
                    ),
                    "estimated_cost_impact": "中〜高",
                })

            # 2. マルチソーシング戦略
            bottlenecks = risk_assessment.bottleneck_parts
            if bottlenecks:
                high_risk_parts = [
                    b for b in bottlenecks if b.get("country_risk_score", 0) >= 60
                ]
                if high_risk_parts:
                    part_names = ", ".join(
                        p.get("part_name", "N/A") for p in high_risk_parts[:5]
                    )
                    strategies.append({
                        "strategy": "multi_sourcing",
                        "priority": "HIGH",
                        "description": f"マルチソーシング（セカンドソース確保）: {part_names}",
                        "rationale": (
                            "高リスク国への単一依存を回避するため、"
                            "代替サプライヤーからの調達比率を最低30%確保"
                        ),
                        "estimated_cost_impact": "中",
                    })

            # 3. 前倒し調達
            if shortage_prob >= 30:
                strategies.append({
                    "strategy": "forward_buying",
                    "priority": "MEDIUM" if shortage_prob < 50 else "HIGH",
                    "description": "前倒し調達（先行発注）",
                    "rationale": (
                        f"供給不足確率{shortage_prob:.0f}%を考慮し、"
                        "需要予測の1.2〜1.5倍の発注を推奨"
                    ),
                    "estimated_cost_impact": "中",
                })

            # 4. 代替材料検討
            critical_parts = [
                p for p in risk_assessment.affected_parts
                if p.get("country_risk_score", 0) >= 80
            ]
            if critical_parts:
                strategies.append({
                    "strategy": "material_substitution",
                    "priority": "MEDIUM",
                    "description": "代替材料・代替仕様の検討",
                    "rationale": (
                        "CRITICALレベルのリスク国からの調達部品について、"
                        "代替材料や設計変更の可能性を技術部門と協議"
                    ),
                    "estimated_cost_impact": "低〜中",
                })

            # 5. 契約見直し
            if overall_risk >= 40:
                strategies.append({
                    "strategy": "contract_review",
                    "priority": "LOW" if overall_risk < 60 else "MEDIUM",
                    "description": "サプライヤー契約の見直し（不可抗力条項・価格調整条項）",
                    "rationale": (
                        "供給リスクの高まりに備え、契約条件の見直しと"
                        "不可抗力時の対応手順を事前に合意"
                    ),
                    "estimated_cost_impact": "低",
                })

            # 6. モニタリング強化
            strategies.append({
                "strategy": "monitoring_enhancement",
                "priority": "LOW" if overall_risk < 40 else "MEDIUM",
                "description": "リスクモニタリング頻度の強化",
                "rationale": (
                    f"現在のリスクレベル（{_risk_level(overall_risk)}）に応じた"
                    "モニタリング頻度の設定"
                ),
                "estimated_cost_impact": "低",
            })

            # 優先度順にソート
            priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            strategies.sort(key=lambda s: priority_order.get(s["priority"], 3))

            return strategies

        except Exception as e:
            logger.error(f"調達戦略推奨エラー: {e}")
            return [{
                "strategy": "error",
                "priority": "HIGH",
                "description": f"推奨生成中にエラーが発生: {e}",
                "rationale": "手動での評価を推奨します",
                "estimated_cost_impact": "不明",
            }]
