# Changelog

## [1.4.0] - 2026-04-03
### Added — Advanced Forecasting Pipeline (高度予測パイプライン)
- **Dual-Scale Model** (`features/tourism/dual_scale_model.py`): 短期(Transformer的注意機構) + 長期(PPML構造重力)の統合、ロジスティック混合比率
- **Bayesian Updater** (`features/tourism/bayesian_updater.py`): Sequential Monte Carlo粒子フィルタ、実績値による逐次分布更新、系統的リサンプリング
- **Risk Adjuster** (`features/tourism/risk_adjuster.py`): 6カ国×シナリオ別期待損失、SCRI動的確率調整、楽観/ベース/悲観3シナリオ
- **Aggregator改訂** (`features/tourism/inbound_aggregator.py`): Dual-Scale→Bayesian→RiskAdjuster統合パイプライン
- **テスト追加** (`tests/test_tourism_advanced.py`): RiskAdjuster/BayesianUpdater/DualScaleModel/Aggregator統合テスト 20+ケース

### Added — Dashboards (ダッシュボード刷新)
- **Logistics Risk Dashboard** (`dashboard/logistics.html`): D3.js + TopoJSON 世界地図、国リスク塗り分け、海路5本/空路5本、チョークポイント7箇所（脈動アニメーション）、40カ国データ、次元切替、詳細パネル
- **Inbound Tourism Risk Dashboard** (`dashboard/inbound.html`): 世界地図（12市場リスク）+ 日本地図（47都道府県 TopoJSON）、市場ランキング、都道府県別来訪者予測
- **Landing Page** (`dashboard/index.html`): 3ダッシュボードへのカード型リンク
- Legacy dashboard preserved as `dashboard/legacy.html`

### Changed — Tourism Demand Model (観光需要モデル根本再設計)
- **PPML構造重力モデル**: OLS → Poisson GLM (Santos Silva & Tenreyro, 2006)
  - ゼロ対応（コロナ期データをそのまま扱える）
  - ソース国固定効果 + 年固定効果で多辺的抵抗を吸収
  - pseudo R² = 0.9874, 為替弾性値 = -1.12
- **STL季節分解**: コロナ前2015-2019データから国別季節パターン抽出
- **ボトムアップ集計**: モンテカルロ1000回で不確実性伝播、都道府県×国別シェア行列
- **ベイズ的予測**: 係数事後分布からサンプリング → p10/p25/p50/p75/p90の確率分布
- **ダッシュボード**: シナリオ切替 → 確率分布帯グラフに変更
- 2 new MCP tools: forecast_japan_inbound, forecast_prefecture_inbound
- 3 new API endpoints: /tourism/japan-forecast, /prefecture-forecast, /decompose-forecast
- テスト修正: test_tourism_gravity.py を新PPML APIに適合（13テスト修正）

### Changed
- VERSION: 1.3.0 → 1.4.0
- FastAPI: `/dashboards` StaticFiles マウント追加（html=True）

## [1.3.0] - 2026-04-02

### Added — Tourism Statistics Pipeline (観光統計パイプライン)
- **Source Market Clients** (`pipeline/tourism/source_markets/`): 6カ国個別クライアント (China/Korea/Taiwan/US/Australia/Others) + World Bankフォールバック
- **Competitor Destination Clients** (`pipeline/tourism/competitors/`): タイ・韓国・台湾・欧州3カ国(FR/ES/IT)のインバウンド統計 + 統合CompetitorDB
- **Tourism Statistics DB** (`data/tourism_stats.db`): 4テーブル (outbound_stats/inbound_stats/japan_inbound/gravity_variables), 285行初期データ
- **Gravity Model DB Integration**: tourism_stats.dbからの自動訓練データ構築 + auto_refit()
- **Flight Supply Client**: OpenFlights routes.dat パース、15カ国の2019-2025容量指数
- **Regional Distribution Model**: 47都道府県分配、国籍バイアス6カ国、季節バイアス4種
- **Inbound Tourism Risk Scorer**: 需要側(50%)+供給側(30%)+日本側(20%)の3カテゴリ統合
- **Bootstrap Script** (`scripts/bootstrap_tourism_stats.py`): 5年分一括取込

### Added — Capital Flow Risk (資金フローリスク 第27次元)
- **CapitalFlowRiskClient** (`pipeline/financial/capital_flow_client.py`): Chinn-Ito Index + IMF AREAER + SWIFT除外リスク
- **CapitalFlowScorer** (`scoring/dimensions/capital_flow_scorer.py`): 第27次元 (weight=0.03)
- 既存26次元を比例縮小して合計1.0維持

### Added — MCP Tools & API
- **7 new MCP tools** (total: 61): assess_inbound_tourism_risk, get_inbound_market_ranking, forecast_visitor_volume, analyze_competitor_performance, predict_regional_distribution, decompose_visitor_change, get_capital_flow_risk
- **7 new API endpoints** under `/api/v1/tourism/`

### Changed
- VERSION: 1.1.0 → 1.3.0
- DIMENSIONS: 26 → 27 (capital_flow追加)
- Gravity Model R² = 0.90 (15カ国×5年パネル, statsmodels OLS)

## [1.1.0] - 2026-03-28

### Added — Digital Twin Dashboard (デジタルツインダッシュボード)
- **Tab 9: Digital Twin**: サマリーカード4枚（CRITICAL部品数/30日内停止リスク/HIGH輸送便数/曝露額合計）、在庫枯渇ウォッチリスト（色分け: 赤7日/黄14日/青30日）、Leaflet.js 拠点リスクマップ、輸送便リスクリスト
- **Tab 10: Scenario Simulator**: suez_closure/china_lockdown/taiwan_blockade、7-180日スライダー、Plotly.jsタイムライン・円グラフ、影響部品一覧・財務影響内訳
- **Leaflet.js CDN 1.9.4**: 拠点マーカーのリスクスコア色分け・ポップアップ

### Added — Test Suite (テスト拡充)
- **tests/test_digital_twin.py**: 7テストクラス、27テストケース（外部API呼び出しなし）
  - TestLogisticsImporter: CSV読込/日本語別名マッピング/バリデーション/エンコーディング検出/パストラバーサル防止
  - TestInternalDataStore: UPSERT/発注挿入
  - TestStockoutPredictor: 正常系/未知部品/空ID/需要倍率/負値デフォルト
  - TestProductionCascade: カスケード伝播/未知部品/二重計上防止
  - TestEmergencyProcurement: 基本計画/予算制約/未知部品
  - TestTransportRisk: 海上/航空/チョークポイント検出
  - TestFacilityRiskMapper: リスクマップ/集中度/シナリオ影響

### Changed
- VERSION: 1.0.0 → 1.1.0
- Dashboard: 8タブ → 10タブ (Digital Twin + Scenario Simulator)
- Dashboard: 1336行 → 1797行
- Dashboard header: v0.6.3 → v1.1.0
- Dashboard footer: v1.0.0 → v1.1.0

## [1.0.0] - 2026-03-28

### Added — Person Layer (人レイヤー完成)
- **OpenOwnership UBO Deep Chain**: タックスヘイブン35法域検出、シェル会社検出、利益相反検出 (`get_ownership_chain_deep_sync`, `find_shared_owners_sync`)
- **Wikidata Director Enrichment**: 兼任役員列挙 (`get_person_affiliations_sync`), 天下り検出28キーワード (`find_revolving_door_sync`)
- **ICIJ Offshore Risk Score**: 0-100のオフショアリスクスコア (`get_offshore_risk_score_sync`)
- **person_risk 第26次元**: UBO国リスク/PEP/制裁/オフショア/天下りの5要素、weight=0.04 (既存×0.96で合計1.0維持)

### Added — Unified Knowledge Graph (統合グラフエンジン)
- **SCIGraph** (`features/graph/unified_graph.py`): 4種ノード(企業/人物/製品/拠点) + 10種エッジのNetworkX MultiDiGraph統合知識グラフ
- **SanctionPathFinder** (`features/graph/sanction_path_finder.py`): BFS 3ホップ制裁検索 (1hop=100, 2hop=70, 3hop=40), 紛争鉱物パス検出(DFS), PageRankリスク伝播スコア
- **SCIGraphBuilder v2** (`features/graph/graph_builder_v2.py`): BOM→制裁→UBO→役員→通関の5段階自動構築パイプライン
- **GraphVisualizer** (`features/graph/graph_visualizer.py`): D3.js JSON / 隣接行列 / Mermaid 3形式出力

### Added — Analytics
- **NetworkVulnerabilityAnalyzer** (`features/analytics/network_vulnerability.py`): Betweenness Centrality, 橋ノード検出, カスケード障害シミュレーション, レジリエンススコア(0-100)
- **ProcurementOptimizer** (`features/analytics/procurement_optimizer.py`): scipy SLSQP (0.7×リスク+0.3×コスト最小化), 代替国提案
- **BenchmarkAnalyzer拡張**: `benchmark_bom_against_industry()` 15業種BOM統合ベンチマーク

### Added — Data Quality
- **ImportYeti品質改善**: 31社99エイリアス逆引き, ファジーマッチ重複排除, 6要素品質スコア
- **HS_PROXY自動更新** (`scripts/update_hs_proxy.py`): Comtrade API 13HSコード×10カ国
- **制裁品質レポート** (`scripts/sanctions_quality_report.py`): 12ソース自動品質分析
- **欠損補完** (`scripts/fill_all_dimensions.py`): 50カ国×25次元エンジン計算+10地域デフォルト
- **BACI代替構築** (`scripts/build_hs_proxy_from_comtrade.py`): 22HSコード×15製造国

### Added — Infrastructure
- **Dashboard タブ8** Supply Chain Graph: D3.js force-directed graph, 制裁パスハイライト
- **SmartCache** (`features/cache/smart_cache.py`): Redis/SQLiteデュアルバックエンド, ヒット率カウンター
- **エラー標準化** (`features/errors/error_types.py`): 5カテゴリ例外 + グローバルハンドラー
- **バッチSSE** (`api/routes/batch.py`): 10件分割 + SSEストリーミング + キャッシュヒット率
- **5 new MCP tools**: `find_sanction_network_exposure`, `build_supply_chain_graph_tool`, `get_network_risk_score`, `analyze_network_vulnerability`, `optimize_procurement` — total: 48

### Changed
- VERSION: 0.9.0 → 1.0.0
- DIMENSIONS: 25 → 26 (person_risk追加)
- WEIGHTS: 全既存次元 ×0.96 で比例縮小、person_risk=0.04 追加

## [0.9.0] - 2026-03-27

### Added — Goods Layer (物レイヤー完成)
- **ImportYeti US Customs Client** (`pipeline/trade/importyeti_client.py`): US Bill of Lading data scraping, company name fuzzy matching (RapidFuzz), rate-limited HTTP, async wrappers
- **IR Scraper** (`pipeline/corporate/ir_scraper.py`): EDINET API v2 (有報主要仕入先), SEC EDGAR 10-K, conflict minerals report (SD/Exhibit 1.01), batch Tier-1 graph builder
- **SAP ERP Connector** (`pipeline/erp/sap_connector.py`): EKKO/EKPO purchase order CSV/Excel import, MARA/MARC material master, EINA/EINE info records, 18+ Japanese/English column alias resolution, full-width normalization, BOM merge
- **BACI Trade Data Client** (`pipeline/trade/baci_client.py`): CEPII bilateral trade analysis, Comtrade cache fallback, HS proxy data generation, 90+ country code mapping
- **Goods Layer Unified API** (`features/goods_layer/unified_api.py`): GoodsLayerAnalyzer with priority cascade (SAP→ImportYeti→IR→BACI/Comtrade), confidence levels (CONFIRMED/PARTIALLY_CONFIRMED/INFERRED), BOM batch analysis, data completeness reporting
- **4 new MCP tools**: `find_actual_suppliers` (US customs verification), `build_supply_chain_from_ir` (IR-based graph), `get_conflict_minerals_status` (3TG check), `analyze_product_complete` (unified analysis) — total: 36
- **BACI Download Script** (`scripts/download_baci.py`): 3 modes (instructions/verify/process), 38 relevant HS4 codes, SQLite builder

### Files Created — Goods Layer
- `pipeline/trade/importyeti_client.py` — ImportYetiClient (1080 lines)
- `pipeline/corporate/ir_scraper.py` — IRScraper (922 lines)
- `pipeline/erp/sap_connector.py` — SAPConnector with PurchaseRecord/MaterialRecord/InfoRecord
- `pipeline/erp/__init__.py` — ERP package exports
- `pipeline/trade/baci_client.py` — BACIClient with TradeFlow/Exporter
- `features/goods_layer/unified_api.py` — GoodsLayerAnalyzer
- `features/goods_layer/__init__.py` — Goods layer package exports
- `scripts/download_baci.py` — BACI data download/processing script

### Added — ROLE-1 (Data Engineer)
- **Comtrade Cache Normalization**: All 22 cache files normalized (share sums fixed to 1.0 from 0.62-0.95)
- **HS_PROXY_DATA Expansion**: 8 → 15 HS codes (+7: vehicles/8703, auto_parts/8708, wire/8544, lens/9013, silicon_raw/2804, refined_copper/7403, plastic_film/3920)
- **Country Coverage Expansion**: +7 countries across HS codes (India, Vietnam, Thailand, Mexico, Poland, Hungary, Czech Republic)
- **HS_MATERIAL_MAP**: +7 entries (vehicle, auto_parts, wire, lens, silicon_raw, refined_copper, plastic_film)
- **HS_RAW_MATERIAL_CHAIN**: +5 entries (8703, 8708, 8544, 9013, 3920)
- **DIMENSION_FRESHNESS**: 24-dimension freshness dict with accurate per-source update intervals (replaces generic thresholds)
- **Enhanced `check_data_freshness()`**: Improved severity logic (realtime/daily → WARNING, longer-cycle → INFO/WARNING)

### Added — ROLE-2 (ML Engineer)
- **Statistical Anomaly Detection**: `_compute_statistical_threshold()` with z-score-based detection (mean ± 2σ at 30+ data points, WARNING at |z|>2.0, CRITICAL at |z|≥3.0)
- **First-Score Guard**: Suppresses false alerts on initial data (no delta-based alerts when no previous score exists)
- **History Accumulation**: Extended history format with `overall_history` and `dim_histories` lists for statistical analysis
- **Leading Indicators Config**: `config/leading_indicators.yaml` with 16 top-ranked indicators (|r|>0.38) and 6 generalized cross-dimension patterns
- **ForecastMonitor.load_leading_indicators()**: PyYAML primary + line-by-line fallback loader for leading indicator config
- **EnsembleForecaster Backtest Documentation**: 16-feature LightGBM set with theoretical importance ranking (ready when 65+ days accumulate)

### Added — ROLE-3 (Product Engineer)
- **BOM Sample: Premium Smartphone** (`data/bom_samples/smartphone_premium.json`): 24 parts, 8 countries, $441.25 total
- **BOM Sample: Wind Turbine 8MW** (`data/bom_samples/wind_turbine.json`): 18 parts, 10 countries, $2,010,100 total
- **Multi-Currency Support**: CURRENCY_RATES (JPY, EUR, GBP, CNY, KRW, TWD, CHF) with `output_currency` parameter on `estimate_disruption_cost()` and `compare_scenarios()`
- **Enhanced Bottleneck Detection**: New types `cost_concentration` (>25% BOM cost) and `sanctioned_country` (9-country list); `bottleneck_type` field added to all bottleneck dicts
- **SANCTIONED_COUNTRIES List**: Russia, China, Iran, North Korea, Myanmar, Syria, Venezuela, Cuba, Belarus

### Added — ROLE-4 (Platform Engineer)
- **OpenAPI 3.0.3 Specification** (`docs/openapi_spec.yaml`): 75 paths, 35 schemas, full endpoint documentation
- **Dashboard: BOM Analysis Tab**: Interactive BOM upload, sample loading, risk visualization (Plotly), bottleneck panel
- **Dashboard: Cost Impact Tab**: Scenario selection, spend/revenue inputs, duration slider, comparison charts
- **In-Memory Rate Limiter** (`api/rate_limiter.py`): Sliding-window, 3 tiers (general 60/min, heavy 10/min, screening 30/min), thread-safe
- **Expanded Rate Limiting**: 53 previously unprotected endpoints now rate-limited (67 total)
- **Prometheus Metrics Module** (`features/monitoring/metrics.py`): 11 metric types, dependency-free, text exposition format
- **MCP Tools Catalog** (`docs/mcp_tools_catalog.md`): 32 tools documented with examples and integration guide

### Changed
- MCP tools: 32 → 36 (+4 goods layer tools)
- config/constants.py: VERSION bumped to 0.9.0
- features/reports/dd_generator.py: version bumped to 0.9.0
- api/main.py: version bumped to 0.9.0, +53 rate limit decorators
- pipeline/erp/sap_connector.py: expanded STANDARD_COLUMN_ALIASES (+購買伝票番号, +品目コード, +品目名称, +仕入先国)
- dashboard/index.html: 525 → 937 lines (+BOM Analysis, +Cost Impact tabs)
- features/analytics/tier_inference.py: HS_PROXY_DATA 8→15 codes, +7 countries, +7 material mappings
- features/monitoring/anomaly_detector.py: DIMENSION_FRESHNESS (24 entries), statistical anomaly detection, first-score guard
- features/timeseries/forecast_monitor.py: load_leading_indicators() method
- features/analytics/bom_analyzer.py: SANCTIONED_COUNTRIES, cost_concentration/sanctioned_country bottleneck types
- features/analytics/cost_impact_analyzer.py: CURRENCY_RATES, output_currency parameter
- data/comtrade_cache/: 22 files normalized (share sums → 1.0)

### Files Created
- `config/leading_indicators.yaml` — 16+6 leading indicator cross-correlation config
- `data/bom_samples/smartphone_premium.json` — Premium smartphone BOM (24 parts)
- `data/bom_samples/wind_turbine.json` — Offshore wind turbine BOM (18 parts)
- `docs/openapi_spec.yaml` — OpenAPI 3.0.3 specification (75 paths)
- `docs/mcp_tools_catalog.md` — MCP tools catalog (32 tools)
- `api/rate_limiter.py` — Sliding-window rate limiter
- `features/monitoring/metrics.py` — Prometheus metrics (11 types)

## [0.8.0] - 2026-03-27
### Added
- **BOM Risk Analysis Engine**: BOMAnalyzer with cost-weighted risk scoring, critical bottleneck detection, mitigation suggestions, and resilience scoring
- **Tier-2/3 Supply Chain Inference**: TierInferenceEngine using UN Comtrade bilateral trade data to probabilistically estimate hidden supply chain layers beyond Tier-1
- **BOM Importer**: Multi-format BOM import (CSV, Excel, JSON, SAP MM60) with column alias resolution
- **EnsembleForecaster (STREAM 3)**: LightGBM(0.6) + Prophet(0.4) ensemble forecasting with lag/time/statistical features, double exponential smoothing fallback, and hold-out backtest
- **Forecast Monitor (STREAM 3)**: Daily prediction accuracy tracking (data/forecast_accuracy.jsonl), cumulative MAE, model drift detection (7d MAE > 1.5x overall → retrain trigger)
- **Supplier Reputation Screening (STREAM 4)**: SupplierReputationScreener using GDELT v2 Article Search API, 5 categories (LABOR_VIOLATION +25, SANCTIONS +30, CORRUPTION +20, ENVIRONMENT +15, SAFETY +10), rate-limited batch screening, country-based fallback
- **Cost Impact Analyzer (STREAM 5)**: CostImpactAnalyzer with 5 disruption scenarios (sanctions/conflict/disaster/port_closure/pandemic), 4-component cost breakdown (sourcing premium, logistics extra, production loss, recovery cost), sensitivity analysis, scenario comparison
- 7 new MCP tools: `infer_supply_chain`, `analyze_bom_risk`, `get_hidden_risk_exposure`, `get_forecast_accuracy`, `screen_supplier_reputation`, `estimate_disruption_cost`, `compare_risk_scenarios` (total: 32)
- 14 new API endpoints: 6 under `/api/v1/bom/`, 3 under `/api/v1/forecast/`, 2 under `/api/v1/screening/`, 3 under `/api/v1/cost-impact/` (total: 85+)
- HS_MATERIAL_MAP: 20 materials mapped to HS codes for automatic Tier inference
- HS_PROXY_DATA: Static trade flow fallback for 7 HS codes x 4-8 importing countries
- EV Powertrain sample BOM (10 components, 6 countries, 5 critical parts)
- Comtrade cache builder script (`scripts/build_tier_inference_cache.py`) for 13 countries x 10 HS codes
- Scheduler: forecast_monitor daily job at 05:00 JST (8 jobs total)
### Changed
- MCP tools: 25 → 32
- API routes: 71 → 85+
- Scheduler jobs: 7 → 8 (added forecast_monitor)
- FastAPI version tag: 0.7.0 → 0.8.0
- Scheduler: manual `start()` call → automatic lifespan startup
- BOMRiskResult: added financial_exposure field (STREAM 5-C)
- BOMNode: added reputation_result field (STREAM 4-B)
- config/constants.py: VERSION bumped to 0.8.0
- features/reports/dd_generator.py: version bumped to 0.8.0

## [0.7.0] - 2026-03-21
### Added
- Prophet forecasting validation with backtest (MAE=8.49) and 286 leading indicator pairs
- Weekly automated correlation audit (APScheduler, Sunday 04:00 JST)
- Interactive Plotly.js dashboard (5 tabs: Risk Map, Portfolio, Correlation, Time Series, Alerts)
- Response standardization middleware (success/error envelope with meta)
- Batch endpoints: POST /api/v1/batch/risk-scores, POST /api/v1/batch/screen-sanctions
- Webhook notification system with HMAC-SHA256 signing
- 3 new MCP tools: compare_risk_trends, explain_score_change, get_risk_report_card
- Enhanced get_risk_score with dimensions filter, forecast, history, explain options
- WJP Rule of Law Index client (73 countries)
- Basel AML Index client (80 countries)
- V-Dem Democracy Index client (68 countries)
- Integration test suite (7 scenarios, 15 tests)
- GitHub Actions CI workflow
- Performance benchmark script
- Data coverage report (97.1% coverage)
- Leading indicators analysis (docs/LEADING_INDICATORS.md)
- Prometheus metrics middleware (GET /metrics)
- Daily automatic backup (timeseries.db + risk.db, 7-day retention)
- Enhanced /health endpoint (forecast status, correlation alerts, coverage, uptime)
- README.md complete rewrite with architecture diagram
- MCP Tools Catalog auto-generator (docs/MCP_TOOLS_CATALOG.md)
### Changed
- MCP tools: 22 → 25
- API routes: 64 → 71
- Tests: 15 → 32
- Dashboard: none → interactive HTML (Plotly.js, 5 tabs)
- Webhooks: none → HMAC-SHA256 signed
- Legal scoring: now blends WJP Rule of Law with existing baseline
- config/constants.py: VERSION bumped to 0.7.0
- features/reports/dd_generator.py: version bumped to 0.7.0

## [0.6.3] - 2026-03-21
### Fixed
- **japan_economy bug**: japan_economy=35 for all countries → now gated to Japan only (JP/Japan/JPN). Non-Japan countries get score=0, status="not_applicable".
- **sanctions bug**: sanctions=33 for all countries (fuzzy matching "test" entity name) → split into entity screening mode vs country-level risk mode. Uses SANCTIONED_COUNTRIES dict for country-level scoring (IR=90, KP=100, RU=70, SY=85, etc.). Clean countries (JP/DE/SG) now score 0.
- **compliance ↔ political correlation**: r=0.916 → r=0.643. Removed INFORM Risk Index from compliance (kept FATF + TI CPI), removed Fragile States Index from political (kept Freedom House only).
- **climate_risk ↔ political correlation**: r=0.931 → r=0.645. Removed readiness (governance) component from ND-GAIN formula. Climate vulnerability now uses physical exposure only (vulnerability * 100).
- **climate_risk ↔ conflict correlation**: r=0.917, classified as CAUSAL_ACCEPTABLE (conflict zones are genuinely in climate-vulnerable regions, not a data source overlap).
### Changed
- scoring/engine.py: japan_economy block gated to Japan-only; sanctions block split into entity/country modes with SANCTIONED_COUNTRIES dict
- pipeline/compliance/fatf_client.py: removed INFORM_RISK_INDEX, TI CPI weight increased to 70%
- pipeline/compliance/political_client.py: removed FRAGILE_STATES, Freedom House weight increased to 85%
- pipeline/climate/ndgain_client.py: formula changed from `vulnerability * 100 * (1 - readiness)` to `vulnerability * 100`
- scripts/diagnose_correlations.py: added `--countries` argparse flag, added climate_risk↔conflict to KNOWN_CAUSAL
- config/constants.py: updated compliance/political data source lists

## [0.6.2] - 2026-03-20
### Fixed
- **energy zero-variance**: Per-country energy import dependency scores (IEA/OWID data, 46 countries, range 5-80, std=24.7). Replaces fixed score=25 for all countries.
- **geo_risk ↔ legal correlation**: r=0.899 → r=0.608. Redefined geo_risk to focus on geopolitical tensions (territorial disputes, military conflicts) and legal on rule of law (contract enforcement, IP protection, judicial independence).
- **political cluster (maritime ↔ political)**: r=0.880 → r≈-0.25. Redefined maritime dependency to track actual shipping dependency and port infrastructure, not country development level.
### Changed
- pipeline/energy/commodity_client.py: `get_energy_risk()` now accepts `country` parameter; `_get_energy_risk_static()` returns per-country energy import dependency scores
- scoring/engine.py: passes `loc` to `get_energy_risk(country=loc)` for country-aware energy scoring
- pipeline/gdelt/monitor.py: GEO_RISK_BASELINE redefined for geopolitical tension (territorial disputes, diplomatic crises)
- scoring/legal.py: LEGAL_RISK_BASELINE redefined for WJP Rule of Law Index (contract enforcement, IP protection)
- pipeline/maritime/portwatch_client.py: MARITIME_DEPENDENCY redefined for actual shipping dependency and port infrastructure
- scripts/diagnose_correlations.py: v2.0 rewrite with 6-tier auto-classification (DOUBLE_COUNTING, SOURCE_PROBLEM, CAUSAL_ACCEPTABLE, METHODOLOGY_OVERLAP, MONITOR, ACCEPTABLE), SOURCE_MAP for all 24 dimensions, known causal relationships, static baseline overlap detection

## [0.6.1] - 2026-03-18
### Fixed
- 7 zero-variance scoring dimensions now return non-zero baseline scores when live APIs are unavailable:
  - **energy**: Static fallback (score=25) when FRED API key not set
  - **health**: Country name resolution for Disease.sh API + 50-country static baseline (scores 3-72)
  - **maritime**: Maritime dependency baseline for 50 countries (scores 5-48, converted to risk 1-16)
  - **aviation**: Country→airport mapping (51 countries) + aviation infrastructure baseline (scores 2-70)
  - **legal**: Legal risk baseline for 50 countries (scores 4-72) when Caselaw MCP unavailable
  - **geo_risk**: Geopolitical risk baseline for 50 countries (scores 3-75) when BigQuery unavailable
  - **typhoon**: Seasonal exposure baseline for 20 typhoon-prone countries (scores 5-30)
- Typhoon dimension: blends seasonal exposure baseline when no active storms detected (previously returned 0)
- Aviation dimension: blends infrastructure quality baseline when flight traffic is normal (previously returned 0)
- Added 9 missing countries to LOCATION_COORDS (Cambodia, Israel, Qatar, Sri Lanka, Poland, Netherlands, Switzerland, Argentina, Chile)
### Changed
- scoring/engine.py: typhoon block now uses TYPHOON_EXPOSURE when live API returns 0; aviation block imports AVIATION_BASELINE
- pipeline/weather/openmeteo_client.py: expanded LOCATION_COORDS from 41 to 50 entries
- pipeline/health/disease_client.py: added country name resolver and 50-country fallback
- pipeline/maritime/portwatch_client.py: added MARITIME_DEPENDENCY baseline
- pipeline/aviation/opensky_client.py: expanded airports (19→54), added country mappings (51), added baseline
- scoring/legal.py: added LEGAL_RISK_BASELINE for 50 countries
- pipeline/gdelt/monitor.py: added GEO_RISK_BASELINE for 50 countries
- pipeline/energy/commodity_client.py: fallback returns score=25 instead of 0

## [0.6.0] - 2026-03-18
### Added
- 50-country baseline scores: all PRIORITY_COUNTRIES scored across 24 dimensions, stored in TimeSeries DB
- Full correlation audit: 24×24 matrix with classification (SOURCE_PROBLEM/DOUBLE_COUNTING/ACCEPTABLE)
- 6 new data source clients: WHO GHO, IMF Fiscal Monitor, SIPRI, Global Peace Index, IATA Air Cargo, Lloyd's List
- Data quality flags in scoring engine: per-dimension status (ok/failed/not_applicable), confidence score
- MCP tool input validation: unified country/dimension/industry validators (mcp_server/validators.py)
- MCP response caching: TTLCache for get_risk_score(1h), screen_sanctions(24h), get_location_risk(1h), dashboard(30m)
- Test suite: 15 unit tests (analytics, scoring, sanctions) with 100% pass rate
- Enhanced scheduler: 5 jobs (full assessment/6h, critical/1h, sanctions/daily, correlation/weekly, health/hourly)
- Alert dispatcher: multi-channel (log/file/webhook), configurable thresholds, JSONL output
- API rate limiting: slowapi on 10 critical endpoints (60/30/10 req/min tiers)
- Input sanitization middleware: SQL injection, XSS, path traversal detection
- Structured logging: JSON formatter with RotatingFileHandler (10MB×5)
- Documentation: MCP Tools Catalog, API Reference (64 endpoints), README v0.5, risk heatmap generator
- Alert configuration: config/alert_config.yaml with threshold and channel settings
- Accepted correlations registry: config/accepted_correlations.yaml
### Changed
- scoring/engine.py: added dimension_status tracking and data_quality in to_dict() output
- pipeline/sanctions/screener.py: added normalize_name() for entity name normalization
- features/timeseries/scheduler.py: expanded from 2 to 5 scheduled jobs
- mcp_server/server.py: added caching and input validation to key tools
- api/main.py: added rate limiting (slowapi) and sanitization middleware
### Dependencies
- Added: slowapi>=0.1.9

## [0.5.1] - 2026-03-17
### Fixed
- food_security dimension: replaced WFP HungerMap (primary) with FEWS NET IPC Phase Classification
  to eliminate r=0.99 correlation with humanitarian dimension
- humanitarian dimension: replaced ReliefWeb report count (primary) with OCHA FTS funding gap ratio
  for conceptual independence from food_security
- food_security ↔ humanitarian correlation: 0.99 → 0.67 (target <0.70 achieved)
- WFP client ISO resolution bug: 2-letter country codes (e.g. "DE") were incorrectly matched
  to unrelated countries via substring matching (e.g. "DE" matched "democratic republic of congo")
- Monte Carlo simulation: vectorized with numpy matrix operations, n=1000 completes in ~27s (was ~4.5min)
### Changed
- WFP HungerMap: demoted to 15% weight in food_security (was 100%)
- ReliefWeb: demoted to 20% weight in humanitarian (was primary source)
### Added
- OCHA Financial Tracking Service (FTS) client: funding gap ratio, active emergency tracking
- FEWS NET client: IPC Phase Classification, market price alerts, 38-country coverage
- Humanitarian scorer: OCHA FTS (80%) + ReliefWeb (20%)
- Food security scorer: FEWS NET IPC+prices (85%) + WFP (15%), non-covered countries fallback to WFP
- Correlation diagnosis script (scripts/diagnose_correlations.py)
- Correlation fix verification script (scripts/verify_correlation_fix.py)

## [0.5.0] - 2026-03-17
### Added
- Portfolio analysis: multi-supplier risk ranking, weighted portfolio scoring, KMeans clustering
- Correlation analysis: 24-dimension correlation matrix (pearson/spearman/kendall), leading indicator detection via cross-correlation, cascade pattern detection
- Benchmark analysis: industry profiles (automotive/semiconductor/pharma/apparel/energy), peer comparison with percentile ranks, regional baselines (6 regions)
- What-If sensitivity analysis: weight perturbation ranking, scenario score override, threshold driver analysis, Monte Carlo simulation (VaR/confidence intervals)
- 6 new MCP tools: analyze_portfolio, analyze_risk_correlations, find_leading_risk_indicators, benchmark_risk_profile, analyze_score_sensitivity, simulate_what_if (total: 22)
- 14 new API endpoints under /api/v1/analytics/ (total: 64)
### Changed
- MCP tools: 16 -> 22
- API routes: 50 -> 64
### Dependencies
- Added: scikit-learn>=1.4.0, pandas>=2.1.0, scipy, numpy

## [0.4.1] - 2026-03-16
### Fixed
- Japan risk score regression: weight normalization corrected (24 dimensions sum to exactly 1.0)
- SECO client: background cache mode with disk persistence, eliminates 180s timeout on screening requests
### Added
- Score anomaly detection with configurable thresholds (overall ±20, dimension ±30)
- Data freshness monitoring per dimension (realtime/daily/monthly thresholds)
- Extended /health endpoint with sanctions source status, alert counts, data staleness
- GET /api/v1/monitoring/quality endpoint for data quality dashboard
- get_data_quality_report MCP tool (#16)
- Score regression test suite (8 locations, tests/score_regression_v041.json)
- Diagnostic script (scripts/diagnose_score.py)

## [0.4.0] - 2026-03-16
### Added
- 24-dimension risk scoring (added climate_risk #23, cyber_risk #24)
- 5 new sanctions sources: UK OFSI, Switzerland SECO, Canada DFATD, Australia DFAT, Japan MOFA
- 10 regional statistics clients: KOSIS, Taiwan Trade, NBS China, GSO Vietnam, DOSM Malaysia, MPA Singapore, ASEAN Stats, Eurostat, ILOSTAT, AfDB
- 4 climate/environment pipeline clients: ND-GAIN, WRI Aqueduct, GloFAS, Climate TRACE
- 3 cyber risk pipeline clients: OONI, CISA KEV, ITU ICT
- 6 new feature modules: route risk analysis (7 chokepoints), concentration risk (HHI), disruption simulation (5 scenarios), timeseries forecasting (moving average + anomaly detection), DD report generation (EDD triggers), commodity exposure analysis
- bulk_assess_suppliers MCP tool for CSV batch assessment
- TimeSeries store (SQLite) with APScheduler (6h full / 1h critical)
- Risk forecasting with confidence intervals
- Sanctions ingestion script (scripts/ingest_sanctions.py) for all 9 parsers
### Fixed
- EU sanctions client: 403 error resolved (added authentication token + fallback URL)
- BIS Entity List: dead URL updated to trade.gov Consolidated Screening List CSV
- METI Foreign User List: 404 fixed with dynamic URL extraction + TLS 1.2 adapter
- US CSL API: fallback to static CSV file with local fuzzy search
### Changed
- MCP tools: 9 -> 15
- API routes: 39 -> 49
- Pipeline clients: 35 -> 75+
- Risk dimensions: 22 -> 24
- Scoring formula: weights rebalanced for 24 dimensions (sum = 1.0)

## [0.3.0] - 2026-03-14
### Added
- 22-dimension risk scoring engine (added food_security, trade, internet, political, labor, port_congestion, aviation, energy, japan_economy)
- 9 MCP tools: screen_sanctions, monitor_supplier, get_risk_score, get_location_risk, get_global_risk_dashboard, get_supply_chain_graph, get_risk_alerts, bulk_screen, compare_locations
- FastAPI server with 39 endpoints covering all risk dimensions
- GDELT BigQuery integration for geopolitical event monitoring
- Pipeline clients for ACLED, World Bank, Frankfurter/ECB, Disease.sh, Open-Meteo, NOAA
- Compliance scoring (FATF, TI CPI), labor risk (DoL ILAB, GSI), internet infrastructure (Cloudflare Radar, IODA)
- UN Comtrade trade dependency analysis
- BOJ/e-Stat Japan economic indicators
### Changed
- Risk dimensions: 10 -> 22
- MCP tools: 3 -> 9
- API routes: 12 -> 39

## [0.2.0] - 2026-03-12
### Added
- Multi-dimension risk scoring (10 dimensions: sanctions, geopolitical, disaster, legal, maritime, conflict, economic, currency, health, humanitarian)
- OFAC, EU, UN, METI sanctions list parsers with fuzzy matching
- GDACS disaster alert integration
- USGS earthquake monitoring
- NASA FIRMS fire detection
- JMA Japan meteorological alerts
- IMF PortWatch maritime disruption tracking
- FastAPI REST server (12 initial endpoints)
- SQLite database for sanctions entities and screening logs
- Composite scoring formula (weighted average + peak amplification)

## [0.1.0] - 2026-03-10
### Added
- Initial project scaffolding
- Basic sanctions screening against OFAC SDN list
- FastMCP server with screen_sanctions tool
- Simple risk score calculation (sanctions-only)
- Project structure: pipeline/, scoring/, mcp_server/, api/
