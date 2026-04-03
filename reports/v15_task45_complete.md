# SCRI v1.5.0 — TASK 4-5 完了レポート

## 概要
GPモデル（ガウス過程）対応のAPI更新とダッシュボード更新を完了。

---

## TASK 4: API更新 (`api/routes/tourism.py`)

### 変更内容
1. **GPモジュール遅延インポート追加**
   - `MultiMarketGPAggregator` (features/tourism/gaussian_process_model.py)
   - `calendar_events` モジュール
   - 全てtry/exceptでフォールバック付き

2. **`JapanForecastRequest`にパラメータ追加**
   - `use_gp: bool = True` — GPモデル使用フラグ

3. **`/api/v1/tourism/japan-forecast` エンドポイント更新**
   - `use_gp=True` + GPモジュール利用可能時: `MultiMarketGPAggregator.predict_japan_total_gp()` を呼び出し
   - GP失敗時: 自動的に既存フォールバック（PPML+STL or モンテカルロ）へ切替
   - `use_gp=False`: 既存処理をそのまま実行

4. **レスポンスにGP固有フィールド追加**
   - `model`: `"GP"`, `"PPML+STL+Bayesian"`, `"fallback"` のいずれか
   - `uncertainty_by_month`: 月別不確実性指数（spread_ratio × calendar_uncertainty / 0.3で正規化）
   - `calendar_effects`: 月別カレンダー効果倍率（主要8市場の加重平均）+ イベント名リスト

5. **ヘルパー関数3本追加**
   - `_compute_calendar_effects()`: 月別の需要倍率と該当イベント一覧
   - `_compute_uncertainty_by_month()`: GP結果から不確実性���数を計算
   - `_compute_uncertainty_by_month_fallback()`: フォールバック結果から不確実性指数を計算

### GP依存モジュール（TASK 1-3）
- `features/tourism/gaussian_process_model.py` — 未作成（try/exceptでフォールバック）
- `features/tourism/calendar_events.py` — 存在、正常に読み込み可能

---

## TASK 5: ダッシュボード更新 (`dashboard/inbound.html`)

### 変更内容
1. **バージョン更新**: v1.4.0 → v1.5.0

2. **GP予測API呼び出し追加**
   - `loadGPForecast()`: POST `/api/v1/tourism/japan-forecast` with `use_gp: true`
   - 初回ロード時 + 30分間隔で自動更新
   - API失敗時は既存のフォールバックチャートをそのまま表示

3. **予測帯の非線形曲線化**
   - 全6データセット（現状維持/楽観/悲観/CI上限/CI下限）に `tension: 0.4` 追加

4. **不確実性マーカー（赤/黄）表示**
   - `pointRadius`: uncertainty > 2.0 → 6px, > 1.5 → 4px, それ以外 → 0
   - `pointBackgroundColor`: > 2.0 → #ff4d4d（赤）, > 1.5 → #ffd43b（黄）, それ以外 → #4a9eff
   - 現状維持ラインにのみ適用

5. **カレンダー効果注釈テキスト**
   - `calendarAnnotations` Chart.jsプラグイン追加
   - demand_multiplier > 1.3 または < 0.7 の月にイベント名+変動率を表示
   - 増加（>1.3）: 緑色テキスト、減少（<0.7）: 赤色テキスト

6. **不確実性凡例追加**（セクション2下部）
   - 赤点 = 不確実性が特に高い月（台風・春節など）
   - 黄点 = 不確実性がやや高い月
   - Model: GP / FALLBACK バッジ表示
   - GPデータ存在時のみ表示

7. **セクション2説明文の動的更新**
   - GP利用時: 「ガウス過程(GP)モデルによる確率的予測」
   - フォールバック時: 既存の説明文を維持

---

## 構文チェック結果
- `api/routes/tourism.py`: Python py_compile — OK
- `dashboard/inbound.html`: HTML構造 + JS括弧バランス — OK
  - `{}`: 306/306, `()`: 626/626, `[]`: 163/163

---

## フォールバック動作確認
- GPモジュール未作成 → `_gp_aggregator = None` → 自動フォール���ック
- calendar_events モジュール存在 → `_calendar_events_module` 正常読み込み
- ダッシュボード: API失敗 → `gpForecastData = null` → 既存チャート維持
