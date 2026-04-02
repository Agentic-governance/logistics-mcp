"""カナダDFATD制裁リスト パーサー
Department of Foreign Affairs, Trade and Development
XML形式、APIキー不要
URL: https://www.international.gc.ca/world-monde/assets/office_docs/international_relations-relations_internationales/sanctions/sema-lmes.xml

XML structure:
  <data-set>
    <record>
      <Country>...</Country>
      <LastName>...</LastName>           # For individuals
      <GivenName>...</GivenName>         # For individuals
      <EntityOrShip>...</EntityOrShip>   # For entities/ships
      <TitleOrShip>...</TitleOrShip>     # Title or ship type
      <Aliases>...</Aliases>
      <DateOfBirthOrShipBuildDate>...</DateOfBirthOrShipBuildDate>
      <Schedule>...</Schedule>
      <Item>...</Item>
      <DateOfListing>...</DateOfListing>
      <ShipIMONumber>...</ShipIMONumber>
    </record>
  </data-set>
"""
import requests
from lxml import etree
from typing import Iterator, List, Optional
from .base import SanctionEntry, BaseParser

CANADA_URL = (
    "https://www.international.gc.ca/world-monde/assets/office_docs/"
    "international_relations-relations_internationales/sanctions/sema-lmes.xml"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SupplyChainRiskMonitor/1.0)",
    "Accept": "text/xml, application/xml, */*",
}


class CanadaParser(BaseParser):
    source = "canada"

    def fetch_and_parse(self) -> Iterator[SanctionEntry]:
        print("Fetching Canada DFATD Sanctions List...")
        resp = requests.get(CANADA_URL, timeout=120, headers=HEADERS)
        resp.raise_for_status()
        root = etree.fromstring(resp.content)

        count = 0
        for record in root.iter("record"):
            entry = self._parse_record(record)
            if entry is not None:
                count += 1
                yield entry

        print(f"  Canada DFATD: parsed {count} entries")

    def _parse_record(self, record) -> Optional[SanctionEntry]:
        """<record>要素をSanctionEntryに変換"""
        # Determine if this is an individual or entity/ship record
        given_name = (record.findtext("GivenName") or "").strip()
        last_name = (record.findtext("LastName") or "").strip()
        entity_or_ship = (record.findtext("EntityOrShip") or "").strip()

        if given_name or last_name:
            # Individual record
            name = f"{given_name} {last_name}".strip()
            entity_type = "individual"
        elif entity_or_ship:
            # Entity or ship record
            name = entity_or_ship
            entity_type = "entity"
        else:
            return None

        if not name:
            return None

        # Country (may contain bilingual format like "Belarus / Bélarus")
        country_raw = (record.findtext("Country") or "").strip()
        country: Optional[str] = None
        if country_raw:
            # Take the English portion (before " / ")
            if " / " in country_raw:
                country = country_raw.split(" / ")[0].strip()
            else:
                country = country_raw

        # Aliases
        aliases: List[str] = []
        aliases_text = (record.findtext("Aliases") or "").strip()
        if aliases_text:
            # Aliases may contain multiple names separated by semicolons
            for alias in aliases_text.split(";"):
                alias = alias.strip()
                if alias and alias != name:
                    aliases.append(alias)
            # If no semicolons, the whole text is one alias
            if not aliases and aliases_text != name:
                aliases.append(aliases_text)

        # Title (for context, not typically an alias)
        title = (record.findtext("TitleOrShip") or "").strip()

        # Programs from Schedule field
        programs: List[str] = []
        schedule = (record.findtext("Schedule") or "").strip()
        if schedule:
            programs.append(f"SEMA Schedule {schedule}")

        # Source ID from Item
        item = (record.findtext("Item") or "").strip()
        source_id = item if item else None

        # Ship IMO number as additional identification
        imo = (record.findtext("ShipIMONumber") or "").strip()
        reason: Optional[str] = None
        if imo:
            reason = f"IMO: {imo}"
        if title:
            if reason:
                reason = f"{title}; {reason}"
            else:
                reason = title

        return SanctionEntry(
            source="canada",
            source_id=source_id,
            entity_type=entity_type,
            name_primary=name,
            names_aliases=aliases,
            country=country,
            address=None,
            programs=programs,
            reason=reason,
        )
