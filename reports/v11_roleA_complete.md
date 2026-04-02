# ROLE-A 完了報告: 内部データ取込エンジン (SCRI v1.1.0)

**完了日時**: 2026-03-28

## 成果物

### A-1: 汎用CSVインポーター
- `pipeline/internal/logistics_importer.py`
  - 6種類のデータスキーマ (inventory, purchase_orders, production_plan, locations, transport_routes, procurement_costs)
  - 日本語/英語/SAP列名のエイリアス自動解決
  - CSV/Excel/JSON 自動判定読み込み
  - UTF-8/Shift-JIS/CP932/EUC-JP エンコーディング自動検出 (BOM + try/except)
  - バリデーション: 必須列・NULL・負値・座標範囲・重複チェック

### A-2: 内部データストア
- `pipeline/internal/internal_data_store.py`
  - SQLite直接使用 (`data/internal_logistics.db`)
  - 6テーブル自動作成 (DDL埋め込み)
  - UPSERT対応 (inventory, locations, transport_routes, procurement_costs)
  - INSERT対応 (purchase_orders, production_plan — ID自動付番)
  - 参照API: `get_stock_days()`, `get_next_delivery()`, `get_total_lead_time()`

### A-3: サンプルデータ
- `scripts/generate_sample_internal_data.py`
- 生成ファイル:
  | ファイル | 行数 | 特徴 |
  |---------|------|------|
  | sample_inventory.csv | 177 | 50部品×複数拠点, 15%在庫薄 |
  | sample_purchase_orders.csv | 30 | 高リスク国(RU/MM)含む |
  | sample_production_plan.csv | 60 | 3製品×22稼働日 |
  | sample_locations.csv | 11 | 工場3+倉庫5+港湾3, 座標付き |
  | sample_transport_routes.csv | 20 | スエズ経由含む |
  | sample_procurement_costs.csv | 99 | 50部品×1-3仕入先 |

## テスト結果

| テスト | 結果 |
|--------|------|
| CSV読込・列名マッピング (6種) | OK |
| バリデーション (6種) | OK |
| DB格納 (6テーブル) | OK |
| get_stock_days('P0001','PLT-JP01') | 5.0 日 |
| get_next_delivery('P0001') | V006, 2026-05-02 |
| get_total_lead_time('PORT-SHANGHAI','PORT-TOKYO','sea') | 4 日 |

全テスト合格。
