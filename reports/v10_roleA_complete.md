# ROLE-A 完了報告: 人レイヤー深化 — SCRI v1.0.0

## 実行日時
2026-03-28

## サマリー
人物リスク（person_risk）を第26次元としてスコアリングエンジンに統合完了。
UBO・役員・PEP・オフショアリーク・天下り検出の5軸で企業の人的リスクを評価する。

---

## A-1: OpenOwnership UBO グラフ取込強化
**ファイル**: `pipeline/corporate/openownership_client.py`

### 追加メソッド
- `get_ownership_chain_deep_sync(company_name)` — UBOまで再帰的に遡り、シェル会社・タックスヘイブンを検出
  - タックスヘイブン法域リスト（35法域）内蔵
  - シェル会社検出ロジック: オーナー不在 or タックスヘイブン所在+単一所有者
  - 返却値: chain, shell_company_flags, tax_haven_flags, max_depth
- `find_shared_owners_sync(company_a, company_b)` — 2社間の共通UBOを検索し利益相反を検出
  - 利益相反スコア算出（制裁対象共通=100, PEP共通=加算, 通常30+15n）
- 非同期版: `get_ownership_chain_deep()`, `find_shared_owners()`

---

## A-2: Wikidata 役員データベース強化
**ファイル**: `pipeline/corporate/wikidata_client.py`

### 追加メソッド
- `get_person_affiliations_sync(person_name)` — 人物名から全企業関係を列挙
  - SPARQL: CEO/取締役/勤務先の3パターン UNION クエリ
  - concurrent_roles（現在兼任数）を算出
- `find_revolving_door_sync(person_name)` — 天下り（政府機関→民間）パターンを検出
  - 政府機関キーワード（英語22語+日本語6語）で判定
  - キャリア履歴取得 → 政府/民間を分類 → 両方あれば天下り検出
  - リスクスコア: 基本10点 + 複数政府経験+10 + 多数民間転職+10 (上限50)
- 非同期版: `get_person_affiliations()`, `find_revolving_door()`

---

## A-3: ICIJ Offshore Leaks DB強化
**ファイル**: `pipeline/corporate/icij_client.py`

### 追加メソッド
- `get_offshore_risk_score_sync(company_name)` — 0〜100のオフショアリスクスコアを算出
  - スコアリングロジック:
    - ヒット1件: 20点ベース
    - 追加ヒット毎: +10点（上限+40）
    - タックスヘイブン法域ヒット: +15点
    - 複数データソース（パナマ+パンドラ等）: +15点
    - Officer + Entity 両方ヒット: +10点
  - タックスヘイブン法域リスト（26法域）
- 非同期版: `get_offshore_risk_score()`

---

## A-4: PersonRisk を第26次元としてエンジンに統合
**ファイル**: `scoring/engine.py`, `config/constants.py`

### engine.py 変更点
- `person_risk_score: int = 0` フィールド追加
- WEIGHTS に `"person_risk": 0.04` 追加（既存22次元を *0.96 で比例縮小）
- `calculate_overall()` の scores dict に `person_risk` 追加
- `to_dict()` に person_risk スコア・カテゴリ追加
- `_data_quality_summary()` の分母を 25→26 に更新
- `calculate_risk_score()` に第26次元のスコアリングブロック追加:
  1. OpenOwnership から UBO レコード取得
  2. PersonRiskScorer で UBO チェーン全体のリスクを評価
  3. UBO情報がない場合は ICIJ オフショアリスクで補完
  4. エビデンス（制裁UBO、PEP）を追加
- ドキュメント文字列を26次元に更新

### constants.py 変更点
- `VERSION`: "0.9.0" → "1.0.0"
- `DIMENSIONS`: 25 → 26
- `DATA_SOURCES` に `"person_risk"` カテゴリ追加

### 重み配分（v1.0.0）
| 次元 | 旧重み | 新重み | 変化率 |
|------|--------|--------|--------|
| conflict | 0.0873 | 0.0842 | -3.6% |
| geo_risk | 0.0679 | 0.0652 | -4.0% |
| disaster | 0.0679 | 0.0652 | -4.0% |
| ... (全次元 *0.96) | | | |
| sc_vulnerability | 0.0300 | 0.0288 | -4.0% |
| **person_risk** | **-** | **0.0400** | **新規** |
| **合計** | **1.0000** | **1.0000** | - |

---

## A-5: 検証結果

### 構文チェック（全7ファイル）
- `pipeline/corporate/openownership_client.py`: OK
- `pipeline/corporate/wikidata_client.py`: OK
- `pipeline/corporate/icij_client.py`: OK
- `scoring/engine.py`: OK
- `config/constants.py`: OK
- `scoring/dimensions/person_risk_scorer.py`: OK
- `features/graph/person_company_graph.py`: OK

### インポートチェック
- 全モジュールのインポート成功
- 新メソッドの存在確認完了
- VERSION=1.0.0, DIMENSIONS=26 確認

### 重み合計検証
- **合計: 1.0000** (24加重次元、sanctions/japan_economyは特殊扱い)
- person_risk: 0.0400 (4.0%)

---

## person_risk スコアリング構成

| 要素 | 条件 | スコア |
|------|------|--------|
| 制裁人物 | UBOが制裁リストにヒット | 即100 |
| PEP接続 | UBOがPEP判定 | +30 |
| オフショア構造 | ICIJ Offshore Leaks ヒット | +20〜40 |
| UBO国リスク | 高リスク国籍 | 国リスク*0.3 |
| 天下り | 規制当局出身 | +10 |
| ネットワーク | 兼任先経由の接続リスク | 平均*0.2 |

---

## 変更ファイル一覧
1. `pipeline/corporate/openownership_client.py` — 2メソッド追加
2. `pipeline/corporate/wikidata_client.py` — 2メソッド追加
3. `pipeline/corporate/icij_client.py` — 1メソッド追加
4. `scoring/engine.py` — 26次元化、person_risk統合
5. `config/constants.py` — v1.0.0、26次元
