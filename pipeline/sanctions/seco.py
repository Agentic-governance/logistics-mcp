"""スイスSECO制裁リスト パーサー（バックグラウンドキャッシュ方式）
State Secretariat for Economic Affairs
XML形式、APIキー不要

キャッシュ戦略:
- 起動時にディスクキャッシュがあれば即ロード
- バックグラウンドで最新版を非同期ダウンロード
- 24時間ごとに自動更新
- SECO_CACHE_PATH 環境変数でディスクキャッシュパスを指定可能

URL: https://www.sesam.search.admin.ch/sesam-search-web/pages/downloadXmlGesamtliste.xhtml
"""
import logging
import os
import pickle
import threading
import time
import requests
from datetime import datetime, timedelta
from lxml import etree
from typing import Dict, Iterator, List, Optional, Tuple
from .base import SanctionEntry, BaseParser

logger = logging.getLogger(__name__)

SECO_URL = (
    "https://www.sesam.search.admin.ch/sesam-search-web/pages/"
    "downloadXmlGesamtliste.xhtml?lang=en&action=downloadXmlGesamtlisteAction"
)

SECO_LEGACY_URL = (
    "https://www.seco.admin.ch/dam/seco/de/dokumente/Aussenwirtschaft/"
    "Wirtschaftsbeziehungen/Exportkontrollen/Sanktionen/"
    "Consolidated_list.xml.download.xml/Consolidated_list.xml"
)

HEADERS = {
    "User-Agent": "SupplyChainRiskMonitor/1.0 (compliance screening)",
    "Accept": "application/xml",
}

# Module-level cache
_cache: List[SanctionEntry] = []
_last_updated: Optional[datetime] = None
_cache_lock = threading.Lock()
_refresh_in_progress = False

# Disk cache path (configurable via env var)
_CACHE_PATH = os.environ.get("SECO_CACHE_PATH", "data/seco_cache.pkl")


def _load_disk_cache() -> bool:
    """ディスクキャッシュからロード"""
    global _cache, _last_updated
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, "rb") as f:
                data = pickle.load(f)
            with _cache_lock:
                _cache = data["entries"]
                _last_updated = data["updated_at"]
            logger.info(f"SECO: loaded {len(_cache)} entries from disk cache "
                        f"(updated: {_last_updated})")
            return True
    except Exception as e:
        logger.warning(f"SECO: disk cache load failed: {e}")
    return False


def _save_disk_cache():
    """ディスクキャッシュに保存"""
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH) or ".", exist_ok=True)
        with _cache_lock:
            data = {"entries": list(_cache), "updated_at": _last_updated}
        with open(_CACHE_PATH, "wb") as f:
            pickle.dump(data, f)
        logger.info(f"SECO: saved {len(data['entries'])} entries to disk cache")
    except Exception as e:
        logger.warning(f"SECO: disk cache save failed: {e}")


def _download_and_parse() -> List[SanctionEntry]:
    """XMLダウンロード→パース（同期、バックグラウンドスレッドから呼ばれる）"""
    parser = SECOParser()
    entries = []

    for url in [SECO_URL, SECO_LEGACY_URL]:
        try:
            resp = requests.get(url, timeout=300, headers=HEADERS, stream=True)
            resp.raise_for_status()

            # Stream into memory in chunks for large file
            chunks = []
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                chunks.append(chunk)
            content = b"".join(chunks)

            root = etree.fromstring(content)
            logger.info(f"SECO: downloaded from {url} ({len(content)} bytes)")

            place_map = parser._build_place_map(root)
            program_map = parser._build_program_map(root)

            for target in root.iter("target"):
                entries.extend(parser._parse_target(target, place_map, program_map))

            logger.info(f"SECO: parsed {len(entries)} entries")
            return entries

        except Exception as e:
            logger.warning(f"SECO: fetch failed from {url}: {e}")

    return entries


def _refresh_cache_background():
    """バックグラウンドでキャッシュを更新"""
    global _cache, _last_updated, _refresh_in_progress

    if _refresh_in_progress:
        return

    _refresh_in_progress = True
    try:
        entries = _download_and_parse()
        if entries:
            with _cache_lock:
                _cache = entries
                _last_updated = datetime.utcnow()
            _save_disk_cache()
            logger.info(f"SECO: cache refreshed with {len(entries)} entries")
    except Exception as e:
        logger.error(f"SECO: background refresh failed: {e}")
    finally:
        _refresh_in_progress = False


def preload():
    """起動時にキャッシュをプリロード。
    1. ディスクキャッシュがあれば即ロード
    2. バックグラウンドで最新版を取得開始
    """
    loaded = _load_disk_cache()

    # バックグラウンドで最新版を取得
    thread = threading.Thread(target=_refresh_cache_background, daemon=True)
    thread.start()

    if not loaded:
        # ディスクキャッシュがない場合は初回ダウンロード完了を待機
        logger.info("SECO: no disk cache, waiting for initial download...")
        thread.join(timeout=300)


def get_entities() -> List[SanctionEntry]:
    """キャッシュからエンティティを即時返却。
    キャッシュ空の場合のみ同期ダウンロード。
    """
    with _cache_lock:
        if _cache:
            return list(_cache)

    # キャッシュ空: 同期ダウンロード
    logger.info("SECO: cache empty, performing synchronous download...")
    entries = _download_and_parse()
    if entries:
        global _last_updated
        with _cache_lock:
            _cache.extend(entries)
            _last_updated = datetime.utcnow()
        _save_disk_cache()
    return entries


def is_cache_fresh(max_age_hours: int = 24) -> bool:
    """キャッシュが新鮮か判定"""
    if _last_updated is None:
        return False
    return datetime.utcnow() - _last_updated < timedelta(hours=max_age_hours)


def cache_status() -> dict:
    """キャッシュ状態を返却"""
    return {
        "source": "seco",
        "cached_entries": len(_cache),
        "last_updated": _last_updated.isoformat() if _last_updated else None,
        "cache_fresh": is_cache_fresh(),
        "cache_mode": True,
        "disk_cache_path": _CACHE_PATH,
        "disk_cache_exists": os.path.exists(_CACHE_PATH),
    }


class SECOParser(BaseParser):
    source = "seco"

    def fetch_and_parse(self) -> Iterator[SanctionEntry]:
        """フルパース（ingestion script用）。キャッシュは使わず直接DL→パース"""
        print("Fetching Swiss SECO Consolidated Sanctions List...")
        root = None

        for url in [SECO_URL, SECO_LEGACY_URL]:
            try:
                resp = requests.get(url, timeout=300, headers=HEADERS, stream=True)
                resp.raise_for_status()

                chunks = []
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    chunks.append(chunk)
                content = b"".join(chunks)

                root = etree.fromstring(content)
                print(f"  Loaded from {url} ({len(content)} bytes)")
                break
            except Exception as e:
                print(f"  Failed to fetch from {url}: {e}")

        if root is None:
            print("  SECO: all fetch attempts failed")
            return

        place_map = self._build_place_map(root)
        program_map = self._build_program_map(root)

        for target in root.iter("target"):
            yield from self._parse_target(target, place_map, program_map)

    def _build_place_map(self, root) -> Dict[str, str]:
        """<place>要素からssid -> 国名マッピングを構築"""
        place_map: Dict[str, str] = {}
        for place in root.iter("place"):
            ssid = place.get("ssid")
            country_elem = place.find("country")
            if ssid and country_elem is not None:
                country_name = country_elem.text
                if country_name:
                    place_map[ssid] = country_name.strip()
        return place_map

    def _build_program_map(self, root) -> Dict[str, str]:
        """sanctions-program -> program-key マッピングを構築"""
        program_map: Dict[str, str] = {}
        for prog in root.iter("sanctions-program"):
            for sset in prog.iter("sanctions-set"):
                ss_id = sset.get("ssid")
                prog_key = prog.findtext("program-key")
                if ss_id and prog_key:
                    program_map[ss_id] = prog_key.strip()
        return program_map

    def _parse_target(
        self,
        target,
        place_map: Dict[str, str],
        program_map: Dict[str, str],
    ) -> Iterator[SanctionEntry]:
        """<target>要素をSanctionEntryに変換"""
        target_ssid = target.get("ssid")
        sanctions_set_id = target.findtext("sanctions-set-id")

        programs: List[str] = []
        if sanctions_set_id and sanctions_set_id in program_map:
            programs.append(program_map[sanctions_set_id])

        for individual in target.iter("individual"):
            names = self._extract_names(individual)
            if not names:
                continue
            country = self._extract_country(individual, place_map)
            address = self._extract_address(individual, place_map)
            reason = self._extract_reason(individual)
            yield SanctionEntry(
                source="seco", source_id=target_ssid,
                entity_type="individual", name_primary=names[0],
                names_aliases=names[1:], country=country,
                address=address, programs=programs, reason=reason,
            )

        for entity in target.iter("entity"):
            names = self._extract_names(entity)
            if not names:
                continue
            country = self._extract_country(entity, place_map)
            address = self._extract_address(entity, place_map)
            reason = self._extract_reason(entity)
            yield SanctionEntry(
                source="seco", source_id=target_ssid,
                entity_type="entity", name_primary=names[0],
                names_aliases=names[1:], country=country,
                address=address, programs=programs, reason=reason,
            )

    def _extract_names(self, elem) -> List[str]:
        """identity/name要素から名前リストを抽出"""
        names: List[str] = []
        spelling_variants: List[str] = []

        for identity in elem.iter("identity"):
            for name_elem in identity.iter("name"):
                parts_with_order: List[Tuple[int, str, str]] = []
                for name_part in name_elem.iter("name-part"):
                    order = int(name_part.get("order", "0"))
                    part_type = name_part.get("name-part-type", "")
                    value_elem = name_part.find("value")
                    value = value_elem.text.strip() if value_elem is not None and value_elem.text else ""
                    if value:
                        parts_with_order.append((order, part_type, value))
                    for sv in name_part.iter("spelling-variant"):
                        if sv.text and sv.text.strip():
                            variant = sv.text.strip()
                            if variant not in spelling_variants:
                                spelling_variants.append(variant)

                if parts_with_order:
                    parts_with_order.sort(key=lambda x: x[0])
                    given_parts = [v for _, t, v in parts_with_order if t == "given-name"]
                    family_parts = [v for _, t, v in parts_with_order if t == "family-name"]
                    other_parts = [v for _, t, v in parts_with_order if t == "father-name"]
                    whole_parts = [v for _, t, v in parts_with_order if t == "whole-name"]

                    if whole_parts:
                        full_name = " ".join(whole_parts)
                    elif given_parts or family_parts:
                        all_parts = given_parts + family_parts + other_parts
                        full_name = " ".join(all_parts)
                    else:
                        full_name = " ".join(v for _, _, v in parts_with_order)

                    if full_name and full_name not in names:
                        names.append(full_name)

        for variant in spelling_variants:
            if variant not in names:
                names.append(variant)

        return names

    def _extract_country(self, elem, place_map: Dict[str, str]) -> Optional[str]:
        """住所のplace-idから国名を解決"""
        for addr in elem.iter("address"):
            place_id = addr.get("place-id")
            if place_id and place_id in place_map:
                return place_map[place_id]
        for nat in elem.iter("nationality"):
            country = nat.findtext("country")
            if country and country.strip():
                return country.strip()
            place_id = nat.get("place-id")
            if place_id and place_id in place_map:
                return place_map[place_id]
        return None

    def _extract_address(self, elem, place_map: Dict[str, str]) -> Optional[str]:
        """住所情報を抽出"""
        addresses: List[str] = []
        for addr in elem.iter("address"):
            parts: List[str] = []
            for field_name in ["c-o", "address-details", "street", "city", "zip-code"]:
                val = addr.findtext(field_name)
                if val and val.strip():
                    parts.append(val.strip())
            place_id = addr.get("place-id")
            if place_id and place_id in place_map:
                parts.append(place_map[place_id])
            if parts:
                addresses.append(", ".join(parts))
        return "; ".join(addresses) if addresses else None

    def _extract_reason(self, elem) -> Optional[str]:
        """制裁理由を抽出"""
        for tag in ["justification", "other-information", "remark", "comment"]:
            val = elem.findtext(tag)
            if val and val.strip():
                return val.strip()
        return None
