# STREAM E: API・インフラ完成 — SCRI v0.9.0

## 完了日: 2026-03-27

---

## E-1: GraphQL API

**ファイル**: `api/graphql_schema.py`

- 既存スキーマ確認・補完完了
- `searchPath(origin, destination, maxHops)` クエリを追加
  - RouteRiskAnalyzer を呼び出し、チョークポイント経由パスを返す
- 既存クエリ: `company`, `searchSanctions`, `riskDashboard`, `riskDetail`, `personCheck`
- `api/main.py` に `/graphql` エンドポイントとして統合済み（既存）

## E-2: WebSocket リアルタイムアラート

**ファイル**: `api/websocket_alerts.py`

- 既存実装確認完了 -- 全機能実装済み
- AlertBroadcaster: 接続管理、サブスクリプションフィルタ（国/スコア/ディメンション）
- クライアントメッセージ: subscribe, ping, status
- `api/main.py` に `ws://localhost:8000/ws/alerts` として統合済み（既存）

## E-3: CLI ツール

**ファイル**: `cli/scri_cli.py`

- 既存実装確認完了 -- 全コマンド実装済み
- コマンド: `risk`, `screen`, `bom`, `route`, `alerts`, `dashboard`
- rich ライブラリによるカラフル出力、テーブル表示

## E-4: Dockerfile + docker-compose

**ファイル**: `Dockerfile`, `docker-compose.yml`

- redis サービス追加: `redis:7-alpine` (port 6379)
  - ヘルスチェック付き、永続ボリューム (`redis_data`)
- 全サービスに `REDIS_URL` 環境変数追加
- api サービスの `depends_on` に redis 追加
- 4サービス構成: api, redis, mcp, scheduler

## E-5: テストカバレッジ向上

**テスト総数: 170テスト** (目標60以上を大幅超過)

### 新規テストファイル (56テスト追加)

| ファイル | テスト数 | 内容 |
|---|---|---|
| `tests/test_person_graph.py` | 23 | UBO/役員/OpenSanctions グラフ操作、パス検索、リスクエクスポージャー |
| `tests/test_graphql.py` | 14 | GraphQL スキーマ構造、company/sanctions/personCheck/riskDetail/searchPath クエリ |
| `tests/test_websocket.py` | 19 | AlertBroadcaster 接続管理、サブスクリプションフィルタ、ブロードキャスト、メッセージハンドリング |

### 新規テスト全56件: PASS

### 既存テスト: 変更なし（既存の4件のFAILは事前から存在、今回の変更に起因しない）

- `test_scoring.py`: test_composite_formula, test_to_dict_structure (次元数変更に伴う既知の不一致)
- `test_diversification.py`: test_high/low_concentration_detection (concentration_level キー名の不一致)

---

## 成果サマリー

| 項目 | 状態 |
|---|---|
| GraphQL /graphql エンドポイント | 完成 (6クエリ) |
| WebSocket /ws/alerts | 完成 (フィルタ対応) |
| CLI (scri) | 完成 (6コマンド) |
| Docker 1コマンド起動 | 完成 (4サービス) |
| テストカバレッジ | 170テスト (目標の283%) |
