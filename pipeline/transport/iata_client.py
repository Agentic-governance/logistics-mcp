"""IATA Air Cargo Hub Rankings and Connectivity
Static dataset approach (IATA data requires paid subscription).
Rankings based on publicly available air cargo volume data.
Source: ACI World Airport Traffic Rankings 2023, IATA Cargo Statistics
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Top 50 cargo airports by cargo volume (metric tonnes, 2023)
# Source: Airports Council International (ACI) World Airport Traffic Report 2023
AIR_CARGO_HUBS = {
    "HKG": {"airport": "Hong Kong International", "country": "China", "region": "east_asia", "cargo_tonnes": 4_290_000, "rank": 1},
    "MEM": {"airport": "Memphis International", "country": "United States", "region": "north_america", "cargo_tonnes": 4_150_000, "rank": 2},
    "PVG": {"airport": "Shanghai Pudong", "country": "China", "region": "east_asia", "cargo_tonnes": 3_540_000, "rank": 3},
    "ANC": {"airport": "Ted Stevens Anchorage", "country": "United States", "region": "north_america", "cargo_tonnes": 3_280_000, "rank": 4},
    "ICN": {"airport": "Incheon International", "country": "South Korea", "region": "east_asia", "cargo_tonnes": 2_960_000, "rank": 5},
    "DXB": {"airport": "Dubai International", "country": "United Arab Emirates", "region": "middle_east", "cargo_tonnes": 2_710_000, "rank": 6},
    "SDF": {"airport": "Louisville Muhammad Ali", "country": "United States", "region": "north_america", "cargo_tonnes": 2_690_000, "rank": 7},
    "TPE": {"airport": "Taiwan Taoyuan", "country": "Taiwan", "region": "east_asia", "cargo_tonnes": 2_310_000, "rank": 8},
    "NRT": {"airport": "Narita International", "country": "Japan", "region": "east_asia", "cargo_tonnes": 2_120_000, "rank": 9},
    "DOH": {"airport": "Hamad International", "country": "Qatar", "region": "middle_east", "cargo_tonnes": 2_090_000, "rank": 10},
    "SIN": {"airport": "Singapore Changi", "country": "Singapore", "region": "southeast_asia", "cargo_tonnes": 2_050_000, "rank": 11},
    "FRA": {"airport": "Frankfurt Airport", "country": "Germany", "region": "europe", "cargo_tonnes": 1_950_000, "rank": 12},
    "CDG": {"airport": "Paris Charles de Gaulle", "country": "France", "region": "europe", "cargo_tonnes": 1_930_000, "rank": 13},
    "MIA": {"airport": "Miami International", "country": "United States", "region": "north_america", "cargo_tonnes": 1_870_000, "rank": 14},
    "LAX": {"airport": "Los Angeles International", "country": "United States", "region": "north_america", "cargo_tonnes": 1_830_000, "rank": 15},
    "BKK": {"airport": "Suvarnabhumi", "country": "Thailand", "region": "southeast_asia", "cargo_tonnes": 1_420_000, "rank": 16},
    "LHR": {"airport": "London Heathrow", "country": "United Kingdom", "region": "europe", "cargo_tonnes": 1_400_000, "rank": 17},
    "CAN": {"airport": "Guangzhou Baiyun", "country": "China", "region": "east_asia", "cargo_tonnes": 1_390_000, "rank": 18},
    "KUL": {"airport": "Kuala Lumpur International", "country": "Malaysia", "region": "southeast_asia", "cargo_tonnes": 1_100_000, "rank": 19},
    "ORD": {"airport": "Chicago O'Hare", "country": "United States", "region": "north_america", "cargo_tonnes": 1_080_000, "rank": 20},
    "AMS": {"airport": "Amsterdam Schiphol", "country": "Netherlands", "region": "europe", "cargo_tonnes": 1_050_000, "rank": 21},
    "DEL": {"airport": "Indira Gandhi International", "country": "India", "region": "south_asia", "cargo_tonnes": 1_020_000, "rank": 22},
    "SZX": {"airport": "Shenzhen Bao'an", "country": "China", "region": "east_asia", "cargo_tonnes": 990_000, "rank": 23},
    "CGN": {"airport": "Cologne Bonn", "country": "Germany", "region": "europe", "cargo_tonnes": 870_000, "rank": 24},
    "IST": {"airport": "Istanbul Airport", "country": "Turkey", "region": "europe", "cargo_tonnes": 860_000, "rank": 25},
    "JFK": {"airport": "John F. Kennedy International", "country": "United States", "region": "north_america", "cargo_tonnes": 850_000, "rank": 26},
    "LIE": {"airport": "Leipzig/Halle", "country": "Germany", "region": "europe", "cargo_tonnes": 840_000, "rank": 27},
    "BOM": {"airport": "Chhatrapati Shivaji Maharaj", "country": "India", "region": "south_asia", "cargo_tonnes": 810_000, "rank": 28},
    "KIX": {"airport": "Kansai International", "country": "Japan", "region": "east_asia", "cargo_tonnes": 780_000, "rank": 29},
    "EWR": {"airport": "Newark Liberty", "country": "United States", "region": "north_america", "cargo_tonnes": 750_000, "rank": 30},
    "GRU": {"airport": "Sao Paulo Guarulhos", "country": "Brazil", "region": "south_america", "cargo_tonnes": 720_000, "rank": 31},
    "NGO": {"airport": "Chubu Centrair", "country": "Japan", "region": "east_asia", "cargo_tonnes": 680_000, "rank": 32},
    "BRU": {"airport": "Brussels Airport", "country": "Belgium", "region": "europe", "cargo_tonnes": 660_000, "rank": 33},
    "ATL": {"airport": "Hartsfield-Jackson Atlanta", "country": "United States", "region": "north_america", "cargo_tonnes": 640_000, "rank": 34},
    "DFW": {"airport": "Dallas/Fort Worth", "country": "United States", "region": "north_america", "cargo_tonnes": 620_000, "rank": 35},
    "SVO": {"airport": "Sheremetyevo", "country": "Russia", "region": "europe", "cargo_tonnes": 600_000, "rank": 36},
    "LUX": {"airport": "Luxembourg Findel", "country": "Luxembourg", "region": "europe", "cargo_tonnes": 590_000, "rank": 37},
    "MXP": {"airport": "Milan Malpensa", "country": "Italy", "region": "europe", "cargo_tonnes": 570_000, "rank": 38},
    "HAN": {"airport": "Noi Bai International", "country": "Vietnam", "region": "southeast_asia", "cargo_tonnes": 560_000, "rank": 39},
    "CTU": {"airport": "Chengdu Tianfu", "country": "China", "region": "east_asia", "cargo_tonnes": 540_000, "rank": 40},
    "PEK": {"airport": "Beijing Capital", "country": "China", "region": "east_asia", "cargo_tonnes": 530_000, "rank": 41},
    "HND": {"airport": "Tokyo Haneda", "country": "Japan", "region": "east_asia", "cargo_tonnes": 520_000, "rank": 42},
    "BEG": {"airport": "Belgrade Nikola Tesla", "country": "Serbia", "region": "europe", "cargo_tonnes": 510_000, "rank": 43},
    "JED": {"airport": "King Abdulaziz", "country": "Saudi Arabia", "region": "middle_east", "cargo_tonnes": 500_000, "rank": 44},
    "MNL": {"airport": "Ninoy Aquino International", "country": "Philippines", "region": "southeast_asia", "cargo_tonnes": 490_000, "rank": 45},
    "CPH": {"airport": "Copenhagen Kastrup", "country": "Denmark", "region": "europe", "cargo_tonnes": 470_000, "rank": 46},
    "MEX": {"airport": "Mexico City International", "country": "Mexico", "region": "north_america", "cargo_tonnes": 460_000, "rank": 47},
    "RUH": {"airport": "King Khalid International", "country": "Saudi Arabia", "region": "middle_east", "cargo_tonnes": 450_000, "rank": 48},
    "CGK": {"airport": "Soekarno-Hatta", "country": "Indonesia", "region": "southeast_asia", "cargo_tonnes": 440_000, "rank": 49},
    "BOG": {"airport": "El Dorado International", "country": "Colombia", "region": "south_america", "cargo_tonnes": 430_000, "rank": 50},
}

# Regional cargo volume indices (normalized, 100 = global average)
REGIONAL_INDICES = {
    "east_asia": {"cargo_volume_index": 145.0, "trend": "stable"},
    "southeast_asia": {"cargo_volume_index": 115.0, "trend": "increasing"},
    "south_asia": {"cargo_volume_index": 85.0, "trend": "increasing"},
    "middle_east": {"cargo_volume_index": 120.0, "trend": "increasing"},
    "europe": {"cargo_volume_index": 105.0, "trend": "stable"},
    "north_america": {"cargo_volume_index": 125.0, "trend": "stable"},
    "south_america": {"cargo_volume_index": 60.0, "trend": "stable"},
    "africa": {"cargo_volume_index": 30.0, "trend": "increasing"},
    "oceania": {"cargo_volume_index": 45.0, "trend": "stable"},
    "central_asia": {"cargo_volume_index": 25.0, "trend": "stable"},
}

# Country name to alias for lookups
COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States",
    "uk": "United Kingdom", "britain": "United Kingdom",
    "korea": "South Korea", "uae": "United Arab Emirates",
}


def _resolve_country(country: str) -> str:
    """Resolve country name to standard form."""
    lower = country.lower().strip()
    if lower in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[lower]
    return country


def get_cargo_volume_trend(region: str) -> dict:
    """Get air cargo volume trend for a region.

    Args:
        region: Region identifier (e.g., 'east_asia', 'europe', 'north_america')

    Returns:
        dict with keys: major_hubs (list), cargo_volume_index (float),
                        score (0-100), evidence (list of str)
    """
    region_lower = region.lower().strip().replace(" ", "_")

    # Find hubs in this region
    hubs_in_region = [
        {"code": code, "airport": data["airport"], "country": data["country"],
         "cargo_tonnes": data["cargo_tonnes"], "rank": data["rank"]}
        for code, data in AIR_CARGO_HUBS.items()
        if data["region"] == region_lower
    ]
    hubs_in_region.sort(key=lambda x: x["rank"])

    regional_data = REGIONAL_INDICES.get(region_lower, {})
    cargo_volume_index = regional_data.get("cargo_volume_index", 50.0)
    trend = regional_data.get("trend", "unknown")

    # Lower cargo volume = higher risk (supply chain disruption indicator)
    # Index 150+ = 0 risk, index 0 = 100 risk
    if cargo_volume_index >= 130:
        score = 5
    elif cargo_volume_index >= 100:
        score = 15
    elif cargo_volume_index >= 70:
        score = 30
    elif cargo_volume_index >= 40:
        score = 50
    elif cargo_volume_index >= 20:
        score = 70
    else:
        score = 85

    # Trend modifier
    if trend == "increasing":
        score = max(0, score - 10)
    elif trend == "decreasing":
        score = min(100, score + 15)

    evidence = [
        f"Air cargo volume index: {cargo_volume_index:.0f} (100=global avg) [{region_lower}]",
        f"Volume trend: {trend}",
        f"Major cargo hubs in region: {len(hubs_in_region)}",
    ]
    if hubs_in_region:
        top_3 = hubs_in_region[:3]
        for hub in top_3:
            evidence.append(f"  #{hub['rank']} {hub['airport']} ({hub['country']}): {hub['cargo_tonnes']:,} tonnes")

    return {
        "major_hubs": hubs_in_region,
        "cargo_volume_index": cargo_volume_index,
        "score": score,
        "evidence": evidence,
    }


def get_aviation_connectivity(country: str) -> dict:
    """Get aviation connectivity score for a country.

    Args:
        country: Country name (e.g., 'Japan', 'United States')

    Returns:
        dict with keys: hub_count, total_cargo_tonnes, connectivity_score (0-100),
                        score (0-100), evidence (list of str)
    """
    resolved = _resolve_country(country)

    # Find all hubs in this country
    country_hubs = [
        {"code": code, "airport": data["airport"], "rank": data["rank"],
         "cargo_tonnes": data["cargo_tonnes"]}
        for code, data in AIR_CARGO_HUBS.items()
        if data["country"].lower() == resolved.lower()
    ]
    country_hubs.sort(key=lambda x: x["rank"])

    hub_count = len(country_hubs)
    total_cargo = sum(h["cargo_tonnes"] for h in country_hubs)

    # Connectivity score: more hubs + more volume = higher connectivity
    # Max hub count in dataset is ~10 (US), max total cargo is ~15M (US)
    hub_score = min(50.0, hub_count * 10.0)
    volume_score = min(50.0, total_cargo / 200_000.0)
    connectivity_score = min(100, int(hub_score + volume_score))

    # Lower connectivity = higher supply chain risk
    risk_score = max(0, 100 - connectivity_score)

    evidence = [
        f"Major cargo airports (top 50): {hub_count} [{resolved}]",
        f"Total cargo volume: {total_cargo:,} tonnes",
        f"Aviation connectivity score: {connectivity_score}/100",
    ]
    for hub in country_hubs[:5]:
        evidence.append(f"  #{hub['rank']} {hub['airport']}: {hub['cargo_tonnes']:,} tonnes")

    if hub_count == 0:
        evidence.append(f"NOTE: No airports in global top 50 - limited air cargo connectivity")

    return {
        "hub_count": hub_count,
        "total_cargo_tonnes": total_cargo,
        "connectivity_score": connectivity_score,
        "score": risk_score,
        "evidence": evidence,
    }


if __name__ == "__main__":
    print("=== Regional Cargo Volume ===")
    for region in ["east_asia", "europe", "africa"]:
        result = get_cargo_volume_trend(region)
        print(f"\n{region}: score={result['score']}, index={result['cargo_volume_index']}")
        for e in result["evidence"]:
            print(f"  {e}")

    print("\n=== Aviation Connectivity ===")
    for country in ["Japan", "United States", "Singapore", "Nigeria"]:
        result = get_aviation_connectivity(country)
        print(f"\n{country}: risk_score={result['score']}, connectivity={result['connectivity_score']}")
        for e in result["evidence"]:
            print(f"  {e}")
