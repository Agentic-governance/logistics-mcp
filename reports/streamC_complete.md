# STREAM C: データパイプライン強化 完了レポート

## 概要
5つのデータパイプラインクライアントを確認・補完・強化した。
既存の基本機能に加え、分析系メソッド・フォールバック・バッチ処理等を追加。

---

## C-1: 欧州通関データ (`pipeline/trade/eu_customs_client.py`)

### 既存機能（確認済み）
- `get_bilateral_flow()` - 二国間貿易フロー取得（Eurostat SDMX REST API）
- `get_top_importers()` - 上位輸入元国の取得
- `get_trade_balance()` - 貿易収支の算出
- SDMX-JSON / JSON-stat 両形式のパーサー

### 追加機能
- **`get_time_series()`** - 月次時系列取得（期間指定可、同一期間の輸出入統合）
- **`get_yoy_change()`** - 前年同月比変動率算出（輸入/輸出別、急変アラートフラグ）
- `get_eu_trade_yoy()` - YoY便利関数

---

## C-2: 日本税関データ (`pipeline/trade/japan_customs_client.py`)

### 既存機能（確認済み）
- `get_import_by_hs()` - HS別輸入データ取得（e-Stat API）
- `get_export_by_hs()` - HS別輸出データ取得
- `get_top_import_sources()` - 上位輸入元国
- 日本語国名→ISO3コード変換（50+国対応）

### 追加機能
- **`get_bilateral_flow()`** - 特定相手国との二国間貿易フロー（輸出入統合、貿易収支算出）
- **`get_yoy_change()`** - 前年同月比変動率（国別変動上位10ヶ国付き）
- **`get_customs_scrape_fallback()`** - 税関公式CSV直接取得フォールバック（APIキー不要時）
- `get_japan_bilateral()` - 二国間フロー便利関数

---

## C-3: OpenSanctions 企業グラフ (`pipeline/sanctions/opensanctions_graph.py`)

### 既存機能（確認済み）
- `get_related_entities()` - N-hopグラフ探索
- `get_ownership_structure()` - 所有構造（株主ツリー）
- `check_sanctions_network()` - 制裁ネットワークチェック（2-hop、リスクスコア0-100）
- エンティティ情報抽出（schema/topic分類）

### 追加機能
- **`get_ultimate_beneficial_owner()`** - 最終実質的支配者（UBO）特定（所有チェーン再帰探索、PEP/制裁フラグ）
- **`batch_check_entities()`** - 複数エンティティ一括制裁チェック（サプライチェーン全取引先向け）
- **`get_risk_propagation_score()`** - リスク伝播スコア算出（距離減衰+関係種別重み付けモデル）
- `batch_sanctions_check()` - バッチチェック便利関数

---

## C-4: GDELT 企業センチメント (`pipeline/gdelt/company_sentiment.py`)

### 既存機能（確認済み）
- `get_sentiment_timeline()` - センチメント時系列（timelinetone API）
- `detect_negative_events()` - ネガティブイベント検出（トーン<-5、5カテゴリ分類）
- `get_company_risk_from_news()` - 総合リスクスコア算出（0-100）

### 追加機能
- **`get_volume_weighted_sentiment()`** - 記事量重み付けセンチメント（ボラティリティ、トレンド方向判定）
- **`detect_sentiment_spike()`** - センチメント急変（スパイク）検出（N-σ閾値方式）
- **`get_multilingual_sentiment()`** - 多言語クエリ統合（英語名+日本語名等、URL重複排除）
- `get_company_sentiment_spikes()` - スパイク検出便利関数

---

## C-5: 港湾リアルタイムデータ (`pipeline/maritime/port_realtime_client.py`)

### 既存機能（確認済み）
- `get_port_congestion_live()` - リアルタイム混雑状況（AISHub → PortWatch → フォールバック）
- `get_all_ports_status()` - 全7港一括取得
- AISHub API / IMF PortWatch ArcGIS 統合

### 追加機能
- **`_fetch_vesselfinder_congestion()`** - VesselFinderスクレイピング（3番目のデータソースとして追加）
- `get_port_congestion_live()` を **4段フォールバック** に拡張（AIS → PortWatch → VesselFinder → ベースライン）
- **`get_congestion_trend()`** - 混雑トレンド推定（前半vs後半比較、IMPROVING/WORSENING/STABLE）
- **`get_delay_forecast()`** - 短期遅延予測（24h/72h、線形外挿+曜日補正+平均回帰）
- **`get_global_congestion_summary()`** - グローバル混雑サマリー（地域別集計、全体リスクレベル）
- `get_global_port_summary()` - サマリー便利関数

---

## 技術詳細

| ファイル | 既存メソッド | 追加メソッド | 追加LOC（概算） |
|----------|------------|------------|---------------|
| eu_customs_client.py | 3 | 2 (+1便利関数) | ~160 |
| japan_customs_client.py | 3 | 3 (+1便利関数) | ~210 |
| opensanctions_graph.py | 3 | 3 (+1便利関数) | ~210 |
| company_sentiment.py | 3 | 3 (+1便利関数) | ~240 |
| port_realtime_client.py | 2 | 4 (+1便利関数) | ~350 |
| **合計** | **14** | **15** | **~1,170** |

## パターン準拠
- 全メソッド: try/except で例外を記録して空結果返却（クラッシュしない）
- レート制限: 全APIリクエストに2秒間隔を適用
- コメント: 日本語
- 型ヒント: `from __future__ import annotations` + dataclass
- Python 3.11 (.venv311) 互換確認済み
