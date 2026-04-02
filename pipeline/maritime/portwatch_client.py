"""IMF PortWatch - 港湾活動・貿易途絶モニタリング
衛星データで2,033港の日次活動を追跡。完全無料。
https://portwatch.imf.org/
"""
import requests
from datetime import datetime, timedelta

# IMF PortWatch ArcGIS Feature Service
PORTWATCH_BASE = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
DISRUPTIONS_URL = f"{PORTWATCH_BASE}/Disruptions/FeatureServer/0/query"
PORT_ACTIVITY_URL = f"{PORTWATCH_BASE}/PortWatch_Portal_Daily_Port_Data/FeatureServer/0/query"

HEADERS = {"User-Agent": "SupplyChainRiskIntelligence/1.0"}


def fetch_active_disruptions() -> list[dict]:
    """現在アクティブな貿易途絶イベントを取得"""
    params = {
        "where": "1=1",
        "outFields": "*",
        "f": "json",
        "resultRecordCount": 100,
        "orderByFields": "start_date DESC",
    }

    try:
        resp = requests.get(DISRUPTIONS_URL, params=params, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for feature in data.get("features", []):
            attrs = feature.get("attributes", {})
            results.append({
                "id": attrs.get("OBJECTID"),
                "name": attrs.get("disruption_name", ""),
                "type": attrs.get("disruption_type", ""),
                "status": attrs.get("status", ""),
                "affected_ports": attrs.get("affected_ports", ""),
                "affected_countries": attrs.get("affected_countries", ""),
                "trade_impact_pct": attrs.get("trade_impact_percent"),
                "start_date": _epoch_to_iso(attrs.get("start_date")),
                "description": attrs.get("description", ""),
            })

        return results
    except Exception as e:
        print(f"PortWatch disruptions error: {e}")
        return []


def fetch_port_activity(port_name: str = None, country: str = None, days_back: int = 30) -> list[dict]:
    """港湾活動データを取得"""
    since = datetime.utcnow() - timedelta(days=days_back)
    since_epoch = int(since.timestamp() * 1000)

    where_clauses = [f"date >= {since_epoch}"]
    if port_name:
        where_clauses.append(f"port_name LIKE '%{port_name}%'")
    if country:
        where_clauses.append(f"country LIKE '%{country}%'")

    params = {
        "where": " AND ".join(where_clauses),
        "outFields": "port_name,country,date,import_volume,export_volume,vessel_count",
        "f": "json",
        "resultRecordCount": 500,
        "orderByFields": "date DESC",
    }

    try:
        resp = requests.get(PORT_ACTIVITY_URL, params=params, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for feature in data.get("features", []):
            attrs = feature.get("attributes", {})
            results.append({
                "port_name": attrs.get("port_name", ""),
                "country": attrs.get("country", ""),
                "date": _epoch_to_iso(attrs.get("date")),
                "import_volume": attrs.get("import_volume"),
                "export_volume": attrs.get("export_volume"),
                "vessel_count": attrs.get("vessel_count"),
            })

        return results
    except Exception as e:
        print(f"PortWatch activity error: {e}")
        return []


# Maritime trade dependency scores (UNCTAD RMT 2024 + port infrastructure)
# Measures: share of trade by sea, port efficiency, chokepoint exposure
# NOT correlated with political freedom — Singapore is most democratic but highest maritime dependency
MARITIME_DEPENDENCY = {
    "Japan": 48, "United States": 20, "Germany": 25, "United Kingdom": 30, "France": 25,
    "Italy": 35, "Canada": 18, "China": 38, "India": 32, "Russia": 15,
    "Brazil": 28, "South Africa": 30, "Indonesia": 45, "Vietnam": 38, "Thailand": 32,
    "Malaysia": 42, "Singapore": 48, "Philippines": 42, "Myanmar": 22, "Cambodia": 15,
    "Saudi Arabia": 40, "UAE": 45, "Iran": 28, "Iraq": 25, "Turkey": 30,
    "Israel": 35, "Qatar": 42, "Yemen": 28, "South Korea": 45, "Taiwan": 48,
    "North Korea": 12, "Bangladesh": 30, "Pakistan": 28, "Sri Lanka": 35,
    "Nigeria": 25, "Ethiopia": 5, "Kenya": 22, "Egypt": 35, "South Sudan": 2,
    "Somalia": 15, "Ukraine": 20, "Poland": 15, "Netherlands": 45, "Switzerland": 2,
    "Mexico": 22, "Colombia": 20, "Venezuela": 22, "Argentina": 20, "Chile": 28,
    "Australia": 28,
}


def get_maritime_risk_for_location(location: str) -> dict:
    """海上輸送リスク評価"""
    # Static baseline
    baseline = 0
    for country, dep_score in MARITIME_DEPENDENCY.items():
        if country.lower() == location.lower() or location.lower() in country.lower() or country.lower() in location.lower():
            baseline = dep_score // 3  # Convert dependency to risk baseline (0-16)
            break

    disruptions = fetch_active_disruptions()

    # Improved country matching
    loc_lower = location.lower()
    relevant = [d for d in disruptions if
                loc_lower in (d.get("affected_countries", "") or "").lower() or
                loc_lower in (d.get("affected_ports", "") or "").lower() or
                loc_lower in (d.get("name", "") or "").lower() or
                any(loc_lower in (p or "").lower() for p in [d.get("description", "")])]

    if not relevant:
        if baseline > 0:
            return {
                "score": baseline,
                "disruptions": [],
                "evidence": [f"[海運] {location}: 海上貿易依存度スコア（ベースライン）"],
            }
        return {"score": 0, "disruptions": [], "evidence": []}

    max_impact = max((d.get("trade_impact_pct") or 0) for d in relevant)
    score = min(100, max(baseline, int(max_impact) + len(relevant) * 15))

    evidence = []
    for d in relevant[:5]:
        impact = d.get("trade_impact_pct", "N/A")
        name = d["name"]
        status = d.get("status", "")
        evidence.append(f"[PortWatch] {name} - 貿易影響: {impact}% ({status})")

    return {
        "score": score,
        "disruption_count": len(relevant),
        "disruptions": relevant[:10],
        "evidence": evidence,
    }


def _epoch_to_iso(epoch_ms) -> str:
    if not epoch_ms:
        return ""
    try:
        return datetime.utcfromtimestamp(epoch_ms / 1000).isoformat()
    except (ValueError, TypeError, OSError):
        return ""
