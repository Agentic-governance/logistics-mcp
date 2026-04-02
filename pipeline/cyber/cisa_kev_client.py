"""CISA KEV (Known Exploited Vulnerabilities) カタログ クライアント
https://www.cisa.gov/known-exploited-vulnerabilities-catalog
APIキー不要、JSONフィード
"""
import requests
from datetime import datetime, timedelta
from typing import Optional

# CISA KEV JSON feed
CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}

# Cached KEV data
_kev_cache: Optional[dict] = None
_kev_cache_time: Optional[datetime] = None
KEV_CACHE_TTL_HOURS = 6


def _fetch_kev_catalog() -> Optional[dict]:
    """CISA KEVカタログJSONをダウンロード"""
    global _kev_cache, _kev_cache_time

    # Return cached data if fresh
    if (_kev_cache is not None
            and _kev_cache_time is not None
            and (datetime.utcnow() - _kev_cache_time).total_seconds() < KEV_CACHE_TTL_HOURS * 3600):
        return _kev_cache

    try:
        resp = requests.get(CISA_KEV_URL, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

        _kev_cache = data
        _kev_cache_time = datetime.utcnow()
        return data
    except Exception:
        return _kev_cache  # Return stale cache if available


def get_kev_stats(days_back: int = 30) -> dict:
    """CISA KEV統計情報を取得

    Args:
        days_back: 何日前までの新規KEVを集計するか

    Returns:
        {"score": int (0-100), "evidence": list[str],
         "total_kevs": int, "recent_kevs": int,
         "top_vendors": list[dict]}
    """
    catalog = _fetch_kev_catalog()
    evidence: list[str] = []

    if catalog is None:
        return {
            "score": 20,
            "evidence": ["[CISA KEV] カタログ取得失敗。デフォルトスコア適用"],
            "total_kevs": 0,
            "recent_kevs": 0,
            "top_vendors": [],
        }

    vulnerabilities = catalog.get("vulnerabilities", [])
    total_kevs = len(vulnerabilities)
    catalog_title = catalog.get("title", "CISA KEV")
    catalog_date = catalog.get("catalogVersion", "unknown")

    # Count recent KEVs (added in last N days)
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    recent: list[dict] = []
    vendor_counts: dict[str, int] = {}

    for vuln in vulnerabilities:
        date_added = vuln.get("dateAdded", "")
        vendor = vuln.get("vendorProject", "Unknown")

        if date_added >= cutoff:
            recent.append(vuln)
            vendor_counts[vendor] = vendor_counts.get(vendor, 0) + 1

    recent_count = len(recent)

    # Sort vendors by count
    top_vendors = sorted(
        [{"vendor": v, "count": c} for v, c in vendor_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    # Score based on recent KEV activity
    # High KEV volume = elevated global cyber threat
    if recent_count >= 30:
        score = 80
    elif recent_count >= 20:
        score = 65
    elif recent_count >= 10:
        score = 50
    elif recent_count >= 5:
        score = 35
    elif recent_count >= 1:
        score = 20
    else:
        score = 10

    evidence.append(
        f"[CISA KEV] カタログ総数: {total_kevs}件, "
        f"直近{days_back}日間の新規: {recent_count}件"
    )

    if top_vendors:
        top3 = ", ".join(
            f"{v['vendor']}({v['count']}件)" for v in top_vendors[:3]
        )
        evidence.append(f"[CISA KEV] 主要ベンダー: {top3}")

    # Highlight critical recent KEVs
    for vuln in recent[:3]:
        cve = vuln.get("cveID", "N/A")
        name = vuln.get("vulnerabilityName", "N/A")
        vendor = vuln.get("vendorProject", "N/A")
        evidence.append(
            f"[CISA KEV] {cve} - {vendor}: {name[:60]}"
        )

    if recent_count >= 20:
        evidence.append(
            f"[CISA KEV] 活発な脆弱性悪用活動。"
            "サプライチェーン全体のパッチ管理を確認"
        )

    return {
        "score": score,
        "evidence": evidence,
        "total_kevs": total_kevs,
        "recent_kevs": recent_count,
        "top_vendors": top_vendors,
    }


def get_vendor_exposure(vendor_name: str) -> dict:
    """特定ベンダーのKEV露出度を取得

    Args:
        vendor_name: ベンダー名（例: "Microsoft", "Apple", "Cisco"）

    Returns:
        {"score": int (0-100), "evidence": list[str], "kev_count": int}
    """
    catalog = _fetch_kev_catalog()

    if catalog is None:
        return {
            "score": 0,
            "evidence": ["[CISA KEV] カタログ取得失敗"],
            "kev_count": 0,
        }

    vulnerabilities = catalog.get("vulnerabilities", [])
    vendor_lower = vendor_name.lower()

    matching = [
        v for v in vulnerabilities
        if vendor_lower in v.get("vendorProject", "").lower()
    ]

    kev_count = len(matching)

    # Recent matches (last 90 days)
    cutoff_90d = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
    recent_matching = [
        v for v in matching
        if v.get("dateAdded", "") >= cutoff_90d
    ]

    # Score based on KEV count for this vendor
    if kev_count >= 50:
        score = 70
    elif kev_count >= 20:
        score = 50
    elif kev_count >= 10:
        score = 35
    elif kev_count >= 5:
        score = 20
    elif kev_count >= 1:
        score = 10
    else:
        score = 0

    # Boost if recent KEVs
    if len(recent_matching) >= 5:
        score = min(100, score + 20)
    elif len(recent_matching) >= 2:
        score = min(100, score + 10)

    evidence = [
        f"[CISA KEV] {vendor_name}: KEV登録数={kev_count}件, "
        f"直近90日={len(recent_matching)}件"
    ]

    for v in recent_matching[:3]:
        cve = v.get("cveID", "N/A")
        name = v.get("vulnerabilityName", "N/A")
        evidence.append(f"[CISA KEV] {cve}: {name[:60]}")

    return {
        "score": score,
        "evidence": evidence,
        "kev_count": kev_count,
    }


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("CISA KEV Catalog Test")
    print("=" * 70)

    # Global stats
    stats = get_kev_stats(days_back=30)
    print(f"\n--- Global KEV Stats (last 30 days) ---")
    print(f"  Score: {stats['score']}/100")
    print(f"  Total KEVs: {stats['total_kevs']}")
    print(f"  Recent KEVs: {stats['recent_kevs']}")
    for e in stats["evidence"]:
        print(f"  {e}")

    # Vendor-specific
    print(f"\n--- Vendor Exposure ---")
    for vendor in ["Microsoft", "Apple", "Cisco", "Google", "Adobe"]:
        result = get_vendor_exposure(vendor)
        print(f"\n  {vendor}:")
        print(f"    Score: {result['score']}/100, KEVs: {result['kev_count']}")
        for e in result["evidence"][:2]:
            print(f"    {e}")

    print("\n" + "=" * 70)
