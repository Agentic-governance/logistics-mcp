# ROLE-A Complete: Logistics Risk Dashboard v1.4.0

## 作成日: 2026-04-02

## 成果物
- `dashboard/logistics.html` -- 新規作成（単一HTMLファイル、外部依存はCDNのみ）

## 実装内容

### 地図描画
- D3.js v7 + TopoJSON (world-atlas@2 CDN) によるNatural Earth投影の世界地図
- 国別リスク塗り分け（0-100のスムーズなカラースケール: 緑→黄→橙→赤）
- ズーム/パン対応（d3.zoom, scaleExtent 1-8）
- グラティキュール（経緯線）描画

### ルート描画
- **SEA_ROUTES**: 5本の主要海路（Asia-Europe Suez, Trans-Pacific, Asia-Africa Cape, ME-Asia Oil, Europe-Americas Atlantic）
- **AIR_ROUTES**: 5本の主要航空路（Tokyo-Frankfurt, Shanghai-LA, Singapore-London, Dubai-NYC, Tokyo-Singapore）
- CatmullRom曲線補間、リスク値に応じた色分け
- 海路: 実線+ダッシュアニメーション / 航空路: 破線

### チョークポイント
- 7箇所: Malacca, Suez, Hormuz, Bab el-Mandeb, Panama, Taiwan Strait, Cape of Good Hope
- 三角マーカー + 脈動アニメーション（CSS @keyframes pulse）
- ホバーでリスクスコア表示

### 左サイドバー
- KPIカード: CRITICAL数 / HIGH数 / 監視国数
- 次元切替セレクトボックス: overall/conflict/sanctions/maritime/disaster/political/trade/economic/cyber_risk/climate_risk
- 輸送モードトグル: All / Sea / Air
- チョークポイントリスト（リスク順ソート、クリックでズーム）
- リスク上位10カ国リスト（国旗絵文字付き）

### 詳細パネル（右下）
- 国クリックで表示、20次元バーチャート
- 全体スコア + リスクレベル表示
- 閉じるボタン + ズームリセット

### データ
- **RISK_DATA**: 40カ国分のハードコードデータ（22次元スコア）
- **iso3ToIso2**: 完全なISO3→ISO2マッピング（190+エントリ）
- ISO数値→ISO3マッピング（TopoJSON対応）

### API連携
- `loadRealData()` -- `/api/v1/dashboard/global` からデータ取得試行
- フォールバック: 静的データを使用、コンソールにログ出力
- タイムスタンプ表示（Live/Static切替）

### UI/UX
- ダークテーマ（#0f1117背景）
- ツールチップ（ホバー: 国名、スコア、主要次元バー）
- 凡例（左下: リスクグラデーション + ルート種別 + チョークポイント）
- レスポンシブ対応（ウィンドウリサイズ時に再描画）

## 既存ファイルへの影響
- `dashboard/index.html` -- 変更なし（既存の旧ダッシュボードはそのまま保持）

## 動作確認方法
```bash
# APIサーバー起動（オプション）
cd ~/supply-chain-risk
.venv311/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000

# ブラウザで開く
open dashboard/logistics.html
# または http://localhost:8000/dashboard/logistics.html（APIサーバー経由）
```
