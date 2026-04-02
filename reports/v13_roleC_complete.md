# SCRI v1.3.0 ROLE-C 完了レポート — 観光統計DBと自動更新パイプライン

## 実行日時
2026-04-02

## 成果物

### C-1: 観光統計専用データベース
- **ファイル**: `pipeline/tourism/tourism_db.py` (新規, ~260 LOC)
- **DB**: `data/tourism_stats.db` (SQLite)
- **テーブル**: 4テーブル
  - `outbound_stats` — アウトバウンド統計（送客元 x 年月）
  - `inbound_stats` — インバウンド統計（デスティネーション x 送客元 x 年月）
  - `japan_inbound` — 日本インバウンド詳細（目的構成・滞在・支出含む）
  - `gravity_variables` — 重力モデル変数（GDP・為替・フライト供給・ビザ・リスク）
- **TourismDBクラス**:
  - upsert: `upsert_outbound`, `upsert_inbound`, `upsert_japan_inbound`, `upsert_gravity_variables`
  - 検索: `get_outbound`, `get_japan_inbound`, `get_inbound`, `get_gravity_variables`
  - 統計: `get_table_counts`
- SQLAlchemy不使用、sqlite3直接操作
- UPSERT = `INSERT ... ON CONFLICT ... DO UPDATE`

### C-2: 初期データ取込スクリプト
- **ファイル**: `scripts/bootstrap_tourism_stats.py` (新規, ~280 LOC)
- **データ件数**:

| テーブル | 件数 | 内容 |
|---|---|---|
| japan_inbound | 100行 | 20市場 x 5年 (2021-2025) |
| outbound_stats | 75行 | 15市場 x 5年 |
| inbound_stats | 35行 | 6競合国+日本 x 5年 |
| gravity_variables | 75行 | 15市場 x 5年 |
| **合計** | **285行** | |

- データソース:
  - JNTO HISTORICAL_DATA (jnto_client.py) — 20市場の訪日者数
  - 各国アウトバウンドクライアント ANNUAL_DATA (country_outbound_clients.py)
  - 競合国 inbound_fallback (competitor_stats_client.py)
  - フライト供給 CAPACITY_INDEX (flight_supply_client.py)
  - GDP/為替はWorld Bank/ECBベースのハードコード推定値
- 外部API呼び出しなし（全データハードコード）

### C-3: スケジューラー設定
- **ファイル**: `features/timeseries/scheduler.py` (更新)
- 月次更新ジョブ4件をコメントとして記載:
  1. `tourism_jnto_update` — 毎月3日 06:00 JST: JNTO訪日統計
  2. `tourism_outbound_update` — 毎月5日 06:00 JST: アウトバウンド統計
  3. `tourism_competitor_update` — 毎月5日 07:00 JST: 競合デスティネーション
  4. `tourism_gravity_update` — 毎月5日 08:00 JST: 重力モデル変数
- 実際のスケジューラー登録は将来実装（コメント内に実装ガイド記載）

### その他
- `pipeline/tourism/__init__.py` — TourismDB をエクスポートに追加

## 検証結果
- `bootstrap_tourism_stats.py` を実行し、285行が正常に投入された
- サンプルクエリで japan_inbound / inbound_stats のデータ整合性を確認
- 2024年 日本インバウンド上位3市場: 韓国(881万人)、中国(696万人)、台湾(536万人)
- 2024年 競合国インバウンド: フランス(1.02億人)、スペイン(9000万人)、日本(3687万人)

## ステータス: 完了
