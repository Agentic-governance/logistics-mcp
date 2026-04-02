# SCRI v1.4.0 TASK 3-4 完了レポート

## TASK 3: PPML国別シェア推計改訂

### 変更ファイル
- `features/tourism/gravity_model.py`

### 変更内容

**変数拡張（5→10説明変数）:**
| 変数名 | カテゴリ | 説明 | 事前係数 |
|--------|----------|------|----------|
| leave_utilization | 余暇proxy | 有給取得率 (0-1) | +0.25 |
| outbound_propensity | 余暇proxy | 出国傾向率 (アウトバウンド/人口) | +0.30 |
| travel_momentum | 余暇proxy | TMI (0-1), TASK1-B生成 | +0.20 |
| ln_restaurant | 文化関心proxy | 日本食レストラン指数の対数 | +0.15 |
| ln_lang_learners | 文化関心proxy | 日本語学習者数の対数 | +0.12 |

**ハードコードデータ:**
- LEAVE_UTILIZATION: 11カ国
- OUTBOUND_PROPENSITY: 11カ国
- RESTAURANT_INDEX: 11カ国 (2019=100)
- LANGUAGE_LEARNERS: 11カ国（千人、国際交流基金2021年調査ベース）
- TRAVEL_MOMENTUM_DEFAULT: 11カ国（TASK1-B未実装時のフォールバック）

**改修メソッド:**
- `_build_design_matrix()`: 新5変数をデザイン行列に追加
- `_build_future_X()`: 将来予測で新変数を反映（シナリオオーバーライド対応）
- `decompose_forecast_by_variable()`: 10変数の寄与分解
- `_fallback_priors()`: 拡張変数の事前係数を含む
- `summary()`: 10変数表示に対応

### 推定結果
- 手法: PPML_HC3 (Poisson GLM + HC3ロバスト標準誤差)
- 観測数: 88 (11カ国 x 8年)
- McFadden pseudo R2: 0.9874
- 収束: OK

**注記:** 新変数（leave_utilization等）は国別で時間不変のため、国固定効果との完全共線性が発生し標準誤差が非常に大きい。これはグラビティモデルの既知の識別問題であり、固定効果を除外した推定や、Hausman-Taylor推定量での対応が今後の課題。

---

## TASK 4: ベイズ更新層 (Sequential Monte Carlo)

### 新規ファイル
- `features/tourism/bayesian_updater.py`

### BayesianUpdater クラス

**アルゴリズム:** Sequential Monte Carlo (粒子フィルタ)

| メソッド | 機能 |
|----------|------|
| `__init__(n_particles=1000)` | 粒子数指定で初期化 |
| `initialize(forecast)` | 予測分布(median/p10/p90)から正規近似で粒子生成 |
| `update(actual, month_index)` | 単月実績で尤度更新、ESS<N/2で系統的リサンプリング |
| `update_batch(actuals)` | 複数月一括更新（None=スキップ） |
| `get_posterior()` | 重み付き事後分位点(p10/p25/median/p75/p90) + ESS |
| `get_update_log()` | 更新履歴 |

**技術詳細:**
- 尤度: N(actual | particle, sigma_obs), sigma_obs = max(actual*0.03, 100)
- リサンプリング: 系統的リサンプリング（多項より低分散）
- 分位点: 重み付きパーセンタイル計算
- 数値安定性: ログ尤度のmax引き、非負制約、退化時のリセット

### __init__.py 更新
- `BayesianUpdater` のlazy importを追加

### 検証結果
- 構文チェック: 全3ファイル OK
- インポートチェック: OK
- PPML fit + 予測 + ベイズ更新の統合テスト: OK
