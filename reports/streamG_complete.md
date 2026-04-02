# STREAM G: ML/予測強化 — 完了レポート

**日時**: 2026-03-27
**バージョン**: SCRI v0.9.0

---

## G-1: リスクスコアの説明可能性 (XAI)

**ファイル**: `features/analytics/explainability.py`

### 既存機能 (確認済み)
- RiskExplainer.explain_score() — 寄与度分析・日本語サマリ・推奨アクション
- 24次元の日本語ラベル・理由テンプレート
- 地域/グローバル平均との比較
- 複数ロケーション比較 (compare_locations)
- スコア変化説明 (explain_score_change)

### 新規追加
- **`forecast` フィールド**: RiskExplanation に 30日先予測テキスト + forecast_data を追加
- **`trend_data` フィールド**: 過去90日の統計的トレンドデータ (slope, R², direction)
- **`_linear_regression()`**: 純Python実装の線形回帰 (intercept, slope, R², residual_std)
- **`_generate_forecast()`**: 線形回帰ベースの予測 + 95%信頼区間 (外挿不確実性考慮)
- **`_generate_trend_text()` 強化**: 履歴データ利用時は実測値ベースのトレンド分析
- **`_get_location_history()`**: data/score_history.json からの自動履歴読み込み
- **`score_history` 引数**: explain_score() に履歴データを直接渡すオプション

### テスト結果
- 履歴なし: 定性的予測を正常生成
- 履歴あり (20ポイント): `30日後のスコアは86±3と予測（95%信頼区間: 84〜90）`
- 線形回帰: R²=0.997 (テストデータ)

---

## G-2: 異常パターンの自動分類

**ファイル**: `features/monitoring/pattern_classifier.py`

### 既存機能 (確認済み)
- PatternClassifier (ルールベース) — 5パターン + UNKNOWN
- SANCTION_EVENT / CONFLICT_OUTBREAK / DISASTER_STRIKE / ELECTION_IMPACT / ECONOMIC_CRISIS
- 歴史的前例データベース (15件)
- パターンシグネチャマッチング (primary/secondary次元)

### 新規追加
- **`MLPatternClassifier` クラス**: RandomForest ベースのML分類器
- **タイムウィンドウ特徴量**: 150次元 (24次元×delta/abs + 統計量6 + 4ウィンドウ×24次元)
  - 現在のデルタ + 絶対値 (48)
  - 統計量: max/min/mean/std/positive_count/negative_count (6)
  - 7日/14日/30日/90日のウィンドウ別デルタ (96)
- **`_generate_synthetic_training_data()`**: 合成訓練データ生成 (パターンシグネチャベース)
- **`train()` メソッド**: 5-fold CV + モデル保存 (pickle)
- **ハイブリッド分類 (ensemble)**: ML + ルールベースの信頼度統合
  - 一致時: 信頼度ブースト (+0.1)
  - 不一致時: 差が0.15超で高信頼側採用、拮抗時はML優先
- **`classify_from_history()`**: 時系列スナップショットからタイムウィンドウ自動構築

### テスト結果
- 合成データ CV精度: 1.000 (600サンプル, 6クラス)
- 制裁イベント分類: pattern=sanction_event, confidence=0.66
- 紛争勃発分類: pattern=conflict_outbreak, confidence=0.68

---

## G-3: サプライヤークラスタリングの高精度化

**ファイル**: `features/analytics/portfolio_analyzer.py`

### 既存機能 (確認済み)
- cluster_by_risk() — KMeans (元の実装)
- **cluster_by_risk_enhanced()** — DBSCAN / Hierarchical / KMeans 選択可能
- **UMAP** 2D次元削減 (umap-learn インストール済み, PCAフォールバック)
- **シルエットスコア** 計算
- **Plotly** インタラクティブHTML可視化 (generate_risk_map_html)

### 新規追加
- **umap-learn インストール**: pip install umap-learn (v0.5.11)
- **出力パス変更**: `data/risk_map.html` → `reports/risk_map_{date}.html` (日付スタンプ)

### テスト結果
- DBSCAN: clusters=1, outliers=3 (小データ), reduction=umap
- KMeans: clusters=2, reduction=umap
- HTML生成: reports/risk_map_20260327.html (9,252 bytes)

---

## G-4: 需要予測との連携設計

**ファイル**: `features/analytics/demand_risk_integration.py`

### 既存機能 (確認済み — 全て実装済み)
- **DemandRiskIntegrator.evaluate_supply_risk_for_forecast()**: 部品別供給リスク評価
- **SupplyRiskAssessment** データクラス: 総合リスク・不足確率・ボトルネック部品
- ロジスティック関数による **供給不足確率** 試算
- **3シナリオ分析** (best/base/worst)
- **simulate_demand_shock()**: 需要急増シミュレーション
- **recommend_procurement_strategy()**: 6種の調達戦略推奨
  - 安全在庫積み増し / マルチソーシング / 前倒し調達 / 代替材料 / 契約見直し / モニタリング強化

### テスト結果
- 3部品テスト: overall_supply_risk=52.6, shortage_prob=60.3%
- ボトルネック検出: 3部品 (希土類磁石, 半導体チップ, リチウム電池)
- シナリオ: best=24.2%, base=60.3%, worst=95.0%
- 需要ショック(2x): severity=57.5

---

## パッケージ追加
- `umap-learn==0.5.11` (+ llvmlite, numba, pynndescent)

## ファイル変更一覧
| ファイル | 変更内容 |
|---------|---------|
| features/analytics/explainability.py | forecast/trend_data追加, 線形回帰予測, 履歴読み込み |
| features/monitoring/pattern_classifier.py | MLPatternClassifier追加, RandomForest, タイムウィンドウ特徴量 |
| features/analytics/portfolio_analyzer.py | HTML出力パスをreports/risk_map_{date}.htmlに変更 |
| features/analytics/demand_risk_integration.py | 変更なし (既に完全実装) |
