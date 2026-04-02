# v1.3.0 ROLE-A: グローバル観光統計クライアント群 — 完了レポート

## 実装サマリー

pipeline/tourism/ ディレクトリを新規作成し、4つの観光統計クライアント + __init__.py を実装。

### A-1: UNWTO統計クライアント (`unwto_client.py`)
- World Bank WDI経由で4指標取得: ST.INT.ARVL, ST.INT.DPRT, ST.INT.RCPT.CD, ST.INT.XPND.CD
- `UNWTOClient` クラス: 4 async メソッド (get_outbound_total, get_inbound_to_japan, get_destination_share, batch_get_outbound)
- 同期便利関数: `get_tourism_profile()`, `get_tourism_risk_indicators()`
- 18カ国のアウトバウンド/インバウンドのハードコードフォールバック完備

### A-2: JNTOクライアント (`jnto_client.py`)
- 主要20市場のISO3→JNTO名称マッピング
- HISTORICAL_DATA: 20市場 x 4年分 (2019, 2023, 2024, 2025) = 80データポイント
- 月別構成比 (MONTHLY_SHARE) + 国別季節調整係数 (COUNTRY_SEASONAL)
- `JNTOClient` クラス: 4 async メソッド (get_monthly_arrivals_by_country, get_annual_trend, get_top_source_markets, get_latest)
- e-Stat API対応（APIキー設定時）、フォールバック月次推定機能
- 同期便利関数: `get_japan_inbound_summary()`

### A-3: 国別アウトバウンドクライアント群 (`country_outbound_clients.py`)
- 共通基底クラス `_BaseOutboundClient` で get_outbound_monthly(), get_outbound_trend() を統一
- 5カ国個別クライアント: ChinaOutboundClient (NBS), KoreaOutboundClient (KOSIS), TaiwanOutboundClient (観光署), USOutboundClient (NTTO), AustraliaOutboundClient (ABS)
- `WorldBankTourismClient`: 全22カ国対応のフォールバッククライアント
- 各国APIを試行しWBフォールバック → ハードコードフォールバックの3段階
- ファクトリー関数 `get_client_for_country()`

### A-4: 競合デスティネーション統計クライアント (`competitor_stats_client.py`)
- 競合8カ国 (THA, KOR, TWN, SGP, IDN, FRA, ITA, ESP) の詳細プロファイル
- `CompetitorStatsClient` クラス: 3 async メソッド (get_competitor_inbound, get_relative_performance, calculate_diversion_index)
- 送客国別デスティネーションシェア推定 (CHN, KOR, USA, TWN)
- 転換指数 (diversion_index) 算出機能
- 国別月次シーズナリティ比率 (THA, FRA, ESP, ITA)
- 同期便利関数: `get_competitor_summary()`

## テスト結果
- 全4ファイル: 構文チェック OK
- インポートテスト: 全クラス・関数のインポート成功
- JNTO同期サマリー: 正常動作 (total=2,590,460 推定月次)
- 競合サマリー: 正常動作 (8カ国分)

## ファイル一覧
| ファイル | 行数 | 主要クラス/関数 |
|---|---|---|
| pipeline/tourism/__init__.py | ~28 | 全エクスポート |
| pipeline/tourism/unwto_client.py | ~240 | UNWTOClient, get_tourism_profile |
| pipeline/tourism/jnto_client.py | ~310 | JNTOClient, get_japan_inbound_summary |
| pipeline/tourism/country_outbound_clients.py | ~310 | 6クライアントクラス, get_client_for_country |
| pipeline/tourism/competitor_stats_client.py | ~300 | CompetitorStatsClient, get_competitor_summary |

## 設計方針
- World Bank WDI APIを第一ソースとし、各国一次統計APIを補完的に試行
- 全API呼び出しをtry/exceptで囲みフォールバックデータを常に用意
- async/await対応 + 同期便利関数を併設
- コメント・docstringは全て日本語
- 既存worldbank_client.pyのHTTPリクエストパターンを踏襲
