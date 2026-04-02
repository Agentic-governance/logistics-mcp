"""
Travel Friction Index (TFI) — 渡航摩擦指数
===========================================
SCRI v1.4.0 / TASK 3

TFI = 0.40 × 文化距離(正規化) + 0.40 × log(EFD)正規化 + 0.20 × ビザ障壁

文化距離: Hofstede次元のユークリッド距離（日本基準）
EFD: Effective Flight Distance（乗継ぎ・便数考慮の実効距離）
ビザ障壁: 0=ビザ免除, 50=eVISA/到着ビザ, 80=事前ビザ必須

出力: 0-100（0=摩擦なし, 100=最大摩擦）
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ビザ障壁スコア (日本入国、2025年時点)
# 0=ビザ免除, 50=eVISA/到着ビザ, 80=事前ビザ必須
# ---------------------------------------------------------------------------
VISA_SCORES: Dict[str, int] = {
    "KR": 0, "TW": 0, "HK": 0, "SG": 0,
    "US": 0, "AU": 0, "GB": 0, "DE": 0, "FR": 0,
    "TH": 0, "MY": 0, "ID": 15, "PH": 15,
    "VN": 15, "MX": 0, "BR": 0, "CA": 0, "NZ": 0,
    "CN": 50, "IN": 50,
    "RU": 80, "NG": 80, "PK": 80, "BD": 80,
}

# ---------------------------------------------------------------------------
# TFI プリコンピュート (20カ国、日本基準)
# TASK1-2のクライアント未実装時のフォールバック
# ---------------------------------------------------------------------------
TFI_PRECOMPUTED: Dict[str, Dict[str, float]] = {
    "KR": {"tfi": 12.5, "cultural_distance": 15.0, "efd": 1200, "visa": 0},
    "TW": {"tfi": 14.8, "cultural_distance": 18.0, "efd": 2100, "visa": 0},
    "CN": {"tfi": 42.3, "cultural_distance": 28.0, "efd": 2500, "visa": 50},
    "HK": {"tfi": 16.2, "cultural_distance": 20.0, "efd": 2900, "visa": 0},
    "TH": {"tfi": 25.8, "cultural_distance": 35.0, "efd": 4500, "visa": 0},
    "SG": {"tfi": 22.1, "cultural_distance": 30.0, "efd": 5300, "visa": 0},
    "MY": {"tfi": 28.4, "cultural_distance": 38.0, "efd": 5100, "visa": 0},
    "ID": {"tfi": 34.5, "cultural_distance": 42.0, "efd": 5800, "visa": 15},
    "PH": {"tfi": 32.0, "cultural_distance": 40.0, "efd": 3200, "visa": 15},
    "VN": {"tfi": 30.2, "cultural_distance": 36.0, "efd": 3800, "visa": 15},
    "IN": {"tfi": 52.8, "cultural_distance": 55.0, "efd": 6200, "visa": 50},
    "US": {"tfi": 38.5, "cultural_distance": 48.0, "efd": 10800, "visa": 0},
    "CA": {"tfi": 39.2, "cultural_distance": 50.0, "efd": 9800, "visa": 0},
    "AU": {"tfi": 37.8, "cultural_distance": 47.0, "efd": 7800, "visa": 0},
    "NZ": {"tfi": 40.1, "cultural_distance": 49.0, "efd": 9200, "visa": 0},
    "GB": {"tfi": 42.5, "cultural_distance": 52.0, "efd": 9500, "visa": 0},
    "DE": {"tfi": 41.8, "cultural_distance": 50.0, "efd": 9200, "visa": 0},
    "FR": {"tfi": 43.2, "cultural_distance": 54.0, "efd": 9800, "visa": 0},
    "RU": {"tfi": 68.5, "cultural_distance": 60.0, "efd": 7500, "visa": 80},
    "BR": {"tfi": 48.0, "cultural_distance": 58.0, "efd": 18500, "visa": 0},
}

# ---------------------------------------------------------------------------
# EFD 正規化用の定数
# ---------------------------------------------------------------------------
_EFD_MIN_LOG = math.log(800)    # 最小EFD（ソウル直行）
_EFD_MAX_LOG = math.log(20000)  # 最大EFD（南米経由便）

# ---------------------------------------------------------------------------
# 文化距離の正規化上限 (0-100スケール想定、100が最大)
# ---------------------------------------------------------------------------
_CULTURAL_DIST_MAX = 100.0


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class TFIResult:
    """Travel Friction Index 計算結果"""
    source_country: str
    tfi: float                       # 0-100
    cultural_distance: float         # 生値
    effective_flight_distance: float  # km
    visa_barrier: int                # 0/15/50/80
    components: Dict[str, float]     # 各コンポーネントの寄与


# ===========================================================================
# メインクラス
# ===========================================================================
class TravelFrictionIndex:
    """
    Travel Friction Index — 渡航摩擦指数

    TFI = 0.40 × cultural_norm + 0.40 × efd_norm + 0.20 × visa_norm

    各コンポーネント:
      - cultural_norm: 文化距離 / 100 × 100 → 0-100
      - efd_norm: (log(EFD) - log_min) / (log_max - log_min) × 100 → 0-100
      - visa_norm: VISA_SCORES[country] → 0-100 (80が最大)
    """

    # 重み
    W_CULTURAL = 0.40
    W_EFD = 0.40
    W_VISA = 0.20

    def __init__(self) -> None:
        self._cultural_client = None
        self._efd_client = None
        self._load_clients()

    def _load_clients(self) -> None:
        """TASK1-2のクライアントをtry/exceptでロード"""
        try:
            from pipeline.tourism.cultural_distance_client import CulturalDistanceClient
            self._cultural_client = CulturalDistanceClient()
            logger.info("CulturalDistanceClient ロード成功")
        except (ImportError, ModuleNotFoundError, Exception) as e:
            logger.info("CulturalDistanceClient 未実装 → プリコンピュートにフォールバック: %s", e)
            self._cultural_client = None

        try:
            from pipeline.tourism.effective_distance_client import EffectiveFlightDistanceClient
            self._efd_client = EffectiveFlightDistanceClient()
            logger.info("EffectiveFlightDistanceClient ロード成功")
        except (ImportError, ModuleNotFoundError, Exception) as e:
            logger.info("EffectiveFlightDistanceClient 未実装 → プリコンピュートにフォールバック: %s", e)
            self._efd_client = None

    # -------------------------------------------------------------------
    def _get_cultural_distance(self, country: str) -> float:
        """文化距離を取得（クライアント or フォールバック）"""
        if self._cultural_client is not None:
            try:
                return self._cultural_client.get_distance("JP", country)
            except Exception as e:
                logger.debug("文化距離クライアントエラー: %s", e)
        # フォールバック
        pre = TFI_PRECOMPUTED.get(country)
        if pre:
            return pre["cultural_distance"]
        return 50.0  # 未知国デフォルト

    def _get_efd(self, country: str) -> float:
        """Effective Flight Distance を取得（クライアント or フォールバック）"""
        if self._efd_client is not None:
            try:
                return self._efd_client.get_distance("JP", country)
            except Exception as e:
                logger.debug("EFDクライアントエラー: %s", e)
        # フォールバック
        pre = TFI_PRECOMPUTED.get(country)
        if pre:
            return pre["efd"]
        return 8000.0  # 未知国デフォルト

    def _get_visa(self, country: str) -> int:
        """ビザ障壁スコア"""
        return VISA_SCORES.get(country, 50)

    # -------------------------------------------------------------------
    @staticmethod
    def _normalize_efd(efd_km: float) -> float:
        """EFDをlog正規化して0-100に変換"""
        log_efd = math.log(max(efd_km, 1.0))
        norm = (log_efd - _EFD_MIN_LOG) / (_EFD_MAX_LOG - _EFD_MIN_LOG)
        return max(0.0, min(100.0, norm * 100.0))

    @staticmethod
    def _normalize_cultural(dist: float) -> float:
        """文化距離を0-100に正規化"""
        return max(0.0, min(100.0, dist / _CULTURAL_DIST_MAX * 100.0))

    @staticmethod
    def _normalize_visa(visa_score: int) -> float:
        """ビザスコアを0-100に正規化（最大80→100にスケール）"""
        return max(0.0, min(100.0, visa_score / 80.0 * 100.0))

    # -------------------------------------------------------------------
    def calculate(self, source_country: str, normalize: bool = True) -> TFIResult:
        """
        指定国のTFIを計算。

        Args:
            source_country: ISO2コード (例: "KR", "CN")
            normalize: True=0-100にクリップ

        Returns:
            TFIResult
        """
        country = source_country.upper()

        cultural_dist = self._get_cultural_distance(country)
        efd = self._get_efd(country)
        visa = self._get_visa(country)

        # 正規化
        cultural_norm = self._normalize_cultural(cultural_dist)
        efd_norm = self._normalize_efd(efd)
        visa_norm = self._normalize_visa(visa)

        # 加重平均
        tfi = (self.W_CULTURAL * cultural_norm
               + self.W_EFD * efd_norm
               + self.W_VISA * visa_norm)

        if normalize:
            tfi = max(0.0, min(100.0, tfi))

        tfi = round(tfi, 2)

        return TFIResult(
            source_country=country,
            tfi=tfi,
            cultural_distance=cultural_dist,
            effective_flight_distance=efd,
            visa_barrier=visa,
            components={
                "cultural_norm": round(cultural_norm, 2),
                "efd_norm": round(efd_norm, 2),
                "visa_norm": round(visa_norm, 2),
                "w_cultural": self.W_CULTURAL,
                "w_efd": self.W_EFD,
                "w_visa": self.W_VISA,
            },
        )

    # -------------------------------------------------------------------
    def calculate_all_countries(self) -> Dict[str, TFIResult]:
        """全プリコンピュート国のTFIを計算"""
        results = {}
        for country in TFI_PRECOMPUTED:
            results[country] = self.calculate(country)
        return results

    # -------------------------------------------------------------------
    def get_expected_tfi_ranking(self) -> List[TFIResult]:
        """TFI昇順（摩擦が低い順）でランキング"""
        all_results = self.calculate_all_countries()
        ranked = sorted(all_results.values(), key=lambda r: r.tfi)
        return ranked
