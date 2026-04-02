"""What-If 感度分析エンジン
重み・スコアを変化させたときの影響を定量分析する。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from scoring.engine import calculate_risk_score, SupplierRiskScore


@dataclass
class DimensionSensitivity:
    """次元別感度結果"""
    dimension: str
    current_weight: float
    current_score: int
    weight_increase_impact: float
    weight_decrease_impact: float

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "current_weight": self.current_weight,
            "current_score": self.current_score,
            "weight_increase_impact": round(self.weight_increase_impact, 2),
            "weight_decrease_impact": round(self.weight_decrease_impact, 2),
        }


@dataclass
class WeightSensitivityReport:
    """重み感度分析レポート"""
    location: str
    baseline_score: int
    perturbation: float
    sensitivity_ranking: list[DimensionSensitivity]
    most_sensitive_dimension: str
    score_range_at_max_perturbation: dict[str, int]
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "baseline_score": self.baseline_score,
            "perturbation": self.perturbation,
            "sensitivity_ranking": [s.to_dict() for s in self.sensitivity_ranking],
            "most_sensitive_dimension": self.most_sensitive_dimension,
            "score_range_at_max_perturbation": self.score_range_at_max_perturbation,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class ScenarioResult:
    """What-Ifシナリオ結果"""
    location: str
    baseline_score: int
    baseline_level: str
    scenario_score: int
    scenario_level: str
    delta: int
    dimension_overrides: dict[str, float]
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "baseline_score": self.baseline_score,
            "baseline_level": self.baseline_level,
            "scenario_score": self.scenario_score,
            "scenario_level": self.scenario_level,
            "delta": self.delta,
            "dimension_overrides": self.dimension_overrides,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class ThresholdPath:
    """閾値到達パス"""
    dimension: str
    current_score: int
    required_score: int
    delta_needed: int

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "current_score": self.current_score,
            "required_score": self.required_score,
            "delta_needed": self.delta_needed,
        }


@dataclass
class ThresholdAnalysis:
    """閾値到達分析"""
    location: str
    current_score: int
    current_level: str
    target_level: str
    target_threshold: int
    gap: int
    paths: list[ThresholdPath]
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "current_score": self.current_score,
            "current_level": self.current_level,
            "target_level": self.target_level,
            "target_threshold": self.target_threshold,
            "gap": self.gap,
            "paths": [p.to_dict() for p in self.paths],
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class MonteCarloResult:
    """モンテカルロシミュレーション結果"""
    location: str
    baseline_score: int
    n_simulations: int
    noise_std: float
    mean_score: float
    median_score: float
    std_score: float
    var_95: float
    var_99: float
    min_score: int
    max_score: int
    confidence_interval_90: tuple[float, float]
    risk_level_distribution: dict[str, float]
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "baseline_score": self.baseline_score,
            "n_simulations": self.n_simulations,
            "noise_std": self.noise_std,
            "mean_score": round(self.mean_score, 1),
            "median_score": round(self.median_score, 1),
            "std_score": round(self.std_score, 1),
            "var_95": round(self.var_95, 1),
            "var_99": round(self.var_99, 1),
            "min_score": self.min_score,
            "max_score": self.max_score,
            "confidence_interval_90": (
                round(self.confidence_interval_90[0], 1),
                round(self.confidence_interval_90[1], 1),
            ),
            "risk_level_distribution": {
                k: round(v, 2) for k, v in self.risk_level_distribution.items()
            },
            "generated_at": self.generated_at.isoformat(),
        }


def _risk_level(score: int) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score >= 20:
        return "LOW"
    return "MINIMAL"


def _compute_overall(scores: dict[str, float], weights: dict[str, float],
                     sanction_score: int = 0) -> int:
    """スコアと重みからoverall_scoreを再計算する内部ヘルパー。

    scoring/engine.py の calculate_overall ロジックを再現:
    composite = weighted_sum * 0.6 + peak * 0.30 + second_peak * 0.10
    """
    if sanction_score == 100:
        return 100

    weighted_sum = sum(scores.get(dim, 0) * weights.get(dim, 0) for dim in weights)
    sorted_vals = sorted(scores.values(), reverse=True)
    peak = sorted_vals[0] if sorted_vals else 0
    second_peak = sorted_vals[1] if len(sorted_vals) > 1 else 0

    composite = int(weighted_sum * 0.6 + peak * 0.30 + second_peak * 0.10)

    if sanction_score > 0:
        composite = min(100, composite + sanction_score // 2)

    return min(100, composite)


class SensitivityAnalyzer:
    """What-If 感度分析エンジン"""

    def _get_baseline(self, location: str) -> dict:
        """ベースラインスコアを取得"""
        result = calculate_risk_score(
            f"sens_{location}", location, country=location, location=location,
        )
        return result.to_dict()

    def analyze_weight_sensitivity(
        self,
        location: str,
        weight_perturbation: float = 0.05,
    ) -> WeightSensitivityReport:
        """各次元の重みを±perturbation変化させたときのスコア感度を分析。

        Args:
            location: 対象国/地域
            weight_perturbation: 摂動幅 (デフォルト±5%)

        Returns:
            WeightSensitivityReport with sensitivity ranking.
        """
        baseline = self._get_baseline(location)
        baseline_score = baseline["overall_score"]
        dim_scores = baseline.get("scores", {})
        sanction_score = dim_scores.get("sanctions", 0)

        # 重み対象の次元のみ (sanctions, japan_economy は除外)
        weights = dict(SupplierRiskScore.WEIGHTS)
        target_dims = list(weights.keys())

        # 重みに含まれない次元を除外したスコアmap
        score_map = {d: dim_scores.get(d, 0) for d in target_dims}

        sensitivities: list[DimensionSensitivity] = []
        all_scores: list[int] = [baseline_score]

        for dim in target_dims:
            original_w = weights[dim]

            # 重み増加
            mod_weights_up = dict(weights)
            mod_weights_up[dim] = original_w + weight_perturbation
            score_up = _compute_overall(score_map, mod_weights_up, sanction_score)

            # 重み減少
            mod_weights_down = dict(weights)
            mod_weights_down[dim] = max(0, original_w - weight_perturbation)
            score_down = _compute_overall(score_map, mod_weights_down, sanction_score)

            impact_up = score_up - baseline_score
            impact_down = score_down - baseline_score

            sensitivities.append(DimensionSensitivity(
                dimension=dim,
                current_weight=original_w,
                current_score=dim_scores.get(dim, 0),
                weight_increase_impact=impact_up,
                weight_decrease_impact=impact_down,
            ))

            all_scores.extend([score_up, score_down])

        # 感度順にソート（|impact_up| + |impact_down| の合計が大きい順）
        sensitivities.sort(
            key=lambda s: -(abs(s.weight_increase_impact) + abs(s.weight_decrease_impact))
        )

        most_sensitive = sensitivities[0].dimension if sensitivities else "N/A"

        return WeightSensitivityReport(
            location=location,
            baseline_score=baseline_score,
            perturbation=weight_perturbation,
            sensitivity_ranking=sensitivities,
            most_sensitive_dimension=most_sensitive,
            score_range_at_max_perturbation={
                "min": min(all_scores),
                "max": max(all_scores),
            },
        )

    def simulate_score_change(
        self,
        location: str,
        dimension_overrides: dict[str, float],
    ) -> ScenarioResult:
        """指定次元のスコアを上書きしてoverall_scoreを再計算するWhat-If。

        Args:
            location: 対象国/地域
            dimension_overrides: {"conflict": 90, "disaster": 50}

        Returns:
            ScenarioResult with baseline vs scenario comparison.
        """
        baseline = self._get_baseline(location)
        baseline_score = baseline["overall_score"]
        dim_scores = baseline.get("scores", {})
        sanction_score = dim_scores.get("sanctions", 0)

        weights = dict(SupplierRiskScore.WEIGHTS)
        score_map = {d: dim_scores.get(d, 0) for d in weights}

        # オーバーライド適用
        for dim, val in dimension_overrides.items():
            if dim in score_map:
                score_map[dim] = val
            elif dim == "sanctions":
                sanction_score = int(val)

        scenario_score = _compute_overall(score_map, weights, sanction_score)

        return ScenarioResult(
            location=location,
            baseline_score=baseline_score,
            baseline_level=_risk_level(baseline_score),
            scenario_score=scenario_score,
            scenario_level=_risk_level(scenario_score),
            delta=scenario_score - baseline_score,
            dimension_overrides=dimension_overrides,
        )

    def find_score_threshold_drivers(
        self,
        location: str,
        target_level: str = "HIGH",
    ) -> ThresholdAnalysis:
        """現在スコアがtarget_levelに到達するために必要な次元変化を逆算。

        Args:
            location: 対象国/地域
            target_level: 目標リスクレベル ("CRITICAL" | "HIGH" | "MEDIUM" | "LOW")

        Returns:
            ThresholdAnalysis with possible paths to reach target level.
        """
        level_thresholds = {"CRITICAL": 80, "HIGH": 60, "MEDIUM": 40, "LOW": 20}
        threshold = level_thresholds.get(target_level)
        if threshold is None:
            raise ValueError(f"Invalid target_level: {target_level}")

        baseline = self._get_baseline(location)
        baseline_score = baseline["overall_score"]
        current_level = _risk_level(baseline_score)
        dim_scores = baseline.get("scores", {})
        sanction_score = dim_scores.get("sanctions", 0)

        weights = dict(SupplierRiskScore.WEIGHTS)
        score_map = {d: dim_scores.get(d, 0) for d in weights}
        gap = threshold - baseline_score

        # 各次元について、何点上昇すればoverallがthresholdに達するか探索
        paths: list[ThresholdPath] = []
        for dim in weights:
            current_dim_score = score_map.get(dim, 0)
            # 二分探索で必要な次元スコアを見つける
            lo, hi = current_dim_score, 100
            if gap > 0:
                # スコアを上げる方向
                required = None
                for target_val in range(current_dim_score + 1, 101):
                    test_map = dict(score_map)
                    test_map[dim] = target_val
                    test_overall = _compute_overall(test_map, weights, sanction_score)
                    if test_overall >= threshold:
                        required = target_val
                        break
                if required is not None:
                    paths.append(ThresholdPath(
                        dimension=dim,
                        current_score=current_dim_score,
                        required_score=required,
                        delta_needed=required - current_dim_score,
                    ))
            else:
                # スコアを下げる方向
                required = None
                for target_val in range(current_dim_score - 1, -1, -1):
                    test_map = dict(score_map)
                    test_map[dim] = target_val
                    test_overall = _compute_overall(test_map, weights, sanction_score)
                    if test_overall < threshold:
                        required = target_val
                        break
                if required is not None:
                    paths.append(ThresholdPath(
                        dimension=dim,
                        current_score=current_dim_score,
                        required_score=required,
                        delta_needed=required - current_dim_score,
                    ))

        # 必要delta昇順ソート
        paths.sort(key=lambda p: abs(p.delta_needed))

        return ThresholdAnalysis(
            location=location,
            current_score=baseline_score,
            current_level=current_level,
            target_level=target_level,
            target_threshold=threshold,
            gap=gap,
            paths=paths,
        )

    def monte_carlo_score_distribution(
        self,
        location: str,
        n_simulations: int = 1000,
        noise_std: float = 10.0,
    ) -> MonteCarloResult:
        """モンテカルロシミュレーションでスコア分布を推定。

        全n_simulations回をnumpy行列演算で一括計算（ベクトル化）。
        n=1000 でも数秒で完了。

        Args:
            location: 対象国/地域
            n_simulations: シミュレーション回数
            noise_std: ガウスノイズの標準偏差

        Returns:
            MonteCarloResult with distribution statistics.
        """
        baseline = self._get_baseline(location)
        baseline_score = baseline["overall_score"]
        dim_scores = baseline.get("scores", {})
        sanction_score = dim_scores.get("sanctions", 0)

        if sanction_score == 100:
            # 制裁100の場合は全シミュレーションが100
            return MonteCarloResult(
                location=location, baseline_score=100,
                n_simulations=n_simulations, noise_std=noise_std,
                mean_score=100.0, median_score=100.0, std_score=0.0,
                var_95=100.0, var_99=100.0, min_score=100, max_score=100,
                confidence_interval_90=(100.0, 100.0),
                risk_level_distribution={"CRITICAL": 1.0, "HIGH": 0.0,
                                         "MEDIUM": 0.0, "LOW": 0.0, "MINIMAL": 0.0},
            )

        weights = dict(SupplierRiskScore.WEIGHTS)
        dims = list(weights.keys())
        n_dims = len(dims)

        base_vector = np.array([dim_scores.get(d, 0) for d in dims], dtype=np.float64)
        weight_vector = np.array([weights[d] for d in dims], dtype=np.float64)

        rng = np.random.default_rng(seed=42)

        # 全シミュレーションを一括行列演算 (n_simulations x n_dims)
        noise_matrix = rng.normal(0, noise_std, size=(n_simulations, n_dims))
        perturbed_matrix = np.clip(base_vector + noise_matrix, 0, 100)

        # 加重平均 (vectorized)
        weighted_sums = perturbed_matrix @ weight_vector  # (n_simulations,)

        # ピーク値: 各行の上位2値
        sorted_matrix = np.sort(perturbed_matrix, axis=1)[:, ::-1]
        peaks = sorted_matrix[:, 0]
        second_peaks = sorted_matrix[:, 1]

        # composite = weighted_sum * 0.6 + peak * 0.30 + second_peak * 0.10
        composites = (weighted_sums * 0.6 + peaks * 0.30 + second_peaks * 0.10).astype(int)

        # 制裁ボーナス
        if sanction_score > 0:
            composites = np.minimum(100, composites + sanction_score // 2)

        composites = np.minimum(100, composites)
        arr = composites

        # リスクレベル分布 (vectorized)
        level_dist = {
            "CRITICAL": float(np.mean(arr >= 80)),
            "HIGH": float(np.mean((arr >= 60) & (arr < 80))),
            "MEDIUM": float(np.mean((arr >= 40) & (arr < 60))),
            "LOW": float(np.mean((arr >= 20) & (arr < 40))),
            "MINIMAL": float(np.mean(arr < 20)),
        }

        return MonteCarloResult(
            location=location,
            baseline_score=baseline_score,
            n_simulations=n_simulations,
            noise_std=noise_std,
            mean_score=float(np.mean(arr)),
            median_score=float(np.median(arr)),
            std_score=float(np.std(arr)),
            var_95=float(np.percentile(arr, 95)),
            var_99=float(np.percentile(arr, 99)),
            min_score=int(np.min(arr)),
            max_score=int(np.max(arr)),
            confidence_interval_90=(
                float(np.percentile(arr, 5)),
                float(np.percentile(arr, 95)),
            ),
            risk_level_distribution=level_dist,
        )
