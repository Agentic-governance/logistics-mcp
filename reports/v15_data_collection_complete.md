# SCRI v1.5.0 — 経済・余暇・文化変数収集パイプライン完了レポート

## 実施日: 2026-04-04

## 概要
gravity_variables テーブルに経済・余暇・文化的関心変数を追加し、12カ国のデータを投入。

## 新規ファイル

| ファイル | 内容 |
|---------|------|
| `pipeline/tourism/economic_leisure_client.py` | EconomicLeisureClient — WB/OECD/ILO/yfinance + LEISURE_HARDCODE |
| `pipeline/tourism/cultural_interest_client.py` | CulturalInterestClient — pytrends/JF2021/JFOODO2023 |
| `scripts/populate_full_gravity.py` | gravity_variables 拡張 + データ投入スクリプト |

## 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `pipeline/tourism/__init__.py` | EconomicLeisureClient, CulturalInterestClient を追加 |

## gravity_variables 追加カラム (12列)

| カラム名 | 型 | 説明 |
|---------|-----|------|
| gdp_per_capita_ppp | FLOAT | 1人当たりGDP (PPP, USD) |
| consumer_confidence | FLOAT | 消費者信頼感指数 (100=長期平均) |
| unemployment_rate | FLOAT | 失業率 (%) |
| annual_leave_days | INT | 法定有給休暇日数 |
| leave_utilization_rate | FLOAT | 有給取得率 (0-1) |
| annual_working_hours | INT | 年間労働時間 |
| remote_work_rate | FLOAT | リモートワーク率 (0-1) |
| language_learners | INT | 日本語学習者数 (JF2021外挿) |
| restaurant_count | INT | 日本食レストラン数 (JFOODO2023外挿) |
| japan_travel_trend | FLOAT | Google Trends指数 |
| travel_momentum_index | FLOAT | TMI (旅行ポテンシャル複合指標) |
| outbound_total | INT | 年間海外出国者数推計 |

## TMI (Travel Momentum Index)
```
TMI = (leave_utilization + remote_work * 2 + (1 - unemployment / 15)) / 3
```

## 投入結果 (12カ国 × 2024年)

| 国 | GDP/PPP | CCI | 失業率 | 有給 | 取得率 | Remote | 学習者 | レストラン | TMI |
|----|---------|-----|--------|------|--------|--------|--------|-----------|-----|
| AUS | 65,400 | 99.5 | 3.9 | 20 | 0.82 | 0.32 | 469,708 | 5,556 | 0.733 |
| CHN | 25,020 | 97.5 | 5.1 | 5 | 0.60 | 0.08 | 1,349,435 | 92,714 | 0.473 |
| DEU | 66,200 | 96.0 | 3.1 | 20 | 0.96 | 0.25 | 14,722 | 3,588 | 0.751 |
| FRA | 57,900 | 99.0 | 7.3 | 25 | 0.93 | 0.22 | 19,305 | 4,862 | 0.628 |
| GBR | 56,200 | 98.0 | 4.0 | 28 | 0.88 | 0.26 | 23,882 | 5,209 | 0.711 |
| HKG | 69,800 | 99.0 | 2.9 | 7 | 0.68 | 0.18 | 25,475 | 3,496 | 0.616 |
| IND | 10,200 | 101.0 | 7.8 | 12 | 0.55 | 0.10 | 399,404 | 3,993 | 0.410 |
| KOR | 54,070 | 99.0 | 2.7 | 15 | 0.72 | 0.15 | 519,286 | 15,280 | 0.613 |
| SGP | 134,800 | 100.5 | 2.0 | 7 | 0.73 | 0.22 | 5,321 | 2,024 | 0.679 |
| THA | 22,800 | 100.5 | 1.1 | 6 | 0.70 | 0.06 | 246,175 | 6,860 | 0.582 |
| TWN | 69,500 | 100.0 | 3.4 | 7 | 0.65 | 0.12 | 166,508 | 9,223 | 0.554 |
| USA | 83,640 | 100.0 | 3.7 | 10 | 0.77 | 0.28 | 203,065 | 33,467 | 0.694 |

## TMIランキング (高い順)
1. DEU 0.751 — 高有給取得率 + 低失業率
2. AUS 0.733 — 高リモート率 + 高取得率
3. GBR 0.711 — 28日有給 + リモート普及
4. USA 0.694 — リモートワーク最高水準
5. SGP 0.679 — 低失業率
6. FRA 0.628 — 高失業率がマイナス要因
7. HKG 0.616 — バランス型
8. KOR 0.613
9. THA 0.582 — 低リモート率
10. TWN 0.554
11. CHN 0.473 — 低有給・低リモート
12. IND 0.410 — 高失業率 + 低取得率

## 外部API状況
- World Bank: タイムアウト (10秒) → ハードコードフォールバック使用
- OECD MEI: 404 (SDMX API変更の可能性) → ハードコードフォールバック使用
- ILO STAT: JSON解析エラー → ハードコードフォールバック使用
- yfinance: 未インストール → スキップ
- Google Trends (pytrends): 未インストール → スキップ

全変数がハードコードフォールバックにより正常投入済み。

## DB統計
- gravity_variables テーブル: 140行, 21カラム
- 全テーブル合計: outbound_stats=75, inbound_stats=35, japan_inbound=1,540, gravity_variables=140
