"""Tourism API Routes — SCRI v1.3.0 ROLE-E
インバウンド観光リスク評価・市場ランキング・訪問者数予測・競合分析・地域分布

GET  /api/v1/tourism/market-risk/{source_country}
GET  /api/v1/tourism/market-ranking
POST /api/v1/tourism/forecast
GET  /api/v1/tourism/competitor-analysis
POST /api/v1/tourism/regional-distribution
POST /api/v1/tourism/decompose
"""
import logging
from datetime import datetime
from typing import Optional

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
