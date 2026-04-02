# Role C+D Complete — SCRI v1.4.0

## 完了タスク

### C-1: ランディングページ
- [x] `dashboard/index.html` → `dashboard/legacy.html` にリネーム
- [x] 新 `dashboard/index.html` 作成（3カード: Logistics / Inbound / Legacy）

### C-2: FastAPI ルーティング
- [x] `/dashboards` StaticFiles マウント追加（html=True）
- [x] 既存 `/dashboard` エンドポイントは維持

### C-3: assets ディレクトリ
- [x] `dashboard/assets/` 作成済み

### D-1: CHANGELOG
- [x] v1.4.0 エントリを CHANGELOG.md 先頭に追加

### D-2: VERSION更新
- [x] `config/constants.py`: VERSION = "1.4.0"

### D-3: テスト
- [x] pytest 実行（バックグラウンド）

### D-4: サマリー
- [x] `reports/v14_OVERNIGHT_SUMMARY.md` 生成
- [x] デスクトップにコピー

## 統計
- MCPツール: 61
- APIルート: 109
- ダッシュボード: 3 (Logistics / Inbound / Legacy) + Landing Page
