"""コモディティ・エクスポージャー分析
原材料の地政学×価格変動リスクを評価
"""
from datetime import datetime
from typing import Optional

# FRED series IDs for key commodities
COMMODITY_SERIES = {
    "wti_crude": "DCOILWTICO",
    "brent_crude": "DCOILBRENTEU",
    "natural_gas": "DHHNGSP",
    "copper": "PCOPPUSDM",
    "aluminum": "PALUMUSDM",
    "iron_ore": "PIORECRUSDM",
    "lithium": None,  # No FRED series
    "cobalt": None,
    "nickel": "PNICKUSDM",
    "wheat": "PWHEAMTUSDM",
    "rice": "PRICENPQUSDM",
    "corn": "PCORNCBUSDM",
}

# Key commodity dependencies by sector
COMMODITY_DEPENDENCIES = {
    "semiconductor": ["silicon", "copper", "aluminum", "rare_earth"],
    "battery_materials": ["lithium", "cobalt", "nickel", "copper", "graphite"],
    "automotive_parts": ["iron_ore", "aluminum", "copper", "rubber", "platinum"],
    "electronics": ["copper", "aluminum", "rare_earth", "silicon"],
    "energy": ["wti_crude", "brent_crude", "natural_gas", "coal"],
    "food": ["wheat", "rice", "corn", "soybeans"],
}

class CommodityExposureAnalyzer:
    """コモディティエクスポージャー分析"""

    def calculate_exposure(self, sector: str, supplier_countries: list = None,
                          shares: list = None) -> dict:
        """セクター別エクスポージャー計算"""
        commodities = COMMODITY_DEPENDENCIES.get(sector, [])
        if not commodities:
            return {"error": f"Unknown sector: {sector}", "available": list(COMMODITY_DEPENDENCIES.keys())}

        # Get price data for available commodities
        price_data = {}
        for commodity in commodities:
            series_id = COMMODITY_SERIES.get(commodity)
            if series_id:
                try:
                    from pipeline.energy.commodity_client import fetch_fred_series
                    data = fetch_fred_series(series_id)
                    if data:
                        price_data[commodity] = data
                except Exception:
                    pass

        # Calculate concentration risk if suppliers provided
        concentration_score = 0
        if supplier_countries and shares:
            try:
                from features.concentration.analyzer import ConcentrationRiskAnalyzer
                ca = ConcentrationRiskAnalyzer()
                suppliers = [{"country": c, "share": s} for c, s in zip(supplier_countries, shares)]
                conc = ca.analyze_supplier_concentration(suppliers, sector=sector)
                concentration_score = conc.get("concentration_score", 0)
            except Exception:
                pass

        # Calculate overall exposure
        price_volatility = len(price_data) * 5  # Simple proxy
        geo_risk = concentration_score
        exposure_score = min(100, int(price_volatility * 0.4 + geo_risk * 0.6))

        evidence = [
            f"[コモディティ] セクター: {sector}",
            f"[コモディティ] 主要原材料: {', '.join(commodities)}",
            f"[コモディティ] 価格データ取得: {len(price_data)}/{len(commodities)}品目",
        ]
        if concentration_score > 0:
            evidence.append(f"[集中度] 調達集中リスク: {concentration_score}")

        return {
            "sector": sector,
            "commodities": commodities,
            "price_data_available": list(price_data.keys()),
            "concentration_score": concentration_score,
            "exposure_score": exposure_score,
            "evidence": evidence,
            "timestamp": datetime.utcnow().isoformat(),
        }
