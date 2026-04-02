"""調達集中リスク分析エンジン
HHI(Herfindahl-Hirschman Index)による集中度分析とフレンドショア代替提案
"""
from datetime import datetime
from typing import Optional

# セクター別調達テンプレート (default global shares)
SECTOR_TEMPLATES = {
    "rare_earth": {"CN": 0.60, "AU": 0.12, "US": 0.08, "MM": 0.05, "IN": 0.04, "BR": 0.03, "VN": 0.02, "Other": 0.06},
    "semiconductor": {"TW": 0.35, "KR": 0.20, "JP": 0.15, "US": 0.10, "CN": 0.10, "EU": 0.05, "Other": 0.05},
    "semiconductor_materials": {"JP": 0.35, "DE": 0.20, "TW": 0.18, "US": 0.12, "KR": 0.08, "Other": 0.07},
    "battery_materials": {"CN": 0.55, "CL": 0.15, "AU": 0.12, "AR": 0.05, "CD": 0.05, "ID": 0.04, "Other": 0.04},
    "automotive_parts": {"JP": 0.25, "CN": 0.20, "DE": 0.15, "US": 0.12, "KR": 0.10, "MX": 0.08, "TH": 0.05, "Other": 0.05},
    "electronics": {"CN": 0.40, "TW": 0.15, "KR": 0.12, "VN": 0.10, "JP": 0.08, "MY": 0.05, "TH": 0.05, "Other": 0.05},
    "textiles": {"CN": 0.35, "BD": 0.15, "VN": 0.12, "IN": 0.10, "TR": 0.08, "ID": 0.06, "KH": 0.05, "Other": 0.09},
    "energy_lng": {"AU": 0.30, "QA": 0.18, "US": 0.15, "MY": 0.10, "RU": 0.08, "ID": 0.05, "Other": 0.14},
    "food_grains": {"US": 0.25, "BR": 0.20, "AU": 0.12, "CA": 0.10, "AR": 0.08, "UA": 0.06, "FR": 0.05, "Other": 0.14},
}

# ISO2→国名マッピング
COUNTRY_NAMES = {
    "JP": "Japan", "CN": "China", "US": "United States", "DE": "Germany",
    "KR": "South Korea", "TW": "Taiwan", "AU": "Australia", "IN": "India",
    "VN": "Vietnam", "TH": "Thailand", "ID": "Indonesia", "MY": "Malaysia",
    "SG": "Singapore", "PH": "Philippines", "BD": "Bangladesh", "MM": "Myanmar",
    "BR": "Brazil", "MX": "Mexico", "TR": "Turkey", "RU": "Russia",
    "SA": "Saudi Arabia", "AE": "UAE", "QA": "Qatar", "CL": "Chile",
    "AR": "Argentina", "UA": "Ukraine", "GB": "United Kingdom", "FR": "France",
    "IT": "Italy", "CA": "Canada", "KH": "Cambodia", "CD": "DR Congo",
}

class ConcentrationRiskAnalyzer:
    """調達集中リスク分析"""

    def calculate_hhi(self, shares: dict) -> float:
        """HHI (Herfindahl-Hirschman Index) = Σ(share_i²)
        0 = perfect competition, 1 = monopoly
        < 0.15 = low concentration
        0.15-0.25 = moderate concentration
        > 0.25 = high concentration
        """
        return sum(s**2 for s in shares.values())

    def analyze_supplier_concentration(self, suppliers: list, sector: str = "") -> dict:
        """
        suppliers: [{"country": "CN", "share": 0.7, "name": "Supplier A"}, ...]
        OR use sector template if suppliers is empty and sector is specified
        """
        if not suppliers and sector in SECTOR_TEMPLATES:
            suppliers = [{"country": k, "share": v} for k, v in SECTOR_TEMPLATES[sector].items()]

        if not suppliers:
            return {"error": "No supplier data provided", "timestamp": datetime.utcnow().isoformat()}

        # Calculate HHI
        country_shares = {}
        for s in suppliers:
            c = s.get("country", "Unknown")
            country_shares[c] = country_shares.get(c, 0) + s.get("share", 0)

        hhi = self.calculate_hhi(country_shares)

        # Determine risk level
        if hhi >= 0.25:
            concentration_level = "HIGH"
            concentration_score = min(100, int(hhi * 200))
        elif hhi >= 0.15:
            concentration_level = "MODERATE"
            concentration_score = min(80, int(hhi * 150))
        else:
            concentration_level = "LOW"
            concentration_score = int(hhi * 100)

        # Get risk scores for each country
        country_risks = {}
        for country_code in country_shares:
            if country_code == "Other":
                continue
            country_name = COUNTRY_NAMES.get(country_code, country_code)
            try:
                from scoring.engine import calculate_risk_score
                score = calculate_risk_score(f"conc_{country_code}", f"Concentration: {country_name}",
                                           country=country_name, location=country_name)
                country_risks[country_code] = {
                    "overall_risk": score.overall_score,
                    "share": country_shares[country_code],
                    "weighted_risk": score.overall_score * country_shares[country_code],
                }
            except Exception:
                country_risks[country_code] = {
                    "overall_risk": 0,
                    "share": country_shares[country_code],
                    "weighted_risk": 0,
                }

        weighted_risk = sum(cr.get("weighted_risk", 0) for cr in country_risks.values())

        # Suggest alternatives (low-risk countries not in current suppliers)
        low_risk_alternatives = [
            {"country": "JP", "name": "Japan", "typical_risk": 13},
            {"country": "SG", "name": "Singapore", "typical_risk": 31},
            {"country": "DE", "name": "Germany", "typical_risk": 42},
            {"country": "AU", "name": "Australia", "typical_risk": 25},
            {"country": "CA", "name": "Canada", "typical_risk": 20},
            {"country": "KR", "name": "South Korea", "typical_risk": 30},
        ]
        alternatives = [a for a in low_risk_alternatives if a["country"] not in country_shares]

        evidence = [
            f"[集中度] HHI指数: {hhi:.3f} ({concentration_level})",
            f"[集中度] 最大シェア: {max(country_shares.values()):.0%} ({max(country_shares, key=country_shares.get)})",
            f"[集中度] 調達国数: {len([c for c in country_shares if c != 'Other'])}カ国",
        ]

        return {
            "hhi": round(hhi, 4),
            "concentration_level": concentration_level,
            "concentration_score": concentration_score,
            "country_shares": country_shares,
            "country_risks": country_risks,
            "weighted_average_risk": round(weighted_risk, 1),
            "alternative_suppliers": alternatives[:5],
            "sector": sector,
            "evidence": evidence,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def recommend_diversification(self, current_shares: dict, target_hhi: float = 0.15) -> list:
        """目標HHI達成のための分散提案"""
        current_hhi = self.calculate_hhi(current_shares)
        if current_hhi <= target_hhi:
            return [{"message": f"Current HHI ({current_hhi:.3f}) already meets target ({target_hhi})"}]

        recommendations = []
        # Find dominant supplier and suggest reducing their share
        sorted_shares = sorted(current_shares.items(), key=lambda x: -x[1])
        dominant = sorted_shares[0]

        # Iteratively reduce dominant supplier share
        new_shares = dict(current_shares)
        step = 0.05
        while self.calculate_hhi(new_shares) > target_hhi and new_shares[dominant[0]] > 0.1:
            new_shares[dominant[0]] -= step
            # Distribute to alternatives
            alternatives = ["JP", "SG", "DE", "AU", "CA", "KR"]
            alt = [a for a in alternatives if a not in new_shares or new_shares.get(a, 0) < 0.15]
            if alt:
                for a in alt[:3]:
                    new_shares[a] = new_shares.get(a, 0) + step / min(3, len(alt))

        new_hhi = self.calculate_hhi(new_shares)
        recommendations.append({
            "target_hhi": target_hhi,
            "achievable_hhi": round(new_hhi, 4),
            "proposed_shares": {k: round(v, 3) for k, v in new_shares.items() if v > 0.01},
            "changes": {k: round(new_shares.get(k, 0) - current_shares.get(k, 0), 3)
                       for k in set(list(new_shares.keys()) + list(current_shares.keys()))
                       if abs(new_shares.get(k, 0) - current_shares.get(k, 0)) > 0.01},
        })
        return recommendations
