"""BOM Risk Analysis API Routes
v0.8.0: BOM リスク分析 + Tier-2+ 推定エンドポイント
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/api/v1/bom", tags=["BOM Risk Analysis"])


class BOMAnalysisRequest(BaseModel):
    bom: list[dict]
    product_name: str = "Product"
    include_tier2_inference: bool = False


class TierInferenceRequest(BaseModel):
    tier1_country: str
    hs_code: str
    material: str = ""
    max_depth: int = 3


class HiddenRiskRequest(BaseModel):
    tier1_country: str
    materials: list[dict]


class BOMImportRequest(BaseModel):
    csv_data: str
    product_name: str = "Product"
    include_tier2_inference: bool = False


@router.post("/analyze")
def analyze_bom(req: BOMAnalysisRequest):
    """BOM リスク分析（Tier-2 推定オプション付き）"""
    try:
        from features.analytics.bom_analyzer import BOMAnalyzer, BOMNode

        bom = []
        for item in req.bom:
            bom.append(BOMNode(
                part_id=item.get("part_id", ""),
                part_name=item.get("part_name", ""),
                supplier_name=item.get("supplier_name", ""),
                supplier_country=item.get("supplier_country", ""),
                material=item.get("material", ""),
                hs_code=item.get("hs_code", ""),
                tier=item.get("tier", 1),
                quantity=float(item.get("quantity", 1)),
                unit_cost_usd=float(item.get("unit_cost_usd", 0)),
                is_critical=item.get("is_critical", False),
            ))

        analyzer = BOMAnalyzer()
        result = analyzer.analyze_bom(bom, req.product_name, req.include_tier2_inference)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/infer-supply-chain")
def infer_supply_chain(req: TierInferenceRequest):
    """Tier-2/3 サプライチェーン推定"""
    try:
        from features.analytics.tier_inference import TierInferenceEngine

        engine = TierInferenceEngine()
        result = engine.estimate_risk_exposure(req.tier1_country, req.hs_code, req.material)

        if req.max_depth >= 2:
            tree = engine.build_full_supply_tree(
                req.tier1_country,
                [{"material": req.material, "hs_code": req.hs_code}],
                max_depth=req.max_depth,
            )
            result["supply_tree"] = [n.to_dict() for n in tree]

        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/hidden-risk")
def get_hidden_risk(req: HiddenRiskRequest):
    """隠れたリスクエクスポージャー分析"""
    try:
        from features.analytics.tier_inference import TierInferenceEngine

        engine = TierInferenceEngine()
        exposures = []
        total_delta = 0.0

        for mat in req.materials:
            hs_code = mat.get("hs_code", "")
            material = mat.get("material", "")
            if not hs_code:
                continue
            exposure = engine.estimate_risk_exposure(req.tier1_country, hs_code, material)
            exposures.append(exposure)
            total_delta += exposure.get("hidden_risk_delta", 0)

        return {
            "tier1_country": req.tier1_country,
            "materials_analyzed": len(exposures),
            "total_hidden_risk_delta": round(total_delta, 1),
            "exposures": exposures,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/import-csv")
def import_bom_csv(req: BOMImportRequest):
    """CSV から BOM をインポートしてリスク分析"""
    try:
        from features.analytics.bom_importer import BOMImporter
        from features.analytics.bom_analyzer import BOMAnalyzer

        importer = BOMImporter()
        bom = importer.from_csv(req.csv_data)

        if not bom:
            raise HTTPException(status_code=400, detail="No valid BOM entries found in CSV")

        analyzer = BOMAnalyzer()
        result = analyzer.analyze_bom(bom, req.product_name, req.include_tier2_inference)
        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/product-risk")
def get_product_risk(
    product_name: str = Query("Product"),
    bom_file: str = Query(None, description="Path to BOM JSON file"),
):
    """BOM ファイルから confirmed/full リスクを比較"""
    try:
        from features.analytics.bom_importer import BOMImporter
        from features.analytics.bom_analyzer import BOMAnalyzer

        if not bom_file:
            return {"error": "bom_file parameter required"}

        importer = BOMImporter()
        bom = importer.from_json_file(bom_file)

        analyzer = BOMAnalyzer()
        return analyzer.calculate_product_risk(bom, product_name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/sample")
def get_sample_bom():
    """サンプル BOM データ（EV パワートレイン）を返す"""
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sample_path = os.path.join(project_root, "data", "sample_bom_ev_powertrain.json")

    if os.path.exists(sample_path):
        import json
        with open(sample_path, "r") as f:
            return json.load(f)

    return {
        "message": "Sample BOM not found. Generate with: python scripts/build_tier_inference_cache.py",
        "sample_format": {
            "product_name": "EV Powertrain",
            "bom": [
                {
                    "part_id": "P001",
                    "part_name": "Battery Cell",
                    "supplier_name": "Example Corp",
                    "supplier_country": "South Korea",
                    "material": "battery",
                    "hs_code": "8507",
                    "quantity": 100,
                    "unit_cost_usd": 45.0,
                    "is_critical": True,
                }
            ],
        },
    }
