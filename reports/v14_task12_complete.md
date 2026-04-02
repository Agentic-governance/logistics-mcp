# SCRI v1.4.0 TASK 1-2: データ収集・前処理 + Dual-Scaleモデル — 完了レポート

**日付**: 2026-04-03
**ステータス**: 完了

## 実装ファイル一覧

| # | ファイル | TASK | 内容 |
|---|---------|------|------|
| 1 | `pipeline/tourism/variable_collector.py` | 1-A | VariableCollector — 8変数×11カ国×2015-2024 パネルデータ収集 |
| 2 | `features/tourism/travel_momentum.py` | 1-B | TravelMomentumIndex — 6成分加重TMI算出 |
| 3 | `features/tourism/models/__init__.py` | — | モデル群パッケージ初期化 |
| 4 | `features/tourism/models/lstm_structural.py` | 2-A | LSTMStructural — LSTM構造成分（長期トレンド） |
| 5 | `features/tourism/models/transformer_cycle.py` | 2-B | TourismTransformer — Transformerサイクル成分（p10/p50/p90） |
| 6 | `features/tourism/models/dual_scale_model.py` | 2-C | DualScaleModel — Dual-Scale統合 + バックテスト |
| 7 | `features/tourism/__init__.py` | — | 更新: TMI, LSTMStructural, TourismTransformer, DualScaleModel 追加 |

## TASK 1-A: VariableCollector

### ハードコード変数 (8変数×11カ国×10年)
- `gdp_per_capita_ppp`: IMF WEO準拠値
- `consumer_confidence`: OECD MEI近似値 (100=長期平均)
- `exchange_rate`: 対円年平均レート
- `flight_supply_index`: 2019=100基準
- `visa_free`: 0/1 (中国は2024年のみ1)
- `outbound_propensity`: アウトバウンド/人口
- `japanese_restaurant_count`: 2019=100相対指数
- `japanese_language_learners`: 2019=100相対指数

### 前処理パイプライン
1. 年次パネル組み立て → 2. 欠損処理 (bfill→ffill) → 3. cubic spline月次補間 → 4. 標準化 (z-score)

### テスト結果
```
collect_panel_data(['KR','US'], [2019,2020], monthly=True) → 48行×12列
```

## TASK 1-B: TravelMomentumIndex

### TMI 計算式
```
TMI = 0.30×Δoutbound + 0.20×leave_util + 0.15×leisure_share
    + 0.15×Δrestaurant + 0.10×(1-domestic) + 0.10×remote_work
```

### テスト結果
```
TMI KR 2024-07: 0.6640
```
- 11カ国の典型的TMI値をハードコード (2015-2024)
- 6成分すべてにフォールバックデータ搭載

## TASK 2-A: LSTMStructural

### アーキテクチャ
- **PyTorch版**: LSTM(input=2, hidden=64, layers=2, dropout=0.2) → FC(64→24)
  - Huber Loss, Adam lr=0.001, 100エポック
- **Numpyフォールバック**: 12ヶ月移動平均 + 線形回帰

### 内蔵データ
- 11カ国×180ヶ月 (2010-2024) の月次来訪者数
- 2010-2014は2015-2019パターンから年次成長率で逆推定
- 季節パターンで年間値を月次按分

### テスト結果 (numpy fallback)
```
KR: LSTM=417千人/月 (12ヶ月平均)
全11カ国で正常動作確認
```

## TASK 2-B: TourismTransformer

### アーキテクチャ
- **PyTorch版**: Transformer Encoder-Decoder
  - d_model=64, nhead=4, enc_layers=3, dec_layers=3
  - Quantile Loss (p10/p50/p90同時推定)
  - Encoder: 過去24ヶ月データ
  - Decoder: カレンダー特徴量 (月sin/cos, 祝日, 季節)
- **Numpyフォールバック**: 季節分解 + 線形トレンド + ノイズ分位点

### テスト結果 (numpy fallback)
```
KR: p10=137, p50=417, p90=697 千人/月
全11カ国で正常動作確認
```

## TASK 2-C: DualScaleModel

### 統合ロジック
```
alpha(h) = min(0.30 + 0.05*h, 0.80)
forecast = alpha * LSTM_structural + (1-alpha) * Transformer_cycle
```
- h=0 (直近): alpha=0.30 → Transformer 70%
- h=10: alpha=0.80 → LSTM 80% (上限)
- 短期はサイクル重視、長期は構造トレンド重視

### バックテスト
```
KR (holdout=12ヶ月):
  alpha: 0.30-0.85
  backend: LSTM=numpy, Transformer=numpy
```

### メソッド一覧
- `predict(country, horizon)` → DualScaleForecast
- `backtest(country, holdout)` → BacktestResult (MAE/MAPE/RMSE/Coverage90)
- `predict_all(countries)` → 全国一括予測
- `backtest_all(countries)` → 全国一括バックテスト
- `summary(forecast)` → サマリ辞書

## PyTorch / Numpy 共存

全モデルは以下のパターンで実装:
```python
try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
```

- PyTorchインストール済み → GPU/CPU でLSTM/Transformer学習
- PyTorch未インストール → numpyベースのフォールバックで同一インターフェース

## 構文チェック
全7ファイル `py_compile` 通過確認済み。

## 対象国一覧
KR(韓国), CN(中国), TW(台湾), US(米国), AU(豪州), TH(タイ), HK(香港), SG(シンガポール), DE(ドイツ), FR(フランス), GB(英国)
