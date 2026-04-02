# ROLE-D 完了報告: 統合API・MCPツール — SCRI v1.1.0

## 完了日時
2026-03-28

## D-1: 内部データ取込API
**ファイル:** `api/routes/internal.py` (新規)

### エンドポイント (8本)
| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/v1/internal/upload/inventory` | 在庫データCSV/Excelアップロード |
| POST | `/api/v1/internal/upload/purchase-orders` | 発注データアップロード |
| POST | `/api/v1/internal/upload/production-plan` | 生産計画アップロード |
| POST | `/api/v1/internal/upload/locations` | 拠点マスタアップロード |
| POST | `/api/v1/internal/upload/transport-routes` | 輸送ルートアップロード |
| POST | `/api/v1/internal/upload/costs` | 調達コストアップロード |
| GET | `/api/v1/internal/data-status` | 各データの最終更新日・件数・品質スコア |
| DELETE | `/api/v1/internal/reset` | 内部データ全削除 |

### 実装詳細
- ROLE-A の `LogisticsImporter` を利用（CSV/Excel/JSON自動判定、列名揺れ吸収）
- `InternalDataStore` が未実装の場合、インメモリフォールバックで動作
- `UploadFile` (multipart/form-data) によるファイルアップロード
- 一時ファイル経由で処理（処理後自動削除）

## D-2: デジタルツイン分析API
**ファイル:** `api/routes/twin.py` (新規)

### エンドポイント (6本)
| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/v1/twin/stockout-scan` | 在庫枯渇リスク全部品スキャン |
| POST | `/api/v1/twin/production-cascade` | 生産カスケードシミュレーション |
| POST | `/api/v1/twin/emergency-procurement` | 緊急調達最適計画 |
| GET | `/api/v1/twin/facility-risks` | 全拠点リスクヒートマップ |
| POST | `/api/v1/twin/transport-analysis` | 輸送ルートリスク分析 |
| POST | `/api/v1/twin/scenario` | What-Ifシナリオシミュレーション |

### 実装詳細
- ROLE-B/C モジュールを try/except で安全にインポート
- 未実装モジュールは `_not_implemented_response()` で統一メッセージ返却
- シナリオシミュレーションは全モジュールを横断的に呼び出し
- Pydantic モデルによる入力バリデーション

## D-3: MCPツール6本追加
**ファイル:** `mcp_server/server.py` (追記)

### 追加ツール
| # | ツール名 | 説明 |
|---|---------|------|
| 1 | `scan_stockout_risks` | 在庫枯渇リスク全部品スキャン |
| 2 | `simulate_production_impact` | 部品欠品の生産カスケードシミュレーション |
| 3 | `get_emergency_procurement_plan` | 緊急調達最適計画 |
| 4 | `analyze_transport_risks` | 輸送ルートリスク分析 |
| 5 | `get_facility_risk_map` | 全拠点リスクヒートマップ |
| 6 | `run_scenario_simulation` | What-Ifシナリオシミュレーション |

### 実装詳細
- 既存MCP 48ツール → 54ツール
- 各ツールは対応するROLE-B/Cクラスを呼び出し
- 未実装の場合は「実装中」メッセージで graceful degradation
- `run_scenario_simulation` の `affected_countries` はカンマ区切り文字列（MCP制約対応）

## ルーター登録
**ファイル:** `api/main.py` (更新)
- `internal_router` と `twin_router` を既存パターンに合わせて登録

## ROLE依存状況
| 依存先 | モジュール | 状態 |
|--------|----------|------|
| ROLE-A | `LogisticsImporter` | 利用可能 |
| ROLE-A | `InternalDataStore` | 未作成（インメモリフォールバック有効） |
| ROLE-B | `StockoutPredictor` | 未作成（graceful degradation） |
| ROLE-B | `ProductionCascade` | 未作成（graceful degradation） |
| ROLE-B | `EmergencyProcurement` | 未作成（graceful degradation） |
| ROLE-B | `FacilityRiskMapper` | 未作成（graceful degradation） |
| ROLE-C | `TransportRisk` | 未作成（graceful degradation） |

## 構文チェック
全4ファイル py_compile 通過済み。
