# SCRI Platform v1.5.0 — データレイク＋分析仕様書
最終更新: 2026-04-04

---

## 1. プラットフォーム概要

| 項目 | 値 |
|---|---|
| バージョン | 1.5.0 |
| Pythonソースファイル | 305 |
| MCPツール | 63 |
| APIエンドポイント | 113 |
| リスク次元 | 28 (27加重 + overall) |
| テスト | 302 pass / 11 skip / 0 fail |
| ダッシュボード | 4 (Landing + Logistics + Inbound + Legacy) |
| シナリオ | 9 (非対称・国別弾性値ベース) |
| GitHub | https://github.com/Agentic-governance/logistics-mcp |
| GitHub Pages | https://agentic-governance.github.io/logistics-mcp/ |

---

## 2. データレイク

### 2-1. データベース一覧

| DB | テーブル | 行数 | 内容 |
|---|---|---|---|
| **timeseries.db** | 3 | 135,210 | 28次元 × 51カ国 × 90日リスクスコア |
| **tourism_stats.db** | 5 | 1,832 | 観光統計・重力変数・月次インバウンド |
| **risk.db** | 5 | 21,992 | 15制裁リスト(OFAC/UN/EU等) |
| **internal_logistics.db** | 7 | 399 | 在庫/発注/生産/拠点/輸送 |
| **cache.db** | 1 | 0 | SmartCache (Redis/SQLiteデュアル) |

### 2-2. timeseries.db (135,210行)

```
risk_scores(location, dimension, score, timestamp)
```
- **28次元**: overall + 27加重次元（全次元補完済み）
- **51カ国**: 主要50カ国 + 日本
- **90日分**: 2026-01-03 〜 2026-04-02
- 季節パターン: typhoon(6-11月+20), health(冬季+10), energy(冬季+12), maritime(冬季+8)
- データソース: スコアリングエンジン + 季節パターン + 決定的ノイズ

### 2-3. tourism_stats.db (1,832行)

| テーブル | 行数 | カラム | 内容 |
|---|---|---|---|
| **japan_inbound** | 1,540 | 8 | 21カ国×月次(2019-2025/03)のJNTO訪日統計 |
| **gravity_variables** | 140 | 21 | 12カ国×7年(2019-2025)の重力モデル変数 |
| **outbound_stats** | 75 | 7 | 15市場×5年のアウトバウンド統計 |
| **inbound_stats** | 35 | 8 | 7デスティネーション×5年のインバウンド |
| **excess_demand** | 42 | 4 | TFI超過需要（ブランド効果追跡） |

#### japan_inbound スキーマ
```sql
(source_country TEXT, year INT, month INT, arrivals INT,
 purpose_leisure_pct FLOAT, purpose_business_pct FLOAT,
 avg_stay_days FLOAT, avg_spend_jpy INT, data_source TEXT)
```
- 21カ国: KOR, CHN, TWN, USA, AUS, THA, HKG, SGP, MYS, PHL, VNM, IND, IDN, DEU, FRA, GBR, CAN, ITA, RUS, SAU, ESP
- 月次データ: JNTO年次公表値 × コロナ回復パターン × 国別季節パターンで生成
- ISO3コード使用（API側でISO2→ISO3変換あり）

#### gravity_variables スキーマ (21カラム)
```sql
(source_country, year, month,
 -- 基本
 ln_gdp_source, ln_exr, ln_flight_supply, visa_free, bilateral_risk, tfi,
 -- 経済・余暇 (v1.5.0追加)
 gdp_per_capita_ppp, consumer_confidence, unemployment_rate,
 annual_leave_days, leave_utilization_rate, annual_working_hours, remote_work_rate,
 -- 文化的関心 (v1.5.0追加)
 language_learners, restaurant_count, japan_travel_trend,
 -- 合成指標
 travel_momentum_index, outbound_total)
```
- 12カ国: KR, CN, TW, US, AU, TH, HK, SG, DE, FR, GB, IN
- 経済データ: World Bank WDI + ハードコードフォールバック
- 余暇データ: OECD/ILO + LEISURE_HARDCODE (有給取得率/リモートワーク率等)
- 文化データ: JF日本語学習者(2021基準外挿) + JFOODO日本食レストラン(2023基準外挿)
- TMI: `(leave_util + remote_work×2 + (1-unemp/15)) / 3`

### 2-4. internal_logistics.db (399行)

| テーブル | 行数 | 内容 |
|---|---|---|
| inventory | 177 | 50部品 × 5拠点 |
| purchase_orders | 30 | 発注残 |
| production_plan | 60 | 3製品 × 30日 |
| locations | 11 | 工場3 + 倉庫5 + 港湾3 |
| transport_routes | 20 | 主要輸送ルート |
| procurement_costs | 99 | 50部品 × 複数仕入先 |

### 2-5. risk.db (21,992行)

- OFAC SDN: ~18,700エンティティ
- UN Security Council: ~1,000
- その他13リスト (EU, UK OFSI, Swiss SECO, Canada, Australia DFAT, Japan METI/MOFA, BIS等)

---

## 3. 分析モデル

### 3-1. リスクスコアリングエンジン (28次元)

```
composite = 60% × weighted_sum + 30% × peak + 10% × second_peak
sanctions = 100 → 即時 CRITICAL
WEIGHTS合計 = 1.0000
```

全28次元: overall, economic, currency, weather, compliance, political, japan_economy, climate_risk, cyber_risk, sanctions, disaster, trade, labor, conflict, food_security, humanitarian, internet, port_congestion, geo_risk, health, maritime, aviation, legal, typhoon, energy, person_risk, capital_flow, sc_vulnerability

### 3-2. PPML構造重力モデル

```
E[T_ij] = exp(α_i + β_j + γ₁·TFI + γ₂·ln(GDP) + γ₃·ln(EXR)
              + γ₄·FLIGHT + γ₅·TMI + γ₆·bilateral + ...)
```
- 手法: Poisson GLM (Santos Silva & Tenreyro, 2006)
- **Pseudo R² = 0.9874**
- 為替弾性値 = **-1.12**
- 10説明変数 + ソース国固定効果 + 年固定効果
- 11カ国 × 8年パネル, HC3ロバスト標準誤差

### 3-3. Travel Friction Index (TFI)

```
TFI = 0.4×文化的距離(Kogut-Singh+言語) + 0.4×log(EFD) + 0.2×ビザ障壁
```

| 国 | TFI | 文化距離 | EFD(km) | ビザ |
|---|---|---|---|---|
| KR | 12.5 | 低 | 1,200 | 無査証 |
| TW | 18.2 | 低 | 2,500 | 無査証 |
| CN | 22.4 | 低 | 2,800 | 要ビザ |
| US | 62.4 | 高 | 13,000 | 無査証 |
| DE | 67.2 | 高 | 13,500 | 無査証 |

### 3-4. Cultural Inertia Coefficient (CIC)

```
CIC = Structural(1-TFI/100) + Psychological(超過需要トレンド)
```
- KR: 0.875 (高慣性) — リスク後に速く回帰
- US: 0.376 (低慣性) — ブランド効果に依存

### 3-5. 二国間為替モデル (v1.5.0新規)

| 国 | 通貨 | 為替弾性値 | 意味 |
|---|---|---|---|
| KR | KRW | -1.05 | 近距離→感度やや低 |
| CN | CNY | -0.95 | 管理通貨→感度低 |
| US | USD | -1.18 | 長距離→感度高 |
| AU | AUD | -1.22 | 長距離→感度最高 |
| HK | HKD | -1.00 | USDペッグ |

弾性値の意味: 「その国通貨に対して円が1%安くなると、訪日が弾性値%増える」

### 3-6. 非対称シナリオエンジン (v1.5.0新規)

9シナリオ、各シナリオは**国別に異なる方向・異なる幅**の変化を生む。

| シナリオ | 日本全体 | KR | CN | TW | US | AU |
|----------|---------|----|----|----|----|-----|
| **現状維持** | 0% | 0% | 0% | 0% | 0% | 0% |
| **円安10%** | +10.5% | +10.5% | +9.5% | +10.8% | +11.8% | +12.2% |
| **円高10%** | -10.5% | -10.5% | -9.5% | -10.8% | -11.8% | -12.2% |
| **中国刺激策** | +4.2% | +0.5% | **+18.5%** | +1.0% | 0% | 0% |
| **アジア増便** | +4.8% | **+9.0%** | 0% | **+9.0%** | 0% | 0% |
| **日中関係悪化** | -11.2% | +2.0% | **-38.5%** | -3.0% | +0.5% | +0.3% |
| **米国景気後退** | -3.2% | +1.5% | +0.5% | +1.0% | **-16.8%** | -2.5% |
| **台湾海峡緊張** | -8.5% | +1.5% | -8.0% | **-28.5%** | +0.5% | +0.3% |
| **スタグフレーション** | -4.8% | -3.2% | **-14.8%** | -1.5% | **+7.2%** | -7.3% |

ポートフォリオ効果: スタグフレーションではUS↑とCN↓が逆方向に動き、日本全体への影響が個別市場より小さくなる。

### 3-7. ガウス過程 (GP) カーネル

```
k(t,t') = k_seasonal(12ヶ月周期) × k_trend(RBF 3年) + k_risk(Matern OU 3ヶ月) + k_noise
```
- gpytorch 1.15.2 + PyTorch 2.11.0 インストール済み
- 現在はnumpyフォールバックで動作（GPモデル未学習）
- カレンダーイベント16種の需要倍率×不確実性倍率でフォールバック予測を非線形化

### 3-8. カレンダーイベント (16種)

| イベント | 月 | 需要倍率 | 不確実性倍率 | 対象国 |
|----------|---|---------|------------|--------|
| 春節 | 2月 | 0.45 | 2.5 | CN/TW/HK/SG/MY |
| 国慶節 | 10月 | 2.2 | 1.8 | CN |
| 秋夕 | 9月 | 0.5 | 2.2 | KR |
| 桜シーズン | 4月 | 1.8 | 2.0 | 全市場 |
| 台風シーズン | 9月 | 0.75 | 3.0 | アジア |
| 豪州スキー | 7月 | 2.5 | 1.8 | AU/NZ |
| 米国夏休み | 7月 | 1.5 | 1.3 | US/CA/GB |

### 3-9. Dual-Scale モデル

- LSTM構造成分: 10年慣性 (PyTorch定義済み、numpyフォールバック稼働)
- Transformer サイクル成分: 未来既知情報入力 (同上)
- 動的α: `min(0.3+0.05h, 0.8)` — 短期→Transformer、長期→LSTM
- ベイズ更新: SMC粒子フィルタ 1000粒子

### 3-10. リスク期待損失モデル

| 国 | 期待損失(ベース) | 主要シナリオ |
|---|---|---|
| CN | 21.2% | 日中関係(6.0%), 景気(5.0%), 円高(4.2%), 感染症(6.0%) |
| KR | 7.6% | 景気(2.0%), 円高(3.2%), 日韓関係(2.4%) |
| TW | 9.8% | 海峡(4.2%), 景気(2.7%), 円高(2.8%) |
| TH | 14.5% | 政情(7.5%), バーツ安(3.5%), 競合(3.5%) |
| US | 4.2% | 景気(3.0%), フライト減(1.2%) |

---

## 4. データ収集パイプライン

### 4-1. 外部データソース (120+)

| カテゴリ | ソース数 | 主要ソース |
|----------|---------|-----------|
| 制裁リスト | 15 | OFAC, UN, EU, OFSI, SECO, DFAT, METI, MOFA |
| 経済統計 | 8 | World Bank WDI, IMF WEO, OECD MEI |
| 紛争・安全保障 | 5 | ACLED, GPI, SIPRI, GDELT |
| 災害・気象 | 6 | USGS, GDACS, BMKG, OpenMeteo |
| 海上・航空 | 5 | OpenSky, AIS, PortWatch, OpenFlights |
| 貿易統計 | 5 | UN Comtrade, ImportYeti, BACI, EU Comext, 日本税関 |
| 観光統計 | 12 | JNTO, UNWTO/WDI, 台湾観光署, KTO, MOTS, ABS |
| 文化的関心 | 3 | JF日本語学習者, JFOODO日本食レストラン, Google Trends |
| 為替・金融 | 3 | Frankfurter, Chinn-Ito, IMF AREAER |
| 企業・人物 | 5 | OpenOwnership, ICIJ, Wikidata, OpenSanctions, Hofstede |

### 4-2. 観光統計クライアント一覧

| クライアント | ファイル | データ |
|-------------|---------|--------|
| UNWTOClient | unwto_client.py | WDI経由4指標 |
| JNTOClient | jnto_client.py | 20市場×月次 |
| EconomicLeisureClient | economic_leisure_client.py | WB/OECD/ILO + 12カ国ハードコード |
| CulturalInterestClient | cultural_interest_client.py | JF/JFOODO/Google Trends |
| BilateralFXClient | bilateral_fx_client.py | 12通貨 Frankfurter API |
| FlightSupplyClient | flight_supply_client.py | OpenFlights 15カ国容量指数 |
| EffectiveFlightDistanceClient | effective_distance_client.py | Haversine + ペナルティ |
| CulturalDistanceClient | cultural_distance_client.py | Hofstede 6次元 + 言語距離 |
| CompetitorStatsClient | competitor_stats_client.py | 競合8カ国インバウンド |
| 6カ国個別クライアント | source_markets/*.py | CN/KR/TW/US/AU/Others |

---

## 5. ダッシュボード仕様

### 5-1. Logistics Risk (`logistics.html`, 69KB)

**URL**: `/dashboards/logistics.html` / [GitHub Pages](https://agentic-governance.github.io/logistics-mcp/logistics.html)

```
┌──────────────────────────────────────────────────────┐
│ HEADER | [次元10種] [All/Sea/Air] [シナリオ3種] [LIVE] │
│ [シナリオバナー: 日本全体-11.2% 重影響5カ国]          │
├───────────────────────┬──────────────────────────────┤
│ 世界地図(60%)         │ チョークポイント(7箇所)       │
│ 49カ国リスク塗り分け  │ 30日閉鎖確率+迂回コスト      │
│ 海路5本+空路5本       │ 選択ルート詳細               │
│ 影響国=赤脈動ハイライト│ 期待追加コスト+推奨アクション │
├───────────────────────┴──────────────────────────────┤
│ ルートリスクランキング（横スクロール）                 │
└──────────────────────────────────────────────────────┘
```

**ホバーツールチップ内容**:
- 国: リスクスコア + **90日調達障害確率XX%** + 主要リスク要因4件
- チョークポイント: **30日通航制限確率XX%** + 迂回日数+コスト(百万円)
- ルート: **期待追加コスト/航** + 推奨アクション(緑ボックス)

**シナリオ連動**: 日中悪化→中国赤ハイライト、台湾海峡→台湾海峡CP+35pt

### 5-2. Inbound Tourism Risk (`inbound.html`, 77KB)

**URL**: `/dashboards/inbound.html` / [GitHub Pages](https://agentic-governance.github.io/logistics-mcp/inbound.html)

```
┌──────────────────────────────────────────────────────┐
│ HEADER | [ソース国] [都道府県] [9シナリオ▼] [LIVE]    │
├────────────────────────┬─────────────────────────────┤
│ 世界地図(バブル)        │ 日本地図(47都道府県,対数)   │
│ サイズ=訪日シェア      │ 色=来訪者数                  │
│ 色=シナリオ方向(緑/赤) │ [30vh]                       │
├────────────────────────┴─────────────────────────────┤
│ セクション1: 全期間推移 2019→コロナ→回復→現在 [15vh] │
├──────────────────────────────────────────────────────┤
│ セクション2: 予測フォーカス 2026-04〜2027-12 [25vh]  │
│ 3シナリオ線(常時表示) + 信頼区間 + 不確実性マーカー  │
│ シナリオ解説 + ポートフォリオ効果パネル               │
│ ┌────────────────────────────────────────────┐       │
│ │ 📊 US↑7.2% / CN↓14.8% / 日本全体-4.8%    │       │
│ │ 市場分散により変動が小さくなっています      │       │
│ └────────────────────────────────────────────┘       │
├──────────────────────────────────────────────────────┤
│ セクション3: 国別影響テーブル(シナリオ選択時) [20vh]  │
│ 市場 | 変化率 | 内訳(為替/GDP/政治/フライト)          │
│ 🇨🇳CN | ▼-14.8% | fx-7.6% gdp-2.5%                 │
│ 🇺🇸US | ▲+7.2%  | fx+5.9% gdp+1.2%                 │
└──────────────────────────────────────────────────────┘
```

**9シナリオドロップダウン**:
- 楽観: 円安10% / 中国刺激策 / アジア増便
- 悲観: 円高10% / 日中関係悪化 / 米国景気後退 / 台湾海峡緊張
- 複合: スタグフレーション混合

**バブルホバーツールチップ**:
- 3シナリオ来訪者数(楽観/基本/悲観)
- リスク顕在化確率(%)
- 最悪経済損失(億円)
- リスク要因内訳(確率×影響)

---

## 6. API一覧 (113本)

### ダッシュボード (2本)
- GET /api/v1/dashboard/global-risk — 49カ国リスク(timeseries.db)
- GET /api/v1/dashboard/chokepoints — 7CP動的リスク

### 観光・シナリオ (12本)
- GET /api/v1/tourism/scenarios — 9シナリオ一覧
- POST /api/v1/tourism/scenario-analysis — 国別非対称影響
- GET /api/v1/tourism/market-ranking — 市場ランキング(キャッシュ+フォールバック)
- GET /api/v1/tourism/historical — 月次実績(ISO2→ISO3変換)
- POST /api/v1/tourism/japan-forecast — GP/Dual-Scale予測
- POST /api/v1/tourism/prefecture-forecast — 都道府県予測
- POST /api/v1/tourism/decompose — 要因分解
- GET /api/v1/tourism/market-risk/{country} — 市場リスク
- GET /api/v1/tourism/competitor-analysis — 競合分析
- POST /api/v1/tourism/regional-distribution — 地域分配
- GET /api/v1/tourism/capital-flow-risk/{country} — 資金フロー

### リスクスコアリング (~30本)
### BOM・物レイヤー (~10本)
### デジタルツイン (~14本)
### 内部データ (~8本)
### その他 (~37本)

---

## 7. MCPツール (63本)

リスクスコアリング(10) + BOM(6) + サプライヤー(6) + ポートフォリオ(4) + ルート(5) + 予測(4) + 人レイヤー(3) + グラフ(5) + デジタルツイン(6) + 観光(9) + その他(5)

---

## 8. バージョン履歴

| Ver | 日付 | 主要追加 |
|-----|------|---------|
| 0.3.0 | 03-15 | 22次元, 9ツール |
| 0.9.0 | 03-27 | 物レイヤー, 43ツール |
| 1.0.0 | 03-28 | 人レイヤー, 統合グラフ, 48ツール |
| 1.1.0 | 03-28 | デジタルツイン, 54ツール |
| 1.3.0 | 04-02 | 観光統計, 資金フロー第27次元, 61ツール |
| 1.4.0 | 04-03 | Dual-Scale, PPML, TFI, CIC, API駆動ダッシュボード, 63ツール |
| **1.5.0** | **04-04** | **GPカーネル, 16カレンダーイベント, 9非対称シナリオ, 二国間FX弾性値, 経済・文化変数収集, ダッシュボードシナリオUI** |
