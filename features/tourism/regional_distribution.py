"""
features/tourism/regional_distribution.py
日本国内インバウンド地域分散モデル — SCRI v1.3.0

日本全体のインバウンド予測を都道府県・地域レベルに分散させる。
Step 2モデル: 日本全体インバウンド × 地域シェア = 都道府県別来訪者数

データソース:
  - 観光庁「宿泊旅行統計調査」— 外国人延べ宿泊者数（都道府県別）
  - 法務省「出入国管理統計」— 空港・港湾別入国者数
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 47都道府県リスト（JIS X 0401 順）
# ---------------------------------------------------------------------------
ALL_PREFECTURES = [
    "Hokkaido", "Aomori", "Iwate", "Miyagi", "Akita", "Yamagata", "Fukushima",
    "Ibaraki", "Tochigi", "Gunma", "Saitama", "Chiba", "Tokyo", "Kanagawa",
    "Niigata", "Toyama", "Ishikawa", "Fukui", "Yamanashi", "Nagano",
    "Gifu", "Shizuoka", "Aichi", "Mie",
    "Shiga", "Kyoto", "Osaka", "Hyogo", "Nara", "Wakayama",
    "Tottori", "Shimane", "Okayama", "Hiroshima", "Yamaguchi",
    "Tokushima", "Kagawa", "Ehime", "Kochi",
    "Fukuoka", "Saga", "Nagasaki", "Kumamoto", "Oita", "Miyazaki", "Kagoshima",
    "Okinawa",
]
assert len(ALL_PREFECTURES) == 47

# ---------------------------------------------------------------------------
# 都道府県別シェア（2024年実績ベース概算）
# 主要20都道府県を明示し、残り27県は均等配分
# ---------------------------------------------------------------------------
_MAJOR_SHARES: Dict[str, float] = {
    "Tokyo":     0.285,
    "Osaka":     0.165,
    "Kyoto":     0.078,
    "Hokkaido":  0.055,
    "Chiba":     0.048,
    "Fukuoka":   0.042,
    "Aichi":     0.035,
    "Okinawa":   0.032,
    "Kanagawa":  0.028,
    "Hiroshima": 0.018,
    "Hyogo":     0.016,
    "Nara":      0.014,
    "Nagano":    0.013,
    "Shizuoka":  0.012,
    "Niigata":   0.010,
    "Miyagi":    0.009,
    "Kumamoto":  0.008,
    "Kagoshima": 0.007,
    "Ishikawa":  0.007,
    "Toyama":    0.005,
}

# 残り27県に割り当てる合計シェア
_REMAINING_TOTAL = round(1.0 - sum(_MAJOR_SHARES.values()), 10)
_MINOR_PREFECTURES = [p for p in ALL_PREFECTURES if p not in _MAJOR_SHARES]
_MINOR_SHARE_EACH = _REMAINING_TOTAL / len(_MINOR_PREFECTURES)

PREFECTURE_SHARES: Dict[str, float] = {}
for _p in ALL_PREFECTURES:
    PREFECTURE_SHARES[_p] = _MAJOR_SHARES.get(_p, _MINOR_SHARE_EACH)

# 合計検証
assert abs(sum(PREFECTURE_SHARES.values()) - 1.0) < 1e-9, \
    f"PREFECTURE_SHARES 合計が 1.0 でない: {sum(PREFECTURE_SHARES.values())}"

# ---------------------------------------------------------------------------
# 国籍バイアス（source_country → 都道府県別の加算調整値）
# "rural" は主要20都道府県以外の全県に均等配分
# ---------------------------------------------------------------------------
NATIONALITY_BIAS: Dict[str, Dict[str, float]] = {
    "CHN": {"Osaka": +0.04, "Tokyo": +0.02, "Hokkaido": +0.01, "rural": -0.07},
    "KOR": {"Osaka": +0.03, "Fukuoka": +0.04, "Okinawa": +0.02, "rural": -0.03},
    "TWN": {"Osaka": +0.02, "Hokkaido": +0.03, "Okinawa": +0.02, "rural": -0.02},
    "USA": {"Kyoto": +0.03, "Hiroshima": +0.02, "rural": +0.04, "Tokyo": -0.03},
    "AUS": {"Hokkaido": +0.05, "Nagano": +0.03, "Niigata": +0.02, "rural": +0.02},
    "THA": {"Osaka": +0.02, "Hokkaido": +0.03, "rural": -0.02},
}

# ---------------------------------------------------------------------------
# 季節バイアス
# ---------------------------------------------------------------------------
SEASONAL_BIAS: Dict[str, Dict[str, float]] = {
    "spring_peak": {"Kyoto": +0.04, "Tokyo": +0.02, "Nara": +0.01},        # 桜シーズン
    "autumn":      {"Kyoto": +0.05, "Tochigi": +0.02, "Kanagawa": +0.01},  # 紅葉（日光→栃木、箱根→神奈川）
    "winter_ski":  {"Hokkaido": +0.08, "Nagano": +0.04, "Niigata": +0.03}, # スキーシーズン
    "summer":      {"Okinawa": +0.04, "Hokkaido": +0.03},                   # 避暑
}

# ---------------------------------------------------------------------------
# 入国空港・港湾別シェア
# ---------------------------------------------------------------------------
PORT_OF_ENTRY_SHARES: Dict[str, float] = {
    "NRT": 0.28,   # 成田国際空港
    "HND": 0.22,   # 羽田空港
    "KIX": 0.20,   # 関西国際空港
    "CTS": 0.07,   # 新千歳空港
    "FUK": 0.08,   # 福岡空港
    "NGO": 0.05,   # 中部国際空港
    "OKA": 0.04,   # 那覇空港
    "other": 0.06, # その他
}

# ---------------------------------------------------------------------------
# 空港→初訪問地域の関連（空港から最初に訪れる都道府県の確率分布）
# ---------------------------------------------------------------------------
_PORT_TO_REGION: Dict[str, Dict[str, float]] = {
    "NRT": {"Tokyo": 0.55, "Chiba": 0.15, "Kanagawa": 0.10, "Saitama": 0.05},
    "HND": {"Tokyo": 0.65, "Kanagawa": 0.15, "Chiba": 0.05},
    "KIX": {"Osaka": 0.50, "Kyoto": 0.25, "Nara": 0.08, "Hyogo": 0.07},
    "CTS": {"Hokkaido": 0.90},
    "FUK": {"Fukuoka": 0.60, "Kumamoto": 0.10, "Oita": 0.08, "Nagasaki": 0.07},
    "NGO": {"Aichi": 0.50, "Gifu": 0.15, "Mie": 0.10, "Shizuoka": 0.08},
    "OKA": {"Okinawa": 0.92},
}

# ---------------------------------------------------------------------------
# 宿泊施設キャパシティ制約（月別稼働率の目安）
# ---------------------------------------------------------------------------
_CAPACITY_PROFILES: Dict[str, Dict[str, float]] = {
    # 都道府県: {月(文字列): 稼働率}  — 主要都道府県のみ定義
    "Tokyo": {str(m): 0.85 for m in range(1, 13)},
    "Osaka": {str(m): 0.82 for m in range(1, 13)},
    "Kyoto": {
        "1": 0.70, "2": 0.65, "3": 0.82, "4": 0.95, "5": 0.80,
        "6": 0.68, "7": 0.75, "8": 0.78, "9": 0.72, "10": 0.88,
        "11": 0.93, "12": 0.72,
    },
    "Hokkaido": {
        "1": 0.85, "2": 0.88, "3": 0.75, "4": 0.60, "5": 0.65,
        "6": 0.62, "7": 0.80, "8": 0.85, "9": 0.70, "10": 0.68,
        "11": 0.60, "12": 0.80,
    },
    "Okinawa": {
        "1": 0.60, "2": 0.62, "3": 0.72, "4": 0.68, "5": 0.65,
        "6": 0.58, "7": 0.88, "8": 0.90, "9": 0.75, "10": 0.70,
        "11": 0.65, "12": 0.60,
    },
    "Fukuoka": {str(m): 0.75 for m in range(1, 13)},
    "Nagano": {
        "1": 0.82, "2": 0.85, "3": 0.70, "4": 0.55, "5": 0.60,
        "6": 0.50, "7": 0.72, "8": 0.78, "9": 0.60, "10": 0.65,
        "11": 0.58, "12": 0.78,
    },
}

# ---------------------------------------------------------------------------
# 月 → 季節マッピング（自動季節判定用）
# ---------------------------------------------------------------------------
_MONTH_TO_SEASON: Dict[int, str] = {
    1: "winter_ski", 2: "winter_ski", 3: "spring_peak",
    4: "spring_peak", 5: "", 6: "summer",
    7: "summer", 8: "summer", 9: "",
    10: "autumn", 11: "autumn", 12: "winter_ski",
}


def _normalize_shares(shares: Dict[str, float]) -> Dict[str, float]:
    """シェアを正規化して合計1.0にする。負値はゼロにクランプ。"""
    # 負値クランプ
    clamped = {k: max(v, 0.0) for k, v in shares.items()}
    total = sum(clamped.values())
    if total <= 0:
        # フォールバック: 均等配分
        n = len(clamped)
        return {k: 1.0 / n for k in clamped}
    return {k: v / total for k, v in clamped.items()}


def _distribute_with_remainder(total: int, shares: Dict[str, float]) -> Dict[str, int]:
    """
    整数分配（最大剰余法）。合計が total と一致することを保証。
    """
    raw = {k: total * v for k, v in shares.items()}
    floored = {k: int(math.floor(v)) for k, v in raw.items()}
    remainder = total - sum(floored.values())

    # 剰余の大きい順にソートして1ずつ配分
    fractional = {k: raw[k] - floored[k] for k in raw}
    sorted_keys = sorted(fractional, key=lambda k: fractional[k], reverse=True)
    for i in range(remainder):
        floored[sorted_keys[i]] += 1

    assert sum(floored.values()) == total, \
        f"分配合計不一致: {sum(floored.values())} != {total}"
    return floored


# ===========================================================================
# メインクラス
# ===========================================================================
class RegionalDistributionModel:
    """
    日本国内インバウンド地域分散モデル

    日本全体のインバウンド予測値を都道府県別に分配する。
    国籍バイアス・季節バイアス・入国空港情報を加味して
    より現実的な地域分散を推定する。
    """

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        logger.info("RegionalDistributionModel 初期化完了")

    # -----------------------------------------------------------------------
    # データ取得: 宿泊旅行統計
    # -----------------------------------------------------------------------
    def get_accommodation_stats(
        self,
        year: int,
        month: int,
        prefecture: str = "",
    ) -> List[Dict[str, Any]]:
        """
        観光庁「宿泊旅行統計調査」から外国人延べ宿泊者数を取得。

        Args:
            year: 対象年（例: 2024）
            month: 対象月（1-12）
            prefecture: 都道府県名（空文字なら全都道府県）

        Returns:
            [{"prefecture": str, "foreign_guests": int, "year": int, "month": int}, ...]

        Note:
            現時点ではe-Stat APIへの接続は未実装。
            ハードコードのシェアからの推計値を返す。
        """
        # TODO: e-Stat API (https://api.e-stat.go.jp/) 接続実装
        #   - 統計表ID: 宿泊旅行統計調査 → 外国人延べ宿泊者数（都道府県別）
        #   - appId が必要（無料登録で取得可能）
        logger.debug(f"宿泊統計取得: {year}/{month:02d} prefecture={prefecture}")

        # 仮推計: 日本全体の月間外国人宿泊者数（概算3000万/年 ÷ 12 ≈ 250万/月）
        # 季節変動を加味
        seasonal_factor = {
            1: 0.85, 2: 0.80, 3: 1.05, 4: 1.15, 5: 1.00, 6: 0.90,
            7: 1.05, 8: 1.10, 9: 0.95, 10: 1.10, 11: 1.05, 12: 0.90,
        }
        base_monthly = 2_500_000
        total_guests = int(base_monthly * seasonal_factor.get(month, 1.0))

        results = []
        if prefecture:
            share = PREFECTURE_SHARES.get(prefecture, _MINOR_SHARE_EACH)
            results.append({
                "prefecture": prefecture,
                "foreign_guests": int(total_guests * share),
                "year": year,
                "month": month,
                "source": "estimated",
            })
        else:
            for pref in ALL_PREFECTURES:
                share = PREFECTURE_SHARES[pref]
                results.append({
                    "prefecture": pref,
                    "foreign_guests": int(total_guests * share),
                    "year": year,
                    "month": month,
                    "source": "estimated",
                })

        return results

    # -----------------------------------------------------------------------
    # データ取得: 入国管理統計
    # -----------------------------------------------------------------------
    def get_port_of_entry_stats(
        self,
        year: int,
        month: int,
    ) -> List[Dict[str, Any]]:
        """
        法務省「出入国管理統計」から空港・港湾別入国者数を取得。

        Args:
            year: 対象年
            month: 対象月

        Returns:
            [{"port_code": str, "port_name": str, "arrivals": int, ...}, ...]

        Note:
            現時点ではe-Stat APIへの接続は未実装。
            ハードコードのシェアからの推計値を返す。
        """
        # TODO: e-Stat API 接続実装
        #   - 出入国管理統計 → 空港・港湾別外国人入国者数
        logger.debug(f"入国統計取得: {year}/{month:02d}")

        # 仮推計: 月間入国者数（年間3600万想定 ÷ 12 = 300万/月）
        base_monthly = 3_000_000
        port_names = {
            "NRT": "成田国際空港",
            "HND": "東京国際空港（羽田）",
            "KIX": "関西国際空港",
            "CTS": "新千歳空港",
            "FUK": "福岡空港",
            "NGO": "中部国際空港（セントレア）",
            "OKA": "那覇空港",
            "other": "その他",
        }

        results = []
        for code, share in PORT_OF_ENTRY_SHARES.items():
            results.append({
                "port_code": code,
                "port_name": port_names.get(code, code),
                "arrivals": int(base_monthly * share),
                "share": share,
                "year": year,
                "month": month,
                "source": "estimated",
            })

        return results

    # -----------------------------------------------------------------------
    # 動的シェア計算（過去データがある場合のリバランス用）
    # -----------------------------------------------------------------------
    def calculate_regional_shares(
        self,
        year: Optional[int] = None,
        months_back: int = 12,
    ) -> Dict[str, float]:
        """
        過去N か月の宿泊統計からシェアを再計算する。

        現時点ではe-Stat未接続のため、ハードコードシェアを返す。
        将来的にはリアルタイム更新に対応。

        Args:
            year: 基準年（Noneなら現在年）
            months_back: 遡る月数

        Returns:
            {都道府県名: シェア(0-1)} — 合計1.0
        """
        if year is None:
            year = datetime.now().year

        cache_key = f"shares_{year}_{months_back}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # TODO: e-Stat接続後は実データから集計
        #   各月の get_accommodation_stats() を集計して
        #   都道府県ごとの宿泊者数合計からシェアを再計算する
        logger.info(
            f"地域シェア計算（ハードコード値を使用）: "
            f"基準年={year}, 遡及={months_back}ヶ月"
        )

        shares = dict(PREFECTURE_SHARES)
        self._cache[cache_key] = shares
        return shares

    # -----------------------------------------------------------------------
    # コア: 地域分散予測
    # -----------------------------------------------------------------------
    def predict_regional_distribution(
        self,
        total_forecast: int,
        source_country: str = "",
        season: str = "",
        month: Optional[int] = None,
        port_of_entry: str = "",
    ) -> Dict[str, Any]:
        """
        日本全体のインバウンド予測を都道府県別に分配する。

        Args:
            total_forecast: 日本全体の入国者数予測（整数）
            source_country: ISO 3166-1 alpha-3 国コード（例: "CHN", "KOR"）
            season: 季節キー（"spring_peak", "autumn", "winter_ski", "summer"）
                    空文字の場合は month から自動判定
            month: 月（1-12）— season 未指定時の自動判定に使用
            port_of_entry: 空港コード（"NRT" 等）— 追加の地域バイアス

        Returns:
            {
                "total": int,
                "distribution": {都道府県: 人数, ...},
                "shares": {都道府県: シェア(0-1), ...},
                "adjustments_applied": [str, ...],
                "metadata": {...},
            }
        """
        if total_forecast <= 0:
            return {
                "total": 0,
                "distribution": {p: 0 for p in ALL_PREFECTURES},
                "shares": dict(PREFECTURE_SHARES),
                "adjustments_applied": [],
                "metadata": {"warning": "total_forecast が 0 以下"},
            }

        adjustments_applied = []

        # Step 1: ベースシェア
        adjusted = dict(PREFECTURE_SHARES)

        # Step 2: 季節自動判定
        effective_season = season
        if not effective_season and month:
            effective_season = _MONTH_TO_SEASON.get(month, "")
            if effective_season:
                adjustments_applied.append(f"season_auto:{effective_season}(month={month})")

        # Step 3: 国籍バイアス適用
        if source_country and source_country.upper() in NATIONALITY_BIAS:
            bias = NATIONALITY_BIAS[source_country.upper()]
            rural_adj = bias.get("rural", 0.0)
            rural_per_pref = rural_adj / len(_MINOR_PREFECTURES) if _MINOR_PREFECTURES else 0.0

            for pref in ALL_PREFECTURES:
                if pref in bias and pref != "rural":
                    adjusted[pref] += bias[pref]
                elif pref in _MINOR_PREFECTURES and rural_adj != 0.0:
                    adjusted[pref] += rural_per_pref

            adjustments_applied.append(f"nationality:{source_country.upper()}")

        # Step 4: 季節バイアス適用
        if effective_season and effective_season in SEASONAL_BIAS:
            bias = SEASONAL_BIAS[effective_season]
            for pref, adj in bias.items():
                if pref in adjusted:
                    adjusted[pref] += adj
            adjustments_applied.append(f"season:{effective_season}")

        # Step 5: 入国空港バイアス（軽微な補正 — 空港の影響は重み 0.1 で混合）
        if port_of_entry and port_of_entry.upper() in _PORT_TO_REGION:
            port_bias = _PORT_TO_REGION[port_of_entry.upper()]
            port_weight = 0.10  # 空港情報の影響度
            for pref, port_share in port_bias.items():
                if pref in adjusted:
                    # 空港に近い都道府県のシェアを少し引き上げ
                    adjusted[pref] += port_share * port_weight
            adjustments_applied.append(f"port:{port_of_entry.upper()}")

        # Step 6: 正規化（合計1.0、負値クランプ）
        normalized = _normalize_shares(adjusted)

        # Step 7: 整数分配（最大剰余法で端数処理、合計一致保証）
        distribution = _distribute_with_remainder(total_forecast, normalized)

        return {
            "total": total_forecast,
            "distribution": distribution,
            "shares": normalized,
            "adjustments_applied": adjustments_applied,
            "metadata": {
                "source_country": source_country,
                "season": effective_season,
                "month": month,
                "port_of_entry": port_of_entry,
                "num_prefectures": len(distribution),
                "top5": sorted(
                    distribution.items(), key=lambda x: x[1], reverse=True
                )[:5],
            },
        }

    # -----------------------------------------------------------------------
    # キャパシティ制約チェック
    # -----------------------------------------------------------------------
    def get_capacity_constraint(
        self,
        prefecture: str,
        month: int,
    ) -> Dict[str, Any]:
        """
        指定都道府県・月の宿泊施設稼働率に基づくキャパシティ制約を返す。

        Args:
            prefecture: 都道府県名
            month: 月（1-12）

        Returns:
            {
                "prefecture": str,
                "month": int,
                "occupancy_rate": float,
                "status": "CAPACITY_LIMIT" | "HIGH_UTILIZATION" | "NORMAL",
                "description": str,
            }
        """
        profile = _CAPACITY_PROFILES.get(prefecture)
        if profile is None:
            # 定義がない都道府県はデフォルト稼働率 0.60
            occupancy = 0.60
        else:
            occupancy = profile.get(str(month), 0.65)

        if occupancy >= 0.95:
            status = "CAPACITY_LIMIT"
            desc = (
                f"{prefecture} は {month}月の宿泊施設稼働率が "
                f"{occupancy:.0%} で実質的な受入上限に達している。"
                f"追加の観光客受入は困難。"
            )
        elif occupancy >= 0.85:
            status = "HIGH_UTILIZATION"
            desc = (
                f"{prefecture} は {month}月の稼働率が {occupancy:.0%} で高水準。"
                f"急増時にはオーバーツーリズムリスクあり。"
            )
        else:
            status = "NORMAL"
            desc = (
                f"{prefecture} は {month}月の稼働率 {occupancy:.0%} で "
                f"受入余力あり。"
            )

        return {
            "prefecture": prefecture,
            "month": month,
            "occupancy_rate": occupancy,
            "status": status,
            "description": desc,
        }

    # -----------------------------------------------------------------------
    # 一括キャパシティチェック（分配結果と突き合わせ）
    # -----------------------------------------------------------------------
    def check_capacity_all(
        self,
        distribution: Dict[str, int],
        month: int,
    ) -> List[Dict[str, Any]]:
        """
        分配結果の全都道府県についてキャパシティ制約をチェック。

        Args:
            distribution: {都道府県: 人数} — predict_regional_distribution の出力
            month: 対象月

        Returns:
            キャパシティ問題がある都道府県のリスト
        """
        alerts = []
        for pref, count in distribution.items():
            if count <= 0:
                continue
            constraint = self.get_capacity_constraint(pref, month)
            if constraint["status"] != "NORMAL":
                constraint["forecast_visitors"] = count
                alerts.append(constraint)

        # 深刻度順にソート
        severity = {"CAPACITY_LIMIT": 0, "HIGH_UTILIZATION": 1}
        alerts.sort(key=lambda x: (severity.get(x["status"], 2), -x["forecast_visitors"]))
        return alerts

    # -----------------------------------------------------------------------
    # ユーティリティ: 季節判定
    # -----------------------------------------------------------------------
    @staticmethod
    def get_season_for_month(month: int) -> str:
        """月から季節キーを返す。"""
        return _MONTH_TO_SEASON.get(month, "")

    # -----------------------------------------------------------------------
    # ユーティリティ: 入国空港から初訪問地域の推定
    # -----------------------------------------------------------------------
    @staticmethod
    def get_likely_first_region(port_code: str) -> Dict[str, float]:
        """空港コードから初訪問地域の確率分布を返す。"""
        return dict(_PORT_TO_REGION.get(port_code.upper(), {}))
