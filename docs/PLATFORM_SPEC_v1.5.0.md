# SCRI Platform v1.5.0 — データレイク＋分析処理 完全仕様書
最終更新: 2026-04-04

---

## 1. プラットフォーム概要

| 項目 | 値 |
|---|---|
| バージョン | 1.5.0 |
| Pythonソースファイル | 309 |
| MCPツール | 63 |
| APIエンドポイント | 114 |
| リスク次元 | 28 (27加重 + overall) |
| テスト | 301 pass / 11 skip / 0 fail |
| ダッシュボード | 4 HTML (Landing / Logistics / Inbound / Legacy) |
| GitHub | https://github.com/Agentic-governance/logistics-mcp |
| GitHub Pages | https://agentic-governance.github.io/logistics-mcp/ |

---

## 2. データレイク

### 2-1. データベース一覧

| DB | テーブル数 | 総行数 | 用途 |
|---|---|---|---|
| **timeseries.db** | 3 | 135,210 | リスクスコア時系列 (28次元×51カ国×90日) |
| **tourism_stats.db** | 7 | 2,853 | 観光統計・重力変数・月次指標 |
| **risk.db** | 5 | 21,992 | 制裁リスト (OFAC/UN/EU等15ソース) |
| **internal_logistics.db** | 7 | 399 | 在庫/発注/生産/拠点/輸送 |
| **cache.db** | 1 | 0 | SmartCache |

### 2-2. tourism_stats.db 詳細 (7テーブル, 2,853行)

| テーブル | 行数 | 国数 | 内容 | データソース |
|---|---|---|---|---|
| **japan_inbound** | 1,540 | 21 | JNTO訪日月次統計 (2019-2025/03) | JNTO公表値×コロナ回復パターン×季節パターン |
| **gravity_variables_v2** | 84 | 12 | 重力モデル全変数 (2019-2025年次) | IMF WEO / OECD / JF / JFOODO / Frankfurter |
| **monthly_indicators** | 979 | 12 | 月次経済指標 | yfinance / Frankfurter / World Bank |
| **gravity_variables** | 140 | 20 | 旧重力変数 (互換用) | 各種API + ハードコード |
| **outbound_stats** | 75 | 15 | アウトバウンド年次 | World Bank WDI ST.INT.DPRT |
| **inbound_stats** | 35 | 1 | 競合デスティネーション | World Bank WDI ST.INT.ARVL |
| **excess_demand** | — | — | TFI超過需要 | PPMLモデル残差 |

#### japan_inbound (1,540行)
```sql
(source_country TEXT, year INT, month INT, arrivals INT,
 purpose_leisure_pct, purpose_business_pct, avg_stay_days, avg_spend_jpy, data_source)
-- 21カ国: KOR,CHN,TWN,USA,AUS,THA,HKG,SGP,MYS,PHL,VNM,IND,IDN,DEU,FRA,GBR,CAN,ITA,RUS,SAU,ESP
-- ISO3コード使用 (API側でISO2→ISO3変換)
-- 月次データ: 年次公表値 × 回復パターン × 季節パターンで分解
```

#### gravity_variables_v2 (84行, 21カラム)
```
source_country, year, month,
gdp_per_capita_ppp,     -- IMF WEO 2024年10月版 (100%)
gdp_growth_rate,        -- World Bank WDI (64%)
unemployment_rate,      -- World Bank WDI / ILO (75%)
annual_leave_days,      -- OECD Employment Outlook 2024 (100%)
leave_utilization_rate,  -- OECD (100%)
annual_working_hours,   -- ILO Working Conditions (100%)
remote_work_rate,       -- OECD (100%, 2020年以前は×0.25)
travel_momentum_index,  -- 合成指標 (100%)
language_learners,      -- 国際交流基金 2021年度調査 + 成長率外挿 (100%)
restaurant_count,       -- JFOODO/農水省 2023年調査 + 成長率外挿 (100%)
flight_supply_index,    -- OpenFlights推定 2019=100 (100%)
ln_flight_supply,       -- log(flight_supply_index) (100%)
exchange_rate,          -- Frankfurter API / ハードコード (100%)
tfi,                    -- Travel Friction Index 計算値 (100%)
cultural_distance,      -- Hofstede 6次元 Kogut-Singh指数 (100%)
effective_flight_distance, -- Haversine + ペナルティ (100%)
visa_free,              -- 外務省統計 (100%)
bilateral_risk,         -- SCRIスコア (100%)
data_sources            -- JSON: 各変数のソース記録
```

**12カ国**: KR, CN, TW, US, AU, TH, HK, SG, DE, FR, GB, IN

**変数カバレッジ**:
| 変数 | カバレッジ | ソース |
|------|-----------|--------|
| gdp_per_capita_ppp | 100% | IMF WEO Oct 2024 |
| leave_utilization_rate | 100% | OECD Employment Outlook 2024 |
| language_learners | 100% | 国際交流基金 2021調査 + 成長率外挿 |
| restaurant_count | 100% | JFOODO/農水省 2023調査 + 外挿 |
| exchange_rate | 100% | Frankfurter API + ハードコード |
| flight_supply_index | 100% | OpenFlights推定 |
| tfi | 100% | Hofstede+EFD計算値 |
| travel_momentum_index | 100% | 合成 (有給取得×0.3+リモート×0.2+雇用×0.3+0.5×0.2) |
| gdp_growth_rate | 64% | World Bank WDI (TW/HK/SG欠損) |
| unemployment_rate | 75% | World Bank WDI |

#### monthly_indicators (979行)
```sql
(source_country, year, month,
 consumer_confidence,  -- OECD MEI
 stock_return,         -- yfinance月次リターン (78行)
 fx_rate_jpy,          -- Frankfurter/ハードコード (900行)
 japan_travel_trend,   -- Google Trends
 retrieved_at)
```

---

## 3. インバウンド観光需要モデル — 処理パイプライン

### 3-1. 全体アーキテクチャ

```
[データ収集]
  JNTO月次 → japan_inbound (1,540行)
  IMF/OECD/JF/JFOODO → gravity_variables_v2 (84行)
  yfinance/Frankfurter → monthly_indicators (979行)
       ↓
[PPML構造重力モデル]
  Poisson GLM, pseudo R²=0.9874
  10説明変数 + 固定効果
       ↓
[29変数確率分布]                    ← v1.5.0 新規
  variable_distributions.py
  29変数 × 29×29相関行列 (Cholesky分解)
       ↓
[Full Monte Carlo Engine]           ← v1.5.0 新規
  full_mc_engine.py
  N=3,000サンプル, 国別対数正規
  共通FXショック + 国別政治ショック + 固有ボラ
       ↓
[API /three-scenarios]
  p10=悲観, p50=ベース, p90=楽観
  分布から自然に生成（人間が決めない）
       ↓
[Dashboard inbound.html]
  フォールバック即座描画 → API成功で上書き
  世界地図バブル + 日本地図 + 3本線チャート
```

### 3-2. PPML構造重力モデル

```
E[T_ij] = exp(α_i + β_j + γ₁·TFI + γ₂·ln(GDP) + γ₃·ln(EXR)
              + γ₄·FLIGHT + γ₅·TMI + γ₆·bilateral + ...)
```
- **Pseudo R² = 0.9874**
- 為替弾性値 = **-1.12** (円高1%→訪日1.12%減)
- 11カ国×8年パネル, HC3ロバスト標準誤差
- ファイル: `features/tourism/gravity_model.py`

### 3-3. 29変数確率分布 + 相関行列

**ファイル**: `features/tourism/variable_distributions.py`

29変数の確率分布を定義し、Cholesky分解で相関付き同時サンプリング。

| カテゴリ | 変数数 | 例 |
|----------|--------|---|
| 為替 (対JPY変化率) | 6 | USD/JPY σ=10%, CNY/JPY σ=5%(管理通貨), AUD/JPY σ=13% |
| GDP成長率ショック | 5 | KR σ=1.5%pt, CN σ=2.0%pt, US σ=1.5%pt |
| 地政学リスク変化 | 4 | 日中関係 σ=12pt, 台湾海峡 σ=8pt, タイ政情 σ=10pt |
| フライト供給変化 | 5 | 日中 σ=10%(回復途上で不確実大), 日韓 σ=6% |
| 消費者信頼感 | 3 | KR σ=5pt, CN σ=4pt, US σ=6pt |
| 株価リターン | 3 | KR σ=20%, CN σ=28%, US σ=18% |
| 文化的関心 | 3 | KR σ=8pt, CN σ=10pt, US σ=8pt |

**主要な相関**:
| 変数ペア | 相関 | 意味 |
|----------|------|------|
| USD/JPY ↔ KRW/JPY | +0.65 | 円安/円高は全通貨に同方向 |
| KRW/JPY ↔ TWD/JPY | +0.70 | 東アジア通貨は強連動 |
| 中国GDP ↔ 韓国GDP | +0.55 | アジア景気連動 |
| 米国GDP ↔ USD/JPY | +0.30 | 景気好→ドル高 |
| 日中関係 ↔ 台湾海峡 | +0.40 | 中国関連リスクは連動 |
| 日中関係 ↔ 日韓関係 | +0.05 | ほぼ独立 |
| CNY/JPY ↔ 管理通貨 | σ=5% | USDの半分（管理通貨のため変動小） |
| 株価 ↔ 消費者信頼感 | +0.40〜0.55 | 資産効果 |

### 3-4. Full Monte Carlo Engine

**ファイル**: `features/tourism/full_mc_engine.py`

```python
class FullMCEngine:
    # N=3,000サンプル
    # Cholesky分解で29変数を同時サンプリング
    # 国別にPPML弾性値で来訪者数を計算

    # 各国の来訪者数 = base × calendar × exp(Σ弾性値×変数)
    # 共通FXショック: 全市場に同時影響（正の相関）
    # 国別政治ショック: CNのみ等（ゼロ相関）
    # 固有ボラ: PPML残差から推定
```

**国別パラメータ**:
| 国 | ベース(千人/月) | FX弾性値 | 政治ショックσ | 固有ボラσ | CIC |
|---|---|---|---|---|---|
| KR | 716 | -1.05 | 0.08 | 0.08 | 0.875 |
| CN | 433 | -0.95 | **0.35** | **0.22** | 0.540 |
| TW | 400 | -1.08 | 0.20 | 0.12 | 0.818 |
| US | 300 | -1.18 | 0.05 | 0.15 | 0.376 |
| AU | 53 | -1.22 | 0.04 | 0.18 | 0.447 |
| TH | 35 | -1.10 | **0.30** | **0.20** | 0.648 |
| HK | 109 | -1.00 | 0.22 | 0.18 | 0.799 |
| SG | 45 | -1.08 | 0.04 | 0.12 | 0.715 |

CNの政治ショックσ=0.35はKRの0.08の**4.4倍** → 中国市場の予測帯が圧倒的に広い

**カレンダー効果**（月別乗数）:
| 国 | ピーク月 | 乗数 | トラフ月 | 乗数 |
|---|---|---|---|---|
| KR | 8月(夏休み) | ×1.40 | 2月(ソルラル) | ×0.75 |
| CN | 10月(国慶節) | ×2.20 | 2月(春節国内回帰) | ×0.45 |
| AU | 8月(スキー) | ×2.80 | 6月 | ×0.90 |
| US | 8月(夏休み) | ×1.50 | 11月(感謝祭) | ×0.75 |

### 3-5. Travel Friction Index (TFI)

```
TFI = 0.4×文化的距離(Kogut-Singh+言語) + 0.4×log(実効飛行距離) + 0.2×ビザ障壁
```
**ファイル**: `features/tourism/travel_friction_index.py`

| 国 | TFI | 解釈 |
|---|---|---|
| KR | 12.5 | 最低摩擦（地理+文化+言語が最も近い） |
| TW | 18.2 | 低摩擦 |
| CN | 22.4 | 低摩擦（ビザ障壁あり） |
| SG | 28.5 | 中摩擦 |
| TH | 35.2 | 中摩擦 |
| AU | 55.3 | 高摩擦（距離） |
| US | 62.4 | 高摩擦（距離+文化） |
| DE | 67.2 | 高摩擦 |

### 3-6. Cultural Inertia Coefficient (CIC)

```
CIC = Structural(1-TFI/100) + Psychological(超過需要トレンド)
```
**ファイル**: `features/tourism/cultural_inertia.py`

高CIC(KR=0.875): 構造的慣性が強い → リスク後に速く回帰
低CIC(US=0.376): ブランド効果に依存 → リスクに脆弱

### 3-7. シナリオエンジン

**ファイル**: `features/tourism/scenario_engine.py`

3シナリオのドライバー:

| ドライバー | ベース | 楽観 | 悲観 |
|-----------|--------|------|------|
| USD/JPY | ±0% | +15% | -8% |
| CNY/JPY | ±0% | +8% | -10% |
| KRW/JPY | ±0% | +12% | -5% |
| 中国GDP | ±0%pt | +1.5%pt | -2.5%pt |
| 米国GDP | ±0%pt | +0.5%pt | -1.5%pt |
| 日中関係 | 0pt | +3pt | **-30pt** |
| 台湾海峡 | 0pt | 0pt | **-15pt** |
| フライト | ±0% | +10〜18% | -5〜15% |

### 3-8. ガウス過程 (GP) カーネル

**ファイル**: `features/tourism/gaussian_process_model.py`

```
k(t,t') = k_seasonal(12ヶ月周期) × k_trend(RBF 3年) + k_risk(Matern OU 3ヶ月) + k_noise
```
- gpytorch 1.15.2 + PyTorch 2.11.0
- GP学習済みチェックポイント: `models/tourism/gp_{ISO2}.pt` (8カ国)
- 16カレンダーイベント (春節/国慶節/秋夕/桜/台風等)

### 3-9. リスク期待損失

| 国 | ベース期待損失 | 主要リスクシナリオ |
|---|---|---|
| CN | 21.2% | 日中関係(6.0%) + 景気(5.0%) + 円高(4.2%) + 感染症(6.0%) |
| TH | 14.5% | 政情不安(7.5%) + バーツ安(3.5%) + 競合(3.5%) |
| TW | 9.8% | 台湾海峡(4.2%) + 景気(2.7%) + 円高(2.8%) |
| KR | 7.6% | 景気(2.0%) + 円高(3.2%) + 日韓関係(2.4%) |
| AU | 5.5% | 豪ドル安(3.6%) + 直行便減(1.8%) |
| US | 4.2% | 景気後退(3.0%) + フライト減(1.2%) |

---

## 4. データ収集パイプライン

### 4-1. 収集クライアント一覧

| クライアント | ファイル | データ | ソース |
|-------------|---------|--------|--------|
| EconomicLeisureClient | economic_leisure_client.py | GDP/CCI/失業率/余暇 | WB/OECD/ILO + ハードコード |
| CulturalInterestClient | cultural_interest_client.py | 日本語学習者/レストラン/Trends | JF/JFOODO/pytrends |
| BilateralFXClient | bilateral_fx_client.py | 12通貨対JPYレート | Frankfurter API |
| FlightSupplyClient | flight_supply_client.py | 15カ国容量指数 | OpenFlights |
| EffectiveFlightDistanceClient | effective_distance_client.py | 実効飛行距離 | Haversine計算 |
| CulturalDistanceClient | cultural_distance_client.py | Hofstede 6次元+言語距離 | Hofstede DB |
| UNWTOClient | unwto_client.py | アウトバウンド/インバウンド | World Bank WDI |
| JNTOClient | jnto_client.py | 訪日月次統計 | JNTO公表データ |
| VariableCollector | variable_collector.py | 全変数統合収集 | 上記全ソース |

### 4-2. マスター収集スクリプト

`scripts/collect_all_tourism_data.py`:
1. DBスキーマ設定 (gravity_variables_v2 + monthly_indicators)
2. 確定値投入 (GDP/余暇/言語学習者/レストラン/TFI/フライト/為替)
3. API収集 (Frankfurter/yfinance/World Bank/OECD)
4. カバレッジ検証

### 4-3. 外部API一覧 (120+ソース)

| カテゴリ | ソース数 | 主要ソース |
|----------|---------|-----------|
| 制裁 | 15 | OFAC, UN, EU, OFSI, SECO, DFAT, METI, MOFA |
| 経済 | 8 | World Bank WDI, IMF WEO, OECD MEI |
| 紛争 | 5 | ACLED, GPI, SIPRI, GDELT |
| 災害 | 6 | USGS, GDACS, BMKG, OpenMeteo |
| 海上/航空 | 5 | OpenSky, AIS, PortWatch, OpenFlights |
| 観光 | 12 | JNTO, UNWTO, 台湾観光署, KTO, MOTS, ABS |
| 文化 | 3 | JF日本語学習者, JFOODO, Google Trends |
| 為替/金融 | 3 | Frankfurter, Chinn-Ito, yfinance |
| 企業/人物 | 5 | OpenOwnership, ICIJ, Wikidata, Hofstede |

---

## 5. ダッシュボード

### 5-1. Inbound Tourism Risk (`inbound.html`, 864行)

**URL**: `/dashboards/inbound.html`
**GitHub Pages**: https://agentic-governance.github.io/logistics-mcp/inbound.html

```
[ヘッダー] SCRI Inbound Tourism Risk | v1.5.0 | STATIC/LIVE
[地図行]   世界地図バブル(8市場) | 日本地図(47都道府県)
[KPIカード] モデル名 | ベース予測
[シナリオ]  悲観(p10,赤) | ベース(p50,青) | 楽観(p90,緑)
[予測チャート] Chart.js 3本線 + 信頼区間帯 (400px)
[国別テーブル] 8カ国 × 悲観/ベース/楽観
[非対称性] 上下幅比率 + CN>KR説明
[フッター]
```

技術: ES5互換, var のみ, 全関数try-catch, フォールバック即座描画

**データフロー**:
1. フォールバック（ハードコード8カ国×21ヶ月）で即座に全描画
2. API `/three-scenarios` を8秒タイムアウトで非同期呼び出し
3. 成功: 29変数MCモデルのライブデータで上書き (model=full_mc_29vars)
4. 失敗: フォールバック表示のまま (model=STATIC)

### 5-2. Logistics Risk (`logistics.html`)

世界地図 + 海路5本/空路5本 + チョークポイント7箇所
国ホバー: 90日調達障害確率 + リスク要因
チョークポイント: 30日閉鎖確率 + 迂回コスト(百万円)
ルート詳細: 期待追加コスト + 推奨アクション

---

## 6. API (114本)

### 主要エンドポイント

| メソッド | パス | 処理 |
|---------|------|------|
| GET | /api/v1/tourism/three-scenarios | **29変数MCで3シナリオ同時計算** |
| GET | /api/v1/dashboard/global-risk | 49カ国リスク(timeseries.db) |
| GET | /api/v1/dashboard/chokepoints | 7CP動的リスク |
| GET | /api/v1/tourism/market-ranking | 市場ランキング(キャッシュ+フォールバック) |
| GET | /api/v1/tourism/historical | 月次実績(ISO2→ISO3変換) |
| POST | /api/v1/tourism/japan-forecast | GP/Dual-Scale予測 |
| POST | /api/v1/tourism/scenario-analysis | シナリオ分析 |
| GET | /api/v1/tourism/scenarios | シナリオ一覧 |

### /three-scenarios レスポンス構造

```json
{
  "data": {
    "model": "full_mc_29vars",
    "n_samples": 3000,
    "months": ["2026/04", ...],
    "scenarios": {
      "pessimistic": {"label":"悲観(p10)", "median":[2121242,...]},
      "base": {"label":"ベース(p50)", "median":[2427505,...], "p10":[...], "p90":[...]},
      "optimistic": {"label":"楽観(p90)", "median":[2779387,...]}
    },
    "by_country": {
      "KR": {"median":[716000,...], "p10":[...], "p90":[...]},
      "CN": {"median":[447849,...], ...}
    },
    "asymmetry_by_month": [1.15, 1.23, ...],
    "uncertainty_by_month": [26.9, 27.3, ...]
  }
}
```

---

## 7. バージョン履歴

| Ver | 日付 | 主要追加 |
|-----|------|---------|
| 0.3.0 | 03-15 | 22次元エンジン, 9ツール |
| 0.9.0 | 03-27 | 物レイヤー, 43ツール |
| 1.0.0 | 03-28 | 人レイヤー, 統合グラフ, 48ツール |
| 1.1.0 | 03-28 | デジタルツイン, 54ツール |
| 1.3.0 | 04-02 | 観光統計, 資金フロー第27次元, 61ツール |
| 1.4.0 | 04-03 | PPML, TFI, CIC, API駆動ダッシュボード, 63ツール |
| **1.5.0** | **04-04** | **29変数相関MC, GPカーネル, カレンダーイベント16種, データ収集パイプライン(979行月次), ダッシュボード完全再構築** |
