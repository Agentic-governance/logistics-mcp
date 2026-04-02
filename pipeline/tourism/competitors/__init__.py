"""競合デスティネーション インバウンド統計クライアント群
タイ・韓国・台湾・欧州3カ国(仏西伊)の詳細インバウンドデータを収集し、
competitor_arrivals テーブルに統合格納する。
"""
from .thailand_client import ThailandInboundClient
from .korea_inbound_client import KoreaInboundClient
from .taiwan_inbound_client import TaiwanInboundClient
from .europe_client import EuropeInboundClient
from .competitor_db import CompetitorDatabase

__all__ = [
    "ThailandInboundClient",
    "KoreaInboundClient",
    "TaiwanInboundClient",
    "EuropeInboundClient",
    "CompetitorDatabase",
]
