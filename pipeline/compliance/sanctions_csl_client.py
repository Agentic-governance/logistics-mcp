"""US Consolidated Screening List (CSL) API
米国統合制裁スクリーニングリスト
https://www.trade.gov/consolidated-screening-list

The old gateway API at api.trade.gov/gateway/v1/... now returns 401.
We try the following in order:
  1. trade.gov CSL search API (if restored)
  2. Static CSV from data.trade.gov (always available, full dump)
  3. Stub response when nothing is reachable
"""
import csv
import io
import requests
from datetime import datetime, timezone
from typing import Optional

# ---- Endpoint candidates (tried in order) ----
CSL_API_SEARCH = (
    "https://api.trade.gov/gateway/v1/consolidated_screening_list/search"
)
CSL_API_V1 = (
    "https://data.trade.gov/consolidated_screening_list/v1/search"
)
CSL_STATIC_CSV = (
    "https://data.trade.gov/downloadable_consolidated_screening_list/"
    "v1/consolidated.csv"
)

_HEADERS = {"User-Agent": "SCRI-Platform/0.4"}

# In-memory cache for the static CSV (avoid re-downloading per query)
_csv_cache: Optional[list] = None
_csv_cache_ts: Optional[float] = None
_CSV_CACHE_TTL = 3600  # seconds


def _try_api_search(query: str, fuzzy: bool) -> Optional[dict]:
    """Attempt the live CSL search API endpoints."""
    params = {
        "q": query,
        "fuzzy_name": "true" if fuzzy else "false",
        "size": 20,
    }
    for url in [CSL_API_SEARCH, CSL_API_V1]:
        try:
            resp = requests.get(
                url, params=params, timeout=15, headers=_HEADERS
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", []):
                results.append({
                    "name": item.get("name", ""),
                    "source": item.get("source", ""),
                    "type": item.get("type", ""),
                    "country": item.get("country", ""),
                    "programs": item.get("programs", []),
                    "score": item.get("score"),
                    "addresses": [
                        {"country": a.get("country", ""), "city": a.get("city", "")}
                        for a in item.get("addresses", [])[:3]
                    ],
                })
            return {
                "total": data.get("total", 0),
                "results": results,
            }
        except Exception:
            continue
    return None


def _load_csv_cache() -> list:
    """Download and cache the static CSL CSV."""
    import time

    global _csv_cache, _csv_cache_ts

    now = time.time()
    if _csv_cache is not None and _csv_cache_ts is not None:
        if now - _csv_cache_ts < _CSV_CACHE_TTL:
            return _csv_cache

    resp = requests.get(CSL_STATIC_CSV, timeout=120, headers=_HEADERS)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    _csv_cache = list(reader)
    _csv_cache_ts = now
    return _csv_cache


def _search_csv(query: str, fuzzy: bool = True, limit: int = 20) -> dict:
    """Search the static CSV dump locally."""
    rows = _load_csv_cache()
    query_lower = query.lower()
    matches = []

    for row in rows:
        name = (row.get("name") or "").strip()
        alt_names = (row.get("alt_names") or "").strip()
        searchable = f"{name} {alt_names}".lower()

        if fuzzy:
            # Token-based fuzzy: all query tokens must appear
            tokens = query_lower.split()
            if all(tok in searchable for tok in tokens):
                matches.append(row)
        else:
            if query_lower in searchable:
                matches.append(row)

        if len(matches) >= limit:
            break

    results = []
    for item in matches:
        programs_raw = item.get("programs", "")
        programs = [p.strip() for p in programs_raw.split(";") if p.strip()]

        addresses_raw = item.get("addresses", "")
        addresses = []
        if addresses_raw:
            for addr in addresses_raw.split(";")[:3]:
                addresses.append({"address": addr.strip()})

        results.append({
            "name": item.get("name", ""),
            "source": item.get("source", ""),
            "type": item.get("type", ""),
            "country": "",
            "programs": programs,
            "score": None,
            "addresses": addresses,
        })

    return {
        "total": len(results),
        "results": results,
    }


def search_csl(query: str, fuzzy: bool = True) -> dict:
    """CSLで企業/個人を検索

    Tries the live API first; falls back to the static CSV;
    returns a stub error dict if everything is unreachable.
    """
    # 1. Live API
    result = _try_api_search(query, fuzzy)
    if result is not None:
        return result

    # 2. Static CSV fallback
    try:
        return _search_csv(query, fuzzy)
    except Exception as exc:
        pass

    # 3. Stub
    return {
        "total": 0,
        "results": [],
        "error": "CSL API unavailable",
        "source": "CSL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_sanctions_risk_for_entity(entity_name: str) -> dict:
    """エンティティの制裁リスク評価"""
    csl = search_csl(entity_name)

    if csl.get("error"):
        return {"score": 0, "evidence": [f"CSL検索不可: {csl['error']}"]}

    score = 0
    evidence: list[str] = []

    total = csl.get("total", 0)
    if total > 0:
        results = csl.get("results", [])
        for r in results[:5]:
            source = r.get("source", "")
            name = r.get("name", "")
            country = r.get("country", "")
            programs = ", ".join(r.get("programs", [])[:3])

            # SDNリスト = 最高リスク
            if "SDN" in source or "Specially Designated" in source:
                score = max(score, 100)
                evidence.append(f"[CSL/SDN] {name} ({country}) - {programs}")
            elif "Entity List" in source or "BIS" in source:
                score = max(score, 90)
                evidence.append(f"[CSL/EL] {name} ({country}) - {source}")
            elif "DPL" in source or "Denied" in source:
                score = max(score, 85)
                evidence.append(f"[CSL/DPL] {name} ({country}) - {source}")
            else:
                score = max(score, 70)
                evidence.append(f"[CSL] {name} ({country}) - {source}")

        evidence.insert(0, f"[CSL] {total}件のマッチ")
    else:
        evidence.append(f"[CSL] '{entity_name}': 制裁リストに該当なし")

    return {"score": min(100, score), "evidence": evidence}
