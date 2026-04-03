# SCRI v1.5.0 — 3シナリオ同時表示 完全実装レポート

**日時**: 2026-04-04
**バージョン**: v1.5.0 (Three Scenarios Update)

## 変更概要

旧9シナリオドロップダウンを廃止し、base/optimistic/pessimistic の3シナリオを常時同時表示する設計に全面刷新。

## TASK 1: scenario_engine.py 完全上書き

- `SCENARIOS` / `calculate_country_impacts` / `calculate_japan_total_impact` を全削除
- 新 `THREE_SCENARIOS` 定義 (base/optimistic/pessimistic)
- 新 `ScenarioEngine` クラス (2メソッドのみ):
  - `calculate_all_three(base_visitors)` — 3シナリオ同時計算
  - `apply_to_forecast(monthly_baseline, country)` — 月別乗数適用

### 弾性値・ドライバー
| パラメータ | 値 |
|---|---|
| FX_ELASTICITY | 国別 (KR=0.45, CN=0.70, US=0.30 等) |
| GDP_ELASTICITY | 1.24 |
| FLIGHT_ELASTICITY | 0.60 |
| POLITICAL_COEF | 0.008 (1pt = 0.8% demand change) |

### 楽観シナリオ
- 円安13.5%, 中国GDP+1.5%, フライト+10~18%, 日中関係+5pt

### 悲観シナリオ
- 円高7.5%, 中国GDP-2.5%, 米国GDP-1.5%, 日中関係-30pt, 台湾-15pt, フライト-5~15%

## TASK 2: API追加

`GET /api/v1/tourism/three-scenarios?source_country=ALL&prefecture=JAPAN`

レスポンス:
- `months`: 21ヶ月 (2026/04 ~ 2027/12)
- `scenarios.{base,optimistic,pessimistic}`: label, color, median[], p10[], p90[], total_change_pct
- `country_impacts.{CC}.{base,optimistic,pessimistic}`: change_pct, direction, breakdown

既存 `/scenarios` と `/scenario-analysis` は後方互換で残存。

## TASK 3: ダッシュボード inbound.html

### 削除
- 9シナリオドロップダウン (`<select id="scenarioSelect">`)
- `onScenarioSelect()`, `updateScenarioDisplay()`, `updateForecastForScenario()`
- 旧 `SCENARIO_FALLBACK` (9シナリオ分)
- forecast_base/forecast_optimistic/forecast_pessimistic (MONTHLY_DATA内)

### 追加
- 3シナリオカード常時表示 (`.scenario-cards` grid)
- カードクリック = `onCardClick()` → 太さ変更のみ (線は消えない)
- `loadThreeScenarios()` → API 1回呼び出し
- `renderThreeScenarioChart()` — 3本の線を常時表示
- `renderScenarioSummaryCards()` — カード数値更新
- `renderCountryImpactTable()` — 3列横並び (悲観/ベース/楽観)
- フォールバック: `SCENARIO_FALLBACK` (BASE_MONTHLYから自動生成)

### チャートデータセット
| 線 | 色 | 太さ | スタイル |
|---|---|---|---|
| ベース | #4a9eff | 2.5px (選択時) / 1.5px | 実線 |
| 楽観 | #51cf66 | 2.5px (選択時) / 1.5px | 破線 [8,4] |
| 悲観 | #ff4d4d | 2.5px (選択時) / 1.5px | 破線 [4,4] |
| 信頼区間 | rgba(74,158,255,0.15) | - | 帯 (p10-p90) |

`docs/inbound.html` にもコピー済み。

## TASK 4: 検証結果

### 3シナリオ同時計算
| シナリオ | 全体変化率 |
|---|---|
| base | +0.0% |
| optimistic | +15.3% |
| pessimistic | -15.9% |

### CN悲観 < KR悲観（政治リスク検証）
- CN悲観: -41.4% (為替-5.3% + GDP-3.1% + フライト-9.0% + 政治-24.0%)
- KR悲観: -6.4% (為替-3.4% + フライト-3.0%)
- **PASS**: 政治リスク(-30pt)が正しくCNに反映

### API検証
- `GET /api/v1/tourism/three-scenarios` → 200 OK
- 21ヶ月分の median/p10/p90 × 3シナリオ
- 12カ国分の country_impacts × 3シナリオ

### 後方互換
- `GET /api/v1/tourism/scenarios` → 200 OK (9シナリオ一覧)
