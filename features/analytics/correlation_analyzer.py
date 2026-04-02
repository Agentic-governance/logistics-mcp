"""リスク次元間の相関・共起パターン分析エンジン
24次元間のピアソン/スピアマン/ケンドール相関行列、先行指標検出、カスケード検出。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from scoring.engine import calculate_risk_score, SupplierRiskScore


@dataclass
class CorrelationPair:
    """高相関次元ペア"""
    dim_a: str
    dim_b: str
    coefficient: float
    interpretation: str

    def to_dict(self) -> dict:
        return {
            "dim_a": self.dim_a,
            "dim_b": self.dim_b,
            "coefficient": round(self.coefficient, 3),
            "interpretation": self.interpretation,
        }


@dataclass
class CorrelationMatrix:
    """次元間相関行列"""
    dimensions: list[str]
    matrix: list[list[float]]
    method: str
    sample_size: int
    high_correlations: list[CorrelationPair]
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "dimensions": self.dimensions,
            "matrix": [[round(v, 3) for v in row] for row in self.matrix],
            "method": self.method,
            "sample_size": self.sample_size,
            "high_correlations": [p.to_dict() for p in self.high_correlations],
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class LeadingIndicator:
    """先行指標"""
    dimension: str
    target_dimension: str
    lag_days: int
    correlation: float
    interpretation: str

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "target_dimension": self.target_dimension,
            "lag_days": self.lag_days,
            "correlation": round(self.correlation, 3),
            "interpretation": self.interpretation,
        }


@dataclass
class CascadeEvent:
    """リスクカスケードイベント"""
    location: str
    leading_dimension: str
    following_dimension: str
    lead_date: str
    follow_date: str
    lead_delta: float
    follow_delta: float
    lag_days: int

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "leading_dimension": self.leading_dimension,
            "following_dimension": self.following_dimension,
            "lead_date": self.lead_date,
            "follow_date": self.follow_date,
            "lead_delta": self.lead_delta,
            "follow_delta": self.follow_delta,
            "lag_days": self.lag_days,
        }


# 相関係数の解釈テンプレート
_INTERPRETATIONS = {
    (0.9, 1.0): "非常に強い正相関",
    (0.7, 0.9): "強い正相関",
    (0.4, 0.7): "中程度の正相関",
    (-0.7, -0.4): "中程度の負相関",
    (-0.9, -0.7): "強い負相関",
    (-1.0, -0.9): "非常に強い負相関",
}


def _interpret_correlation(r: float, dim_a: str, dim_b: str) -> str:
    """相関係数の解釈テキストを生成"""
    abs_r = abs(r)
    if abs_r >= 0.9:
        strength = "非常に強い"
    elif abs_r >= 0.7:
        strength = "強い"
    elif abs_r >= 0.4:
        strength = "中程度の"
    else:
        strength = "弱い"
    direction = "正" if r > 0 else "負"
    return f"{dim_a} と {dim_b} は r={r:.2f} で{strength}{direction}相関"


class CorrelationAnalyzer:
    """リスク次元間の相関分析エンジン"""

    def compute_dimension_correlations(
        self,
        locations: list[str],
        method: str = "pearson",
    ) -> CorrelationMatrix:
        """指定国群の全次元スコアから次元間相関行列を算出。

        Args:
            locations: 分析対象国リスト（最低20カ国推奨）
            method: 相関係数の算出方法 ("pearson" | "spearman" | "kendall")

        Returns:
            CorrelationMatrix with high correlation pairs extracted.
        """
        from scipy import stats

        dims = sorted(SupplierRiskScore.WEIGHTS.keys())
        # 各国のスコアを取得
        data: list[dict[str, int]] = []
        for loc in locations:
            try:
                result = calculate_risk_score(
                    f"corr_{loc}", loc, country=loc, location=loc,
                )
                scores = result.to_dict().get("scores", {})
                data.append({d: scores.get(d, 0) for d in dims})
            except Exception:
                continue

        if len(data) < 3:
            return CorrelationMatrix(
                dimensions=dims,
                matrix=[[0.0] * len(dims) for _ in dims],
                method=method,
                sample_size=len(data),
                high_correlations=[],
            )

        # numpy行列 (rows=locations, cols=dimensions)
        matrix = np.array([[row[d] for d in dims] for row in data], dtype=float)

        n_dims = len(dims)
        corr_matrix = np.zeros((n_dims, n_dims))

        for i in range(n_dims):
            for j in range(i, n_dims):
                x, y = matrix[:, i], matrix[:, j]
                # 分散ゼロのチェック
                if np.std(x) == 0 or np.std(y) == 0:
                    r = 0.0
                elif method == "spearman":
                    r, _ = stats.spearmanr(x, y)
                elif method == "kendall":
                    r, _ = stats.kendalltau(x, y)
                else:
                    r, _ = stats.pearsonr(x, y)
                if np.isnan(r):
                    r = 0.0
                corr_matrix[i][j] = r
                corr_matrix[j][i] = r

        # 高相関ペア抽出 (|r| > 0.7, 対角除く)
        high_pairs: list[CorrelationPair] = []
        for i in range(n_dims):
            for j in range(i + 1, n_dims):
                r = corr_matrix[i][j]
                if abs(r) > 0.7:
                    high_pairs.append(CorrelationPair(
                        dim_a=dims[i],
                        dim_b=dims[j],
                        coefficient=float(r),
                        interpretation=_interpret_correlation(r, dims[i], dims[j]),
                    ))

        high_pairs.sort(key=lambda p: -abs(p.coefficient))

        return CorrelationMatrix(
            dimensions=dims,
            matrix=corr_matrix.tolist(),
            method=method,
            sample_size=len(data),
            high_correlations=high_pairs,
        )

    def find_leading_indicators(
        self,
        target_dimension: str,
        locations: list[str],
        lag_days: int = 30,
    ) -> list[LeadingIndicator]:
        """時系列クロス相関で先行指標を検出。

        Args:
            target_dimension: 分析対象次元
            locations: 分析対象国リスト
            lag_days: 先行日数の上限

        Returns:
            先行指標リスト (相関順)
        """
        from scipy.signal import correlate as sig_correlate

        indicators: list[LeadingIndicator] = []
        dims = sorted(SupplierRiskScore.WEIGHTS.keys())

        try:
            from features.timeseries.store import RiskTimeSeriesStore
            store = RiskTimeSeriesStore()
        except Exception:
            return indicators

        # 各国の時系列データを集約
        for loc in locations:
            try:
                end_date = datetime.utcnow().strftime("%Y-%m-%d")
                start_date = (datetime.utcnow() - __import__("datetime").timedelta(days=lag_days * 3)).strftime("%Y-%m-%d")
                history = store.get_history(loc, start_date, end_date)
                if len(history) < 10:
                    continue

                # 時系列を次元別に分離
                dim_series: dict[str, list[float]] = {d: [] for d in dims}
                target_series: list[float] = []

                for row in history:
                    dim = row.get("dimension", "")
                    score_val = row.get("score", 0)
                    if dim == target_dimension:
                        target_series.append(float(score_val))
                    elif dim in dim_series:
                        dim_series[dim].append(float(score_val))

                if len(target_series) < 5:
                    continue

                # 各次元とのクロス相関
                for dim in dims:
                    if dim == target_dimension:
                        continue
                    series = dim_series[dim]
                    min_len = min(len(target_series), len(series))
                    if min_len < 5:
                        continue

                    a = np.array(target_series[:min_len])
                    b = np.array(series[:min_len])

                    if np.std(a) == 0 or np.std(b) == 0:
                        continue

                    # 正規化クロス相関
                    a_norm = (a - np.mean(a)) / (np.std(a) * len(a))
                    b_norm = (b - np.mean(b)) / np.std(b)
                    cross_corr = sig_correlate(a_norm, b_norm, mode="full")

                    # 正のラグ部分のみ (b が a に先行するケース)
                    mid = len(cross_corr) // 2
                    positive_lags = cross_corr[mid:]
                    if len(positive_lags) > 1:
                        best_lag = int(np.argmax(np.abs(positive_lags[1:]))) + 1
                        best_r = float(positive_lags[best_lag]) if best_lag < len(positive_lags) else 0.0
                        if abs(best_r) > 0.3:
                            indicators.append(LeadingIndicator(
                                dimension=dim,
                                target_dimension=target_dimension,
                                lag_days=best_lag,
                                correlation=best_r,
                                interpretation=f"{dim} は {target_dimension} に {best_lag}日先行する傾向 (r={best_r:.2f})",
                            ))
            except Exception:
                continue

        # 重複除去（同じ次元ペアは最大相関のみ残す）
        seen: dict[str, LeadingIndicator] = {}
        for ind in indicators:
            key = ind.dimension
            if key not in seen or abs(ind.correlation) > abs(seen[key].correlation):
                seen[key] = ind

        result = sorted(seen.values(), key=lambda x: -abs(x.correlation))
        return result

    def detect_risk_cascades(
        self,
        location: str,
        start_date: str,
        end_date: str,
    ) -> list[CascadeEvent]:
        """リスクカスケード（連鎖的上昇）パターンを検出。

        先行次元が+20点以上上昇した後、30日以内に後続次元が+15点以上上昇した事例を抽出。

        Args:
            location: 対象国/地域
            start_date: 分析開始日 (YYYY-MM-DD)
            end_date: 分析終了日 (YYYY-MM-DD)

        Returns:
            検出されたカスケードイベントリスト
        """
        cascades: list[CascadeEvent] = []

        try:
            from features.timeseries.store import RiskTimeSeriesStore
            store = RiskTimeSeriesStore()
        except Exception:
            return cascades

        history = store.get_history(location, start_date, end_date)
        if not history:
            return cascades

        # 次元別に日付→スコアのマッピングを構築
        dim_timeline: dict[str, list[tuple[str, float]]] = {}
        for row in history:
            dim = row.get("dimension", "")
            if dim == "overall":
                continue
            ts = row.get("timestamp", "")[:10]
            score_val = float(row.get("score", 0))
            if dim not in dim_timeline:
                dim_timeline[dim] = []
            dim_timeline[dim].append((ts, score_val))

        # 各次元で急上昇イベントを検出
        spike_events: list[tuple[str, str, float]] = []  # (dim, date, delta)
        for dim, timeline in dim_timeline.items():
            timeline.sort(key=lambda x: x[0])
            for i in range(1, len(timeline)):
                delta = timeline[i][1] - timeline[i - 1][1]
                if delta >= 20:
                    spike_events.append((dim, timeline[i][0], delta))

        # カスケード検出: 先行スパイク後30日以内に後続スパイク
        from datetime import timedelta as td

        for lead_dim, lead_date, lead_delta in spike_events:
            for follow_dim, follow_date, follow_delta in spike_events:
                if lead_dim == follow_dim:
                    continue
                if follow_delta < 15:
                    continue
                try:
                    ld = datetime.strptime(lead_date, "%Y-%m-%d")
                    fd = datetime.strptime(follow_date, "%Y-%m-%d")
                    lag = (fd - ld).days
                    if 1 <= lag <= 30:
                        cascades.append(CascadeEvent(
                            location=location,
                            leading_dimension=lead_dim,
                            following_dimension=follow_dim,
                            lead_date=lead_date,
                            follow_date=follow_date,
                            lead_delta=lead_delta,
                            follow_delta=follow_delta,
                            lag_days=lag,
                        ))
                except Exception:
                    continue

        cascades.sort(key=lambda c: c.lead_date)
        return cascades
