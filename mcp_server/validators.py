"""MCP Tool Input Validators"""

# Country name/code normalization
COUNTRY_ALIASES = {
    # Common aliases
    "US": "United States", "USA": "United States", "UK": "United Kingdom",
    "GB": "United Kingdom", "JP": "Japan", "JPN": "Japan",
    "CN": "China", "CHN": "China", "KR": "South Korea", "KOR": "South Korea",
    "DE": "Germany", "DEU": "Germany", "FR": "France", "FRA": "France",
    "TW": "Taiwan", "TWN": "Taiwan", "IN": "India", "IND": "India",
    "BR": "Brazil", "BRA": "Brazil", "RU": "Russia", "RUS": "Russia",
    "AU": "Australia", "AUS": "Australia", "CA": "Canada", "CAN": "Canada",
    "IT": "Italy", "ITA": "Italy", "MX": "Mexico", "MEX": "Mexico",
    "ID": "Indonesia", "IDN": "Indonesia", "VN": "Vietnam", "VNM": "Vietnam",
    "TH": "Thailand", "THA": "Thailand", "MY": "Malaysia", "MYS": "Malaysia",
    "SG": "Singapore", "SGP": "Singapore", "PH": "Philippines", "PHL": "Philippines",
    "SA": "Saudi Arabia", "SAU": "Saudi Arabia", "AE": "UAE", "ARE": "UAE",
    "IL": "Israel", "ISR": "Israel", "TR": "Turkey", "TUR": "Turkey",
    "ZA": "South Africa", "ZAF": "South Africa", "NG": "Nigeria", "NGA": "Nigeria",
    "EG": "Egypt", "EGY": "Egypt", "KE": "Kenya", "KEN": "Kenya",
    "PK": "Pakistan", "PAK": "Pakistan", "BD": "Bangladesh", "BGD": "Bangladesh",
    "UA": "Ukraine", "UKR": "Ukraine", "PL": "Poland", "POL": "Poland",
    "NL": "Netherlands", "NLD": "Netherlands", "CH": "Switzerland", "CHE": "Switzerland",
    "SE": "Sweden", "SWE": "Sweden", "CO": "Colombia", "COL": "Colombia",
    "AR": "Argentina", "ARG": "Argentina", "CL": "Chile", "CHL": "Chile",
    "MM": "Myanmar", "MMR": "Myanmar", "IQ": "Iraq", "IRQ": "Iraq",
    "IR": "Iran", "IRN": "Iran", "YE": "Yemen", "YEM": "Yemen",
    "VE": "Venezuela", "VEN": "Venezuela", "ET": "Ethiopia", "ETH": "Ethiopia",
    "KP": "North Korea", "PRK": "North Korea", "HK": "Hong Kong", "HKG": "Hong Kong",
}

VALID_DIMENSIONS = [
    "sanctions", "geo_risk", "disaster", "legal", "maritime", "conflict",
    "economic", "currency", "health", "humanitarian", "weather", "typhoon",
    "compliance", "food_security", "trade", "internet", "political",
    "labor", "port_congestion", "aviation", "energy", "japan_economy",
    "climate_risk", "cyber_risk",
]

VALID_INDUSTRIES = ["automotive", "semiconductor", "pharma", "apparel", "energy"]

VALID_SCENARIOS = ["taiwan_blockade", "suez_closure", "china_lockdown", "semiconductor_shortage", "pandemic_wave"]


def validate_country(country: str) -> str:
    """Normalize country input to standard name. Raises ValueError if invalid."""
    if not country or not isinstance(country, str):
        raise ValueError("Country must be a non-empty string")

    cleaned = country.strip()
    upper = cleaned.upper()

    # Check aliases
    if upper in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[upper]

    # Check if it's already a valid country name (case-insensitive match)
    for alias_val in set(COUNTRY_ALIASES.values()):
        if cleaned.lower() == alias_val.lower():
            return alias_val

    # Return as-is if not found in aliases (let downstream handle it)
    return cleaned


def validate_dimension(dim: str) -> str:
    """Validate dimension name. Raises ValueError with valid options if invalid."""
    if dim not in VALID_DIMENSIONS:
        raise ValueError(f"Invalid dimension '{dim}'. Valid dimensions: {VALID_DIMENSIONS}")
    return dim


def validate_industry(industry: str) -> str:
    """Validate industry name."""
    if industry not in VALID_INDUSTRIES:
        raise ValueError(f"Invalid industry '{industry}'. Valid: {VALID_INDUSTRIES}")
    return industry


def validate_scenario(scenario: str) -> str:
    """Validate scenario name."""
    if scenario not in VALID_SCENARIOS:
        raise ValueError(f"Invalid scenario '{scenario}'. Valid: {VALID_SCENARIOS}")
    return scenario


def validate_locations_list(locations_str: str, max_items: int = 10) -> list[str]:
    """Parse and validate comma-separated locations."""
    if not locations_str:
        raise ValueError("Locations must be a non-empty string")
    items = [l.strip() for l in locations_str.split(",") if l.strip()]
    if len(items) > max_items:
        raise ValueError(f"Maximum {max_items} locations allowed, got {len(items)}")
    return [validate_country(loc) for loc in items]


def safe_error_response(error: Exception) -> dict:
    """Create standardized error response."""
    return {
        "error": str(error),
        "error_type": type(error).__name__,
    }
