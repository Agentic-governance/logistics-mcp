"""OFAC SDN List パーサー
URL: https://www.treasury.gov/ofac/downloads/sdn.xml
"""
import requests
from lxml import etree
from typing import Iterator
from .base import SanctionEntry, BaseParser

OFAC_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"


class OFACParser(BaseParser):
    source = "ofac"

    def fetch_and_parse(self) -> Iterator[SanctionEntry]:
        print("Fetching OFAC SDN List...")
        resp = requests.get(OFAC_URL, timeout=120)
        resp.raise_for_status()
        root = etree.fromstring(resp.content)

        # Detect namespace dynamically from root tag
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        for entry in root.iter(f"{ns}sdnEntry"):
            uid = entry.findtext(f"{ns}uid")
            first = entry.findtext(f"{ns}firstName") or ""
            last = entry.findtext(f"{ns}lastName") or ""
            name = f"{first} {last}".strip() if first else last
            entity_type_elem = entry.findtext(f"{ns}sdnType") or "Entity"

            aliases = []
            for aka in entry.iter(f"{ns}aka"):
                aka_first = aka.findtext(f"{ns}firstName") or ""
                aka_last = aka.findtext(f"{ns}lastName") or ""
                alias_name = f"{aka_first} {aka_last}".strip() if aka_first else aka_last
                if alias_name:
                    aliases.append(alias_name)

            programs = [p.text for p in entry.iter(f"{ns}program") if p.text]

            addresses = []
            for addr in entry.iter(f"{ns}address"):
                parts = [
                    addr.findtext(f"{ns}address1"),
                    addr.findtext(f"{ns}city"),
                    addr.findtext(f"{ns}country"),
                ]
                addresses.append(", ".join(p for p in parts if p))

            yield SanctionEntry(
                source="ofac",
                source_id=uid,
                entity_type=entity_type_elem.lower(),
                name_primary=name,
                names_aliases=aliases,
                country=addresses[0].split(", ")[-1] if addresses else None,
                address="; ".join(addresses),
                programs=programs,
                reason=None,
            )
