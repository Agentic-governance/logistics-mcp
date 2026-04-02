# MCP Tools Catalog -- SCRI Platform v0.9.0

> **Model Context Protocol (MCP)** tools for the Supply Chain Risk Intelligence platform.
> 39 tools providing 24-dimensional risk assessment, sanctions screening, BOM analysis,
> cost-impact estimation, forecasting, goods layer analysis, person layer analysis,
> and advanced analytics capabilities.

---

## Table of Contents

1. [Core Risk Assessment (Tools 1-9)](#core-risk-assessment)
2. [Route, Concentration & Simulation (Tools 10-16)](#route-concentration--simulation)
3. [Advanced Analytics (Tools 17-22)](#advanced-analytics)
4. [Trend & Reporting (Tools 23-25)](#trend--reporting)
5. [BOM & Tier Inference (Tools 26-28)](#bom--tier-inference)
6. [Forecasting & Screening (Tools 29-30)](#forecasting--screening)
7. [Cost Impact (Tools 31-32)](#cost-impact)
8. [Goods Layer (Tools 33-36)](#goods-layer)
9. [Person Layer (Tools 37-39)](#person-layer)
10. [Integration Guide](#integration-guide)

---

## Core Risk Assessment

### 1. `screen_sanctions`

Screen a company against 10 consolidated sanctions lists (OFAC/EU/UN/METI/BIS/OFSI/SECO/Canada/DFAT/MOFA).

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | `str` | Yes | Company name (Japanese and English supported) |
| `country` | `str` | No | Country name (improves matching accuracy) |

**Returns:** `dict` with `matched`, `match_score`, `source`, `matched_entity`, `evidence`, `screened_at`

**Example conversations:**

```
1. User: Huawei Technologiesを制裁リストでチェックして
   Claude: screen_sanctions("Huawei Technologies", "China")
   Result: BIS Entity Listでマッチ (95%)。輸出管理規制の対象です。

2. User: Is "Acme Trading Co" on any sanctions lists?
   Claude: screen_sanctions("Acme Trading Co")
   Result: No match found across 10 sanctions lists. Entity appears clean.

3. User: 株式会社ABCを制裁スクリーニングして、ロシアの会社です
   Claude: screen_sanctions("株式会社ABC", "Russia")
   Result: OFAC SDN listで部分一致 (82%)。法務部門への確認を推奨します。
```

**Notes:**
- Results are cached for 24 hours (TTL).
- Fuzzy matching is used; check `match_score` (threshold: 80+).
- Japanese company names are normalized (full-width to half-width) before matching.

---

### 2. `monitor_supplier`

Register a supplier for real-time 24-dimensional monitoring at 15-minute intervals.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `supplier_id` | `str` | Yes | Internal supplier ID |
| `company_name` | `str` | Yes | Company name |
| `location` | `str` | Yes | Country or city name |

**Returns:** `dict` with `status`, `supplier_id`, `monitoring` config

**Example conversations:**

```
1. User: Samsung SDIを監視対象に追加して
   Claude: monitor_supplier("SUP-KR-001", "Samsung SDI", "South Korea")
   Result: 登録完了。15分間隔で24次元×40+データソースを自動監視します。

2. User: Monitor TSMC for supply chain risks
   Claude: monitor_supplier("SUP-TW-001", "TSMC", "Taiwan")
   Result: Registered. 15-minute monitoring across 24 dimensions and 40+ data sources.

3. User: ベトナムの新規仕入先 VinFast を登録して
   Claude: monitor_supplier("SUP-VN-001", "VinFast", "Vietnam")
   Result: 登録完了。紛争(68)、政治(55)リスクを重点監視します。
```

**Notes:**
- Stored in SQLite; persists across restarts.
- Re-registering the same `supplier_id` updates the existing record.

---

### 3. `get_risk_score`

Compute the full 24-dimensional risk score for a supplier with optional forecast, history, and explanations.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `supplier_id` | `str` | Yes | Supplier ID |
| `company_name` | `str` | Yes | Company name |
| `country` | `str` | No | Country name |
| `location` | `str` | No | Location (city or region) |
| `dimensions` | `list[str]` | No | Filter to specific dimensions (empty = all 24) |
| `include_forecast` | `bool` | No | Include 30-day forecast (default: false) |
| `include_history` | `bool` | No | Include 90-day score history (default: false) |
| `explain` | `bool` | No | Add human-readable explanation per dimension (default: false) |

**Returns:** `dict` with `overall_score`, `risk_level`, `scores` (24 dimensions), `evidence`, optionally `explanations`, `history`, `forecast`

**Example conversations:**

```
1. User: 中国のサプライヤーリスクを詳しく教えて
   Claude: get_risk_score("CN001", "China Supplier", country="China", explain=True)
   Result: 総合56/100 (MEDIUM)。conflict(68), political(55)が高リスク。

2. User: What's the risk forecast for Japan over the next month?
   Claude: get_risk_score("JP001", "Japan", country="Japan", include_forecast=True)
   Result: Current: 28/100 (LOW). 30-day forecast: stable at 26-30.

3. User: 台湾の制裁と地政学リスクだけ見たい
   Claude: get_risk_score("TW001", "Taiwan", country="Taiwan", dimensions=["sanctions", "geo_risk"])
   Result: sanctions=0, geo_risk=45. 台湾海峡の地政学的緊張が反映されています。
```

**Notes:**
- Results are cached for 1 hour (TTL).
- `explain=True` adds Japanese explanation text per dimension.
- Composite formula: 60% weighted sum + 30% peak + 10% second-peak.

---

### 4. `get_location_risk`

Location-based risk assessment returning all 24 dimensions.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `location` | `str` | Yes | Country name, city name, or region name |

**Returns:** `dict` with full 24-dimension risk scores and evidence

**Example conversations:**

```
1. User: ベトナムのリスクを教えて
   Claude: get_location_risk("Vietnam")
   Result: 総合42/100 (MEDIUM)。紛争と政治リスクが比較的高い。

2. User: Assess risk for Singapore
   Claude: get_location_risk("Singapore")
   Result: Overall 18/100 (MINIMAL). Low risk across all dimensions.

3. User: ミャンマーの状況は？
   Claude: get_location_risk("Myanmar")
   Result: 総合78/100 (HIGH)。制裁(85), 紛争(90), 政治(82)が深刻。
```

---

### 5. `get_global_risk_dashboard`

Global real-time risk overview aggregating all major data sources.

**Parameters:** None

**Returns:** `dict` with `sources` containing disasters, earthquakes, weather, maritime, health, japan_economy

**Example conversations:**

```
1. User: 今日の世界のリスク状況を教えて
   Claude: get_global_risk_dashboard()
   Result: 災害3件(赤2件), 活発な台風1個, 港湾途絶2件, COVID陽性500万件。

2. User: Any global risks I should know about?
   Claude: get_global_risk_dashboard()
   Result: 2 Red GDACS alerts, M6.2 earthquake in Indonesia, Suez congestion reported.

3. User: グローバルダッシュボードの概要を見せて
   Claude: get_global_risk_dashboard()
   Result: 地震(USGS): 重大3件, 台風: なし, 港湾途絶: 1件(紅海)。
```

**Notes:**
- Cached for 30 minutes to reduce API load.

---

### 6. `get_supply_chain_graph`

Tier-N supply network graph visualization.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | `str` | Yes | Root company name |
| `country_code` | `str` | No | Country code (jp/us/cn, default: jp) |
| `depth` | `int` | No | Exploration depth (1-3, default: 2) |

**Returns:** `dict` with `nodes` and `edges` for graph visualization

**Example conversations:**

```
1. User: トヨタのサプライチェーンを可視化して
   Claude: get_supply_chain_graph("Toyota", "jp", 2)
   Result: 15ノード, 22エッジのTier-2供給網グラフ。

2. User: Show me Apple's supply chain
   Claude: get_supply_chain_graph("Apple", "us", 2)
   Result: 12 nodes, 18 edges. Key Tier-1 in Taiwan, China, South Korea.

3. User: Samsung の Tier-3 まで見たい
   Claude: get_supply_chain_graph("Samsung", "kr", 3)
   Result: 28ノード, 45エッジ。中国・日本・台湾に深い依存関係。
```

---

### 7. `get_risk_alerts`

Recent risk alerts from monitoring system.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `since_hours` | `int` | No | Hours to look back (default: 24) |
| `min_score` | `int` | No | Minimum score threshold (default: 50) |

**Returns:** `dict` with `count` and `alerts` list

**Example conversations:**

```
1. User: 直近24時間のアラートを見せて
   Claude: get_risk_alerts(24, 50)

2. User: Any critical alerts in the last week?
   Claude: get_risk_alerts(168, 80)

3. User: 低スコアのアラートも含めて全部見たい
   Claude: get_risk_alerts(24, 0)
```

---

### 8. `bulk_screen`

CSV-based bulk sanctions screening.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `csv_content` | `str` | Yes | CSV text (header: company_name,country) |

**Returns:** `dict` with `total_screened`, `matched_count`, `results`

**Example conversations:**

```
1. User: この3社をまとめてスクリーニングして
   Claude: bulk_screen("company_name,country\nAcme Corp,China\nXYZ Ltd,Russia\nABC Inc,Japan")

2. User: Screen this supplier list against sanctions
   Claude: bulk_screen(csv_content)

3. User: サプライヤーリスト100社を一括チェックしたい
   Claude: bulk_screen(csv_data)  # Processes each row sequentially
```

---

### 9. `compare_locations`

Multi-location risk comparison across all 24 dimensions.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `locations` | `str` | Yes | Comma-separated location list (e.g., "China,Vietnam,Thailand") |

**Returns:** `dict` with `comparisons` sorted by overall score (highest risk first)

**Example conversations:**

```
1. User: 中国とベトナムとタイを比較して
   Claude: compare_locations("China,Vietnam,Thailand")
   Result: 中国(56)>ベトナム(42)>タイ(35)。中国は制裁・紛争リスクが突出。

2. User: Compare ASEAN countries for manufacturing
   Claude: compare_locations("Vietnam,Thailand,Indonesia,Malaysia,Philippines")
   Result: Indonesia(48) highest, Malaysia(28) lowest.

3. User: 調達先候補の4カ国を比較して
   Claude: compare_locations("Taiwan,South Korea,Japan,Singapore")
```

---

## Route, Concentration & Simulation

### 10. `analyze_route_risk`

Transport route risk analysis with 7 chokepoint assessment.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `origin` | `str` | Yes | Origin (port/city/country) |
| `destination` | `str` | Yes | Destination (port/city/country) |

**Returns:** `dict` with chokepoint risks, alternative routes, total route risk

**Example conversations:**

```
1. User: 上海から横浜への輸送ルートリスクを分析して
   Claude: analyze_route_risk("China", "Japan")
   Result: 台湾海峡(リスク45)を通過。代替: マラッカ経由(+3日)。

2. User: What's the risk shipping from Germany to Japan?
   Claude: analyze_route_risk("Germany", "Japan")
   Result: Suez Canal (risk 35), Malacca Strait (risk 28). Alternative: Cape route.

3. User: ペルシャ湾からロッテルダムまで
   Claude: analyze_route_risk("Iran", "Netherlands")
   Result: ホルムズ海峡(リスク62), スエズ(35)。2つのチョークポイント通過。
```

---

### 11. `get_concentration_risk`

HHI-based supplier concentration analysis.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `supplier_csv` | `str` | Yes | CSV text (header: name,country,share) |
| `sector` | `str` | No | Sector name (e.g., semiconductor) |

**Returns:** `dict` with HHI index, geographic concentration, risk assessment

**Example conversations:**

```
1. User: 半導体サプライヤーの集中度を分析して
   Claude: get_concentration_risk("name,country,share\nTSMC,Taiwan,0.55\nSamsung,South Korea,0.30\nIntel,US,0.15", "semiconductor")
   Result: HHI=4150 (高集中)。台湾依存度55%は危険水準。

2. User: Analyze our battery supplier concentration
   Claude: get_concentration_risk(csv_data, "battery_materials")

3. User: この5社の地理的集中リスクは？
   Claude: get_concentration_risk(csv_data)
```

---

### 12. `simulate_disruption`

Disruption scenario simulation with predefined scenarios.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `scenario` | `str` | Yes | Scenario name: taiwan_blockade, suez_closure, china_lockdown, semiconductor_shortage |
| `custom_params` | `str` | No | Custom parameters JSON |

**Returns:** `dict` with impact assessment, affected countries, timeline

**Example conversations:**

```
1. User: 台湾海峡封鎖シナリオをシミュレーションして
   Claude: simulate_disruption("taiwan_blockade")

2. User: What happens if the Suez Canal closes?
   Claude: simulate_disruption("suez_closure")

3. User: 半導体不足シナリオの影響は？
   Claude: simulate_disruption("semiconductor_shortage")
```

---

### 13. `generate_dd_report`

Automated KYS due diligence report generation.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `entity_name` | `str` | Yes | Company name |
| `country` | `str` | Yes | Country name |

**Returns:** `dict` with sanctions screening, risk scores, EDD determination

**Example conversations:**

```
1. User: Acme Corpのデューデリジェンスレポートを作成して
   Claude: generate_dd_report("Acme Corp", "China")

2. User: Generate a DD report for a new Russian supplier
   Claude: generate_dd_report("OOO Supplier", "Russia")

3. User: 新規取引先のKYSレポートを出して
   Claude: generate_dd_report("XYZ株式会社", "Japan")
```

---

### 14. `get_commodity_exposure`

Sector-specific commodity exposure analysis.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `sector` | `str` | Yes | Sector: semiconductor, battery_materials, automotive_parts, electronics, energy, food |

**Returns:** `dict` with commodity risks, price volatility, geopolitical exposure

**Example conversations:**

```
1. User: 半導体セクターのコモディティリスクは？
   Claude: get_commodity_exposure("semiconductor")

2. User: What commodities expose our battery supply chain?
   Claude: get_commodity_exposure("battery_materials")

3. User: 自動車部品のエクスポージャーを分析して
   Claude: get_commodity_exposure("automotive_parts")
```

---

### 15. `bulk_assess_suppliers`

CSV bulk assessment combining sanctions + risk scoring + concentration analysis.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `csv_content` | `str` | Yes | CSV text (header: name,country) |
| `depth` | `str` | No | "quick" (sanctions+basic) or "full" (all 24 dimensions) |

**Returns:** `dict` with per-supplier results

---

### 16. `get_data_quality_report`

Data quality and source health monitoring report.

**Parameters:** None

**Returns:** `dict` with `score_coverage`, `sanctions_sources`, `recent_anomalies`, `anomaly_count`

---

## Advanced Analytics

### 17. `analyze_portfolio`

Multi-supplier risk portfolio analysis with optional clustering.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `entities_json` | `str` | Yes | JSON array: `[{"name":"...","country":"...","share":0.0}]` |
| `dimensions` | `list[str]` | No | Filter dimensions |
| `include_clustering` | `bool` | No | Include KMeans clustering (requires >= 3 entities) |

**Returns:** `dict` with portfolio scores, ranking, optionally clusters

**Example conversations:**

```
1. User: うちの5社のサプライヤーポートフォリオを分析して
   Claude: analyze_portfolio(json_data, include_clustering=True)

2. User: Rank our suppliers by risk
   Claude: analyze_portfolio(json_data)

3. User: クラスタリングも含めてリスク分析して
   Claude: analyze_portfolio(json_data, include_clustering=True)
```

---

### 18. `analyze_risk_correlations`

Compute dimension correlation matrix across multiple locations.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `locations` | `list[str]` | Yes | List of countries to analyze |
| `method` | `str` | No | "pearson", "spearman", or "kendall" (default: pearson) |

**Returns:** `dict` with correlation matrix, high-correlation pairs

---

### 19. `find_leading_risk_indicators`

Identify leading indicators via time-series cross-correlation.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `target_dimension` | `str` | Yes | Target dimension to predict |
| `locations` | `list[str]` | Yes | Locations to analyze |
| `lag_days` | `int` | No | Maximum lag in days (default: 30) |

**Returns:** `dict` with ranked leading indicators and correlation strengths

---

### 20. `benchmark_risk_profile`

Industry and peer benchmark comparison with percentile ranks.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `entity_country` | `str` | Yes | Target country |
| `industry` | `str` | Yes | Industry: automotive, semiconductor, pharma, apparel, energy |
| `peer_countries` | `list[str]` | No | Peer countries for comparison |

**Returns:** `dict` with industry benchmark and optional peer comparison

---

### 21. `analyze_score_sensitivity`

Weight perturbation sensitivity analysis.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `location` | `str` | Yes | Target location |
| `weight_perturbation` | `float` | No | Perturbation amount (default: 0.05) |

**Returns:** `dict` with sensitivity ranking of dimensions

---

### 22. `simulate_what_if`

What-If scenario simulation with dimension score overrides.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `location` | `str` | Yes | Target location |
| `dimension_overrides_json` | `str` | Yes | JSON: `{"conflict": 90}` |

**Returns:** `dict` with original and simulated overall scores

---

## Trend & Reporting

### 23. `compare_risk_trends`

Compare risk score trends across multiple locations over time.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `locations` | `list[str]` | Yes | Locations to compare |
| `dimension` | `str` | No | Dimension to compare (default: "overall") |
| `period_days` | `int` | No | Period in days (default: 90) |

**Returns:** `dict` with `trends` (slope, direction), `most_improved`, `most_deteriorated`

**Example conversations:**

```
1. User: ASEAN各国のリスクトレンドを比較して
   Claude: compare_risk_trends(["Vietnam", "Thailand", "Indonesia", "Malaysia", "Philippines"])
   Result: インドネシアが悪化傾向, マレーシアが改善傾向。

2. User: How has China's conflict risk trended?
   Claude: compare_risk_trends(["China"], "conflict", 180)

3. User: 半年間の各国リスク推移を教えて
   Claude: compare_risk_trends(["Japan", "China", "US"], period_days=180)
```

---

### 24. `explain_score_change`

Root cause analysis for score changes between two dates.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `location` | `str` | Yes | Country name |
| `from_date` | `str` | Yes | Start date (YYYY-MM-DD) |
| `to_date` | `str` | Yes | End date (YYYY-MM-DD) |

**Returns:** `dict` with overall change, per-dimension drivers, top worsened/improved, Japanese summary

---

### 25. `get_risk_report_card`

Executive-summary risk report card for management presentations.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `location` | `str` | Yes | Country name |

**Returns:** `dict` with overall score, top 3 risks, trend, peer comparison, alerts, recommended actions

**Example conversations:**

```
1. User: 中国のリスクレポートカードを作って
   Claude: get_risk_report_card("China")
   Result: 総合56 (MEDIUM), トップ3: conflict(68), political(55), compliance(48).
          トレンド: 安定。上位32%(50カ国中)。推奨: 地政学モニタリング強化。

2. User: Executive summary for our Taiwan exposure
   Claude: get_risk_report_card("Taiwan")

3. User: 日本のリスクサマリーを経営陣向けに
   Claude: get_risk_report_card("Japan")
```

---

## BOM & Tier Inference

### 26. `infer_supply_chain`

Estimate Tier-2/3 supply chain using UN Comtrade trade data.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `tier1_country` | `str` | Yes | Tier-1 supplier country |
| `hs_code` | `str` | Yes | HS code (e.g., "8507" = battery) |
| `material` | `str` | No | Material name (display only) |
| `max_depth` | `int` | No | Inference depth (2-3, default: 3) |

**Returns:** `dict` with estimated exporters, risk exposure, supply tree

---

### 27. `analyze_bom_risk`

BOM (Bill of Materials) supply chain risk analysis.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `bom_json` | `str` | Yes | BOM JSON (see format below) |
| `product_name` | `str` | No | Product name (default: "Product") |
| `include_tier2_inference` | `bool` | No | Include Tier-2/3 inference |

**BOM JSON format:**
```json
[{"part_id": "P001", "part_name": "Battery Cell",
  "supplier_name": "Samsung SDI", "supplier_country": "South Korea",
  "material": "battery", "hs_code": "8507",
  "quantity": 100, "unit_cost_usd": 45.0, "is_critical": true}]
```

**Returns:** `dict` with per-part risk, bottlenecks, mitigation suggestions, resilience score

---

### 28. `get_hidden_risk_exposure`

Analyze hidden Tier-2/3 risk exposure for multiple materials.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `tier1_country` | `str` | Yes | Tier-1 supplier country |
| `materials_json` | `str` | Yes | JSON: `[{"material": "battery", "hs_code": "8507"}]` |

**Returns:** `dict` with per-material exposure, total hidden risk delta

---

## Forecasting & Screening

### 29. `get_forecast_accuracy`

ML forecast model accuracy report.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `days` | `int` | No | Report period in days (default: 30) |

**Returns:** `dict` with cumulative MAE, trend, retrain check

---

### 30. `screen_supplier_reputation`

GDELT news-based supplier reputation screening.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `supplier_name` | `str` | Yes | Supplier name (English recommended) |
| `country` | `str` | No | Country for filtering |
| `days_back` | `int` | No | Search period in days (default: 180) |

**Returns:** `dict` with reputation score, category breakdown (labor/sanctions/corruption/environment/safety)

---

## Cost Impact

### 31. `estimate_disruption_cost`

Financial impact estimation with 4-component cost breakdown.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `scenario` | `str` | Yes | sanctions, conflict, disaster, port_closure, pandemic |
| `annual_spend_usd` | `float` | No | Annual procurement spend (default: 1M) |
| `daily_revenue_usd` | `float` | No | Daily revenue (default: 100K) |
| `duration_days` | `int` | No | Disruption duration (default: 60) |
| `risk_score` | `float` | No | Risk score 0-100 (default: 50) |

**Returns:** `dict` with total cost, 4-component breakdown (sourcing premium, logistics extra, production loss, recovery cost)

**Example conversations:**

```
1. User: 制裁シナリオで年間調達額5億円の場合のコストインパクトは？
   Claude: estimate_disruption_cost("sanctions", 5000000, 500000, 90)
   Result: 総コスト: $2.1M (調達プレミアム$800K + 物流$300K + 生産損失$700K + 復旧$300K)

2. User: What's the financial impact of a port closure?
   Claude: estimate_disruption_cost("port_closure", 2000000, 200000, 45)

3. User: パンデミックシナリオの180日間の影響は？
   Claude: estimate_disruption_cost("pandemic", 10000000, 1000000, 180)
```

---

### 32. `compare_risk_scenarios`

Compare financial impact across all disruption scenarios.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `annual_spend_usd` | `float` | No | Annual procurement spend |
| `daily_revenue_usd` | `float` | No | Daily revenue |
| `duration_days` | `int` | No | Disruption duration |
| `risk_score` | `float` | No | Risk score |

**Returns:** `dict` with ranked scenarios, worst case identification

---

## Goods Layer

### 33. `find_actual_suppliers`

Verify supplier relationships using US customs data (ImportYeti).

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `buyer_company` | `str` | Yes | Buyer company name (e.g., "APPLE INC") |
| `supplier_company` | `str` | No | Specific supplier to verify |

**Returns:** `dict` with confirmed suppliers, shipment counts, products, HS codes

**Example conversations:**

```
1. User: AppleのUS税関データからサプライヤーを確認して
   Claude: find_actual_suppliers("APPLE INC")
   Result: 45サプライヤー確認。Foxconn(中国,shipments:2340), TSMC(台湾,shipments:890)...

2. User: Does Toyota actually import from Denso?
   Claude: find_actual_suppliers("TOYOTA MOTOR", "DENSO CORPORATION")
   Result: Confirmed. 156 shipments in last 12 months.

3. User: Samsung の実際の部品調達先を教えて
   Claude: find_actual_suppliers("SAMSUNG ELECTRONICS")
```

---

### 34. `build_supply_chain_from_ir`

Build supply chain graph from corporate filings (EDINET/SEC EDGAR).

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `companies` | `list[str]` | Yes | Company names or tickers (e.g., ["AAPL", "トヨタ自動車"]) |
| `market` | `str` | No | "auto", "jp" (EDINET), or "us" (SEC) |

**Returns:** `dict` with nodes, edges, supplier relationships extracted from filings

---

### 35. `get_conflict_minerals_status`

Check SEC conflict minerals (3TG: Tin, Tantalum, Tungsten, Gold) reports.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `ticker` | `str` | Yes | Ticker symbol (e.g., "AAPL") |

**Returns:** `dict` with minerals in scope, smelter list, DRC sourcing status, certification

---

### 36. `analyze_product_complete`

Unified goods layer analysis combining all data sources.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `part_name` | `str` | Yes | Part name (e.g., "Battery Cell") |
| `supplier_name` | `str` | Yes | Supplier name |
| `supplier_country` | `str` | Yes | Supplier country |
| `hs_code` | `str` | No | HS code |

**Returns:** `dict` with analysis from SAP, ImportYeti, IR, BACI/Comtrade with confidence levels

---

## Person Layer

### 37. `screen_ownership_chain`

UBO (Ultimate Beneficial Owner) chain risk screening.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | `str` | Yes | Company name (English recommended) |

**Returns:** `dict` with UBO records, ownership chain, risk assessment (sanctions/PEP/offshore leaks), graph stats

**Example conversations:**

```
1. User: Acme Corpの実質的支配者チェーンをスクリーニングして
   Claude: screen_ownership_chain("Acme Corp")
   Result: UBO 3名検出。1名がPEP(政治的露出者)。EDD推奨。

2. User: Check the ownership structure of XYZ Holdings
   Claude: screen_ownership_chain("XYZ Holdings")
   Result: 5 UBOs identified. 1 offshore entity connection via ICIJ data.

3. User: この新規取引先のUBOリスクを調べて
   Claude: screen_ownership_chain("New Supplier Ltd")
```

**Notes:**
- Integrates OpenOwnership API, ICIJ Offshore Leaks, sanctions screening.
- Risk levels: CRITICAL (sanctioned UBO), HIGH (PEP connection), LOW (clean).

---

### 38. `check_pep_connection`

PEP (Politically Exposed Person) connection detection.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | `str` | Yes | Company name |
| `max_hops` | `int` | No | Maximum graph traversal hops (default: 3) |

**Returns:** `dict` with PEP connections, sanctioned connections, risk level, graph stats

**Example conversations:**

```
1. User: Acme CorpにPEP接続はある？
   Claude: check_pep_connection("Acme Corp", 3)
   Result: 2ホップ先にPEP1名検出。EDD（強化DD）を推奨します。

2. User: Any politically exposed persons linked to XYZ?
   Claude: check_pep_connection("XYZ Corp")
   Result: No PEP or sanctioned connections within 3 hops. LOW risk.

3. User: 5ホップまで広げてPEPを探して
   Claude: check_pep_connection("Target Corp", 5)
```

---

### 39. `get_officer_network`

Officer network analysis with interlocking directorate detection.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | `str` | Yes | Company name |

**Returns:** `dict` with executives, board members, interlocking directorates, offshore leak hits, person risk scores, graph data

**Example conversations:**

```
1. User: トヨタの役員ネットワークを分析して
   Claude: get_officer_network("Toyota Motor")
   Result: 経営幹部12名, 取締役8名。兼任先企業5社。オフショアリーク該当なし。

2. User: Check officer connections for Alibaba
   Claude: get_officer_network("Alibaba Group")
   Result: 15 executives, 3 interlocking board connections, 1 offshore leak hit.

3. User: この会社の取締役の兼任状況を調べて
   Claude: get_officer_network("Company X")
```

---

## Integration Guide

### Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "supply-chain-risk": {
      "command": "python",
      "args": ["mcp_server/server.py"],
      "cwd": "/path/to/supply-chain-risk"
    }
  }
}
```

### SSE Transport

The MCP server uses SSE (Server-Sent Events) transport on port 8001:

```bash
python mcp_server/server.py
# -> MCP server running on http://localhost:8001/sse
```

### Response Caching

| Cache | TTL | Max Size |
|---|---|---|
| Risk scores | 1 hour | 200 entries |
| Location risk | 1 hour | 200 entries |
| Sanctions screening | 24 hours | 500 entries |
| Global dashboard | 30 minutes | 1 entry |

### Input Validation

All tools validate inputs via `mcp_server/validators.py`:
- Country names are normalized (e.g., "JP" -> "Japan")
- Dimension names are checked against the 24 valid dimensions
- Industry names are validated against 5 profiles
- Scenario names are validated against 4 predefined scenarios
- Location lists are capped at 10 entries

### Error Handling

All tools return structured error responses:
```json
{
  "error": "Invalid country name: 'XX'",
  "valid_values": ["Japan", "China", "..."]
}
```
