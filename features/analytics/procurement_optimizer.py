"""調達最適化エンジン (ROLE-D: D-3)
scipy.optimize を使用し、リスク×コストを最小化する
調達ポートフォリオを提案。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

try:
    from scipy.optimize import minimize, LinearConstraint
except ImportError:
    minimize = None  # type: ignore
    LinearConstraint = None  # type: ignore


@dataclass
class OptimizationResult:
    """最適化結果"""
    current_risk: float
    optimized_risk: float
    risk_improvement_pct: float
    cost_delta_pct: float
    current_allocation: dict  # {supplier: share}
    optimized_allocation: dict  # {supplier: share}
    changes: list[dict]  # 変更提案リスト
    feasible: bool
    solver_status: str

    def to_dict(self) -> dict:
        return {
            "current_risk": round(self.current_risk, 2),
            "optimized_risk": round(self.optimized_risk, 2),
            "risk_improvement_pct": round(self.risk_improvement_pct, 2),
            "cost_delta_pct": round(self.cost_delta_pct, 2),
            "current_allocation": {
                k: round(v, 4) for k, v in self.current_allocation.items()
            },
            "optimized_allocation": {
                k: round(v, 4) for k, v in self.optimized_allocation.items()
            },
            "changes": self.changes,
            "feasible": self.feasible,
            "solver_status": self.solver_status,
        }


class ProcurementOptimizer:
    """調達ポートフォリオ最適化エンジン

    BOM 分析結果を入力にして、リスクとコストのバランスを最適化する
    サプライヤー配分を提案。
    """

    # デフォルト制約
    DEFAULT_CONSTRAINTS = {
        "max_risk_increase_pct": 0.0,   # リスク増加上限（%）
        "max_cost_increase_pct": 15.0,  # コスト増加上限（%）
        "min_diversification": 2,       # 最低サプライヤー数
        "max_single_share": 0.6,        # 単一サプライヤー最大シェア
    }

    def __init__(self):
        self._risk_cache: dict[str, float] = {}

    def _get_country_risk(self, country: str) -> float:
        """国リスクスコアを取得（キャッシュ付き）"""
        if country in self._risk_cache:
            return self._risk_cache[country]
        try:
            from scoring.engine import calculate_risk_score
            result = calculate_risk_score(
                f"opt_{country.lower().replace(' ', '_')}",
                f"Optimize: {country}",
                country=country,
                location=country,
            )
            risk = float(result.overall_score)
        except Exception:
            risk = 50.0  # フォールバック
        self._risk_cache[country] = risk
        return risk

    def optimize_supplier_mix(
        self,
        current_bom: list[dict],
        constraints: Optional[dict] = None,
        alternative_suppliers: Optional[list[dict]] = None,
    ) -> dict:
        """リスク×コストを最小化する調達ポートフォリオを提案。

        Args:
            current_bom: 現在のBOM。各要素:
                {"part_id": str, "supplier_name": str, "supplier_country": str,
                 "share": float (0-1), "unit_cost_usd": float, "risk_score": float (optional)}
            constraints: 制約条件 dict
                - max_risk_increase_pct: リスク増加上限 (%)
                - max_cost_increase_pct: コスト増加上限 (%)
                - min_diversification: 最低サプライヤー数
                - max_single_share: 単一サプライヤー最大シェア (0-1)
            alternative_suppliers: 代替サプライヤー候補 (optional)
                [{"supplier_name": str, "supplier_country": str,
                  "unit_cost_usd": float, "capacity_pct": float}, ...]

        Returns:
            OptimizationResult.to_dict()
        """
        if minimize is None:
            return {
                "error": "scipy がインストールされていません。pip install scipy を実行してください。",
                "feasible": False,
            }

        cons = dict(self.DEFAULT_CONSTRAINTS)
        if constraints:
            cons.update(constraints)

        # BOM をサプライヤー単位に集約
        suppliers = self._aggregate_suppliers(current_bom)
        n = len(suppliers)

        if n == 0:
            return {"error": "BOM が空です。", "feasible": False}

        # リスクスコア取得
        risks = np.array([
            s.get("risk_score") if s.get("risk_score") is not None
            else self._get_country_risk(s["supplier_country"])
            for s in suppliers
        ], dtype=float)

        costs = np.array([s.get("unit_cost_usd", 1.0) for s in suppliers], dtype=float)
        current_shares = np.array([s["share"] for s in suppliers], dtype=float)

        # 正規化
        if current_shares.sum() > 0:
            current_shares = current_shares / current_shares.sum()

        # 代替サプライヤーがあれば追加
        alt_indices_start = n
        if alternative_suppliers:
            for alt in alternative_suppliers:
                alt_risk = self._get_country_risk(alt["supplier_country"])
                risks = np.append(risks, alt_risk)
                costs = np.append(costs, alt.get("unit_cost_usd", costs.mean()))
                current_shares = np.append(current_shares, 0.0)
                suppliers.append({
                    "supplier_name": alt["supplier_name"],
                    "supplier_country": alt["supplier_country"],
                    "unit_cost_usd": alt.get("unit_cost_usd", costs.mean()),
                    "share": 0.0,
                    "is_alternative": True,
                })
            n = len(suppliers)

        # 現在のリスクとコスト
        current_risk = float(np.dot(current_shares, risks))
        current_cost = float(np.dot(current_shares, costs))

        # 目的関数: リスク加重合計の最小化（コスト増制約付き）
        # risk_weight = 0.7, cost_weight = 0.3 でバランス
        cost_norm = costs / max(costs.max(), 1e-6)
        risk_norm = risks / max(risks.max(), 1e-6)

        def objective(x):
            return 0.7 * np.dot(x, risk_norm) + 0.3 * np.dot(x, cost_norm)

        # 制約
        scipy_constraints = []

        # シェア合計 = 1
        scipy_constraints.append({
            "type": "eq",
            "fun": lambda x: np.sum(x) - 1.0,
        })

        # コスト制約: 最適化後のコスト <= 現在コスト * (1 + max_cost_increase_pct/100)
        max_cost = current_cost * (1 + cons["max_cost_increase_pct"] / 100.0)
        if current_cost > 0:
            scipy_constraints.append({
                "type": "ineq",
                "fun": lambda x, mc=max_cost: mc - np.dot(x, costs),
            })

        # 多様化制約: 閾値以上のシェアを持つサプライヤー数 >= min_diversification
        # (非線形なのでペナルティ項で近似)

        # 各サプライヤーの上限
        max_share = cons.get("max_single_share", 0.6)
        bounds = [(0.0, max_share) for _ in range(n)]

        # 初期値: 現在の配分
        x0 = current_shares.copy()
        if x0.sum() == 0:
            x0 = np.ones(n) / n

        # 最適化実行
        try:
            result = minimize(
                objective,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=scipy_constraints,
                options={"maxiter": 500, "ftol": 1e-8},
            )

            if result.success:
                opt_shares = result.x
                # 微小値をゼロに丸める
                opt_shares[opt_shares < 0.01] = 0.0
                # 再正規化
                if opt_shares.sum() > 0:
                    opt_shares = opt_shares / opt_shares.sum()

                opt_risk = float(np.dot(opt_shares, risks))
                opt_cost = float(np.dot(opt_shares, costs))
                cost_delta = ((opt_cost - current_cost) / max(current_cost, 1e-6)) * 100
                risk_improvement = ((current_risk - opt_risk) / max(current_risk, 1e-6)) * 100

                # 変更リスト生成
                changes = self._generate_changes(suppliers, current_shares, opt_shares, risks)

                # 多様化チェック
                active_suppliers = sum(1 for s in opt_shares if s >= 0.01)
                if active_suppliers < cons["min_diversification"]:
                    # 多様化が足りない場合、均等配分にフォールバック
                    changes.append({
                        "type": "warning",
                        "message": f"多様化制約未達 ({active_suppliers} < {cons['min_diversification']})"
                    })

                opt_result = OptimizationResult(
                    current_risk=current_risk,
                    optimized_risk=opt_risk,
                    risk_improvement_pct=risk_improvement,
                    cost_delta_pct=cost_delta,
                    current_allocation={
                        suppliers[i]["supplier_name"]: float(current_shares[i])
                        for i in range(n) if current_shares[i] > 0.001
                    },
                    optimized_allocation={
                        suppliers[i]["supplier_name"]: float(opt_shares[i])
                        for i in range(n) if opt_shares[i] > 0.001
                    },
                    changes=changes,
                    feasible=True,
                    solver_status=result.message,
                )
            else:
                opt_result = OptimizationResult(
                    current_risk=current_risk,
                    optimized_risk=current_risk,
                    risk_improvement_pct=0.0,
                    cost_delta_pct=0.0,
                    current_allocation={
                        suppliers[i]["supplier_name"]: float(current_shares[i])
                        for i in range(n) if current_shares[i] > 0.001
                    },
                    optimized_allocation={},
                    changes=[{"type": "error", "message": f"最適化に失敗: {result.message}"}],
                    feasible=False,
                    solver_status=result.message,
                )
        except Exception as e:
            opt_result = OptimizationResult(
                current_risk=current_risk,
                optimized_risk=current_risk,
                risk_improvement_pct=0.0,
                cost_delta_pct=0.0,
                current_allocation={
                    suppliers[i]["supplier_name"]: float(current_shares[i])
                    for i in range(n) if current_shares[i] > 0.001
                },
                optimized_allocation={},
                changes=[{"type": "error", "message": f"ソルバーエラー: {str(e)}"}],
                feasible=False,
                solver_status=str(e),
            )

        result_dict = opt_result.to_dict()
        result_dict["constraints_applied"] = cons
        result_dict["supplier_count"] = n
        result_dict["timestamp"] = datetime.utcnow().isoformat()
        return result_dict

    def suggest_alternative_countries(
        self,
        current_countries: list[str],
        material: str = "",
        top_n: int = 5,
    ) -> list[dict]:
        """現在の調達国の代替候補を提案。

        同一材料の典型的な調達国からリスクの低い国を推薦。

        Args:
            current_countries: 現在の調達国リスト
            material: 対象材料名
            top_n: 返却する候補数

        Returns:
            [{"country": str, "risk_score": float, "risk_delta": float}, ...]
        """
        # 材料→一般的な調達国マッピング
        material_sources = {
            "battery": ["KR", "JP", "CN", "US", "DE", "HU", "PL"],
            "semiconductor": ["TW", "KR", "JP", "US", "NL", "DE", "SG"],
            "steel": ["JP", "KR", "US", "DE", "IN", "BR", "TR"],
            "rare_earth": ["CN", "AU", "US", "MM", "IN", "BR"],
            "copper": ["CL", "PE", "AU", "US", "ZM", "CD"],
            "aluminum": ["CN", "RU", "CA", "IN", "AE", "AU"],
            "rubber": ["TH", "ID", "MY", "VN", "IN", "CI"],
            "cotton": ["US", "IN", "CN", "BR", "PK", "UZ"],
            "electronics": ["CN", "TW", "KR", "JP", "VN", "MY", "TH"],
        }

        # 候補国を決定
        if material.lower() in material_sources:
            candidates = material_sources[material.lower()]
        else:
            # デフォルト: 主要製造国群
            candidates = [
                "JP", "KR", "TW", "US", "DE", "NL", "SG", "MY",
                "TH", "VN", "IN", "MX", "PL", "CZ", "HU",
            ]

        # 現在の調達国を除外
        current_set = set(c.upper() for c in current_countries)
        candidates = [c for c in candidates if c not in current_set]

        # 現在の平均リスク
        current_risks = [self._get_country_risk(c) for c in current_countries]
        current_avg = np.mean(current_risks) if current_risks else 50.0

        # 候補国のリスクを評価
        alternatives = []
        for c in candidates:
            risk = self._get_country_risk(c)
            alternatives.append({
                "country": c,
                "risk_score": round(risk, 1),
                "risk_delta": round(risk - current_avg, 1),
            })

        # リスクの低い順にソート
        alternatives.sort(key=lambda x: x["risk_score"])

        return alternatives[:top_n]

    @staticmethod
    def _aggregate_suppliers(bom: list[dict]) -> list[dict]:
        """BOM をサプライヤー単位に集約"""
        supplier_map: dict[str, dict] = {}
        total_cost = sum(
            float(item.get("quantity", 1)) * float(item.get("unit_cost_usd", 0))
            for item in bom
        ) or 1.0

        for item in bom:
            name = item.get("supplier_name", "Unknown")
            if name not in supplier_map:
                supplier_map[name] = {
                    "supplier_name": name,
                    "supplier_country": item.get("supplier_country", ""),
                    "unit_cost_usd": float(item.get("unit_cost_usd", 1.0)),
                    "risk_score": item.get("risk_score"),
                    "share": 0.0,
                    "is_alternative": False,
                }

            # シェア加算
            if "share" in item:
                supplier_map[name]["share"] += float(item["share"])
            else:
                # コストベースでシェア推定
                item_cost = float(item.get("quantity", 1)) * float(item.get("unit_cost_usd", 0))
                supplier_map[name]["share"] += item_cost / total_cost

        return list(supplier_map.values())

    @staticmethod
    def _generate_changes(
        suppliers: list[dict],
        current: np.ndarray,
        optimized: np.ndarray,
        risks: np.ndarray,
    ) -> list[dict]:
        """変更提案リストを生成"""
        changes = []
        for i in range(len(suppliers)):
            delta = float(optimized[i] - current[i])
            if abs(delta) < 0.005:
                continue

            action = "increase" if delta > 0 else "decrease"
            changes.append({
                "supplier_name": suppliers[i]["supplier_name"],
                "supplier_country": suppliers[i]["supplier_country"],
                "current_share": round(float(current[i]) * 100, 1),
                "optimized_share": round(float(optimized[i]) * 100, 1),
                "change_pct": round(delta * 100, 1),
                "action": action,
                "risk_score": round(float(risks[i]), 1),
                "rationale": (
                    f"リスクスコア {risks[i]:.0f} — "
                    + ("低リスクのためシェア拡大推奨" if action == "increase" and risks[i] < 40 else
                       "高リスクのためシェア縮小推奨" if action == "decrease" and risks[i] >= 60 else
                       "多様化のための配分調整")
                ),
            })

        changes.sort(key=lambda c: abs(c["change_pct"]), reverse=True)
        return changes
