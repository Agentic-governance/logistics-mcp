# ROLE-E: 統合スコアリングとMCPツール — SCRI v1.3.0

完了日時: 2026-04-02

## E-1: InboundTourismRiskScorer

ファイル: `features/tourism/inbound_risk_scorer.py` (新規作成)

### クラス構成
- `InboundTourismRiskScorer` — メインクラス
  - `calculate_market_risk(source_country, horizon_months=6)` — 3カテゴリ統合リスク評価
  - `forecast_visitor_volume(source_country, horizon_months=6, scenario={})` — 重力モデル×リスク調整予測
  - `scan_all_markets(top_n=20)` — 主要20市場一括評価
  - `decompose_visitor_change(source_country, period_months=12)` — 変動要因分解

### リスク構成
| カテゴリ | 重み | 内訳 |
|---------|------|------|
| A) 需要側リスク | 50% | 為替25% + 経済15% + 政治10% |
| B) 供給側リスク | 30% | 二国間関係15% + フライト10% + ビザ5% |
| C) 日本側リスク | 20% | 災害10% + 台風5% + 競合5% |

### 依存モジュール (全てtry/except)
- `scoring.engine.calculate_risk_score` — 為替・経済・政治・災害スコア取得
- `features.tourism.gravity_model.TourismGravityModel` (ROLE-B)
- `pipeline.tourism.flight_supply_client.FlightSupplyClient` (ROLE-C)
- `features.tourism.regional_distribution.RegionalDistributionModel` (ROLE-D)
- `pipeline.tourism.competitor_stats_client.CompetitorStatsClient` (ROLE-A)
- `pipeline.tourism.jnto_client.JNTOClient` (ROLE-A)

未実装モジュールはデフォルト値(50)でフォールバック。

### バリデーション
- `horizon_months`: 1-36 (ValueError)
- `top_n`: 1-50 (ValueError)
- `period_months`: 1-36 (ValueError)

## E-2: MCPツール6本追加

ファイル: `mcp_server/server.py` (末尾に追加)

| # | ツール名 | 説明 |
|---|---------|------|
| 1 | `assess_inbound_tourism_risk` | 市場リスク評価（需要/供給/日本側） |
| 2 | `get_inbound_market_ranking` | 主要20市場リスクランキング |
| 3 | `forecast_visitor_volume` | 訪問者数予測（重力モデル×リスク調整） |
| 4 | `analyze_competitor_performance` | 競合デスティネーション分析 |
| 5 | `predict_regional_distribution` | 都道府県別地域分布予測 |
| 6 | `decompose_visitor_change` | 訪問者数変動の要因分解 |

MCPツール総数: 54 → 60

全ツールで:
- 入力バリデーション実施
- 未実装モジュール時はサンプルデータ返却
- `safe_error_response()` 使用（str(e)未使用）
- `logger.error()` で詳細ログ記録

## E-3: APIエンドポイント6本追加

ファイル: `api/routes/tourism.py` (新規作成)

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/v1/tourism/market-risk/{source_country}` | 市場リスク評価 |
| GET | `/api/v1/tourism/market-ranking` | 市場ランキング |
| POST | `/api/v1/tourism/forecast` | 訪問者数予測 |
| GET | `/api/v1/tourism/competitor-analysis` | 競合分析 |
| POST | `/api/v1/tourism/regional-distribution` | 地域分布予測 |
| POST | `/api/v1/tourism/decompose` | 変動要因分解 |

ルーター登録: `api/main.py` に `tourism_router` を追加（try/except付き）

Pydanticモデル:
- `ForecastRequest` (source_country, horizon_months, scenario)
- `RegionalDistributionRequest` (total_visitors, source_country, season)
- `DecomposeRequest` (source_country, period_months)

## 変更ファイル一覧
| ファイル | 操作 |
|---------|------|
| `features/tourism/inbound_risk_scorer.py` | 新規 (~400行) |
| `features/tourism/__init__.py` | 更新 (InboundTourismRiskScorer追加) |
| `mcp_server/server.py` | 追加 (6ツール, ~250行) |
| `api/routes/tourism.py` | 新規 (~210行) |
| `api/main.py` | 更新 (tourism_router登録) |

## テスト結果
- InboundTourismRiskScorer: インポートOK、calculate_market_risk/forecast実行OK
- MCP: 60ツール登録確認（6ツール追加）
- API: 6ルート登録確認
- 外部API依存: スコアリングエンジン経由で各種APIを呼び出し（タイムアウト時フォールバック）
