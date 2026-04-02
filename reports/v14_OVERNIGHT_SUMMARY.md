# SCRI v1.4.0 Overnight Summary

## バージョン比較

| 項目 | v1.3.0 | v1.4.0 |
|---|---|---|
| MCPツール | 61 | 61 |
| APIルート | 105 | 109 |
| ダッシュボード | legacy(10タブ) | **3ダッシュボード** (Logistics/Inbound/Legacy) |
| VERSION | 1.3.0 | 1.4.0 |

## 新規ダッシュボード

### Logistics Risk Dashboard (`dashboard/logistics.html`)
- D3.js + TopoJSON 世界地図
- 国リスク塗り分け（40カ国データ）
- 海路5本 / 空路5本 / チョークポイント7箇所（脈動アニメーション）
- 次元切替、詳細パネル

### Inbound Tourism Risk Dashboard (`dashboard/inbound.html`)
- 世界地図（12市場リスク）+ 日本地図（47都道府県 TopoJSON）
- 市場ランキング
- 都道府県別来訪者予測

### Landing Page (`dashboard/index.html`)
- 3ダッシュボードへのカード型リンク
- ダークテーマ、ホバーエフェクト

## API変更
- `/dashboards` StaticFiles マウント追加（html=True）
- `/dashboard` は引き続きランディングページを返す

## ファイル構成
```
dashboard/
  index.html        # ランディングページ (NEW)
  logistics.html    # 物流リスク (NEW)
  inbound.html      # インバウンド観光リスク (NEW)
  legacy.html       # 旧ダッシュボード (RENAMED from index.html)
  assets/           # ローカルアセット用 (NEW, CDN利用のため空)
```
