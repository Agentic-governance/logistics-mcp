"""共通基底クラスと正規化済みエントリ型"""
from dataclasses import dataclass, field
from typing import Optional
from abc import ABC, abstractmethod


# ソース別タイムアウト設定（秒）
DEFAULT_TIMEOUTS = {
    "ofac": 30,
    "un": 30,
    "eu": 60,
    "bis": 30,
    "meti": 60,
    "ofsi": 30,
    "seco": 300,      # 37MB大ファイル。実運用はキャッシュ経由で即時
    "canada": 45,
    "dfat": 60,
    "mofa_japan": 60,
}


@dataclass
class SanctionEntry:
    source: str
    source_id: Optional[str]
    entity_type: str
    name_primary: str
    names_aliases: list[str] = field(default_factory=list)
    country: Optional[str] = None
    address: Optional[str] = None
    programs: list[str] = field(default_factory=list)
    reason: Optional[str] = None


class BaseParser(ABC):
    source: str

    @property
    def timeout(self) -> int:
        """ソース別タイムアウト値を返す"""
        return DEFAULT_TIMEOUTS.get(self.source, 60)

    @abstractmethod
    def fetch_and_parse(self):
        pass
