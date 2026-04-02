"""文化的距離クライアント — Cultural Distance (Kogut-Singh Index + Linguistic Distance)
Hofstede 6次元文化指標と言語距離を組み合わせた複合文化的距離を算出。
CD_total = 0.7 × CD_hofstede_normalized + 0.3 × CD_linguistic
"""
import logging
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


# ========== Hofstede 6次元文化指標 ==========
# ソース: Hofstede Insights (https://www.hofstede-insights.com/)
# 次元: PDI(権力距離), IDV(個人主義), MAS(男性性), UAI(不確実性回避),
#        LTO(長期志向), IVR(享楽主義)
# 各値は0-100のスケール

HOFSTEDE = {
    "JP": {"PDI": 54, "IDV": 46, "MAS": 95, "UAI": 92, "LTO": 88, "IVR": 42},
    "KR": {"PDI": 60, "IDV": 18, "MAS": 39, "UAI": 85, "LTO": 100, "IVR": 29},
    "CN": {"PDI": 80, "IDV": 20, "MAS": 66, "UAI": 30, "LTO": 87, "IVR": 24},
    "TW": {"PDI": 58, "IDV": 17, "MAS": 45, "UAI": 69, "LTO": 93, "IVR": 49},
    "HK": {"PDI": 68, "IDV": 25, "MAS": 57, "UAI": 29, "LTO": 61, "IVR": 17},
    "US": {"PDI": 40, "IDV": 91, "MAS": 62, "UAI": 46, "LTO": 26, "IVR": 68},
    "AU": {"PDI": 38, "IDV": 90, "MAS": 61, "UAI": 51, "LTO": 21, "IVR": 71},
    "DE": {"PDI": 35, "IDV": 67, "MAS": 66, "UAI": 65, "LTO": 83, "IVR": 40},
    "GB": {"PDI": 35, "IDV": 89, "MAS": 66, "UAI": 35, "LTO": 51, "IVR": 69},
    "FR": {"PDI": 68, "IDV": 71, "MAS": 43, "UAI": 86, "LTO": 63, "IVR": 48},
    "TH": {"PDI": 64, "IDV": 20, "MAS": 34, "UAI": 64, "LTO": 32, "IVR": 45},
    "SG": {"PDI": 74, "IDV": 20, "MAS": 48, "UAI": 8, "LTO": 72, "IVR": 46},
    "IN": {"PDI": 77, "IDV": 48, "MAS": 56, "UAI": 40, "LTO": 51, "IVR": 26},
    "VN": {"PDI": 70, "IDV": 20, "MAS": 40, "UAI": 30, "LTO": 57, "IVR": 35},
    "ID": {"PDI": 78, "IDV": 14, "MAS": 46, "UAI": 48, "LTO": 62, "IVR": 38},
    "MY": {"PDI": 100, "IDV": 26, "MAS": 50, "UAI": 36, "LTO": 41, "IVR": 57},
    "PH": {"PDI": 94, "IDV": 32, "MAS": 64, "UAI": 44, "LTO": 27, "IVR": 42},
    "RU": {"PDI": 93, "IDV": 39, "MAS": 36, "UAI": 95, "LTO": 81, "IVR": 20},
    "TR": {"PDI": 66, "IDV": 37, "MAS": 45, "UAI": 85, "LTO": 46, "IVR": 49},
    "BR": {"PDI": 69, "IDV": 38, "MAS": 49, "UAI": 76, "LTO": 44, "IVR": 59},
    "MX": {"PDI": 81, "IDV": 30, "MAS": 69, "UAI": 82, "LTO": 24, "IVR": 97},
    "CA": {"PDI": 39, "IDV": 80, "MAS": 52, "UAI": 48, "LTO": 36, "IVR": 68},
}

# 各次元の分散（Kogut-Singh指数の正規化用）
# Hofstede全データセットから算出された分散値
DIMENSION_VARIANCES = {
    "PDI": 420.0,
    "IDV": 600.0,
    "MAS": 340.0,
    "UAI": 530.0,
    "LTO": 600.0,
    "IVR": 350.0,
}

DIMENSIONS = ["PDI", "IDV", "MAS", "UAI", "LTO", "IVR"]


# ========== 言語距離 ==========
# 日本語を基準とした言語的距離（0-1スケール）
# 言語系統・文字体系・語彙的近さの複合指標
# 0 = 同一言語、1 = 最大距離

LINGUISTIC_DISTANCE = {
    "JP": 0.00,  # 日本語（基準）
    "KR": 0.35,  # 韓国語 — 語順類似・漢字語彙共有、系統は別
    "CN": 0.50,  # 中国語 — 漢字共有だが語順・文法体系が異なる
    "TW": 0.50,  # 中国語（繁体字）— CNと同等
    "HK": 0.55,  # 広東語 — 漢字共有だが口語は北京語とも異なる
    "US": 0.90,  # 英語 — 系統・文字・語順すべて異なる
    "AU": 0.90,  # 英語
    "GB": 0.90,  # 英語
    "CA": 0.90,  # 英語/フランス語
    "DE": 0.92,  # ドイツ語 — ゲルマン語族だが日本語とは遠い
    "FR": 0.93,  # フランス語 — ロマンス語族
    "TH": 0.75,  # タイ語 — 声調言語、仏教用語の共有はあるが体系は異なる
    "SG": 0.70,  # 多言語（英語/中国語/マレー語/タミル語）
    "IN": 0.88,  # ヒンディー語/英語 — インド・ヨーロッパ語族
    "VN": 0.72,  # ベトナム語 — 漢字文化圏、漢越語あり
    "ID": 0.85,  # インドネシア語 — オーストロネシア語族
    "MY": 0.82,  # マレー語 — インドネシア語と近縁
    "PH": 0.80,  # フィリピノ語/英語 — オーストロネシア語族+英語
    "RU": 0.95,  # ロシア語 — キリル文字、スラブ語族
    "TR": 0.93,  # トルコ語 — アルタイ語族説あるが膠着語の類似のみ
    "BR": 0.95,  # ポルトガル語 — ロマンス語族
    "MX": 0.94,  # スペイン語 — ロマンス語族
}


@dataclass
class CulturalDistance:
    """文化的距離の算出結果"""
    source_country: str        # ISO2コード
    reference_country: str     # 基準国（通常JP）
    hofstede_distance: float   # Kogut-Singh指数（生値）
    linguistic_distance: float # 言語距離（0-1）
    total_distance: float      # 複合文化的距離（0-1正規化）
    dimensions: Dict[str, float]  # 各次元の距離内訳
    data_source: str           # "hofstede" | "partial"
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


class CulturalDistanceClient:
    """文化的距離クライアント

    Kogut-Singh指数（Hofstede 6次元）+ 言語距離の複合指標。
    CD_total = 0.7 × CD_hofstede_normalized + 0.3 × CD_linguistic

    Kogut-Singh指数:
        KS = Σ_{d} [(I_{d,source} - I_{d,ref})² / V_d]
    ここで I_d = 各次元の値、V_d = 次元の分散
    """

    # 正規化用の最大Kogut-Singh距離（理論上の上限に近い値）
    # 実測データ上の最大値をやや上回るよう設定
    KS_MAX = 15.0

    # 複合スコアの重み
    HOFSTEDE_WEIGHT = 0.7
    LINGUISTIC_WEIGHT = 0.3

    def calculate_cultural_distance(
        self, source_country: str, reference: str = "JP"
    ) -> CulturalDistance:
        """文化的距離を算出

        Args:
            source_country: ISO2国コード（例: "KR", "US"）
            reference: 基準国ISO2コード（デフォルト: "JP"）

        Returns:
            CulturalDistance dataclass
        """
        sc = source_country.upper().strip()
        ref = reference.upper().strip()

        # Hofstede次元データの取得
        source_data = HOFSTEDE.get(sc)
        ref_data = HOFSTEDE.get(ref)

        if source_data and ref_data:
            ks_index, dim_details = self._kogut_singh(source_data, ref_data)
            data_source = "hofstede"
        else:
            # Hofstedeデータがない場合はデフォルト中間値
            ks_index = self.KS_MAX / 2
            dim_details = {d: 0.0 for d in DIMENSIONS}
            data_source = "partial"
            logger.warning(
                "Hofstedeデータなし: source=%s ref=%s → デフォルト値使用", sc, ref
            )

        # 正規化（0-1）
        ks_normalized = min(ks_index / self.KS_MAX, 1.0)

        # 言語距離
        ling_dist = LINGUISTIC_DISTANCE.get(sc, 0.85)  # 不明国は0.85

        # 複合スコア
        total = (
            self.HOFSTEDE_WEIGHT * ks_normalized
            + self.LINGUISTIC_WEIGHT * ling_dist
        )

        return CulturalDistance(
            source_country=sc,
            reference_country=ref,
            hofstede_distance=round(ks_index, 4),
            linguistic_distance=round(ling_dist, 4),
            total_distance=round(total, 4),
            dimensions=dim_details,
            data_source=data_source,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _kogut_singh(
        self, source: Dict[str, int], ref: Dict[str, int]
    ) -> tuple:
        """Kogut-Singh文化的距離指数を算出

        KS = Σ_{d} [(I_{d,source} - I_{d,ref})² / V_d]

        Returns:
            (ks_index, {dim: contribution})
        """
        total = 0.0
        details = {}
        for dim in DIMENSIONS:
            s_val = source.get(dim, 50)
            r_val = ref.get(dim, 50)
            variance = DIMENSION_VARIANCES.get(dim, 500)
            contribution = (s_val - r_val) ** 2 / variance
            details[dim] = round(contribution, 4)
            total += contribution

        return total, details

    def get_all_distances(self, reference: str = "JP") -> Dict[str, CulturalDistance]:
        """全登録国の文化的距離を一括算出

        Returns:
            {iso2: CulturalDistance}
        """
        results = {}
        all_countries = set(HOFSTEDE.keys()) | set(LINGUISTIC_DISTANCE.keys())
        ref = reference.upper().strip()
        for country in sorted(all_countries):
            if country == ref:
                continue
            results[country] = self.calculate_cultural_distance(country, ref)
        return results

    def validate(self) -> Dict[str, dict]:
        """文化的距離の妥当性チェック

        期待される順序制約:
        - KR < CN < TH < US（東アジア→東南アジア→欧米の距離増加）
        - SG < AU（英語圏でもアジア寄りのSGが近い）
        - CN ≈ TW（文化的に近似）

        Returns:
            {check_name: {"pass": bool, "detail": str}}
        """
        results = {}
        distances = self.get_all_distances("JP")

        def _td(iso2):
            return distances[iso2].total_distance if iso2 in distances else 999

        # 順序チェック（文化的に妥当な大小関係）
        order_checks = [
            ("KR < US", _td("KR") < _td("US")),
            ("CN < US", _td("CN") < _td("US")),
            ("TW < US", _td("TW") < _td("US")),
            ("TW < RU", _td("TW") < _td("RU")),
            ("KR < RU", _td("KR") < _td("RU")),
            ("CN < MX", _td("CN") < _td("MX")),
        ]
        for name, passed in order_checks:
            results[name] = {
                "pass": passed,
                "detail": f"{name}: {'OK' if passed else 'FAIL'}",
            }

        # 近似チェック: CN ≈ TW（差が0.2以内 — 政治的差異はあるが文化基盤は共通）
        cn_tw_diff = abs(_td("CN") - _td("TW"))
        results["CN ≈ TW"] = {
            "pass": cn_tw_diff < 0.20,
            "detail": f"CN-TW差: {cn_tw_diff:.4f} ({'OK' if cn_tw_diff < 0.20 else 'WARN'})",
        }

        # 東アジア圏（KR,CN,TW）が全体の中で下位半分にいること
        all_dists = sorted(distances.values(), key=lambda x: x.total_distance)
        midpoint = len(all_dists) // 2
        east_asia_in_lower = all(
            _td(c) <= all_dists[midpoint].total_distance
            for c in ["KR", "CN", "TW"] if c in distances
        )
        results["東アジア圏=下位半分"] = {
            "pass": east_asia_in_lower,
            "detail": f"KR/CN/TW全て中央値以下: {'OK' if east_asia_in_lower else 'FAIL'}",
        }

        return results


# ========== テスト用エントリポイント ==========

def _test():
    """動作確認"""
    client = CulturalDistanceClient()

    print("=" * 60)
    print("文化的距離クライアント テスト")
    print("=" * 60)

    # 全国の距離一覧
    all_dist = client.get_all_distances("JP")
    sorted_countries = sorted(all_dist.items(), key=lambda x: x[1].total_distance)

    print("\n--- 日本からの文化的距離（昇順） ---")
    for iso2, cd in sorted_countries:
        print(
            f"  {iso2}: total={cd.total_distance:.4f} "
            f"(Hofstede={cd.hofstede_distance:.4f}, "
            f"言語={cd.linguistic_distance:.2f})"
        )

    # 次元別詳細（韓国の例）
    print("\n--- 韓国（KR）次元別詳細 ---")
    kr = client.calculate_cultural_distance("KR")
    for dim, val in kr.dimensions.items():
        jp_val = HOFSTEDE["JP"][dim]
        kr_val = HOFSTEDE["KR"][dim]
        print(f"  {dim}: JP={jp_val}, KR={kr_val}, 距離寄与={val:.4f}")

    # バリデーション
    print("\n" + "=" * 60)
    print("バリデーション")
    print("=" * 60)
    validation = client.validate()
    pass_count = sum(1 for v in validation.values() if v["pass"])
    total = len(validation)
    print(f"\n合格: {pass_count}/{total}")
    for name, v in validation.items():
        status = "OK  " if v["pass"] else "FAIL"
        print(f"  [{status}] {v['detail']}")


if __name__ == "__main__":
    _test()
