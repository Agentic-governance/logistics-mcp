"""観光統計クライアント群
UNWTO(World Bank経由)、JNTO訪日統計、国別アウトバウンド、競合デスティネーション
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
from .tourism_db import TourismDB
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
    "TourismDB",
    "ThailandInboundClient",
    "KoreaInboundClient",
    "TaiwanInboundClient",
    "EuropeInboundClient",
    "CompetitorDatabase",
]
