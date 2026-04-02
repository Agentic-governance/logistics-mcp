# SCRI v1.4.0 TASK 4-5 完了レポート

## 完了日時
2026-04-03

## TASK 4: APIエンドポイント + MCPツール

### 新規APIエンドポイント (api/routes/tourism.py)

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/v1/tourism/japan-forecast` | POST | 日本全国インバウンド確率分布予測 |
| `/api/v1/tourism/prefecture-forecast` | POST | 都道府県別予測（国別シェア×ローカルリスク） |
| `/api/v1/tourism/decompose-forecast` | POST | 変数別要因分解（重力モデル各変数の寄与度） |

#### japan-forecast レスポンス形式
```json
{
  "months": ["2025/01", ...],
  "median": [...],
  "p10": [...], "p25": [...], "p75": [...], "p90": [...],
  "by_country": {"CN": {...}, "KR": {...}, ...},
  "model_info": {"method": "PPML+STL+Bayesian", "n_samples": 1000}
}
```

### 新規MCPツール (mcp_server/server.py)

| ツール | 説明 |
|---|---|
| `forecast_japan_inbound` | 日本全国インバウンド確率分布予測（PPML+STL+ベイズ） |
| `forecast_prefecture_inbound` | 都道府県別予測（国別シェア×ローカルリスク） |

両ツールともTASK1-3モジュール（TourismGravityModel, SeasonalExtractor, InboundAggregator）を
try/exceptで遅延インポート。未実装時はモンテカルロフォールバックで動作。

### TASK1-3モジュール依存
- `features/tourism/gravity_model.py` → TourismGravityModel
- `features/tourism/seasonal_extractor.py` → SeasonalExtractor
- `features/tourism/inbound_aggregator.py` → InboundAggregator
- 全てtry/exceptで囲み、未完成時は静的データ+モンテカルロサンプリングでフォールバック

## TASK 5: ダッシュボード改修 (dashboard/inbound.html)

### 変更点

1. **予測の表現を「シナリオ」から「確率分布」に変更**
   - p90-p10帯: 薄い青（rgba(66,133,244,0.10)）— 全体的な不確実性
   - p75-p25帯: やや濃い青（rgba(66,133,244,0.25)）— 中心的な予測範囲
   - 中央値: 実線（#4285f4, width 2.5）

2. **シナリオボタンの意味変更**
   - [現状維持] [円安10%] [円高10%] [日中悪化]
   - 各ボタンはショックを与えた別の確率分布を表示
   - ボタン切替で分布全体がシフト（_calcShockMultiplier関数）

3. **API連携**
   - loadForecast() でバックグラウンドAPIリクエスト
   - `/api/v1/tourism/japan-forecast` にPOST
   - レスポンスをapiForecastDataに格納しチャート更新
   - API不可時は静的MONTHLY_DATAからフォールバック

4. **右パネルの説明追加**
   - 「この予測は1000回のシミュレーションから生成された確率分布です。帯の中心から外れるほど発生確率が低くなります。」

## 構文チェック結果
- api/routes/tourism.py: OK
- mcp_server/server.py: OK
- dashboard/inbound.html: div/braces balanced, OK

## 変更ファイル
- `/Users/reikumaki/supply-chain-risk/api/routes/tourism.py`
- `/Users/reikumaki/supply-chain-risk/mcp_server/server.py`
- `/Users/reikumaki/supply-chain-risk/dashboard/inbound.html`
