"""資本フローリスク データクライアント
3つのデータソースを統合して資本規制リスクを評価:
  1. Chinn-Ito Index（資本勘定開放度）
  2. IMF AREAER指標（二値規制フラグ）
  3. SWIFT除外リスク（制裁連携）
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Chinn-Ito Index（資本勘定開放度）
#    -2.5（完全規制）〜 2.5（完全開放）
#    最新公開データ（2022年版）に基づくハードコード
# ---------------------------------------------------------------------------
CHINN_ITO_SCORES: dict = {
    # 完全開放（2.39）
    "USA": 2.39, "GBR": 2.39, "DEU": 2.39, "JPN": 2.39, "SGP": 2.39,
    "FRA": 2.39, "CAN": 2.39, "AUS": 2.39, "MEX": 2.39, "ARE": 2.39,
    "NLD": 2.39, "CHE": 2.39, "ITA": 2.39, "ESP": 2.39, "IRL": 2.39,
    "NZL": 2.39, "DNK": 2.39, "SWE": 2.39, "NOR": 2.39, "FIN": 2.39,
    # 高開放（1.0〜2.38）
    "TWN": 1.18, "SAU": 1.18, "ISR": 1.18, "CHL": 1.18, "POL": 1.18,
    "QAT": 1.18, "BHR": 1.18, "KWT": 1.18,
    # 中程度（0.0〜0.99）
    "KOR": 0.72, "IDN": 0.72, "PER": 0.72, "COL": 0.72,
    "THA": 0.08, "GHA": 0.08, "KEN": 0.08,
    # やや規制的（-0.5〜-0.01）
    "MYS": -0.08, "ZAF": -0.08, "PHL": -0.08, "PAK": -0.08,
    "BRA": -0.56, "TUR": -0.56, "ARG": -0.56,
    # 規制的（-1.0〜-1.5）
    "CHN": -1.19, "IND": -1.19, "RUS": -1.19, "VNM": -1.19,
    "NGA": -1.19, "EGY": -1.19, "BGD": -1.19, "UKR": -1.19,
    "MMR": -1.19, "LKA": -1.19, "ETH": -1.19,
    # 強い規制（-1.5〜-2.5）
    "IRN": -1.87, "PRK": -1.87, "VEN": -1.87, "CUB": -1.87,
    "SYR": -1.87, "SDN": -1.87, "SSD": -1.87, "LBY": -1.87,
}

# ---------------------------------------------------------------------------
# 2. IMF AREAER指標（規制有無の二値フラグ）
#    capital_account_open: 資本勘定が開放されているか
#    current_account_restrict: 経常勘定に制限があるか
#    multiple_exchange_rates: 多重為替レート制度か
#    remittance_restrict: 送金制限があるか
# ---------------------------------------------------------------------------
IMF_RESTRICTIONS: dict = {
    # 先進国（概ね規制なし）
    "USA": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "GBR": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "DEU": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "JPN": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "FRA": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "CAN": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "AUS": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "SGP": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "NLD": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "CHE": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "ITA": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "ESP": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "KOR": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "TWN": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "ISR": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "NZL": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    # 中程度の規制
    "CHN": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": False, "remittance_restrict": True},
    "IND": {"capital_account_open": False, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": True},
    "BRA": {"capital_account_open": False, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "MEX": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "IDN": {"capital_account_open": False, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "THA": {"capital_account_open": False, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "MYS": {"capital_account_open": False, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": True},
    "PHL": {"capital_account_open": False, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "VNM": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": False, "remittance_restrict": True},
    "TUR": {"capital_account_open": False, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "ZAF": {"capital_account_open": False, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "SAU": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "ARE": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "EGY": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "NGA": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "ARG": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "COL": {"capital_account_open": False, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "CHL": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "POL": {"capital_account_open": True, "current_account_restrict": False, "multiple_exchange_rates": False, "remittance_restrict": False},
    "UKR": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "PAK": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": False, "remittance_restrict": True},
    "BGD": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": False, "remittance_restrict": True},
    "MMR": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "ETH": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "LKA": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": False, "remittance_restrict": True},
    # 高規制国
    "RUS": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "IRN": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "PRK": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "VEN": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "CUB": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "SYR": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "SDN": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "SSD": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
    "LBY": {"capital_account_open": False, "current_account_restrict": True, "multiple_exchange_rates": True, "remittance_restrict": True},
}

# ---------------------------------------------------------------------------
# 3. SWIFT除外リスク
#    国際送金網から実質排除されている国
# ---------------------------------------------------------------------------
SWIFT_EXCLUDED: set = {"RUS", "IRN", "PRK", "CUB", "SYR", "VEN"}

# ---------------------------------------------------------------------------
# 国名→ISO3マッピング（ロケーション文字列の解決用）
# ---------------------------------------------------------------------------
COUNTRY_TO_ISO3: dict = {
    "united states": "USA", "usa": "USA", "us": "USA",
    "united kingdom": "GBR", "uk": "GBR", "gbr": "GBR",
    "germany": "DEU", "deu": "DEU",
    "japan": "JPN", "jp": "JPN", "jpn": "JPN",
    "singapore": "SGP", "sgp": "SGP",
    "france": "FRA", "fra": "FRA",
    "canada": "CAN", "can": "CAN",
    "australia": "AUS", "aus": "AUS",
    "south korea": "KOR", "korea": "KOR", "kor": "KOR",
    "taiwan": "TWN", "twn": "TWN",
    "china": "CHN", "chn": "CHN",
    "india": "IND", "ind": "IND",
    "thailand": "THA", "tha": "THA",
    "malaysia": "MYS", "mys": "MYS",
    "vietnam": "VNM", "vnm": "VNM",
    "indonesia": "IDN", "idn": "IDN",
    "philippines": "PHL", "phl": "PHL",
    "brazil": "BRA", "bra": "BRA",
    "mexico": "MEX", "mex": "MEX",
    "turkey": "TUR", "tur": "TUR",
    "russia": "RUS", "rus": "RUS",
    "iran": "IRN", "irn": "IRN",
    "north korea": "PRK", "dprk": "PRK", "prk": "PRK",
    "venezuela": "VEN", "ven": "VEN",
    "cuba": "CUB", "cub": "CUB",
    "south africa": "ZAF", "zaf": "ZAF",
    "nigeria": "NGA", "nga": "NGA",
    "egypt": "EGY", "egy": "EGY",
    "saudi arabia": "SAU", "sau": "SAU",
    "uae": "ARE", "united arab emirates": "ARE", "are": "ARE",
    "netherlands": "NLD", "nld": "NLD",
    "switzerland": "CHE", "che": "CHE",
    "italy": "ITA", "ita": "ITA",
    "spain": "ESP", "esp": "ESP",
    "ireland": "IRL", "irl": "IRL",
    "new zealand": "NZL", "nzl": "NZL",
    "denmark": "DNK", "dnk": "DNK",
    "sweden": "SWE", "swe": "SWE",
    "norway": "NOR", "nor": "NOR",
    "finland": "FIN", "fin": "FIN",
    "israel": "ISR", "isr": "ISR",
    "chile": "CHL", "chl": "CHL",
    "poland": "POL", "pol": "POL",
    "qatar": "QAT", "qat": "QAT",
    "bahrain": "BHR", "bhr": "BHR",
    "kuwait": "KWT", "kwt": "KWT",
    "peru": "PER", "per": "PER",
    "colombia": "COL", "col": "COL",
    "ghana": "GHA", "gha": "GHA",
    "kenya": "KEN", "ken": "KEN",
    "argentina": "ARG", "arg": "ARG",
    "ukraine": "UKR", "ukr": "UKR",
    "pakistan": "PAK", "pak": "PAK",
    "bangladesh": "BGD", "bgd": "BGD",
    "myanmar": "MMR", "mmr": "MMR",
    "sri lanka": "LKA", "lka": "LKA",
    "ethiopia": "ETH", "eth": "ETH",
    "syria": "SYR", "syr": "SYR",
    "sudan": "SDN", "sdn": "SDN",
    "south sudan": "SSD", "ssd": "SSD",
    "libya": "LBY", "lby": "LBY",
}


def _resolve_iso3(location: str) -> Optional[str]:
    """ロケーション文字列をISO3コードに解決"""
    if not location:
        return None
    loc = location.strip().lower()
    # 直接ISO3コードの場合
    if loc.upper() in CHINN_ITO_SCORES:
        return loc.upper()
    return COUNTRY_TO_ISO3.get(loc)


class CapitalFlowRiskClient:
    """資本フローリスク評価クライアント

    3つのデータソースを統合:
      1. Chinn-Ito Index → 資本勘定開放度（低開放=高リスク）
      2. IMF AREAER → 個別規制フラグ
      3. SWIFT除外 → 国際送金遮断リスク
    """

    def _chinn_ito_to_risk(self, score: float) -> int:
        """Chinn-Itoスコア(-2.5〜2.5)を0-100リスクスコアに変換
        低スコア（規制的）= 高リスク
        """
        # -2.5 → 100, 2.5 → 0 の線形変換
        normalized = (2.5 - score) / 5.0  # 0.0（完全開放）〜1.0（完全規制）
        return min(100, max(0, int(normalized * 100)))

    def _imf_restriction_score(self, restrictions: dict) -> int:
        """IMF規制フラグからリスク加算スコアを算出
        各規制フラグごとに10点加算（最大40点）
        """
        if not restrictions:
            return 0
        penalty = 0
        if not restrictions.get("capital_account_open", True):
            penalty += 10  # 資本勘定非開放
        if restrictions.get("current_account_restrict", False):
            penalty += 10  # 経常勘定制限
        if restrictions.get("multiple_exchange_rates", False):
            penalty += 10  # 多重為替レート
        if restrictions.get("remittance_restrict", False):
            penalty += 10  # 送金制限
        return penalty

    def calculate_capital_flow_risk(self, country_iso3: str) -> dict:
        """資本フローリスクを算出

        Args:
            country_iso3: ISO3国コード（例: "JPN", "CHN"）

        Returns:
            {"score": 0-100, "evidence": [...], "details": {...}}
        """
        if not country_iso3:
            return {"score": 0, "evidence": [], "details": {}}

        iso3 = country_iso3.upper()
        evidence = []
        details = {}

        # --- 1. Chinn-Ito Index ---
        chinn_ito_raw = CHINN_ITO_SCORES.get(iso3)
        if chinn_ito_raw is not None:
            ci_risk = self._chinn_ito_to_risk(chinn_ito_raw)
            details["chinn_ito_raw"] = chinn_ito_raw
            details["chinn_ito_risk"] = ci_risk
            if ci_risk >= 60:
                evidence.append(
                    f"[資本規制] {iso3}: Chinn-Ito指数 {chinn_ito_raw:.2f}（資本勘定開放度が低い、リスク{ci_risk}/100）"
                )
            elif ci_risk >= 30:
                evidence.append(
                    f"[資本規制] {iso3}: Chinn-Ito指数 {chinn_ito_raw:.2f}（中程度の資本規制、リスク{ci_risk}/100）"
                )
        else:
            # データなし → 中程度のリスクを仮定
            ci_risk = 50
            details["chinn_ito_raw"] = None
            details["chinn_ito_risk"] = ci_risk
            evidence.append(f"[資本規制] {iso3}: Chinn-Itoデータなし、中リスク仮定")

        # --- 2. IMF AREAER ---
        imf_data = IMF_RESTRICTIONS.get(iso3, {})
        imf_penalty = self._imf_restriction_score(imf_data)
        details["imf_restrictions"] = imf_data
        details["imf_penalty"] = imf_penalty
        if imf_penalty > 0:
            flags = []
            if not imf_data.get("capital_account_open", True):
                flags.append("資本勘定非開放")
            if imf_data.get("current_account_restrict", False):
                flags.append("経常勘定制限")
            if imf_data.get("multiple_exchange_rates", False):
                flags.append("多重為替レート")
            if imf_data.get("remittance_restrict", False):
                flags.append("送金制限")
            evidence.append(
                f"[IMF規制] {iso3}: {', '.join(flags)}（加算{imf_penalty}点）"
            )

        # --- 3. SWIFT除外 ---
        swift_penalty = 0
        if iso3 in SWIFT_EXCLUDED:
            swift_penalty = 50
            details["swift_excluded"] = True
            evidence.append(
                f"[SWIFT除外] {iso3}: 国際送金ネットワークから実質排除（+{swift_penalty}点）"
            )
        else:
            details["swift_excluded"] = False

        # --- 総合スコア算出 ---
        # Chinn-Ito基礎スコア + IMF規制ペナルティ + SWIFT除外ペナルティ
        total = min(100, ci_risk + imf_penalty + swift_penalty)
        details["total_score"] = total

        return {
            "score": total,
            "evidence": evidence,
            "details": details,
        }

    def get_risk_for_location(self, location: str) -> dict:
        """ロケーション文字列から資本フローリスクを取得（エンジン統合用）"""
        iso3 = _resolve_iso3(location)
        if not iso3:
            return {"score": 0, "evidence": [f"[資本規制] {location}: ISO3コード解決不可"], "details": {}}
        return self.calculate_capital_flow_risk(iso3)


# モジュールレベル関数（エンジンからの呼び出し用）
_client = None

def get_capital_flow_risk(location: str) -> dict:
    """資本フローリスクを取得（遅延初期化シングルトン）"""
    global _client
    if _client is None:
        _client = CapitalFlowRiskClient()
    return _client.get_risk_for_location(location)
