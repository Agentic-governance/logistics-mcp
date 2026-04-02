"""デジタルツイン分析エンジン群
在庫枯渇予測・生産カスケード・緊急調達最適化・拠点リスクマップ
SCRI v1.1.0
"""
try:
    from .transport_risk import TransportRiskAnalyzer
except ImportError:
    TransportRiskAnalyzer = None

try:
    from .stockout_predictor import StockoutPredictor
except ImportError:
    StockoutPredictor = None

try:
    from .production_cascade import ProductionCascadeSimulator
except ImportError:
    ProductionCascadeSimulator = None

try:
    from .emergency_procurement import EmergencyProcurementOptimizer
except ImportError:
    EmergencyProcurementOptimizer = None

try:
    from .facility_risk_mapper import FacilityRiskMapper
except ImportError:
    FacilityRiskMapper = None

__all__ = [
    "TransportRiskAnalyzer",
    "StockoutPredictor",
    "ProductionCascadeSimulator",
    "EmergencyProcurementOptimizer",
    "FacilityRiskMapper",
]
