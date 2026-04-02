"""UK OFSI Consolidated List パーサー
Office of Financial Sanctions Implementation
CSV形式、APIキー不要
URL: https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv

CSV structure (line 0 is metadata "Last Updated,...", line 1 is the header):
  Name 6 (surname), Name 1, Name 2, Name 3, Name 4, Name 5,
  Title, Name Non-Latin Script, ...,
  DOB, Country of Birth, Nationality, ...,
  Address 1-6, Post/Zip Code, Country,
  Other Information, Group Type, Alias Type, Alias Quality,
  Regime, Listed On, ..., Group ID

Multiple rows can share the same Group ID (aliases of same entity).
"""
import csv
import io
import requests
from typing import Dict, Iterator, List, Optional
from .base import SanctionEntry, BaseParser

OFSI_URL = "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv"

HEADERS = {
    "User-Agent": "SupplyChainRiskMonitor/1.0 (compliance screening)",
}


class OFSIParser(BaseParser):
    source = "ofsi"

    def fetch_and_parse(self) -> Iterator[SanctionEntry]:
        print("Fetching UK OFSI Consolidated List...")
        resp = requests.get(OFSI_URL, timeout=120, headers=HEADERS)
        resp.raise_for_status()

        # OFSI CSV uses UTF-8 BOM encoding; first line is metadata
        text = resp.content.decode("utf-8-sig")
        lines = text.split("\n")

        # Skip the metadata line (line 0: "Last Updated,27/01/2026")
        if len(lines) < 2:
            print("  OFSI: CSV too short")
            return

        csv_text = "\n".join(lines[1:])
        reader = csv.DictReader(io.StringIO(csv_text))

        # Group rows by Group ID to consolidate aliases
        groups: Dict[str, List[dict]] = {}
        ungrouped: List[dict] = []

        for row in reader:
            group_id = (row.get("Group ID") or "").strip()
            if group_id:
                groups.setdefault(group_id, []).append(row)
            else:
                ungrouped.append(row)

        # Process grouped entries
        for group_id, rows in groups.items():
            entry = self._build_entry_from_group(group_id, rows)
            if entry is not None:
                yield entry

        # Process ungrouped entries
        for row in ungrouped:
            entry = self._build_entry_from_group(None, [row])
            if entry is not None:
                yield entry

        total = len(groups) + len(ungrouped)
        print(f"  OFSI: parsed {total} entries ({len(groups)} grouped, {len(ungrouped)} ungrouped)")

    def _build_entry_from_group(
        self, group_id: Optional[str], rows: List[dict]
    ) -> Optional[SanctionEntry]:
        """同一Group IDの行群から1つのSanctionEntryを構築"""
        if not rows:
            return None

        all_names: List[str] = []
        primary_name: Optional[str] = None

        for row in rows:
            name = self._build_name(row)
            if not name:
                continue

            alias_type = (row.get("Alias Type") or "").strip().lower()

            if alias_type in ("primary name", "") and primary_name is None:
                primary_name = name
            elif name not in all_names:
                all_names.append(name)

            # Non-Latin script name as alias
            non_latin = (row.get("Name Non-Latin Script") or "").strip()
            if non_latin and non_latin not in all_names:
                all_names.append(non_latin)

        if primary_name is None:
            # Use first available name as primary
            if all_names:
                primary_name = all_names.pop(0)
            else:
                return None

        # Remove primary from aliases
        aliases = [n for n in all_names if n != primary_name]

        # Use first row for metadata
        first_row = rows[0]

        # Group Type -> entity_type
        group_type = (first_row.get("Group Type") or "").strip()
        if group_type.lower() == "individual":
            entity_type = "individual"
        else:
            entity_type = "entity"

        # Country
        country = (first_row.get("Country") or "").strip() or None
        if not country:
            country = (first_row.get("Nationality") or "").strip() or None

        # Address
        address = self._build_address(first_row)

        # Programs from Regime
        regime = (first_row.get("Regime") or "").strip()
        programs = [regime] if regime else []

        # Reason from Other Information
        reason = (first_row.get("Other Information") or "").strip() or None

        return SanctionEntry(
            source="ofsi",
            source_id=group_id,
            entity_type=entity_type,
            name_primary=primary_name,
            names_aliases=aliases,
            country=country,
            address=address,
            programs=programs,
            reason=reason,
        )

    def _build_name(self, row: dict) -> Optional[str]:
        """行からName 1-6を組み合わせて名前を構築

        OFSI CSV column order: Name 6 (surname) is first column,
        followed by Name 1 through Name 5. We combine them in
        Name 1, Name 2, ..., Name 6 order for natural reading.
        """
        parts: List[str] = []
        for i in range(1, 7):
            val = (row.get(f"Name {i}") or "").strip()
            if val:
                parts.append(val)

        if not parts:
            return None

        return " ".join(parts)

    def _build_address(self, row: dict) -> Optional[str]:
        """行からAddress 1-6 + Post/Zip Code + Countryを構築"""
        parts: List[str] = []
        for i in range(1, 7):
            val = (row.get(f"Address {i}") or "").strip()
            if val:
                parts.append(val)

        zip_code = (row.get("Post/Zip Code") or "").strip()
        if zip_code:
            parts.append(zip_code)

        country = (row.get("Country") or "").strip()
        if country:
            parts.append(country)

        return ", ".join(parts) if parts else None
