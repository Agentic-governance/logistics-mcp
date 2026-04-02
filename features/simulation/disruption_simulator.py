"""混乱シナリオシミュレーター
サプライチェーンのノード障害カスケード影響をシミュレート
"""
from datetime import datetime
from typing import Optional
import networkx as nx

# シナリオテンプレート
SCENARIO_TEMPLATES = {
    "taiwan_blockade": {
        "name": "台湾海峡封鎖シナリオ",
        "affected_locations": ["Taiwan"],
        "affected_chokepoints": ["taiwan_strait"],
        "duration_estimate_days": 180,
        "impact_sectors": ["semiconductor", "electronics"],
        "description": "中国による台湾海峡封鎖。半導体サプライチェーンに壊滅的影響。",
    },
    "suez_closure": {
        "name": "スエズ運河封鎖シナリオ",
        "affected_locations": ["Egypt"],
        "affected_chokepoints": ["suez", "bab_el_mandeb"],
        "duration_estimate_days": 30,
        "impact_sectors": ["energy_lng", "automotive_parts", "electronics"],
        "description": "スエズ運河の物理的封鎖。欧亜間貿易に甚大な影響。",
    },
    "hormuz_crisis": {
        "name": "ホルムズ海峡危機シナリオ",
        "affected_locations": ["Iran"],
        "affected_chokepoints": ["hormuz"],
        "duration_estimate_days": 90,
        "impact_sectors": ["energy_lng"],
        "description": "イラン紛争によるホルムズ海峡封鎖。世界の石油供給の20%に影響。",
    },
    "pandemic": {
        "name": "パンデミックシナリオ",
        "affected_locations": ["China", "Vietnam", "India", "Bangladesh"],
        "affected_chokepoints": [],
        "duration_estimate_days": 120,
        "impact_sectors": ["textiles", "electronics", "automotive_parts"],
        "description": "新型感染症による複数国同時封鎖。製造業サプライチェーンが広範に停止。",
    },
    "china_rare_earth_ban": {
        "name": "中国レアアース輸出規制シナリオ",
        "affected_locations": ["China"],
        "affected_chokepoints": [],
        "duration_estimate_days": 365,
        "impact_sectors": ["rare_earth", "battery_materials", "electronics"],
        "description": "中国がレアアース輸出を制限。EV・ハイテク産業に長期的影響。",
    },
}

# 回復日数の過去事例ベース推定
RECOVERY_BENCHMARKS = {
    "sanctions": {"min": 180, "max": 730, "typical": 365},
    "natural_disaster": {"min": 30, "max": 180, "typical": 90},
    "port_closure": {"min": 7, "max": 90, "typical": 30},
    "pandemic": {"min": 60, "max": 365, "typical": 120},
    "trade_war": {"min": 90, "max": 730, "typical": 365},
    "canal_blockage": {"min": 7, "max": 60, "typical": 14},
    "military_conflict": {"min": 90, "max": 1095, "typical": 365},
}

class DisruptionSimulator:
    """サプライチェーン混乱シミュレータ"""

    def simulate_node_failure(self, location: str, cascade_depth: int = 3) -> dict:
        """指定ロケーションのノード障害シミュレーション"""
        timestamp = datetime.utcnow().isoformat()

        # Get location risk score
        try:
            from scoring.engine import calculate_risk_score
            base_score = calculate_risk_score(f"sim_{location}", f"Simulation: {location}",
                                             country=location, location=location)
            base_risk = base_score.overall_score
        except Exception:
            base_risk = 50  # default

        # Simulate cascade effects
        affected_nodes = []
        impact_score = base_risk

        # Use concentration templates to find dependent sectors
        from features.concentration.analyzer import SECTOR_TEMPLATES, COUNTRY_NAMES

        # Find which sectors depend on this location
        loc_upper = location.upper()[:2]
        affected_sectors = []
        for sector, shares in SECTOR_TEMPLATES.items():
            for country_code, share in shares.items():
                if country_code == loc_upper or COUNTRY_NAMES.get(country_code, "").lower() == location.lower():
                    if share >= 0.05:  # 5% threshold
                        affected_sectors.append({
                            "sector": sector,
                            "share": share,
                            "impact": "CRITICAL" if share > 0.3 else "HIGH" if share > 0.15 else "MEDIUM",
                        })

        # Cascade effect: each depth level reduces impact by 40%
        cascade_impacts = []
        for depth in range(1, cascade_depth + 1):
            depth_impact = int(impact_score * (0.6 ** depth))
            if depth_impact < 5:
                break
            cascade_impacts.append({
                "tier": depth,
                "impact_score": depth_impact,
                "description": f"Tier-{depth} suppliers affected ({depth_impact}% indirect impact)",
            })

        total_impact = base_risk + sum(c["impact_score"] for c in cascade_impacts) // 3
        total_impact = min(100, total_impact)

        return {
            "scenario": "node_failure",
            "location": location,
            "base_risk_score": base_risk,
            "affected_sectors": affected_sectors,
            "cascade_impacts": cascade_impacts,
            "cascade_depth_reached": len(cascade_impacts),
            "total_impact_score": total_impact,
            "recovery_days_estimate": self.estimate_recovery_time("natural_disaster"),
            "evidence": [
                f"[シミュレーション] {location}ノード障害",
                f"[影響] 影響セクター: {len(affected_sectors)}件",
                f"[カスケード] Tier-{len(cascade_impacts)}まで影響波及",
            ],
            "timestamp": timestamp,
        }

    def simulate_scenario(self, scenario_type: str) -> dict:
        """定義済みシナリオのシミュレーション"""
        template = SCENARIO_TEMPLATES.get(scenario_type)
        if not template:
            return {"error": f"Unknown scenario: {scenario_type}",
                    "available": list(SCENARIO_TEMPLATES.keys()),
                    "timestamp": datetime.utcnow().isoformat()}

        results = []
        for loc in template["affected_locations"]:
            result = self.simulate_node_failure(loc, cascade_depth=3)
            results.append(result)

        max_impact = max(r["total_impact_score"] for r in results) if results else 0
        total_sectors = set()
        for r in results:
            for s in r.get("affected_sectors", []):
                total_sectors.add(s["sector"])

        return {
            "scenario": scenario_type,
            "scenario_name": template["name"],
            "description": template["description"],
            "affected_locations": template["affected_locations"],
            "affected_chokepoints": template["affected_chokepoints"],
            "impact_score": max_impact,
            "risk_level": "CRITICAL" if max_impact >= 80 else "HIGH" if max_impact >= 60 else "MEDIUM",
            "affected_sectors": list(total_sectors),
            "location_results": results,
            "duration_estimate_days": template["duration_estimate_days"],
            "recovery_estimate": self.estimate_recovery_time(
                "military_conflict" if "blockade" in scenario_type else
                "canal_blockage" if "closure" in scenario_type else
                "pandemic" if "pandemic" in scenario_type else
                "trade_war"
            ),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def estimate_recovery_time(self, disruption_type: str) -> dict:
        """回復日数の推定"""
        benchmark = RECOVERY_BENCHMARKS.get(disruption_type, RECOVERY_BENCHMARKS["natural_disaster"])
        return {
            "disruption_type": disruption_type,
            "min_days": benchmark["min"],
            "max_days": benchmark["max"],
            "typical_days": benchmark["typical"],
        }
