# SCRI v1.4.0 — TASK 1-3 完了報告

## 完了日時
2026-04-03

## TASK 1: PPML構造重力モデル (gravity_model.py 全面改修)

### 実装内容
- **推定手法**: statsmodels Poisson GLM (PPML) + HC3ロバスト標準誤差
- **固定効果**: ソース国FE (参照: CN) + 年FE (参照: 2019)
- **説明変数**: ln_gdp_source, ln_exr, ln_flight, visa_free, bilateral_risk
- **パネルデータ**: 11カ国 × 2015-2019 + 2022-2024 = 88観測値
- **ゼロ対応**: PPMLはレベル形式なのでゼロ観測値をそのまま扱える
- **フォールバック**: PPML失敗時 → COEFFICIENT_PRIORS (学術文献ベース)

### 推定結果
| 変数 | 係数 | p値 |
|------|------|-----|
| ln_gdp_source | +0.630 | 0.018 |
| ln_exr | -1.116 | 0.014 |
| ln_flight | +1.768 | 0.000 |
| visa_free | -2.542 | 1.000 (FE吸収) |
| bilateral_risk | -1.953 | 0.027 |

- **McFadden pseudo R² = 0.9874**
- **N = 88, 収束 = True**

### クラスメソッド
- `fit(panel_data)` → FitResult
- `fit_from_db()` → tourism_stats.dbからデータ読み込み
- `predict_with_uncertainty(country, months, n_samples, scenario)` → BayesianForecast
- `predict_point(country, year_month, shock)` → float
- `decompose_forecast_by_variable(country, year_month)` → dict
- `predict()` — 後方互換

## TASK 2: STL季節分解 (seasonal_extractor.py 新規)

### 実装内容
- **手法**: statsmodels STL (robust=True, seasonal=13)
- **データ**: 5カ国 (KR, CN, TW, US, AU) × 2015-2019 月次 (60ヶ月)
- **出力**: 12ヶ月の季節指数 (平均=1.0に正規化)
- **フォールバック**: STL失敗時 → FALLBACK_SEASONAL (11カ国分)

### KR季節指数サンプル (STL推定)
| 月 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|----|---|---|---|---|---|---|---|---|---|----|----|-----|
| KR | 0.94 | 0.88 | 1.03 | 1.01 | 0.94 | 0.97 | 1.06 | 1.11 | 1.04 | 0.97 | 0.91 | 0.96 |

### クラスメソッド
- `fit(country, data, period)` → SeasonalPattern
- `fit_all_countries()` → dict
- `apply_seasonal(base_forecast, year_month_list, country)` → list

## TASK 3: ボトムアップ集計エンジン (inbound_aggregator.py 新規)

### 実装内容
- **日本全体**: 11カ国のPPML予測をモンテカルロ(n=1000)で積み上げ
- **都道府県**: PREF_SHARE (10都道府県) × ローカルリスク補正
- **ローカルリスク**: 沖縄台風(7-10月+8%), 北海道雪(12-3月+3%), 東京猛暑(7-8月+1%)

### クラスメソッド
- `calculate_japan_total(year_months, n_samples)` → JapanForecast
- `calculate_prefecture(pref, japan_forecast, year_months)` → PrefForecast
- `_get_local_risk(pref, year_months)` → list

## __init__.py 更新
- TourismGravityModel, SeasonalExtractor, InboundAggregator をエクスポート
- 既存の RegionalDistributionModel, InboundTourismRiskScorer も維持

## 構文チェック結果
- gravity_model.py: OK
- seasonal_extractor.py: OK
- inbound_aggregator.py: OK
- __init__.py: OK
- 全インポート成功、PPML推定・STL分解・ポイント予測すべて動作確認済み
