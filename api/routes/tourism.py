"""Tourism API Routes — SCRI v1.5.0
インバウンド観光リスク評価・市場ランキング・訪問者数予測・競合分析・地域分布・確率分布予測・GP予測・シナリオ分析

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
GET  /api/v1/tourism/scenarios
POST /api/v1/tourism/scenario-analysis
GET  /api/v1/tourism/three-scenarios
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

import time as _time
_cache = {}
_CACHE_TTL = 300  # 5分

def _get_cached(key, compute_fn):
    """5分キャッシュ"""
    now = _time.time()
    if key in _cache and now - _cache[key]["ts"] < _CACHE_TTL:
        return _cache[key]["data"]
    data = compute_fn()
    _cache[key] = {"data": data, "ts": now}
    return data

# ── ISO2→ISO3マッピング ──
ISO2_TO_ISO3 = {
    'CN':'CHN','KR':'KOR','TW':'TWN','US':'USA','AU':'AUS',
    'TH':'THA','HK':'HKG','SG':'SGP','MY':'MYS','PH':'PHL',
    'VN':'VNM','IN':'IND','ID':'IDN','DE':'DEU','FR':'FRA',
    'GB':'GBR','CA':'CAN','IT':'ITA','RU':'RUS','SA':'SAU',
    'JP':'JPN','BR':'BRA','MX':'MEX','TR':'TUR','AE':'ARE',
    'EG':'EGY','NG':'NGA','ZA':'ZAF','KE':'KEN','AR':'ARG',
}

# ── market-ranking フォールバック ──
MARKET_RANKING_FALLBACK = [
    {'iso2':'CN','name':'中国','flag':'🇨🇳','lat':35.0,'lon':105.0,'share_pct':24.8,'inbound_risk_score':72,'expected_loss_pct':21.2,'expected_change':-8,'visitors_2024':5200000},
    {'iso2':'KR','name':'韓国','flag':'🇰🇷','lat':37.0,'lon':127.5,'share_pct':19.3,'inbound_risk_score':28,'expected_loss_pct':7.6,'expected_change':5,'visitors_2024':8600000},
    {'iso2':'TW','name':'台湾','flag':'🇹🇼','lat':23.5,'lon':121.0,'share_pct':17.2,'inbound_risk_score':32,'expected_loss_pct':9.8,'expected_change':3,'visitors_2024':4800000},
    {'iso2':'US','name':'米国','flag':'🇺🇸','lat':39.0,'lon':-98.0,'share_pct':8.5,'inbound_risk_score':18,'expected_loss_pct':4.2,'expected_change':12,'visitors_2024':3600000},
    {'iso2':'HK','name':'香港','flag':'🇭🇰','lat':22.3,'lon':114.2,'share_pct':6.2,'inbound_risk_score':38,'expected_loss_pct':11.2,'expected_change':2,'visitors_2024':1310000},
    {'iso2':'AU','name':'豪州','flag':'🇦🇺','lat':-25.0,'lon':133.0,'share_pct':4.8,'inbound_risk_score':22,'expected_loss_pct':5.5,'expected_change':9,'visitors_2024':620000},
    {'iso2':'TH','name':'タイ','flag':'🇹🇭','lat':15.0,'lon':100.0,'share_pct':3.2,'inbound_risk_score':42,'expected_loss_pct':14.5,'expected_change':-3,'visitors_2024':420000},
    {'iso2':'SG','name':'シンガポール','flag':'🇸🇬','lat':1.35,'lon':103.8,'share_pct':2.8,'inbound_risk_score':15,'expected_loss_pct':3.8,'expected_change':6,'visitors_2024':380000},
]

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

# TASK4: GPモデル（ガウス過程による訪日予測）
_gp_aggregator = None
try:
    from features.tourism.gaussian_process_model import MultiMarketGPAggregator
    _gp_aggregator = MultiMarketGPAggregator()
except (ImportError, Exception) as _e:
    logger.warning("MultiMarketGPAggregator 初期化失敗: %s", _e)

_calendar_events_module = None
try:
    from features.tourism import calendar_events as _calendar_events_module
except (ImportError, Exception) as _e:
    logger.warning("calendar_events 初期化失敗: %s", _e)

# v1.5.0: シナリオエンジン + 二国間為替クライアント
_scenario_engine = None
try:
    from features.tourism.scenario_engine import ScenarioEngine
    _scenario_engine = ScenarioEngine()
except (ImportError, Exception) as _e:
    logger.warning("ScenarioEngine 初期化失敗: %s", _e)

_bilateral_fx_client = None
try:
    from pipeline.tourism.bilateral_fx_client import BilateralFXClient
    _bilateral_fx_client = BilateralFXClient()
except (ImportError, Exception) as _e:
    logger.warning("BilateralFXClient 初期化失敗: %s", _e)


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
    use_gp: bool = Field(default=True, description="GPモデルを使用するか（Falseで既存フォールバック）")


class PrefectureForecastRequest(BaseModel):
    prefecture: str = Field(..., description="都道府県名（例: 東京）")
    months: List[str] = Field(default=None, description="予測対象月リスト")
    scenario: Optional[dict] = Field(default=None, description="シナリオショック")


class DecomposeForecastRequest(BaseModel):
    source_country: str = Field(..., description="送客国ISO2コード（例: CN）")
    year_month: str = Field(..., description="対象年月（例: 2025/06）")


class ScenarioAnalysisRequest(BaseModel):
    scenario_name: str = Field(..., description="シナリオ名（例: jpy_weak_10, china_stimulus）")
    include_fx_details: bool = Field(default=False, description="為替レート詳細を含めるか")


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


@router.get("/driver-sensitivity")
async def get_driver_sensitivity(
    source_country: str = Query(default="CN", description="国コード"),
):
    """変数別感度分析: 各ドライバー変数を±1σ動かした時の来訪者数への影響"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        cache_key = f"driver_sensitivity_{source_country}"
        result = await loop.run_in_executor(
            None, lambda: _get_cached(cache_key, lambda: _full_mc_engine.driver_sensitivity(source_country))
        )
        return {"status": "ok", **result}
    except KeyError:
        raise HTTPException(status_code=400, detail=f"未対応の国コード: {source_country}")
    except Exception as e:
        logger.error("driver-sensitivity エラー: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market-opportunity")
async def get_market_opportunity():
    """市場機会スコアリング"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        cache_key = "market_opportunity"
        result = await loop.run_in_executor(
            None, lambda: _get_cached(cache_key, _full_mc_engine.market_opportunity_score)
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backtest")
async def get_backtest(
    source_country: str = Query(default="ALL"),
    start_year: int = Query(default=2024),
    end_year: int = Query(default=2025),
):
    """バックテスト: 過去予測のMAPE + p10-p90カバー率"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        months = []
        for y in range(start_year, end_year + 1):
            for m in range(1, 13):
                months.append(f"{y}/{m:02d}")
        loop = asyncio.get_event_loop()
        cache_key = f"backtest_{source_country}_{start_year}_{end_year}"
        result = await loop.run_in_executor(
            None, lambda: _get_cached(cache_key, lambda: _full_mc_engine.backtest(months, source_country))
        )
        return {"status": "ok", **result}
    except Exception as e:
        logger.error("backtest エラー: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spending-forecast")
async def get_spending_forecast(
    month: int = Query(default=4, ge=1, le=12),
    year: int = Query(default=2026),
):
    """国別消費額予測（月次）"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        cache_key = f"spending_{year}_{month}"
        result = await loop.run_in_executor(
            None, lambda: _get_cached(cache_key, lambda: _full_mc_engine.spending_forecast(month, year))
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monthly-forecast-table")
async def get_monthly_forecast_table(
    source_country: str = Query(default="ALL"),
    rooms: int = Query(default=30, ge=1, le=5000),
    adr: int = Query(default=25000, ge=1000, le=500000),
):
    """12ヶ月P/L計画用テーブル (2026/04〜2027/03)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        months = [f"{2026 + (m+3)//12}/{(m+3)%12+1:02d}" for m in range(12)]
        loop = asyncio.get_event_loop()
        cache_key = f"forecast_table_{source_country}_{rooms}_{adr}"
        result = await loop.run_in_executor(
            None, lambda: _get_cached(cache_key, lambda: _build_forecast_table(months, source_country, rooms, adr))
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _build_forecast_table(months, source_country, rooms, adr):
    """MC結果から12ヶ月P/Lテーブルを構築"""
    result = _full_mc_engine.run(months, source_country)
    table = []
    total_rev = {"p10": 0, "p50": 0, "p90": 0}
    for i, ms in enumerate(months):
        visitors_p10 = result["p10"][i]
        visitors_p50 = result["median"][i]
        visitors_p90 = result["p90"][i]
        # 稼働率推定: 来訪者数ベースで正規化 (全国月間250万人=稼働率80%想定)
        occ_p10 = min(round(visitors_p10 / 2_500_000 * 0.80 * 100, 1), 100.0)
        occ_p50 = min(round(visitors_p50 / 2_500_000 * 0.80 * 100, 1), 100.0)
        occ_p90 = min(round(visitors_p90 / 2_500_000 * 0.80 * 100, 1), 100.0)
        # RevPAR = ADR × 稼働率
        revpar_p10 = round(adr * occ_p10 / 100)
        revpar_p50 = round(adr * occ_p50 / 100)
        revpar_p90 = round(adr * occ_p90 / 100)
        # 月間売上 = RevPAR × 客室数 × 30日
        rev_p10 = revpar_p10 * rooms * 30
        rev_p50 = revpar_p50 * rooms * 30
        rev_p90 = revpar_p90 * rooms * 30
        total_rev["p10"] += rev_p10
        total_rev["p50"] += rev_p50
        total_rev["p90"] += rev_p90
        table.append({
            "month": ms,
            "visitors": {"p10": visitors_p10, "p50": visitors_p50, "p90": visitors_p90},
            "occupancy_pct": {"p10": occ_p10, "p50": occ_p50, "p90": occ_p90},
            "revpar": {"p10": revpar_p10, "p50": revpar_p50, "p90": revpar_p90},
            "revenue": {"p10": rev_p10, "p50": rev_p50, "p90": rev_p90},
        })
    return {
        "months": months,
        "source_country": source_country,
        "rooms": rooms,
        "adr": adr,
        "table": table,
        "annual_revenue": {
            "p10": total_rev["p10"],
            "p50": total_rev["p50"],
            "p90": total_rev["p90"],
        },
    }


@router.get("/market-ranking")
async def get_market_ranking(
    top_n: int = Query(default=20, ge=1, le=50, description="評価市場数"),
):
    """インバウンド主要市場のリスクランキング（タイムアウト15秒、フォールバック付き）"""
    import asyncio

    # キャッシュ確認
    try:
        from features.cache.smart_cache import get_cache
        cache = get_cache()
        cached = await cache.get("tourism:market_ranking")
        if cached:
            return cached
    except Exception:
        pass

    # ライブ計算（タイムアウト15秒）
    if _inbound_scorer is not None:
        try:
            markets = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, _inbound_scorer.scan_all_markets, top_n
                ),
                timeout=15.0,
            )
            result = {
                "status": "ok",
                "source": "live",
                "markets": markets,
                "total_markets": len(markets),
                "calculated_at": datetime.utcnow().isoformat(),
            }
            # キャッシュ保存
            try:
                cache = get_cache()
                await cache.set("tourism:market_ranking", result, ttl=3600)
            except Exception:
                pass
            return result
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("market-ranking タイムアウトまたはエラー: %s", e)

    # フォールバック
    return {
        "status": "fallback",
        "source": "static",
        "markets": MARKET_RANKING_FALLBACK[:top_n],
        "total_markets": len(MARKET_RANKING_FALLBACK[:top_n]),
        "calculated_at": datetime.utcnow().isoformat(),
    }


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
            # ISO2→ISO3変換（KR→KOR等）
            source_db = ISO2_TO_ISO3.get(source.upper(), source.upper())
            rows = db.get_japan_inbound(country=source_db)

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


def _compute_calendar_effects(months: List[str]) -> List[dict]:
    """月別のカレンダー効果倍率を計算（全市場の加重平均）

    Returns:
        [{"month": "2026/04", "demand_multiplier": 1.35, "events": ["桜"]}, ...]
    """
    # 主要市場のシェア（加重平均用）
    market_shares = {
        "CN": 0.248, "KR": 0.193, "TW": 0.172, "US": 0.085,
        "AU": 0.048, "TH": 0.032, "HK": 0.062, "SG": 0.028,
    }

    results = []
    for m_str in months:
        m_idx = _month_str_to_index(m_str)
        month_1based = m_idx + 1  # 1-12

        weighted_demand = 0.0
        all_events = set()

        if _calendar_events_module:
            for country, share in market_shares.items():
                dm = _calendar_events_module.get_demand_multiplier(country, month_1based)
                weighted_demand += dm * share
                events = _calendar_events_module.get_events_for_country_month(country, month_1based)
                for ev in events:
                    all_events.add(ev.name)

            # 残りの市場分（シェア合計が1未満の場合）
            remaining = 1.0 - sum(market_shares.values())
            weighted_demand += 1.0 * remaining  # 残りは倍率1.0
        else:
            weighted_demand = 1.0

        results.append({
            "month": m_str,
            "demand_multiplier": round(weighted_demand, 3),
            "events": sorted(all_events),
        })

    return results


def _compute_uncertainty_by_month(
    months: List[str], gp_result: dict
) -> List[dict]:
    """GP予測結果から月別不確実性指数を計算

    不確実性 = (p90 - p10) / median × カレンダー不確実性倍率
    """
    market_shares = {
        "CN": 0.248, "KR": 0.193, "TW": 0.172, "US": 0.085,
        "AU": 0.048, "TH": 0.032, "HK": 0.062, "SG": 0.028,
    }

    medians = gp_result.get("median", [])
    p10s = gp_result.get("p10", [])
    p90s = gp_result.get("p90", [])

    results = []
    for i, m_str in enumerate(months):
        m_idx = _month_str_to_index(m_str)
        month_1based = m_idx + 1

        # GP由来の不確実性（分布の幅）
        if i < len(medians) and i < len(p10s) and i < len(p90s):
            med = medians[i] if medians[i] > 0 else 1
            spread_ratio = (p90s[i] - p10s[i]) / med
        else:
            spread_ratio = 0.3  # デフォルト

        # カレンダー不確実性倍率
        cal_unc = 1.0
        if _calendar_events_module:
            for country, share in market_shares.items():
                um = _calendar_events_module.get_uncertainty_multiplier(country, month_1based)
                cal_unc = max(cal_unc, um)  # 最大値を採用

        # 統合不確実性指数（1.0=標準、>1.5=高不確実性）
        uncertainty_index = round(spread_ratio * cal_unc / 0.3, 2)  # 0.3を基準に正規化

        results.append({
            "month": m_str,
            "uncertainty_index": uncertainty_index,
            "spread_ratio": round(spread_ratio, 3),
            "calendar_uncertainty": round(cal_unc, 2),
        })

    return results


def _compute_uncertainty_by_month_fallback(
    months: List[str], dist: list
) -> List[dict]:
    """フォールバック予測結果から月別不確実性指数を計算"""
    market_shares = {
        "CN": 0.248, "KR": 0.193, "TW": 0.172, "US": 0.085,
        "AU": 0.048, "TH": 0.032, "HK": 0.062, "SG": 0.028,
    }

    results = []
    for i, m_str in enumerate(months):
        m_idx = _month_str_to_index(m_str)
        month_1based = m_idx + 1

        # フォールバック由来の不確実性
        if i < len(dist):
            med = dist[i]["median"] if dist[i]["median"] > 0 else 1
            spread_ratio = (dist[i]["p90"] - dist[i]["p10"]) / med
        else:
            spread_ratio = 0.3

        # カレンダー不確実性倍率
        cal_unc = 1.0
        if _calendar_events_module:
            for country, share in market_shares.items():
                um = _calendar_events_module.get_uncertainty_multiplier(country, month_1based)
                cal_unc = max(cal_unc, um)

        uncertainty_index = round(spread_ratio * cal_unc / 0.3, 2)

        results.append({
            "month": m_str,
            "uncertainty_index": uncertainty_index,
            "spread_ratio": round(spread_ratio, 3),
            "calendar_uncertainty": round(cal_unc, 2),
        })

    return results


@router.post("/japan-forecast")
def post_japan_forecast(req: JapanForecastRequest):
    """日本全国インバウンド訪問者数の確率分布予測（GP/PPML+STL+ベイズ）

    use_gp=True: ガウス過程モデルによる予測（不確実性付き）
    use_gp=False: モンテカルロシミュレーションによる確率分布生成
    GPが失敗した場合は自動的にフォールバックへ切替。
    """
    months = req.months
    n_samples = req.n_samples
    scenario = req.scenario

    # ── GP予測（use_gp=True かつ GPモジュール利用可能時） ──
    if req.use_gp and _gp_aggregator:
        try:
            gp_result = _gp_aggregator.predict_japan_total_gp(
                months=months,
                scenario=scenario,
            )
            # カレンダー効果倍率を計算
            calendar_effects = _compute_calendar_effects(months)
            # 月別不確実性指数を計算
            uncertainty_by_month = _compute_uncertainty_by_month(months, gp_result)

            return {
                "status": "ok",
                "model": "GP",
                "months": months,
                "median": gp_result.get("median", []),
                "p10": gp_result.get("p10", []),
                "p25": gp_result.get("p25", []),
                "p75": gp_result.get("p75", []),
                "p90": gp_result.get("p90", []),
                "by_country": gp_result.get("by_country", {}),
                "uncertainty_by_month": uncertainty_by_month,
                "calendar_effects": calendar_effects,
                "model_info": {
                    "method": "GaussianProcess",
                    "scenario": scenario,
                    "gp_details": gp_result.get("gp_details", {}),
                },
            }
        except Exception as e:
            logger.warning("GP予測失敗（フォールバック使用）: %s", e)

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
            calendar_effects = _compute_calendar_effects(months)
            agg_result = {
                "median": [m["median"] for m in aggregated],
                "p10": [m["p10"] for m in aggregated],
                "p90": [m["p90"] for m in aggregated],
            }
            uncertainty_by_month = _compute_uncertainty_by_month(months, agg_result)
            return {
                "status": "ok",
                "model": "PPML+STL+Bayesian",
                "months": months,
                "median": agg_result["median"],
                "p10": agg_result["p10"],
                "p25": [m["p25"] for m in aggregated],
                "p75": [m["p75"] for m in aggregated],
                "p90": agg_result["p90"],
                "by_country": country_forecasts,
                "uncertainty_by_month": uncertainty_by_month,
                "calendar_effects": calendar_effects,
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

    # フォールバック時もカレンダー効果・不確実性を付与
    calendar_effects = _compute_calendar_effects(months)
    uncertainty_by_month = _compute_uncertainty_by_month_fallback(months, dist)

    return {
        "status": "fallback",
        "model": "fallback",
        "message": "DBデータからの簡易予測" if db_monthly_base else "静的データからのモンテカルロフォールバック",
        "months": months,
        "median": [d["median"] for d in dist],
        "p10": [d["p10"] for d in dist],
        "p25": [d["p25"] for d in dist],
        "p75": [d["p75"] for d in dist],
        "p90": [d["p90"] for d in dist],
        "by_country": by_country,
        "uncertainty_by_month": uncertainty_by_month,
        "calendar_effects": calendar_effects,
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


# ── v1.5.0 シナリオ分析エンドポイント ──

@router.get("/scenarios")
def get_scenarios():
    """利用可能なシナリオ一覧を返す"""
    if _scenario_engine is not None:
        try:
            scenarios = _scenario_engine.list_scenarios()
            return {
                "status": "ok",
                "count": len(scenarios),
                "scenarios": scenarios,
            }
        except Exception as e:
            logger.warning("ScenarioEngine.list_scenarios失敗: %s", e)

    # フォールバック: ハードコード
    fallback_scenarios = [
        {"name": "base", "label": "ベースケース", "description": "現状維持"},
        {"name": "jpy_weak_10", "label": "円安10%", "description": "円が10%下落"},
        {"name": "jpy_strong_10", "label": "円高10%", "description": "円が10%上昇"},
        {"name": "china_stimulus", "label": "中国景気刺激策", "description": "中国財政出動"},
        {"name": "flight_expansion", "label": "航空便拡大", "description": "LCC路線増便"},
        {"name": "japan_china_tension", "label": "日中関係悪化", "description": "日中緊張"},
        {"name": "us_recession", "label": "米国景気後退", "description": "米国リセッション"},
        {"name": "taiwan_strait_risk", "label": "台湾海峡リスク", "description": "台湾海峡緊張"},
        {"name": "stagflation_mixed", "label": "スタグフレーション", "description": "世界的滞留"},
    ]
    return {
        "status": "fallback",
        "message": "ScenarioEngine未初期化（フォールバック一覧）",
        "count": len(fallback_scenarios),
        "scenarios": fallback_scenarios,
    }


@router.post("/scenario-analysis")
def post_scenario_analysis(req: ScenarioAnalysisRequest):
    """シナリオの国別影響分析。為替ショック・地政学リスクの需要変化を定量評価"""
    scenario_name = req.scenario_name

    if _scenario_engine is not None:
        try:
            result = _scenario_engine.calculate_japan_total_impact(scenario_name)

            # 為替詳細を追加（オプション）
            if req.include_fx_details and _bilateral_fx_client is not None:
                try:
                    fx_rates = _bilateral_fx_client.get_current_rates()
                    result["fx_rates"] = {
                        cc: {
                            "currency": r.currency,
                            "rate_per_jpy": round(r.rate_per_jpy, 4),
                            "source": r.source,
                            "date": r.date,
                        }
                        for cc, r in fx_rates.items()
                    }
                except Exception as e:
                    logger.warning("為替レート取得失敗: %s", e)

            return {"status": "ok", **result}
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception:
            logger.error("scenario-analysis エラー: %s", scenario_name, exc_info=True)
            raise HTTPException(status_code=500, detail="シナリオ分析中に内部エラーが発生しました")

    # フォールバック
    raise HTTPException(
        status_code=503,
        detail="ScenarioEngine未初期化。依存モジュールを確認してください。",
    )


# ── v1.5.0 3シナリオ同時表示 ──

# FullMCEngine（真の確率的予測、優先使用）
_full_mc_engine = None
try:
    from features.tourism.full_mc_engine import FullMCEngine
    _full_mc_engine = FullMCEngine(n_samples=3000)
    logger.info("FullMCEngine 初期化成功 (29変数, 相関行列付き)")
except (ImportError, Exception) as _e:
    logger.warning("FullMCEngine 初期化失敗: %s", _e)

# MC集計器（フォールバック）
_mc_aggregator = None
try:
    from features.tourism.country_distribution_model import MonteCarloAggregator
    _mc_aggregator = MonteCarloAggregator(n_samples=5000, seed=42)
except (ImportError, Exception) as _e:
    logger.warning("MonteCarloAggregator 初期化失敗: %s", _e)

# 月別ベースライン（千人）— MC失敗時フォールバック用
BASE_MONTHLY = {
    "KR": [672, 598, 746, 724, 662, 588, 756, 693, 640, 798, 682, 756,
           699, 622, 776, 753, 688, 612, 786, 721, 666],
    "CN": [322, 276, 432, 469, 442, 377, 552, 506, 405, 626, 460, 515,
           301, 258, 404, 439, 414, 353, 517, 474, 379],
    "TW": [412, 453, 407, 443, 397, 371, 464, 443, 386, 489, 433, 448,
           422, 464, 417, 454, 407, 380, 475, 454, 395],
    "US": [185, 174, 246, 291, 274, 302, 353, 314, 269, 330, 252, 218,
           203, 191, 270, 319, 300, 331, 387, 344, 295],
    "AU": [74, 68, 55, 46, 36, 38, 50, 55, 65, 70, 74, 85,
           79, 73, 59, 49, 39, 41, 54, 59, 70],
}

# 予測月ラベル（2026/04 ~ 2027/12, 21ヶ月）
_THREE_SCENARIO_MONTHS = []
for _y in (2026, 2027):
    _sm = 4 if _y == 2026 else 1
    for _m in range(_sm, 13):
        _THREE_SCENARIO_MONTHS.append(f"{_y}/{str(_m).zfill(2)}")


@router.get("/three-scenarios")
async def get_three_scenarios(
    source_country: str = Query(default="ALL", description="国コード (ALL=全市場)"),
    prefecture: str = Query(default="JAPAN", description="都道府県 (JAPAN=全国)"),
):
    """3シナリオ (base/optimistic/pessimistic) をモンテカルロ集計で同時計算

    真のMC集計: 共通FXショック + 国別政治ショック + 固有ボラティリティ
    → サンプルレベルで合算 → 非対称なp10/p50/p90
    MC失敗時は従来のScenarioEngine乗数方式にフォールバック
    """
    import asyncio

    months = list(_THREE_SCENARIO_MONTHS)

    # ── FullMCEngine (真の確率的予測) を最優先 ──
    if _full_mc_engine is not None:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            cache_key = f"three_scenarios_{source_country}"
            mc_result = await loop.run_in_executor(
                None, lambda: _get_cached(cache_key, lambda: _full_mc_engine.run(months, source_country))
            )
            # YoY計算（前年同月DBから取得）
            yoy_data = {}
            try:
                import sqlite3
                conn = sqlite3.connect('data/tourism_stats.db')
                for row in conn.execute(
                    "SELECT source_country, SUM(arrivals) as total FROM japan_inbound "
                    "WHERE year=2025 AND month=4 GROUP BY source_country"
                ).fetchall():
                    yoy_data[row[0]] = row[1]
                conn.close()
            except Exception:
                pass

            # ドライバー変数の影響度
            from features.tourism.variable_distributions import SPECS
            driver_info = {}
            for vname, spec in SPECS.items():
                driver_info[vname] = {
                    "label": spec.name,
                    "sigma": spec.sigma,
                    "range": [spec.lo, spec.hi],
                }

            return {
                "status": "ok",
                "model": "full_mc_29vars",
                "n_samples": _full_mc_engine.n_samples,
                "months": mc_result["months"],
                "scenarios": {
                    "pessimistic": {"label":"悲観(p10)","color":"#ff4d4d","line_style":"dashed","median":mc_result["p10"]},
                    "base": {"label":"ベース(p50)","color":"#4a9eff","line_style":"solid",
                             "median":mc_result["median"],"p10":mc_result["p10"],"p25":mc_result["p25"],
                             "p75":mc_result["p75"],"p90":mc_result["p90"]},
                    "optimistic": {"label":"楽観(p90)","color":"#51cf66","line_style":"dashed","median":mc_result["p90"]},
                },
                "by_country": mc_result.get("by_country", {}),
                "country_impacts": mc_result.get("by_country", {}),
                "yoy_actuals": yoy_data,
                "driver_variables": driver_info,
                "asymmetry_by_month": mc_result.get("asymmetry_by_month", []),
                "uncertainty_by_month": mc_result.get("uncertainty_by_month", []),
                "model_note": f"29変数相関行列, N={_full_mc_engine.n_samples}",
                "correlation_health": _full_mc_engine.correlation_health(),
                "backtest_summary": _get_cached("bt_summary_2024", lambda: _full_mc_engine.backtest(
                    [f"2024/{m:02d}" for m in range(1,13)], "ALL"
                )) if True else None,
            }
        except Exception as e:
            logger.warning("FullMCEngine計算失敗: %s", e)

    # ── MonteCarloAggregator フォールバック ──
    if _mc_aggregator is not None:
        try:
            loop = asyncio.get_event_loop()
            mc_result = await loop.run_in_executor(
                None, _mc_aggregator.compute_all_three, months
            )

            # ScenarioEngineからcountry_impactsを取得（国別影響テーブル用）
            country_impacts = {}
            try:
                from features.tourism.scenario_engine import ScenarioEngine as _SE
                engine = _SE()
                all_three = engine.calculate_all_three()
                base_impacts = all_three.get("base", {}).get("country_impacts", {})
                opt_impacts = all_three.get("optimistic", {}).get("country_impacts", {})
                pess_impacts = all_three.get("pessimistic", {}).get("country_impacts", {})
                for cc in set(list(base_impacts.keys()) + list(opt_impacts.keys()) + list(pess_impacts.keys())):
                    country_impacts[cc] = {
                        "base": base_impacts.get(cc, {"change_pct": 0, "direction": "FLAT", "breakdown": {}}),
                        "optimistic": opt_impacts.get(cc, {"change_pct": 0, "direction": "FLAT", "breakdown": {}}),
                        "pessimistic": pess_impacts.get(cc, {"change_pct": 0, "direction": "FLAT", "breakdown": {}}),
                    }
            except Exception as e:
                logger.warning("ScenarioEngine country_impacts取得失敗: %s", e)

            return {
                "status": "ok",
                "model": "montecarlo",
                "n_samples": _mc_aggregator.n_samples,
                "months": mc_result["months"],
                "scenarios": mc_result["scenarios"],
                "country_impacts": country_impacts,
                "distribution_stats": mc_result.get("distribution_stats", {}),
            }
        except Exception as e:
            logger.warning("MonteCarloAggregator 計算失敗、フォールバック: %s", e)

    # ── フォールバック: 従来方式（ScenarioEngine乗数） ──
    logger.info("three-scenarios: フォールバックモード (ScenarioEngine乗数方式)")

    # ベースライン予測を取得
    baseline_median = None
    baseline_p10 = None
    baseline_p90 = None
    gp_model_used = False

    if _gp_aggregator is not None:
        try:
            gp_result = _gp_aggregator.predict_japan_total_gp(months=months)
            baseline_median = gp_result.get("median", [])
            baseline_p10 = gp_result.get("p10", [])
            baseline_p90 = gp_result.get("p90", [])
            if baseline_median and len(baseline_median) == len(months):
                gp_model_used = True
            else:
                baseline_median = None
        except Exception as e:
            logger.warning("three-scenarios GP予測失敗: %s", e)

    if baseline_median is None:
        baseline_median = []
        for i in range(len(months)):
            total = 0
            for cdata in BASE_MONTHLY.values():
                if i < len(cdata):
                    total += cdata[i]
            total = int(total * 1.25)
            baseline_median.append(total)
        baseline_p10 = [round(v * 0.88) for v in baseline_median]
        baseline_p90 = [round(v * 1.12) for v in baseline_median]

    # ScenarioEngine で乗数計算
    engine = None
    try:
        from features.tourism.scenario_engine import ScenarioEngine as _SE
        engine = _SE()
    except Exception as e:
        logger.warning("ScenarioEngine初期化失敗: %s", e)

    if engine is None:
        opt_mult = 1.18
        pess_mult = 0.82
        country_impacts = {}
    else:
        all_three = engine.calculate_all_three()
        opt_data = all_three.get("optimistic", {})
        pess_data = all_three.get("pessimistic", {})
        opt_mult = 1.0 + opt_data.get("total_change_pct", 18.0) / 100.0
        pess_mult = 1.0 + pess_data.get("total_change_pct", -18.0) / 100.0

        country_impacts = {}
        base_impacts = all_three.get("base", {}).get("country_impacts", {})
        opt_impacts = opt_data.get("country_impacts", {})
        pess_impacts = pess_data.get("country_impacts", {})
        for cc in set(list(base_impacts.keys()) + list(opt_impacts.keys()) + list(pess_impacts.keys())):
            country_impacts[cc] = {
                "base": base_impacts.get(cc, {"change_pct": 0, "direction": "FLAT", "breakdown": {}}),
                "optimistic": opt_impacts.get(cc, {"change_pct": 0, "direction": "FLAT", "breakdown": {}}),
                "pessimistic": pess_impacts.get(cc, {"change_pct": 0, "direction": "FLAT", "breakdown": {}}),
            }

    base_med = baseline_median
    opt_med = [round(v * opt_mult) for v in baseline_median]
    pess_med = [round(v * pess_mult) for v in baseline_median]
    base_p10 = baseline_p10
    base_p90 = baseline_p90
    opt_p10 = [round(v * opt_mult) for v in baseline_p10]
    opt_p90 = [round(v * opt_mult) for v in baseline_p90]
    pess_p10 = [round(v * pess_mult) for v in baseline_p10]
    pess_p90 = [round(v * pess_mult) for v in baseline_p90]

    return {
        "status": "ok",
        "model": "GP" if gp_model_used else "fallback",
        "months": months,
        "scenarios": {
            "base": {
                "label": "ベース",
                "color": "#4a9eff",
                "median": base_med,
                "p10": base_p10,
                "p90": base_p90,
                "total_change_pct": 0.0,
            },
            "optimistic": {
                "label": "楽観",
                "color": "#51cf66",
                "median": opt_med,
                "p10": opt_p10,
                "p90": opt_p90,
                "total_change_pct": round((opt_mult - 1.0) * 100.0, 1),
            },
            "pessimistic": {
                "label": "悲観",
                "color": "#ff4d4d",
                "median": pess_med,
                "p10": pess_p10,
                "p90": pess_p90,
                "total_change_pct": round((pess_mult - 1.0) * 100.0, 1),
            },
        },
        "country_impacts": country_impacts,
    }


@router.get("/fx-exposure")
async def get_fx_exposure(
    month: int = Query(default=4, ge=1, le=12),
    year: int = Query(default=2026),
):
    """通貨別FXエクスポージャー台帳 (IFRS 9対応)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        cache_key = f"fx_exp_{year}_{month}"
        result = await loop.run_in_executor(
            None, lambda: _get_cached(cache_key, lambda: _full_mc_engine.fx_exposure(month, year))
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/var-cvar")
async def get_var_cvar(
    month: int = Query(default=4, ge=1, le=12),
    year: int = Query(default=2026),
    confidence: float = Query(default=0.99, ge=0.90, le=0.999),
):
    """VaR/CVaR計算 (モンテカルロ法)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        cache_key = f"var_{year}_{month}_{confidence}"
        result = await loop.run_in_executor(
            None, lambda: _get_cached(cache_key, lambda: _full_mc_engine.compute_var_cvar(month, year, confidence))
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/optimal-hedge")
async def get_optimal_hedge(
    month: int = Query(default=4, ge=1, le=12),
    year: int = Query(default=2026),
):
    """ヘッジ比率最適化 (policy制約30-70%)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        cache_key = f"opt_hedge_{year}_{month}"
        result = await loop.run_in_executor(
            None, lambda: _get_cached(cache_key, lambda: _full_mc_engine.optimal_hedge_ratio(month, year))
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hedge-effectiveness")
async def get_hedge_effectiveness(
    hedge_notional_jpy: float = Query(default=3000e8, gt=0),
    hedged_item_pct: float = Query(default=1.0, gt=0, le=1.0),
    fx_sensitivity: float = Query(default=0.8, gt=0, le=2.0),
):
    """IFRS 9ヘッジ有効性テスト (80-125%ルール)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        months = [f"2024/{m:02d}" for m in range(1, 13)]
        result = await loop.run_in_executor(
            None, lambda: _full_mc_engine.hedge_effectiveness_test(months, hedge_notional_jpy, hedged_item_pct, fx_sensitivity)
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fx-forward")
async def get_fx_forward(currency: str = "USD", tenor_months: int = 3):
    """FXフォワード理論価格 (IRP)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        return {"status": "ok", **_full_mc_engine.fx_forward_price(currency, tenor_months)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fx-option")
async def get_fx_option(currency: str = "USD", tenor_months: int = 3, strike_pct: float = 1.0, is_call: bool = False, iv: float = 0.10):
    """Black-Scholes FXオプション価格"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        return {"status": "ok", **_full_mc_engine.fx_option_price_bs(currency, tenor_months, strike_pct, is_call, iv)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fx-vol")
async def get_fx_vol(currency: str = "USD"):
    """IV vs RV分析"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        return {"status": "ok", **_full_mc_engine.fx_vol_analysis(currency)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pair-trading")
async def get_pair_trading(country_a: str = "KR", country_b: str = "TW", window: int = 24):
    """ペアトレード信号 (z-score, half-life)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: _full_mc_engine.pair_trading_signal(country_a, country_b, window))
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rolling-correlation")
async def get_rolling_corr(country_a: str = "KR", country_b: str = "TW", window: int = 12):
    """時変相関 (レジーム変化検出)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: _full_mc_engine.rolling_correlation(country_a, country_b, window))
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/basis-risk")
async def get_basis_risk():
    """ベーシスリスク分析 (JNTO vs 自社実績)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _full_mc_engine.basis_risk_analysis)
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customer-hedge")
async def get_customer_hedge(
    usd_jpy: float = Query(default=1e8),
    krw_jpy: float = Query(default=2e8),
    cny_jpy: float = Query(default=5e8),
    twd_jpy: float = Query(default=3e8),
    aud_jpy: float = Query(default=5e7),
):
    """顧客別ヘッジ推奨 (地銀RM向け)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        breakdown = {"USD": usd_jpy, "KRW": krw_jpy, "CNY": cny_jpy, "TWD": twd_jpy, "AUD": aud_jpy}
        breakdown = {k:v for k,v in breakdown.items() if v >= 1e7}
        result = _full_mc_engine.customer_hedge_recommendation(breakdown)
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hedge-documentation")
async def create_hedge_doc(
    hedged_item: str = "外貨建てインバウンド売上",
    hedging_instrument: str = "為替フォワード売り (USD/JPY, KRW/JPY他)",
    hedge_ratio: float = 0.7,
    risk_objective: str = "為替変動リスクの低減",
    designated_by: str = "treasury@company.com",
):
    """IFRS 9ヘッジ指定文書作成 (監査対応)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        doc = _full_mc_engine.create_hedge_documentation(
            hedged_item, hedging_instrument, hedge_ratio, risk_objective, designated_by=designated_by
        )
        return {"status": "ok", "document": doc}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dollar-offset-test")
async def dollar_offset(
    hedged_item_pnl: str = "[-120,150,-80,90,-40,60,-100,120,-70,80,-30,50]",
    hedging_instrument_pnl: str = "[115,-145,78,-88,38,-58,98,-118,68,-78,29,-48]",
):
    """Dollar Offset累積相殺テスト (IFRS 9 B6.4.4.b)"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import json
        h_pnl = json.loads(hedged_item_pnl)
        hi_pnl = json.loads(hedging_instrument_pnl)
        result = _full_mc_engine.dollar_offset_test(h_pnl, hi_pnl)
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auto-calibrate")
async def get_auto_calibrate():
    """バックテスト結果に基づくidioパラメータ自動校正"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _full_mc_engine.auto_calibrate)
        # Re-run backtest after calibration
        bt_after = await loop.run_in_executor(
            None, lambda: _full_mc_engine.backtest([f"2024/{m:02d}" for m in range(1, 13)], "ALL")
        )
        return {
            "status": "ok",
            "adjustments": result,
            "backtest_after": bt_after,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model-diagnostics")
async def get_model_diagnostics():
    """モデル診断情報（バックテスト + 相関行列 + 設定）"""
    if _full_mc_engine is None:
        raise HTTPException(status_code=503, detail="MCエンジン未初期化")
    try:
        import asyncio
        from features.tourism.variable_distributions import SPECS, VAR_NAMES, N_VARS
        from features.tourism.full_mc_engine import FX_ELA, GDP_ELA, FLT_ELA, GEO_COEF, PARAMS

        loop = asyncio.get_event_loop()
        bt = await loop.run_in_executor(
            None, lambda: _get_cached("diagnostics_bt", lambda: _full_mc_engine.backtest(
                [f"2024/{m:02d}" for m in range(1, 13)], "ALL"
            ))
        )
        corr = _full_mc_engine.correlation_health()

        return {
            "status": "ok",
            "model": {
                "name": "FullMCEngine",
                "type": "29変数相関モンテカルロシミュレーション",
                "n_samples": _full_mc_engine.n_samples,
                "n_variables": N_VARS,
                "correlation_method": "Higham (2002) nearest correlation matrix",
                "countries": list(PARAMS.keys()),
            },
            "elasticities": {
                "fx": dict(FX_ELA),
                "gdp": GDP_ELA,
                "flight": FLT_ELA,
                "geopolitical": GEO_COEF,
            },
            "variables": {v: {"label": SPECS[v].name, "sigma": SPECS[v].sigma} for v in VAR_NAMES},
            "correlation_health": corr,
            "backtest_2024": bt,
            "references": [
                "Santos Silva & Tenreyro (2006) - PPML gravity model",
                "Higham (2002) - Nearest correlation matrix",
                "Crouch (1994) - Tourism demand elasticities",
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache-status")
async def get_cache_status():
    now = _time.time()
    entries = {}
    for k, v in _cache.items():
        entries[k] = {"age_seconds": round(now - v["ts"], 1), "expired": now - v["ts"] >= _CACHE_TTL}
    return {"cache_entries": len(_cache), "ttl_seconds": _CACHE_TTL, "entries": entries}
