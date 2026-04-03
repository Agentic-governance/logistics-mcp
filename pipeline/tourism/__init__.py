"""観光統計クライアント群
UNWTO(World Bank経由)、JNTO訪日統計、国別アウトバウンド、競合デスティネーション、
経済・余暇変数、文化的関心変数
"""
from .unwto_client import UNWTOClient
from .jnto_client import JNTOClient
from .country_outbound_clients import (
    ChinaOutboundClient,
    KoreaOutboundClient,
    TaiwanOutboundClient,
    USOutboundClient,
    AustraliaOutboundClient,
    WorldBankTourismClient,
)
from .competitor_stats_client import CompetitorStatsClient
from .flight_supply_client import FlightSupplyClient
from .effective_distance_client import EffectiveFlightDistanceClient, EffectiveDistance
from .cultural_distance_client import CulturalDistanceClient, CulturalDistance
from .economic_leisure_client import EconomicLeisureClient
from .cultural_interest_client import CulturalInterestClient
from .tourism_db import TourismDB
from .bilateral_fx_client import BilateralFXClient
from .competitors import (
    ThailandInboundClient,
    KoreaInboundClient,
    TaiwanInboundClient,
    EuropeInboundClient,
    CompetitorDatabase,
)

__all__ = [
    "UNWTOClient",
    "JNTOClient",
    "ChinaOutboundClient",
    "KoreaOutboundClient",
    "TaiwanOutboundClient",
    "USOutboundClient",
    "AustraliaOutboundClient",
    "WorldBankTourismClient",
    "CompetitorStatsClient",
    "FlightSupplyClient",
    "EffectiveFlightDistanceClient",
    "EffectiveDistance",
    "CulturalDistanceClient",
    "CulturalDistance",
    "EconomicLeisureClient",
    "CulturalInterestClient",
    "TourismDB",
    "BilateralFXClient",
    "ThailandInboundClient",
    "KoreaInboundClient",
    "TaiwanInboundClient",
    "EuropeInboundClient",
    "CompetitorDatabase",
]
