"""サプライヤー多様化シミュレータ (STREAM D-4)
現在のサプライヤー構成と代替候補を入力し、
リスク・コスト・移行期間の最適バランスをシミュレーション。
最適分割比率の算出と段階的移行計画を生成。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import math

from config.constants import RISK_THRESHOLDS


@dataclass
class DiversificationResult:
    """多様化シミュレーション結果"""
    risk_before: float
    risk_after: float
    risk_improvement_pct: float
    cost_delta_pct: float
    transition_time_months: int
    recommended_split: dict   # {supplier_name: share}
    feasibility: str          # "FEASIBLE", "CHALLENGING", "NOT_RECOMMENDED"
    rationale: str

    def to_dict(self) -> dict:
        return {
            "risk_before": round(self.risk_before, 1),
            "risk_after": round(self.risk_after, 1),
            "risk_improvement_pct": round(self.risk_improvement_pct, 1),
            "cost_delta_pct": round(self.cost_delta_pct, 2),
            "transition_time_months": self.transition_time_months,
            "recommended_split": {
                k: round(v, 3) for k, v in self.recommended_split.items()
            },
            "feasibility": self.feasibility,
            "rationale": self.rationale,
        }


@dataclass
class TransitionMilestone:
    """移行計画マイルストーン"""
    phase: int
    description: str
    duration_months: int
    target_split: dict
    risk_at_phase: float
    actions: list[str]

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "description": self.description,
            "duration_months": self.duration_months,
            "target_split": {
                k: round(v, 3) for k, v in self.target_split.items()
            },
            "risk_at_phase": round(self.risk_at_phase, 1),
            "actions": self.actions,
        }


# 国別リスクベースライン（簡易。scoring/engine.py のフル評価を使わない場合の代替）
_COUNTRY_RISK_BASELINE = {
    "Japan": 25, "Germany": 20, "United States": 22,
    "South Korea": 28, "Taiwan": 45, "China": 55,
    "Vietnam": 40, "India": 42, "Thailand": 35,
    "Mexico": 38, "Indonesia": 42, "Malaysia": 30,
    "Singapore": 15, "Netherlands": 18, "Switzerland": 12,
    "Bangladesh": 55, "Myanmar": 75, "Russia": 80,
    "Iran": 90, "North Korea": 100,
}

# 移行期間の推定ベース（月数）
TRANSITION_BASE_MONTHS = {
    "same_region": 6,       # 同一地域内の切替
    "cross_region": 12,     # 異なる地域への切替
    "new_capability": 18,   # 新規能力構築が必要
}


class DiversificationSimulator:
    """サプライヤー多様化シミュレータ

    現在のサプライヤー構成から代替候補への移行をシミュレートし、
    リスク・コスト・移行期間のトレードオフを分析。
    """

    def simulate_supplier_change(
        self,
        current_supplier: dict,
        alternative_suppliers: list[dict],
        cost_constraint: float = 1.1,
    ) -> DiversificationResult:
        """サプライヤー変更のシミュレーション。

        Args:
            current_supplier: {
                "name": str, "country": str,
                "cost": float, "share": float (0-1)
            }
            alternative_suppliers: [{
                "name": str, "country": str,
                "cost": float, "quality_score": float (0-100)
            }, ...]
            cost_constraint: コスト上限倍率 (1.1 = 10%増まで許容)

        Returns:
            DiversificationResult
        """
        try:
            # 現在のリスク
            current_risk = self._get_country_risk(
                current_supplier.get("country", "")
            )
            current_cost = current_supplier.get("cost", 1.0)
            current_share = current_supplier.get("share", 1.0)
            current_name = current_supplier.get("name", "Current")

            if not alternative_suppliers:
                return DiversificationResult(
                    risk_before=current_risk,
                    risk_after=current_risk,
                    risk_improvement_pct=0,
                    cost_delta_pct=0,
                    transition_time_months=0,
                    recommended_split={current_name: 1.0},
                    feasibility="NOT_RECOMMENDED",
                    rationale="代替サプライヤー候補が指定されていません。",
                )

            # 全サプライヤー情報の収集
            all_suppliers = [{
                "name": current_name,
                "country": current_supplier.get("country", ""),
                "cost": current_cost,
                "quality_score": 80,  # 既存 = ベンチマーク品質
                "risk_score": current_risk,
                "is_current": True,
            }]

            for alt in alternative_suppliers:
                alt_risk = self._get_country_risk(alt.get("country", ""))
                all_suppliers.append({
                    "name": alt.get("name", "Unknown"),
                    "country": alt.get("country", ""),
                    "cost": alt.get("cost", current_cost),
                    "quality_score": alt.get("quality_score", 70),
                    "risk_score": alt_risk,
                    "is_current": False,
                })

            # 最適分割の探索
            optimal_split = self.find_optimal_split(
                all_suppliers,
                risk_weight=0.6,
                cost_weight=0.4,
            )

            # シミュレーション後のリスク・コスト算出
            risk_after = 0
            cost_after = 0
            for supplier in all_suppliers:
                share = optimal_split.get(supplier["name"], 0)
                risk_after += supplier["risk_score"] * share
                cost_after += supplier["cost"] * share

            cost_delta_pct = (
                (cost_after - current_cost) / current_cost * 100
                if current_cost > 0 else 0
            )

            # コスト制約チェック
            if cost_after > current_cost * cost_constraint:
                # コスト制約超過 → 制約内で再最適化
                constrained_split = self._constrained_optimization(
                    all_suppliers, current_cost, cost_constraint
                )
                optimal_split = constrained_split

                # 再計算
                risk_after = sum(
                    s["risk_score"] * constrained_split.get(s["name"], 0)
                    for s in all_suppliers
                )
                cost_after = sum(
                    s["cost"] * constrained_split.get(s["name"], 0)
                    for s in all_suppliers
                )
                cost_delta_pct = (
                    (cost_after - current_cost) / current_cost * 100
                    if current_cost > 0 else 0
                )

            risk_improvement = (
                (current_risk - risk_after) / current_risk * 100
                if current_risk > 0 else 0
            )

            # 移行期間の推定
            transition_months = self._estimate_transition_time(
                current_supplier, alternative_suppliers
            )

            # 実現可能性判定
            feasibility = self._assess_feasibility(
                risk_improvement, cost_delta_pct, transition_months,
                alternative_suppliers,
            )

            # 根拠テキスト
            rationale = self._build_rationale(
                current_risk, risk_after, risk_improvement,
                cost_delta_pct, transition_months, feasibility,
            )

            return DiversificationResult(
                risk_before=current_risk,
                risk_after=risk_after,
                risk_improvement_pct=risk_improvement,
                cost_delta_pct=cost_delta_pct,
                transition_time_months=transition_months,
                recommended_split=optimal_split,
                feasibility=feasibility,
                rationale=rationale,
            )

        except Exception as e:
            return DiversificationResult(
                risk_before=0,
                risk_after=0,
                risk_improvement_pct=0,
                cost_delta_pct=0,
                transition_time_months=0,
                recommended_split={},
                feasibility="NOT_RECOMMENDED",
                rationale=f"シミュレーション中にエラーが発生: {str(e)}",
            )

    def find_optimal_split(
        self,
        suppliers: list[dict],
        risk_weight: float = 0.6,
        cost_weight: float = 0.4,
    ) -> dict:
        """リスクとコストを加重最小化する最適分割比率を算出。

        Args:
            suppliers: [{
                "name": str, "cost": float,
                "risk_score": float, "quality_score": float
            }, ...]
            risk_weight: リスク最小化の重み (0-1)
            cost_weight: コスト最小化の重み (0-1)

        Returns:
            {supplier_name: share} (合計 = 1.0)
        """
        try:
            if not suppliers:
                return {}

            if len(suppliers) == 1:
                return {suppliers[0]["name"]: 1.0}

            # 正規化
            total_weight = risk_weight + cost_weight
            risk_w = risk_weight / total_weight
            cost_w = cost_weight / total_weight

            # 各サプライヤーの統合スコア算出 (低い = 良い)
            max_cost = max(s.get("cost", 1) for s in suppliers) or 1
            max_risk = max(s.get("risk_score", 1) for s in suppliers) or 1

            scores = {}
            for s in suppliers:
                name = s["name"]
                # リスクと コストを正規化 (0-1)
                norm_risk = s.get("risk_score", 50) / max_risk
                norm_cost = s.get("cost", 1) / max_cost

                # 品質ボーナス (品質が高いほどスコア改善)
                quality_bonus = (s.get("quality_score", 70) - 50) / 100.0

                # 統合スコア (低い = 良い)
                combined = (
                    norm_risk * risk_w
                    + norm_cost * cost_w
                    - quality_bonus * 0.1
                )
                scores[name] = max(0.01, combined)  # ゼロ除算防止

            # 逆数比例配分 (スコアが低いサプライヤーに多く配分)
            inv_scores = {name: 1.0 / score for name, score in scores.items()}
            total_inv = sum(inv_scores.values())

            optimal = {
                name: inv / total_inv
                for name, inv in inv_scores.items()
            }

            # 最小シェア制約: 5%未満の配分は実用的でないため除外
            filtered = {
                name: share for name, share in optimal.items()
                if share >= 0.05
            }

            if not filtered:
                # フィルタで全部消えた場合はトップ2を選択
                sorted_scores = sorted(scores.items(), key=lambda x: x[1])
                top2 = sorted_scores[:2]
                total_inv = sum(1.0 / s[1] for s in top2)
                filtered = {
                    name: (1.0 / score) / total_inv
                    for name, score in top2
                }

            # 再正規化
            total = sum(filtered.values())
            return {name: share / total for name, share in filtered.items()}

        except Exception:
            if suppliers:
                equal_share = 1.0 / len(suppliers)
                return {s["name"]: equal_share for s in suppliers}
            return {}

    def generate_transition_plan(
        self,
        result: DiversificationResult,
    ) -> list[dict]:
        """段階的移行計画をマイルストーン付きで生成。

        Args:
            result: simulate_supplier_change() の結果

        Returns:
            移行フェーズリスト [TransitionMilestone.to_dict(), ...]
        """
        try:
            if result.feasibility == "NOT_RECOMMENDED":
                return [{
                    "phase": 0,
                    "description": "移行非推奨",
                    "duration_months": 0,
                    "target_split": result.recommended_split,
                    "risk_at_phase": result.risk_before,
                    "actions": [result.rationale],
                }]

            total_months = result.transition_time_months
            recommended = result.recommended_split

            # 現在のサプライヤーを特定（最大シェア保持者）
            current_suppliers = {
                name for name, share in recommended.items()
                if share < 0.95  # 95%未満 = 移行先あり
            }
            new_suppliers = {
                name for name in recommended.keys()
                if name not in current_suppliers
            }

            # 3フェーズに分割
            phases = []

            # Phase 1: 準備・検証 (全体の30%)
            phase1_months = max(1, int(total_months * 0.3))
            phase1_split = {}
            for name, target_share in recommended.items():
                if name in current_suppliers or target_share > 0.5:
                    # 現行サプライヤーは90%維持
                    phase1_split[name] = max(target_share, 0.9)
                else:
                    # 新規サプライヤーは10%でテスト
                    phase1_split[name] = min(target_share, 0.10)

            # 正規化
            total = sum(phase1_split.values()) or 1
            phase1_split = {k: v / total for k, v in phase1_split.items()}

            phase1_risk = sum(
                result.risk_before * s if s > 0.5 else result.risk_after * s
                for s in phase1_split.values()
            )

            phases.append(TransitionMilestone(
                phase=1,
                description="準備・検証フェーズ: 新規サプライヤーの品質検証とパイロット発注",
                duration_months=phase1_months,
                target_split=phase1_split,
                risk_at_phase=min(100, phase1_risk),
                actions=[
                    "新規サプライヤーの品質監査実施",
                    "少量パイロット発注で品質確認",
                    "物流ルートの確認とリードタイム測定",
                    "契約条件の交渉",
                ],
            ).to_dict())

            # Phase 2: 段階的移行 (全体の40%)
            phase2_months = max(1, int(total_months * 0.4))
            phase2_split = {}
            for name, target_share in recommended.items():
                # 最終目標の70%まで移行
                current_share = phase1_split.get(name, 0)
                phase2_split[name] = current_share + (target_share - current_share) * 0.7

            total = sum(phase2_split.values()) or 1
            phase2_split = {k: v / total for k, v in phase2_split.items()}

            phase2_risk = result.risk_before * 0.4 + result.risk_after * 0.6

            phases.append(TransitionMilestone(
                phase=2,
                description="段階的移行フェーズ: 発注比率を目標値の70%まで移行",
                duration_months=phase2_months,
                target_split=phase2_split,
                risk_at_phase=min(100, phase2_risk),
                actions=[
                    "発注比率を段階的に変更",
                    "品質KPIの継続モニタリング",
                    "在庫バッファの調整",
                    "サプライチェーンリスクの再評価",
                ],
            ).to_dict())

            # Phase 3: 完了・安定化 (全体の30%)
            phase3_months = max(1, total_months - phase1_months - phase2_months)

            phases.append(TransitionMilestone(
                phase=3,
                description="完了・安定化フェーズ: 最終目標比率への到達と安定運用",
                duration_months=phase3_months,
                target_split=recommended,
                risk_at_phase=result.risk_after,
                actions=[
                    "最終目標比率への調整",
                    "BCP(事業継続計画)の更新",
                    "定期的なサプライヤー評価体制の構築",
                    "コスト・品質・リスクの最終レビュー",
                ],
            ).to_dict())

            return phases

        except Exception as e:
            return [{
                "phase": 0,
                "description": f"移行計画生成中にエラー: {str(e)}",
                "duration_months": 0,
                "target_split": {},
                "risk_at_phase": 0,
                "actions": [],
            }]

    def _get_country_risk(self, country: str) -> float:
        """国リスクスコアを取得。

        scoring/engine.py のフル評価を試み、失敗時はベースラインを使用。
        """
        try:
            from scoring.engine import calculate_risk_score
            result = calculate_risk_score(
                f"div_sim_{country.lower().replace(' ', '_')}",
                f"DivSim: {country}",
                country=country,
                location=country,
            )
            return result.overall_score
        except Exception:
            # ベースラインフォールバック
            for c, risk in _COUNTRY_RISK_BASELINE.items():
                if c.lower() == country.lower():
                    return risk
            return 40  # デフォルトリスク

    def _estimate_transition_time(
        self,
        current: dict,
        alternatives: list[dict],
    ) -> int:
        """移行期間を推定。

        同一地域内 vs 異地域、サプライヤー数で期間を調整。
        """
        current_country = current.get("country", "")
        alt_countries = [a.get("country", "") for a in alternatives]

        # 地域判定（簡易）
        asia = {"Japan", "China", "Taiwan", "South Korea", "Vietnam",
                "Thailand", "Malaysia", "Singapore", "Indonesia",
                "Philippines", "India", "Bangladesh", "Myanmar", "Cambodia"}
        europe = {"Germany", "France", "United Kingdom", "Italy", "Spain",
                  "Netherlands", "Poland", "Switzerland", "Sweden", "Austria"}
        americas = {"United States", "Mexico", "Canada", "Brazil",
                    "Argentina", "Chile", "Colombia"}

        def get_region(c):
            if c in asia:
                return "asia"
            if c in europe:
                return "europe"
            if c in americas:
                return "americas"
            return "other"

        current_region = get_region(current_country)
        base_months = TRANSITION_BASE_MONTHS["same_region"]

        for alt_country in alt_countries:
            alt_region = get_region(alt_country)
            if alt_region != current_region:
                base_months = max(
                    base_months,
                    TRANSITION_BASE_MONTHS["cross_region"],
                )

        # サプライヤー数による調整
        if len(alternatives) > 3:
            base_months += 3  # 多数サプライヤーの管理コスト

        return base_months

    def _constrained_optimization(
        self,
        suppliers: list[dict],
        current_cost: float,
        cost_constraint: float,
    ) -> dict:
        """コスト制約内での最適化。

        コスト制約を満たしつつリスクを最小化する分割を探索。
        """
        # 単純なヒューリスティック: コストの安い順にリスク加重配分
        sorted_by_cost = sorted(suppliers, key=lambda s: s.get("cost", 0))

        max_cost = current_cost * cost_constraint
        result = {}
        remaining = 1.0

        for s in sorted_by_cost:
            if remaining <= 0:
                break
            name = s["name"]
            cost = s.get("cost", current_cost)
            risk = s.get("risk_score", 50)

            # リスクが低いほど多く配分
            ideal_share = max(0.1, 1.0 - risk / 100.0) * 0.5
            actual_share = min(remaining, ideal_share)

            # コストチェック
            if cost * actual_share <= max_cost * actual_share:
                result[name] = actual_share
                remaining -= actual_share

        if remaining > 0 and result:
            # 残りを最初のサプライヤーに配分
            first = list(result.keys())[0]
            result[first] += remaining

        if not result and suppliers:
            result = {suppliers[0]["name"]: 1.0}

        # 正規化
        total = sum(result.values()) or 1
        return {k: v / total for k, v in result.items()}

    def _assess_feasibility(
        self,
        risk_improvement: float,
        cost_delta: float,
        transition_months: int,
        alternatives: list[dict],
    ) -> str:
        """実現可能性を判定"""
        if risk_improvement <= 0:
            return "NOT_RECOMMENDED"

        if risk_improvement >= 20 and cost_delta <= 10 and transition_months <= 12:
            return "FEASIBLE"
        elif risk_improvement >= 10 and cost_delta <= 20:
            return "FEASIBLE"
        elif risk_improvement >= 5:
            return "CHALLENGING"
        else:
            return "NOT_RECOMMENDED"

    def _build_rationale(
        self,
        risk_before: float,
        risk_after: float,
        improvement: float,
        cost_delta: float,
        months: int,
        feasibility: str,
    ) -> str:
        """根拠テキストを生成"""
        parts = [
            f"リスクスコア: {risk_before:.0f} → {risk_after:.0f} "
            f"({improvement:+.1f}%改善)",
        ]

        if cost_delta > 0:
            parts.append(f"コスト: +{cost_delta:.1f}%増")
        elif cost_delta < 0:
            parts.append(f"コスト: {cost_delta:.1f}%減")
        else:
            parts.append("コスト: 変動なし")

        parts.append(f"移行期間: 約{months}ヶ月")

        if feasibility == "FEASIBLE":
            parts.append("判定: 実行推奨。リスク軽減効果がコスト増を十分に上回ります。")
        elif feasibility == "CHALLENGING":
            parts.append(
                "判定: 実行可能だが課題あり。"
                "段階的な移行と綿密なモニタリングが必要です。"
            )
        else:
            parts.append(
                "判定: 現時点では非推奨。"
                "リスク軽減効果がコスト・移行負荷に見合いません。"
            )

        return " | ".join(parts)
