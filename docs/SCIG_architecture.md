# Supply Chain Intelligence Graph (SCIG) — 統合設計図

## 概念

現在のSCRI = 「国・地域レベルのリスクスコアリング」
次のSCIG = 「物の流れ × 人・組織の関係」を統合した知識グラフ

---

## 4種類のノード

### 1. 企業ノード (Company)
- id: 法人番号 / D-U-N-S / LEI
- name: 正規化企業名 (RapidFuzz済み)
- country: ISO3
- risk_score: 24次元スコア (既存SCRI)
- sanctions: 制裁ヒット状況
- reputation: GDELT評判スコア
- financials: 売上・信用格付

### 2. 人物ノード (Person)
- id: OpenSanctions ID
- name: 正規化人名
- is_pep: 政治的露出者フラグ
- sanctions: 制裁対象フラグ
- positions: 現職・前職リスト
- network_risk: 周辺人物リスク平均

### 3. 部品・製品ノード (Product)
- id: 品番 / GTIN
- hs_code: HSコード
- tier: BOM階層
- cost_share: 原価構成比
- conflict_mineral: 紛争鉱物フラグ
- inferred_origins: 推定原産国 (確率付き)

### 4. 地域ノード (Location)
- id: ISO3 / 港湾コード
- risk_scores: 24次元リスク (既存SCRI)
- chokepoint: チョークポイントフラグ
- forecast: 30日先リスク予測

---

## エッジタイプ（関係の種類）

| From | To | Type | 属性 |
|---|---|---|---|
| 企業 | 企業 | SUPPLIES_TO | 確率・金額・HSコード |
| 企業 | 企業 | OWNED_BY | 株式比率・支配構造 |
| 人物 | 企業 | CONTROLS | UBO・議決権比率 |
| 人物 | 企業 | DIRECTOR_OF | 役職・在任期間 |
| 企業 | 地域 | OPERATES_IN | 工場・倉庫・事務所 |
| 部品 | 企業 | MANUFACTURED_BY | 確定 or 推定(確率付) |
| 部品 | 地域 | ORIGINATES_FROM | 原産国・鉱山 |
| 人物 | 人物 | ASSOCIATED_WITH | 家族・ビジネスパートナー |

---

## データソース（新規追加分）

### 人レイヤー
- OpenOwnership: UBO（実質的支配者）データ 無料
- ICIJ Offshore Leaks DB: パナマ文書等 無料
- Wikidata: 役員・政治家情報 無料
- OpenCorporates API: 企業登記 無料
- EDINET: 日本有報スクレイピング 無料
- SEC EDGAR: 米10-K サプライヤー開示 無料

### 実取引・確定Tier情報
- ImportYeti: 米国通関記録 無料
- BACI: 研究用精緻貿易DB 無料
- SAP EKKO/EKPO: 購買発注履歴 (顧客提供)
- 有報主要仕入先開示: スクレイピング 無料

### 製品・認証
- SEC Conflict Minerals Report (Exhibit 1.01): 無料
- GS1 GTIN DB: 無料
- RoHS/REACH適合DB

---

## 統合グラフで初めて答えられる問い

1. **隠れた制裁リスク**
   「Tier-2サプライヤーのCEOが制裁対象者と取締役を兼任」
   → 現在の制裁スクリーニングでは検出不可
   → 人物グラフ3ホップ検索で検出可能

2. **SAP購買履歴でTier-2確定化**
   EKKO/EKPO + 品目マスタ原産国フィールド
   → 「推定68%」が「確定」になる

3. **IR開示でTier-1自動構築**
   有報主要仕入先300社をスクレイピング
   → BOM入力なしでTier-1グラフが自動構築

4. **役員兼任ネットワーク分析**
   競合他社役員兼任 → 情報漏洩リスク
   政府機関出身役員 → 規制リスク

5. **紛争鉱物規制自動対応**
   BOM × 原材料推定 → SEC Section 1502 レポート自動生成

---

## 実装フェーズ

### Phase 1 (現在〜v0.9.0): 物レイヤー完成
- BOM Tier-2/3 確率推定 ✅
- コスト試算 ✅
- SAP連携インターフェース設計

### Phase 2 (v1.0.0): 人レイヤー追加
- OpenOwnership UBOグラフ取込
- 役員DB (Wikidata/EDINET)
- 人物-企業エッジ構築

### Phase 3 (v1.1.0): 統合グラフ化
- NetworkX → Neo4j移行 or 拡張
- クロスレイヤー推論エンジン
- 3ホップ制裁検索

### Phase 4 (v1.2.0): 実取引データ統合
- ImportYeti通関記録取込
- 有報スクレイピング自動化
- SAP API連携 (顧客別)
