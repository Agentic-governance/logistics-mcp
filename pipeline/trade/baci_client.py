"""BACI (Base pour l'Analyse du Commerce International) Trade Data Client

BACI from CEPII/HEC Paris provides research-grade bilateral trade flow data
at the HS6 product level. Unlike raw UN Comtrade, BACI reconciles
exporter/importer declaration discrepancies via CIF/FOB correction, yielding
more precise and consistent values.

Data source: http://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37

Usage:
    client = BACIClient()
    flow = client.get_trade_flow("JPN", "CHN", "850710", year=2022)
    top = client.get_top_exporters("854231", top_n=10, year=2022)
    proxy = client.build_hs_proxy_from_baci(["JPN", "KOR"], ["8507", "8542"])
"""
from __future__ import annotations

import csv
import json
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
#  Project root detection
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent  # supply-chain-risk/

BACI_DATA_DIR = _PROJECT_ROOT / "data" / "baci"
COMTRADE_CACHE_DIR = _PROJECT_ROOT / "data" / "comtrade_cache"


# ---------------------------------------------------------------------------
#  Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class TradeFlow:
    """A single bilateral trade flow for a specific product and year."""
    reporter_iso3: str       # Exporter ISO3 code
    partner_iso3: str        # Importer ISO3 code
    hs6_code: str            # HS 6-digit product code
    year: int
    value_usd: float         # Trade value in USD
    quantity_kg: float       # Quantity in kilograms
    unit_value_usd: float    # Unit value (USD per kg)


@dataclass
class Exporter:
    """A country's export position for a given product."""
    country_iso3: str
    country_name: str
    export_value_usd: float
    world_share_pct: float   # Percentage of world exports (0-100)


# ---------------------------------------------------------------------------
#  BACI numeric country code -> ISO3 mapping
#  BACI uses the same UN M49 / ISO numeric codes as Comtrade.
#  This built-in mapping covers major trading economies. For full coverage,
#  download country_codes_V*.csv from the BACI distribution.
# ---------------------------------------------------------------------------
NUMERIC_TO_ISO3: dict[int, str] = {
    4: "AFG",    8: "ALB",   12: "DZA",   32: "ARG",   36: "AUS",
    40: "AUT",   50: "BGD",   56: "BEL",   76: "BRA",  100: "BGR",
    104: "MMR",  116: "KHM",  124: "CAN",  152: "CHL",  156: "CHN",
    170: "COL",  180: "COD",  191: "HRV",  203: "CZE",  208: "DNK",
    218: "ECU",  818: "EGY",  233: "EST",  231: "ETH",  246: "FIN",
    251: "FRA",  276: "DEU",  288: "GHA",  300: "GRC",  344: "HKG",
    348: "HUN",  356: "IND",  360: "IDN",  364: "IRN",  368: "IRQ",
    372: "IRL",  376: "ISR",  381: "ITA",  392: "JPN",  400: "JOR",
    398: "KAZ",  404: "KEN",  410: "KOR",  414: "KWT",  428: "LVA",
    440: "LTU",  458: "MYS",  484: "MEX",  504: "MAR",  528: "NLD",
    554: "NZL",  566: "NGA",  578: "NOR",  586: "PAK",  604: "PER",
    608: "PHL",  616: "POL",  620: "PRT",  634: "QAT",  642: "ROU",
    643: "RUS",  682: "SAU",  702: "SGP",  703: "SVK",  705: "SVN",
    710: "ZAF",  724: "ESP",  144: "LKA",  752: "SWE",  756: "CHE",
    490: "TWN",  764: "THA",  792: "TUR",  804: "UKR",  784: "ARE",
    826: "GBR",  842: "USA",  704: "VNM",  887: "YEM",
}

ISO3_TO_NUMERIC: dict[str, int] = {v: k for k, v in NUMERIC_TO_ISO3.items()}

# ISO3 -> full English country name (for display and fallback matching)
ISO3_TO_NAME: dict[str, str] = {
    "AFG": "Afghanistan",  "ALB": "Albania",      "DZA": "Algeria",
    "ARG": "Argentina",    "AUS": "Australia",     "AUT": "Austria",
    "BGD": "Bangladesh",   "BEL": "Belgium",       "BRA": "Brazil",
    "BGR": "Bulgaria",     "MMR": "Myanmar",       "KHM": "Cambodia",
    "CAN": "Canada",       "CHL": "Chile",         "CHN": "China",
    "COL": "Colombia",     "COD": "Congo",         "HRV": "Croatia",
    "CZE": "Czech Republic", "DNK": "Denmark",     "ECU": "Ecuador",
    "EGY": "Egypt",        "EST": "Estonia",       "ETH": "Ethiopia",
    "FIN": "Finland",      "FRA": "France",        "DEU": "Germany",
    "GHA": "Ghana",        "GRC": "Greece",        "HKG": "Hong Kong",
    "HUN": "Hungary",      "IND": "India",         "IDN": "Indonesia",
    "IRN": "Iran",         "IRQ": "Iraq",          "IRL": "Ireland",
    "ISR": "Israel",       "ITA": "Italy",         "JPN": "Japan",
    "JOR": "Jordan",       "KAZ": "Kazakhstan",    "KEN": "Kenya",
    "KOR": "South Korea",  "KWT": "Kuwait",        "LVA": "Latvia",
    "LTU": "Lithuania",    "MYS": "Malaysia",      "MEX": "Mexico",
    "MAR": "Morocco",      "NLD": "Netherlands",   "NZL": "New Zealand",
    "NGA": "Nigeria",      "NOR": "Norway",        "PAK": "Pakistan",
    "PER": "Peru",         "PHL": "Philippines",   "POL": "Poland",
    "PRT": "Portugal",     "QAT": "Qatar",         "ROU": "Romania",
    "RUS": "Russia",       "SAU": "Saudi Arabia",  "SGP": "Singapore",
    "SVK": "Slovakia",     "SVN": "Slovenia",      "ZAF": "South Africa",
    "ESP": "Spain",        "LKA": "Sri Lanka",     "SWE": "Sweden",
    "CHE": "Switzerland",  "TWN": "Taiwan",        "THA": "Thailand",
    "TUR": "Turkey",       "UKR": "Ukraine",       "ARE": "UAE",
    "GBR": "United Kingdom", "USA": "United States", "VNM": "Vietnam",
    "YEM": "Yemen",
}

# Reverse: country name -> ISO3 (case-insensitive lookup built at import time)
_NAME_TO_ISO3: dict[str, str] = {}
for _iso3, _name in ISO3_TO_NAME.items():
    _NAME_TO_ISO3[_name.lower()] = _iso3
# Add common aliases
_NAME_TO_ISO3.update({
    "south korea": "KOR", "korea": "KOR", "republic of korea": "KOR",
    "united states of america": "USA", "us": "USA",
    "united kingdom": "GBR", "uk": "GBR",
    "uae": "ARE", "united arab emirates": "ARE",
    "democratic republic of the congo": "COD", "dr congo": "COD", "drc": "COD",
    "hong kong": "HKG", "czech republic": "CZE", "czechia": "CZE",
})


def _resolve_to_iso3(country: str) -> str:
    """Best-effort conversion of a country identifier to ISO3 code.

    Accepts: ISO3 code, full country name, or common aliases.
    Returns the ISO3 code in uppercase, or the original string if unresolvable.
    """
    c = country.strip().upper()
    if c in ISO3_TO_NAME:
        return c
    # Try lowercase name lookup
    lower = country.strip().lower()
    if lower in _NAME_TO_ISO3:
        return _NAME_TO_ISO3[lower]
    # Try substring matching
    for name, iso3 in _NAME_TO_ISO3.items():
        if lower in name or name in lower:
            return iso3
    return country.upper()


def _resolve_name_to_iso3(country_name: str) -> str:
    """Convert a full country name (as used in HS_PROXY_DATA / comtrade cache)
    to ISO3. Falls back to the name itself."""
    return _resolve_to_iso3(country_name)


# ---------------------------------------------------------------------------
#  BACI Client
# ---------------------------------------------------------------------------
class BACIClient:
    """Client for querying BACI trade flow data.

    BACI CSV files are expected in ``data/baci/`` with naming like:
        BACI_HS17_Y2022_V202401.csv

    Columns: t (year), i (exporter numeric), j (importer numeric),
             k (HS6 code), v (value in thousands USD), q (quantity in tons)

    If the BACI data directory does not exist or is empty, all methods
    transparently fall back to Comtrade API / cache data.
    """

    def __init__(self, baci_dir: str | Path | None = None,
                 comtrade_cache_dir: str | Path | None = None):
        self.baci_dir = Path(baci_dir) if baci_dir else BACI_DATA_DIR
        self.comtrade_cache_dir = (
            Path(comtrade_cache_dir) if comtrade_cache_dir else COMTRADE_CACHE_DIR
        )
        self._baci_available = self._check_baci_availability()
        # In-memory index: keyed by (year, hs4_prefix) for fast filtering
        # Lazily populated on first query per year
        self._loaded_years: set[int] = set()
        # rows[year] = list of parsed dicts
        self._rows_by_year: dict[int, list[dict]] = {}

    # ------------------------------------------------------------------
    #  Availability check
    # ------------------------------------------------------------------
    def _check_baci_availability(self) -> bool:
        """Return True if BACI CSV files are present and non-empty."""
        if not self.baci_dir.is_dir():
            return False
        csv_files = list(self.baci_dir.glob("BACI_HS*_Y*_V*.csv"))
        return len(csv_files) > 0

    def _warn_fallback(self):
        """Emit a one-time warning when falling back to Comtrade data."""
        warnings.warn(
            "[BACIClient] BACI data not found in "
            f"'{self.baci_dir}'. Falling back to Comtrade API/cache. "
            "Run scripts/download_baci.py for instructions on obtaining BACI data.",
            stacklevel=3,
        )

    # ------------------------------------------------------------------
    #  BACI file loading
    # ------------------------------------------------------------------
    def _find_baci_file(self, year: int) -> Optional[Path]:
        """Locate the BACI CSV file for a given year."""
        if not self.baci_dir.is_dir():
            return None
        # Try exact pattern first
        candidates = sorted(self.baci_dir.glob(f"BACI_HS*_Y{year}_V*.csv"))
        if candidates:
            return candidates[-1]  # newest version
        return None

    def _load_year(self, year: int) -> bool:
        """Load BACI CSV for a given year into memory. Returns True on success."""
        if year in self._loaded_years:
            return True

        csv_path = self._find_baci_file(year)
        if csv_path is None:
            return False

        rows: list[dict] = []
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        parsed = {
                            "t": int(row.get("t", 0)),
                            "i": int(row.get("i", 0)),      # exporter numeric
                            "j": int(row.get("j", 0)),      # importer numeric
                            "k": str(row.get("k", "")).strip(),  # HS6 code
                            "v": float(row.get("v", 0)),    # value in thousands USD
                            "q": float(row.get("q", 0)) if row.get("q", "NA") not in ("", "NA") else 0.0,
                        }
                        rows.append(parsed)
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            print(f"[BACIClient] Error loading {csv_path}: {e}", file=sys.stderr)
            return False

        self._rows_by_year[year] = rows
        self._loaded_years.add(year)
        print(f"[BACIClient] Loaded {len(rows):,} rows from {csv_path.name}")
        return True

    def _query_rows(self, year: int,
                    exporter_num: int | None = None,
                    importer_num: int | None = None,
                    hs6_code: str | None = None,
                    hs4_prefix: str | None = None) -> list[dict]:
        """Filter loaded BACI rows by criteria."""
        if year not in self._rows_by_year:
            return []
        result = []
        for row in self._rows_by_year[year]:
            if exporter_num is not None and row["i"] != exporter_num:
                continue
            if importer_num is not None and row["j"] != importer_num:
                continue
            if hs6_code is not None and row["k"] != hs6_code:
                continue
            if hs4_prefix is not None and not row["k"].startswith(hs4_prefix):
                continue
            result.append(row)
        return result

    # ------------------------------------------------------------------
    #  Comtrade Fallback helpers
    # ------------------------------------------------------------------
    def _load_comtrade_cache(self, importer_name_lower: str, hs_code: str) -> Optional[dict]:
        """Load a Comtrade cache file (e.g. japan_8507.json)."""
        cache_key = f"{importer_name_lower.replace(' ', '_')}_{hs_code}"
        cache_path = self.comtrade_cache_dir / f"{cache_key}.json"
        if cache_path.is_file():
            try:
                with open(cache_path, "r") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _fallback_get_trade_flow(self, reporter_iso3: str, partner_iso3: str,
                                  hs6_code: str, year: int) -> Optional[TradeFlow]:
        """Attempt to derive a trade flow from Comtrade cache.

        Comtrade cache is structured as {importer -> sources[{country, share, value_usd}]}.
        We look for the importer=partner (who imports from reporter=exporter).
        """
        partner_name = ISO3_TO_NAME.get(partner_iso3, partner_iso3).lower()
        hs4 = hs6_code[:4]

        cache_data = self._load_comtrade_cache(partner_name, hs4)
        if not cache_data:
            # Also try with hs6
            cache_data = self._load_comtrade_cache(partner_name, hs6_code)
        if not cache_data:
            return None

        reporter_name = ISO3_TO_NAME.get(reporter_iso3, reporter_iso3)
        for src in cache_data.get("sources", []):
            src_iso3 = _resolve_name_to_iso3(src["country"])
            if src_iso3 == reporter_iso3 or src["country"].lower() == reporter_name.lower():
                value = src.get("value_usd", 0)
                return TradeFlow(
                    reporter_iso3=reporter_iso3,
                    partner_iso3=partner_iso3,
                    hs6_code=hs6_code,
                    year=year,
                    value_usd=value,
                    quantity_kg=0.0,
                    unit_value_usd=0.0,
                )
        return None

    def _fallback_get_top_exporters(self, hs6_code: str, top_n: int,
                                     year: int) -> list[Exporter]:
        """Estimate top exporters from Comtrade cache by aggregating all
        importers' source data for a given HS code."""
        hs4 = hs6_code[:4]
        export_totals: dict[str, float] = {}

        if not self.comtrade_cache_dir.is_dir():
            return []

        for cache_file in self.comtrade_cache_dir.glob(f"*_{hs4}.json"):
            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)
                for src in data.get("sources", []):
                    iso3 = _resolve_name_to_iso3(src["country"])
                    export_totals[iso3] = export_totals.get(iso3, 0) + src.get("value_usd", 0)
            except Exception:
                continue

        if not export_totals:
            return []

        total_world = sum(export_totals.values())
        sorted_exporters = sorted(export_totals.items(), key=lambda x: -x[1])

        results = []
        for iso3, value in sorted_exporters[:top_n]:
            share_pct = (value / total_world * 100) if total_world > 0 else 0.0
            results.append(Exporter(
                country_iso3=iso3,
                country_name=ISO3_TO_NAME.get(iso3, iso3),
                export_value_usd=value,
                world_share_pct=round(share_pct, 2),
            ))
        return results

    # ------------------------------------------------------------------
    #  Public API: get_trade_flow
    # ------------------------------------------------------------------
    def get_trade_flow(self, reporter_iso3: str, partner_iso3: str,
                       hs6_code: str, year: int = 2022) -> Optional[TradeFlow]:
        """Look up a specific country-pair x product bilateral trade flow.

        Args:
            reporter_iso3: Exporter country ISO3 code (e.g. "CHN")
            partner_iso3:  Importer country ISO3 code (e.g. "JPN")
            hs6_code:      HS 6-digit product code (e.g. "850710")
            year:          Reference year (default 2022)

        Returns:
            TradeFlow dataclass with value_usd, quantity_kg, unit_value_usd,
            or None if no matching record is found.
        """
        reporter_iso3 = _resolve_to_iso3(reporter_iso3)
        partner_iso3 = _resolve_to_iso3(partner_iso3)

        # --- BACI path ---
        if self._baci_available and self._load_year(year):
            exp_num = ISO3_TO_NUMERIC.get(reporter_iso3)
            imp_num = ISO3_TO_NUMERIC.get(partner_iso3)
            if exp_num is not None and imp_num is not None:
                matches = self._query_rows(year, exporter_num=exp_num,
                                           importer_num=imp_num, hs6_code=hs6_code)
                if matches:
                    row = matches[0]
                    value_usd = row["v"] * 1000.0          # thousands -> USD
                    quantity_kg = row["q"] * 1000.0         # tons -> kg
                    unit_value = (value_usd / quantity_kg) if quantity_kg > 0 else 0.0
                    return TradeFlow(
                        reporter_iso3=reporter_iso3,
                        partner_iso3=partner_iso3,
                        hs6_code=hs6_code,
                        year=year,
                        value_usd=value_usd,
                        quantity_kg=quantity_kg,
                        unit_value_usd=round(unit_value, 2),
                    )
                # HS6 not found; try HS4 prefix aggregation
                hs4 = hs6_code[:4]
                matches_hs4 = self._query_rows(year, exporter_num=exp_num,
                                               importer_num=imp_num, hs4_prefix=hs4)
                if matches_hs4:
                    total_v = sum(r["v"] for r in matches_hs4) * 1000.0
                    total_q = sum(r["q"] for r in matches_hs4) * 1000.0
                    unit_value = (total_v / total_q) if total_q > 0 else 0.0
                    return TradeFlow(
                        reporter_iso3=reporter_iso3,
                        partner_iso3=partner_iso3,
                        hs6_code=hs6_code,
                        year=year,
                        value_usd=total_v,
                        quantity_kg=total_q,
                        unit_value_usd=round(unit_value, 2),
                    )

        # --- Fallback: Comtrade cache / API ---
        self._warn_fallback()
        return self._fallback_get_trade_flow(reporter_iso3, partner_iso3, hs6_code, year)

    # ------------------------------------------------------------------
    #  Public API: get_top_exporters
    # ------------------------------------------------------------------
    def get_top_exporters(self, hs6_code: str, top_n: int = 10,
                          year: int = 2022) -> list[Exporter]:
        """Return the top N exporting countries for a product by world export share.

        Args:
            hs6_code: HS 6-digit product code (also works with 4-digit prefix)
            top_n:    Number of top exporters to return (default 10)
            year:     Reference year (default 2022)

        Returns:
            List of Exporter dataclasses sorted by world_share_pct descending.
        """
        # --- BACI path ---
        if self._baci_available and self._load_year(year):
            # Determine if hs6 or hs4
            use_hs6 = len(hs6_code) >= 6
            if use_hs6:
                rows = self._query_rows(year, hs6_code=hs6_code)
            else:
                rows = self._query_rows(year, hs4_prefix=hs6_code[:4])

            # Aggregate by exporter
            export_totals: dict[int, float] = {}
            for row in rows:
                exp = row["i"]
                export_totals[exp] = export_totals.get(exp, 0) + row["v"]

            if not export_totals:
                self._warn_fallback()
                return self._fallback_get_top_exporters(hs6_code, top_n, year)

            total_world = sum(export_totals.values())
            sorted_exp = sorted(export_totals.items(), key=lambda x: -x[1])

            results = []
            for num_code, v_thousands in sorted_exp[:top_n]:
                iso3 = NUMERIC_TO_ISO3.get(num_code, f"NUM{num_code}")
                name = ISO3_TO_NAME.get(iso3, iso3)
                value_usd = v_thousands * 1000.0
                share_pct = (v_thousands / total_world * 100) if total_world > 0 else 0.0
                results.append(Exporter(
                    country_iso3=iso3,
                    country_name=name,
                    export_value_usd=value_usd,
                    world_share_pct=round(share_pct, 2),
                ))
            return results

        # --- Fallback ---
        self._warn_fallback()
        return self._fallback_get_top_exporters(hs6_code, top_n, year)

    # ------------------------------------------------------------------
    #  Public API: build_hs_proxy_from_baci
    # ------------------------------------------------------------------
    def build_hs_proxy_from_baci(self, manufacturing_countries: list[str],
                                  hs_codes: list[str],
                                  year: int = 2022,
                                  min_share: float = 0.02) -> dict:
        """Auto-generate HS_PROXY_DATA format from BACI data.

        This replaces/supplements the manually-defined HS_PROXY_DATA in
        tier_inference.py. For each (HS code, importer country) pair, it
        computes the import source shares.

        Args:
            manufacturing_countries: ISO3 codes of importing/manufacturing
                                    countries (e.g. ["JPN", "KOR", "DEU"])
            hs_codes:   HS codes to analyze (4 or 6 digit, e.g. ["8507", "8542"])
            year:       Reference year
            min_share:  Minimum trade share to include a source (default 2%)

        Returns:
            Dict matching HS_PROXY_DATA format:
            {
                "8507": {
                    "JPN": {
                        "suppliers": {"CHN": 0.71, "KOR": 0.13, ...}
                    }
                }
            }

        Note: If BACI data is unavailable, builds from Comtrade cache instead.
        """
        result: dict[str, dict] = {}

        # Resolve country identifiers to ISO3
        resolved_countries = [_resolve_to_iso3(c) for c in manufacturing_countries]

        for hs_code in hs_codes:
            hs_key = hs_code[:4] if len(hs_code) <= 4 else hs_code
            result.setdefault(hs_key, {})

            for country_iso3 in resolved_countries:
                suppliers = self._get_import_suppliers(
                    country_iso3, hs_code, year, min_share
                )
                if suppliers:
                    result[hs_key][country_iso3] = {"suppliers": suppliers}

        return result

    def _get_import_suppliers(self, importer_iso3: str, hs_code: str,
                               year: int, min_share: float) -> dict[str, float]:
        """Get import supplier shares for a country/HS code pair.

        Returns: {"CHN": 0.71, "KOR": 0.13, ...}
        """
        # --- BACI path ---
        if self._baci_available and self._load_year(year):
            imp_num = ISO3_TO_NUMERIC.get(importer_iso3)
            if imp_num is not None:
                use_hs6 = len(hs_code) >= 6
                if use_hs6:
                    rows = self._query_rows(year, importer_num=imp_num, hs6_code=hs_code)
                else:
                    rows = self._query_rows(year, importer_num=imp_num, hs4_prefix=hs_code[:4])

                if rows:
                    # Aggregate by exporter
                    exp_totals: dict[int, float] = {}
                    for row in rows:
                        exp = row["i"]
                        exp_totals[exp] = exp_totals.get(exp, 0) + row["v"]

                    total = sum(exp_totals.values())
                    if total > 0:
                        suppliers: dict[str, float] = {}
                        for num_code, v in sorted(exp_totals.items(), key=lambda x: -x[1]):
                            share = v / total
                            if share < min_share:
                                continue
                            iso3 = NUMERIC_TO_ISO3.get(num_code, f"NUM{num_code}")
                            suppliers[iso3] = round(share, 4)
                        return suppliers

        # --- Fallback: Comtrade cache ---
        self._warn_fallback()
        return self._fallback_get_import_suppliers(importer_iso3, hs_code, min_share)

    def _fallback_get_import_suppliers(self, importer_iso3: str, hs_code: str,
                                        min_share: float) -> dict[str, float]:
        """Build import supplier shares from Comtrade cache."""
        importer_name = ISO3_TO_NAME.get(importer_iso3, importer_iso3).lower()
        hs4 = hs_code[:4]

        cache_data = self._load_comtrade_cache(importer_name, hs4)
        if not cache_data:
            cache_data = self._load_comtrade_cache(importer_name, hs_code)
        if not cache_data:
            return {}

        suppliers: dict[str, float] = {}
        for src in cache_data.get("sources", []):
            share = src.get("share", 0)
            if share < min_share:
                continue
            iso3 = _resolve_name_to_iso3(src["country"])
            suppliers[iso3] = round(share, 4)
        return suppliers

    # ------------------------------------------------------------------
    #  Utility: list available years
    # ------------------------------------------------------------------
    def available_years(self) -> list[int]:
        """List years for which BACI CSV files are available."""
        if not self.baci_dir.is_dir():
            return []
        years = set()
        for f in self.baci_dir.glob("BACI_HS*_Y*_V*.csv"):
            # Extract year from filename like BACI_HS17_Y2022_V202401.csv
            parts = f.stem.split("_")
            for part in parts:
                if part.startswith("Y") and part[1:].isdigit():
                    years.add(int(part[1:]))
        return sorted(years)

    def __repr__(self) -> str:
        mode = "BACI" if self._baci_available else "Comtrade-fallback"
        return f"<BACIClient mode={mode} baci_dir='{self.baci_dir}'>"


# ---------------------------------------------------------------------------
#  Module-level convenience
# ---------------------------------------------------------------------------
def get_client(**kwargs) -> BACIClient:
    """Factory function for creating a BACIClient with default settings."""
    return BACIClient(**kwargs)
