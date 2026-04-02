"""輸送ルートリスク分析エンジン
2地点間の輸送ルートリスクを評価し、チョークポイント通過判定と代替ルート提案を行う。
"""
from dataclasses import dataclass, field
from typing import Optional
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime

# 7大チョークポイント定義
CHOKEPOINTS = {
    "suez": {"lat": 30.42, "lon": 32.35, "name": "Suez Canal",
             "risk_factors": ["Houthi attacks", "canal blockage", "Egypt instability"]},
    "malacca": {"lat": 1.25, "lon": 103.82, "name": "Strait of Malacca",
                "risk_factors": ["piracy", "congestion", "territorial disputes"]},
    "hormuz": {"lat": 26.57, "lon": 56.25, "name": "Strait of Hormuz",
               "risk_factors": ["Iran tensions", "oil transit", "military activity"]},
    "bab_el_mandeb": {"lat": 12.58, "lon": 43.47, "name": "Bab-el-Mandeb",
                      "risk_factors": ["Houthi attacks", "Yemen conflict", "piracy"]},
    "panama": {"lat": 9.08, "lon": -79.68, "name": "Panama Canal",
               "risk_factors": ["drought restrictions", "capacity limits", "wait times"]},
    "turkish_straits": {"lat": 41.12, "lon": 29.07, "name": "Turkish Straits",
                        "risk_factors": ["congestion", "Ukraine conflict", "Black Sea mines"]},
    "taiwan_strait": {"lat": 24.5, "lon": 119.5, "name": "Taiwan Strait",
                      "risk_factors": ["China-Taiwan tensions", "military exercises", "trade disruption"]},
}

# 主要港湾の座標
PORT_COORDS = {
    "tokyo": (35.65, 139.77), "yokohama": (35.44, 139.64), "kobe": (34.68, 135.18),
    "nagoya": (35.08, 136.88), "osaka": (34.65, 135.43),
    "shanghai": (31.35, 121.50), "shenzhen": (22.48, 114.25), "ningbo": (29.87, 121.56),
    "busan": (35.10, 129.04), "kaohsiung": (22.61, 120.29),
    "singapore": (1.26, 103.84), "ho_chi_minh": (10.77, 106.71),
    "bangkok": (13.69, 100.58), "jakarta": (-6.10, 106.87),
    "mumbai": (18.95, 72.84), "dubai": (25.27, 55.29),
    "rotterdam": (51.90, 4.48), "hamburg": (53.53, 9.97),
    "los_angeles": (33.74, -118.26), "long_beach": (33.76, -118.19),
    "new_york": (40.68, -74.04), "suez_port": (29.97, 32.55),
}

# 主要航路定義 (origin -> destination -> list of chokepoints passed)
SEA_ROUTES = {
    ("east_asia", "europe"): {
        "primary": ["malacca", "bab_el_mandeb", "suez"],
        "alt_cape": [],  # Cape of Good Hope - no chokepoints
        "alt_arctic": [],  # Northern Sea Route - seasonal
    },
    ("east_asia", "middle_east"): {
        "primary": ["malacca"],
        "alt_lombok": [],  # Lombok Strait bypass
    },
    ("east_asia", "us_west"): {
        "primary": [],  # Pacific direct
    },
    ("east_asia", "us_east"): {
        "primary": ["panama"],
        "alt_suez": ["malacca", "bab_el_mandeb", "suez"],
    },
    ("europe", "middle_east"): {
        "primary": ["suez"],
        "alt_cape": [],
    },
}

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の距離(km)"""
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def _resolve_port(location: str) -> tuple:
    """ロケーション名を座標に解決"""
    loc = location.lower().strip().replace(" ", "_")
    if loc in PORT_COORDS:
        return PORT_COORDS[loc]
    for name, coords in PORT_COORDS.items():
        if loc in name or name in loc:
            return coords
    return None

def _get_region(lat: float, lon: float) -> str:
    """座標から地域を判定"""
    if 100 < lon < 150 and -10 < lat < 50: return "east_asia"
    if -10 < lon < 45 and 30 < lat < 70: return "europe"
    if 40 < lon < 65 and 10 < lat < 40: return "middle_east"
    if -130 < lon < -60 and 25 < lat < 50: return "us_east" if lon > -90 else "us_west"
    return "other"

class RouteRiskAnalyzer:
    """輸送ルートリスク分析"""

    def analyze_route(self, origin: str, destination: str, mode: str = "sea") -> dict:
        """2地点間のルートリスクを分析"""
        # 1. Resolve coordinates
        origin_coords = _resolve_port(origin)
        dest_coords = _resolve_port(destination)
        if not origin_coords or not dest_coords:
            return {"error": f"Cannot resolve: {origin if not origin_coords else destination}",
                    "source": "RouteRisk", "timestamp": datetime.utcnow().isoformat()}

        # 2. Determine regions and find route
        origin_region = _get_region(*origin_coords)
        dest_region = _get_region(*dest_coords)

        # 3. Find chokepoints on route
        route_key = (origin_region, dest_region)
        reverse_key = (dest_region, origin_region)
        routes = SEA_ROUTES.get(route_key) or SEA_ROUTES.get(reverse_key) or {"primary": []}

        primary_chokepoints = routes.get("primary", [])

        # 4. Calculate risk for each chokepoint
        chokepoint_risks = []
        total_risk = 0
        for cp_id in primary_chokepoints:
            cp_risk = self.get_chokepoint_risk(cp_id)
            chokepoint_risks.append(cp_risk)
            total_risk = max(total_risk, cp_risk.get("risk_score", 0))

        # 5. Calculate distance
        distance = _haversine(*origin_coords, *dest_coords)

        # 6. Find alternative routes
        alternatives = []
        for route_name, cp_list in routes.items():
            if route_name == "primary":
                continue
            alt_risk = 0
            for cp_id in cp_list:
                r = self.get_chokepoint_risk(cp_id)
                alt_risk = max(alt_risk, r.get("risk_score", 0))
            alternatives.append({
                "route_name": route_name,
                "chokepoints": cp_list,
                "risk_score": alt_risk,
            })
        alternatives.sort(key=lambda x: x["risk_score"])

        return {
            "origin": origin, "destination": destination,
            "distance_km": round(distance),
            "route_risk": total_risk,
            "risk_level": "CRITICAL" if total_risk >= 80 else "HIGH" if total_risk >= 60 else "MEDIUM" if total_risk >= 40 else "LOW",
            "chokepoints_passed": [{
                "id": cp_id,
                "name": CHOKEPOINTS[cp_id]["name"],
                "risk": chokepoint_risks[i] if i < len(chokepoint_risks) else {}
            } for i, cp_id in enumerate(primary_chokepoints)],
            "alternative_routes": alternatives[:3],
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_chokepoint_risk(self, chokepoint_id: str) -> dict:
        """チョークポイントのリアルタイムリスク"""
        cp = CHOKEPOINTS.get(chokepoint_id)
        if not cp:
            return {"error": f"Unknown chokepoint: {chokepoint_id}"}

        risk_score = 0
        evidence = []

        # Use existing pipeline clients to assess
        try:
            from pipeline.conflict.acled_client import get_conflict_risk_for_location
            conflict = get_conflict_risk_for_location(cp["name"])
            if conflict.get("score", 0) > 0:
                risk_score = max(risk_score, conflict["score"])
                evidence.extend(conflict.get("evidence", []))
        except Exception:
            pass

        # Check port congestion
        try:
            from pipeline.infrastructure.port_congestion_client import get_port_congestion_risk
            port = get_port_congestion_risk(cp["name"])
            if port.get("score", 0) > 0:
                risk_score = max(risk_score, port["score"])
                evidence.extend(port.get("evidence", []))
        except Exception:
            pass

        # Static risk factors
        if not evidence:
            evidence = [f"[ルートリスク] {cp['name']}: {', '.join(cp['risk_factors'])}"]
            # Assign baseline scores
            baseline_scores = {
                "bab_el_mandeb": 75, "suez": 50, "hormuz": 65,
                "taiwan_strait": 55, "malacca": 30, "panama": 25,
                "turkish_straits": 40,
            }
            risk_score = max(risk_score, baseline_scores.get(chokepoint_id, 20))

        return {
            "chokepoint_id": chokepoint_id,
            "name": cp["name"],
            "risk_score": risk_score,
            "risk_factors": cp["risk_factors"],
            "evidence": evidence,
            "timestamp": datetime.utcnow().isoformat(),
        }
