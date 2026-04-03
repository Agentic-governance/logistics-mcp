# SCRI v1.5.0 — 国別シナリオエンジン + 二国間為替クライアント

## 完了サマリー (2026-04-04)

### 新規ファイル
| ファイル | 内容 |
|---|---|
| `pipeline/tourism/bilateral_fx_client.py` | Frankfurter API二国間為替レートクライアント (12通貨対応) |
| `features/tourism/scenario_engine.py` | 9シナリオ×12市場の需要影響計算エンジン |

### 変更ファイル
| ファイル | 変更内容 |
|---|---|
| `api/routes/tourism.py` | GET `/scenarios`, POST `/scenario-analysis` 追加 |
| `pipeline/tourism/__init__.py` | BilateralFXClient エクスポート追加 |
| `features/tourism/__init__.py` | ScenarioEngine, SCENARIOS, CountryScenarioImpact エクスポート追加 |
| `tests/test_tourism_gravity.py` | TestBilateralFXClient(5件) + TestScenarioEngine(8件) 追加 |

### BilateralFXClient
- 12市場の通貨マッピング (CURRENCY_MAP)
- 国別為替弾性値 (FX_ELASTICITY): KR=0.45, CN=0.70, TH=0.80, IN=0.90 等
- Frankfurter API失敗時のハードコードフォールバック (FALLBACK_RATES)
- `get_current_rates()`, `get_historical_rates(year)`, `calculate_fx_shock()`

### ScenarioEngine — 9シナリオ
| シナリオ | 全体影響 | 特記 |
|---|---|---|
| base | 0.00% | 基準ケース |
| jpy_weak_10 | +4.97% | 円安で全市場にプラス |
| jpy_strong_10 | -4.97% | 円高で全市場にマイナス |
| china_stimulus | +5.2% | CN+25%, HK+10% |
| flight_expansion | +6.8% | アジア近距離路線に恩恵大 |
| japan_china_tension | -11.3% | CN-40.6%, HK-17% |
| us_recession | -12.1% | US-20%, 円高連動 |
| taiwan_strait_risk | -18.4% | TW-50%, CN-30% |
| stagflation_mixed | -2.8% | US-15% vs CN+5%(円安恩恵) |

### API新規エンドポイント
- `GET /api/v1/tourism/scenarios` — シナリオ一覧 (フォールバック付き)
- `POST /api/v1/tourism/scenario-analysis` — 国別影響分析 (為替詳細オプション)

### テスト結果
```
TestBilateralFXClient: 5 passed
TestScenarioEngine:    8 passed
合計: 13 passed, 0 failed
```
