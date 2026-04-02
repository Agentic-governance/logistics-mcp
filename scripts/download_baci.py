#!/usr/bin/env python3
"""BACI Trade Data - Download & Processing Script

BACI (Base pour l'Analyse du Commerce International) from CEPII provides
research-grade bilateral trade flow data that reconciles exporter/importer
declaration differences (CIF/FOB correction).

This script:
  1. Prints instructions for downloading BACI data from CEPII
  2. Explains required registration and file structure
  3. Optionally processes raw BACI CSV into optimized formats
     (filtered CSV for relevant HS codes, or SQLite database)

Usage:
    python scripts/download_baci.py                 # Print download instructions
    python scripts/download_baci.py --process       # Process raw BACI data after download
    python scripts/download_baci.py --process --sqlite  # Also build SQLite database
    python scripts/download_baci.py --verify        # Verify existing BACI data
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from pathlib import Path

# Project root: two levels up from scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACI_DIR = PROJECT_ROOT / "data" / "baci"

# HS codes used by the SCRI platform (from tier_inference.py)
RELEVANT_HS4_CODES = {
    "2504",  # graphite
    "2601",  # iron ores
    "2603",  # copper ores
    "2604",  # nickel ores
    "2605",  # cobalt ores
    "2606",  # aluminum ores
    "2804",  # silicon
    "2818",  # alumina
    "2825",  # lithium oxide / rare-earth
    "2836",  # lithium carbonate
    "2846",  # rare-earth compounds
    "3901",  # polyethylene
    "3907",  # polyesters
    "3920",  # plastic film/sheets
    "4001",  # natural rubber
    "7005",  # float glass
    "7007",  # safety glass
    "7110",  # platinum
    "7202",  # ferroalloys
    "7206",  # iron/steel
    "7207",  # iron/steel semi-finished
    "7403",  # refined copper
    "7410",  # copper foil
    "7502",  # unwrought nickel
    "7601",  # unwrought aluminum
    "8105",  # cobalt
    "8501",  # electric motors
    "8507",  # batteries
    "8524",  # OLED/LCD modules
    "8534",  # PCBs
    "8541",  # diodes/transistors
    "8542",  # integrated circuits
    "8544",  # electric wire/cable
    "8703",  # passenger vehicles
    "8708",  # auto parts
    "9013",  # optical lenses
    "9031",  # measuring instruments
}


def print_download_instructions():
    """Print step-by-step instructions for downloading BACI data."""
    print("=" * 76)
    print("  BACI Trade Data - Download Instructions")
    print("=" * 76)
    print()
    print("  BACI (Base pour l'Analyse du Commerce International)")
    print("  Published by CEPII / HEC Paris")
    print()
    print("  BACI provides reconciled bilateral trade data at the HS 6-digit")
    print("  product level. It corrects CIF/FOB discrepancies between export")
    print("  and import declarations, making it more accurate than raw Comtrade.")
    print()
    print("-" * 76)
    print("  Step 1: Register (free) at CEPII")
    print("-" * 76)
    print()
    print("  Visit: http://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37")
    print()
    print("  Click 'Download the data' and create a free CEPII account if you")
    print("  do not already have one. Academic and research use is free.")
    print()
    print("-" * 76)
    print("  Step 2: Download the CSV files")
    print("-" * 76)
    print()
    print("  After logging in, download the BACI dataset in CSV format.")
    print("  The full dataset is approximately 3 GB compressed.")
    print()
    print("  Download files named like:")
    print("    BACI_HS17_Y2022_V202401.csv")
    print("    BACI_HS17_Y2021_V202401.csv")
    print()
    print("  Also download the auxiliary file:")
    print("    country_codes_V202401.csv   (numeric -> ISO3 mapping)")
    print()
    print("-" * 76)
    print("  Step 3: Place files in the expected directory")
    print("-" * 76)
    print()
    print(f"  Target directory: {BACI_DIR}")
    print()
    print("  Expected structure:")
    print(f"    {BACI_DIR}/")
    print("    +-- BACI_HS17_Y2022_V202401.csv")
    print("    +-- BACI_HS17_Y2021_V202401.csv  (optional, for time series)")
    print("    +-- country_codes_V202401.csv     (optional, for full mapping)")
    print()
    print("-" * 76)
    print("  Step 4: Process the data (optional but recommended)")
    print("-" * 76)
    print()
    print("  After placing the CSV files, run this script with --process:")
    print()
    print("    python scripts/download_baci.py --process")
    print()
    print("  This will filter the ~3GB CSV down to only the HS codes relevant")
    print("  to the SCRI platform (~40 HS4 codes), reducing load time by ~95%.")
    print()
    print("  Optionally, add --sqlite to also build a SQLite database:")
    print()
    print("    python scripts/download_baci.py --process --sqlite")
    print()
    print("-" * 76)
    print("  BACI CSV Column Reference")
    print("-" * 76)
    print()
    print("  Column  Description                  Example")
    print("  ------  ---------------------------  --------")
    print("  t       Year                         2022")
    print("  i       Exporter (numeric code)      392 (Japan)")
    print("  j       Importer (numeric code)      156 (China)")
    print("  k       HS 6-digit product code      850710")
    print("  v       Trade value (thousands USD)   1234.567")
    print("  q       Quantity (metric tons)        890.123")
    print()
    print("=" * 76)
    print()

    # Check current status
    if BACI_DIR.is_dir():
        csv_files = list(BACI_DIR.glob("BACI_HS*_Y*_V*.csv"))
        filtered = list(BACI_DIR.glob("BACI_*_filtered.csv"))
        sqlite_files = list(BACI_DIR.glob("*.db"))
        if csv_files:
            print(f"  Status: {len(csv_files)} raw BACI CSV file(s) found.")
            for f in csv_files:
                size_mb = f.stat().st_size / (1024 * 1024)
                print(f"    - {f.name}  ({size_mb:.1f} MB)")
        if filtered:
            print(f"  Processed: {len(filtered)} filtered CSV file(s) found.")
        if sqlite_files:
            print(f"  SQLite: {len(sqlite_files)} database file(s) found.")
        if not csv_files:
            print("  Status: data/baci/ directory exists but no BACI CSV files found.")
    else:
        print(f"  Status: data/baci/ directory does not exist yet.")
        print(f"  It will be created at: {BACI_DIR}")
    print()


def verify_baci_data():
    """Verify that BACI data files are present and well-formed."""
    print("Verifying BACI data...")
    print()

    if not BACI_DIR.is_dir():
        print(f"  ERROR: Directory not found: {BACI_DIR}")
        print("  Run this script without flags for download instructions.")
        return False

    csv_files = sorted(BACI_DIR.glob("BACI_HS*_Y*_V*.csv"))
    if not csv_files:
        print(f"  ERROR: No BACI CSV files found in {BACI_DIR}")
        return False

    all_ok = True
    for csv_path in csv_files:
        size_mb = csv_path.stat().st_size / (1024 * 1024)
        print(f"  File: {csv_path.name}  ({size_mb:.1f} MB)")

        # Read first few lines to verify format
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                expected = {"t", "i", "j", "k", "v", "q"}
                if not expected.issubset(set(headers)):
                    print(f"    WARNING: Missing columns. Expected {expected}, got {set(headers)}")
                    all_ok = False
                else:
                    print(f"    Columns: {headers}")

                # Count a few rows
                count = 0
                for _ in reader:
                    count += 1
                    if count >= 5:
                        break
                print(f"    Sample rows readable: {count}")
                if count == 0:
                    print("    WARNING: File appears empty.")
                    all_ok = False
                else:
                    print("    OK")
        except Exception as e:
            print(f"    ERROR reading file: {e}")
            all_ok = False
        print()

    if all_ok:
        print("  All checks passed.")
    else:
        print("  Some checks failed. See warnings above.")
    return all_ok


def process_baci_data(build_sqlite: bool = False):
    """Filter raw BACI CSV to only relevant HS codes and optionally build SQLite.

    This dramatically reduces file size and query time for the SCRI platform.
    """
    print("Processing BACI data...")
    print()

    if not BACI_DIR.is_dir():
        print(f"  ERROR: Directory not found: {BACI_DIR}")
        print("  Download BACI data first. Run this script without flags for instructions.")
        sys.exit(1)

    csv_files = sorted(BACI_DIR.glob("BACI_HS*_Y*_V*.csv"))
    # Exclude already-filtered files
    csv_files = [f for f in csv_files if "_filtered" not in f.name]

    if not csv_files:
        print(f"  ERROR: No raw BACI CSV files found in {BACI_DIR}")
        sys.exit(1)

    print(f"  Relevant HS4 codes ({len(RELEVANT_HS4_CODES)}):")
    for code in sorted(RELEVANT_HS4_CODES):
        print(f"    {code}")
    print()

    # --- Filter each CSV ---
    filtered_paths = []
    for csv_path in csv_files:
        size_mb = csv_path.stat().st_size / (1024 * 1024)
        print(f"  Processing: {csv_path.name} ({size_mb:.1f} MB)")

        # Output file: BACI_HS17_Y2022_V202401_filtered.csv
        out_name = csv_path.stem + "_filtered.csv"
        out_path = BACI_DIR / out_name

        total_rows = 0
        kept_rows = 0

        try:
            with open(csv_path, "r", encoding="utf-8") as fin, \
                 open(out_path, "w", encoding="utf-8", newline="") as fout:
                reader = csv.DictReader(fin)
                writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
                writer.writeheader()

                for row in reader:
                    total_rows += 1
                    hs6 = str(row.get("k", "")).strip()
                    hs4 = hs6[:4]
                    if hs4 in RELEVANT_HS4_CODES:
                        writer.writerow(row)
                        kept_rows += 1

                    if total_rows % 5_000_000 == 0:
                        print(f"    ... {total_rows:,} rows scanned, {kept_rows:,} kept")

            out_size_mb = out_path.stat().st_size / (1024 * 1024)
            reduction_pct = (1 - kept_rows / total_rows) * 100 if total_rows > 0 else 0
            print(f"    Done: {total_rows:,} total -> {kept_rows:,} kept ({reduction_pct:.1f}% reduction)")
            print(f"    Output: {out_path.name} ({out_size_mb:.1f} MB)")
            filtered_paths.append(out_path)
        except Exception as e:
            print(f"    ERROR: {e}")
        print()

    # --- Optionally build SQLite ---
    if build_sqlite and filtered_paths:
        db_path = BACI_DIR / "baci_scri.db"
        print(f"  Building SQLite database: {db_path.name}")

        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS trade_flows (
                    year     INTEGER NOT NULL,
                    exporter INTEGER NOT NULL,
                    importer INTEGER NOT NULL,
                    hs6      TEXT    NOT NULL,
                    value_k  REAL    NOT NULL,
                    quantity REAL,
                    PRIMARY KEY (year, exporter, importer, hs6)
                )
            """)
            cur.execute("DELETE FROM trade_flows")  # Clear existing data

            total_inserted = 0
            for fp in filtered_paths:
                with open(fp, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    batch = []
                    for row in reader:
                        try:
                            q_val = row.get("q", "")
                            quantity = float(q_val) if q_val not in ("", "NA") else None
                            batch.append((
                                int(row["t"]),
                                int(row["i"]),
                                int(row["j"]),
                                str(row["k"]).strip(),
                                float(row["v"]),
                                quantity,
                            ))
                        except (ValueError, TypeError):
                            continue

                        if len(batch) >= 10_000:
                            cur.executemany(
                                "INSERT OR REPLACE INTO trade_flows VALUES (?,?,?,?,?,?)",
                                batch,
                            )
                            total_inserted += len(batch)
                            batch = []

                    if batch:
                        cur.executemany(
                            "INSERT OR REPLACE INTO trade_flows VALUES (?,?,?,?,?,?)",
                            batch,
                        )
                        total_inserted += len(batch)

            # Create indexes for common query patterns
            print("    Creating indexes...")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_year_hs6 ON trade_flows(year, hs6)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_year_exporter ON trade_flows(year, exporter)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_year_importer ON trade_flows(year, importer)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_hs6_prefix ON trade_flows(year, substr(hs6, 1, 4))")

            conn.commit()
            conn.close()

            db_size_mb = db_path.stat().st_size / (1024 * 1024)
            print(f"    Done: {total_inserted:,} rows inserted")
            print(f"    Database: {db_path.name} ({db_size_mb:.1f} MB)")
        except Exception as e:
            print(f"    ERROR building SQLite: {e}")
        print()

    print("Processing complete.")


def main():
    parser = argparse.ArgumentParser(
        description="BACI Trade Data - Download & Processing Script for SCRI Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/download_baci.py                    Show download instructions
  python scripts/download_baci.py --verify           Verify existing BACI files
  python scripts/download_baci.py --process          Filter CSVs to relevant HS codes
  python scripts/download_baci.py --process --sqlite Also build SQLite database
        """,
    )
    parser.add_argument(
        "--process", action="store_true",
        help="Process raw BACI CSV files into filtered/optimized format",
    )
    parser.add_argument(
        "--sqlite", action="store_true",
        help="Build SQLite database from filtered data (requires --process)",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Verify existing BACI data files",
    )

    args = parser.parse_args()

    if args.verify:
        verify_baci_data()
    elif args.process:
        # Ensure baci directory exists
        BACI_DIR.mkdir(parents=True, exist_ok=True)
        process_baci_data(build_sqlite=args.sqlite)
    else:
        print_download_instructions()


if __name__ == "__main__":
    main()
