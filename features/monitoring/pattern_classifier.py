"""リスクスコア急変パターンの自動分類 — STREAM G-2
次元別スコアの変化パターンからイベント種別を推定し、
歴史的前例との照合を行う。

Enhanced in v0.9.0:
- MLベースの分類器 (RandomForest) を追加
- タイムウィンドウ特徴量 (7/14/30/90日の変化率・ボラティリティ) で学習
- ルールベースとMLのハイブリッド分類 (ML利用可能時はアンサンブル)
- 合成訓練データによる事前学習機能
"""
import logging
import math
import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# 学習済みモデルの保存先
_MODEL_PATH = os.environ.get(
    "PATTERN_MODEL_PATH", "data/pattern_classifier_model.pkl",
)


class AnomalyPattern(Enum):
    """異常パターンの分類"""
    SANCTION_EVENT = "sanction_event"
    CONFLICT_OUTBREAK = "conflict_outbreak"
    DISASTER_STRIKE = "disaster_strike"
    ELECTION_IMPACT = "election_impact"
    ECONOMIC_CRISIS = "economic_crisis"
    UNKNOWN = "unknown"


@dataclass
class ClassifiedAnomaly:
    """分類済みの異常パターン"""
    pattern: AnomalyPattern
    confidence: float           # 0.0 - 1.0
    trigger_dimensions: list[str]
    description: str
    historical_precedent: str
    dimension_deltas: dict = field(default_factory=dict)
    classified_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern.value,
            "confidence": round(self.confidence, 3),
            "trigger_dimensions": self.trigger_dimensions,
            "description": self.description,
            "historical_precedent": self.historical_precedent,
            "dimension_deltas": self.dimension_deltas,
            "classified_at": self.classified_at,
        }


class PatternClassifier:
    """リスクスコア急変パターンの自動分類"""

    # パターンシグネチャ定義
    # primary: 急上昇が期待される主要次元
    # secondary: 付随して変動する可能性のある次元
    # description: パターンの日本語説明
    PATTERN_SIGNATURES = {
        AnomalyPattern.SANCTION_EVENT: {
            "primary": ["sanctions", "compliance"],
            "secondary": ["trade", "economic"],
            "description": "制裁発動パターン: sanctions/complianceが急上昇",
        },
        AnomalyPattern.CONFLICT_OUTBREAK: {
            "primary": ["conflict", "geo_risk"],
            "secondary": ["humanitarian", "health"],
            "description": "紛争勃発パターン: conflict/geopoliticalが急上昇",
        },
        AnomalyPattern.DISASTER_STRIKE: {
            "primary": ["disaster", "infrastructure"],
            "secondary": ["port_congestion", "maritime"],
            "description": "自然災害パターン: disaster/infrastructureが急上昇",
        },
        AnomalyPattern.ELECTION_IMPACT: {
            "primary": ["political", "geo_risk"],
            "secondary": ["economic", "currency"],
            "description": "選挙影響パターン: political/geopoliticalが変動",
        },
        AnomalyPattern.ECONOMIC_CRISIS: {
            "primary": ["economic", "currency"],
            "secondary": ["trade", "food_security"],
            "description": "経済危機パターン: economic/currencyが急上昇",
        },
    }

    # 歴史的前例データベース
    HISTORICAL_PRECEDENTS = {
        AnomalyPattern.SANCTION_EVENT: [
            {
                "event": "ロシア制裁強化 (2022)",
                "location": "Russia",
                "year": 2022,
                "description": "ウクライナ侵攻に伴う西側諸国による包括的制裁。sanctions/compliance/tradeが急上昇。",
                "peak_dimensions": {"sanctions": 100, "compliance": 85, "trade": 75},
            },
            {
                "event": "イラン核合意離脱制裁 (2018)",
                "location": "Iran",
                "year": 2018,
                "description": "米国のJCPOA離脱に伴う制裁再発動。石油・金融セクターに直接影響。",
                "peak_dimensions": {"sanctions": 90, "economic": 80, "energy": 70},
            },
            {
                "event": "北朝鮮追加制裁 (2017)",
                "location": "North Korea",
                "year": 2017,
                "description": "核実験に対する国連安保理追加制裁決議。全面的な貿易制限。",
                "peak_dimensions": {"sanctions": 100, "compliance": 90, "trade": 85},
            },
        ],
        AnomalyPattern.CONFLICT_OUTBREAK: [
            {
                "event": "ウクライナ紛争 (2022)",
                "location": "Ukraine",
                "year": 2022,
                "description": "大規模な軍事侵攻。conflict/geo_risk/humanitarianが同時に急上昇。",
                "peak_dimensions": {"conflict": 95, "geo_risk": 90, "humanitarian": 85},
            },
            {
                "event": "ガザ紛争 (2023)",
                "location": "Israel",
                "year": 2023,
                "description": "大規模な軍事作戦。周辺地域のgeopoliticalリスクも上昇。",
                "peak_dimensions": {"conflict": 90, "geo_risk": 85, "humanitarian": 80},
            },
            {
                "event": "ミャンマークーデター (2021)",
                "location": "Myanmar",
                "year": 2021,
                "description": "軍事クーデターによる政治的混乱。conflict/political/sanctionsが上昇。",
                "peak_dimensions": {"conflict": 80, "political": 90, "sanctions": 60},
            },
        ],
        AnomalyPattern.DISASTER_STRIKE: [
            {
                "event": "トルコ・シリア地震 (2023)",
                "location": "Turkey",
                "year": 2023,
                "description": "M7.8の大地震。災害/インフラ/港湾が急上昇。",
                "peak_dimensions": {"disaster": 95, "port_congestion": 70},
            },
            {
                "event": "タイ洪水 (2011)",
                "location": "Thailand",
                "year": 2011,
                "description": "大規模洪水がサプライチェーンを直撃。HDD生産に壊滅的影響。",
                "peak_dimensions": {"disaster": 90, "maritime": 75, "port_congestion": 80},
            },
            {
                "event": "東日本大震災 (2011)",
                "location": "Japan",
                "year": 2011,
                "description": "M9.0の地震と津波。原発事故も重なり、グローバルSCに深刻な影響。",
                "peak_dimensions": {"disaster": 100, "energy": 85, "maritime": 70},
            },
        ],
        AnomalyPattern.ELECTION_IMPACT: [
            {
                "event": "トランプ大統領就任 (2017/2025)",
                "location": "United States",
                "year": 2017,
                "description": "貿易政策の大幅な変更。関税引き上げと貿易戦争リスク。",
                "peak_dimensions": {"political": 60, "trade": 65, "economic": 55},
            },
            {
                "event": "ブラジル大統領選 (2022)",
                "location": "Brazil",
                "year": 2022,
                "description": "接戦の大統領選。政治不安定性と通貨変動。",
                "peak_dimensions": {"political": 70, "currency": 60, "economic": 55},
            },
        ],
        AnomalyPattern.ECONOMIC_CRISIS: [
            {
                "event": "スリランカ経済危機 (2022)",
                "location": "Sri Lanka",
                "year": 2022,
                "description": "外貨準備の枯渇によるデフォルト。economic/currency/food_securityが急上昇。",
                "peak_dimensions": {"economic": 95, "currency": 90, "food_security": 80},
            },
            {
                "event": "トルコリラ危機 (2018/2021)",
                "location": "Turkey",
                "year": 2021,
                "description": "リラの大幅下落。economic/currencyが急上昇。",
                "peak_dimensions": {"economic": 75, "currency": 90, "trade": 60},
            },
            {
                "event": "アルゼンチンペソ危機 (2023)",
                "location": "Argentina",
                "year": 2023,
                "description": "インフレ率100%超とペソの大幅切り下げ。",
                "peak_dimensions": {"economic": 85, "currency": 95, "food_security": 65},
            },
        ],
    }

    # 分類に必要な最小デルタ閾値
    MIN_SIGNIFICANT_DELTA = 10.0

    def classify_anomaly(
        self,
        dimension_deltas: dict[str, float],
    ) -> ClassifiedAnomaly:
        """次元別スコア変化からパターンを分類する。

        Args:
            dimension_deltas: {dimension_name: score_change} 辞書
                              正の値=スコア上昇（リスク増大）

        Returns:
            ClassifiedAnomaly: 分類結果
        """
        try:
            if not dimension_deltas:
                return ClassifiedAnomaly(
                    pattern=AnomalyPattern.UNKNOWN,
                    confidence=0.0,
                    trigger_dimensions=[],
                    description="変化データが提供されていません",
                    historical_precedent="該当なし",
                    dimension_deltas=dimension_deltas,
                )

            # 有意な変化がある次元を抽出
            significant = {
                dim: delta for dim, delta in dimension_deltas.items()
                if abs(delta) >= self.MIN_SIGNIFICANT_DELTA
            }

            if not significant:
                return ClassifiedAnomaly(
                    pattern=AnomalyPattern.UNKNOWN,
                    confidence=0.0,
                    trigger_dimensions=[],
                    description="有意なスコア変化が検出されませんでした",
                    historical_precedent="該当なし",
                    dimension_deltas=dimension_deltas,
                )

            # 各パターンとのマッチスコアを計算
            pattern_scores = {}
            for pattern, signature in self.PATTERN_SIGNATURES.items():
                score = self._compute_match_score(significant, signature)
                pattern_scores[pattern] = score

            # 最もスコアの高いパターンを選択
            best_pattern = max(pattern_scores, key=pattern_scores.get)
            best_score = pattern_scores[best_pattern]

            # 信頼度の閾値チェック
            if best_score < 0.2:
                best_pattern = AnomalyPattern.UNKNOWN
                best_score = 0.0

            # トリガー次元の特定
            trigger_dims = sorted(
                significant.keys(),
                key=lambda d: abs(significant[d]),
                reverse=True,
            )[:5]

            # 歴史的前例の取得
            precedent = self._get_best_precedent(best_pattern, significant)

            # 説明文の生成
            sig_info = self.PATTERN_SIGNATURES.get(best_pattern, {})
            description = sig_info.get(
                "description",
                "パターンを特定できませんでした",
            )

            return ClassifiedAnomaly(
                pattern=best_pattern,
                confidence=min(1.0, best_score),
                trigger_dimensions=trigger_dims,
                description=description,
                historical_precedent=precedent,
                dimension_deltas=dimension_deltas,
            )

        except Exception as e:
            logger.error(f"パターン分類エラー: {e}")
            return ClassifiedAnomaly(
                pattern=AnomalyPattern.UNKNOWN,
                confidence=0.0,
                trigger_dimensions=[],
                description=f"分類中にエラーが発生しました: {e}",
                historical_precedent="該当なし",
                dimension_deltas=dimension_deltas,
            )

    def _compute_match_score(
        self,
        significant_deltas: dict[str, float],
        signature: dict,
    ) -> float:
        """パターンシグネチャとの一致度を計算する。

        スコア計算:
        - primary次元にヒット: 各 +0.3 (最大0.6)
        - secondary次元にヒット: 各 +0.15 (最大0.3)
        - デルタの大きさによるボーナス: 最大 +0.1

        Returns:
            0.0 - 1.0 のマッチスコア
        """
        primary_dims = signature.get("primary", [])
        secondary_dims = signature.get("secondary", [])

        score = 0.0
        max_delta = max(abs(v) for v in significant_deltas.values()) if significant_deltas else 1.0

        # Primary次元マッチ
        primary_hits = 0
        for dim in primary_dims:
            if dim in significant_deltas and significant_deltas[dim] > 0:
                primary_hits += 1
                # デルタの大きさに比例したボーナス
                score += 0.3 * min(1.0, abs(significant_deltas[dim]) / max(max_delta, 1.0))

        # Secondary次元マッチ
        secondary_hits = 0
        for dim in secondary_dims:
            if dim in significant_deltas and significant_deltas[dim] > 0:
                secondary_hits += 1
                score += 0.15 * min(1.0, abs(significant_deltas[dim]) / max(max_delta, 1.0))

        # Primary次元が一つもヒットしなければ低スコア
        if primary_hits == 0:
            score *= 0.2

        # 大きなデルタへのボーナス（急激な変化は分類しやすい）
        if max_delta >= 30:
            score += 0.1

        return min(1.0, score)

    def _get_best_precedent(
        self,
        pattern: AnomalyPattern,
        significant_deltas: dict[str, float],
    ) -> str:
        """パターンに最も近い歴史的前例を返す"""
        precedents = self.HISTORICAL_PRECEDENTS.get(pattern, [])
        if not precedents:
            return "該当する歴史的前例なし"

        # 最も新しい前例をデフォルトとして返す
        best = max(precedents, key=lambda p: p.get("year", 0))
        return f"{best['event']}: {best['description']}"

    def classify_from_history(
        self,
        location: str,
        scores_before: dict,
        scores_after: dict,
    ) -> ClassifiedAnomaly:
        """前後のスコアから変化パターンを分類する。

        Args:
            location: ロケーション名
            scores_before: 変化前のスコア辞書 (to_dict形式)
            scores_after: 変化後のスコア辞書 (to_dict形式)

        Returns:
            ClassifiedAnomaly: 分類結果
        """
        try:
            before_scores = scores_before.get("scores", {})
            after_scores = scores_after.get("scores", {})

            # デルタを計算
            all_dims = set(list(before_scores.keys()) + list(after_scores.keys()))
            deltas = {}
            for dim in all_dims:
                old_val = before_scores.get(dim, 0)
                new_val = after_scores.get(dim, 0)
                delta = new_val - old_val
                if abs(delta) > 0:
                    deltas[dim] = delta

            result = self.classify_anomaly(deltas)

            # ロケーション固有の説明を追加
            overall_before = scores_before.get("overall_score", 0)
            overall_after = scores_after.get("overall_score", 0)
            overall_delta = overall_after - overall_before

            if overall_delta > 0:
                direction = "上昇"
            elif overall_delta < 0:
                direction = "下降"
            else:
                direction = "変化なし"

            result.description = (
                f"{location}: 総合スコア{overall_before}→{overall_after}"
                f"（{direction}{abs(overall_delta):.0f}pt）。"
                f"{result.description}"
            )

            return result

        except Exception as e:
            logger.error(f"履歴ベースのパターン分類エラー ({location}): {e}")
            return ClassifiedAnomaly(
                pattern=AnomalyPattern.UNKNOWN,
                confidence=0.0,
                trigger_dimensions=[],
                description=f"{location}: 分類中にエラーが発生 — {e}",
                historical_precedent="該当なし",
            )

    def get_historical_precedents(
        self,
        pattern: AnomalyPattern,
    ) -> list[dict]:
        """指定パターンの歴史的前例一覧を返す。

        Args:
            pattern: AnomalyPattern enum値

        Returns:
            前例辞書のリスト
        """
        return list(self.HISTORICAL_PRECEDENTS.get(pattern, []))


# =====================================================================
#  ML ベースのパターン分類器 — RandomForest + タイムウィンドウ特徴量
# =====================================================================

# タイムウィンドウ特徴量で使用する次元（scoring engine の WEIGHTS キー順）
_FEATURE_DIMENSIONS = [
    "geo_risk", "conflict", "political", "compliance",
    "disaster", "weather", "typhoon", "maritime", "internet", "climate_risk",
    "economic", "currency", "trade", "energy", "port_congestion",
    "cyber_risk", "legal", "health", "humanitarian", "food_security",
    "labor", "aviation", "sc_vulnerability", "sanctions",
]

# パターン → 整数ラベル
_PATTERN_TO_LABEL = {
    AnomalyPattern.SANCTION_EVENT: 0,
    AnomalyPattern.CONFLICT_OUTBREAK: 1,
    AnomalyPattern.DISASTER_STRIKE: 2,
    AnomalyPattern.ELECTION_IMPACT: 3,
    AnomalyPattern.ECONOMIC_CRISIS: 4,
    AnomalyPattern.UNKNOWN: 5,
}
_LABEL_TO_PATTERN = {v: k for k, v in _PATTERN_TO_LABEL.items()}


def _build_time_window_features(
    dimension_deltas: dict,
    window_deltas: Optional[dict] = None,
) -> list:
    """タイムウィンドウ特徴量ベクトルを構築する。

    特徴量構成 (1サンプルあたり):
    - 24次元のデルタ値 (現在の変化)
    - 24次元の絶対値
    - 統計量: max_delta, min_delta, mean_delta, std_delta,
              positive_count, negative_count
    - タイムウィンドウ別 (7/14/30/90日) × 24次元の変化率 (提供時)
    合計: 基本54 + オプション96 = 最大150特徴量

    Args:
        dimension_deltas: {dimension: delta} 現在の変化量
        window_deltas: {window_name: {dimension: delta}} 期間別の変化量
                       例: {"7d": {...}, "14d": {...}, "30d": {...}, "90d": {...}}

    Returns:
        特徴量ベクトル (list of float)
    """
    features = []

    # 1. 現在のデルタ値 (24次元)
    for dim in _FEATURE_DIMENSIONS:
        features.append(dimension_deltas.get(dim, 0.0))

    # 2. 絶対値 (24次元)
    for dim in _FEATURE_DIMENSIONS:
        features.append(abs(dimension_deltas.get(dim, 0.0)))

    # 3. 統計量 (6値)
    all_deltas = [dimension_deltas.get(dim, 0.0) for dim in _FEATURE_DIMENSIONS]
    if all_deltas:
        max_d = max(all_deltas)
        min_d = min(all_deltas)
        mean_d = sum(all_deltas) / len(all_deltas)
        var_d = sum((v - mean_d) ** 2 for v in all_deltas) / len(all_deltas)
        std_d = math.sqrt(var_d) if var_d > 0 else 0.0
        pos_count = sum(1 for v in all_deltas if v > 5)
        neg_count = sum(1 for v in all_deltas if v < -5)
    else:
        max_d = min_d = mean_d = std_d = 0.0
        pos_count = neg_count = 0

    features.extend([max_d, min_d, mean_d, std_d, float(pos_count), float(neg_count)])

    # 4. タイムウィンドウ別のデルタ (オプション: 各24次元 × 4ウィンドウ = 96)
    for window in ["7d", "14d", "30d", "90d"]:
        if window_deltas and window in window_deltas:
            w_deltas = window_deltas[window]
            for dim in _FEATURE_DIMENSIONS:
                features.append(w_deltas.get(dim, 0.0))
        else:
            # データなし: 0埋め
            features.extend([0.0] * len(_FEATURE_DIMENSIONS))

    return features


def _generate_synthetic_training_data(n_samples_per_class: int = 200) -> tuple:
    """合成訓練データを生成する（事前学習用）。

    各パターンのシグネチャに基づいてノイズ付きの合成サンプルを生成。

    Returns:
        (X: list[list], y: list[int])
    """
    import random
    random.seed(42)

    # パターンシグネチャ定義（PatternClassifierと同じ）
    signatures = {
        AnomalyPattern.SANCTION_EVENT: {
            "primary": {"sanctions": (40, 80), "compliance": (30, 70)},
            "secondary": {"trade": (10, 40), "economic": (10, 35)},
        },
        AnomalyPattern.CONFLICT_OUTBREAK: {
            "primary": {"conflict": (40, 80), "geo_risk": (30, 70)},
            "secondary": {"humanitarian": (15, 45), "health": (5, 25)},
        },
        AnomalyPattern.DISASTER_STRIKE: {
            "primary": {"disaster": (40, 80), "weather": (20, 60)},
            "secondary": {"port_congestion": (10, 40), "maritime": (10, 35)},
        },
        AnomalyPattern.ELECTION_IMPACT: {
            "primary": {"political": (25, 60), "geo_risk": (15, 45)},
            "secondary": {"economic": (10, 30), "currency": (10, 30)},
        },
        AnomalyPattern.ECONOMIC_CRISIS: {
            "primary": {"economic": (40, 80), "currency": (35, 75)},
            "secondary": {"trade": (15, 40), "food_security": (10, 35)},
        },
    }

    X = []
    y = []

    for pattern, sig in signatures.items():
        label = _PATTERN_TO_LABEL[pattern]
        for _ in range(n_samples_per_class):
            deltas = {}
            # Primary次元: 指定範囲のランダム値
            for dim, (lo, hi) in sig["primary"].items():
                deltas[dim] = random.uniform(lo, hi)
            # Secondary次元: 指定範囲のランダム値
            for dim, (lo, hi) in sig["secondary"].items():
                deltas[dim] = random.uniform(lo, hi)
            # その他の次元: 小さなノイズ
            for dim in _FEATURE_DIMENSIONS:
                if dim not in deltas:
                    deltas[dim] = random.uniform(-8, 8)

            # タイムウィンドウも合成（primary/secondaryを時間で減衰）
            window_deltas = {}
            for w_name, decay in [("7d", 0.5), ("14d", 0.7), ("30d", 0.85), ("90d", 0.95)]:
                w = {}
                for dim in _FEATURE_DIMENSIONS:
                    base = deltas.get(dim, 0)
                    w[dim] = base * decay + random.uniform(-3, 3)
                window_deltas[w_name] = w

            features = _build_time_window_features(deltas, window_deltas)
            X.append(features)
            y.append(label)

    # UNKNOWN クラス: ランダムなノイズ（パターンなし）
    for _ in range(n_samples_per_class):
        deltas = {dim: random.uniform(-15, 15) for dim in _FEATURE_DIMENSIONS}
        window_deltas = {
            w: {dim: random.uniform(-10, 10) for dim in _FEATURE_DIMENSIONS}
            for w in ["7d", "14d", "30d", "90d"]
        }
        features = _build_time_window_features(deltas, window_deltas)
        X.append(features)
        y.append(_PATTERN_TO_LABEL[AnomalyPattern.UNKNOWN])

    return X, y


class MLPatternClassifier:
    """ML ベースのパターン分類器。

    RandomForest を使用し、タイムウィンドウ特徴量から
    異常パターンを自動分類する。
    ルールベースの PatternClassifier と併用（アンサンブル）可能。

    使い方:
        ml_clf = MLPatternClassifier()
        ml_clf.train()  # 初回のみ（合成データで事前学習）
        result = ml_clf.classify(dimension_deltas)
    """

    def __init__(self):
        self._model = None
        self._rule_classifier = PatternClassifier()
        self._is_trained = False
        # 保存済みモデルがあれば読み込み
        self._try_load_model()

    def _try_load_model(self):
        """保存済みモデルの読み込みを試行"""
        try:
            if os.path.exists(_MODEL_PATH):
                with open(_MODEL_PATH, "rb") as f:
                    self._model = pickle.load(f)
                self._is_trained = True
                logger.info(f"学習済みパターン分類モデルを読み込みました: {_MODEL_PATH}")
        except Exception as e:
            logger.debug(f"モデル読み込み失敗: {e}")
            self._model = None
            self._is_trained = False

    def train(
        self,
        X: Optional[list] = None,
        y: Optional[list] = None,
        n_synthetic: int = 200,
        save: bool = True,
    ) -> dict:
        """モデルを学習する。

        Args:
            X: 特徴量行列。None の場合は合成データを生成。
            y: ラベルベクトル。
            n_synthetic: 合成データ生成時のクラスあたりサンプル数。
            save: 学習済みモデルを保存するか。

        Returns:
            学習結果の辞書 (accuracy, feature_importances, etc.)
        """
        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.model_selection import cross_val_score
            import numpy as np

            # データ準備
            if X is None or y is None:
                logger.info(f"合成訓練データを生成中 (各クラス{n_synthetic}サンプル)...")
                X, y = _generate_synthetic_training_data(n_synthetic)

            X_arr = np.array(X, dtype=float)
            y_arr = np.array(y, dtype=int)

            logger.info(
                f"学習データ: {X_arr.shape[0]}サンプル × {X_arr.shape[1]}特徴量, "
                f"{len(set(y_arr))}クラス"
            )

            # RandomForest
            self._model = RandomForestClassifier(
                n_estimators=100,
                max_depth=15,
                min_samples_split=5,
                min_samples_leaf=2,
                random_state=42,
                n_jobs=-1,
            )

            # クロスバリデーション
            cv_scores = cross_val_score(self._model, X_arr, y_arr, cv=5, scoring="accuracy")
            logger.info(f"CV精度: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

            # 全データで学習
            self._model.fit(X_arr, y_arr)
            self._is_trained = True

            # 特徴量重要度（上位10）
            importances = self._model.feature_importances_
            n_base = len(_FEATURE_DIMENSIONS)
            feature_names = (
                [f"{d}_delta" for d in _FEATURE_DIMENSIONS]
                + [f"{d}_abs" for d in _FEATURE_DIMENSIONS]
                + ["max_delta", "min_delta", "mean_delta", "std_delta", "pos_count", "neg_count"]
                + [f"{d}_{w}" for w in ["7d", "14d", "30d", "90d"] for d in _FEATURE_DIMENSIONS]
            )
            top_indices = np.argsort(importances)[::-1][:10]
            top_features = []
            for idx in top_indices:
                name = feature_names[idx] if idx < len(feature_names) else f"feature_{idx}"
                top_features.append({
                    "feature": name,
                    "importance": round(float(importances[idx]), 4),
                })

            # モデル保存
            if save:
                try:
                    os.makedirs(os.path.dirname(_MODEL_PATH) or ".", exist_ok=True)
                    with open(_MODEL_PATH, "wb") as f:
                        pickle.dump(self._model, f)
                    logger.info(f"モデル保存完了: {_MODEL_PATH}")
                except Exception as e:
                    logger.warning(f"モデル保存失敗: {e}")

            return {
                "status": "trained",
                "n_samples": len(y_arr),
                "n_features": X_arr.shape[1],
                "n_classes": len(set(y_arr)),
                "cv_accuracy_mean": round(float(cv_scores.mean()), 4),
                "cv_accuracy_std": round(float(cv_scores.std()), 4),
                "top_features": top_features,
                "model_path": _MODEL_PATH if save else None,
            }

        except Exception as e:
            logger.error(f"ML分類器の学習エラー: {e}")
            return {"status": "error", "error": str(e)}

    def classify(
        self,
        dimension_deltas: dict,
        window_deltas: Optional[dict] = None,
        use_ensemble: bool = True,
    ) -> ClassifiedAnomaly:
        """MLベースの分類を実行する。

        Args:
            dimension_deltas: {dimension: delta} 変化量
            window_deltas: タイムウィンドウ別デルタ（オプション）
            use_ensemble: True の場合、ルールベースとMLのアンサンブル

        Returns:
            ClassifiedAnomaly
        """
        # ルールベースの結果を常に取得
        rule_result = self._rule_classifier.classify_anomaly(dimension_deltas)

        # MLモデルが使えない場合はルールベースにフォールバック
        if not self._is_trained or self._model is None:
            logger.debug("MLモデル未学習 — ルールベース分類にフォールバック")
            return rule_result

        try:
            import numpy as np

            # 特徴量構築
            features = _build_time_window_features(dimension_deltas, window_deltas)
            X = np.array([features], dtype=float)

            # ML予測
            ml_label = int(self._model.predict(X)[0])
            ml_proba = self._model.predict_proba(X)[0]
            ml_confidence = float(max(ml_proba))
            ml_pattern = _LABEL_TO_PATTERN.get(ml_label, AnomalyPattern.UNKNOWN)

            if not use_ensemble:
                # ML結果のみを返す
                precedent = self._rule_classifier._get_best_precedent(
                    ml_pattern, {d: v for d, v in dimension_deltas.items() if abs(v) >= 10},
                )
                sig_info = PatternClassifier.PATTERN_SIGNATURES.get(ml_pattern, {})
                description = sig_info.get("description", "MLベース分類結果")

                trigger_dims = sorted(
                    dimension_deltas.keys(),
                    key=lambda d: abs(dimension_deltas.get(d, 0)),
                    reverse=True,
                )[:5]

                return ClassifiedAnomaly(
                    pattern=ml_pattern,
                    confidence=ml_confidence,
                    trigger_dimensions=trigger_dims,
                    description=f"[ML] {description}",
                    historical_precedent=precedent,
                    dimension_deltas=dimension_deltas,
                )

            # アンサンブル: ルールベースとMLの結合
            rule_confidence = rule_result.confidence
            rule_pattern = rule_result.pattern

            # 両者が一致 → 信頼度を上げる
            if ml_pattern == rule_pattern:
                ensemble_pattern = ml_pattern
                ensemble_confidence = min(1.0, (ml_confidence + rule_confidence) / 2 + 0.1)
            # 不一致の場合は信頼度の高い方を採用
            elif ml_confidence > rule_confidence + 0.15:
                ensemble_pattern = ml_pattern
                ensemble_confidence = ml_confidence * 0.8
            elif rule_confidence > ml_confidence + 0.15:
                ensemble_pattern = rule_pattern
                ensemble_confidence = rule_confidence * 0.8
            else:
                # 拮抗: ML側を優先（データドリブン）
                ensemble_pattern = ml_pattern
                ensemble_confidence = (ml_confidence + rule_confidence) / 2

            # メタデータ更新
            sig_info = PatternClassifier.PATTERN_SIGNATURES.get(ensemble_pattern, {})
            description = sig_info.get("description", "パターン不明")
            if ml_pattern != rule_pattern:
                description += (
                    f" [ML:{ml_pattern.value}({ml_confidence:.2f})"
                    f" / Rule:{rule_pattern.value}({rule_confidence:.2f})]"
                )

            precedent = self._rule_classifier._get_best_precedent(
                ensemble_pattern,
                {d: v for d, v in dimension_deltas.items() if abs(v) >= 10},
            )

            return ClassifiedAnomaly(
                pattern=ensemble_pattern,
                confidence=min(1.0, ensemble_confidence),
                trigger_dimensions=rule_result.trigger_dimensions,
                description=description,
                historical_precedent=precedent,
                dimension_deltas=dimension_deltas,
            )

        except Exception as e:
            logger.error(f"ML分類エラー: {e}")
            return rule_result

    def classify_from_history(
        self,
        location: str,
        score_snapshots: list,
    ) -> ClassifiedAnomaly:
        """複数時点のスコアスナップショットからパターンを分類する。

        タイムウィンドウ特徴量を自動構築して ML 分類を実行。

        Args:
            location: ロケーション名
            score_snapshots: 時系列順のスコアリスト
                [{date, overall_score, scores: {dim: val}}, ...]
                最低2件、最後の要素が最新。

        Returns:
            ClassifiedAnomaly
        """
        if not score_snapshots or len(score_snapshots) < 2:
            return ClassifiedAnomaly(
                pattern=AnomalyPattern.UNKNOWN,
                confidence=0.0,
                trigger_dimensions=[],
                description=f"{location}: スナップショットが不足しています",
                historical_precedent="該当なし",
            )

        try:
            latest = score_snapshots[-1].get("scores", {})
            previous = score_snapshots[-2].get("scores", {})

            # 現在の変化量
            all_dims = set(list(latest.keys()) + list(previous.keys()))
            deltas = {}
            for dim in all_dims:
                delta = latest.get(dim, 0) - previous.get(dim, 0)
                if abs(delta) > 0:
                    deltas[dim] = delta

            # タイムウィンドウ別のデルタ構築
            window_deltas = {}
            n = len(score_snapshots)
            for window_name, lookback in [("7d", 2), ("14d", 4), ("30d", 8), ("90d", 20)]:
                if n > lookback:
                    old_scores = score_snapshots[max(0, n - 1 - lookback)].get("scores", {})
                    w = {}
                    for dim in all_dims:
                        w[dim] = latest.get(dim, 0) - old_scores.get(dim, 0)
                    window_deltas[window_name] = w

            result = self.classify(deltas, window_deltas)

            # ロケーション情報を追加
            overall_before = score_snapshots[-2].get("overall_score", 0)
            overall_after = score_snapshots[-1].get("overall_score", 0)
            direction = "上昇" if overall_after > overall_before else "下降"
            result.description = (
                f"{location}: 総合スコア{overall_before}→{overall_after}"
                f"（{direction}{abs(overall_after - overall_before):.0f}pt）。"
                f"{result.description}"
            )

            return result

        except Exception as e:
            logger.error(f"履歴ベースML分類エラー ({location}): {e}")
            return ClassifiedAnomaly(
                pattern=AnomalyPattern.UNKNOWN,
                confidence=0.0,
                trigger_dimensions=[],
                description=f"{location}: ML分類中にエラーが発生 — {e}",
                historical_precedent="該当なし",
            )
