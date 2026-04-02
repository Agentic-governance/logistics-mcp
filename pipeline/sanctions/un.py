"""UN Sanctions Consolidated List パーサー
URL: https://scsanctions.un.org/resources/xml/en/consolidated.xml
"""
import requests
from lxml import etree
from typing import Iterator
from .base import SanctionEntry, BaseParser

UN_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"


class UNParser(BaseParser):
    source = "un"

    def fetch_and_parse(self) -> Iterator[SanctionEntry]:
        print("Fetching UN Consolidated Sanctions List...")
        resp = requests.get(UN_URL, timeout=60)
        resp.raise_for_status()
        root = etree.fromstring(resp.content)

        # Process INDIVIDUAL entries
        for individual in root.iter("INDIVIDUAL"):
            yield from self._parse_individual(individual)

        # Process ENTITY entries
        for entity in root.iter("ENTITY"):
            yield from self._parse_entity(entity)

    def _parse_individual(self, elem) -> Iterator[SanctionEntry]:
        dataid = elem.findtext("DATAID")
        first = elem.findtext("FIRST_NAME") or ""
        second = elem.findtext("SECOND_NAME") or ""
        third = elem.findtext("THIRD_NAME") or ""
        name_parts = [p for p in [first, second, third] if p]
        name = " ".join(name_parts)

        if not name:
            return

        aliases = []
        for alias in elem.iter("INDIVIDUAL_ALIAS"):
            alias_name = alias.findtext("ALIAS_NAME")
            if alias_name:
                aliases.append(alias_name)

        nationality = elem.findtext("NATIONALITY/VALUE") or None
        address_parts = []
        for addr in elem.iter("INDIVIDUAL_ADDRESS"):
            parts = [
                addr.findtext("STREET"),
                addr.findtext("CITY"),
                addr.findtext("COUNTRY"),
            ]
            address_parts.append(", ".join(p for p in parts if p))

        country = None
        for addr in elem.iter("INDIVIDUAL_ADDRESS"):
            c = addr.findtext("COUNTRY")
            if c:
                country = c
                break
        if not country:
            country = nationality

        programs = []
        for listing in elem.iter("UN_LIST_TYPE"):
            if listing.text:
                programs.append(listing.text)

        comments = elem.findtext("COMMENTS1") or None

        yield SanctionEntry(
            source="un",
            source_id=dataid,
            entity_type="individual",
            name_primary=name,
            names_aliases=aliases,
            country=country,
            address="; ".join(address_parts) if address_parts else None,
            programs=programs,
            reason=comments,
        )

    def _parse_entity(self, elem) -> Iterator[SanctionEntry]:
        dataid = elem.findtext("DATAID")
        name = elem.findtext("FIRST_NAME") or ""

        if not name:
            return

        aliases = []
        for alias in elem.iter("ENTITY_ALIAS"):
            alias_name = alias.findtext("ALIAS_NAME")
            if alias_name:
                aliases.append(alias_name)

        address_parts = []
        for addr in elem.iter("ENTITY_ADDRESS"):
            parts = [
                addr.findtext("STREET"),
                addr.findtext("CITY"),
                addr.findtext("COUNTRY"),
            ]
            address_parts.append(", ".join(p for p in parts if p))

        country = None
        for addr in elem.iter("ENTITY_ADDRESS"):
            c = addr.findtext("COUNTRY")
            if c:
                country = c
                break

        programs = []
        for listing in elem.iter("UN_LIST_TYPE"):
            if listing.text:
                programs.append(listing.text)

        comments = elem.findtext("COMMENTS1") or None

        yield SanctionEntry(
            source="un",
            source_id=dataid,
            entity_type="entity",
            name_primary=name,
            names_aliases=aliases,
            country=country,
            address="; ".join(address_parts) if address_parts else None,
            programs=programs,
            reason=comments,
        )
