#!/usr/bin/env python3
"""Comtrade Tier-2/3 推定キャッシュ構築スクリプト

主要 13 カ国 × 10 HS コードの輸入ソースデータを取得し、
data/comtrade_cache/ に JSON ファイルとして保存する。

Comtrade API キーがない場合は HS_PROXY_DATA フォールバックを使用。

Usage:
    python scripts/build_tier_inference_cache.py
    python scripts/build_tier_inference_cache.py --live  # API使用を強制
"""
import sys
import os
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


TARGET_COUNTRIES = [
    "South Korea", "Japan", "China", "United States", "Germany",
    "Taiwan", "Vietnam", "Thailand", "India", "Malaysia",
    "Indonesia", "United Kingdom", "Mexico",
]

TARGET_HS_CODES = [
    ("8507", "battery"),
    ("8542", "semiconductor"),
    ("8501", "motor"),
    ("2604", "nickel"),
    ("2836", "lithium"),
    ("2846", "rare_earth"),
    ("2603", "copper"),
    ("7601", "aluminum"),
    ("8534", "pcb"),
    ("7207", "steel"),
]


def build_cache(use_live: bool = False):
    from features.analytics.tier_inference import TierInferenceEngine, HS_PROXY_DATA

    cache_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "comtrade_cache",
    )
    os.makedirs(cache_dir, exist_ok=True)

    engine = TierInferenceEngine(cache_dir=cache_dir)

    total = len(TARGET_COUNTRIES) * len(TARGET_HS_CODES)
    cached = 0
    skipped = 0

    print(f"Building Tier inference cache: {len(TARGET_COUNTRIES)} countries x {len(TARGET_HS_CODES)} HS codes = {total} combinations")
    print(f"Cache directory: {cache_dir}")
    print(f"Mode: {'Live API' if use_live else 'Proxy data + API fallback'}")
    print()

    for country in TARGET_COUNTRIES:
        for hs_code, material in TARGET_HS_CODES:
            key = engine._cache_key(country, hs_code)
            cache_file = os.path.join(cache_dir, f"{key}.json")

            # Skip if already cached
            if os.path.exists(cache_file) and not use_live:
                skipped += 1
                continue

            sources = []

            if use_live:
                sources = engine._fetch_comtrade_live(country, hs_code)

            if not sources:
                # Use proxy data
                proxy = HS_PROXY_DATA.get(hs_code, {})
                for name in [country, country.title()]:
                    if name in proxy:
                        sources = proxy[name]
                        break
                if not sources:
                    for cname, cdata in proxy.items():
                        if country.lower() in cname.lower() or cname.lower() in country.lower():
                            sources = cdata
                            break

            if sources:
                data = {
                    "importer": country,
                    "hs_code": hs_code,
                    "material": material,
                    "sources": sources,
                    "fetched_at": datetime.utcnow().isoformat(),
                    "source_type": "live" if use_live else "proxy",
                }
                with open(cache_file, "w") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                cached += 1
                print(f"  [+] {country} / HS {hs_code} ({material}): {len(sources)} sources")
            else:
                print(f"  [-] {country} / HS {hs_code} ({material}): no data")

    print()
    print(f"Done: {cached} cached, {skipped} already existed, {total - cached - skipped} no data")

    # Summary statistics
    cache_files = [f for f in os.listdir(cache_dir) if f.endswith(".json")]
    print(f"Total cache files: {len(cache_files)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Comtrade inference cache")
    parser.add_argument("--live", action="store_true", help="Force live API calls")
    args = parser.parse_args()
    build_cache(use_live=args.live)
