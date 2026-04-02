"""
Cultural Inertia Coefficient (CIC) — 文化的慣性係数
====================================================
SCRI v1.4.0 / TASK 5

CIC = structural_cic + psychological_cic

structural_cic = 1 - TFI / 100
  → 文化的近接性による構造的リピート傾向
  → 高い = 低摩擦 = 訪日が容易 = 慣性が強い

psychological_cic = excess_demand トレンドから推定
  → ブランド効果の時系列安定性
  → データ < 3ヶ月なら 0

total_cic = α × structural + (1-α) × psychological
  α = 0.70 (構造的要因優先)

解釈:
  > 0.80: 強い文化的慣性（アジア近隣国）
  0.50-0.80: 中程度（東南アジア、オセアニア）
  < 0.50: 弱い慣性（欧米遠距離国）
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class CICResult:
    """Cultural Inertia Coefficient 計算結果"""
    country: str
    structural_cic: float         # 0-1
    psychological_cic: float      # 0-1
    total_cic: float              # 0-1
    alpha: float                  # 構造重み (default 0.70)
    recovery_rate: float          # コロナ後回復率 (参考値)
    interpretation: str           # "STRONG" / "MODERATE" / "WEAK"


# ---------------------------------------------------------------------------
# 構造パラメータ
# ---------------------------------------------------------------------------
_ALPHA = 0.70  # structural_cic の重み
_PSYCHOLOGICAL_LOOKBACK_MIN = 3  # 最小必要月数


class CulturalInertiaCoefficient:
    """
    Cultural Inertia Coefficient — 文化的慣性係数

    TFI由来の構造的慣性 + excess_demand由来の心理的慣性
    """

    def __init__(self, alpha: float = _ALPHA) -> None:
        self._alpha = alpha
        self._tfi_index = None
        self._tfi_cache = {}
        self._load_tfi()

    def _load_tfi(self) -> None:
        """TFIモジュールをロード"""
        try:
            from features.tourism.travel_friction_index import TravelFrictionIndex
            self._tfi_index = TravelFrictionIndex()
            all_tfi = self._tfi_index.calculate_all_countries()
            for country, result in all_tfi.items():
                self._tfi_cache[country] = result.tfi
            logger.info("CIC: TFI ロード完了: %d カ国", len(self._tfi_cache))
        except Exception as e:
            logger.warning("CIC: TFI ロード失敗: %s → プリコンピュートを使用", e)
            try:
                from features.tourism.travel_friction_index import TFI_PRECOMPUTED
                for country, data in TFI_PRECOMPUTED.items():
                    self._tfi_cache[country] = data["tfi"]
            except Exception:
                # 完全フォールバック
                self._tfi_cache = {
                    "KR": 12.5, "TW": 14.8, "CN": 42.3, "HK": 16.2,
                    "TH": 25.8, "SG": 22.1, "US": 38.5, "AU": 37.8,
                    "GB": 42.5, "DE": 41.8, "FR": 43.2, "RU": 68.5,
                }

    # -------------------------------------------------------------------
    def _get_tfi(self, country: str) -> float:
        """国のTFI値を取得"""
        return self._tfi_cache.get(country.upper(), 40.0)

    # -------------------------------------------------------------------
    def calculate_structural(self, country: str) -> float:
        """
        構造的CIC = 1 - TFI / 100

        TFIが低い（摩擦が小さい）ほどCICが高い（慣性が強い）。
        """
        tfi = self._get_tfi(country)
        cic = 1.0 - tfi / 100.0
        return round(max(0.0, min(1.0, cic)), 4)

    # -------------------------------------------------------------------
    def estimate_psychological(
        self,
        country: str,
        lookback_months: int = 24,
    ) -> float:
        """
        心理的CIC: excess_demandトレンドから推定。

        excess_demandが安定的に正（ブランドプレミアム持続）→ 高い心理的慣性
        データ < 3ヶ月なら 0 を返す。

        Args:
            country: ISO2コード
            lookback_months: 参照期間（月数）

        Returns:
            psychological_cic (0-1)
        """
        try:
            excess_data = self._load_excess_demand(country, lookback_months)
        except Exception:
            excess_data = []

        if len(excess_data) < _PSYCHOLOGICAL_LOOKBACK_MIN:
            logger.debug("CIC心理: %s データ不足 (%d < %d) → 0",
                        country, len(excess_data), _PSYCHOLOGICAL_LOOKBACK_MIN)
            return 0.0

        # excess_demandの安定性を計算
        # 正の超過需要の割合 × 変動の安定性
        positive_ratio = sum(1 for x in excess_data if x > 0) / len(excess_data)

        # 変動係数（CV）の逆数で安定性を測定
        mean_ed = sum(excess_data) / len(excess_data)
        if len(excess_data) > 1 and mean_ed != 0:
            variance = sum((x - mean_ed) ** 2 for x in excess_data) / len(excess_data)
            std_ed = math.sqrt(variance)
            cv = std_ed / abs(mean_ed) if mean_ed != 0 else 1.0
            stability = 1.0 / (1.0 + cv)  # 0-1
        else:
            stability = 0.5

        # 心理的CIC = positive_ratio × stability
        psy_cic = positive_ratio * stability
        return round(max(0.0, min(1.0, psy_cic)), 4)

    # -------------------------------------------------------------------
    def _load_excess_demand(
        self,
        country: str,
        lookback_months: int,
    ) -> List[float]:
        """excess_demandテーブルからデータを読む"""
        try:
            from pipeline.tourism.tourism_db import TourismDB
            import sqlite3

            db = TourismDB()
            conn = sqlite3.connect(db.db_path)
            conn.row_factory = sqlite3.Row

            rows = conn.execute("""
                SELECT excess_demand
                FROM excess_demand
                WHERE source_country = ?
                ORDER BY year_month DESC
                LIMIT ?
            """, (country, lookback_months)).fetchall()
            conn.close()

            return [float(r["excess_demand"]) for r in rows]

        except Exception as e:
            logger.debug("excess_demand DB読み込み失敗: %s", e)
            return []

    # -------------------------------------------------------------------
    def _estimate_recovery_rate(self, country: str) -> float:
        """コロナ後回復率（2024 / 2019）を推定"""
        # 内蔵パネルデータから回復率を算出
        try:
            from features.tourism.gravity_model import _BUILTIN_PANEL
            visitors_2019 = 0
            visitors_2024 = 0
            iso2 = country.upper()
            for row in _BUILTIN_PANEL:
                if row["country"] == iso2:
                    if row["year"] == 2019:
                        visitors_2019 = row["visitors"]
                    elif row["year"] == 2024:
                        visitors_2024 = row["visitors"]
            if visitors_2019 > 0:
                return round(visitors_2024 / visitors_2019, 4)
        except Exception:
            pass
        return 0.80  # デフォルト

    # -------------------------------------------------------------------
    def get_full_cic(self, country: str) -> CICResult:
        """
        Total CIC = α × structural + (1-α) × psychological

        Args:
            country: ISO2コード

        Returns:
            CICResult
        """
        country = country.upper()

        structural = self.calculate_structural(country)
        psychological = self.estimate_psychological(country)
        recovery = self._estimate_recovery_rate(country)

        total = self._alpha * structural + (1.0 - self._alpha) * psychological
        total = round(max(0.0, min(1.0, total)), 4)

        # 解釈
        if total >= 0.60:
            interpretation = "STRONG"
        elif total >= 0.40:
            interpretation = "MODERATE"
        else:
            interpretation = "WEAK"

        return CICResult(
            country=country,
            structural_cic=structural,
            psychological_cic=psychological,
            total_cic=total,
            alpha=self._alpha,
            recovery_rate=recovery,
            interpretation=interpretation,
        )

    # -------------------------------------------------------------------
    def get_all_cic(self) -> Dict[str, CICResult]:
        """全プリコンピュート国のCICを計算"""
        results = {}
        for country in self._tfi_cache:
            results[country] = self.get_full_cic(country)
        return results

    # -------------------------------------------------------------------
    def get_cic_ranking(self) -> List[CICResult]:
        """CIC降順（慣性が強い順）でランキング"""
        all_results = self.get_all_cic()
        return sorted(all_results.values(), key=lambda r: r.total_cic, reverse=True)
