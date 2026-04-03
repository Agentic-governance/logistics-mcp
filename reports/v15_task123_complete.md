# SCRI v1.5.0 — TASK 1-3 完了レポート

## 実装サマリ

### TASK 1: カレンダーイベント (`features/tourism/calendar_events.py`)
- `CalendarEvent` dataclass + `CALENDAR_EVENTS` リスト (16イベント)
- 春節, 国慶節, 労働節, 秋夕, ソルラル, 韓国夏休み, 台湾春節, 台湾国慶日,
  Thanksgiving, 米国夏休み, クリスマス, 豪州スキー, 豪州夏休み, 桜, 紅葉, 台風
- 3関数: `get_events_for_country_month`, `get_demand_multiplier`, `get_uncertainty_multiplier`

### TASK 2: GPモデル (`features/tourism/gaussian_process_model.py`)
- `GPYTORCH_AVAILABLE` フラグで動的切替
- gpytorch版: `TourismGPKernel` (seasonal×trend + risk + noise), `TourismGPModel` (ExactGP)
- `GaussianProcessInboundModel`: fit/predict、numpyフォールバック (`_calendar_only_fallback`)
- BASE_MONTHLY: KR=716K, CN=583K, TW=430K, US=272K, AU=53K, TH=35K, HK=109K, SG=45K

### TASK 3: 複数市場集計 (同ファイル内)
- `MultiMarketGPAggregator`: correlation_matrix (14ペア), predict_japan_total_gp
- シナリオ: base / optimistic (×1.112, flight +9%) / pessimistic (÷1.112, CN -23.5%)
- 共通ショック: 5%の共通変動、相関ペアへの共有ノイズ注入

### __init__.py 更新
- v1.4.0 → v1.5.0、新モジュール9シンボルをエクスポート

## テスト結果
```
14 passed, 2 warnings in 1.74s
```
- TestCalendarEvents: 6テスト (春節CN低, 国慶節CN高, 台風不確実性, 秋夕KR低, ニュートラル, 桜全市場)
- TestGPModel: 5テスト (分布返却, 月別不確実性変動, カレンダー効果, リスク調整, モデルタイプ)
- TestMultiMarketAggregator: 3テスト (base合計, optimistic>base, pessimistic<base)

## gpytorch状態
- torch/gpytorch: インストール済み・利用可能 (warningはtorch.jit deprecation のみ)
