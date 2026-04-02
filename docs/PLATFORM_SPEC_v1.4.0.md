# SCRI Platform v1.4.0 — プラットフォーム仕様書
最終更新: 2026-04-03

---

## 1. プラットフォーム概要

| 項目 | 値 |
|---|---|
| バージョン | 1.4.0 |
| Pythonソースファイル | 296 |
| MCPツール | 63 |
| APIエンドポイント | 110 |
| リスク次元 | 28 (27加重 + overall) |
| テスト | 275 pass / 11 skip / 0 fail |
| ダッシュボード | 4 (Landing + Logistics + Inbound + Legacy) |
| リポジトリ | https://github.com/Agentic-governance/logistics-mcp |
| ライセンス | MIT |

---

## 2. データベース

| DB | テーブル数 | 行数 | 内容 |
|---|---|---|---|
| timeseries.db | 3 | 133,308 | 28次元 × 51カ国 × 90日リスクスコア時系列 |
| risk.db | 5 | 20,942 | OFAC/UN/EU等15制裁リスト |
| tourism_stats.db | 5 | 327 | 観光統計(アウトバウンド/インバウンド/重力変数) |
| internal_logistics.db | 7 | 399 | 内部ロジスティクス(在庫/発注/生産/拠点/輸送) |
| cache.db | 1 | 0 | SmartCache (Redis/SQLiteデュアル) |

### timeseries.db 詳細
- **28次元**: overall + 27加重次元 (全次元補完済み、欠落なし)
- **51カ国**: 主要50カ国 + 日本
- **90日分**: 2026-01-03 〜 2026-04-02
- 季節パターン: typhoon(6-11月), health(冬季), energy(冬季), maritime(冬季), aviation等

### tourism_stats.db 詳細
| テーブル | 行数 | 内容 |
|---|---|---|
| outbound_stats | 75 | 15市場 × 5年のアウトバウンド統計 |
| inbound_stats | 35 | 7デスティネーション × 5年 |
| japan_inbound | 100 | 20市場 × 5年のJNTO訪日統計 |
| gravity_variables | 75 | 15市場 × 5年の重力モデル変数 |
| excess_demand | 42 | TFI超過需要(ブランド効果追跡) |

### internal_logistics.db 詳細
| テーブル | 行数 | 内容 |
|---|---|---|
| inventory | 177 | 50部品 × 5拠点の在庫データ |
| purchase_orders | 30 | 発注残 |
| production_plan | 60 | 3製品 × 30日間 |
| locations | 11 | 工場3 + 倉庫5 + 港湾3 |
| transport_routes | 20 | 主要輸送ルート |
| procurement_costs | 99 | 50部品 × 複数仕入先 |

---

## 3. リスクスコアリングエンジン (28次元)

### スコア計算式
```
composite = 60% × weighted_sum + 30% × peak_dimension + 10% × second_peak
sanctions = 100 → 即時 CRITICAL (overall = 100)
WEIGHTS合計 = 1.0000 (27加重次元)
```

### 全次元一覧
| # | 次元 | 主要データソース | 季節性 |
|---|------|------------------|--------|
| 1 | economic | World Bank, IMF | - |
| 2 | currency | Frankfurter/ECB | - |
| 3 | weather | OpenMeteo | 台風6-11月 |
| 4 | compliance | FATF, Basel AML | - |
| 5 | political | V-Dem, WJP | - |
| 6 | climate_risk | ND-GAIN, Climate TRACE | - |
| 7 | cyber_risk | CISA KEV, ITU | - |
| 8 | sanctions | OFAC, UN, EU + 12リスト | - |
| 9 | disaster | USGS, GDACS, BMKG | 台風/地震 |
| 10 | trade | UN Comtrade | - |
| 11 | labor | ILO, ITUC | - |
| 12 | conflict | ACLED, GPI | - |
| 13 | food_security | WFP, FEWS NET | 乾季 |
| 14 | humanitarian | OCHA, ReliefWeb | - |
| 15 | internet | OONI | - |
| 16 | port_congestion | PortWatch, AIS | 冬季+5 |
| 17 | geo_risk | SIPRI, GDELT | - |
| 18 | health | WHO, Disease.sh | 冬季+10 |
| 19 | maritime | Lloyd's, MarineTraffic | 冬季+8 |
| 20 | aviation | OpenSky, IATA | 台風期-5 |
| 21 | legal | Caselaw MCP | - |
| 22 | typhoon | 気象庁, IBTrACS | 7-9月+20 |
| 23 | energy | EIA, OPEC | 冬季+12 |
| 24 | japan_economy | BOJ, e-Stat | (参考) |
| 25 | sc_vulnerability | HHI, 単一調達源率 | - |
| 26 | person_risk | OpenOwnership, ICIJ, Wikidata | - |
| 27 | capital_flow | Chinn-Ito, IMF AREAER, SWIFT | - |

---

## 4. 観光需要モデル

### 4-1. PPML構造重力モデル
- 手法: Poisson GLM (Santos Silva & Tenreyro, 2006)
- Pseudo R² = **0.9874**
- 為替弾性値 = **-1.12** (円高1%→訪日1.12%減)
- 10説明変数: TFI, ln_gdp, ln_exr, ln_flight, visa, bilateral, leave_util, outbound_prop, ln_restaurant, ln_learners
- 11カ国 × 8年パネル, HC3ロバスト標準誤差

### 4-2. Travel Friction Index (TFI)
```
TFI = 0.4×文化的距離(Kogut-Singh+言語) + 0.4×log(実効飛行距離) + 0.2×ビザ障壁
```
| 国 | TFI | 解釈 |
|---|---|---|
| KR | 12.5 | 最低摩擦 |
| TW | 18.2 | 低摩擦 |
| CN | 22.4 | 低摩擦(ビザ障壁) |
| US | 62.4 | 高摩擦 |
| DE | 67.2 | 高摩擦 |
| SA | 78.5 | 最高摩擦 |

### 4-3. Cultural Inertia Coefficient (CIC)
```
CIC = Structural(1-TFI/100) + Psychological(超過需要トレンド)
```
- KR: 0.875 (高慣性→リスク後に速く回帰)
- US: 0.376 (低慣性→ブランド依存)

### 4-4. Dual-Scale モデル
- LSTM構造成分: 10年の文化的慣性 (PyTorch + numpyフォールバック)
- Transformer サイクル成分: 未来既知情報入力、Quantile Loss (p10/p50/p90)
- 動的α: `min(0.3+0.05h, 0.8)` — 短期→Transformer、長期→LSTM

### 4-5. ベイズ更新 (粒子フィルタ)
- 1000粒子、ESS < N/2 で系統的リサンプリング
- 月次JNTO実績入力で即座に予測更新

### 4-6. リスク期待損失
| 国 | 期待損失(ベース) | 主要シナリオ |
|---|---|---|
| CN | 21.2% | 日中関係(6.0%), 景気後退(5.0%), 円高(4.2%), 感染症(6.0%) |
| KR | 7.6% | 景気停滞(2.0%), 円高(3.2%), 日韓関係(2.4%) |
| TW | 9.8% | 台湾海峡(4.2%), 景気(2.7%), 円高(2.8%) |
| TH | 14.5% | 政情不安(7.5%), バーツ安(3.5%), 競合(3.5%) |
| US | 4.2% | 景気後退(3.0%), フライト減(1.2%) |

### 4-7. 3シナリオ定義
| シナリオ | 前提 | 需要影響 |
|----------|------|----------|
| **現状維持** | 現在の為替・フライト供給・二国間関係が継続 | ±0% |
| **楽観** | 円安10%進行 + フライト増便+15% + ビザ緩和 | +18% |
| **悲観** | 円高10% + 日中関係悪化 + 中国景気減速 | -18% |

---

## 5. ダッシュボード仕様

### 5-1. ランディング (`dashboard/index.html`, 1.9KB)
3カード: Logistics / Inbound / Legacy

### 5-2. Logistics Risk (`dashboard/logistics.html`, 56KB)
**URL**: `/dashboards/logistics.html`

```
┌─────────────────────────────────────────────────────┐
│ HEADER | [次元選択10種] [All/Sea/Air] [LIVE/STATIC]  │
├───────────────────────┬─────────────────────────────┤
│ 世界地図(60%)         │ チョークポイント状況(7箇所)  │
│ 49カ国リスク塗り分け  │ 選択ルート詳細              │
│ 海路5本+空路5本       │ (チョークポイント別+代替)    │
├───────────────────────┴─────────────────────────────┤
│ ルートリスクランキング（横スクロール）                │
└─────────────────────────────────────────────────────┘
```

**データソース**: `/api/v1/dashboard/global-risk` (49カ国, timeseries.dbからリアルタイム)
**フォールバック**: 40カ国ハードコード
**自動更新**: 30分間隔

**チョークポイント** (動的リスク調整: 70%静的+30%近隣国リスク):
| 名称 | ベースリスク | ステータス |
|------|-------------|-----------|
| バベルマンデブ | 82 | フーシ派攻撃 |
| ホルムズ海峡 | 74 | イラン緊張 |
| スエズ運河 | 67 | 通航制限 |
| 台湾海峡 | 55 | 監視強化 |
| パナマ運河 | 49 | 水位低下 |
| マラッカ海峡 | 36 | 通常運航 |
| 喜望峰 | 28 | 迂回航路増 |

### 5-3. Inbound Tourism Risk (`dashboard/inbound.html`, 56KB)
**URL**: `/dashboards/inbound.html`

```
┌──────────────────────────────────────────────────────┐
│ HEADER | [ソース国] [都道府県] [LIVE/STATIC]          │
├────────────────────────┬─────────────────────────────┤
│ 世界地図(バブル)        │ 日本地図(47都道府県,対数)   │
│ サイズ=訪日シェア      │ 色=来訪者数(5万〜1800万)    │
│ 色=期待損失率          │ [高さ: 30vh]                │
├────────────────────────┴─────────────────────────────┤
│ ■ セクション1: 全期間推移（コンテキスト）             │
│   灰色1本線 2019→コロナ→回復→現在  [15vh]            │
├──────────────────────────────────────────────────────┤
│ ■ セクション2: 予測フォーカス ★最重要★              │
│   [現状維持] [楽観] [悲観]                            │
│   3シナリオ線が常時表示（選択で太さ変化）              │
│   現状維持=青実線 / 楽観=緑破線 / 悲観=赤破線         │
│   信頼区間=青帯                                       │
│   2026-04 〜 2027-12 (21ヶ月)  [25vh]                 │
│                                                       │
│   シナリオ解説カード:                                  │
│   [現状維持: 現在の為替・供給継続]                     │
│   [楽観: 円安10%+増便+ビザ緩和]                       │
│   [悲観: 円高10%+日中悪化+景気減速]                   │
├──────────────────────────────────────────────────────┤
│ ■ セクション3: 国別内訳（シナリオ選択時のみ表示）     │
│   未選択: 「シナリオを選択してください」               │
│   選択時: stacked bar + 合計線 (21ヶ月)                │
│   ツールチップ: リスクシナリオ分解                     │
│   「中国: 35千人 / 期待損失21.2%                      │
│    ・日中関係 確率30%×影響40%=12.0%                   │
│    ・景気後退 確率40%×影響20%=8.0%」  [20vh]          │
└──────────────────────────────────────────────────────┘
```

**データソース**: `/api/v1/tourism/market-ranking` + フォールバック
**時系列データ**:
- 実績: 2019-01 〜 2026-03 (87ヶ月, 5カ国月次千人単位)
- 予測: 2026-04 〜 2027-12 (21ヶ月, 3シナリオ)
- 成長率: KR+5%, CN-8%, TW+3%, US+12%, AU+9%

**バブルチャート (8市場)**:
| 国 | シェア | 期待損失 | 2025来訪者 | 予測変化 |
|---|---|---|---|---|
| CN | 24.8% | 21.2% | 520万 | -8% |
| KR | 19.3% | 7.6% | 860万 | +5% |
| TW | 17.2% | 9.8% | 480万 | +3% |
| US | 8.5% | 4.2% | 360万 | +12% |
| HK | 6.2% | 11.2% | 131万 | +2% |
| AU | 4.8% | 5.5% | 62万 | +9% |
| TH | 3.2% | 14.5% | 42万 | -3% |
| SG | 2.8% | 3.8% | 38万 | +6% |

**日本地図 (47都道府県, 対数スケール)**:
東京1800万, 大阪1000万, 京都500万, 北海道390万, 福岡335万, 沖縄280万, 愛知220万, 神奈川170万, 奈良140万, 兵庫110万, 長崎100万, 広島85万, 石川72万, 長野67万, 静岡56万, 栃木55万, 山梨48万, 新潟45万, 三重42万, 滋賀35万 ... (全47県)

### 5-4. Legacy (`dashboard/legacy.html`, 154KB)
10タブ: Risk/Sanctions/BOM/Routes/Timeseries/Alerts/Analytics/Graph/Digital Twin/Scenario

---

## 6. APIエンドポイント (110本)

### ダッシュボードAPI
| メソッド | パス | 説明 |
|----------|------|------|
| GET | /api/v1/dashboard/global-risk | 49カ国リスクサマリー(timeseries.dbから) |
| GET | /api/v1/dashboard/chokepoints | 7チョークポイント動的リスク |

### リスクスコアリングAPI (主要)
| GET | /api/v1/risk/score/{location} | 単一国スコア |
| GET | /api/v1/risk/compare | 複数国比較 |
| POST | /api/v1/risk/batch | バッチスコアリング |
| POST | /api/v1/risk/batch/stream | SSEストリーミング |

### 観光API
| GET | /api/v1/tourism/market-risk/{country} | 市場リスク評価 |
| GET | /api/v1/tourism/market-ranking | 市場ランキング |
| POST | /api/v1/tourism/forecast | 来訪者予測 |
| POST | /api/v1/tourism/japan-forecast | 日本全国予測(PPML+ベイズ) |
| POST | /api/v1/tourism/prefecture-forecast | 都道府県予測 |
| POST | /api/v1/tourism/decompose | 変動要因分解 |
| GET | /api/v1/tourism/capital-flow-risk/{country} | 資金フローリスク |

### デジタルツインAPI
| POST | /api/v1/twin/stockout-scan | 在庫枯渇スキャン |
| POST | /api/v1/twin/production-cascade | 生産カスケード |
| POST | /api/v1/twin/emergency-procurement | 緊急調達計画 |
| GET | /api/v1/twin/facility-risks | 拠点リスクマップ |
| POST | /api/v1/twin/scenario | シナリオシミュレーション |

### 内部データAPI
| POST | /api/v1/internal/upload/{type} | CSV/Excelアップロード(6種) |
| GET | /api/v1/internal/data-status | データステータス |
| DELETE | /api/v1/internal/reset | データリセット |

---

## 7. MCPツール一覧 (63本)

### リスクスコアリング (10本)
get_risk_score, get_location_risk, compare_locations, compare_risk_scenarios, compare_risk_trends, get_risk_report_card, get_global_risk_dashboard, get_data_quality_report, get_risk_alerts, get_hidden_risk_exposure

### BOM・物レイヤー (6本)
analyze_bom_risk, analyze_goods_layer, find_actual_suppliers, build_supply_chain_from_ir, get_conflict_minerals_status, analyze_product_complete

### サプライヤー分析 (6本)
bulk_screen, bulk_assess_suppliers, get_supplier_materials, search_customs_records, get_conflict_mineral_report, get_commodity_exposure

### ポートフォリオ (4本)
analyze_portfolio, benchmark_risk_profile, get_concentration_risk, analyze_risk_correlations

### ルート・シミュレーション (5本)
analyze_route_risk, estimate_disruption_cost, analyze_score_sensitivity, simulate_disruption, simulate_what_if

### 予測・監視 (4本)
find_leading_risk_indicators, get_forecast_accuracy, explain_score_change, monitor_supplier

### 人レイヤー (3本)
screen_ownership_chain, check_pep_connection, get_officer_network

### 統合グラフ (5本)
find_sanction_network_exposure, build_supply_chain_graph_tool, get_network_risk_score, analyze_network_vulnerability, optimize_procurement

### デジタルツイン (6本)
scan_stockout_risks, simulate_production_impact, get_emergency_procurement_plan, analyze_transport_risks, get_facility_risk_map, run_scenario_simulation

### 観光・インバウンド (9本)
assess_inbound_tourism_risk, get_inbound_market_ranking, forecast_visitor_volume, analyze_competitor_performance, predict_regional_distribution, decompose_visitor_change, get_capital_flow_risk, forecast_japan_inbound, forecast_prefecture_inbound

### その他 (5本)
screen_sanctions, screen_supplier_reputation, infer_supply_chain, get_supply_chain_graph, generate_dd_report

---

## 8. 観光需要モデル — アーキテクチャ図

```
                    ┌─────────────────────┐
                    │   月次JNTO実績      │
                    │   (2019-2026/03)    │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
    ┌─────────────────┐ ┌──────────┐ ┌──────────────┐
    │ LSTM構造成分    │ │ PPML重力 │ │ STL季節分解  │
    │ (10年慣性)      │ │ (国別シェア)│ │ (12ヶ月周期) │
    └────────┬────────┘ └─────┬────┘ └──────┬───────┘
             │                │              │
             ▼                ▼              ▼
    ┌─────────────────┐ ┌──────────┐
    │ Transformer     │ │ TFI      │
    │ (サイクル成分)   │ │ (文化距離)│
    └────────┬────────┘ └─────┬────┘
             │                │
             ▼                ▼
    ┌──────────────────────────────┐
    │  Dual-Scale統合              │
    │  α=min(0.3+0.05h, 0.8)      │
    │  短期→Transformer, 長期→LSTM │
    └──────────────┬───────────────┘
                   │
                   ▼
    ┌──────────────────────────────┐
    │  ベイズ更新 (粒子フィルタ)    │
    │  1000粒子, ESS < N/2 resample│
    └──────────────┬───────────────┘
                   │
                   ▼
    ┌──────────────────────────────┐
    │  リスク期待損失調整           │
    │  予測 × (1 - expected_loss)  │
    │  3シナリオ: base/opt/pes     │
    └──────────────┬───────────────┘
                   │
          ┌────────┼────────┐
          ▼                 ▼
    ┌───────────┐    ┌────────────┐
    │ 日本全体   │    │ 都道府県   │
    │ (積み上げ) │    │ (シェア行列)│
    └───────────┘    └────────────┘
```

---

## 9. デジタルツインレイヤー

```
内部データ(CSV/Excel) → LogisticsImporter → internal_logistics.db
                                                    │
            ┌───────────────┬───────────────┬───────┴───────┐
            ▼               ▼               ▼               ▼
    StockoutPredictor  ProductionCascade  EmergencyProcure  FacilityRiskMapper
    (在庫枯渇予測)    (生産カスケード)   (緊急調達最適化)  (拠点リスクマップ)
            │               │               │               │
            └───────────────┴───────────────┴───────┬───────┘
                                                    ▼
                                          TransportRiskAnalyzer
                                          (輸送リスク統合)
```

---

## 10. 起動方法

```bash
cd ~/supply-chain-risk

# サーバー起動
.venv311/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000

# ダッシュボード
open http://localhost:8000/dashboards/

# MCP接続
.venv311/bin/python mcp_server/server.py  # SSE on port 8001

# テスト
.venv311/bin/python -m pytest tests/ -q --timeout=120

# API確認
curl -s http://localhost:8000/api/v1/dashboard/global-risk | python -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d.get(\"data\",d).get(\"countries\",[]))}カ国')"
```

---

## 11. バージョン履歴

| バージョン | 日付 | 主要追加 |
|-----------|------|---------|
| v0.3.0 | 2026-03-15 | 22次元エンジン, 9 MCPツール |
| v0.9.0 | 2026-03-27 | 物レイヤー, 25次元, 43ツール |
| v1.0.0 | 2026-03-28 | 人レイヤー, 統合グラフ, 48ツール |
| v1.1.0 | 2026-03-28 | デジタルツイン, 54ツール |
| v1.3.0 | 2026-04-02 | 観光統計, 資金フロー第27次元, 61ツール |
| v1.4.0 | 2026-04-03 | Dual-Scale LSTM+Transformer, PPML, TFI, CIC, API駆動ダッシュボード, 28次元×51カ国×90日DB, 63ツール |
