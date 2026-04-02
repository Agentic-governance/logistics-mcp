# SCRI v1.4.0 — TASK 3-5 完了レポート

## 概要
Travel Friction Index (TFI)、TFI統合PPML、Cultural Inertia Coefficient (CIC) を実装。

## TASK 3: Travel Friction Index
**ファイル**: `features/tourism/travel_friction_index.py` (新規)

- `TravelFrictionIndex` クラス: TFI = 0.40×文化距離 + 0.40×log(EFD)正規化 + 0.20×ビザ障壁
- `TFIResult` データクラス: source_country, tfi, cultural_distance, effective_flight_distance, visa_barrier, components
- `TFI_PRECOMPUTED`: 20カ国のプリコンピュートデータ（TASK1-2のクライアント未実装時フォールバック）
- `VISA_SCORES`: 24カ国のビザ障壁スコア
- TASK1-2の `EffectiveFlightDistanceClient` / `CulturalDistanceClient` を try/except でロード

## TASK 4: TFI統合PPML
**ファイル**: `features/tourism/gravity_model.py` (追記)

- `TFIEnrichedGravityModel(TourismGravityModel)`: TFIを距離変数として追加したPPML
- `ExcessDemandRecord` データクラス: excess_demand = actual - predicted
- `calculate_excess_demand()`: ブランド効果の計算
- `save_excess_demand()`: tourism_stats.db の excess_demand テーブルに保存
- 既存の `TourismGravityModel` は一切変更なし（サブクラスで拡張）

## TASK 5: Cultural Inertia Coefficient
**ファイル**: `features/tourism/cultural_inertia.py` (新規)

- `CulturalInertiaCoefficient` クラス
  - `calculate_structural()`: structural_cic = 1 - TFI/100
  - `estimate_psychological()`: excess_demandトレンドベース（データ<3月→0）
  - `get_full_cic()`: total = 0.70×structural + 0.30×psychological
- `CICResult` データクラス: country, structural_cic, psychological_cic, total_cic, alpha, recovery_rate, interpretation

## 更新ファイル
- `features/tourism/__init__.py`: TravelFrictionIndex, TFIEnrichedGravityModel, CulturalInertiaCoefficient を追加
- `tests/test_tourism_gravity.py`: TestTFI(6テスト), TestTFIEnrichedGravityModel(4テスト), TestCIC(6テスト) 追加

## テスト結果
```
59 passed, 6 deselected (network), 12 warnings in 2.85s
```
- 新規16テスト: 全パス
- 既存43テスト: 全パス（破壊なし）
