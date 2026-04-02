# SCRI v1.1.0 ROLE-B 完了レポート: デジタルツイン分析エンジン

**完了日時**: 2026-03-28
**ステータス**: 全4エンジン実装・テスト完了

## 実装ファイル

| ファイル | クラス | 行数 |
|---------|--------|------|
| `features/digital_twin/__init__.py` | (パッケージ初期化) | 22 |
| `features/digital_twin/stockout_predictor.py` | `StockoutPredictor` | ~280 |
| `features/digital_twin/production_cascade.py` | `ProductionCascadeSimulator` | ~340 |
| `features/digital_twin/emergency_procurement.py` | `EmergencyProcurementOptimizer` | ~320 |
| `features/digital_twin/facility_risk_mapper.py` | `FacilityRiskMapper` | ~380 |

## B-1: 在庫枯渇予測エンジン (`StockoutPredictor`)

### メソッド
- `predict_stockout(part_id, location_id, risk_context)` — 単一部品の枯渇予測
- `scan_all_parts(location_id, risk_threshold)` — 全部品一括スキャン
- `simulate_risk_event(scenario, affected_countries, duration_days)` — シナリオ別影響シミュレーション

### テスト結果
- P-003 (USB-C, Taiwan): gap=32.9日, severity=CRITICAL
- 全8部品スキャン: CRITICAL=4, MEDIUM=1, OK=3
- 台湾海峡封鎖シナリオ: 影響2部品

### 計算ロジック
- `current_stock_days = stock_qty / daily_consumption`
- `risk_adjusted_lead_time = lead_time_days × (1 + risk_score/200)`
- `gap_days = risk_adjusted_lead_time - current_stock_days`
- severity: CRITICAL(>14日gap), HIGH(>7日), MEDIUM(>0日)

## B-2: 生産停止カスケードシミュレーター (`ProductionCascadeSimulator`)

### メソッド
- `simulate_part_shortage(part_id, shortage_start_date, shortage_days, bom_result)` — カスケードシミュレーション
- `find_critical_path(product_id, production_date)` — 最長リードタイム経路特定
- `calculate_production_resilience(plant_id)` — 生産回復力スコア

### テスト結果
- P-001 (MCU) 60日欠品: 3アセンブリ・3製品に影響、総損失 ¥5,415,000,000
- クリティカルパス: 63日 (PROD-EV-01)
- 回復力スコア: 96 (HIGH)

### 特徴
- networkx DiGraphでBOM依存関係をモデル化
- 安全在庫バッファ考慮の生産停止タイミング算出
- 単一調達源率・安全在庫充足率・代替サプライヤー確立率の3軸評価

## B-3: 緊急調達最適化エンジン (`EmergencyProcurementOptimizer`)

### メソッド
- `optimize_emergency_order(part_id, required_qty, deadline_date, budget_limit_jpy)` — 最適発注先選定
- `calculate_total_cost_of_risk(part_id, scenario, duration_days, annual_production_units)` — リスクコストROI

### テスト結果
- P-001 緊急3000個: 推奨=STMicro (France), ¥3,187,500
- scipy.linprog (HiGHS) による分割発注最適化成功
- P-006 中国制裁90日ROI: 3.85 → 「予防投資を強く推奨」

### 特徴
- コスト(40%) + リスク(30%) + 品質(15%) + 納期遵守(15%) の複合スコア
- scipy.optimize.linprog によるマルチサプライヤー分割発注最適化
- リスク顕在化コスト vs 予防コストの定量ROI分析

## B-4: 拠点リスクヒートマップ (`FacilityRiskMapper`)

### メソッド
- `map_facility_risks(locations)` — 全拠点リスクマッピング
- `identify_concentration_risk(locations)` — 地理的集中リスク分析

### テスト結果
- 6拠点マッピング: MEDIUM=2, LOW=4
- HHI=0.5858 (CRITICAL)
- アラート: 台湾海峡チョークポイント依存87%, 日本集中75%, 台風経路87%

### 特徴
- GDACSリアルタイム災害アラート統合 (500km圏内)
- Haversine公式による最寄りチョークポイント距離算出
- 台風経路上の季節リスク分析
- HHI (Herfindahl-Hirschman Index) による国別集中度評価

## InternalDataStore フォールバック

ROLE-Aの `pipeline/internal/internal_data_store.py` が未作成のため、全エンジンでサンプルデータによるフォールバック実装を使用。InternalDataStoreが作成され次第、try/exceptで自動的に切り替わる構造。

## サンプルデータ

- **8部品**: MCU, MLCC, コネクタ, MOSFET, コンデンサ, 電池セル, CANトランシーバ, 抵抗器
- **3製品**: EV制御ユニット, 車載バッテリーパック, 車載センサーモジュール
- **6拠点**: 名古屋工場, 大阪工場, バンコク工場, 横浜倉庫, 深圳工場, シンガポール倉庫
- **サプライヤー候補**: 部品ごとに2-3社の緊急調達先（価格・リードタイム・品質評価付き）
