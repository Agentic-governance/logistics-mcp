"""Tourism API Routes — SCRI v1.4.0
インバウンド観光リスク評価・市場ランキング・訪問者数予測・競合分析・地域分布・確率分布予測

GET  /api/v1/tourism/market-risk/{source_country}
GET  /api/v1/tourism/market-ranking
GET  /api/v1/tourism/historical
POST /api/v1/tourism/forecast
GET  /api/v1/tourism/competitor-analysis
POST /api/v1/tourism/regional-distribution
POST /api/v1/tourism/decompose
POST /api/v1/tourism/japan-forecast
POST /api/v1/tourism/prefecture-forecast
POST /api/v1/tourism/decompose-forecast
"""
import logging
import math
import random
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tourism", tags=["tourism"])

# ── 遅延インポート ──
_inbound_scorer = None
_regional_dist_model = None
_competitor_client = None

try:
    from features.tourism.inbound_risk_scorer import InboundTourismRiskScorer
    _inbound_scorer = InboundTourismRiskScorer()
except (ImportError, Exception) as _e:
    logger.warning("InboundTourismRiskScorer 初期化失敗: %s", _e)

try:
    from features.tourism.regional_distribution import RegionalDistributionModel
    _regional_dist_model = RegionalDistributionModel()
except (ImportError, Exception):
    pass

try:
    from pipeline.tourism.competitor_stats_client import CompetitorStatsClient
    _competitor_client = CompetitorStatsClient()
except (ImportError, Exception):
    pass

_capital_flow_client = None
try:
    from pipeline.financial.capital_flow_client import CapitalFlowRiskClient
    _capital_flow_client = CapitalFlowRiskClient()
except (ImportError, Exception):
    pass

# TASK1-3 モジュール（未完成時はフォールバック）
_gravity_model = None
try:
    from features.tourism.gravity_model import TourismGravityModel
    _gravity_model = TourismGravityModel()
except (ImportError, Exception) as _e:
    logger.warning("TourismGravityModel 初期化失敗: %s", _e)

_seasonal_extractor = None
try:
    from features.tourism.seasonal_extractor import SeasonalExtractor
    _seasonal_extractor = SeasonalExtractor()
except (ImportError, Exception) as _e:
    logger.warning("SeasonalExtractor 初期化失敗: %s", _e)

_inbound_aggregator = None
try:
    from features.tourism.inbound_aggregator import InboundAggregator
    _inbound_aggregator = InboundAggregator()
except (ImportError, Exception) as _e:
    logger.warning("InboundAggregator 初期化失敗: %s", _e)


# ── リクエスト/レスポンスモデル ──

class ForecastRequest(BaseModel):
    source_country: str = Field(..., description="送客国（ISO2/ISO3/国名）")
    horizon_months: int = Field(default=12, ge=1, le=36, description="予測期間（月）")
    scenario: Optional[dict] = Field(default=None, description="シナリオパラメータ")


class RegionalDistributionRequest(BaseModel):
    total_visitors: int = Field(..., ge=0, le=100_000_000, description="予測総訪問者数")
    source_country: str = Field(..., description="送客国（ISO2/ISO3/国名）")
    season: Optional[str] = Field(default="", description="季節（spring/summer/autumn/winter）")


class DecomposeRequest(BaseModel):
    source_country: str = Field(..., description="送客国（ISO2/ISO3/国名）")
    period_months: int = Field(default=12, ge=1, le=36, description="分析期間（月）")


class JapanForecastRequest(BaseModel):
    months: List[str] = Field(..., description="予測対象月リスト（例: ['2025/01','2025/02',...]）")
    n_samples: int = Field(default=1000, ge=100, le=10000, description="モンテカルロサンプル数")
    scenario: Optional[dict] = Field(default=None, description="シナリオショック（例: {exr:0.10}）")


class PrefectureForecastRequest(BaseModel):
    prefecture: str = Field(..., description="都道府県名（例: 東京）")
    months: List[str] = Field(default=None, description="予測対象月リスト")
    scenario: Optional[dict] = Field(default=None, description="シナリオショック")


class DecomposeForecastRequest(BaseModel):
    source_country: str = Field(..., description="送客国ISO2コード（例: CN）")
    year_month: str = Field(..., description="対象年月（例: 2025/06）")


# ── エンドポイント ──

@router.get("/market-risk/{source_country}")
def get_market_risk(
    source_country: str,
    horizon_months: int = Query(default=6, ge=1, le=36, description="評価期間（月）"),
):
    """インバウンド観光市場リスクを評価（需要・供給・日本側の3カテゴリ統合）"""
    if _inbound_scorer is None:
        return {
            "status": "fallback",
            "message": "インバウンドリスクスコアラー未初期化",
            "source_country": source_country,
            "inbound_risk_score": 50,
            "risk_level": "MEDIUM",
        }

    try:
        result = _inbound_scorer.calculate_market_risk(source_country, horizon_months)
        return {"status": "ok", **result}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception:
        logger.error("market-risk エラー: %s", source_country, exc_info=True)
        raise HTTPException(status_code=500, detail="リスク評価中に内部エラーが発生しました")


@router.get("/market-ranking")
def get_market_ranking(
    top_n: int = Query(default=20, ge=1, le=50, description="評価市場数"),
):
    """インバウンド主要市場のリスクランキング"""
    if _inbound_scorer is None:
        return {
            "status": "fallback",
            "message": "スコアラー未初期化",
            "markets": [],
            "total_markets": 0,
        }

    try:
        markets = _inbound_scorer.scan_all_markets(top_n=top_n)
        return {
            "status": "ok",
            "markets": markets,
            "total_markets": len(markets),
            "calculated_at": datetime.utcnow().isoformat(),
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception:
        logger.error("market-ranking エラー", exc_info=True)
        raise HTTPException(status_code=500, detail="市場ランキング取得中に内部エラーが発生しました")


@router.get("/historical")
def get_historical(
    source: str = Query(default="ALL", description="国コード（ALLで全市場）"),
    months: int = Query(default=87, ge=1, le=240, description="取得月数"),
):
    """japan_inbound テーブルから月次インバウンドデータを返す

    Args:
        source: ISO3国コード or "ALL"
        months: 取得月数（デフォルト87=7年分+α）

    Returns:
        月次データ配列
    """
    try:
        from pipeline.tourism.tourism_db import TourismDB
        db = TourismDB()

        if source.upper() == "ALL":
            rows = db.get_japan_inbound()
        else:
            rows = db.get_japan_inbound(country=source.upper())

        # month > 0 のみ（年次データ除外）
        monthly = [r for r in rows if r.get("month", 0) > 0]

        # 最新から指定月数分に制限
        # ソート: 年降順、月降順
        monthly.sort(key=lambda x: (x["year"], x["month"]), reverse=True)
        monthly = monthly[:months]
        monthly.reverse()  # 古い順に並べ直す

        # 国別に整形
        by_country = {}
        for r in monthly:
            cc = r["source_country"]
            if cc not in by_country:
                by_country[cc] = []
            by_country[cc].append({
                "year": r["year"],
                "month": r["month"],
                "arrivals": r["arrivals"],
                "purpose_leisure_pct": r.get("purpose_leisure_pct"),
                "avg_stay_days": r.get("avg_stay_days"),
                "avg_spend_jpy": r.get("avg_spend_jpy"),
            })

        return {
            "status": "ok",
            "source": source.upper(),
            "total_records": len(monthly),
            "countries": len(by_country),
            "data": by_country,
        }

    except Exception as e:
        logger.error("historical エラー: %s", e, exc_info=True)
        return {
            "status": "error",
            "message": f"月次データ取得失敗: {e}",
            "data": {},
        }


@router.post("/forecast")
def post_forecast(req: ForecastRequest):
    """送客国別の訪日観光客数予測（重力モデル×リスク調整）"""
    if _inbound_scorer is None:
        return {
            "status": "fallback",
            "message": "スコアラー未初期化",
            "source_country": req.source_country,
            "adjusted_forecast": 100000,
        }

    try:
        result = _inbound_scorer.forecast_visitor_volume(
            req.source_country, req.horizon_months, req.scenario
        )
        return {"status": "ok", **result}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception:
        logger.error("forecast エラー: %s", req.source_country, exc_info=True)
        raise HTTPException(status_code=500, detail="予測中に内部エラーが発生しました")


@router.get("/competitor-analysis")
def get_competitor_analysis(
    source_country: str = Query(default="", description="送客国（空欄で全体概要）"),
):
    """競合デスティネーションパフォーマンス分析"""
    if _competitor_client:
        try:
            if source_country:
                data = _competitor_client.get_competitor_index(source_country)
            else:
                data = _competitor_client.get_overview()
            return {"status": "ok", **data}
        except Exception:
            logger.warning("競合分析クライアントエラー（フォールバック使用）")

    # サンプルデータ
    competitors = ["JPN", "KOR", "THA", "TWN", "SGP", "IDN"]
    return {
        "status": "fallback",
        "message": "競合分析クライアント未実装（サンプルデータ）",
        "source_country": source_country or "全市場",
        "competitors": [
            {
                "destination": c,
                "market_share_pct": round(100 / len(competitors), 1),
                "yoy_change_pct": 0.0,
                "trend": "stable",
            }
            for c in competitors
        ],
    }


@router.post("/regional-distribution")
def post_regional_distribution(req: RegionalDistributionRequest):
    """訪日外国人の都道府県別・地域別分布予測"""
    valid_seasons = ("", "spring", "summer", "autumn", "winter")
    season = (req.season or "").lower()
    if season and season not in valid_seasons:
        raise HTTPException(
            status_code=400,
            detail=f"season は {', '.join(s for s in valid_seasons if s)} のいずれかを指定してください",
        )

    if _regional_dist_model:
        try:
            result = _regional_dist_model.predict(
                total_visitors=req.total_visitors,
                source_country=req.source_country,
                season=season or None,
            )
            return {"status": "ok", **result}
        except Exception:
            logger.warning("地域分布モデルエラー（フォールバック使用）")

    # デフォルト分布
    default_dist = {
        "関東": 0.45, "近畿": 0.25, "中部": 0.10,
        "九州": 0.08, "北海道": 0.05, "東北": 0.02,
        "中国": 0.02, "四国": 0.01, "沖縄": 0.02,
    }
    regions = []
    for region, share in default_dist.items():
        visitors = int(req.total_visitors * share)
        regions.append({
            "region": region,
            "share_pct": round(share * 100, 1),
            "estimated_visitors": visitors,
        })

    return {
        "status": "fallback",
        "message": "地域分布モデル未実装（デフォルト分布で推定）",
        "source_country": req.source_country,
        "season": season or "通年",
        "total_visitors": req.total_visitors,
        "regional_distribution": regions,
    }


@router.post("/decompose")
def post_decompose(req: DecomposeRequest):
    """訪問者数変動の要因分解（需要・供給・日本側）"""
    if _inbound_scorer is None:
        return {
            "status": "fallback",
            "message": "スコアラー未初期化",
            "source_country": req.source_country,
            "decomposition": {
                "demand_factors": {"total_impact": 0, "components": {}},
                "supply_factors": {"total_impact": 0, "components": {}},
                "japan_factors": {"total_impact": 0, "components": {}},
            },
        }

    try:
        result = _inbound_scorer.decompose_visitor_change(
            req.source_country, req.period_months
        )
        return {"status": "ok", **result}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception:
        logger.error("decompose エラー: %s", req.source_country, exc_info=True)
        raise HTTPException(status_code=500, detail="変動要因分解中に内部エラーが発生しました")


@router.get("/capital-flow-risk/{country}")
def get_capital_flow_risk(country: str):
    """国の資金フローリスク評価。Chinn-Ito資本開放度・IMF送金規制・SWIFT除外リスクを統合。"""
    if _capital_flow_client is not None:
        try:
            result = _capital_flow_client.assess(country)
            return {"status": "ok", **result}
        except Exception:
            logger.warning("CapitalFlowRiskClient エラー（フォールバック使用）")

    # フォールバック: ハードコードデータによる推定
    swift_excluded = {"RUS", "BLR", "IRN", "PRK", "SYR", "CUB"}
    closed_economies = {"CHN": 65, "RUS": 80, "IRN": 85, "PRK": 95,
                        "CUB": 90, "VEN": 75, "BLR": 78, "SYR": 88}
    open_economies = {"USA": 12, "GBR": 10, "SGP": 8, "JPN": 15,
                      "DEU": 11, "AUS": 13, "CAN": 12, "CHE": 9,
                      "HKG": 7, "NZL": 14}

    iso3 = country.upper()[:3]

    if iso3 in swift_excluded:
        score = max(closed_economies.get(iso3, 75), 70)
        swift_risk = True
    else:
        score = closed_economies.get(iso3, open_economies.get(iso3, 40))
        swift_risk = False

    risk_level = (
        "CRITICAL" if score >= 80 else
        "HIGH" if score >= 60 else
        "MEDIUM" if score >= 40 else
        "LOW" if score >= 20 else "MINIMAL"
    )

    return {
        "status": "fallback",
        "country": iso3,
        "capital_flow_risk_score": score,
        "risk_level": risk_level,
        "components": {
            "chinn_ito_openness": 100 - score,
            "swift_exclusion": swift_risk,
            "remittance_restriction": score > 50,
        },
        "message": "CapitalFlowRiskClient 未初期化（フォールバックデータ）",
    }


# ── v1.4.0 新規エンドポイント ──

# 主要市場の月次ベースライン（千人）— フォールバック用静的データ
_FALLBACK_MONTHLY_BASE = {
    "CN": [350, 300, 470, 510, 480, 410, 600, 550, 440, 680, 500, 560],
    "KR": [640, 570, 710, 690, 630, 560, 720, 660, 610, 760, 650, 720],
    "TW": [400, 440, 395, 430, 385, 360, 450, 430, 375, 475, 420, 435],
    "US": [165, 155, 220, 260, 245, 270, 315, 280, 240, 295, 225, 195],
    "AU": [68, 62, 50, 42, 33, 35, 46, 50, 60, 64, 68, 78],
}

# 都道府県別シェア（フォールバック）
_FALLBACK_PREF_SHARES = {
    "東京": 0.25, "大阪": 0.15, "京都": 0.08, "北海道": 0.06,
    "福岡": 0.05, "沖縄": 0.04, "新潟": 0.01, "長野": 0.01,
}


def _generate_forecast_samples(
    base_values: List[float],
    n_samples: int,
    scenario: Optional[dict] = None,
    cv: float = 0.12,
) -> dict:
    """モンテカルロサンプリングで確率分布を生成（フォールバック実装）"""
    # シナリオショック適用
    shock_multiplier = 1.0
    if scenario:
        exr_shock = scenario.get("exr", 0.0)
        bilateral_risk = scenario.get("bilateral_risk", 0)
        # 円安→訪日増、円高→減
        shock_multiplier *= (1.0 + exr_shock * 0.8)
        # 二国間リスク→訪日減
        if bilateral_risk > 0:
            shock_multiplier *= max(0.5, 1.0 - bilateral_risk / 100.0)

    results = []
    for base in base_values:
        adjusted = base * shock_multiplier
        samples = []
        for _ in range(n_samples):
            # 対数正規分布でサンプリング
            sigma = cv
            mu = math.log(adjusted) - 0.5 * sigma * sigma
            s = random.lognormexp(mu, sigma) if hasattr(random, 'lognormexp') else math.exp(random.gauss(mu, sigma))
            samples.append(max(0, s))
        samples.sort()
        results.append({
            "median": round(samples[n_samples // 2]),
            "p10": round(samples[int(n_samples * 0.10)]),
            "p25": round(samples[int(n_samples * 0.25)]),
            "p75": round(samples[int(n_samples * 0.75)]),
            "p90": round(samples[int(n_samples * 0.90)]),
            "mean": round(sum(samples) / len(samples)),
        })
    return results


def _month_str_to_index(month_str: str) -> int:
    """'2025/01' → 0-based month index (0=Jan)"""
    parts = month_str.replace("-", "/").split("/")
    if len(parts) >= 2:
        return int(parts[1]) - 1
    return 0


@router.post("/japan-forecast")
def post_japan_forecast(req: JapanForecastRequest):
    """日本全国インバウンド訪問者数の確率分布予測（PPML+STL+ベイズ）

    1000回のモンテカルロシミュレーションから確率分布を生成。
    シナリオショック（円安/円高/二国間関係悪化等）で分布全体をシフト可能。
    """
    months = req.months
    n_samples = req.n_samples
    scenario = req.scenario

    # TASK1-3モジュールが利用可能な場合
    if _gravity_model and _seasonal_extractor and _inbound_aggregator:
        try:
            # 重力モデル＋季節分解＋集計で全国予測
            country_forecasts = {}
            for country_code in ["CN", "KR", "TW", "US", "AU", "TH", "HK", "SG"]:
                try:
                    gravity_pred = _gravity_model.predict(
                        source_country=country_code,
                        months=months,
                        n_samples=n_samples,
                        scenario=scenario,
                    )
                    seasonal_adj = _seasonal_extractor.adjust(
                        country_code, months, gravity_pred
                    )
                    country_forecasts[country_code] = seasonal_adj
                except Exception:
                    logger.warning("国別予測失敗 %s（スキップ）", country_code)
                    continue

            aggregated = _inbound_aggregator.aggregate(country_forecasts, months)
            return {
                "status": "ok",
                "months": months,
                "median": [m["median"] for m in aggregated],
                "p10": [m["p10"] for m in aggregated],
                "p25": [m["p25"] for m in aggregated],
                "p75": [m["p75"] for m in aggregated],
                "p90": [m["p90"] for m in aggregated],
                "by_country": country_forecasts,
                "model_info": {
                    "method": "PPML+STL+Bayesian",
                    "n_samples": n_samples,
                    "scenario": scenario,
                },
            }
        except Exception:
            logger.warning("TASK1-3モジュール予測失敗（フォールバック使用）")

    # フォールバック: tourism_stats.db のデータを優先使用
    db_monthly_base = None
    try:
        from pipeline.tourism.tourism_db import TourismDB
        db = TourismDB()
        # 直近年（2024）の月次データからベースライン取得
        all_rows = db.get_japan_inbound(year=2024)
        monthly_rows = [r for r in all_rows if r.get("month", 0) > 0]
        if monthly_rows:
            db_monthly_base = {}
            for r in monthly_rows:
                cc = r["source_country"]
                if cc not in db_monthly_base:
                    db_monthly_base[cc] = [0] * 12
                m_idx = r["month"] - 1
                if 0 <= m_idx < 12:
                    db_monthly_base[cc][m_idx] = r["arrivals"] / 1000  # 千人単位
            logger.info("japan-forecast: DBデータからフォールバック生成 (%d市場)", len(db_monthly_base))
    except Exception as e:
        logger.warning("japan-forecast: DB読み込み失敗 (%s) — 静的データ使用", e)

    use_base = db_monthly_base if db_monthly_base else _FALLBACK_MONTHLY_BASE
    data_source = "db_montecarlo_fallback" if db_monthly_base else "static_montecarlo_fallback"

    total_base = []
    for m_str in months:
        m_idx = _month_str_to_index(m_str)
        total = 0
        for cdata in use_base.values():
            total += cdata[m_idx % 12]
        # DB由来データがない市場分は加算不要（全20市場カバー済み）
        if not db_monthly_base:
            total = int(total * 1.12)  # 非掲載市場分12%加算
        total_base.append(total)

    dist = _generate_forecast_samples(total_base, n_samples, scenario)

    # 国別内訳
    by_country = {}
    for code, cdata in use_base.items():
        c_base = [cdata[_month_str_to_index(m) % 12] for m in months]
        c_dist = _generate_forecast_samples(c_base, n_samples, scenario, cv=0.15)
        by_country[code] = {
            "median": [d["median"] for d in c_dist],
            "p10": [d["p10"] for d in c_dist],
            "p90": [d["p90"] for d in c_dist],
        }

    return {
        "status": "fallback",
        "message": "DBデータからの簡易予測" if db_monthly_base else "静的データからのモンテカルロフォールバック",
        "months": months,
        "median": [d["median"] for d in dist],
        "p10": [d["p10"] for d in dist],
        "p25": [d["p25"] for d in dist],
        "p75": [d["p75"] for d in dist],
        "p90": [d["p90"] for d in dist],
        "by_country": by_country,
        "model_info": {
            "method": data_source,
            "n_samples": n_samples,
            "scenario": scenario,
        },
    }


@router.post("/prefecture-forecast")
def post_prefecture_forecast(req: PrefectureForecastRequest):
    """都道府県別インバウンド訪問者数予測（国別シェア x ローカルリスク調整）"""
    prefecture = req.prefecture
    scenario = req.scenario

    # デフォルト: 24ヶ月分の月リスト生成
    if not req.months:
        months = [f"2025/{str(m).zfill(2)}" for m in range(1, 13)] + \
                 [f"2026/{str(m).zfill(2)}" for m in range(1, 13)]
    else:
        months = req.months

    # TASK1-3モジュール利用可能時
    if _gravity_model and _inbound_aggregator:
        try:
            national = _inbound_aggregator.get_national_forecast(months, scenario=scenario)
            pref_share = _inbound_aggregator.get_prefecture_share(prefecture)
            local_risk = _inbound_aggregator.get_local_risk_factor(prefecture)

            pref_forecast = []
            for m_data in national:
                adjusted = {
                    k: round(v * pref_share * local_risk) if isinstance(v, (int, float)) else v
                    for k, v in m_data.items()
                }
                pref_forecast.append(adjusted)

            return {
                "status": "ok",
                "prefecture": prefecture,
                "months": months,
                "forecast": pref_forecast,
                "share_pct": round(pref_share * 100, 2),
                "local_risk_factor": round(local_risk, 3),
            }
        except Exception:
            logger.warning("都道府県予測モジュール失敗（フォールバック使用）")

    # フォールバック
    pref_share = _FALLBACK_PREF_SHARES.get(prefecture, 0.02)

    total_base = []
    for m_str in months:
        m_idx = _month_str_to_index(m_str)
        total = 0
        for cdata in _FALLBACK_MONTHLY_BASE.values():
            total += cdata[m_idx % 12]
        total = int(total * 1.12)
        total_base.append(total)

    # 都道府県シェア適用
    pref_base = [round(v * pref_share) for v in total_base]
    dist = _generate_forecast_samples(pref_base, 500, scenario, cv=0.18)

    return {
        "status": "fallback",
        "message": "都道府県予測モジュール未実装（フォールバック）",
        "prefecture": prefecture,
        "months": months,
        "median": [d["median"] for d in dist],
        "p10": [d["p10"] for d in dist],
        "p25": [d["p25"] for d in dist],
        "p75": [d["p75"] for d in dist],
        "p90": [d["p90"] for d in dist],
        "share_pct": round(pref_share * 100, 2),
    }


@router.post("/decompose-forecast")
def post_decompose_forecast(req: DecomposeForecastRequest):
    """予測の変数別要因分解（重力モデルの各説明変数の寄与度）"""
    source_country = req.source_country.upper()
    year_month = req.year_month

    # TASK1-3モジュール利用可能時
    if _gravity_model:
        try:
            decomp = _gravity_model.decompose(source_country, year_month)
            return {"status": "ok", **decomp}
        except Exception:
            logger.warning("要因分解モジュール失敗（フォールバック使用）")

    # フォールバック: 典型的な要因分解サンプル
    m_idx = _month_str_to_index(year_month)
    base = _FALLBACK_MONTHLY_BASE.get(source_country, [200] * 12)
    baseline_val = base[m_idx % 12]

    # 国ごとの要因パターン
    factors = {
        "CN": {
            "gdp_per_capita": {"contribution_pct": 25.0, "direction": "positive", "value": 12500},
            "exchange_rate": {"contribution_pct": 20.0, "direction": "positive", "value": 0.053},
            "bilateral_risk": {"contribution_pct": -15.0, "direction": "negative", "value": 35},
            "distance_cost": {"contribution_pct": -8.0, "direction": "negative", "value": 1800},
            "seasonal_factor": {"contribution_pct": 12.0, "direction": "positive", "value": 1.15},
            "visa_ease": {"contribution_pct": 10.0, "direction": "positive", "value": 0.7},
            "flight_capacity": {"contribution_pct": 6.0, "direction": "positive", "value": 850},
        },
        "KR": {
            "gdp_per_capita": {"contribution_pct": 15.0, "direction": "positive", "value": 33000},
            "exchange_rate": {"contribution_pct": 22.0, "direction": "positive", "value": 0.11},
            "bilateral_risk": {"contribution_pct": -5.0, "direction": "negative", "value": 15},
            "distance_cost": {"contribution_pct": -3.0, "direction": "negative", "value": 900},
            "seasonal_factor": {"contribution_pct": 18.0, "direction": "positive", "value": 1.25},
            "visa_ease": {"contribution_pct": 8.0, "direction": "positive", "value": 0.95},
            "flight_capacity": {"contribution_pct": 5.0, "direction": "positive", "value": 1200},
        },
    }

    default_factors = {
        "gdp_per_capita": {"contribution_pct": 20.0, "direction": "positive", "value": 20000},
        "exchange_rate": {"contribution_pct": 18.0, "direction": "positive", "value": 0.07},
        "bilateral_risk": {"contribution_pct": -8.0, "direction": "negative", "value": 20},
        "distance_cost": {"contribution_pct": -10.0, "direction": "negative", "value": 3000},
        "seasonal_factor": {"contribution_pct": 15.0, "direction": "positive", "value": 1.10},
        "visa_ease": {"contribution_pct": 7.0, "direction": "positive", "value": 0.8},
        "flight_capacity": {"contribution_pct": 5.0, "direction": "positive", "value": 500},
    }

    return {
        "status": "fallback",
        "message": "重力モデル未実装（サンプル要因分解）",
        "source_country": source_country,
        "year_month": year_month,
        "baseline_visitors_thousands": baseline_val,
        "factors": factors.get(source_country, default_factors),
    }
