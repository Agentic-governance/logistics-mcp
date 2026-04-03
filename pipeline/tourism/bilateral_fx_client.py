"""二国間為替レートクライアント — SCRI v1.5.0
============================================================
Frankfurter API を使い、主要送客国の対円為替レートを取得。
各国通貨の円換算レート変動 → 訪日需要への弾性値を適用して
為替ショックによる需要変化率を計算する。

データソース: https://api.frankfurter.app/ (ECB参照レート)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── 国コード → 通貨マッピング ──
CURRENCY_MAP: Dict[str, str] = {
    "KR": "KRW",   # 韓国ウォン
    "CN": "CNY",   # 中国人民元
    "TW": "TWD",   # 台湾ドル
    "US": "USD",   # 米ドル
    "AU": "AUD",   # 豪ドル
    "TH": "THB",   # タイバーツ
    "HK": "HKD",   # 香港ドル
    "SG": "SGD",   # シンガポールドル
    "DE": "EUR",   # ドイツ（ユーロ）
    "FR": "EUR",   # フランス（ユーロ）
    "GB": "GBP",   # 英ポンド
    "IN": "INR",   # インドルピー
}

# ── 為替弾性値（1%の自国通貨高 → 訪日需要 +X%） ──
# 学術文献: Peng et al.(2015), Song & Li (2008)
# 近距離・リピーター国は低弾性、遠距離・価格敏感国は高弾性
FX_ELASTICITY: Dict[str, float] = {
    "KR": 0.45,   # 韓国: リピーター多く価格弾性は中程度
    "CN": 0.70,   # 中国: 団体旅行＋買物目的で価格敏感
    "TW": 0.50,   # 台湾: リピーター多いが買物需要あり
    "US": 0.30,   # 米国: 所得効果大、為替弾性は低い
    "AU": 0.35,   # 豪州: 所得効果大
    "TH": 0.80,   # タイ: 価格敏感
    "HK": 0.55,   # 香港: 買物目的多い
    "SG": 0.40,   # シンガポール: 所得水準高い
    "DE": 0.35,   # ドイツ: 長距離、所得効果大
    "FR": 0.35,   # フランス: 長距離
    "GB": 0.30,   # 英国: 長距離、所得効果大
    "IN": 0.90,   # インド: 価格敏感
}

# ── APIフォールバック用ハードコードレート（1通貨単位あたりの円） ──
FALLBACK_RATES: Dict[str, float] = {
    "KR": 0.107,   # 1 KRW = 0.107 JPY
    "CN": 20.8,    # 1 CNY = 20.8 JPY
    "TW": 4.65,    # 1 TWD = 4.65 JPY
    "US": 149.5,   # 1 USD = 149.5 JPY
    "AU": 96.5,    # 1 AUD = 96.5 JPY
    "TH": 4.15,    # 1 THB = 4.15 JPY
    "HK": 18.4,    # 1 HKD = 18.4 JPY
    "SG": 110.2,   # 1 SGD = 110.2 JPY
    "DE": 162.5,   # 1 EUR = 162.5 JPY (ドイツ)
    "FR": 162.5,   # 1 EUR = 162.5 JPY (フランス)
    "GB": 188.5,   # 1 GBP = 188.5 JPY
    "IN": 1.78,    # 1 INR = 1.78 JPY
}


@dataclass
class FXRate:
    """為替レートデータ"""
    country_code: str       # ISO2
    currency: str           # ISO4217
    rate_per_jpy: float     # 1通貨単位あたりの円
    source: str             # "frankfurter" or "fallback"
    date: str               # YYYY-MM-DD


@dataclass
class FXShockResult:
    """為替ショック計算結果"""
    country_code: str
    currency: str
    current_rate: float
    shocked_rate: float
    rate_change_pct: float       # レート変化率(%)
    elasticity: float
    demand_change_pct: float     # 需要変化率(%)
    explanation: str


class BilateralFXClient:
    """二国間為替レートクライアント

    Frankfurter API（ECBベース）から対円レートを取得。
    失敗時はハードコードフォールバックを使用。
    """

    API_BASE = "https://api.frankfurter.app"

    def __init__(self):
        self._session = None

    def _get_session(self):
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
                self._session.headers.update({
                    "User-Agent": "SCRI/1.5.0 BilateralFXClient"
                })
            except ImportError:
                logger.warning("requests未インストール")
        return self._session

    def get_current_rates(self) -> Dict[str, FXRate]:
        """全送客国の最新対円レートを取得"""
        rates: Dict[str, FXRate] = {}

        # ユニークな通貨リスト
        unique_currencies = set(CURRENCY_MAP.values())
        symbols = ",".join(sorted(unique_currencies))

        api_rates: Dict[str, float] = {}
        source = "fallback"
        date_str = datetime.now().strftime("%Y-%m-%d")

        try:
            session = self._get_session()
            if session is not None:
                url = f"{self.API_BASE}/latest?from=JPY&to={symbols}"
                resp = session.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                # Frankfurter returns: {"base":"JPY","date":"...","rates":{"USD":0.0067,...}}
                # 1 JPY = X通貨 → 1通貨 = 1/X JPY
                raw_rates = data.get("rates", {})
                for ccy, val in raw_rates.items():
                    if val > 0:
                        api_rates[ccy] = 1.0 / val  # 1通貨単位あたりの円
                source = "frankfurter"
                date_str = data.get("date", date_str)
                logger.info("Frankfurter APIから %d 通貨取得", len(api_rates))
        except Exception as e:
            logger.warning("Frankfurter API失敗（フォールバック使用）: %s", e)

        # 各国のレートを構築
        for cc, ccy in CURRENCY_MAP.items():
            if ccy in api_rates:
                rate_val = api_rates[ccy]
                src = source
            else:
                rate_val = FALLBACK_RATES.get(cc, 100.0)
                src = "fallback"

            rates[cc] = FXRate(
                country_code=cc,
                currency=ccy,
                rate_per_jpy=rate_val,
                source=src,
                date=date_str,
            )

        return rates

    def get_historical_rates(self, year: int) -> Dict[str, FXRate]:
        """指定年の年央(7/1)レートを取得"""
        rates: Dict[str, FXRate] = {}
        date_str = f"{year}-07-01"

        unique_currencies = set(CURRENCY_MAP.values())
        symbols = ",".join(sorted(unique_currencies))

        api_rates: Dict[str, float] = {}
        source = "fallback"

        try:
            session = self._get_session()
            if session is not None:
                url = f"{self.API_BASE}/{date_str}?from=JPY&to={symbols}"
                resp = session.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                raw_rates = data.get("rates", {})
                for ccy, val in raw_rates.items():
                    if val > 0:
                        api_rates[ccy] = 1.0 / val
                source = "frankfurter"
                date_str = data.get("date", date_str)
        except Exception as e:
            logger.warning("Frankfurter 歴史レート取得失敗 (%d): %s", year, e)

        for cc, ccy in CURRENCY_MAP.items():
            if ccy in api_rates:
                rate_val = api_rates[ccy]
                src = source
            else:
                rate_val = FALLBACK_RATES.get(cc, 100.0)
                src = "fallback"

            rates[cc] = FXRate(
                country_code=cc,
                currency=ccy,
                rate_per_jpy=rate_val,
                source=src,
                date=date_str,
            )

        return rates

    def calculate_fx_shock(
        self,
        country_code: str,
        shock_pct: float,
        current_rate: Optional[float] = None,
    ) -> FXShockResult:
        """為替ショック → 需要変化率を計算

        Args:
            country_code: ISO2国コード
            shock_pct: 円の変化率(%)。正=円安、負=円高
                       例: +10 = 10%円安（外貨高）→ 訪日需要増
            current_rate: 現在のレート（省略時はAPI/フォールバック取得）

        Returns:
            FXShockResult: ショック計算結果
        """
        ccy = CURRENCY_MAP.get(country_code)
        if ccy is None:
            raise ValueError(f"未対応国コード: {country_code}")

        # 現在レート取得
        if current_rate is None:
            rates = self.get_current_rates()
            if country_code in rates:
                current_rate = rates[country_code].rate_per_jpy
            else:
                current_rate = FALLBACK_RATES.get(country_code, 100.0)

        # ショック後レート: 円安 shock_pct% → 1通貨あたりの円が増える
        shocked_rate = current_rate * (1.0 + shock_pct / 100.0)

        # 弾性値適用: 自国通貨の円換算が上がる → 日本が割安 → 訪日需要増
        elasticity = FX_ELASTICITY.get(country_code, 0.50)
        demand_change_pct = shock_pct * elasticity

        # 説明文生成
        direction = "円安" if shock_pct > 0 else "円高"
        demand_dir = "増加" if demand_change_pct > 0 else "減少"
        explanation = (
            f"{country_code}({ccy}): {abs(shock_pct):.1f}%{direction} → "
            f"訪日需要 {abs(demand_change_pct):.1f}%{demand_dir} "
            f"(弾性値={elasticity:.2f})"
        )

        return FXShockResult(
            country_code=country_code,
            currency=ccy,
            current_rate=current_rate,
            shocked_rate=shocked_rate,
            rate_change_pct=shock_pct,
            elasticity=elasticity,
            demand_change_pct=demand_change_pct,
            explanation=explanation,
        )
