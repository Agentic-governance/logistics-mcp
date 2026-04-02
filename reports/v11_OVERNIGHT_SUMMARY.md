# SCRI v1.1.0 Overnight Summary

Generated: 2026-03-28

## Version Comparison

| Metric | v0.3.0 | v1.0.0 | v1.1.0 |
|--------|--------|--------|--------|
| Python Files | 67 | 247 | 248 |
| Total LOC (Python) | ~7,300 | ~66,500 | ~67,240 |
| Risk Dimensions | 22 | 26 | 26 |
| MCP Tools | 9 | 48 | 54 |
| API Routes (main.py) | 39 | 72 | 72 |
| API Routes (routers) | 0 | 26 | 26 |
| API Routes (total) | 39 | 98 | 98 |
| Dashboard Tabs | 0 | 8 | 10 |
| Dashboard Lines | 0 | 1336 | 1797 |
| Test Files | 0 | 14 | 15 |
| Monitoring Countries | 50 | 50 | 50 |
| External Data Sources | 30+ | 95+ | 95+ |
| Sanctions Sources | 5 | 10 | 10 |

## v1.1.0 Changes (ROLE-E)

### E-1: Dashboard — Digital Twin + Scenario Simulator
- **Tab 9: Digital Twin**
  - 上段: サマリーカード4枚（CRITICAL部品/30日内停止リスク/HIGH輸送便数/曝露額合計）
  - 中段左: 在庫枯渇ウォッチリスト（色分け: 赤<7日/黄<14日/青<30日）
  - 中段右: Leaflet.js 拠点リスクマップ（CDN 1.9.4、リスクスコア色分けマーカー）
  - 下段: 輸送便リスクリスト（便名/出発地/到着地/モード/スコア/レベル/チョークポイント）
  - API呼び出し: /api/v1/twin/stockout-scan, /api/v1/twin/facility-risks, /api/v1/twin/transport-analysis
  - デモデータフォールバック付き

- **Tab 10: Scenario Simulator**
  - シナリオ選択: suez_closure / china_lockdown / taiwan_blockade
  - 期間スライダー: 7-180日
  - 結果: 影響部品数/生産停止リスク/財務影響/回復予測日数
  - Plotly.js カスケードタイムライン + 財務影響円グラフ
  - API呼び出し: /api/v1/twin/scenario

### E-2: Test Suite
- **tests/test_digital_twin.py** (新規: 29テストケース)
  - TestLogisticsImporter: 6テスト（CSV読込/日本語別名/バリデーション/エンコーディング検出/パストラバーサル防止）
  - TestInternalDataStore: 2テスト（UPSERT/発注挿入）
  - TestStockoutPredictor: 6テスト（正常系/未知部品/空ID/需要倍率/負値デフォルト/全部品スキャン）
  - TestProductionCascade: 4テスト（カスケード伝播/未知部品/二重計上防止/クリティカルパス）
  - TestEmergencyProcurement: 4テスト（基本最適化/予算制約/未知部品/リスク総コスト）
  - TestTransportRisk: 4テスト（海上コスト/航空コスト/チョークポイント検出/一括分析）
  - TestFacilityRiskMapper: 3テスト（リスクマップ/集中度/インスタンス化）
  - 全29テスト: 外部API呼び出しなし（mock/サンプルデータで完結）

### E-3: Test Results
- **Total: 194 passed, 3 failed, 2 deselected** (95.62s)
- test_digital_twin.py: 29/29 passed (0.92s)
- 既存テスト: 破壊なし
- Pre-existing failures (3件, 全てネットワークタイムアウト):
  - test_goods_layer::test_analyze_product_structure (EDINET API rate limit timeout)
  - test_goods_layer::test_analyze_bom (同上)
  - test_goods_layer::test_analyze_goods_layer_empty_bom (同上)

### E-4: Metrics
- MCP Tools: 54 (@mcp.tool count in mcp_server/server.py)
- API Routes: 98 total (72 in main.py + 26 in routers)
- Python Files: 248
- Dashboard: 1797 lines, 10 tabs

### E-5: Version Updates
- config/constants.py: VERSION = "1.1.0"
- CHANGELOG.md: v1.1.0 エントリ追加
- Dashboard header: v1.1.0
- Dashboard footer: v1.1.0

## Architecture Overview (v1.1.0)

```
supply-chain-risk/
  config/          — 定数・設定 (constants.py, leading_indicators.yaml)
  scoring/         — 26次元リスクスコアリングエンジン
  pipeline/        — 95+ 外部データソースクライアント
    internal/      — 内部ロジスティクスデータ (CSV/SQLite)
  features/
    digital_twin/  — デジタルツイン分析エンジン群 (v1.1.0)
      stockout_predictor.py      — 在庫枯渇予測
      production_cascade.py      — 生産停止カスケード
      emergency_procurement.py   — 緊急調達最適化
      facility_risk_mapper.py    — 拠点リスクマッパー
      transport_risk.py          — 輸送リスク分析
    analytics/     — ポートフォリオ/BOM/ベンチマーク分析
    graph/         — 統合知識グラフ (NetworkX)
    route_risk/    — チョークポイントルートリスク
    timeseries/    — 時系列データ/予測
    monitoring/    — 異常検知/メトリクス
  api/             — FastAPI REST (98 routes)
    routes/        — twin.py, bom.py, batch.py, internal.py, webhooks.py
  mcp_server/      — FastMCP SSE (54 tools)
  dashboard/       — Plotly.js + D3.js + Leaflet.js HTML (10 tabs)
  tests/           — 15 test files
```
