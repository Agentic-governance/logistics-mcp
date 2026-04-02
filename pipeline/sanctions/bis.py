"""BIS Entity List パーサー
Bureau of Industry and Security - Entity List

The old bis.doc.gov CSV endpoint now redirects to the bis.gov homepage.
We use the trade.gov Consolidated Screening List CSV instead, which
contains BIS Entity List entries (source == "Entity List (EL) - Bureau of
Industry and Security") alongside other lists.

Fallback: attempt the legacy bis.doc.gov URL in case it is restored.
"""
import requests
import pandas as pd
import io
from typing import Iterator, Optional
from .base import SanctionEntry, BaseParser

# Primary: trade.gov CSL CSV (contains BIS Entity List records)
CSL_CSV_URL = (
    "https://data.trade.gov/downloadable_consolidated_screening_list/"
    "v1/consolidated.csv"
)

# Legacy BIS Entity List CSV (currently redirects to bis.gov homepage)
BIS_LEGACY_CSV_URL = "https://www.bis.doc.gov/entities/entity_list.csv"

HEADERS = {
    "User-Agent": "SCRI-Platform/0.4 (compliance screening)",
}


class BISParser(BaseParser):
    source = "bis"

    def fetch_and_parse(self) -> Iterator[SanctionEntry]:
        print("Fetching BIS Entity List...")
        df = None

        # ------- Strategy 1: CSL CSV (primary) -------
        try:
            resp = requests.get(CSL_CSV_URL, timeout=120, headers=HEADERS)
            resp.raise_for_status()
            full_df = pd.read_csv(io.StringIO(resp.text), encoding="utf-8")
            # Filter to BIS Entity List entries only
            bis_mask = full_df["source"].str.contains(
                "Entity List", case=False, na=False
            )
            df = full_df[bis_mask].copy()
            print(f"  CSL CSV loaded: {len(full_df)} total rows, "
                  f"{len(df)} BIS Entity List rows")
        except Exception as exc:
            print(f"  CSL CSV failed: {exc}")

        # ------- Strategy 2: legacy BIS CSV (fallback) -------
        if df is None or df.empty:
            for encoding in ["utf-8", "latin-1"]:
                try:
                    resp = requests.get(
                        BIS_LEGACY_CSV_URL, timeout=60,
                        headers=HEADERS, verify=False,
                        allow_redirects=False,   # avoid silent redirect to homepage
                    )
                    resp.raise_for_status()
                    content_type = resp.headers.get("Content-Type", "")
                    if "html" in content_type.lower():
                        print("  Legacy BIS URL returned HTML (redirect); skipping")
                        break
                    df = pd.read_csv(
                        io.StringIO(resp.text), encoding=encoding
                    )
                    print(f"  Legacy BIS CSV loaded ({encoding}): {len(df)} rows")
                    break
                except Exception:
                    continue

        if df is None or df.empty:
            print("BIS Entity List: all fetch attempts failed")
            return

        # Normalize column names
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        name_col = self._find_column(df, ["name", "entity_name", "entity"])
        country_col = self._find_column(df, ["country", "nationality"])
        address_col = self._find_column(df, ["addresses", "address", "street_address"])
        reason_col = self._find_column(
            df, ["license_requirement", "reason",
                 "federal_register_notice", "remarks"]
        )
        programs_col = self._find_column(df, ["programs"])

        if not name_col:
            print(f"BIS CSV: could not find name column in {list(df.columns)}")
            return

        for _, row in df.iterrows():
            name = str(row.get(name_col, "")).strip()
            if not name or name == "nan":
                continue

            country = str(row.get(country_col, "")).strip() if country_col else None
            if country == "nan":
                country = None

            address = str(row.get(address_col, "")).strip() if address_col else None
            if address == "nan":
                address = None

            reason = str(row.get(reason_col, "")).strip() if reason_col else None
            if reason == "nan":
                reason = None

            programs_raw = str(row.get(programs_col, "")).strip() if programs_col else ""
            if programs_raw and programs_raw != "nan":
                programs = [p.strip() for p in programs_raw.split(";") if p.strip()]
            else:
                programs = ["BIS_ENTITY_LIST"]

            yield SanctionEntry(
                source="bis",
                source_id=None,
                entity_type="entity",
                name_primary=name,
                names_aliases=[],
                country=country,
                address=address,
                programs=programs,
                reason=reason,
            )

    def _find_column(
        self, df: pd.DataFrame, candidates: "list[str]"
    ) -> Optional[str]:
        """Return the first column whose name contains one of *candidates*."""
        for col in df.columns:
            for candidate in candidates:
                if candidate in col:
                    return col
        return None
