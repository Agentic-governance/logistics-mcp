# ROLE-D: 日本国内分散モデル — 完了報告

## ステータス: COMPLETE
- 日付: 2026-04-02
- バージョン: SCRI v1.3.0

## 実装ファイル
- `features/tourism/regional_distribution.py` (新規, ~420 LOC)
- `features/tourism/__init__.py` (更新)

## 実装内容

### RegionalDistributionModel クラス
| メソッド | 説明 |
|---------|------|
| `get_accommodation_stats(year, month, prefecture)` | 観光庁宿泊旅行統計の取得（現在は推計値） |
| `get_port_of_entry_stats(year, month)` | 法務省出入国管理統計の取得（現在は推計値） |
| `calculate_regional_shares(year, months_back)` | 過去データからシェア再計算（将来のe-Stat接続用） |
| `predict_regional_distribution(total, country, season, ...)` | コア: 全国予測→47都道府県分配 |
| `get_capacity_constraint(prefecture, month)` | 宿泊施設稼働率に基づくキャパシティ制約 |
| `check_capacity_all(distribution, month)` | 一括キャパシティアラート |

### 定数データ
- **PREFECTURE_SHARES**: 47都道府県のベースシェア（主要20県+残り27県均等配分、合計=1.0）
- **NATIONALITY_BIAS**: 6カ国（CHN, KOR, TWN, USA, AUS, THA）の地域偏向
- **SEASONAL_BIAS**: 4季節（桜, 紅葉, スキー, 夏）の地域偏向
- **PORT_OF_ENTRY_SHARES**: 7空港+その他の入国シェア

### predict_regional_distribution ロジック
1. ベースシェア（PREFECTURE_SHARES）
2. 国籍バイアス加算（"rural" は27県に均等分配）
3. 季節バイアス加算（月から自動判定可）
4. 入国空港バイアス（重み0.10で混合）
5. 正規化（負値クランプ→合計1.0）
6. 最大剰余法で整数分配（**合計一致保証**）

### キャパシティ制約
- 稼働率 ≥ 95% → `CAPACITY_LIMIT`
- 稼働率 85-95% → `HIGH_UTILIZATION`
- 稼働率 < 85% → `NORMAL`
- 定義済: 東京, 大阪, 京都, 北海道, 沖縄, 福岡, 長野（月別プロファイル）

## テスト結果
| テスト | 結果 |
|--------|------|
| CHN × 桜 × 300万人 → 47県分配 | OK（合計一致） |
| AUS × スキー × 50万人 | OK（北海道14.6%に上昇） |
| KOR × month=4 自動季節判定 | OK（spring_peak判定） |
| 京都4月キャパシティ | CAPACITY_LIMIT (95%) |
| 全都道府県配分確認 | 47県すべてに配分 |

## 未実装（TODO）
- e-Stat API接続（宿泊旅行統計・出入国管理統計のリアルタイム取得）
- 動的シェア再計算（calculate_regional_shares の実データ版）
- イベントバイアス（万博、五輪等の一時的な地域需要変動）
