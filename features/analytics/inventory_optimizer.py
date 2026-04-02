"""在庫最適化推奨エンジン (STREAM D-3)
BOMリスク分析結果に基づき、リスク調整済み安全在庫推奨を生成。
高リスク部品には多めの安全在庫を推奨し、
在庫コスト増 vs リスク軽減効果のトレードオフ分析を提供。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import math

from config.constants import RISK_THRESHOLDS


@dataclass
class StockRecommendation:
    """在庫推奨結果"""
    part_id: str
    part_name: str
    current_risk_score: float
    recommended_safety_stock_days: int
    holding_cost_increase_pct: float
    risk_reduction_pct: float
    priority: str   # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    rationale: str

    def to_dict(self) -> dict:
        return {
            "part_id": self.part_id,
            "part_name": self.part_name,
            "current_risk_score": round(self.current_risk_score, 1),
            "recommended_safety_stock_days": self.recommended_safety_stock_days,
            "holding_cost_increase_pct": round(self.holding_cost_increase_pct, 2),
            "risk_reduction_pct": round(self.risk_reduction_pct, 1),
            "priority": self.priority,
            "rationale": self.rationale,
        }


@dataclass
class TradeoffAnalysis:
    """在庫コスト vs リスク軽減トレードオフ分析結果"""
    total_parts_analyzed: int
    critical_parts: int
    total_holding_cost_increase_pct: float
    average_risk_reduction_pct: float
    cost_per_risk_point: float
    roi_summary: str
    recommendations_by_priority: dict
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "total_parts_analyzed": self.total_parts_analyzed,
            "critical_parts": self.critical_parts,
            "total_holding_cost_increase_pct": round(
                self.total_holding_cost_increase_pct, 2
            ),
            "average_risk_reduction_pct": round(
                self.average_risk_reduction_pct, 1
            ),
            "cost_per_risk_point": round(self.cost_per_risk_point, 4),
            "roi_summary": self.roi_summary,
            "recommendations_by_priority": self.recommendations_by_priority,
            "timestamp": self.timestamp,
        }


# サービスレベル → Z値テーブル (正規分布近似)
SERVICE_LEVEL_Z = {
    0.90: 1.28,
    0.95: 1.65,
    0.97: 1.88,
    0.98: 2.05,
    0.99: 2.33,
    0.995: 2.58,
}

# リスクスコア → 安全在庫倍率
RISK_MULTIPLIER_TABLE = {
    "CRITICAL": 2.5,   # リスク80+ → 2.5倍の安全在庫
    "HIGH": 2.0,       # リスク60-79 → 2.0倍
    "MEDIUM": 1.5,     # リスク40-59 → 1.5倍
    "LOW": 1.0,        # リスク20-39 → 1.0倍 (標準)
    "MINIMAL": 0.7,    # リスク0-19 → 0.7倍 (削減可能)
}


class InventoryOptimizer:
    """在庫最適化推奨エンジン

    BOMリスク分析結果に基づき、部品ごとのリスク調整済み安全在庫を推奨。
    """

    def recommend_safety_stock(
        self,
        bom_result: dict,
        service_level: float = 0.95,
        avg_daily_demand: float = 100.0,
        current_safety_stock_days: float = 14.0,
    ) -> list[StockRecommendation]:
        """リスク調整済み安全在庫推奨を生成。

        高リスク部品にはより多くの安全在庫を推奨し、
        低リスク部品には在庫削減の余地を示す。

        Args:
            bom_result: BOMRiskResult.to_dict() の結果
            service_level: 目標サービスレベル (0.90-0.995)
            avg_daily_demand: 平均日次需要量
            current_safety_stock_days: 現在の安全在庫日数

        Returns:
            部品ごとの StockRecommendation リスト (優先度順)
        """
        try:
            if not bom_result or not isinstance(bom_result, dict):
                return []

            part_risks = bom_result.get("part_risks", [])
            if not part_risks:
                return []

            # Z値取得
            z_value = self._get_z_value(service_level)

            # 推奨リスト
            recommendations: list[StockRecommendation] = []

            for part in part_risks:
                if part.get("is_inferred"):
                    continue  # 推定部品はスキップ

                part_id = part.get("part_id", "unknown")
                part_name = part.get("part_name", "unknown")
                risk_score = part.get("risk_score", 0)
                cost_weight = part.get("cost_weight", 0)
                is_critical = part.get("is_critical", False)
                supplier_country = part.get("supplier_country", "")

                # リスクレベル判定
                risk_level = self._get_risk_level(risk_score)

                # 優先度判定 (is_critical指定がある場合はCRITICALに昇格)
                priority = risk_level
                if is_critical and priority not in ("CRITICAL",):
                    priority = "CRITICAL" if risk_score >= 40 else "HIGH"

                # リスク倍率
                risk_multiplier = RISK_MULTIPLIER_TABLE.get(risk_level, 1.0)
                if is_critical:
                    risk_multiplier = max(risk_multiplier, 2.0)

                # 推奨安全在庫日数
                base_days = current_safety_stock_days * z_value / 1.65  # 95%基準で正規化
                recommended_days = max(1, int(base_days * risk_multiplier))

                # 在庫コスト増加率
                if current_safety_stock_days > 0:
                    holding_increase = (
                        (recommended_days - current_safety_stock_days)
                        / current_safety_stock_days
                    ) * cost_weight * 100
                else:
                    holding_increase = recommended_days * cost_weight * 100

                # リスク軽減効果
                risk_reduction = self._estimate_risk_reduction(
                    risk_score, recommended_days, current_safety_stock_days
                )

                # 根拠テキスト
                rationale = self._build_rationale(
                    part_name, supplier_country, risk_score, risk_level,
                    is_critical, recommended_days, current_safety_stock_days,
                )

                recommendations.append(StockRecommendation(
                    part_id=part_id,
                    part_name=part_name,
                    current_risk_score=risk_score,
                    recommended_safety_stock_days=recommended_days,
                    holding_cost_increase_pct=holding_increase,
                    risk_reduction_pct=risk_reduction,
                    priority=priority,
                    rationale=rationale,
                ))

            # 優先度順にソート
            priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "MINIMAL": 4}
            recommendations.sort(
                key=lambda r: (
                    priority_order.get(r.priority, 5),
                    -r.current_risk_score,
                )
            )

            return recommendations

        except Exception as e:
            return [StockRecommendation(
                part_id="error",
                part_name="Error",
                current_risk_score=0,
                recommended_safety_stock_days=0,
                holding_cost_increase_pct=0,
                risk_reduction_pct=0,
                priority="LOW",
                rationale=f"推奨生成中にエラーが発生: {str(e)}",
            )]

    def calculate_tradeoff(
        self,
        recommendations: list[StockRecommendation],
        holding_cost_pct: float = 0.25,
    ) -> dict:
        """在庫コスト増 vs リスク軽減効果のトレードオフ分析。

        Args:
            recommendations: recommend_safety_stock() の結果
            holding_cost_pct: 年間在庫保有コスト率 (デフォルト25%)

        Returns:
            TradeoffAnalysis.to_dict()
        """
        try:
            if not recommendations:
                return TradeoffAnalysis(
                    total_parts_analyzed=0,
                    critical_parts=0,
                    total_holding_cost_increase_pct=0,
                    average_risk_reduction_pct=0,
                    cost_per_risk_point=0,
                    roi_summary="分析対象部品なし",
                    recommendations_by_priority={},
                    timestamp=datetime.utcnow().isoformat(),
                ).to_dict()

            # 優先度別集計
            by_priority: dict[str, list] = {}
            for rec in recommendations:
                if rec.priority not in by_priority:
                    by_priority[rec.priority] = []
                by_priority[rec.priority].append(rec)

            # 全体集計
            total_holding_increase = sum(
                r.holding_cost_increase_pct for r in recommendations
            )
            risk_reductions = [
                r.risk_reduction_pct for r in recommendations
                if r.risk_reduction_pct > 0
            ]
            avg_risk_reduction = (
                sum(risk_reductions) / len(risk_reductions)
                if risk_reductions else 0
            )

            critical_count = len(by_priority.get("CRITICAL", []))

            # コスト/リスクポイント
            cost_per_risk = (
                (total_holding_increase * holding_cost_pct)
                / max(1, avg_risk_reduction)
            )

            # 優先度別サマリ
            priority_summary = {}
            for priority, recs in by_priority.items():
                priority_summary[priority] = {
                    "count": len(recs),
                    "avg_safety_stock_days": round(
                        sum(r.recommended_safety_stock_days for r in recs)
                        / max(1, len(recs)),
                        1,
                    ),
                    "avg_risk_reduction_pct": round(
                        sum(r.risk_reduction_pct for r in recs)
                        / max(1, len(recs)),
                        1,
                    ),
                    "total_holding_cost_increase_pct": round(
                        sum(r.holding_cost_increase_pct for r in recs), 2
                    ),
                    "parts": [r.part_name for r in recs],
                }

            # ROIサマリ
            if avg_risk_reduction > 0 and total_holding_increase > 0:
                ratio = avg_risk_reduction / (total_holding_increase * holding_cost_pct)
                if ratio > 2:
                    roi_summary = (
                        f"高ROI: 在庫コスト{total_holding_increase:.1f}%増で"
                        f"平均{avg_risk_reduction:.1f}%のリスク軽減。強く推奨。"
                    )
                elif ratio > 1:
                    roi_summary = (
                        f"良好なROI: 在庫コスト{total_holding_increase:.1f}%増で"
                        f"平均{avg_risk_reduction:.1f}%のリスク軽減。推奨。"
                    )
                else:
                    roi_summary = (
                        f"限定的なROI: 在庫コスト{total_holding_increase:.1f}%増で"
                        f"平均{avg_risk_reduction:.1f}%のリスク軽減。"
                        "CRITICAL部品のみの実施を推奨。"
                    )
            else:
                roi_summary = "在庫増加なし、または追加のリスク軽減効果なし。"

            return TradeoffAnalysis(
                total_parts_analyzed=len(recommendations),
                critical_parts=critical_count,
                total_holding_cost_increase_pct=total_holding_increase,
                average_risk_reduction_pct=avg_risk_reduction,
                cost_per_risk_point=cost_per_risk,
                roi_summary=roi_summary,
                recommendations_by_priority=priority_summary,
                timestamp=datetime.utcnow().isoformat(),
            ).to_dict()

        except Exception as e:
            return {
                "error": str(e),
                "total_parts_analyzed": 0,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def _get_z_value(self, service_level: float) -> float:
        """サービスレベルからZ値を取得"""
        if service_level in SERVICE_LEVEL_Z:
            return SERVICE_LEVEL_Z[service_level]

        # 最も近い値を選択
        closest = min(
            SERVICE_LEVEL_Z.keys(),
            key=lambda k: abs(k - service_level),
        )
        return SERVICE_LEVEL_Z[closest]

    def _get_risk_level(self, score: float) -> str:
        """リスクスコアからリスクレベルを判定"""
        if score >= RISK_THRESHOLDS["CRITICAL"]:
            return "CRITICAL"
        if score >= RISK_THRESHOLDS["HIGH"]:
            return "HIGH"
        if score >= RISK_THRESHOLDS["MEDIUM"]:
            return "MEDIUM"
        if score >= RISK_THRESHOLDS["LOW"]:
            return "LOW"
        return "MINIMAL"

    def _estimate_risk_reduction(
        self,
        risk_score: float,
        recommended_days: int,
        current_days: float,
    ) -> float:
        """安全在庫増加によるリスク軽減効果を推定。

        在庫バッファが増えることで、途絶時の影響を吸収できる割合。
        """
        if current_days <= 0:
            current_days = 1

        # バッファ増加率
        buffer_increase_ratio = recommended_days / current_days

        if buffer_increase_ratio <= 1.0:
            return 0.0  # 増加なし

        # リスク軽減は対数的に効く (収穫逓減)
        # 2倍のバッファ → 約30%のリスク軽減
        # 3倍のバッファ → 約45%のリスク軽減
        base_reduction = min(60, math.log2(buffer_increase_ratio) * 30)

        # リスクスコアが高いほど軽減効果も大きい
        risk_factor = risk_score / 100.0
        reduction = base_reduction * (0.5 + risk_factor * 0.5)

        return min(60, max(0, reduction))

    def _build_rationale(
        self,
        part_name: str,
        country: str,
        risk_score: float,
        risk_level: str,
        is_critical: bool,
        recommended_days: int,
        current_days: float,
    ) -> str:
        """推奨根拠テキストを生成"""
        reasons = []

        if is_critical:
            reasons.append("クリティカル部品指定")
        if risk_score >= 60:
            reasons.append(f"高リスクスコア({risk_score:.0f})")
        if country:
            reasons.append(f"調達国: {country}")

        if recommended_days > current_days:
            delta = recommended_days - current_days
            reasons.append(
                f"安全在庫を{current_days:.0f}日→{recommended_days}日に"
                f"+{delta:.0f}日増加推奨"
            )
        elif recommended_days < current_days:
            delta = current_days - recommended_days
            reasons.append(
                f"安全在庫を{current_days:.0f}日→{recommended_days}日に"
                f"-{delta:.0f}日削減可能"
            )
        else:
            reasons.append(f"現在の安全在庫{current_days:.0f}日を維持")

        return f"{part_name}: {'; '.join(reasons)}"
