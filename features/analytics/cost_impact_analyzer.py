"""コスト影響試算エンジン — STREAM 5-A
サプライチェーン途絶シナリオごとの財務インパクトを試算。
調達プレミアム・物流追加コスト・生産損失・復旧コストの4要素で算出。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import math


# 通貨換算レート (USD基準)
CURRENCY_RATES = {
    "USD": 1.0,
    "JPY": 150.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "CNY": 7.25,
    "KRW": 1350.0,
    "TWD": 32.0,
    "CHF": 0.88,
}

# 途絶シナリオ定義
DISRUPTION_SCENARIOS = {
    "sanctions": {
        "name": "制裁・輸出規制",
        "description": "対象国/企業への制裁発動による調達停止",
        "base_cost_multiplier": 0.50,  # 調達コスト50%増
        "logistics_multiplier": 0.30,  # 物流コスト30%増
        "production_loss_rate": 0.40,  # 生産能力40%低下
        "recovery_days": 180,
        "probability_base": 0.15,
    },
    "conflict": {
        "name": "武力紛争・地政学危機",
        "description": "紛争による輸送路遮断、工場操業停止",
        "base_cost_multiplier": 0.35,
        "logistics_multiplier": 0.50,
        "production_loss_rate": 0.30,
        "recovery_days": 120,
        "probability_base": 0.10,
    },
    "disaster": {
        "name": "自然災害",
        "description": "地震・洪水・台風によるサプライヤー被災",
        "base_cost_multiplier": 0.25,
        "logistics_multiplier": 0.20,
        "production_loss_rate": 0.25,
        "recovery_days": 90,
        "probability_base": 0.20,
    },
    "port_closure": {
        "name": "港湾閉鎖・チョークポイント封鎖",
        "description": "主要港湾/海峡の封鎖による物流途絶",
        "base_cost_multiplier": 0.10,
        "logistics_multiplier": 0.60,
        "production_loss_rate": 0.15,
        "recovery_days": 60,
        "probability_base": 0.12,
    },
    "pandemic": {
        "name": "パンデミック・感染症",
        "description": "感染症拡大によるロックダウン・操業停止",
        "base_cost_multiplier": 0.20,
        "logistics_multiplier": 0.40,
        "production_loss_rate": 0.35,
        "recovery_days": 150,
        "probability_base": 0.08,
    },
}


@dataclass
class CostBreakdown:
    """コスト内訳"""
    sourcing_premium: float = 0.0      # 調達プレミアム (代替調達先の割増)
    logistics_extra: float = 0.0       # 物流追加コスト (迂回・緊急輸送)
    production_loss: float = 0.0       # 生産損失 (操業停止による逸失利益)
    recovery_cost: float = 0.0         # 復旧コスト (サプライチェーン再構築)
    total: float = 0.0

    def to_dict(self) -> dict:
        return {
            "sourcing_premium_usd": round(self.sourcing_premium, 2),
            "logistics_extra_usd": round(self.logistics_extra, 2),
            "production_loss_usd": round(self.production_loss, 2),
            "recovery_cost_usd": round(self.recovery_cost, 2),
            "total_impact_usd": round(self.total, 2),
        }


@dataclass
class DisruptionCostResult:
    """途絶コスト試算結果"""
    scenario: str
    scenario_name: str
    duration_days: int
    annual_spend_usd: float
    daily_revenue_usd: float
    cost_breakdown: CostBreakdown
    risk_adjusted_cost: float  # probability × total cost
    probability: float
    affected_countries: list[str]
    timestamp: str

    def to_dict(self) -> dict:
        d = {
            "scenario": self.scenario,
            "scenario_name": self.scenario_name,
            "duration_days": self.duration_days,
            "annual_spend_usd": round(self.annual_spend_usd, 2),
            "daily_revenue_usd": round(self.daily_revenue_usd, 2),
            "cost_breakdown": self.cost_breakdown.to_dict(),
            "risk_adjusted_cost_usd": round(self.risk_adjusted_cost, 2),
            "probability": round(self.probability, 3),
            "affected_countries": self.affected_countries,
            "timestamp": self.timestamp,
        }
        if hasattr(self, "_output_currency") and self._output_currency != "USD":
            d["output_currency"] = self._output_currency
        return d


class CostImpactAnalyzer:
    """コスト影響試算エンジン"""

    def estimate_disruption_cost(
        self,
        scenario: str,
        annual_spend_usd: float = 1_000_000,
        daily_revenue_usd: float = 100_000,
        duration_days: int = 60,
        affected_countries: list[str] = None,
        risk_score: float = 50.0,
        output_currency: str = "USD",
    ) -> DisruptionCostResult:
        """途絶シナリオのコスト試算

        Args:
            scenario: シナリオ名 (sanctions/conflict/disaster/port_closure/pandemic)
            annual_spend_usd: 対象サプライヤーからの年間調達額 (USD)
            daily_revenue_usd: 1日あたりの売上高 (USD)
            duration_days: 途絶期間 (日数)
            affected_countries: 影響を受ける国リスト
            risk_score: 対象国/サプライヤーのリスクスコア (0-100)
            output_currency: 出力通貨コード (デフォルト USD)。CURRENCY_RATES に定義された通貨のみ対応。

        Returns:
            DisruptionCostResult
        """
        if scenario not in DISRUPTION_SCENARIOS:
            raise ValueError(
                f"Unknown scenario: {scenario}. "
                f"Available: {', '.join(DISRUPTION_SCENARIOS.keys())}"
            )

        params = DISRUPTION_SCENARIOS[scenario]

        # リスクスコアによる確率調整
        risk_factor = risk_score / 100.0
        probability = min(0.95, params["probability_base"] * (1 + risk_factor * 2))

        # 期間調整係数 (長期途絶はコスト加速)
        duration_factor = 1.0 + math.log2(max(1, duration_days / 30))

        # 1. 調達プレミアム
        daily_spend = annual_spend_usd / 365
        sourcing_premium = (
            daily_spend
            * params["base_cost_multiplier"]
            * duration_days
            * duration_factor
        )

        # 2. 物流追加コスト
        logistics_extra = (
            daily_spend
            * params["logistics_multiplier"]
            * duration_days
        )

        # 3. 生産損失
        production_loss = (
            daily_revenue_usd
            * params["production_loss_rate"]
            * duration_days
        )

        # 4. 復旧コスト (サプライチェーン再構築)
        recovery_days = params["recovery_days"]
        recovery_cost = daily_spend * 0.1 * recovery_days  # 10% of daily spend × recovery period

        total = sourcing_premium + logistics_extra + production_loss + recovery_cost

        breakdown = CostBreakdown(
            sourcing_premium=sourcing_premium,
            logistics_extra=logistics_extra,
            production_loss=production_loss,
            recovery_cost=recovery_cost,
            total=total,
        )

        # 通貨換算
        fx_rate = CURRENCY_RATES.get(output_currency, 1.0)
        if output_currency != "USD" and fx_rate != 1.0:
            breakdown = CostBreakdown(
                sourcing_premium=sourcing_premium * fx_rate,
                logistics_extra=logistics_extra * fx_rate,
                production_loss=production_loss * fx_rate,
                recovery_cost=recovery_cost * fx_rate,
                total=total * fx_rate,
            )
            risk_adjusted = total * probability * fx_rate
        else:
            risk_adjusted = total * probability

        result = DisruptionCostResult(
            scenario=scenario,
            scenario_name=params["name"],
            duration_days=duration_days,
            annual_spend_usd=annual_spend_usd,
            daily_revenue_usd=daily_revenue_usd,
            cost_breakdown=breakdown,
            risk_adjusted_cost=risk_adjusted,
            probability=probability,
            affected_countries=affected_countries or [],
            timestamp=datetime.utcnow().isoformat(),
        )

        # 通貨ラベルを結果に追加
        result._output_currency = output_currency
        return result

    def sensitivity_analysis(
        self,
        scenario: str,
        annual_spend_usd: float = 1_000_000,
        daily_revenue_usd: float = 100_000,
        durations: list[int] = None,
        risk_score: float = 50.0,
    ) -> dict:
        """期間別感度分析

        Args:
            scenario: シナリオ名
            annual_spend_usd: 年間調達額
            daily_revenue_usd: 日次売上高
            durations: 分析する期間リスト (日数)
            risk_score: リスクスコア

        Returns:
            感度分析結果
        """
        if durations is None:
            durations = [30, 60, 90, 180]

        results = []
        for days in durations:
            cost = self.estimate_disruption_cost(
                scenario=scenario,
                annual_spend_usd=annual_spend_usd,
                daily_revenue_usd=daily_revenue_usd,
                duration_days=days,
                risk_score=risk_score,
            )
            results.append({
                "duration_days": days,
                "total_impact_usd": round(cost.cost_breakdown.total, 2),
                "risk_adjusted_usd": round(cost.risk_adjusted_cost, 2),
                "breakdown": cost.cost_breakdown.to_dict(),
            })

        return {
            "scenario": scenario,
            "scenario_name": DISRUPTION_SCENARIOS[scenario]["name"],
            "annual_spend_usd": annual_spend_usd,
            "daily_revenue_usd": daily_revenue_usd,
            "risk_score": risk_score,
            "sensitivity": results,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def compare_scenarios(
        self,
        annual_spend_usd: float = 1_000_000,
        daily_revenue_usd: float = 100_000,
        duration_days: int = 60,
        risk_score: float = 50.0,
        scenarios: list[str] = None,
        output_currency: str = "USD",
    ) -> dict:
        """全シナリオ比較

        Args:
            annual_spend_usd: 年間調達額
            daily_revenue_usd: 日次売上高
            duration_days: 途絶期間
            risk_score: リスクスコア
            scenarios: 比較するシナリオリスト (None=全シナリオ)
            output_currency: 出力通貨コード (デフォルト USD)

        Returns:
            シナリオ比較結果 (financial impact 降順)
        """
        target_scenarios = scenarios or list(DISRUPTION_SCENARIOS.keys())

        comparisons = []
        for sc in target_scenarios:
            if sc not in DISRUPTION_SCENARIOS:
                continue

            cost = self.estimate_disruption_cost(
                scenario=sc,
                annual_spend_usd=annual_spend_usd,
                daily_revenue_usd=daily_revenue_usd,
                duration_days=duration_days,
                risk_score=risk_score,
                output_currency=output_currency,
            )
            result_dict = cost.to_dict()
            if output_currency != "USD":
                result_dict["output_currency"] = output_currency
            comparisons.append(result_dict)

        # Sort by total impact descending
        comparisons.sort(
            key=lambda c: c["cost_breakdown"]["total_impact_usd"],
            reverse=True,
        )

        result = {
            "duration_days": duration_days,
            "annual_spend_usd": annual_spend_usd,
            "daily_revenue_usd": daily_revenue_usd,
            "risk_score": risk_score,
            "scenarios_compared": len(comparisons),
            "worst_case_scenario": comparisons[0]["scenario"] if comparisons else None,
            "worst_case_impact_usd": (
                comparisons[0]["cost_breakdown"]["total_impact_usd"]
                if comparisons else 0
            ),
            "comparisons": comparisons,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if output_currency != "USD":
            result["output_currency"] = output_currency
        return result

    def estimate_bom_financial_exposure(
        self,
        bom_parts: list[dict],
        scenario: str = "disaster",
        duration_days: int = 60,
    ) -> dict:
        """BOM 部品リストからの財務エクスポージャー算出

        Args:
            bom_parts: BOM 部品リスト [{"supplier_country": ..., "unit_cost_usd": ..., "quantity": ..., "risk_score": ...}]
            scenario: シナリオ名
            duration_days: 途絶期間

        Returns:
            BOM 財務エクスポージャー
        """
        if scenario not in DISRUPTION_SCENARIOS:
            scenario = "disaster"

        total_cost = sum(
            p.get("quantity", 1) * p.get("unit_cost_usd", 0)
            for p in bom_parts
        )

        country_exposures = {}
        for p in bom_parts:
            country = p.get("supplier_country", "Unknown")
            cost = p.get("quantity", 1) * p.get("unit_cost_usd", 0)
            risk = p.get("risk_score", 30)

            if country not in country_exposures:
                country_exposures[country] = {
                    "annual_spend_usd": 0,
                    "risk_score": 0,
                    "parts": 0,
                }
            country_exposures[country]["annual_spend_usd"] += cost * 12  # monthly→annual estimate
            country_exposures[country]["risk_score"] = max(
                country_exposures[country]["risk_score"], risk
            )
            country_exposures[country]["parts"] += 1

        # Calculate per-country exposure
        per_country = []
        total_exposure = 0.0

        for country, data in country_exposures.items():
            result = self.estimate_disruption_cost(
                scenario=scenario,
                annual_spend_usd=data["annual_spend_usd"],
                daily_revenue_usd=data["annual_spend_usd"] / 365 * 3,  # 3x spend as revenue proxy
                duration_days=duration_days,
                affected_countries=[country],
                risk_score=data["risk_score"],
            )

            per_country.append({
                "country": country,
                "parts_count": data["parts"],
                "annual_spend_usd": round(data["annual_spend_usd"], 2),
                "risk_score": data["risk_score"],
                "impact_usd": round(result.cost_breakdown.total, 2),
                "risk_adjusted_usd": round(result.risk_adjusted_cost, 2),
            })
            total_exposure += result.risk_adjusted_cost

        per_country.sort(key=lambda x: -x["impact_usd"])

        return {
            "scenario": scenario,
            "scenario_name": DISRUPTION_SCENARIOS[scenario]["name"],
            "duration_days": duration_days,
            "total_bom_cost_usd": round(total_cost, 2),
            "total_financial_exposure_usd": round(total_exposure, 2),
            "countries_analyzed": len(per_country),
            "highest_exposure_country": per_country[0]["country"] if per_country else None,
            "per_country": per_country,
            "timestamp": datetime.utcnow().isoformat(),
        }
