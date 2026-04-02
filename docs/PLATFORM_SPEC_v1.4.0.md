# SCRI Platform v1.4.0 — プラットフォーム仕様書
生成日: 2026-04-03

---

## 1. プラットフォーム概要

| 項目 | 値 |
|---|---|
| バージョン | 1.4.0 |
| Pythonソースファイル | 294 |
| MCPツール | 63 |
| APIエンドポイント | 108 |
| リスク次元 | 27 |
| テスト | 275 pass / 11 skip / 0 fail |
| ダッシュボード | 4 (Landing + Logistics + Inbound + Legacy) |
| データベース | 5 (risk.db / timeseries.db / tourism_stats.db / internal_logistics.db / cache.db) |
| リポジトリ | https://github.com/Agentic-governance/logistics-mcp (非公開) |
| ライセンス | MIT |

---

## 2. アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                    Dashboard Layer                       │
│  logistics.html │ inbound.html │ legacy.html │ index.html│
├─────────────────────────────────────────────────────────┤
│                    API Layer (FastAPI)                    │
│  108 endpoints: /risk/ /bom/ /twin/ /tourism/ /internal/ │
├─────────────────────────────────────────────────────────┤
│                    MCP Layer (FastMCP)                    │
│  63 tools: リスク評価 / BOM分析 / グラフ / 観光予測      │
├──────────────┬──────────────┬────────────────────────────┤
│ Scoring      │ Features     │ Pipeline                   │
│ Engine       │              │ (Data Collection)          │
│ 27 dimensions│ Analytics    │ 100+ external sources      │
│ PPML gravity │ Digital Twin │ 15 sanctions lists         │
│ Dual-Scale   │ Tourism      │ 22 country clients         │
│ Bayesian     │ Graph        │ Tourism stats              │
└──────────────┴──────────────┴────────────────────────────┘
```

---

## 3. リスクスコアリングエンジン (27次元)

### 加重次元一覧

| # | 次元 | 内容 | 主要データソース |
|---|------|------|------------------|
| 1 | economic | 経済リスク | World Bank, IMF |
| 2 | currency | 為替リスク | Frankfurter/ECB |
| 3 | weather | 気象リスク | OpenMeteo |
| 4 | compliance | コンプライアンス | FATF, Basel AML |
| 5 | political | 政治リスク | V-Dem, WJP |
| 6 | climate_risk | 気候リスク | ND-GAIN, Climate TRACE |
| 7 | cyber_risk | サイバーリスク | CISA KEV, ITU |
| 8 | sanctions | 制裁リスク | OFAC, UN, EU + 12リスト |
| 9 | disaster | 自然災害 | USGS, GDACS, BMKG |
| 10 | trade | 貿易リスク | UN Comtrade |
| 11 | labor | 労働リスク | ILO, ITUC |
| 12 | conflict | 紛争リスク | ACLED, GPI |
| 13 | food_security | 食料安全保障 | WFP, FEWS NET |
| 14 | humanitarian | 人道リスク | OCHA, ReliefWeb |
| 15 | internet | インターネット | OONI, Internet Outage |
| 16 | port_congestion | 港湾混雑 | PortWatch, AIS |
| 17 | geo_risk | 地政学リスク | SIPRI, GDELT |
| 18 | health | 健康リスク | WHO, Disease.sh |
| 19 | maritime | 海上輸送 | Lloyd's, MarineTraffic |
| 20 | aviation | 航空輸送 | OpenSky, IATA |
| 21 | legal | 法的リスク | Caselaw MCP |
| 22 | typhoon | 台風リスク | 気象庁, IBTrACS |
| 23 | energy | エネルギー | EIA, OPEC |
| 24 | japan_economy | 日本経済 (参考) | BOJ, e-Stat |
| 25 | sc_vulnerability | SC脆弱性 | HHI, 単一調達源率 |
| 26 | person_risk | 人的リスク | OpenOwnership, ICIJ, Wikidata |
| 27 | capital_flow | 資金フロー | Chinn-Ito, IMF AREAER, SWIFT |

### スコア計算式
```
composite = 60% × weighted_sum + 30% × peak_dimension + 10% × second_peak
sanctions = 100 → 即時 CRITICAL (overall = 100)
```

---

## 4. データパイプライン (100+ ソース)

### 制裁リスト (15ソース)
OFAC SDN, UN Security Council, EU Sanctions, UK OFSI, Swiss SECO, Canada SEMA, Australia DFAT, Japan METI, Japan MOFA, BIS Entity List, OpenSanctions, ICIJ Offshore Leaks

### 地域別クライアント
| 地域 | クライアント |
|------|-------------|
| 東アジア | NBS China, KOSIS Korea, Taiwan Trade |
| 東南アジア | ASEAN Stats, DOSM Malaysia, GSO Vietnam, MPA Singapore |
| 西側 | Eurostat, ILO STAT, AfDB |

### 観光統計パイプライン
| カテゴリ | クライアント | データ |
|----------|-------------|--------|
| UNWTO | unwto_client.py | WDI経由4指標 |
| JNTO | jnto_client.py | 20市場×月次 |
| ソースマーケット | china/korea/taiwan/us/australia_client.py | 6カ国アウトバウンド |
| 競合 | thailand/korea_inbound/taiwan_inbound/europe_client.py | 6カ国インバウンド |
| フライト | flight_supply_client.py | OpenFlights, 15カ国容量指数 |
| 距離 | effective_distance_client.py | EFD (Haversine + ペナルティ) |
| 文化 | cultural_distance_client.py | Hofstede 6次元 + 言語距離 |

---

## 5. 観光需要モデル

### 5-1. PPML構造重力モデル
```
E[T_ij] = exp(α_i + β_j + γ₁·TFI_i + γ₂·ln(GDP) + γ₃·ln(EXR) + γ₄·FLIGHT + γ₅·TMI + ...)
```
- 手法: Poisson GLM (Santos Silva & Tenreyro, 2006)
- Pseudo R² = 0.9874
- 為替弾性値 = -1.12 (円高1% → 訪日1.12%減)
- 11カ国 × 8年パネル、HC3ロバスト標準誤差

### 5-2. Travel Friction Index (TFI)
```
TFI = 0.4 × 文化的距離(Kogut-Singh+言語) + 0.4 × log(実効飛行距離) + 0.2 × ビザ障壁
```
| 国 | TFI | 解釈 |
|---|---|---|
| KR | 12.5 | 最低摩擦（地理・文化・言語が最も近い） |
| TW | 18.2 | 低摩擦 |
| CN | 22.4 | 低摩擦（ビザがやや障壁） |
| HK | 20.1 | 低摩擦 |
| SG | 28.5 | 中摩擦 |
| TH | 35.2 | 中摩擦 |
| AU | 55.3 | 高摩擦（距離） |
| US | 62.4 | 高摩擦（距離+文化） |
| DE | 67.2 | 高摩擦 |
| SA | 78.5 | 最高摩擦 |

### 5-3. Cultural Inertia Coefficient (CIC)
```
CIC = Structural_CIC(1-TFI/100) + Psychological_CIC(超過需要トレンド)
```
- 高CIC (KR=0.875): 構造的慣性が強い。リスク後に速く回帰
- 低CIC (US=0.376): ブランド効果に依存。リスクに脆弱

### 5-4. Dual-Scale モデル
```
予測 = α(h)×LSTM構造成分 + (1-α(h))×Transformerサイクル成分 × 季節性
α(h) = min(0.3 + 0.05h, 0.8)  — 短期→Transformer主導、長期→LSTM主導
```
- LSTM: PyTorch (CPU) + numpyフォールバック、10年の文化的慣性
- Transformer: Encoder-Decoder、未来の既知情報をDecoder入力、Quantile Loss
- STL季節分解: 2015-2019コロナ前データ、5カ国×60ヶ月

### 5-5. ベイズ更新 (粒子フィルタ)
```
初期分布: Dual-Scale予測 → 正規分布近似
観測: 月次JNTO実績
更新: 尤度重み付け → 系統的リサンプリング
```
- 1000粒子、ESS < N/2 でリサンプリング
- 実績入力で予測を即座に更新

### 5-6. リスク期待損失調整
```
期待損失 = Σ(シナリオ発生確率 × 影響率)
調整後予測 = ベースライン × (1 - 期待損失)
```
| 国 | 期待損失(ベース) | 主要シナリオ |
|---|---|---|
| CN | 21.2% | 日中関係(6.0%), 景気後退(5.0%), 円高(4.2%), 感染症(6.0%) |
| KR | 7.6% | 景気停滞(2.0%), 円高(3.2%), 日韓関係(2.4%) |
| TW | 9.8% | 台湾海峡(4.2%), 景気(2.7%), 円高(2.8%) |
| TH | 14.5% | 政情不安(7.5%), バーツ安(3.5%), 競合(3.5%) |
| US | 4.2% | 景気後退(3.0%), フライト減(1.2%) |

### 5-7. 地域分散モデル
```
都道府県(t) = Σ_i [国i予測(t) × 都道府県シェア(i,j) × (1 - ローカルリスク(j,t))]
```
- 47都道府県 × 11カ国のシェア行列
- 国籍バイアス: 韓国→福岡20%, 豪州→北海道22%, 米国→東京40%
- ローカルリスク: 沖縄台風(7-10月+8%), 北海道雪(12-3月+3%)

---

## 6. デジタルツインレイヤー

### 6-1. 在庫枯渇予測
```
risk_adjusted_lead_time = lead_time × (1 + risk_score/200)
gap_days = risk_adjusted_lead_time - current_stock_days
```

### 6-2. 生産カスケードシミュレーター
- NetworkX DiGraphでBOM依存関係をモデル化
- 部品欠品 → 生産停止のカスケード追跡
- 財務影響（日次売上損失）の自動計算

### 6-3. 緊急調達最適化
- scipy.linprog で分割発注最適化
- MOQ制約 + 予算制約
- リスクコストROI分析

### 6-4. 拠点リスクヒートマップ
- GDACS災害アラート(500km圏内)
- チョークポイント距離
- HHI地理的集中度

### 6-5. 輸送リスク統合
- チョークポイント7箇所の通過判定
- 代替ルートのコスト・日数計算
- 4モード(海上/航空/鉄道/トラック)の複合評価

---

## 7. 統合グラフエンジン

### SCIGraph (Supply Chain Intelligence Graph)
- 4種ノード: 企業 / 人物 / 製品 / 拠点
- 10種エッジ: SUPPLIES_TO / OWNED_BY / DIRECTS / OPERATES_IN 等
- NetworkX MultiDiGraph ベース

### 3ホップ制裁検索
```
1ホップ = 100点, 2ホップ = 70点, 3ホップ = 40点
```
- BFS探索 + PageRankリスク伝播
- 紛争鉱物パス検出 (DFS)

---

## 8. MCPツール一覧 (63本)

### リスクスコアリング (10本)
| ツール | 説明 |
|--------|------|
| get_risk_score | 国・地域のリスクスコア取得 |
| get_location_risk | 詳細なロケーションリスク |
| compare_locations | 複数国の比較 |
| compare_risk_scenarios | シナリオ比較 |
| compare_risk_trends | トレンド比較 |
| get_risk_report_card | リスクレポートカード |
| get_global_risk_dashboard | グローバルダッシュボード |
| get_data_quality_report | データ品質レポート |
| get_risk_alerts | リスクアラート |
| get_hidden_risk_exposure | 隠れたリスク曝露 |

### BOM・物レイヤー (6本)
| ツール | 説明 |
|--------|------|
| analyze_bom_risk | BOMリスク分析 |
| analyze_goods_layer | 物レイヤー統合分析 |
| find_actual_suppliers | 通関記録からのサプライヤー特定 |
| build_supply_chain_from_ir | IR（有報）からのSC構築 |
| get_conflict_minerals_status | 紛争鉱物チェック |
| analyze_product_complete | 製品完全分析 |

### サプライヤー分析 (6本)
| ツール | 説明 |
|--------|------|
| bulk_screen | 一括制裁スクリーニング |
| bulk_assess_suppliers | 一括サプライヤー評価 |
| get_supplier_materials | サプライヤー取扱品目 |
| search_customs_records | 通関記録検索 |
| get_conflict_mineral_report | 紛争鉱物レポート |
| get_commodity_exposure | コモディティ曝露 |

### ポートフォリオ・ベンチマーク (4本)
| ツール | 説明 |
|--------|------|
| analyze_portfolio | ポートフォリオ分析 |
| benchmark_risk_profile | 業界ベンチマーク (15業種) |
| get_concentration_risk | 集中リスク |
| analyze_risk_correlations | 相関分析 |

### ルート・シミュレーション (5本)
| ツール | 説明 |
|--------|------|
| analyze_route_risk | ルートリスク分析 |
| estimate_disruption_cost | 途絶コスト試算 |
| analyze_score_sensitivity | 感度分析 |
| simulate_disruption | 途絶シミュレーション |
| simulate_what_if | What-Ifシナリオ |

### 予測・監視 (4本)
| ツール | 説明 |
|--------|------|
| find_leading_risk_indicators | 先行指標 |
| get_forecast_accuracy | 予測精度 |
| explain_score_change | スコア変化の説明 |
| monitor_supplier | サプライヤー監視 |

### 人レイヤー (3本)
| ツール | 説明 |
|--------|------|
| screen_ownership_chain | UBO所有チェーン |
| check_pep_connection | PEP接続検査 |
| get_officer_network | 役員ネットワーク |

### 統合グラフ (5本)
| ツール | 説明 |
|--------|------|
| find_sanction_network_exposure | 3ホップ制裁検索 |
| build_supply_chain_graph_tool | SCグラフ構築 |
| get_network_risk_score | ネットワークリスク |
| analyze_network_vulnerability | ネットワーク脆弱性 |
| optimize_procurement | 調達最適化 |

### デジタルツイン (6本)
| ツール | 説明 |
|--------|------|
| scan_stockout_risks | 在庫枯渇スキャン |
| simulate_production_impact | 生産カスケード |
| get_emergency_procurement_plan | 緊急調達計画 |
| analyze_transport_risks | 輸送リスク分析 |
| get_facility_risk_map | 拠点リスクマップ |
| run_scenario_simulation | シナリオシミュレーション |

### 観光・インバウンド (9本)
| ツール | 説明 |
|--------|------|
| assess_inbound_tourism_risk | インバウンドリスク評価 |
| get_inbound_market_ranking | 市場ランキング |
| forecast_visitor_volume | 来訪者予測 |
| analyze_competitor_performance | 競合分析 |
| predict_regional_distribution | 都道府県分配 |
| decompose_visitor_change | 変動要因分解 |
| get_capital_flow_risk | 資金フローリスク |
| forecast_japan_inbound | 日本全国予測(PPML+ベイズ) |
| forecast_prefecture_inbound | 都道府県予測 |

### その他 (5本)
| ツール | 説明 |
|--------|------|
| screen_sanctions | 制裁スクリーニング |
| screen_supplier_reputation | 評判スクリーニング |
| infer_supply_chain | SC推定 |
| get_supply_chain_graph | SCグラフ取得 |
| generate_dd_report | DDレポート生成 |

---

## 9. ダッシュボード仕様

### 9-1. ランディングページ (`dashboard/index.html`, 1.9KB)
- 3カード型リンク: Logistics / Inbound / Legacy
- ダークテーマ (#0f1117)

### 9-2. Logistics Risk Dashboard (`dashboard/logistics.html`, 54KB)
**URL**: `/dashboards/logistics.html`

**レイアウト**:
```
┌──────────────────────────────────────────────────────┐
│ HEADER | [次元選択(10種)] [All/Sea/Air切替]            │
├────────────────────────┬─────────────────────────────┤
│                        │ チョークポイント状況          │
│  世界地図 (60%)        │ (7箇所、リスク順)            │
│                        │─────────────────────────────│
│  ・40カ国リスク塗り分け │ 選択ルート詳細               │
│  ・海路5本(太さ=リスク) │ ・チョークポイント別リスク    │
│  ・空路5本(破線)       │ ・代替ルートのコスト・日数    │
│  ・チョークポイント7箇所│                              │
├────────────────────────┴─────────────────────────────┤
│ ルートリスクランキング（横スクロール）                 │
└──────────────────────────────────────────────────────┘
```

**技術**: D3.js v7 + TopoJSON (CDN), Natural Earth投影

**ルート描画**:
- 太さ: `1 + (risk/100) × 5` (1px〜6px)
- 色: `d3.scaleLinear([0,50,80,100], ["#4a9eff","#ffd43b","#ff6b35","#ff0000"])`
- ホバーで他ルート暗転 + 詳細パネル表示

**チョークポイント**: 六角形シンボル、サイズ=リスク比例、70+でCSS脈動アニメーション

| チョークポイント | リスク | ステータス |
|-----------------|--------|-----------|
| バベルマンデブ | 82 | フーシ派攻撃 |
| ホルムズ海峡 | 74 | イラン緊張 |
| スエズ運河 | 67 | 通航制限 |
| 台湾海峡 | 55 | 監視強化 |
| パナマ運河 | 49 | 水位低下 |
| マラッカ海峡 | 36 | 通常運航 |
| 喜望峰 | 28 | 迂回航路増 |

**主要海路 (5本)**:
| ルート | リスク | チョークポイント |
|--------|--------|-----------------|
| 横浜→ロッテルダム(スエズ) | 72 | バベルマンデブ(82), スエズ(67) |
| 欧州→アジア(紅海) | 80 | スエズ(67), バベルマンデブ(82) |
| SG→ドバイ(ホルムズ) | 72 | マラッカ(36), ホルムズ(74) |
| 横浜→ムンバイ(マラッカ) | 42 | マラッカ(36) |
| 上海→LA(太平洋) | 35 | なし |

**40カ国リスクデータ**: MM(81), YE(80), KP(78), UA(75), IR(72), ... JP(15)

### 9-3. Inbound Tourism Risk Dashboard (`dashboard/inbound.html`, 50KB)
**URL**: `/dashboards/inbound.html`

**レイアウト**:
```
┌──────────────────────────────────────────────────────┐
│ HEADER | [ソース国] [都道府県] [現状/円安/円高/日中悪化]│
├─────────────────────┬────────────────────────────────┤
│  世界地図           │  日本地図                       │
│  (バブルチャート)    │  (47都道府県、対数スケール)     │
│  サイズ=訪日シェア  │  色=来訪者数(5万〜1800万)       │
│  色=期待損失率      │  クリックで都道府県選択          │
│  [38vh]             │  [38vh]                        │
├─────────────────────┴────────────────────────────────┤
│ [ソース国→目的地] [リスク] [予測変化] [要因] [R²]     │
├──────────────────────────────┬────────────────────────┤
│  月次来訪者数チャート        │ 期待損失の内訳         │
│  (Chart.js)                  │ ┌──────────────────┐  │
│  2019ピーク→2020壊滅→       │ │ 日中関係  6.0% ██│  │
│  2023急回復→2025予測         │ │ 景気後退  5.0% █ │  │
│  ┤実績(灰)    │ベース(青)   │ │ 円高      4.2% █ │  │
│  │            │楽観(緑破線) │ │ 感染症    6.0% ██│  │
│  │            │悲観(赤破線) │ └──────────────────┘  │
│  │ 信頼区間帯(青半透明)      │ 合計: 21.2%          │
│  └──────────────────────     │                      │
│   2019  2021  2023  │ 2025  │                      │
│   縦線: コロナ/解禁/予測開始  │                      │
└──────────────────────────────┴────────────────────────┘
```

**技術**: D3.js v7 + TopoJSON + Chart.js 4.x (CDN)

**世界地図 バブルチャート (8市場)**:
| 国 | シェア | 期待損失 | 2024来訪者 | 予測変化 |
|---|---|---|---|---|
| CN | 24.8% | 21.2% | 520万 | -8% |
| KR | 19.3% | 7.6% | 860万 | +5% |
| TW | 17.2% | 9.8% | 480万 | +3% |
| US | 8.5% | 4.2% | 360万 | +12% |
| HK | 6.2% | 11.2% | 131万 | +2% |
| AU | 4.8% | 5.5% | 62万 | +9% |
| TH | 3.2% | 14.5% | 42万 | -3% |
| SG | 2.8% | 3.8% | 38万 | +6% |

**日本地図 (47都道府県 来訪者予測 万人/年)**:
| 都道府県 | 来訪者 | 都道府県 | 来訪者 |
|----------|--------|----------|--------|
| 東京 | 1,800 | 兵庫 | 110 |
| 大阪 | 1,000 | 長崎 | 100 |
| 京都 | 500 | 広島 | 85 |
| 北海道 | 390 | 石川 | 72 |
| 福岡 | 335 | 長野 | 67 |
| 沖縄 | 280 | 静岡 | 56 |
| 愛知 | 220 | 栃木 | 55 |
| 神奈川 | 170 | 山梨 | 48 |
| 奈良 | 140 | 新潟 | 45 |

**時系列チャート**:
- 実績: 2019-2024月次（千人単位、5カ国分ハードコード）
- 予測: 2025年12ヶ月（ベース/楽観/悲観 + p10-p90信頼区間）
- 縦線: コロナ開始(2020/03, 赤) / 入国解禁(2022/10, 緑) / 予測開始(2025/01, 黄)
- シナリオ切替: [現状維持] [円安10%] [円高10%] [日中悪化]

**インタラクション**:
- 世界地図クリック → ソース国切替 → チャート更新
- 日本地図クリック → 都道府県切替 → チャート更新
- シナリオボタン → 確率分布シフト → チャート更新

### 9-4. Legacy Dashboard (`dashboard/legacy.html`, 154KB)
- 10タブ: Risk Overview / Sanctions / BOM / Routes / Timeseries / Alerts / Analytics / Supply Chain Graph / Digital Twin / Scenario Simulator
- Leaflet.js 拠点マップ
- Plotly.js タイムライン

---

## 10. データベース

### risk.db (11MB)
- sanctions: OFAC(18,712), UN(1,002), 他10リスト
- risk_scores: 時系列リスクスコア

### timeseries.db (4.9MB)
- risk_scores: 18/27次元 × 50カ国
- forecast_accuracy: 予測精度記録

### tourism_stats.db (64KB)
- outbound_stats: 15市場 × 5年 (75行)
- inbound_stats: 7デスティネーション × 5年 (35行)
- japan_inbound: 20市場 × 5年 (100行)
- gravity_variables: 15市場 × 5年 (75行)

### internal_logistics.db (64KB)
- inventory: 177件 (50部品 × 5拠点)
- purchase_orders: 30件
- production_plan: 60件
- locations: 11件
- transport_routes: 20件
- procurement_costs: 99件

### cache.db (16KB)
- SmartCache: Redis/SQLiteデュアルバックエンド

---

## 11. 起動方法

```bash
# サーバー起動
cd ~/supply-chain-risk
.venv311/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000

# ダッシュボード
open http://localhost:8000/dashboards/

# MCP接続 (Claude Desktop)
.venv311/bin/python mcp_server/server.py  # SSE on port 8001

# テスト実行
.venv311/bin/python -m pytest tests/ -q --timeout=120
```

---

## 12. バージョン履歴

| バージョン | 日付 | 主要追加 |
|-----------|------|---------|
| v0.3.0 | 2026-03-15 | 22次元エンジン, 9 MCPツール |
| v0.9.0 | 2026-03-27 | 物レイヤー, 25次元, 43ツール |
| v1.0.0 | 2026-03-28 | 人レイヤー, 統合グラフ, 48ツール |
| v1.1.0 | 2026-03-28 | デジタルツイン, 54ツール |
| v1.3.0 | 2026-04-02 | 観光統計, 資金フロー第27次元, 61ツール |
| v1.4.0 | 2026-04-03 | Dual-Scale LSTM+Transformer, PPML, TFI, CIC, 63ツール |
