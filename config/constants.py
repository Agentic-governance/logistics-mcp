"""SCRI Platform v1.4.0 中央定数定義"""

VERSION = "1.4.0"
DIMENSIONS = 27

# リスクレベル閾値
RISK_THRESHOLDS = {
    "CRITICAL": 80,
    "HIGH": 60,
    "MEDIUM": 40,
    "LOW": 20,
    "MINIMAL": 0,
}

# 制裁ソース一覧
SANCTION_SOURCES = [
    "OFAC", "EU", "UN", "METI", "BIS",
    "OFSI", "SECO", "Canada", "DFAT", "MOFA_Japan",
]

# データソース一覧
DATA_SOURCES = {
    "sanctions": SANCTION_SOURCES,
    "geopolitical": ["GDELT BigQuery"],
    "disaster": ["GDACS", "USGS Earthquake", "NASA FIRMS", "JMA", "BMKG"],
    "maritime": ["IMF PortWatch", "AISHub", "UNCTAD Port Statistics"],
    "conflict": ["ACLED"],
    "economic": ["World Bank", "Frankfurter/ECB", "UN Comtrade"],
    "health": ["Disease.sh", "ReliefWeb/OCHA"],
    "weather": ["Open-Meteo", "NOAA NHC", "NOAA SWPC"],
    "compliance": ["FATF", "TI CPI"],
    "political": ["Freedom House"],
    "food_security": ["WFP HungerMap"],
    "labor": ["DoL ILAB", "Global Slavery Index"],
    "infrastructure": ["Cloudflare Radar", "IODA"],
    "aviation": ["OpenSky Network"],
    "energy": ["FRED", "EIA"],
    "japan": ["BOJ", "ExchangeRate-API", "e-Stat"],
    "climate": ["ND-GAIN", "GloFAS", "WRI Aqueduct", "Climate TRACE"],
    "cyber": ["OONI", "CISA KEV", "ITU ICT"],
    "regional": ["KOSIS", "Taiwan DGBAS", "China NBS",
                 "Vietnam GSO", "DOSM Malaysia", "MPA Singapore",
                 "ASEAN Stats", "Eurostat", "ILO", "AfDB"],
    "person_risk": ["OpenOwnership", "ICIJ Offshore Leaks", "Wikidata", "制裁DB"],
    "capital_flow": ["Chinn-Ito Index", "IMF AREAER", "SWIFT"],
}

# 7大チョークポイント
CHOKEPOINTS = [
    "Suez Canal", "Strait of Malacca", "Strait of Hormuz",
    "Bab-el-Mandeb", "Panama Canal", "Turkish Straits", "Taiwan Strait",
]

# 主要50カ国 (定期監視対象)
PRIORITY_COUNTRIES = [
    "Japan", "United States", "Germany", "United Kingdom", "France", "Italy", "Canada",
    "China", "India", "Russia", "Brazil", "South Africa",
    "Indonesia", "Vietnam", "Thailand", "Malaysia", "Singapore", "Philippines", "Myanmar", "Cambodia",
    "Saudi Arabia", "UAE", "Iran", "Iraq", "Turkey", "Israel", "Qatar", "Yemen",
    "South Korea", "Taiwan", "North Korea",
    "Bangladesh", "Pakistan", "Sri Lanka",
    "Nigeria", "Ethiopia", "Kenya", "Egypt", "South Sudan", "Somalia",
    "Ukraine", "Poland", "Netherlands", "Switzerland",
    "Mexico", "Colombia", "Venezuela", "Argentina", "Chile",
    "Australia",
]

# セクター別コモディティ依存
SECTOR_COMMODITIES = {
    "semiconductor": ["silicon", "copper", "aluminum", "rare_earth"],
    "battery_materials": ["lithium", "cobalt", "nickel", "copper", "graphite"],
    "automotive_parts": ["iron_ore", "aluminum", "copper", "rubber", "platinum"],
    "electronics": ["copper", "aluminum", "rare_earth", "silicon"],
    "energy": ["wti_crude", "brent_crude", "natural_gas", "coal"],
    "food": ["wheat", "rice", "corn", "soybeans"],
}
