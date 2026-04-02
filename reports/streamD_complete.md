# STREAM D: 分析機能の深化 — 完了報告

**バージョン**: SCRI v0.9.0
**完了日**: 2026-03-27

## D-1: サプライチェーン脆弱性スコア（第25次元）

**ファイル**: `scoring/dimensions/supply_chain_vulnerability_scorer.py`

### 実装済み5コンポーネント
| コンポーネント | 内部重み | 説明 |
|---|---|---|
| 調達集中度 HHI | 30% | ハーフィンダール指数によるサプライヤー集中度 |
| 単一調達源率 | 25% | sole_source部品のコスト比率 |
| 平均リードタイム | 15% | 14/30/60/90日閾値による線形補間 |
| 代替調達国 | 20% | 代替国数に応じた逆リスク(0国=90, 8+国=5) |
| 在庫バッファ日数 | 10% | バッファ/リードタイム比率でカバレッジ判定 |

### engine.py 統合
- **重み**: 3% (`sc_vulnerability: 0.03`)
- **既存21次元**: 全て `×0.97` で比例縮小（合計1.0維持）
- `SupplierRiskScore.WEIGHTS` を23キーに拡張
- `calculate_overall()`, `to_dict()`, `_data_quality_summary()` を25次元対応に更新
- `config/constants.py` の `DIMENSIONS` を24→25に更新

## D-2: ルートリスクの精緻化

**ファイル**: `features/route_risk/enhanced_analyzer.py`

### 実装済み機能
- **季節性リスク調整**: `SEASONAL_ADJUSTMENTS` テーブル（台風+20, モンスーン+15, 冬季結氷+30, スエズ酷暑+5）
- **代替ルートテーブル**: スエズ→喜望峰(+12日/$180K), パナマ→マゼラン(+8日/$120K), マラッカ→ロンボク(+3日/$45K), 台湾→ルソン(+2日/$30K)
- **迂回コスト試算**: 日次運行コスト($40K/day) + 保険追加料(5%) + 貨物タイプ別係数(7種)
- **統合分析**: `analyze_route()` がベース分析→季節性→代替ルート→推奨事項を一括出力

## D-3: 在庫・リードタイム最適化提案

**ファイル**: `features/analytics/inventory_optimizer.py`

### 実装済み機能
- **`recommend_safety_stock(bom_result, service_level=0.95)`**: リスク調整済み安全在庫推奨
  - サービスレベル→Z値変換（0.90〜0.995対応）
  - リスクレベル別倍率: CRITICAL=2.5x, HIGH=2.0x, MEDIUM=1.5x, LOW=1.0x, MINIMAL=0.7x
- **`calculate_tradeoff()`**: 在庫コスト増 vs リスク軽減効果のROI分析
  - 対数的リスク軽減効果（収穫逓減モデル）
  - 優先度別サマリ付きレポート生成

## D-4: サプライヤー多様化シミュレーター

**ファイル**: `features/analytics/diversification_simulator.py`

### 実装済み機能
- **`simulate_supplier_change(current, alternatives, cost_constraint=1.1)`**:
  - リスク改善量・コスト増加額・移行期間推定
  - 逆数比例配分による最適分割探索
  - コスト制約内再最適化
- **`generate_transition_plan()`**: 3フェーズ移行計画
  - Phase 1: 準備・検証（30%期間、10%テスト発注）
  - Phase 2: 段階的移行（40%期間、目標の70%まで）
  - Phase 3: 完了・安定化（30%期間、最終比率到達）
- 国別リスクベースライン: 20カ国、地域判定（Asia/Europe/Americas）
- 実現可能性3段階判定: FEASIBLE / CHALLENGING / NOT_RECOMMENDED

## D-5: 業界別リスクベンチマーク強化

**ファイル**: `features/analytics/benchmark_analyzer.py`

### 15業種プロファイル（完全）
| # | 業種キー | 説明 | リスク許容度 |
|---|---|---|---|
| 1 | automotive | 自動車 | MEDIUM |
| 2 | semiconductor | 半導体 | LOW |
| 3 | pharma | 製薬 | LOW |
| 4 | apparel | アパレル | HIGH |
| 5 | energy | エネルギー | HIGH |
| 6 | aerospace | 航空宇宙 | LOW |
| 7 | food_beverage | 食品・飲料 | MEDIUM |
| 8 | chemical | 化学 | MEDIUM |
| 9 | medical_device | 医療機器 | LOW |
| 10 | construction | 建設・建材 | HIGH |
| 11 | telecom | 通信 | LOW |
| 12 | defense | 防衛 | LOW |
| 13 | textile | 繊維 | HIGH |
| 14 | mining | 鉱業 | HIGH |
| 15 | logistics | 物流 | MEDIUM |

各プロファイルに `critical_dimensions`, `critical_materials`, `regulatory`, `weight_overrides` を定義。

## 検証結果
- 全6ファイルの構文チェック: PASS
- engine.py WEIGHTS合計: 1.0000 (23キー、25次元)
- 業種数: 15/15
- Python 3.11互換: 確認済み
