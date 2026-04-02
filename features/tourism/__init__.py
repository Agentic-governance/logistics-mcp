# features/tourism — 観光需要モデル + インバウンドリスク評価 (SCRI v1.3.0)

try:
    from .gravity_model import TourismGravityModel
except (ImportError, ModuleNotFoundError):
    TourismGravityModel = None

try:
    from .regional_distribution import RegionalDistributionModel
except (ImportError, ModuleNotFoundError):
    RegionalDistributionModel = None

try:
    from .inbound_risk_scorer import InboundTourismRiskScorer
except (ImportError, ModuleNotFoundError):
    InboundTourismRiskScorer = None

__all__ = ["TourismGravityModel", "RegionalDistributionModel", "InboundTourismRiskScorer"]
