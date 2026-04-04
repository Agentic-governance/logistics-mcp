# features/tourism — 観光需要モデル + インバウンドリスク評価 (SCRI v1.5.0)

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

try:
    from .travel_friction_index import TravelFrictionIndex
except (ImportError, ModuleNotFoundError):
    TravelFrictionIndex = None

try:
    from .gravity_model import TFIEnrichedGravityModel
except (ImportError, ModuleNotFoundError):
    TFIEnrichedGravityModel = None

try:
    from .cultural_inertia import CulturalInertiaCoefficient
except (ImportError, ModuleNotFoundError):
    CulturalInertiaCoefficient = None

try:
    from .calendar_events import (
        CalendarEvent, CALENDAR_EVENTS,
        get_events_for_country_month, get_demand_multiplier,
        get_uncertainty_multiplier,
    )
except (ImportError, ModuleNotFoundError):
    CalendarEvent = None
    CALENDAR_EVENTS = None
    get_events_for_country_month = None
    get_demand_multiplier = None
    get_uncertainty_multiplier = None

try:
    from .gaussian_process_model import (
        GaussianProcessInboundModel, MultiMarketGPAggregator,
        BASE_MONTHLY, GPYTORCH_AVAILABLE,
    )
except (ImportError, ModuleNotFoundError):
    GaussianProcessInboundModel = None
    MultiMarketGPAggregator = None
    BASE_MONTHLY = None
    GPYTORCH_AVAILABLE = None

try:
    from .scenario_engine import ScenarioEngine, SCENARIOS, CountryScenarioImpact
except (ImportError, ModuleNotFoundError):
    ScenarioEngine = None
    SCENARIOS = None
    CountryScenarioImpact = None

try:
    from .country_distribution_model import (
        CountryDistributionModel, MonteCarloAggregator,
        COUNTRY_RISK_PARAMS, SCENARIO_DRIVERS,
    )
except (ImportError, ModuleNotFoundError):
    CountryDistributionModel = None
    MonteCarloAggregator = None
    COUNTRY_RISK_PARAMS = None
    SCENARIO_DRIVERS = None

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
    "TravelFrictionIndex",
    "TFIEnrichedGravityModel",
    "CulturalInertiaCoefficient",
    "CalendarEvent",
    "CALENDAR_EVENTS",
    "get_events_for_country_month",
    "get_demand_multiplier",
    "get_uncertainty_multiplier",
    "GaussianProcessInboundModel",
    "MultiMarketGPAggregator",
    "BASE_MONTHLY",
    "GPYTORCH_AVAILABLE",
    "ScenarioEngine",
    "SCENARIOS",
    "CountryScenarioImpact",
    "CountryDistributionModel",
    "MonteCarloAggregator",
    "COUNTRY_RISK_PARAMS",
    "SCENARIO_DRIVERS",
]
