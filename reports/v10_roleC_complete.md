# ROLE-C: データ品質エンジニア 完了レポート

**SCRI v1.0.0 | 2026-03-28**

---

## C-1: ImportYeti 品質改善

**ファイル**: `pipeline/trade/importyeti_client.py`

### 実装内容

1. **COMPANY_ALIASES 辞書**: 30+社の通称・略称マッピングを追加
   - 逆引きインデックス `_ALIAS_TO_CANONICAL` でO(1)検索
   - 日本企業(Toyota, Sony, Panasonic等)、韓国企業(Samsung, SK Hynix等)、中国企業(Huawei, BYD, CATL等)を網羅

2. **企業名正規化強化**: `resolve_canonical_name()` 関数を追加
   - `company_names_match()` にエイリアス解決を統合
   - 例: "HON HAI PRECISION INDUSTRY" と "FOXCONN" が同一企業と判定される

3. **重複排除**: `deduplicate_shipments()` 関数を追加
   - 正規化キー(シッパー×コンサイニー×日付×HSコード)で完全一致排除
   - RapidFuzz ファジーマッチで表記揺れの重複も検出(閾値85%)
   - `get_shipments()` メソッドに自動適用

4. **品質スコア**: `quality_score(shipment)` 関数を追加
   - 6要素を重み付き評価(0.0〜1.0)
     - シッパー名(0.25): 長さ+エイリアス解決可能性
     - コンサイニー名(0.20): 有無+長さ
     - HSコード(0.20): 桁数で品質判定(6桁>4桁)
     - 日付(0.15): ISO8601準拠チェック
     - 国名(0.10): ISO3コードか否か
     - 重量(0.10): 正の値の有無

---

## C-2: HS_PROXY_DATA 自動更新スクリプト

**ファイル**: `scripts/update_hs_proxy.py` (新規)

### 機能
- UN Comtrade API (`comtradeapi.un.org/public/v1/preview/`) から輸入データ取得
- 13 HSコード × 10 輸入国 = 最大130クエリ
- パートナー国別シェアを自動計算(1%未満カット、上位10カ国)
- `data/hs_proxy_auto.json` に `tier_inference.py` の `HS_PROXY_DATA` 互換形式で保存
- レート制限(1.5秒/リクエスト)、タイムアウト、JSONパースエラー全てのフォールバック付き

---

## C-3: 制裁データ品質レポート

**ファイル**: `scripts/sanctions_quality_report.py` (新規)

### 機能
- 12ソース(OFAC/UN/EU/BIS/METI/OFSI/SECO/Canada/DFAT/MOFA Japan/OpenSanctions×2)を分析
- 各ソースの品質メトリクス:
  - アクティブ件数、最終取得日時
  - エンティティタイプ分布(individual/entity/vessel)
  - 国別分布(上位10)
  - エイリアス保有率
  - 名前品質スコア(全角混在/連続空白/短すぎ/長すぎ等をチェック)
  - 未正規化エンティティ率
  - RapidFuzz による重複検出(サンプル500件、閾値90%)
- コンソール表形式 + `data/sanctions_quality_report.json` に保存

---

## C-4: 時系列データ欠損補完

**ファイル**: `scripts/fill_all_dimensions.py` (新規)

### 機能
- 50カ国 × 25次元のリスクスコアを一括計算
- `scoring.engine.calculate_risk_score()` でライブ計算を試行
- 失敗/欠損次元は地域別デフォルトで補完:
  - 10地域区分(East Asia / Southeast Asia / South Asia / Middle East / Europe / North America / Latin America / Africa / Oceania / Conflict Zone)
  - 各次元の地域リスク傾向に基づく保守的推定値
- dimension_status で各次元の状態を追跡("ok" / "fallback" / "failed" / "not_applicable")
- overall_score を補完後の全次元スコアから再計算(60%加重平均 + 30%ピーク + 10%第2ピーク)
- `features/timeseries/store.py` の `RiskTimeSeriesStore` に保存
  - `risk_scores` テーブル(次元別)
  - `risk_summaries` テーブル(日次サマリー)
- `data/all_dimensions_scores.json` にサマリーJSON保存

---

## C-5: BACI代替データ構築

**ファイル**: `scripts/build_hs_proxy_from_comtrade.py` (新規)

### 機能
- BACIデータ(有償/アカデミック限定)の完全代替
- UN Comtrade パブリックAPIのみで構築
- 22 HSコード(原材料8 + 中間財6 + 完成品8) × 15製造国 = 最大330クエリ
- 複数年(2022-2023)の集計で安定したシェア計算
- `data/hs_proxy_baci_alt.json` にJSON出力
- `data/hs_proxy_snippet.py` に `tier_inference.py` 貼り付け用Pythonコード生成
- 既存 `hs_proxy_auto.json` との自動マージ機能

---

## 変更ファイル一覧

| ファイル | 種別 | 行数(概算) |
|---------|------|-----------|
| `pipeline/trade/importyeti_client.py` | 変更 | +200行 |
| `scripts/update_hs_proxy.py` | 新規 | ~210行 |
| `scripts/sanctions_quality_report.py` | 新規 | ~280行 |
| `scripts/fill_all_dimensions.py` | 新規 | ~330行 |
| `scripts/build_hs_proxy_from_comtrade.py` | 新規 | ~340行 |
| `reports/v10_roleC_complete.md` | 新規 | このファイル |

## 実行方法

```bash
cd ~/supply-chain-risk

# C-1: ImportYeti品質改善 → コード変更のみ（テスト実行）
.venv311/bin/python -c "from pipeline.trade.importyeti_client import quality_score, deduplicate_shipments, COMPANY_ALIASES; print(f'ALIASES: {len(COMPANY_ALIASES)} companies')"

# C-2: HS_PROXY_DATA自動更新
.venv311/bin/python scripts/update_hs_proxy.py

# C-3: 制裁品質レポート
.venv311/bin/python scripts/sanctions_quality_report.py

# C-4: 全次元スコア計算
.venv311/bin/python scripts/fill_all_dimensions.py

# C-5: BACI代替データ構築
.venv311/bin/python scripts/build_hs_proxy_from_comtrade.py
```
