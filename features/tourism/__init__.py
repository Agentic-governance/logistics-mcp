# features/tourism — 観光需要モデル + インバウンドリスク評価 (SCRI v1.4.0)

try:
    from .gravity_model import TourismGravityModel
except (ImportError, ModuleNotFoundError):
    TourismGravityModel = None

try:
    from .seasonal_extractor import SeasonalExtractor
except (ImportError, ModuleNotFoundError):
    SeasonalExtractor = None

try:
    from .inbound_aggregator import InboundAggregator
except (ImportError, ModuleNotFoundError):
    InboundAggregator = None

try:
    from .regional_distribution import RegionalDistributionModel
except (ImportError, ModuleNotFoundError):
    RegionalDistributionModel = None

try:
    from .inbound_risk_scorer import InboundTourismRiskScorer
except (ImportError, ModuleNotFoundError):
    InboundTourismRiskScorer = None

try:
    from .travel_momentum import TravelMomentumIndex
except (ImportError, ModuleNotFoundError):
    TravelMomentumIndex = None

try:
    from .models import LSTMStructural, TourismTransformer
    from .models import DualScaleModel
except (ImportError, ModuleNotFoundError):
    LSTMStructural = None
    TourismTransformer = None
    DualScaleModel = None

try:
    from .bayesian_updater import BayesianUpdater
except (ImportError, ModuleNotFoundError):
    BayesianUpdater = None

try:
    from .risk_adjuster import RiskAdjuster
except (ImportError, ModuleNotFoundError):
    RiskAdjuster = None

__all__ = [
    "TourismGravityModel",
    "SeasonalExtractor",
    "InboundAggregator",
    "RegionalDistributionModel",
    "InboundTourismRiskScorer",
    "TravelMomentumIndex",
    "LSTMStructural",
    "TourismTransformer",
    "DualScaleModel",
    "BayesianUpdater",
    "RiskAdjuster",
]
