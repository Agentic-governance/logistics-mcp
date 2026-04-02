"""ソースマーケット別アウトバウンド統計クライアント群
主要6市場（中国・韓国・台湾・米国・豪州・その他）のアウトバウンド出国者数を
各国一次統計API + World Bankフォールバック + ハードコード実績で提供。

共通インターフェース:
  async get_outbound_stats(year, month=None) -> dict
  async get_historical(years_back=5) -> list
  async get_top_destinations(year) -> list
"""
from .china_client import ChinaSourceMarketClient
from .korea_client import KoreaSourceMarketClient
from .taiwan_client import TaiwanSourceMarketClient
from .us_client import USSourceMarketClient
from .australia_client import AustraliaSourceMarketClient
from .other_markets_client import (
    HongKongSourceMarketClient,
    SingaporeSourceMarketClient,
    IndiaSourceMarketClient,
    GermanySourceMarketClient,
    FranceSourceMarketClient,
    UKSourceMarketClient,
    OtherMarketClientFactory,
)

__all__ = [
    "ChinaSourceMarketClient",
    "KoreaSourceMarketClient",
    "TaiwanSourceMarketClient",
    "USSourceMarketClient",
    "AustraliaSourceMarketClient",
    "HongKongSourceMarketClient",
    "SingaporeSourceMarketClient",
    "IndiaSourceMarketClient",
    "GermanySourceMarketClient",
    "FranceSourceMarketClient",
    "UKSourceMarketClient",
    "OtherMarketClientFactory",
]
