"""インバウンド観光リスク評価スコアラー — SCRI v1.3.0 ROLE-E

訪日観光の市場別リスクを多角的に評価し、訪問者数を予測する。
既存の26次元リスクエンジンを活用し、観光固有の需要・供給・日本側リスクを統合。

構成:
  A) 需要側リスク (50%): 為替25% + 経済15% + 政治10%
  B) 供給側リスク (30%): 二国間関係15% + フライト10% + ビザ5%
  C) 日本側リスク (20%): 災害10% + 台風5% + 競合5%
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── 既存スコアリングエンジン ──
try:
    from scoring.engine import calculate_risk_score
    _HAS_SCORING_ENGINE = True
except ImportError:
    _HAS_SCORING_ENGINE = False

# ── ROLE-B: 重力モデル ──
try:
    from features.tourism.gravity_model import TourismGravityModel
    _HAS_GRAVITY_MODEL = True
except (ImportError, ModuleNotFoundError):
    _HAS_GRAVITY_MODEL = False

# ── ROLE-C: フライト供給 ──
try:
    from pipeline.tourism.flight_supply_client import FlightSupplyClient
    _HAS_FLIGHT_SUPPLY = True
except (ImportError, ModuleNotFoundError):
    _HAS_FLIGHT_SUPPLY = False

# ── ROLE-D: 地域分布 ──
try:
    from features.tourism.regional_distribution import RegionalDistributionModel
    _HAS_REGIONAL_DIST = True
except (ImportError, ModuleNotFoundError):
    _HAS_REGIONAL_DIST = False

# ── ROLE-A: 観光統計クライアント ──
try:
    from pipeline.tourism.unwto_client import UNWTOClient
    _HAS_UNWTO = True
except (ImportError, ModuleNotFoundError):
    _HAS_UNWTO = False

try:
    from pipeline.tourism.competitor_stats_client import CompetitorStatsClient
    _HAS_COMPETITOR = True
except (ImportError, ModuleNotFoundError):
    _HAS_COMPETITOR = False

try:
    from pipeline.tourism.jnto_client import JNTOClient
    _HAS_JNTO = True
except (ImportError, ModuleNotFoundError):
    _HAS_JNTO = False

# ── 主要送客国→リスク評価用国名マッピング ──
_COUNTRY_NAME_MAP = {
    "CN": "China", "KR": "South Korea", "TW": "Taiwan", "HK": "Hong Kong",
    "US": "United States", "TH": "Thailand", "AU": "Australia", "PH": "Philippines",
    "VN": "Vietnam", "ID": "Indonesia", "MY": "Malaysia", "SG": "Singapore",
    "GB": "United Kingdom", "FR": "France", "DE": "Germany", "CA": "Canada",
    "IT": "Italy", "ES": "Spain", "IN": "India", "RU": "Russia",
}

# 主要20市場（ISO2コード）
TOP_20_MARKETS = [
    "CN", "KR", "TW", "HK", "US", "TH", "AU", "PH", "VN", "ID",
    "MY", "SG", "GB", "FR", "DE", "CA", "IT", "IN", "ES", "RU",
]

# デフォルトの年間訪問者数推定（万人、2019年ベース）
_DEFAULT_VISITOR_ESTIMATES = {
    "CN": 959, "KR": 558, "TW": 489, "HK": 229, "US": 172,
    "TH": 132, "AU": 62, "PH": 61, "VN": 50, "ID": 41,
    "MY": 50, "SG": 49, "GB": 42, "FR": 34, "DE": 24,
    "CA": 38, "IT": 16, "IN": 18, "ES": 13, "RU": 12,
}

# ビザリスク（主観的だが安定的な値。0=ビザ免除/簡便、50=一般観光ビザ、80=厳格）
_VISA_RISK = {
    "CN": 40, "KR": 0, "TW": 0, "HK": 0, "US": 0,
    "TH": 0, "AU": 0, "PH": 30, "VN": 30, "ID": 0,
    "MY": 0, "SG": 0, "GB": 0, "FR": 0, "DE": 0,
    "CA": 0, "IT": 0, "IN": 40, "ES": 0, "RU": 50,
}

# デフォルトスコア（エンジン取得失敗時）
_DEFAULT_SCORE = 50


def _resolve_country_name(source_country: str) -> str:
    """ISO2/ISO3/国名をリスクエンジン用国名に変換"""
    upper = source_country.strip().upper()
    if upper in _COUNTRY_NAME_MAP:
        return _COUNTRY_NAME_MAP[upper]
    # ISO3 → ISO2 のフォールバック
    iso3_to_iso2 = {
        "CHN": "CN", "KOR": "KR", "TWN": "TW", "HKG": "HK", "USA": "US",
        "THA": "TH", "AUS": "AU", "PHL": "PH", "VNM": "VN", "IDN": "ID",
        "MYS": "MY", "SGP": "SG", "GBR": "GB", "FRA": "FR", "DEU": "DE",
        "CAN": "CA", "ITA": "IT", "IND": "IN", "ESP": "ES", "RUS": "RU",
    }
    if upper in iso3_to_iso2:
        return _COUNTRY_NAME_MAP.get(iso3_to_iso2[upper], source_country)
    # そのまま返す（フルネーム入力の場合）
    return source_country


def _resolve_iso2(source_country: str) -> str:
    """国名/ISO3をISO2に変換"""
    upper = source_country.strip().upper()
    if upper in _COUNTRY_NAME_MAP:
        return upper
    # 逆引き
    for iso2, name in _COUNTRY_NAME_MAP.items():
        if name.upper() == upper:
            return iso2
    iso3_to_iso2 = {
        "CHN": "CN", "KOR": "KR", "TWN": "TW", "HKG": "HK", "USA": "US",
        "THA": "TH", "AUS": "AU", "PHL": "PH", "VNM": "VN", "IDN": "ID",
        "MYS": "MY", "SGP": "SG", "GBR": "GB", "FRA": "FR", "DEU": "DE",
        "CAN": "CA", "ITA": "IT", "IND": "IN", "ESP": "ES", "RUS": "RU",
    }
    if upper in iso3_to_iso2:
        return iso3_to_iso2[upper]
    return upper[:2]


def _get_risk_scores_for_country(country_name: str) -> dict:
    """既存スコアリングエンジンから必要な次元スコアを取得"""
    defaults = {
        "currency": _DEFAULT_SCORE,
        "economic": _DEFAULT_SCORE,
        "political": _DEFAULT_SCORE,
        "geo_risk": _DEFAULT_SCORE,
        "disaster": _DEFAULT_SCORE,
        "typhoon": _DEFAULT_SCORE,
    }
    if not _HAS_SCORING_ENGINE:
        return defaults

    try:
        result = calculate_risk_score(
            supplier_id=f"tourism_{country_name}",
            company_name=f"tourism_proxy_{country_name}",
            country=country_name,
            location=country_name,
        )
        scores = result.to_dict().get("scores", {})
        return {
            "currency": scores.get("currency", _DEFAULT_SCORE),
            "economic": scores.get("economic", _DEFAULT_SCORE),
            "political": scores.get("political", _DEFAULT_SCORE),
            "geo_risk": scores.get("geo_risk", _DEFAULT_SCORE),
            "disaster": scores.get("disaster", _DEFAULT_SCORE),
            "typhoon": scores.get("typhoon", _DEFAULT_SCORE),
        }
    except Exception:
        logger.error("リスクスコア取得失敗: country=%s", country_name, exc_info=True)
        return defaults


class InboundTourismRiskScorer:
    """インバウンド観光の市場別リスク評価・訪問者数予測"""

    def __init__(self):
        self._gravity_model = None
        self._flight_client = None
        self._competitor_client = None
        self._jnto_client = None

        if _HAS_GRAVITY_MODEL:
            try:
                self._gravity_model = TourismGravityModel()
            except Exception:
                logger.warning("重力モデル初期化失敗（フォールバック使用）")

        if _HAS_FLIGHT_SUPPLY:
            try:
                self._flight_client = FlightSupplyClient()
            except Exception:
                logger.warning("フライト供給クライアント初期化失敗")

        if _HAS_COMPETITOR:
            try:
                self._competitor_client = CompetitorStatsClient()
            except Exception:
                logger.warning("競合分析クライアント初期化失敗")

        if _HAS_JNTO:
            try:
                self._jnto_client = JNTOClient()
            except Exception:
                logger.warning("JNTOクライアント初期化失敗")

    # ─────────────────────────────────────────────
    #  A) 需要側リスク (50%)
    # ─────────────────────────────────────────────
    def _calculate_demand_risk(self, scores: dict, iso2: str) -> dict:
        """為替25% + 経済15% + 政治10%"""
        currency_risk = scores.get("currency", _DEFAULT_SCORE)
        economic_risk = scores.get("economic", _DEFAULT_SCORE)
        political_risk = scores.get("political", _DEFAULT_SCORE)

        demand_score = (
            currency_risk * 0.25
            + economic_risk * 0.15
            + political_risk * 0.10
        ) / 0.50  # 0.50で割って0-100に正規化

        return {
            "score": min(100, max(0, int(demand_score))),
            "weight": 0.50,
            "components": {
                "currency_risk": {"score": currency_risk, "weight": 0.25},
                "economic_risk": {"score": economic_risk, "weight": 0.15},
                "political_risk": {"score": political_risk, "weight": 0.10},
            },
        }

    # ─────────────────────────────────────────────
    #  B) 供給側リスク (30%)
    # ─────────────────────────────────────────────
    def _calculate_supply_risk(self, scores: dict, iso2: str) -> dict:
        """二国間関係15% + フライト10% + ビザ5%"""
        # 二国間関係 = geo_riskを代用
        bilateral_risk = scores.get("geo_risk", _DEFAULT_SCORE)

        # フライト供給リスク
        flight_risk = _DEFAULT_SCORE
        if self._flight_client:
            try:
                flight_data = self._flight_client.get_flight_supply(iso2, "JP")
                flight_risk = flight_data.get("risk_score", _DEFAULT_SCORE)
            except Exception:
                logger.warning("フライト供給データ取得失敗: %s", iso2)

        # ビザリスク
        visa_risk = _VISA_RISK.get(iso2, 30)

        supply_score = (
            bilateral_risk * 0.15
            + flight_risk * 0.10
            + visa_risk * 0.05
        ) / 0.30

        return {
            "score": min(100, max(0, int(supply_score))),
            "weight": 0.30,
            "components": {
                "bilateral_risk": {"score": bilateral_risk, "weight": 0.15},
                "flight_risk": {"score": flight_risk, "weight": 0.10},
                "visa_risk": {"score": visa_risk, "weight": 0.05},
            },
        }

    # ─────────────────────────────────────────────
    #  C) 日本側リスク (20%)
    # ─────────────────────────────────────────────
    def _calculate_japan_risk(self, scores: dict, iso2: str) -> dict:
        """災害10% + 台風5% + 競合5%"""
        # 日本の災害リスク
        japan_scores = _get_risk_scores_for_country("Japan")
        disaster_risk = japan_scores.get("disaster", _DEFAULT_SCORE)
        typhoon_risk = japan_scores.get("typhoon", _DEFAULT_SCORE)

        # 競合リスク（他デスティネーションの魅力度変化）
        competitor_risk = _DEFAULT_SCORE
        if self._competitor_client:
            try:
                comp_data = self._competitor_client.get_competitor_index(iso2)
                competitor_risk = comp_data.get("risk_score", _DEFAULT_SCORE)
            except Exception:
                logger.warning("競合分析データ取得失敗: %s", iso2)

        japan_score = (
            disaster_risk * 0.10
            + typhoon_risk * 0.05
            + competitor_risk * 0.05
        ) / 0.20

        return {
            "score": min(100, max(0, int(japan_score))),
            "weight": 0.20,
            "components": {
                "disaster_risk": {"score": disaster_risk, "weight": 0.10},
                "typhoon_risk": {"score": typhoon_risk, "weight": 0.05},
                "competitor_risk": {"score": competitor_risk, "weight": 0.05},
            },
        }

    # ─────────────────────────────────────────────
    #  市場リスク統合
    # ─────────────────────────────────────────────
    def calculate_market_risk(
        self, source_country: str, horizon_months: int = 6
    ) -> dict:
        """
        特定市場のインバウンドリスクを統合評価。

        Args:
            source_country: 送客国（ISO2/ISO3/国名）
            horizon_months: 評価期間（1-36ヶ月）

        Returns:
            dict: 統合リスクスコア・内訳・リスクレベル
        """
        # 入力バリデーション
        if not isinstance(horizon_months, int) or horizon_months < 1 or horizon_months > 36:
            raise ValueError("horizon_months は 1〜36 の整数を指定してください")

        country_name = _resolve_country_name(source_country)
        iso2 = _resolve_iso2(source_country)

        # 既存エンジンからスコア取得
        scores = _get_risk_scores_for_country(country_name)

        # 3カテゴリ算出
        demand = self._calculate_demand_risk(scores, iso2)
        supply = self._calculate_supply_risk(scores, iso2)
        japan = self._calculate_japan_risk(scores, iso2)

        # 統合スコア = A×0.5 + B×0.3 + C×0.2
        inbound_risk = int(
            demand["score"] * 0.5
            + supply["score"] * 0.3
            + japan["score"] * 0.2
        )
        inbound_risk = min(100, max(0, inbound_risk))

        # リスクレベル判定
        if inbound_risk >= 80:
            risk_level = "CRITICAL"
        elif inbound_risk >= 60:
            risk_level = "HIGH"
        elif inbound_risk >= 40:
            risk_level = "MEDIUM"
        elif inbound_risk >= 20:
            risk_level = "LOW"
        else:
            risk_level = "MINIMAL"

        return {
            "source_country": source_country,
            "country_name": country_name,
            "iso2": iso2,
            "horizon_months": horizon_months,
            "inbound_risk_score": inbound_risk,
            "risk_level": risk_level,
            "categories": {
                "demand_risk": demand,
                "supply_risk": supply,
                "japan_risk": japan,
            },
            "scoring_method": "demand×0.5 + supply×0.3 + japan×0.2",
            "data_sources": {
                "scoring_engine": _HAS_SCORING_ENGINE,
                "flight_supply": _HAS_FLIGHT_SUPPLY,
                "competitor_stats": _HAS_COMPETITOR,
            },
            "calculated_at": datetime.utcnow().isoformat(),
        }

    # ─────────────────────────────────────────────
    #  訪問者数予測
    # ─────────────────────────────────────────────
    def forecast_visitor_volume(
        self,
        source_country: str,
        horizon_months: int = 6,
        scenario: Optional[dict] = None,
    ) -> dict:
        """
        重力モデル予測 × リスク調整で訪問者数を予測。

        adjustment_factor = 1 - (inbound_risk_score / 200)
        final_forecast = gravity_forecast × adjustment_factor

        Args:
            source_country: 送客国
            horizon_months: 予測期間（1-36ヶ月）
            scenario: シナリオパラメータ（オプション）

        Returns:
            dict: 予測訪問者数・信頼区間・リスク調整率
        """
        if not isinstance(horizon_months, int) or horizon_months < 1 or horizon_months > 36:
            raise ValueError("horizon_months は 1〜36 の整数を指定してください")

        iso2 = _resolve_iso2(source_country)
        country_name = _resolve_country_name(source_country)

        # リスクスコア算出
        risk_result = self.calculate_market_risk(source_country, horizon_months)
        inbound_risk = risk_result["inbound_risk_score"]

        # 重力モデル予測
        gravity_forecast = None
        if self._gravity_model:
            try:
                gf = self._gravity_model.predict(
                    source_country=iso2,
                    destination="JP",
                    horizon_months=horizon_months,
                    scenario=scenario or {},
                )
                gravity_forecast = gf.get("predicted_visitors")
            except Exception:
                logger.warning("重力モデル予測失敗: %s", source_country)

        # フォールバック: デフォルト推定値をベースに月割り
        if gravity_forecast is None:
            annual = _DEFAULT_VISITOR_ESTIMATES.get(iso2, 10) * 10000  # 万人→人
            gravity_forecast = int(annual / 12 * horizon_months)

        # リスク調整
        adjustment_factor = 1.0 - (inbound_risk / 200.0)
        adjusted_forecast = int(gravity_forecast * adjustment_factor)

        # シナリオ調整（指定時）
        scenario_adjustment = 1.0
        if scenario:
            # シナリオの影響度を加算
            impact = scenario.get("impact_factor", 0)
            scenario_adjustment = max(0.1, 1.0 + impact)
            adjusted_forecast = int(adjusted_forecast * scenario_adjustment)

        # 信頼区間（±20%を標準とし、リスクが高いほど拡大）
        uncertainty = 0.20 + (inbound_risk / 500.0)
        lower = int(adjusted_forecast * (1 - uncertainty))
        upper = int(adjusted_forecast * (1 + uncertainty))

        return {
            "source_country": source_country,
            "country_name": country_name,
            "iso2": iso2,
            "horizon_months": horizon_months,
            "gravity_forecast": gravity_forecast,
            "inbound_risk_score": inbound_risk,
            "adjustment_factor": round(adjustment_factor, 4),
            "scenario_adjustment": round(scenario_adjustment, 4),
            "adjusted_forecast": adjusted_forecast,
            "confidence_interval": {
                "lower": max(0, lower),
                "upper": upper,
                "uncertainty_pct": round(uncertainty * 100, 1),
            },
            "model_source": "gravity_model" if self._gravity_model else "default_estimate",
            "calculated_at": datetime.utcnow().isoformat(),
        }

    # ─────────────────────────────────────────────
    #  全市場一括評価
    # ─────────────────────────────────────────────
    def scan_all_markets(self, top_n: int = 20) -> list:
        """
        主要市場を一括評価し、リスクスコア順にソート。

        Args:
            top_n: 評価市場数（1-50）

        Returns:
            list: リスクスコア降順の市場リスト
        """
        if not isinstance(top_n, int) or top_n < 1 or top_n > 50:
            raise ValueError("top_n は 1〜50 の整数を指定してください")

        markets_to_scan = TOP_20_MARKETS[:min(top_n, len(TOP_20_MARKETS))]
        results = []

        for iso2 in markets_to_scan:
            try:
                risk = self.calculate_market_risk(iso2)
                forecast = self.forecast_visitor_volume(iso2)
                results.append({
                    "rank": 0,  # 後でソート後に割当
                    "iso2": iso2,
                    "country_name": _COUNTRY_NAME_MAP.get(iso2, iso2),
                    "inbound_risk_score": risk["inbound_risk_score"],
                    "risk_level": risk["risk_level"],
                    "demand_risk": risk["categories"]["demand_risk"]["score"],
                    "supply_risk": risk["categories"]["supply_risk"]["score"],
                    "japan_risk": risk["categories"]["japan_risk"]["score"],
                    "forecast_visitors": forecast["adjusted_forecast"],
                    "forecast_period_months": forecast["horizon_months"],
                })
            except Exception:
                logger.error("市場スキャン失敗: %s", iso2, exc_info=True)
                results.append({
                    "rank": 0,
                    "iso2": iso2,
                    "country_name": _COUNTRY_NAME_MAP.get(iso2, iso2),
                    "inbound_risk_score": _DEFAULT_SCORE,
                    "risk_level": "UNKNOWN",
                    "demand_risk": _DEFAULT_SCORE,
                    "supply_risk": _DEFAULT_SCORE,
                    "japan_risk": _DEFAULT_SCORE,
                    "forecast_visitors": None,
                    "forecast_period_months": 6,
                })

        # リスクスコア降順ソート
        results.sort(key=lambda x: x["inbound_risk_score"], reverse=True)

        # ランク付与
        for i, item in enumerate(results, 1):
            item["rank"] = i

        return results

    # ─────────────────────────────────────────────
    #  変動要因分解
    # ─────────────────────────────────────────────
    def decompose_visitor_change(
        self, source_country: str, period_months: int = 12
    ) -> dict:
        """
        訪問者数変動を需要・供給・日本側要因に分解。

        Args:
            source_country: 送客国
            period_months: 分析期間（1-36ヶ月）

        Returns:
            dict: 要因別の寄与度分解
        """
        if not isinstance(period_months, int) or period_months < 1 or period_months > 36:
            raise ValueError("period_months は 1〜36 の整数を指定してください")

        iso2 = _resolve_iso2(source_country)
        country_name = _resolve_country_name(source_country)

        # 現在のリスク状況
        risk = self.calculate_market_risk(source_country)

        demand = risk["categories"]["demand_risk"]
        supply = risk["categories"]["supply_risk"]
        japan = risk["categories"]["japan_risk"]

        # 各コンポーネントの影響度算出
        # 基準値(50)からの偏差を影響度として表現
        def _impact(score, weight):
            deviation = score - _DEFAULT_SCORE
            return round(deviation * weight, 2)

        demand_components = {}
        for key, comp in demand["components"].items():
            demand_components[key] = {
                "score": comp["score"],
                "impact": _impact(comp["score"], comp["weight"]),
                "direction": "negative" if comp["score"] > _DEFAULT_SCORE else "positive",
            }

        supply_components = {}
        for key, comp in supply["components"].items():
            supply_components[key] = {
                "score": comp["score"],
                "impact": _impact(comp["score"], comp["weight"]),
                "direction": "negative" if comp["score"] > _DEFAULT_SCORE else "positive",
            }

        japan_components = {}
        for key, comp in japan["components"].items():
            japan_components[key] = {
                "score": comp["score"],
                "impact": _impact(comp["score"], comp["weight"]),
                "direction": "negative" if comp["score"] > _DEFAULT_SCORE else "positive",
            }

        # JNTO実績データ（あれば）
        jnto_data = None
        if self._jnto_client:
            try:
                jnto_data = self._jnto_client.get_monthly_visitors(iso2, months=period_months)
            except Exception:
                logger.warning("JNTO実績データ取得失敗: %s", iso2)

        return {
            "source_country": source_country,
            "country_name": country_name,
            "iso2": iso2,
            "period_months": period_months,
            "overall_risk_score": risk["inbound_risk_score"],
            "decomposition": {
                "demand_factors": {
                    "total_impact": _impact(demand["score"], demand["weight"]),
                    "components": demand_components,
                },
                "supply_factors": {
                    "total_impact": _impact(supply["score"], supply["weight"]),
                    "components": supply_components,
                },
                "japan_factors": {
                    "total_impact": _impact(japan["score"], japan["weight"]),
                    "components": japan_components,
                },
            },
            "jnto_actual_data": jnto_data,
            "calculated_at": datetime.utcnow().isoformat(),
        }
