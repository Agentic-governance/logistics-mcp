"""FastAPI - Supply Chain Risk Intelligence API
24次元リスク評価 + 個別データソースエンドポイント
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.requests import Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import time

# STREAM 9: Server start time for uptime tracking
_SERVER_START_TIME = time.time()

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
# STREAM 4-C: In-memory rate limiter (backup for endpoints without slowapi decorators)
from api.rate_limiter import RateLimiter, RateLimitExceededError, classify_endpoint
_rate_limiter = RateLimiter()

from pipeline.db import Session, engine, Base, SanctionedEntity, SanctionsMetadata, ScreeningLog
from pipeline.sanctions.screener import screen_entity
from pipeline.gdelt.monitor import RiskAlert
from pipeline.scheduler import MonitoredSupplier

# Ensure all tables exist
Base.metadata.create_all(engine)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    """Application lifespan: start scheduler on startup, stop on shutdown."""
    scheduler_instance = None
    try:
        from features.timeseries.scheduler import RiskScoreScheduler
        sched = RiskScoreScheduler()
        scheduler_instance = sched.start()
        if scheduler_instance:
            import logging
            logging.getLogger(__name__).info("Scheduler started via lifespan")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Scheduler startup failed: {e}")
    yield
    if scheduler_instance:
        try:
            scheduler_instance.shutdown(wait=False)
        except Exception:
            pass

app = FastAPI(
    title="Supply Chain Risk Intelligence",
    description="24次元パッシブ型サプライチェーンリスク検知プラットフォーム",
    version="0.9.0",
    lifespan=lifespan,
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- SCRI統一エラーハンドラー ---
try:
    from features.errors.error_types import SCRIError, DataSourceError, ValidationError, InferenceError, GraphError

    @app.exception_handler(ValidationError)
    async def scri_validation_error_handler(request: Request, exc: ValidationError):
        """バリデーションエラー → 400"""
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": exc.to_dict()},
        )

    @app.exception_handler(DataSourceError)
    async def scri_datasource_error_handler(request: Request, exc: DataSourceError):
        """データソースエラー → 502"""
        return JSONResponse(
            status_code=502,
            content={"success": False, "error": exc.to_dict()},
        )

    @app.exception_handler(InferenceError)
    async def scri_inference_error_handler(request: Request, exc: InferenceError):
        """推論エラー → 422"""
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": exc.to_dict()},
        )

    @app.exception_handler(GraphError)
    async def scri_graph_error_handler(request: Request, exc: GraphError):
        """グラフエラー → 500"""
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": exc.to_dict()},
        )

    @app.exception_handler(SCRIError)
    async def scri_base_error_handler(request: Request, exc: SCRIError):
        """SCRI汎用エラー → 500"""
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": exc.to_dict()},
        )
except ImportError:
    pass  # features.errors モジュールが利用不可

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.middleware.sanitizer import InputSanitizationMiddleware
app.add_middleware(InputSanitizationMiddleware)

# STREAM 9: Prometheus metrics middleware
from server.middleware.metrics import MetricsMiddleware, metrics_response, get_total_requests_served
app.add_middleware(MetricsMiddleware)

from server.middleware.response_formatter import ResponseFormatterMiddleware
app.add_middleware(ResponseFormatterMiddleware)


# --- Router Includes ---
from api.routes.batch import router as batch_router
from api.routes.webhooks import router as webhooks_router
from api.routes.bom import router as bom_router
from api.routes.internal import router as internal_router
from api.routes.twin import router as twin_router
app.include_router(batch_router)
app.include_router(webhooks_router)
app.include_router(bom_router)
app.include_router(internal_router)
app.include_router(twin_router)

# --- STREAM v1.4.0: Dashboard API Router ---
try:
    from api.routes.dashboard_api import router as dashboard_api_router
    app.include_router(dashboard_api_router)
except ImportError:
    pass  # dashboard_api モジュール未インストール

# --- STREAM v1.3.0: Tourism Router (ROLE-E) ---
try:
    from api.routes.tourism import router as tourism_router
    app.include_router(tourism_router)
except ImportError:
    pass  # tourism モジュール未インストール

# --- STREAM E-1: GraphQL Router ---
try:
    from api.graphql_schema import graphql_router
    app.include_router(graphql_router, prefix="/graphql")
except ImportError:
    pass  # strawberry-graphql not installed

# --- STREAM E-2: WebSocket Alerts ---
from fastapi import WebSocket, WebSocketDisconnect
from api.websocket_alerts import broadcaster, handle_client_message

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """リアルタイムリスクアラート WebSocket エンドポイント"""
    await broadcaster.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await handle_client_message(websocket, data)
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)


# --- Pydantic Models ---

class ScreenRequest(BaseModel):
    company_name: str
    country: Optional[str] = None


class BulkScreenRequest(BaseModel):
    companies: list[ScreenRequest]


class MonitorRequest(BaseModel):
    supplier_id: str
    company_name: str
    location: str


# --- Health ---

@app.get("/health")
@limiter.limit("60/minute")
def health(request: Request):
    """ヘルスチェック（制裁ソースステータス・アラート件数・データ鮮度・予測モデル・相関・カバレッジ・稼働時間）"""
    import json as _json

    result = {
        "status": "ok",
        "version": "0.9.0",
        "dimensions": 24,
        "mcp_tools": 32,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # --- 制裁ソースステータス ---
    try:
        with Session() as session:
            metadata = session.query(SanctionsMetadata).all()
            sources = {}
            for m in metadata:
                sources[m.source] = {
                    "status": "ok",
                    "records": m.record_count or 0,
                    "last_updated": m.last_fetched.isoformat() if m.last_fetched else None,
                }
            try:
                from pipeline.sanctions.seco import cache_status
                seco_status = cache_status()
                if "seco" in sources:
                    sources["seco"]["cache_mode"] = True
                    sources["seco"]["cache_entries"] = seco_status["cached_entries"]
            except Exception:
                pass
            result["sanctions_sources"] = sources
    except Exception:
        result["sanctions_sources"] = {"status": "unavailable"}

    # --- アラート件数 ---
    try:
        with Session() as session:
            active_alerts = session.query(RiskAlert).filter(
                RiskAlert.created_at >= datetime.utcnow() - timedelta(hours=24),
            ).count()
        result["active_alerts"] = active_alerts
    except Exception:
        result["active_alerts"] = 0

    # --- データ鮮度 ---
    try:
        from features.monitoring.anomaly_detector import _load_history
        history = _load_history()
        stale_dims = []
        oldest_source = None
        oldest_age = 0
        for loc, data in history.items():
            updated = data.get("updated_at")
            if updated:
                age_hours = (datetime.utcnow() - datetime.fromisoformat(updated)).total_seconds() / 3600
                if age_hours > oldest_age:
                    oldest_age = age_hours
                    oldest_source = f"{loc} ({age_hours:.0f}h ago)"
        result["data_staleness"] = {
            "stale_dimensions": stale_dims,
            "oldest_source": oldest_source,
        }
    except Exception:
        result["data_staleness"] = {"stale_dimensions": [], "oldest_source": None}

    # --- 最終スコア実行 ---
    try:
        from features.monitoring.anomaly_detector import _load_history
        history = _load_history()
        if history:
            latest = max(
                (data.get("updated_at", "") for data in history.values()),
                default=None,
            )
            result["last_score_run"] = latest
    except Exception:
        pass

    # --- STREAM 9: forecast_model_status ---
    try:
        from features.timeseries.store import RiskTimeSeriesStore
        store = RiskTimeSeriesStore()
        # Check if we have enough data points for forecasting
        sample = store.get_latest("Japan")
        if sample:
            result["forecast_model_status"] = "ready"
        else:
            result["forecast_model_status"] = "insufficient_data"
    except Exception:
        result["forecast_model_status"] = "error"

    # --- STREAM 9: correlation_last_checked & high_correlation_alerts ---
    try:
        corr_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "correlation_history.jsonl",
        )
        if os.path.exists(corr_path):
            with open(corr_path, "r") as fh:
                lines = fh.readlines()
            if lines:
                last_entry = _json.loads(lines[-1].strip())
                result["correlation_last_checked"] = last_entry.get("timestamp")
                # Count r>0.85 pairs that are NOT accepted
                high_pairs = last_entry.get("high_r_pairs", [])
                non_accepted = sum(
                    1 for p in high_pairs
                    if abs(p.get("r", 0)) > 0.85 and not p.get("accepted", False)
                )
                result["high_correlation_alerts"] = non_accepted
            else:
                result["correlation_last_checked"] = None
                result["high_correlation_alerts"] = 0
        else:
            result["correlation_last_checked"] = None
            result["high_correlation_alerts"] = 0
    except Exception:
        result["correlation_last_checked"] = None
        result["high_correlation_alerts"] = 0

    # --- STREAM 9: coverage ---
    try:
        from features.timeseries.store import RiskTimeSeriesStore
        store = RiskTimeSeriesStore()
        from features.timeseries.scheduler import PRIORITY_COUNTRIES
        full_data = 0
        partial_data = 0
        for country in PRIORITY_COUNTRIES:
            latest = store.get_latest(country)
            if latest and latest.get("overall_score") is not None:
                full_data += 1
            elif latest:
                partial_data += 1
        result["coverage"] = {
            "countries_with_full_data": full_data,
            "countries_with_partial_data": partial_data,
            "total_countries": 50,
        }
    except Exception:
        result["coverage"] = {
            "countries_with_full_data": 0,
            "countries_with_partial_data": 0,
            "total_countries": 50,
        }

    # --- STREAM 9: uptime_seconds ---
    result["uptime_seconds"] = round(time.time() - _SERVER_START_TIME, 1)

    # --- STREAM 9: total_requests_served ---
    result["total_requests_served"] = get_total_requests_served()

    return result


# --- STREAM 9: Prometheus metrics endpoint ---

@app.get("/metrics")
def prometheus_metrics():
    """Prometheus互換メトリクスエンドポイント"""
    return metrics_response()


# --- Sanctions Screening ---

@app.post("/api/v1/screen")
@limiter.limit("30/minute")
def screen_sanctions(request: Request, req: ScreenRequest):
    """単一企業の制裁リストスクリーニング"""
    result = screen_entity(req.company_name, req.country)
    return {
        "company_name": req.company_name,
        "matched": result.matched,
        "match_score": result.match_score,
        "source": result.source,
        "matched_entity": result.matched_entity,
        "evidence": result.evidence,
        "screened_at": datetime.utcnow().isoformat(),
    }


@app.post("/api/v1/screen/bulk")
@limiter.limit("30/minute")
def bulk_screen(request: Request, req: BulkScreenRequest):
    """複数企業の一括スクリーニング"""
    results = []
    matched_count = 0
    for company in req.companies:
        result = screen_entity(company.company_name, company.country)
        results.append({
            "company_name": company.company_name,
            "country": company.country,
            "matched": result.matched,
            "match_score": result.match_score,
            "source": result.source,
            "evidence": result.evidence,
        })
        if result.matched:
            matched_count += 1
    return {"total_screened": len(results), "matched_count": matched_count, "results": results}


# --- Risk Scoring (24次元) ---

@app.get("/api/v1/risk/{supplier_id}")
@limiter.limit("60/minute")
def get_risk_score(
    request: Request,
    supplier_id: str,
    company_name: str = Query(...),
    country: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
):
    """24次元総合リスクスコア取得"""
    from scoring.engine import calculate_risk_score
    score = calculate_risk_score(supplier_id, company_name, country, location)
    return score.to_dict()


# ====================================================================
# Individual Data Source Endpoints
# ====================================================================

# --- Disaster ---

@app.get("/api/v1/disasters/global")
@limiter.limit("60/minute")
def get_global_disasters(request: Request):
    """GDACS: グローバル災害アラート"""
    try:
        from pipeline.disaster.gdacs_client import fetch_gdacs_alerts
        events = fetch_gdacs_alerts()
        return {
            "count": len(events),
            "events": [
                {"id": e.event_id, "type": e.event_type, "title": e.title,
                 "severity": e.severity, "country": e.country,
                 "lat": e.lat, "lon": e.lon, "date": e.event_date}
                for e in events
            ],
            "source": "GDACS",
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GDACS fetch failed: {e}")


@app.get("/api/v1/disasters/earthquakes")
@limiter.limit("60/minute")
def get_earthquakes(
    request: Request,
    min_magnitude: float = Query(4.5),
    days: int = Query(7, ge=1, le=30),
):
    """USGS: 地震データ"""
    try:
        from pipeline.disaster.usgs_client import fetch_earthquakes
        quakes = fetch_earthquakes(min_magnitude=min_magnitude, days_back=days)
        return {"count": len(quakes), "earthquakes": quakes, "source": "USGS"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"USGS fetch failed: {e}")


# --- Maritime ---

@app.get("/api/v1/maritime/disruptions")
@limiter.limit("60/minute")
def get_maritime_disruptions(request: Request):
    """IMF PortWatch: 港湾途絶イベント"""
    try:
        from pipeline.maritime.portwatch_client import fetch_active_disruptions
        disruptions = fetch_active_disruptions()
        return {"count": len(disruptions), "disruptions": disruptions, "source": "IMF PortWatch"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"PortWatch fetch failed: {e}")


@app.get("/api/v1/maritime/port-activity")
@limiter.limit("60/minute")
def get_port_activity(
    request: Request,
    port_name: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=90),
):
    """IMF PortWatch: 港湾活動データ"""
    try:
        from pipeline.maritime.portwatch_client import fetch_port_activity
        activity = fetch_port_activity(port_name=port_name, country=country, days_back=days)
        return {"count": len(activity), "activity": activity, "source": "IMF PortWatch"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"PortWatch fetch failed: {e}")


@app.get("/api/v1/maritime/congestion/{region}")
@limiter.limit("60/minute")
def get_shipping_congestion(request: Request, region: str):
    """AIS: 航路混雑状況"""
    try:
        from pipeline.maritime.ais_client import get_shipping_lane_congestion
        result = get_shipping_lane_congestion(region)
        return {"region": region, **result, "source": "AISHub"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AIS fetch failed: {e}")


@app.get("/api/v1/maritime/port-congestion/{location}")
@limiter.limit("60/minute")
def get_port_congestion(request: Request, location: str):
    """港湾混雑・チョークポイントリスク"""
    try:
        from pipeline.infrastructure.port_congestion_client import get_port_congestion_risk
        result = get_port_congestion_risk(location)
        return {"location": location, **result, "source": "UNCTAD/港湾統計"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Conflict ---

@app.get("/api/v1/conflict/{location}")
@limiter.limit("60/minute")
def get_conflict_risk(request: Request, location: str):
    """ACLED: 紛争・政治暴力リスク"""
    try:
        from pipeline.conflict.acled_client import get_conflict_risk_for_location
        result = get_conflict_risk_for_location(location)
        return {"location": location, **result, "source": "ACLED"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Economic ---

@app.get("/api/v1/economic/{location}")
@limiter.limit("60/minute")
def get_economic_risk(request: Request, location: str):
    """World Bank: 経済リスク指標"""
    try:
        from pipeline.economic.worldbank_client import get_economic_risk_for_location
        result = get_economic_risk_for_location(location)
        return {"location": location, **result, "source": "World Bank"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/economic/profile/{location}")
@limiter.limit("60/minute")
def get_economic_profile(request: Request, location: str):
    """World Bank: 経済プロファイル"""
    try:
        from pipeline.economic.worldbank_client import get_economic_profile
        profile = get_economic_profile(location)
        return {"location": location, **profile, "source": "World Bank"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/currency/{location}")
@limiter.limit("60/minute")
def get_currency_risk(request: Request, location: str):
    """通貨ボラティリティリスク"""
    try:
        from pipeline.economic.currency_client import get_currency_risk_for_location
        result = get_currency_risk_for_location(location)
        return {"location": location, **result, "source": "Frankfurter/ECB"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/trade/{location}")
@limiter.limit("60/minute")
def get_trade_risk(request: Request, location: str):
    """UN Comtrade: 貿易依存リスク"""
    try:
        from pipeline.trade.comtrade_client import get_trade_dependency_risk
        result = get_trade_dependency_risk(location)
        return {"location": location, **result, "source": "UN Comtrade"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/energy/commodities")
@limiter.limit("60/minute")
def get_commodity_prices(request: Request):
    """FRED: コモディティ価格"""
    try:
        from pipeline.energy.commodity_client import get_energy_risk
        result = get_energy_risk()
        return {**result, "source": "FRED/EIA"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Health ---

@app.get("/api/v1/health/{location}")
@limiter.limit("60/minute")
def get_health_risk(request: Request, location: str):
    """Disease.sh: 感染症リスク"""
    try:
        from pipeline.health.disease_client import get_health_risk_for_location
        result = get_health_risk_for_location(location)
        return {"location": location, **result, "source": "Disease.sh"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/humanitarian/{location}")
@limiter.limit("60/minute")
def get_humanitarian_risk(request: Request, location: str):
    """ReliefWeb: 人道危機リスク"""
    try:
        from pipeline.health.reliefweb_client import get_humanitarian_risk_for_location
        result = get_humanitarian_risk_for_location(location)
        return {"location": location, **result, "source": "ReliefWeb/OCHA"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/food-security/{location}")
@limiter.limit("60/minute")
def get_food_security(request: Request, location: str):
    """WFP: 食料安全保障リスク"""
    try:
        from pipeline.food.wfp_client import get_food_security_risk
        result = get_food_security_risk(location)
        return {"location": location, **result, "source": "WFP HungerMap"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Weather ---

@app.get("/api/v1/weather/{location}")
@limiter.limit("60/minute")
def get_weather_risk(request: Request, location: str):
    """Open-Meteo: 気象リスク"""
    try:
        from pipeline.weather.openmeteo_client import get_weather_risk_by_name
        result = get_weather_risk_by_name(location)
        return {"location": location, **result, "source": "Open-Meteo"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/weather/typhoon/{location}")
@limiter.limit("60/minute")
def get_typhoon_risk(request: Request, location: str):
    """NOAA: 台風・宇宙天気リスク"""
    try:
        from pipeline.weather.openmeteo_client import _resolve_coords
        from pipeline.weather.typhoon_client import get_typhoon_risk_for_location
        coords = _resolve_coords(location)
        if not coords:
            return {"location": location, "score": 0, "evidence": ["座標不明"]}
        result = get_typhoon_risk_for_location(coords[0], coords[1], location)
        return {"location": location, **result, "source": "NOAA NHC/SWPC"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/weather/space")
@limiter.limit("60/minute")
def get_space_weather(request: Request):
    """NOAA SWPC: 宇宙天気データ"""
    try:
        from pipeline.weather.typhoon_client import fetch_space_weather
        result = fetch_space_weather()
        return {**result, "source": "NOAA SWPC"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Compliance ---

@app.get("/api/v1/compliance/{location}")
@limiter.limit("60/minute")
def get_compliance_risk(request: Request, location: str):
    """FATF/INFORM/TI-CPI: コンプライアンスリスク"""
    try:
        from pipeline.compliance.fatf_client import get_compliance_risk_for_location
        result = get_compliance_risk_for_location(location)
        return {"location": location, **result, "source": "FATF/INFORM/TI-CPI"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/compliance/political/{location}")
@limiter.limit("60/minute")
def get_political_risk(request: Request, location: str):
    """Freedom House/FSI: 政治リスク"""
    try:
        from pipeline.compliance.political_client import get_political_risk_for_location
        result = get_political_risk_for_location(location)
        return {"location": location, **result, "source": "Freedom House/FSI"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/compliance/labor/{location}")
@limiter.limit("60/minute")
def get_labor_risk(request: Request, location: str):
    """DoL ILAB/GSI: 労働リスク"""
    try:
        from pipeline.compliance.labor_client import get_labor_risk_for_location
        result = get_labor_risk_for_location(location)
        return {"location": location, **result, "source": "DoL ILAB/GSI"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Infrastructure ---

@app.get("/api/v1/infrastructure/internet/{location}")
@limiter.limit("60/minute")
def get_internet_risk(request: Request, location: str):
    """Cloudflare Radar/IODA: インターネットインフラリスク"""
    try:
        from pipeline.infrastructure.internet_client import get_internet_risk_for_location
        result = get_internet_risk_for_location(location)
        return {"location": location, **result, "source": "Cloudflare Radar/IODA"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Aviation ---

@app.get("/api/v1/aviation/{location}")
@limiter.limit("60/minute")
def get_aviation_activity(request: Request, location: str):
    """OpenSky: 航空交通活動"""
    try:
        from pipeline.aviation.opensky_client import get_aviation_risk_for_location
        result = get_aviation_risk_for_location(location)
        return {"location": location, **result, "source": "OpenSky Network"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Japan Specific ---

@app.get("/api/v1/japan/economy")
@limiter.limit("60/minute")
def get_japan_economy(request: Request):
    """BOJ/e-Stat: 日本経済指標"""
    try:
        from pipeline.japan.estat_client import get_japan_economic_indicators
        result = get_japan_economic_indicators()
        return {**result, "source": "BOJ/ExchangeRate-API"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ====================================================================
# Global Risk Dashboard
# ====================================================================

@app.get("/api/v1/dashboard/global")
@limiter.limit("60/minute")
def global_risk_dashboard(request: Request):
    """グローバルリスクダッシュボード（全データソース統合）"""
    dashboard = {
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.4.0",
        "dimensions": 24,
        "sources": {},
    }

    # GDACS: 災害
    try:
        from pipeline.disaster.gdacs_client import fetch_gdacs_alerts
        events = fetch_gdacs_alerts()
        red_alerts = [e for e in events if e.severity == "Red"]
        orange_alerts = [e for e in events if e.severity == "Orange"]
        dashboard["sources"]["gdacs"] = {
            "status": "ok",
            "total_events": len(events),
            "red_alerts": len(red_alerts),
            "orange_alerts": len(orange_alerts),
            "top_events": [
                {"title": e.title, "severity": e.severity, "country": e.country}
                for e in (red_alerts + orange_alerts)[:5]
            ],
        }
    except Exception as e:
        dashboard["sources"]["gdacs"] = {"status": "error", "error": str(e)}

    # USGS: 地震
    try:
        from pipeline.disaster.usgs_client import fetch_significant_earthquakes
        quakes = fetch_significant_earthquakes()
        dashboard["sources"]["usgs"] = {
            "status": "ok",
            "significant_earthquakes_month": len(quakes),
            "top_quakes": [
                {"magnitude": q["magnitude"], "place": q["place"], "time": q["time"]}
                for q in quakes[:5]
            ],
        }
    except Exception as e:
        dashboard["sources"]["usgs"] = {"status": "error", "error": str(e)}

    # Typhoon/Space Weather
    try:
        from pipeline.weather.typhoon_client import fetch_active_tropical_cyclones, fetch_space_weather
        storms = fetch_active_tropical_cyclones()
        space = fetch_space_weather()
        dashboard["sources"]["noaa"] = {
            "status": "ok",
            "active_storms": len(storms),
            "storms": [{"name": s["name"], "basin": s["basin"], "wind_mph": s.get("wind_mph")}
                       for s in storms[:5]],
            "kp_index": space.get("kp_index"),
            "solar_wind_speed": space.get("solar_wind_speed"),
            "space_alerts": len(space.get("alerts", [])),
        }
    except Exception as e:
        dashboard["sources"]["noaa"] = {"status": "error", "error": str(e)}

    # PortWatch: 海上途絶
    try:
        from pipeline.maritime.portwatch_client import fetch_active_disruptions
        disruptions = fetch_active_disruptions()
        dashboard["sources"]["portwatch"] = {
            "status": "ok",
            "active_disruptions": len(disruptions),
            "disruptions": [
                {"name": d["name"], "type": d["type"],
                 "trade_impact_pct": d.get("trade_impact_pct")}
                for d in disruptions[:5]
            ],
        }
    except Exception as e:
        dashboard["sources"]["portwatch"] = {"status": "error", "error": str(e)}

    # COVID global
    try:
        from pipeline.health.disease_client import fetch_covid_global
        covid = fetch_covid_global()
        dashboard["sources"]["covid"] = {
            "status": "ok",
            "active_global": covid.get("active", 0),
            "today_cases": covid.get("today_cases", 0),
            "critical": covid.get("critical", 0),
        }
    except Exception as e:
        dashboard["sources"]["covid"] = {"status": "error", "error": str(e)}

    # Japan Economy
    try:
        from pipeline.japan.estat_client import fetch_boj_exchange_rate
        fx = fetch_boj_exchange_rate()
        if "rates" in fx:
            dashboard["sources"]["japan_economy"] = {
                "status": "ok",
                "usd_jpy": fx["rates"].get("USD"),
                "eur_jpy": fx["rates"].get("EUR"),
                "cny_jpy": fx["rates"].get("CNY"),
            }
    except Exception:
        pass

    # DB Stats
    try:
        with Session() as session:
            dashboard["db"] = {
                "sanctions_entities": session.query(SanctionedEntity).filter_by(is_active=True).count(),
                "monitored_suppliers": session.query(MonitoredSupplier).filter_by(is_active=True).count(),
                "active_alerts": session.query(RiskAlert).count(),
            }
    except Exception:
        dashboard["db"] = {"status": "error"}

    return dashboard


# --- Alerts ---

@app.get("/api/v1/alerts")
@limiter.limit("60/minute")
def get_alerts(
    request: Request,
    since_hours: int = Query(24, ge=1, le=720),
    min_score: int = Query(50, ge=0, le=100),
):
    """リスクアラート一覧"""
    since = datetime.utcnow() - timedelta(hours=since_hours)
    with Session() as session:
        alerts = session.query(RiskAlert).filter(
            RiskAlert.created_at >= since,
            RiskAlert.score >= min_score
        ).order_by(RiskAlert.created_at.desc()).limit(50).all()
        return {
            "count": len(alerts),
            "alerts": [
                {"id": a.id, "supplier": a.company_name, "type": a.alert_type,
                 "severity": a.severity, "score": a.score, "title": a.title,
                 "description": a.description, "created_at": a.created_at.isoformat()}
                for a in alerts
            ],
        }


# --- Monitoring ---

@app.post("/api/v1/monitor")
@limiter.limit("60/minute")
def register_monitor(request: Request, req: MonitorRequest):
    """サプライヤー監視登録"""
    with Session() as session:
        supplier = MonitoredSupplier(
            supplier_id=req.supplier_id,
            company_name=req.company_name,
            location=req.location,
        )
        session.merge(supplier)
        session.commit()

    return {
        "status": "registered",
        "supplier_id": req.supplier_id,
        "monitoring": {
            "interval": "15 minutes",
            "dimensions": 24,
            "sources": [
                "OFAC", "EU", "UN", "OpenSanctions", "GDELT",
                "GDACS", "USGS", "FIRMS", "JMA", "PortWatch",
                "ACLED", "WorldBank", "Frankfurter/ECB", "Disease.sh",
                "ReliefWeb", "Open-Meteo", "NOAA", "FATF", "WFP",
                "UN Comtrade", "Cloudflare Radar", "Freedom House",
                "DoL ILAB", "OpenSky", "FRED",
            ],
        },
    }


@app.get("/api/v1/monitors")
@limiter.limit("60/minute")
def list_monitors(request: Request):
    """監視対象サプライヤー一覧"""
    with Session() as session:
        suppliers = session.query(MonitoredSupplier).filter_by(is_active=True).all()
        return {
            "count": len(suppliers),
            "suppliers": [
                {"supplier_id": s.supplier_id, "company_name": s.company_name,
                 "location": s.location}
                for s in suppliers
            ],
        }


# --- Stats ---

@app.get("/api/v1/stats")
@limiter.limit("60/minute")
def get_stats(request: Request):
    """DB統計 + データソースステータス"""
    with Session() as session:
        entity_count = session.query(SanctionedEntity).filter_by(is_active=True).count()
        screening_count = session.query(ScreeningLog).count()
        alert_count = session.query(RiskAlert).count()
        monitor_count = session.query(MonitoredSupplier).filter_by(is_active=True).count()

        metadata = session.query(SanctionsMetadata).all()
        sources = {
            m.source: {
                "record_count": m.record_count,
                "last_fetched": m.last_fetched.isoformat() if m.last_fetched else None,
            }
            for m in metadata
        }

        return {
            "sanctions_entities": entity_count,
            "screenings_performed": screening_count,
            "active_alerts": alert_count,
            "monitored_suppliers": monitor_count,
            "sources": sources,
            "dimensions": 24,
            "data_pipelines": {
                "sanctions": ["OFAC", "EU", "UN", "OpenSanctions", "METI", "BIS",
                              "OFSI", "SECO", "Canada DFATD", "DFAT Australia", "MOFA Japan"],
                "geopolitical": ["GDELT BigQuery"],
                "disaster": ["GDACS", "USGS Earthquake", "NASA FIRMS", "JMA"],
                "maritime": ["IMF PortWatch", "AISHub", "UNCTAD Port Statistics"],
                "conflict": ["ACLED"],
                "economic": ["World Bank", "Frankfurter/ECB", "UN Comtrade"],
                "health": ["Disease.sh", "ReliefWeb/OCHA"],
                "weather": ["Open-Meteo", "NOAA NHC", "NOAA SWPC"],
                "compliance": ["FATF", "INFORM Risk Index", "TI CPI",
                               "Freedom House", "Fragile States Index"],
                "food_security": ["WFP HungerMap"],
                "labor": ["DoL ILAB", "Global Slavery Index", "ILOSTAT"],
                "infrastructure": ["Cloudflare Radar", "IODA"],
                "aviation": ["OpenSky Network"],
                "energy": ["FRED", "EIA"],
                "japan": ["BOJ", "ExchangeRate-API", "e-Stat"],
                "climate": ["ND-GAIN", "GloFAS", "WRI Aqueduct", "Climate TRACE"],
                "cyber": ["OONI", "CISA KEV", "ITU ICT"],
                "regional": ["KOSIS", "Taiwan Trade", "NBS China",
                              "GSO Vietnam", "DOSM Malaysia", "MPA Singapore",
                              "ASEAN Stats", "Eurostat", "AfDB"],
            },
        }


# --- Supply Chain Graph ---

@app.get("/api/v1/graph/{company_name}")
@limiter.limit("60/minute")
def get_graph(
    request: Request,
    company_name: str,
    country_code: str = Query("jp"),
    depth: int = Query(2, ge=1, le=3),
):
    """Tier-N供給網グラフ取得"""
    from pipeline.corporate.graph_builder import build_supply_chain_graph, graph_to_visualization_data
    G = build_supply_chain_graph(company_name, country_code, depth)
    return graph_to_visualization_data(G)


# ====================================================================
# v0.5.1 New Endpoints
# ====================================================================

# --- Route Risk ---

class RouteRiskRequest(BaseModel):
    origin: str
    destination: str


@app.post("/api/v1/route-risk")
@limiter.limit("10/minute")
def analyze_route_risk(request: Request, req: RouteRiskRequest):
    """輸送ルートリスク分析（チョークポイント通過判定+代替ルート）"""
    try:
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        return analyzer.analyze_route(req.origin, req.destination)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/chokepoints")
@limiter.limit("60/minute")
def list_chokepoints(request: Request):
    """7大チョークポイント一覧"""
    from features.route_risk.analyzer import CHOKEPOINTS, RouteRiskAnalyzer
    analyzer = RouteRiskAnalyzer()
    result = []
    for cp_id, cp_info in CHOKEPOINTS.items():
        risk = analyzer.get_chokepoint_risk(cp_id)
        result.append({"id": cp_id, **risk})
    return {"count": len(result), "chokepoints": result}


@app.get("/api/v1/chokepoint/{chokepoint_id}")
@limiter.limit("60/minute")
def get_chokepoint_risk(request: Request, chokepoint_id: str):
    """個別チョークポイントリスク"""
    try:
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        return analyzer.get_chokepoint_risk(chokepoint_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Concentration Risk ---

@app.post("/api/v1/concentration")
@limiter.limit("10/minute")
def analyze_concentration(
    request: Request,
    sector: Optional[str] = Query(None),
):
    """サプライヤー集中リスク分析"""
    try:
        from features.concentration.analyzer import ConcentrationRiskAnalyzer
        analyzer = ConcentrationRiskAnalyzer()
        return analyzer.analyze_supplier_concentration([], sector=sector)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Disruption Simulation ---

@app.get("/api/v1/simulate/{scenario}")
@limiter.limit("60/minute")
def simulate_disruption(request: Request, scenario: str):
    """途絶シミュレーション"""
    try:
        from features.simulation.disruption_simulator import DisruptionSimulator
        simulator = DisruptionSimulator()
        return simulator.simulate_scenario(scenario)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- DD Reports ---

class DDReportRequest(BaseModel):
    entity_name: str
    country: str


@app.post("/api/v1/dd-report")
@limiter.limit("10/minute")
def generate_dd_report(request: Request, req: DDReportRequest):
    """KYSデューデリジェンスレポート生成"""
    try:
        from features.reports.dd_generator import DueDiligenceReportGenerator
        generator = DueDiligenceReportGenerator()
        return generator.generate_report(req.entity_name, req.country)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Commodity Exposure ---

@app.get("/api/v1/commodity/{sector}")
@limiter.limit("60/minute")
def get_commodity_exposure(request: Request, sector: str):
    """コモディティ・エクスポージャー分析"""
    try:
        from features.commodity.exposure_analyzer import CommodityExposureAnalyzer
        analyzer = CommodityExposureAnalyzer()
        return analyzer.calculate_exposure(sector)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Bulk Assessment ---

class BulkAssessRequest(BaseModel):
    csv_data: str
    depth: str = "quick"


@app.post("/api/v1/bulk-assess")
@limiter.limit("10/minute")
def bulk_assess_suppliers(request: Request, req: BulkAssessRequest):
    """一括アセスメント"""
    try:
        from features.bulk_assess import bulk_assess
        return bulk_assess(req.csv_data, assessment_depth=req.depth)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Climate Risk ---

@app.get("/api/v1/climate/{location}")
@limiter.limit("60/minute")
def get_climate_risk(request: Request, location: str):
    """気候リスク（ND-GAIN/GloFAS/WRI/Climate TRACE）"""
    try:
        from scoring.dimensions.climate_scorer import get_climate_risk as _get_climate
        result = _get_climate(location)
        return {"location": location, **result, "source": "ND-GAIN/GloFAS/WRI/Climate TRACE"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Cyber Risk ---

@app.get("/api/v1/cyber/{location}")
@limiter.limit("60/minute")
def get_cyber_risk(request: Request, location: str):
    """サイバーリスク（OONI/CISA KEV/ITU ICT）"""
    try:
        from scoring.dimensions.cyber_scorer import get_cyber_risk as _get_cyber
        result = _get_cyber(location)
        return {"location": location, **result, "source": "OONI/CISA KEV/ITU ICT"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Monitoring / Data Quality ---

@app.get("/api/v1/monitoring/quality")
@limiter.limit("60/minute")
def get_data_quality(request: Request):
    """データ品質ダッシュボード"""
    from features.monitoring.anomaly_detector import (
        ScoreAnomalyDetector, _load_history, FRESHNESS_THRESHOLDS,
    )
    from features.timeseries.scheduler import PRIORITY_COUNTRIES

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "score_coverage": {},
        "recent_anomalies": [],
        "source_health": {},
        "last_full_run": None,
    }

    # Score coverage: 各次元のデータ充足率
    history = _load_history()
    if history:
        from scoring.engine import SupplierRiskScore
        all_dims = list(SupplierRiskScore.WEIGHTS.keys())
        total_locations = len(history)

        for dim in all_dims:
            has_data = sum(
                1 for data in history.values()
                if data.get("scores", {}).get(dim, 0) > 0
            )
            result["score_coverage"][dim] = round(has_data / max(total_locations, 1), 2)

        # last_full_run
        timestamps = [data.get("updated_at") for data in history.values() if data.get("updated_at")]
        if timestamps:
            result["last_full_run"] = max(timestamps)

    # Recent anomalies (from JSONL files)
    import os, json, glob
    alerts_dir = "data/alerts"
    if os.path.exists(alerts_dir):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        for date_str in [today, yesterday]:
            filepath = os.path.join(alerts_dir, f"{date_str}.jsonl")
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r") as f:
                        for line in f:
                            if line.strip():
                                result["recent_anomalies"].append(json.loads(line))
                except Exception:
                    pass

    # Source health (sanctions DB status)
    try:
        with Session() as session:
            metadata = session.query(SanctionsMetadata).all()
            for m in metadata:
                result["source_health"][m.source] = {
                    "status": "ok" if m.record_count and m.record_count > 0 else "empty",
                    "records": m.record_count or 0,
                    "last_fetched": m.last_fetched.isoformat() if m.last_fetched else None,
                }
    except Exception:
        pass

    return result


# --- Analytics ---


@app.get("/api/v1/analytics/overview")
@limiter.limit("60/minute")
def analytics_overview(request: Request):
    """全分析機能の一覧とサンプルリクエストを返すインデックスエンドポイント"""
    return {
        "available_analyses": [
            {
                "name": "portfolio",
                "endpoint": "POST /api/v1/analytics/portfolio",
                "description": "複数サプライヤーのリスクポートフォリオ一括分析・ランク付け",
                "sample_request": {
                    "entities": [
                        {"name": "TSMC", "country": "TW", "tier": 1, "share": 0.35},
                        {"name": "Samsung", "country": "KR", "tier": 1, "share": 0.25},
                    ]
                },
            },
            {
                "name": "correlations",
                "endpoint": "POST /api/v1/analytics/correlations",
                "description": "リスク次元間の相関行列算出・高相関ペア自動抽出",
                "sample_request": {"locations": ["JP", "CN", "KR", "TW", "US"]},
            },
            {
                "name": "benchmark",
                "endpoint": "POST /api/v1/analytics/benchmark/industry",
                "description": "業界平均との相対リスク比較",
                "sample_request": {"entity": {"name": "Test", "country": "JP", "industry": "automotive"}},
            },
            {
                "name": "sensitivity",
                "endpoint": "POST /api/v1/analytics/sensitivity/weights",
                "description": "次元重み感度分析・What-Ifシミュレーション",
                "sample_request": {"location": "CN", "weight_perturbation": 0.05},
            },
        ],
    }


class PortfolioRequest(BaseModel):
    entities: list[dict]
    dimensions: list[str] = []
    include_clustering: bool = False


@app.post("/api/v1/analytics/portfolio")
@limiter.limit("10/minute")
def analyze_portfolio(request: Request, req: PortfolioRequest):
    """複数サプライヤーのリスクポートフォリオ分析"""
    try:
        from features.analytics.portfolio_analyzer import PortfolioAnalyzer
        analyzer = PortfolioAnalyzer()
        report = analyzer.analyze_portfolio(req.entities, req.dimensions or None)
        result = report.to_dict()
        if req.include_clustering and len(req.entities) >= 3:
            result["clusters"] = analyzer.cluster_by_risk(req.entities)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class RankRequest(BaseModel):
    entities: list[dict]
    sort_by: str = "overall"
    ascending: bool = True


@app.post("/api/v1/analytics/portfolio/rank")
@limiter.limit("10/minute")
def rank_portfolio(request: Request, req: RankRequest):
    """サプライヤーリスクランキング"""
    try:
        from features.analytics.portfolio_analyzer import PortfolioAnalyzer
        analyzer = PortfolioAnalyzer()
        return {"ranking": analyzer.rank_suppliers(req.entities, req.sort_by, req.ascending)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class ClusterRequest(BaseModel):
    entities: list[dict]
    n_clusters: int = 3


@app.post("/api/v1/analytics/portfolio/cluster")
@limiter.limit("10/minute")
def cluster_portfolio(request: Request, req: ClusterRequest):
    """サプライヤーリスククラスタリング"""
    try:
        from features.analytics.portfolio_analyzer import PortfolioAnalyzer
        analyzer = PortfolioAnalyzer()
        return {"clusters": analyzer.cluster_by_risk(req.entities, req.n_clusters)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class CorrelationRequest(BaseModel):
    locations: list[str]
    method: str = "pearson"


@app.post("/api/v1/analytics/correlations")
@limiter.limit("10/minute")
def analyze_correlations(request: Request, req: CorrelationRequest):
    """リスク次元間の相関行列"""
    try:
        from features.analytics.correlation_analyzer import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        matrix = analyzer.compute_dimension_correlations(req.locations, req.method)
        return matrix.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class LeadingIndicatorRequest(BaseModel):
    target_dimension: str
    locations: list[str]
    lag_days: int = 30


@app.post("/api/v1/analytics/correlations/leading-indicators")
@limiter.limit("10/minute")
def find_leading_indicators(request: Request, req: LeadingIndicatorRequest):
    """先行指標検出"""
    try:
        from features.analytics.correlation_analyzer import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        indicators = analyzer.find_leading_indicators(req.target_dimension, req.locations, req.lag_days)
        return {
            "target_dimension": req.target_dimension,
            "indicators": [i.to_dict() for i in indicators],
            "count": len(indicators),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/analytics/correlations/cascades/{location}")
@limiter.limit("10/minute")
def detect_cascades(
    request: Request,
    location: str,
    start_date: str = Query(default="2026-01-01"),
    end_date: str = Query(default="2026-03-17"),
):
    """リスクカスケード検出"""
    try:
        from features.analytics.correlation_analyzer import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        cascades = analyzer.detect_risk_cascades(location, start_date, end_date)
        return {
            "location": location,
            "cascades": [c.to_dict() for c in cascades],
            "count": len(cascades),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class IndustryBenchmarkRequest(BaseModel):
    entity: dict  # {"name": ..., "country": ..., "industry": ...}


@app.post("/api/v1/analytics/benchmark/industry")
@limiter.limit("10/minute")
def benchmark_industry(request: Request, req: IndustryBenchmarkRequest):
    """業界ベンチマーク分析"""
    try:
        from features.analytics.benchmark_analyzer import BenchmarkAnalyzer
        analyzer = BenchmarkAnalyzer()
        report = analyzer.benchmark_against_industry(req.entity)
        return report.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class PeerBenchmarkRequest(BaseModel):
    target: dict
    peers: list[dict]


@app.post("/api/v1/analytics/benchmark/peers")
@limiter.limit("10/minute")
def benchmark_peers(request: Request, req: PeerBenchmarkRequest):
    """競合他社ベンチマーク分析"""
    try:
        from features.analytics.benchmark_analyzer import BenchmarkAnalyzer
        analyzer = BenchmarkAnalyzer()
        report = analyzer.benchmark_against_peers(req.target, req.peers)
        return report.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/analytics/benchmark/regional/{region}")
@limiter.limit("10/minute")
def benchmark_regional(request: Request, region: str):
    """地域ベースライン算出"""
    try:
        from features.analytics.benchmark_analyzer import BenchmarkAnalyzer
        analyzer = BenchmarkAnalyzer()
        baseline = analyzer.compute_regional_baseline(region)
        return baseline.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class WeightSensitivityRequest(BaseModel):
    location: str
    weight_perturbation: float = 0.05


@app.post("/api/v1/analytics/sensitivity/weights")
@limiter.limit("10/minute")
def analyze_weight_sensitivity(request: Request, req: WeightSensitivityRequest):
    """重み感度分析"""
    try:
        from features.analytics.sensitivity_analyzer import SensitivityAnalyzer
        analyzer = SensitivityAnalyzer()
        report = analyzer.analyze_weight_sensitivity(req.location, req.weight_perturbation)
        return report.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class WhatIfRequest(BaseModel):
    location: str
    dimension_overrides: dict[str, float]


@app.post("/api/v1/analytics/sensitivity/what-if")
@limiter.limit("10/minute")
def simulate_what_if(request: Request, req: WhatIfRequest):
    """What-Ifシナリオシミュレーション"""
    try:
        from features.analytics.sensitivity_analyzer import SensitivityAnalyzer
        analyzer = SensitivityAnalyzer()
        result = analyzer.simulate_score_change(req.location, req.dimension_overrides)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class ThresholdRequest(BaseModel):
    location: str
    target_level: str = "HIGH"


@app.post("/api/v1/analytics/sensitivity/threshold")
@limiter.limit("10/minute")
def find_threshold_drivers(request: Request, req: ThresholdRequest):
    """閾値到達ドライバー分析"""
    try:
        from features.analytics.sensitivity_analyzer import SensitivityAnalyzer
        analyzer = SensitivityAnalyzer()
        analysis = analyzer.find_score_threshold_drivers(req.location, req.target_level)
        return analysis.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class MonteCarloRequest(BaseModel):
    location: str
    n_simulations: int = 1000
    noise_std: float = 10.0


@app.post("/api/v1/analytics/sensitivity/montecarlo")
@limiter.limit("10/minute")
def monte_carlo_simulation(request: Request, req: MonteCarloRequest):
    """モンテカルロシミュレーション"""
    try:
        from features.analytics.sensitivity_analyzer import SensitivityAnalyzer
        analyzer = SensitivityAnalyzer()
        result = analyzer.monte_carlo_score_distribution(req.location, req.n_simulations, req.noise_std)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))



# ===========================================================================
#  STREAM 3-B: Forecast Monitoring Endpoints
# ===========================================================================


@app.get("/api/v1/forecast/accuracy")
@limiter.limit("60/minute")
def get_forecast_accuracy(request: Request, days: int = Query(30, ge=1, le=365)):
    """予測精度レポート"""
    try:
        from features.timeseries.forecast_monitor import ForecastMonitor
        monitor = ForecastMonitor()
        return monitor.get_accuracy_report(days)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/forecast/ensemble/{location}")
@limiter.limit("10/minute")
def get_ensemble_forecast(
    request: Request,
    location: str,
    dimension: str = Query("overall"),
    horizon_days: int = Query(30, ge=1, le=90),
):
    """EnsembleForecaster による予測"""
    try:
        from features.timeseries.forecaster import EnsembleForecaster
        forecaster = EnsembleForecaster()
        return forecaster.forecast(location, dimension, horizon_days)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v1/forecast/backtest/{location}")
@limiter.limit("10/minute")
def backtest_forecast(
    request: Request,
    location: str,
    dimension: str = Query("overall"),
    holdout_days: int = Query(30, ge=7, le=90),
):
    """予測モデルバックテスト"""
    try:
        from features.timeseries.forecaster import EnsembleForecaster
        forecaster = EnsembleForecaster()
        return forecaster.backtest(location, dimension, holdout_days)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ===========================================================================
#  STREAM 4: Supplier Reputation Screening Endpoints
# ===========================================================================


class ReputationScreenRequest(BaseModel):
    supplier_name: str
    country: Optional[str] = ""
    days_back: int = 180


class BatchReputationRequest(BaseModel):
    suppliers: list[dict]
    days_back: int = 180


@app.post("/api/v1/screening/reputation")
@limiter.limit("10/minute")
def screen_reputation(request: Request, req: ReputationScreenRequest):
    """サプライヤー評判スクリーニング"""
    try:
        from features.screening.supplier_reputation import SupplierReputationScreener
        screener = SupplierReputationScreener()
        result = screener.screen_supplier(req.supplier_name, req.country, req.days_back)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/v1/screening/reputation/batch")
@limiter.limit("10/minute")
def batch_screen_reputation(request: Request, req: BatchReputationRequest):
    """サプライヤー評判一括スクリーニング"""
    try:
        from features.screening.supplier_reputation import SupplierReputationScreener
        screener = SupplierReputationScreener()
        results = screener.batch_screen(req.suppliers, req.days_back)
        return {
            "total_screened": len(results),
            "results": results,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ===========================================================================
#  STREAM 5: Cost Impact Estimation Endpoints
# ===========================================================================


class CostEstimateRequest(BaseModel):
    scenario: str
    annual_spend_usd: float = 1000000
    daily_revenue_usd: float = 100000
    duration_days: int = 60
    risk_score: float = 50.0


class CostCompareRequest(BaseModel):
    annual_spend_usd: float = 1000000
    daily_revenue_usd: float = 100000
    duration_days: int = 60
    risk_score: float = 50.0
    scenarios: Optional[list[str]] = None


class CostSensitivityRequest(BaseModel):
    scenario: str
    annual_spend_usd: float = 1000000
    daily_revenue_usd: float = 100000
    durations: list[int] = [30, 60, 90, 180]
    risk_score: float = 50.0


@app.post("/api/v1/cost-impact/estimate")
@limiter.limit("10/minute")
def estimate_cost_impact(request: Request, req: CostEstimateRequest):
    """途絶コスト試算"""
    try:
        from features.analytics.cost_impact_analyzer import CostImpactAnalyzer
        analyzer = CostImpactAnalyzer()
        result = analyzer.estimate_disruption_cost(
            scenario=req.scenario,
            annual_spend_usd=req.annual_spend_usd,
            daily_revenue_usd=req.daily_revenue_usd,
            duration_days=req.duration_days,
            risk_score=req.risk_score,
        )
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/v1/cost-impact/compare")
@limiter.limit("10/minute")
def compare_cost_scenarios(request: Request, req: CostCompareRequest):
    """全シナリオ比較"""
    try:
        from features.analytics.cost_impact_analyzer import CostImpactAnalyzer
        analyzer = CostImpactAnalyzer()
        return analyzer.compare_scenarios(
            annual_spend_usd=req.annual_spend_usd,
            daily_revenue_usd=req.daily_revenue_usd,
            duration_days=req.duration_days,
            risk_score=req.risk_score,
            scenarios=req.scenarios,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/v1/cost-impact/sensitivity")
@limiter.limit("10/minute")
def cost_sensitivity(request: Request, req: CostSensitivityRequest):
    """期間別感度分析"""
    try:
        from features.analytics.cost_impact_analyzer import CostImpactAnalyzer
        analyzer = CostImpactAnalyzer()
        return analyzer.sensitivity_analysis(
            scenario=req.scenario,
            annual_spend_usd=req.annual_spend_usd,
            daily_revenue_usd=req.daily_revenue_usd,
            durations=req.durations,
            risk_score=req.risk_score,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Dashboard (STREAM 3) ---

dashboard_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")

@app.get("/dashboard")
def serve_dashboard():
    """Interactive HTML Dashboard — redirects to landing page"""
    dashboard_path = os.path.join(dashboard_dir, "index.html")
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path, media_type="text/html")
    return JSONResponse(
        status_code=404,
        content={"error": "Dashboard not generated. Run: python scripts/generate_dashboard.py"}
    )

# --- Dashboard static files (Logistics / Inbound / Legacy) ---
if os.path.exists(dashboard_dir):
    app.mount("/dashboards", StaticFiles(directory=dashboard_dir, html=True), name="dashboards")

# --- Static files (UI) ---

ui_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")
if os.path.exists(ui_dir):
    app.mount("/static", StaticFiles(directory=ui_dir), name="static")

    @app.get("/")
    def serve_index():
        index_path = os.path.join(ui_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return JSONResponse({"message": "Supply Chain Risk Intelligence API v0.5.1", "docs": "/docs"})
else:
    @app.get("/")
    def root():
        return {"message": "Supply Chain Risk Intelligence API v0.5.1", "docs": "/docs",
                "dimensions": 24}
