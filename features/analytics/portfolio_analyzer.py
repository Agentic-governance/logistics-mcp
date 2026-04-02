"""ポートフォリオ分析エンジン
複数サプライヤー/国を一覧比較・ランク付け・クラスタリングする。
Enhanced in STREAM G-3: DBSCAN/hierarchical clustering, UMAP/PCA次元削減,
Plotlyインタラクティブ可視化を追加。
"""
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from scoring.engine import calculate_risk_score, SupplierRiskScore

logger = logging.getLogger(__name__)


@dataclass
class EntityRiskResult:
    """個別エンティティのリスクスコア結果"""
    name: str
    country: str
    tier: int
    share: float
    overall_score: int
    risk_level: str
    scores: dict[str, int]
    evidence_count: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "country": self.country,
            "tier": self.tier,
            "share": self.share,
            "overall_score": self.overall_score,
            "risk_level": self.risk_level,
            "scores": self.scores,
            "evidence_count": self.evidence_count,
        }


@dataclass
class PortfolioReport:
    """ポートフォリオ分析レポート"""
    entities: list[EntityRiskResult]
    weighted_portfolio_score: float
    risk_distribution: dict[str, int]
    top_risks: list[EntityRiskResult]
    lowest_risks: list[EntityRiskResult]
    dominant_risk_dimension: str
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "entity_count": len(self.entities),
            "entities": [e.to_dict() for e in self.entities],
            "weighted_portfolio_score": round(self.weighted_portfolio_score, 1),
            "risk_distribution": self.risk_distribution,
            "top_risks": [e.to_dict() for e in self.top_risks],
            "lowest_risks": [e.to_dict() for e in self.lowest_risks],
            "dominant_risk_dimension": self.dominant_risk_dimension,
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


class PortfolioAnalyzer:
    """複数サプライヤーのリスクポートフォリオを分析"""

    def _score_entity(self, entity: dict, dimensions: list[str]) -> EntityRiskResult:
        """単一エンティティのリスクスコアを取得"""
        name = entity.get("name", "Unknown")
        country = entity.get("country", "")
        tier = entity.get("tier", 1)
        share = entity.get("share", 0.0)

        result = calculate_risk_score(
            supplier_id=f"portfolio_{name}",
            company_name=name,
            country=country,
            location=country,
        )
        result_dict = result.to_dict()
        scores = result_dict.get("scores", {})

        if dimensions:
            scores = {k: v for k, v in scores.items() if k in dimensions}

        return EntityRiskResult(
            name=name,
            country=country,
            tier=tier,
            share=share,
            overall_score=result_dict["overall_score"],
            risk_level=result_dict["risk_level"],
            scores=scores,
            evidence_count=len(result_dict.get("evidence", [])),
        )

    def analyze_portfolio(
        self,
        entities: list[dict],
        dimensions: list[str] | None = None,
    ) -> PortfolioReport:
        """複数エンティティのリスクポートフォリオを一括分析。

        Args:
            entities: [{"name": "TSMC", "country": "TW", "tier": 1, "share": 0.35}, ...]
            dimensions: 分析対象次元リスト。空/Noneなら全24次元。

        Returns:
            PortfolioReport with rankings, distribution, dominant risk dimension.
        """
        dims = dimensions or []
        results: list[EntityRiskResult] = []
        for ent in entities:
            results.append(self._score_entity(ent, dims))

        # 加重平均スコア (share で重み付け)
        total_share = sum(r.share for r in results) or 1.0
        weighted_score = sum(r.overall_score * r.share for r in results) / total_share

        # リスク分布
        distribution: dict[str, int] = {
            "CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "MINIMAL": 0,
        }
        for r in results:
            distribution[r.risk_level] += 1

        # 最高/最低リスク
        sorted_by_risk = sorted(results, key=lambda r: -r.overall_score)
        top_risks = sorted_by_risk[:5]
        lowest_risks = sorted(results, key=lambda r: r.overall_score)[:5]

        # 最大エクスポージャー次元 (全エンティティで最も高い平均スコアの次元)
        all_dims = set()
        for r in results:
            all_dims.update(r.scores.keys())

        dim_averages: dict[str, float] = {}
        for dim in all_dims:
            vals = [r.scores.get(dim, 0) for r in results]
            dim_averages[dim] = sum(vals) / len(vals) if vals else 0.0

        dominant = max(dim_averages, key=dim_averages.get) if dim_averages else "N/A"

        return PortfolioReport(
            entities=results,
            weighted_portfolio_score=weighted_score,
            risk_distribution=distribution,
            top_risks=top_risks,
            lowest_risks=lowest_risks,
            dominant_risk_dimension=dominant,
        )

    def rank_suppliers(
        self,
        entities: list[dict],
        sort_by: str = "overall",
        ascending: bool = True,
    ) -> list[dict]:
        """スコアでランキングを返す。

        Args:
            entities: エンティティリスト
            sort_by: ソートキー ("overall" or 次元名)
            ascending: True=リスク低い順

        Returns:
            ランキングリスト (rank付き)
        """
        results = [self._score_entity(ent, []) for ent in entities]

        def sort_key(r: EntityRiskResult):
            if sort_by == "overall":
                score = r.overall_score
            else:
                score = r.scores.get(sort_by, 0)
            return (score, r.country)

        results.sort(key=sort_key, reverse=not ascending)

        return [
            {"rank": i + 1, **r.to_dict()}
            for i, r in enumerate(results)
        ]

    def cluster_by_risk(
        self,
        entities: list[dict],
        n_clusters: int = 3,
    ) -> dict[str, list]:
        """KMeansでリスクプロファイルをクラスタリング。

        Args:
            entities: エンティティリスト
            n_clusters: クラスタ数

        Returns:
            クラスタ名→エンティティリストのマッピング
        """
        from sklearn.cluster import KMeans
        import numpy as np

        results = [self._score_entity(ent, []) for ent in entities]

        # 次元名を揃える
        all_dims = sorted(SupplierRiskScore.WEIGHTS.keys())

        # 特徴ベクトル構築
        vectors = []
        for r in results:
            vec = [r.scores.get(dim, 0) for dim in all_dims]
            vectors.append(vec)

        X = np.array(vectors, dtype=float)

        # クラスタ数をデータ数に制限
        actual_k = min(n_clusters, len(results))
        if actual_k < 2:
            return {"cluster_0": [r.to_dict() for r in results]}

        kmeans = KMeans(n_clusters=actual_k, n_init=10, random_state=42)
        labels = kmeans.fit_predict(X)

        # クラスタプロファイル生成
        clusters: dict[str, list] = {}
        for label_id in range(actual_k):
            mask = labels == label_id
            center = kmeans.cluster_centers_[label_id]

            # 代表的なリスク次元 (上位3つ)
            top_dims_idx = np.argsort(center)[::-1][:3]
            top_dims = [all_dims[i] for i in top_dims_idx]
            avg_score = float(np.mean([results[j].overall_score for j in range(len(results)) if mask[j]]))

            profile = f"{_risk_level(int(avg_score))}_avg{int(avg_score)}_{'+'.join(top_dims)}"
            members = [results[j].to_dict() for j in range(len(results)) if labels[j] == label_id]
            clusters[profile] = members

        return clusters

    # -----------------------------------------------------------------
    #  STREAM G-3: Enhanced clustering methods
    # -----------------------------------------------------------------

    def cluster_by_risk_enhanced(
        self,
        scores: list[dict],
        method: str = "dbscan",
    ) -> dict:
        """拡張クラスタリング (DBSCAN / hierarchical / kmeans)。

        UMAP が利用可能な場合は 2D 次元削減に使用し、
        利用不可の場合は PCA にフォールバックする。

        Args:
            scores: スコア辞書のリスト。各要素は to_dict() 形式で
                    {"name": str, "country": str, "overall_score": int,
                     "scores": {dim: int, ...}} を含むこと。
            method: "dbscan" (default), "hierarchical", "kmeans"

        Returns:
            {
                "clusters": [...],
                "outliers": [...],
                "cluster_labels": {entity_name: cluster_id},
                "silhouette_score": float or None,
                "coordinates_2d": [...],
                "method": str,
                "reduction_method": str,
            }
        """
        import numpy as np

        try:
            if not scores or len(scores) < 2:
                return {
                    "clusters": [],
                    "outliers": [],
                    "cluster_labels": {},
                    "silhouette_score": None,
                    "coordinates_2d": [],
                    "method": method,
                    "reduction_method": "none",
                    "error": "データが不足しています（2件以上必要）",
                }

            # 全次元名を揃える
            all_dims = sorted(SupplierRiskScore.WEIGHTS.keys())

            # 特徴ベクトル構築
            names = []
            vectors = []
            for s in scores:
                dim_scores = s.get("scores", {})
                vec = [dim_scores.get(dim, 0) for dim in all_dims]
                vectors.append(vec)
                names.append(s.get("name", s.get("country", "Unknown")))

            X = np.array(vectors, dtype=float)

            # 正規化 (0-100 → 0-1)
            X_norm = X / 100.0

            # --- 2D 次元削減 (UMAP or PCA) ---
            coords_2d, reduction_method = self._reduce_to_2d(X_norm)

            # --- クラスタリング ---
            labels, sil_score = self._run_clustering(X_norm, method)

            # --- 結果整理 ---
            cluster_labels = {}
            clusters_dict: dict[int, list] = {}
            outliers = []

            for i, (name, label) in enumerate(zip(names, labels)):
                entry = {
                    "name": name,
                    "country": scores[i].get("country", ""),
                    "overall_score": scores[i].get("overall_score", 0),
                    "cluster_id": int(label),
                    "x": round(float(coords_2d[i][0]), 4) if coords_2d is not None else None,
                    "y": round(float(coords_2d[i][1]), 4) if coords_2d is not None else None,
                }
                cluster_labels[name] = int(label)

                if label == -1:
                    outliers.append(entry)
                else:
                    clusters_dict.setdefault(int(label), []).append(entry)

            # クラスタ情報のリスト化
            cluster_list = []
            for cid, members in sorted(clusters_dict.items()):
                avg_score = sum(m["overall_score"] for m in members) / len(members)
                cluster_list.append({
                    "cluster_id": cid,
                    "size": len(members),
                    "avg_score": round(avg_score, 1),
                    "risk_level": _risk_level(int(avg_score)),
                    "members": members,
                })

            # coordinates_2d のフラットリスト
            coords_list = []
            if coords_2d is not None:
                for i, name in enumerate(names):
                    coords_list.append({
                        "name": name,
                        "x": round(float(coords_2d[i][0]), 4),
                        "y": round(float(coords_2d[i][1]), 4),
                        "cluster_id": int(labels[i]),
                        "overall_score": scores[i].get("overall_score", 0),
                    })

            return {
                "clusters": cluster_list,
                "outliers": outliers,
                "cluster_labels": cluster_labels,
                "silhouette_score": round(sil_score, 4) if sil_score is not None else None,
                "coordinates_2d": coords_list,
                "method": method,
                "reduction_method": reduction_method,
            }

        except Exception as e:
            logger.error(f"拡張クラスタリングエラー: {e}")
            return {
                "clusters": [],
                "outliers": [],
                "cluster_labels": {},
                "silhouette_score": None,
                "coordinates_2d": [],
                "method": method,
                "reduction_method": "error",
                "error": str(e),
            }

    def _reduce_to_2d(self, X: "np.ndarray") -> tuple:
        """UMAP または PCA による 2D 次元削減。

        Args:
            X: 正規化済み特徴行列 (n_samples, n_features)

        Returns:
            (coords_2d: ndarray, method_name: str)
        """
        import numpy as np

        n_samples = X.shape[0]
        if n_samples < 2:
            return None, "none"

        # UMAP を試行
        try:
            import umap
            n_neighbors = min(15, max(2, n_samples - 1))
            reducer = umap.UMAP(
                n_components=2,
                n_neighbors=n_neighbors,
                random_state=42,
            )
            coords = reducer.fit_transform(X)
            return coords, "umap"
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"UMAP失敗、PCAにフォールバック: {e}")

        # PCA フォールバック
        try:
            from sklearn.decomposition import PCA
            n_components = min(2, X.shape[1], n_samples)
            pca = PCA(n_components=n_components, random_state=42)
            coords = pca.fit_transform(X)
            # 1次元の場合は2列目を0で埋める
            if coords.shape[1] == 1:
                coords = np.hstack([coords, np.zeros((n_samples, 1))])
            return coords, "pca"
        except Exception as e:
            logger.warning(f"PCAも失敗: {e}")
            return None, "none"

    def _run_clustering(
        self,
        X: "np.ndarray",
        method: str,
    ) -> tuple:
        """クラスタリングを実行しラベルとシルエットスコアを返す。

        Args:
            X: 正規化済み特徴行列
            method: "dbscan", "hierarchical", "kmeans"

        Returns:
            (labels: ndarray, silhouette_score: float or None)
        """
        import numpy as np
        from sklearn.metrics import silhouette_score as sklearn_silhouette

        n_samples = X.shape[0]

        if method == "dbscan":
            from sklearn.cluster import DBSCAN
            min_samp = min(3, max(2, n_samples // 5))
            clusterer = DBSCAN(eps=0.5, min_samples=min_samp)
            labels = clusterer.fit_predict(X)

        elif method == "hierarchical":
            from sklearn.cluster import AgglomerativeClustering
            n_clusters = min(5, max(2, n_samples // 3))
            clusterer = AgglomerativeClustering(n_clusters=n_clusters)
            labels = clusterer.fit_predict(X)

        else:  # kmeans (default)
            from sklearn.cluster import KMeans
            n_clusters = min(5, max(2, n_samples // 3))
            kmeans = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
            labels = kmeans.fit_predict(X)

        # シルエットスコア計算（2クラスタ以上で有効）
        unique_labels = set(labels)
        non_noise_labels = unique_labels - {-1}

        sil_score = None
        if len(non_noise_labels) >= 2:
            # ノイズ以外のサンプルのみで計算
            mask = labels != -1
            if mask.sum() >= 2:
                try:
                    sil_score = float(sklearn_silhouette(X[mask], labels[mask]))
                except Exception:
                    sil_score = None

        return labels, sil_score

    def generate_risk_map_html(
        self,
        cluster_result: dict,
        output_path: str = "",
    ) -> str:
        """クラスタリング結果をPlotlyでインタラクティブHTML可視化する。

        Args:
            cluster_result: cluster_by_risk_enhanced() の返り値
            output_path: 保存先パス。空文字の場合は data/risk_map.html

        Returns:
            出力ファイルパス
        """
        try:
            import plotly.graph_objects as go

            coords = cluster_result.get("coordinates_2d", [])
            if not coords:
                return ""

            # 出力パス決定: reports/risk_map_{date}.html
            if not output_path:
                _project_root = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
                date_str = datetime.utcnow().strftime("%Y%m%d")
                output_path = os.path.join(
                    _project_root, "reports", f"risk_map_{date_str}.html",
                )

            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # クラスタIDでグループ化
            cluster_groups: dict[int, list] = {}
            for pt in coords:
                cid = pt.get("cluster_id", -1)
                cluster_groups.setdefault(cid, []).append(pt)

            # カラーパレット
            colors = [
                "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
                "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
                "#bcbd22", "#17becf",
            ]

            fig = go.Figure()

            for cid, points in sorted(cluster_groups.items()):
                if cid == -1:
                    color = "#333333"
                    label = "外れ値 (Outlier)"
                    marker_symbol = "x"
                else:
                    color = colors[cid % len(colors)]
                    avg = sum(p["overall_score"] for p in points) / len(points)
                    label = f"クラスタ {cid} (平均スコア: {avg:.0f})"
                    marker_symbol = "circle"

                fig.add_trace(go.Scatter(
                    x=[p["x"] for p in points],
                    y=[p["y"] for p in points],
                    mode="markers+text",
                    marker=dict(
                        size=[max(8, p["overall_score"] / 5) for p in points],
                        color=color,
                        symbol=marker_symbol,
                        line=dict(width=1, color="white"),
                    ),
                    text=[p["name"] for p in points],
                    textposition="top center",
                    textfont=dict(size=9),
                    hovertemplate=(
                        "<b>%{text}</b><br>"
                        "リスクスコア: %{customdata[0]}<br>"
                        "クラスタ: %{customdata[1]}<br>"
                        "<extra></extra>"
                    ),
                    customdata=[
                        [p["overall_score"], cid]
                        for p in points
                    ],
                    name=label,
                ))

            reduction = cluster_result.get("reduction_method", "PCA")
            method = cluster_result.get("method", "unknown")
            sil = cluster_result.get("silhouette_score")
            sil_text = f"  |  シルエットスコア: {sil:.3f}" if sil is not None else ""

            fig.update_layout(
                title=f"サプライチェーンリスクマップ ({method.upper()} + {reduction.upper()}){sil_text}",
                xaxis_title=f"{reduction.upper()} 成分1",
                yaxis_title=f"{reduction.upper()} 成分2",
                template="plotly_white",
                font=dict(family="Noto Sans JP, sans-serif"),
                legend=dict(
                    yanchor="top", y=0.99,
                    xanchor="left", x=0.01,
                ),
                width=1000,
                height=700,
            )

            fig.write_html(output_path, include_plotlyjs="cdn")
            logger.info(f"リスクマップHTML生成: {output_path}")
            return output_path

        except ImportError:
            logger.warning("plotlyが未インストールのため、HTMLマップを生成できません")
            return ""
        except Exception as e:
            logger.error(f"リスクマップ生成エラー: {e}")
            return ""
