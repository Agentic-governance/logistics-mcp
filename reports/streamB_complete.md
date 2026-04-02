# Stream B: Person Layer Implementation — SCRI v0.9.0

## 概要

企業-人物のリスクレイヤー実装。OpenOwnership UBO、ICIJ Offshore Leaks、
Wikidata 役員情報を統合し、制裁・PEP・オフショアリーク・国籍・ネットワークの
5軸で個人リスクを評価する。v0.9.0 ではネットワークリスク計算をグラフベースに強化。

## コンポーネント一覧

### B-1: OpenOwnership UBO クライアント
**ファイル:** `pipeline/corporate/openownership_client.py`

- `UBORecord` dataclass: person_name, nationality, ownership_pct, is_pep, sanctions_hit
- `OpenOwnershipClient`:
  - `get_ubo()` / `get_ubo_sync()` — 実質的支配者取得
  - `get_ownership_chain()` / `get_ownership_chain_sync()` — 所有チェーン全体をツリー形式で取得
- 制裁スクリーナー (`pipeline.sanctions.screener`) 連携で PEP/制裁フラグ自動付与
- レートリミット 1req/sec、タイムアウト 15秒

### B-2: ICIJ Offshore Leaks DB クライアント
**ファイル:** `pipeline/corporate/icij_client.py`

- `LeakRecord` dataclass: entity_name, entity_type, jurisdiction, linked_to, data_source, node_id
- `ICIJClient`:
  - `search_entity()` / `search_entity_sync()` — 全タイプ検索
  - `search_officer()` / `search_officer_sync()` — Officer フィルタ検索
  - `search_company()` / `search_company_sync()` — Entity フィルタ検索
- 対応データソース: Panama Papers, Pandora Papers, Paradise Papers, Bahamas Leaks, Offshore Leaks
- レートリミット 1req/sec

### B-3: Wikidata 役員情報クライアント
**ファイル:** `pipeline/corporate/wikidata_client.py`

- `Executive` dataclass: name, wikidata_id, position, company, start_date, end_date, nationality
- `BoardMember` dataclass: name, wikidata_id, company, board_role, other_boards
- `WikidataClient`:
  - `get_executives()` / `get_executives_sync()` — 経営幹部 (CEO, CFO等)
  - `get_board_members()` / `get_board_members_sync()` — 取締役
  - `find_interlocking_directorates()` / `find_interlocking_directorates_sync()` — 兼任役員ネットワーク
- SPARQL クエリ: 完全一致 + 部分一致の2段階企業名解決
- レートリミット 1req/2sec (Wikidata推奨)

### B-4: 人物リスクスコアラー
**ファイル:** `scoring/dimensions/person_risk_scorer.py`

- `PersonRiskScorer`:
  - `score_person(name, nationality, company_associations, graph)` — 個人リスク5軸評価
  - `score_ownership_chain(ubo_records, company_name, graph)` — UBOチェーン全体リスク
- スコアリングロジック:
  - 制裁ヒット: 即100点 (CRITICAL)
  - PEP（政治的露出者）: +30点
  - オフショアリーク: +25点 (複数ヒットで最大+40)
  - 高リスク国籍: country_risk_score * 0.3
  - **[v0.9.0強化] ネットワークリスク: グラフベース — 接続人物の平均リスク * 0.2 + 近傍制裁者/PEP加算 (上限30)**
- リスクレベル: CRITICAL (80+), HIGH (60+), MEDIUM (40+), LOW (20+), MINIMAL (<20)
- 国籍リスクスコアDB: 30+ 国 (DPRK=100, Iran=95 ... Cayman=40)

### B-5: 企業-人物グラフ
**ファイル:** `features/graph/person_company_graph.py`

- `PersonCompanyGraph` (NetworkX DiGraph):
  - `add_company()`, `add_person()`, `add_edge()` — ノード/エッジ操作
  - `find_path(entity1, entity2, max_hops)` — 2エンティティ間の全経路
  - `get_risk_exposure(company, max_hops)` — N ホップ以内の制裁/PEP検出
  - **[v0.9.0新規] `get_connected_person_risks(person, max_hops)` — 接続人物のリスク集約**
  - `build_from_ubo()`, `build_from_wikidata()` — データソース別グラフ構築
  - `to_dict()`, `get_stats()` — エクスポート/統計
- 関係タイプ: CONTROLS, DIRECTOR_OF, EXECUTIVE_OF, ASSOCIATED_WITH, OWNS, SUBSIDIARY_OF

### B-6: MCP ツール (3ツール)
**ファイル:** `mcp_server/server.py`

1. **screen_ownership_chain(company_name)** — UBOチェーンリスクスクリーニング
   - OpenOwnership → グラフ構築 → ネットワーク連携スコアリング → リスクエクスポージャー分析
2. **check_pep_connection(company_name, max_hops=3)** — PEP接続検査
   - UBO + Wikidata役員/取締役の統合グラフからNホップ以内のPEP/制裁対象検出
3. **get_officer_network(company_name)** — 役員ネットワーク分析
   - Wikidata役員取得 → ICIJ照合 → グラフ連携リスクスコアリング（国籍情報付き）

## v0.9.0 での強化点

1. **ネットワークリスク精密計算**: `PersonRiskScorer.score_person()` に `graph` パラメータ追加。
   `PersonCompanyGraph.get_connected_person_risks()` で BFS 探索し、接続人物の平均リスク・
   制裁者数・PEP数をもとにネットワークスコアを算出（旧: 単純な企業数ヒューリスティック）。
2. **グラフ→スコアラー連携**: MCP ツール `screen_ownership_chain` と `get_officer_network` が
   構築済みグラフをスコアラーに渡し、ネットワークリスクを精密に反映。
3. **国籍情報の伝播**: `get_officer_network` が Wikidata の国籍情報を `score_person()` に渡す
   ことで、役員の国籍リスクも正確に評価。

## テスト結果

```
$ .venv311/bin/python -c "from features.graph.person_company_graph import PersonCompanyGraph; ..."
connected persons: 1
pep_count: 1
avg_risk: 50.0
Alice score: 39, network: 15
All tests passed
```

- PEP (Bob, Russia) が TestCorp 経由で Alice に接続 → Alice のネットワークスコア = 15
- 制裁/PEP/国籍の各チェックは graceful degradation (APIエラー時は0点でスキップ)
