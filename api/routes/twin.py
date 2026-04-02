"""デジタルツイン分析API
POST /api/v1/twin/stockout-scan       — 在庫枯渇リスクスキャン
POST /api/v1/twin/production-cascade  — 生産カスケードシミュレーション
POST /api/v1/twin/emergency-procurement — 緊急調達最適計画
GET  /api/v1/twin/facility-risks      — 全拠点リスクヒートマップ
POST /api/v1/twin/transport-analysis  — 輸送ルートリスク分析
POST /api/v1/twin/scenario            — What-Ifシナリオシミュレーション
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/twin", tags=["digital-twin"])

# --- ROLE-B/C 依存モジュール（未完成時は graceful degradation） ---

_STOCKOUT_AVAILABLE = False
_CASCADE_AVAILABLE = False
_PROCUREMENT_AVAILABLE = False
_FACILITY_AVAILABLE = False
_TRANSPORT_AVAILABLE = False

try:
    from features.digital_twin.stockout_predictor import StockoutPredictor
    _stockout = StockoutPredictor()
    _STOCKOUT_AVAILABLE = True
except (ImportError, Exception) as e:
    logger.warning(f"StockoutPredictor 読み込み失敗: {e}")
    _stockout = None

try:
    from features.digital_twin.production_cascade import ProductionCascade
    _cascade = ProductionCascade()
    _CASCADE_AVAILABLE = True
except (ImportError, Exception) as e:
    logger.warning(f"ProductionCascade 読み込み失敗: {e}")
    _cascade = None

try:
    from features.digital_twin.emergency_procurement import EmergencyProcurement
    _procurement = EmergencyProcurement()
    _PROCUREMENT_AVAILABLE = True
except (ImportError, Exception) as e:
    logger.warning(f"EmergencyProcurement 読み込み失敗: {e}")
    _procurement = None

try:
    from features.digital_twin.facility_risk_mapper import FacilityRiskMapper
    _facility = FacilityRiskMapper()
    _FACILITY_AVAILABLE = True
except (ImportError, Exception) as e:
    logger.warning(f"FacilityRiskMapper 読み込み失敗: {e}")
    _facility = None

try:
    from features.digital_twin.transport_risk import TransportRisk
    _transport = TransportRisk()
    _TRANSPORT_AVAILABLE = True
except (ImportError, Exception) as e:
    logger.warning(f"TransportRisk 読み込み失敗: {e}")
    _transport = None


# ---------------------------------------------------------------------------
# リクエストモデル
# ---------------------------------------------------------------------------

class StockoutScanRequest(BaseModel):
    location_id: str = Field(default="", description="拠点ID（空=全拠点）")
    risk_threshold: int = Field(default=50, ge=0, le=100, description="リスク閾値")


class ProductionCascadeRequest(BaseModel):
    part_id: str = Field(..., description="欠品部品ID")
    shortage_days: int = Field(..., ge=1, description="欠品日数")
    product_id: str = Field(default="", description="対象製品ID（空=全製品）")


class EmergencyProcurementRequest(BaseModel):
    part_id: str = Field(..., description="緊急調達部品ID")
    required_qty: int = Field(..., ge=1, description="必要数量")
    deadline_date: str = Field(..., description="納期（YYYY-MM-DD）")
    budget_limit_jpy: int = Field(default=0, ge=0, description="予算上限（円、0=無制限）")


class TransportAnalysisRequest(BaseModel):
    origin_country: str = Field(..., description="出発国（ISO2 or 国名）")
    dest_country: str = Field(..., description="到着国（ISO2 or 国名）")
    cargo_value_jpy: int = Field(default=0, ge=0, description="貨物価値（円）")
    transport_mode: str = Field(default="sea", description="輸送モード: sea/air/rail/truck")


class ScenarioRequest(BaseModel):
    scenario: str = Field(..., description="シナリオ名（earthquake, pandemic, port_closure, sanctions, war, typhoon）")
    duration_days: int = Field(default=30, ge=1, le=365, description="シミュレーション期間（日）")
    affected_countries: list[str] = Field(default_factory=list, description="影響国リスト")
    parameters: dict = Field(default_factory=dict, description="追加パラメータ")


# ---------------------------------------------------------------------------
# サンプルレスポンス生成（モジュール未実装時のフォールバック）
# ---------------------------------------------------------------------------

def _not_implemented_response(feature_name: str) -> dict:
    """機能未実装時の標準レスポンス"""
    return {
        "success": False,
        "error": f"{feature_name} は現在実装中です。サンプルデータで動作確認してください。",
        "status": "not_implemented",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------

@router.post("/stockout-scan")
async def stockout_scan(req: StockoutScanRequest):
    """在庫枯渇リスク全部品スキャン"""
    if not _STOCKOUT_AVAILABLE:
        return _not_implemented_response("StockoutPredictor")
    try:
        result = _stockout.scan(
            location_id=req.location_id or None,
            risk_threshold=req.risk_threshold,
        )
        return {
            "success": True,
            "location_id": req.location_id or "ALL",
            "risk_threshold": req.risk_threshold,
            "results": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"在庫枯渇スキャンエラー: {e}")
        raise HTTPException(status_code=500, detail=f"在庫枯渇スキャン失敗: {str(e)}")


@router.post("/production-cascade")
async def production_cascade(req: ProductionCascadeRequest):
    """部品欠品の生産カスケードシミュレーション"""
    if not _CASCADE_AVAILABLE:
        return _not_implemented_response("ProductionCascade")
    try:
        result = _cascade.simulate(
            part_id=req.part_id,
            shortage_days=req.shortage_days,
            product_id=req.product_id or None,
        )
        return {
            "success": True,
            "part_id": req.part_id,
            "shortage_days": req.shortage_days,
            "product_id": req.product_id or "ALL",
            "cascade_impact": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"生産カスケードエラー: {e}")
        raise HTTPException(status_code=500, detail=f"生産カスケードシミュレーション失敗: {str(e)}")


@router.post("/emergency-procurement")
async def emergency_procurement(req: EmergencyProcurementRequest):
    """緊急調達最適計画"""
    if not _PROCUREMENT_AVAILABLE:
        return _not_implemented_response("EmergencyProcurement")
    try:
        result = _procurement.plan(
            part_id=req.part_id,
            required_qty=req.required_qty,
            deadline_date=req.deadline_date,
            budget_limit_jpy=req.budget_limit_jpy or None,
        )
        return {
            "success": True,
            "part_id": req.part_id,
            "required_qty": req.required_qty,
            "deadline_date": req.deadline_date,
            "budget_limit_jpy": req.budget_limit_jpy,
            "procurement_plan": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"緊急調達エラー: {e}")
        raise HTTPException(status_code=500, detail=f"緊急調達計画失敗: {str(e)}")


@router.get("/facility-risks")
async def get_facility_risks():
    """全拠点リスクヒートマップ"""
    if not _FACILITY_AVAILABLE:
        return _not_implemented_response("FacilityRiskMapper")
    try:
        result = _facility.get_risk_map()
        return {
            "success": True,
            "facility_risks": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"拠点リスクマップエラー: {e}")
        raise HTTPException(status_code=500, detail=f"拠点リスクマップ取得失敗: {str(e)}")


@router.post("/transport-analysis")
async def transport_analysis(req: TransportAnalysisRequest):
    """輸送ルートリスク分析"""
    if not _TRANSPORT_AVAILABLE:
        return _not_implemented_response("TransportRisk")
    try:
        result = _transport.analyze(
            origin_country=req.origin_country,
            dest_country=req.dest_country,
            cargo_value_jpy=req.cargo_value_jpy or None,
            transport_mode=req.transport_mode,
        )
        return {
            "success": True,
            "origin": req.origin_country,
            "destination": req.dest_country,
            "transport_mode": req.transport_mode,
            "cargo_value_jpy": req.cargo_value_jpy,
            "analysis": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"輸送リスク分析エラー: {e}")
        raise HTTPException(status_code=500, detail=f"輸送リスク分析失敗: {str(e)}")


@router.post("/scenario")
async def run_scenario(req: ScenarioRequest):
    """What-Ifシナリオシミュレーション"""
    valid_scenarios = ["earthquake", "pandemic", "port_closure", "sanctions", "war", "typhoon"]
    if req.scenario not in valid_scenarios:
        raise HTTPException(
            status_code=400,
            detail=f"無効なシナリオ: {req.scenario}。有効値: {valid_scenarios}",
        )

    # 各モジュールを組み合わせたシナリオ分析
    results = {
        "scenario": req.scenario,
        "duration_days": req.duration_days,
        "affected_countries": req.affected_countries,
        "impacts": {},
    }

    # 在庫枯渇影響
    if _STOCKOUT_AVAILABLE:
        try:
            stockout_impact = _stockout.scenario_impact(
                scenario=req.scenario,
                duration_days=req.duration_days,
                affected_countries=req.affected_countries,
            )
            results["impacts"]["stockout"] = stockout_impact
        except Exception as e:
            results["impacts"]["stockout"] = {"error": str(e)}
    else:
        results["impacts"]["stockout"] = {"status": "not_implemented"}

    # 生産カスケード影響
    if _CASCADE_AVAILABLE:
        try:
            cascade_impact = _cascade.scenario_impact(
                scenario=req.scenario,
                duration_days=req.duration_days,
                affected_countries=req.affected_countries,
            )
            results["impacts"]["production_cascade"] = cascade_impact
        except Exception as e:
            results["impacts"]["production_cascade"] = {"error": str(e)}
    else:
        results["impacts"]["production_cascade"] = {"status": "not_implemented"}

    # 輸送影響
    if _TRANSPORT_AVAILABLE:
        try:
            transport_impact = _transport.scenario_impact(
                scenario=req.scenario,
                duration_days=req.duration_days,
                affected_countries=req.affected_countries,
            )
            results["impacts"]["transport"] = transport_impact
        except Exception as e:
            results["impacts"]["transport"] = {"error": str(e)}
    else:
        results["impacts"]["transport"] = {"status": "not_implemented"}

    # 拠点影響
    if _FACILITY_AVAILABLE:
        try:
            facility_impact = _facility.scenario_impact(
                scenario=req.scenario,
                affected_countries=req.affected_countries,
            )
            results["impacts"]["facilities"] = facility_impact
        except Exception as e:
            results["impacts"]["facilities"] = {"error": str(e)}
    else:
        results["impacts"]["facilities"] = {"status": "not_implemented"}

    # 全モジュール未実装の場合
    all_not_impl = all(
        v.get("status") == "not_implemented"
        for v in results["impacts"].values()
        if isinstance(v, dict)
    )
    if all_not_impl:
        results["message"] = "デジタルツイン機能は現在実装中です。サンプルデータで動作確認してください。"

    results["success"] = True
    results["timestamp"] = datetime.now(timezone.utc).isoformat()
    return results
