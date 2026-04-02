# SCRI v1.4.0 TASK 5-7 完了報告

**日付**: 2026-04-03
**バージョン**: 1.4.0

---

## TASK 5: RiskAdjuster（リスク調整レイヤー）

**ファイル**: `features/tourism/risk_adjuster.py` (新規)

### 実装内容
- `RiskAdjuster` クラス: シナリオベースの期待損失計算
- **6カ国のリスクシナリオ定義**: CN(4件), KR(3件), TW(3件), US(2件), AU(2件), TH(2件)
- **3シナリオモード**: optimistic / base / pessimistic
- **SCRI動的調整**: trigger_dimensionのSCRIスコアが50超→確率上方修正
  - `scri_boost = (score - 50) / 100` で±0.5の範囲で確率を動的調整
- **期待損失上限**: 90%
- `calculate_expected_loss()`: 国別シナリオの確率×影響率を積算
- `apply_risk_adjustment()`: ベースライン × (1 - expected_loss)、P10は更に下方拡大

---

## TASK 6: 集計エンジン改訂

**ファイル**: `features/tourism/inbound_aggregator.py` (更新)

### 改修内容
- **統合パイプライン**: Dual-Scale → Bayesian更新 → RiskAdjuster → 積み上げ
- `_predict_country()`: Dual-Scale優先、重力モデルフォールバック
- `_apply_bayesian()`: 実績データがあれば粒子フィルタで事後分布を更新
- `calculate_japan_total()` に `risk_scenario`, `scri_scores`, `actuals` パラメータ追加
- `pipeline_info` で使用モジュールの追跡（dual_scale_used/bayesian_used/risk_adjuster_used）
- 各モジュールは `try/except` で囲み、未実装時は既存フォールバック動作を維持

### MCP連携確認
- `mcp_server/server.py` に `_risk_adjuster` インポート追加
- `forecast_japan_inbound` / `forecast_prefecture_inbound` はフォールバック経由で動作維持
- InboundAggregator初期化時にDual-Scale/RiskAdjusterを自動ロード

---

## TASK 7: テスト追加

**ファイル**: `tests/test_tourism_advanced.py` (新規)

### テスト結果: 22/22 PASSED

| クラス | テスト数 | 内容 |
|--------|----------|------|
| TestRiskAdjuster | 8 | 期待損失順序(楽観<ベース<悲観)、正値、0-90%範囲、SCRI調整、未知国、リスク適用、ゼロ損失、シナリオ詳細 |
| TestBayesianUpdater | 6 | 初期化、上方シフト、リサンプリング、バッチ更新、事後キー、未初期化エラー |
| TestDualScaleIntegration | 5 | 予測値返却、短期比率優位性、未知国、short_term_ratios、パーセンタイル順序 |
| TestAggregatorIntegration | 3 | 沖縄台風リスク、北海道降雪リスク、都道府県シェア合計 |

### CHANGELOG更新
- v1.4.0セクションにDual-Scale/Bayesian/RiskAdjuster/テスト追加を追記

---

## 変更ファイル一覧

| ファイル | 操作 |
|----------|------|
| `features/tourism/risk_adjuster.py` | 新規作成 |
| `features/tourism/inbound_aggregator.py` | 改修（パイプライン統合） |
| `features/tourism/__init__.py` | RiskAdjuster/DualScaleModel追加 |
| `mcp_server/server.py` | _risk_adjuster インポート追加 |
| `tests/test_tourism_advanced.py` | 新規作成（22テスト） |
| `CHANGELOG.md` | v1.4.0追記 |
