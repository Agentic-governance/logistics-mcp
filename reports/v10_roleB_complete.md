# ROLE-B 完了レポート: 統合グラフエンジン & 3ホップ制裁検索

**日時**: 2026-03-28
**バージョン**: v1.0.0

## 実装サマリー

### B-1: 統合グラフスキーマ (unified_graph.py)
- `SCIGraph` クラス — NetworkX MultiDiGraph ベース
- 4種ノード: company, person, product, location
- 10種エッジ: SUPPLIES, OWNS, DIRECTOR_OF, EXECUTIVE_OF, CONTROLS, OPERATES_IN, PRODUCES, CONTAINS, ORIGINATES, ASSOCIATED_WITH
- メソッド: add_company/person/product/location, add_supply_relation/ownership/directorship/operates_in/product_relation/bom_relation/origin
- クエリ: get_neighbors, get_sanctioned_nodes, get_nodes_by_type, get_edges_by_type
- シリアライズ: to_dict / from_dict (往復テスト済み)
- マージ: merge() で複数グラフを統合可能

### B-2: 3ホップ制裁検索エンジン (sanction_path_finder.py)
- `SanctionPathFinder` クラス
- `find_sanction_exposure()` — BFS で max_hops 以内の制裁ノードを検出、ホップ距離でスコアリング (1hop=100, 2hop=70, 3hop=40)
- `find_conflict_mineral_path()` — BOM構成を DFS で遡り、紛争地域 (CD/CF/SS/SO/YE/SY/AF/MM/LY/RW/UG) 経由パスを検出
- `get_network_risk_score()` — PersonalizedPageRank でリスク伝播スコア (0-100) を算出
- `get_full_exposure_report()` — 制裁+PageRankの統合レポート + リスクレベル判定 + 推奨アクション

### B-3: グラフ自動構築パイプライン (graph_builder_v2.py)
- `SCIGraphBuilder` クラス (async)
- 5段階パイプライン: BOM構築 → 制裁スクリーニング → 所有構造(UBO) → 役員情報(Wikidata) → 通関確定(ImportYeti)
- `build_full_graph()` — ワンコール統合構築
- `build_full_graph_sync()` — MCP ツール向け同期ラッパー

### B-4: グラフ可視化データ生成 (graph_visualizer.py)
- `to_d3_json()` — D3.js force-directed graph 形式 (nodes/links + color/size/shape/opacity)
- `to_adjacency_matrix()` — 隣接行列形式
- `to_mermaid()` — Mermaid フローチャート (テキストレポート用)
- `generate_risk_highlights()` — 制裁/高リスク/PEP/未確認取引のハイライト

### B-5: MCPツール追加 (server.py)
3ツール追加 (合計46ツール):
1. `find_sanction_network_exposure(entity_name, max_hops)` — 3ホップ制裁ネットワーク検索 + D3可視化
2. `build_supply_chain_graph_tool(bom_input, buyer_company, include_ownership, include_directors)` — BOMから統合グラフ構築
3. `get_network_risk_score(entity_name, radius)` — PageRankリスク伝播スコア

## テスト結果

| テスト | 結果 |
|--------|------|
| SCIGraph 基本操作 (7ノード/6エッジ) | PASS |
| 制裁パス検索 (2hop=score70, 3hop=score40) | PASS |
| PageRank リスクスコア (38.6) | PASS |
| 紛争鉱物パス検出 (DRC経由1件) | PASS |
| シリアライズ往復 (to_dict/from_dict) | PASS |
| グラフマージ | PASS |
| D3 JSON 生成 (7ノード/6リンク) | PASS |
| Mermaid 生成 (20行) | PASS |
| リスクハイライト (3件: 制裁2, PEP1) | PASS |
| BOM グラフ構築 (7ノード/6エッジ) | PASS |

## ファイル一覧

| ファイル | 状態 | 概要 |
|----------|------|------|
| `features/graph/unified_graph.py` | 新規 | SCIGraph 統合知識グラフ (~380行) |
| `features/graph/sanction_path_finder.py` | 新規 | 制裁パス検索エンジン (~270行) |
| `features/graph/graph_builder_v2.py` | 新規 | グラフ自動構築パイプライン (~340行) |
| `features/graph/graph_visualizer.py` | 新規 | D3/Mermaid可視化データ生成 (~280行) |
| `features/graph/__init__.py` | 更新 | docstring更新 |
| `mcp_server/server.py` | 更新 | 3ツール追加 (~200行追加) |
