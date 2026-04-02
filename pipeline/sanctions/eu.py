"""EU Sanctions List パーサー
Primary: webgate.ec.europa.eu (XML Full Sanctions List v1.1)
The endpoint requires a token parameter; without it the server returns 403.
"""
import requests
from lxml import etree
from typing import Iterator, Optional
from .base import SanctionEntry, BaseParser

# Primary URL (requires token)
EU_URL_PRIMARY = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/"
    "xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"
)

# Fallback: EU open-data portal (may lag behind the primary)
EU_URL_FALLBACK = (
    "https://data.europa.eu/api/hub/store/data/"
    "consolidated-list-of-persons-groups-and-entities-"
    "subject-to-eu-financial-sanctions.xml"
)


class EUParser(BaseParser):
    source = "eu"

    # Ordered list of URLs to attempt
    _urls = [EU_URL_PRIMARY, EU_URL_FALLBACK]

    def fetch_and_parse(self) -> Iterator[SanctionEntry]:
        print("Fetching EU Sanctions List...")
        headers = {
            "User-Agent": "SCRI-Platform/0.4",
            "Accept": "application/xml",
        }

        content: Optional[bytes] = None
        for url in self._urls:
            try:
                resp = requests.get(url, timeout=120, headers=headers)
                resp.raise_for_status()
                content = resp.content
                print(f"  Loaded from {url} ({len(content)} bytes)")
                break
            except Exception as exc:
                print(f"  Failed {url}: {exc}")

        if content is None:
            print("EU Sanctions List: all fetch attempts failed")
            return

        root = etree.fromstring(content)

        for subject in root.iter("subject"):
            subject_id = subject.get("logicalId")
            entity_type = subject.get("subjectType", "entity").lower()

            names: list[str] = []
            for name_alias in subject.iter("nameAlias"):
                full_name = name_alias.get("wholeName") or \
                    f"{name_alias.get('firstName', '')} {name_alias.get('lastName', '')}".strip()
                if full_name:
                    names.append(full_name)

            if not names:
                continue

            addresses: list[str] = []
            for addr in subject.iter("address"):
                parts = [addr.get("street"), addr.get("city"), addr.get("countryDescription")]
                addresses.append(", ".join(p for p in parts if p))

            regulations = [r.get("programme", "") for r in subject.iter("regulation")]

            yield SanctionEntry(
                source="eu",
                source_id=subject_id,
                entity_type=entity_type,
                name_primary=names[0],
                names_aliases=names[1:],
                country=next((a.get("countryDescription") for a in subject.iter("address")), None),
                address="; ".join(addresses),
                programs=regulations,
                reason=next((r.get("numberTitle") for r in subject.iter("regulation")), None),
            )
