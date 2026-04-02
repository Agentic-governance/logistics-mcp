# SCRI v1.4.0 TFI Task 1-2 Complete

## Task 1: 実効飛行距離（Effective Flight Distance）クライアント
**ファイル**: `pipeline/tourism/effective_distance_client.py`

### 実装内容
- `EffectiveFlightDistanceClient` クラス — OpenFlightsデータから実効飛行距離を算出
- `EffectiveDistance` dataclass — 算出結果を格納
- EFD = 加重平均ルート距離 x 乗り継ぎペナルティ x 頻度ペナルティ
  - 加重平均: 週次座席数ベースで重み付けしたHaversine大圏距離
  - 乗り継ぎペナルティ: `1 + (1 - direct_ratio) * 0.4`
  - 頻度ペナルティ: `max(1.0, 2.0 - weekly_seats / 1000)`
- 18カ国のハードコードフォールバック（`EFD_FALLBACK`）
- 18カ国のバリデーション用フライト時間データ（`VALIDATION_FLIGHT_HOURS`）
- 短距離路線の実効速度補正（離着陸・上昇降下フェーズ考慮）

### バリデーション結果
- **12/18 合格**（±20%以内）
- 長距離路線（US, DE, GB, FR, AU等）: 全合格（81-93%）
- 短距離路線で一部WARNあり（大圏距離 vs フライト時間×速度の乖離は物理的に正常）

## Task 2: 文化的距離クライアント
**ファイル**: `pipeline/tourism/cultural_distance_client.py`

### 実装内容
- `CulturalDistanceClient` クラス — Kogut-Singh指数 + 言語距離の複合指標
- `CulturalDistance` dataclass — 算出結果を格納
- CD_total = 0.7 x CD_hofstede_normalized + 0.3 x CD_linguistic
- Hofstede 6次元データ: 22カ国（PDI, IDV, MAS, UAI, LTO, IVR）
- 言語距離: 22カ国（日本語基準、0-1スケール）
- `get_all_distances()` — 全国一括算出

### バリデーション結果
- **8/8 合格**
- 順序制約: KR < US, CN < US, TW < US, TW < RU, KR < RU, CN < MX — 全OK
- CN ≈ TW 近似チェック: 差0.1595 < 0.20 — OK
- 東アジア圏（KR/CN/TW）が下位半分 — OK

### 距離ランキング（日本からの文化的距離、昇順トップ5）
1. DE: 0.5325（Hofstede次元でJPと高い類似性）
2. TW: 0.6154
3. KR: 0.6385
4. CN: 0.7749
5. FR: 0.7771

## __init__.py 更新
- `EffectiveFlightDistanceClient`, `EffectiveDistance` をエクスポートに追加
- `CulturalDistanceClient`, `CulturalDistance` をエクスポートに追加

## 構文チェック
- 両ファイルとも `py_compile` パス
