"""Lloyd's List Port Rankings - Container Port Throughput
Static dataset of top 100 container ports by TEU throughput.
Source: Lloyd's List One Hundred Ports 2024
https://lloydslist.com/
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Top 100 container ports by TEU throughput (millions, 2023 estimates)
# Source: Lloyd's List Top 100 Container Ports 2024, Alphaliner
PORT_RANKINGS = [
    {"rank": 1, "port": "Shanghai", "country": "China", "teu_millions": 49.2},
    {"rank": 2, "port": "Singapore", "country": "Singapore", "teu_millions": 39.0},
    {"rank": 3, "port": "Ningbo-Zhoushan", "country": "China", "teu_millions": 35.3},
    {"rank": 4, "port": "Shenzhen", "country": "China", "teu_millions": 30.2},
    {"rank": 5, "port": "Qingdao", "country": "China", "teu_millions": 28.7},
    {"rank": 6, "port": "Guangzhou", "country": "China", "teu_millions": 25.2},
    {"rank": 7, "port": "Busan", "country": "South Korea", "teu_millions": 23.5},
    {"rank": 8, "port": "Tianjin", "country": "China", "teu_millions": 22.7},
    {"rank": 9, "port": "Hong Kong", "country": "China", "teu_millions": 14.3},
    {"rank": 10, "port": "Rotterdam", "country": "Netherlands", "teu_millions": 14.0},
    {"rank": 11, "port": "Dubai (Jebel Ali)", "country": "United Arab Emirates", "teu_millions": 13.6},
    {"rank": 12, "port": "Port Klang", "country": "Malaysia", "teu_millions": 13.2},
    {"rank": 13, "port": "Antwerp-Bruges", "country": "Belgium", "teu_millions": 13.0},
    {"rank": 14, "port": "Xiamen", "country": "China", "teu_millions": 12.8},
    {"rank": 15, "port": "Kaohsiung", "country": "Taiwan", "teu_millions": 9.6},
    {"rank": 16, "port": "Los Angeles", "country": "United States", "teu_millions": 9.5},
    {"rank": 17, "port": "Tanjung Pelepas", "country": "Malaysia", "teu_millions": 9.3},
    {"rank": 18, "port": "Hamburg", "country": "Germany", "teu_millions": 8.2},
    {"rank": 19, "port": "Long Beach", "country": "United States", "teu_millions": 8.1},
    {"rank": 20, "port": "Laem Chabang", "country": "Thailand", "teu_millions": 7.8},
    {"rank": 21, "port": "Tanjung Priok (Jakarta)", "country": "Indonesia", "teu_millions": 7.6},
    {"rank": 22, "port": "Ho Chi Minh City", "country": "Vietnam", "teu_millions": 7.5},
    {"rank": 23, "port": "Colombo", "country": "Sri Lanka", "teu_millions": 7.3},
    {"rank": 24, "port": "Dalian", "country": "China", "teu_millions": 7.1},
    {"rank": 25, "port": "Piraeus", "country": "Greece", "teu_millions": 5.2},
    {"rank": 26, "port": "Tokyo", "country": "Japan", "teu_millions": 5.0},
    {"rank": 27, "port": "Suzhou (Taicang)", "country": "China", "teu_millions": 4.8},
    {"rank": 28, "port": "New York/New Jersey", "country": "United States", "teu_millions": 4.7},
    {"rank": 29, "port": "Savannah", "country": "United States", "teu_millions": 4.6},
    {"rank": 30, "port": "Valencia", "country": "Spain", "teu_millions": 4.5},
    {"rank": 31, "port": "Jeddah", "country": "Saudi Arabia", "teu_millions": 4.4},
    {"rank": 32, "port": "Yokohama", "country": "Japan", "teu_millions": 4.3},
    {"rank": 33, "port": "Manila", "country": "Philippines", "teu_millions": 4.2},
    {"rank": 34, "port": "Santos", "country": "Brazil", "teu_millions": 4.1},
    {"rank": 35, "port": "Mundra", "country": "India", "teu_millions": 4.0},
    {"rank": 36, "port": "Nhava Sheva (JNPT)", "country": "India", "teu_millions": 3.9},
    {"rank": 37, "port": "Algeciras", "country": "Spain", "teu_millions": 3.8},
    {"rank": 38, "port": "Tanger Med", "country": "Morocco", "teu_millions": 3.7},
    {"rank": 39, "port": "Lianyungang", "country": "China", "teu_millions": 3.6},
    {"rank": 40, "port": "Felixstowe", "country": "United Kingdom", "teu_millions": 3.5},
    {"rank": 41, "port": "Manzanillo", "country": "Mexico", "teu_millions": 3.4},
    {"rank": 42, "port": "King Abdullah Port", "country": "Saudi Arabia", "teu_millions": 3.3},
    {"rank": 43, "port": "Yingkou", "country": "China", "teu_millions": 3.2},
    {"rank": 44, "port": "Colombo South", "country": "Sri Lanka", "teu_millions": 3.1},
    {"rank": 45, "port": "Kobe", "country": "Japan", "teu_millions": 3.0},
    {"rank": 46, "port": "Nagoya", "country": "Japan", "teu_millions": 2.9},
    {"rank": 47, "port": "Balboa", "country": "Panama", "teu_millions": 2.8},
    {"rank": 48, "port": "Le Havre", "country": "France", "teu_millions": 2.7},
    {"rank": 49, "port": "Cartagena", "country": "Colombia", "teu_millions": 2.7},
    {"rank": 50, "port": "Khalifa Port (Abu Dhabi)", "country": "United Arab Emirates", "teu_millions": 2.6},
    {"rank": 51, "port": "Salalah", "country": "Oman", "teu_millions": 2.5},
    {"rank": 52, "port": "Bremerhaven", "country": "Germany", "teu_millions": 2.5},
    {"rank": 53, "port": "Durban", "country": "South Africa", "teu_millions": 2.4},
    {"rank": 54, "port": "Gothenburg", "country": "Sweden", "teu_millions": 2.4},
    {"rank": 55, "port": "Colombo (East)", "country": "Sri Lanka", "teu_millions": 2.3},
    {"rank": 56, "port": "Chittagong", "country": "Bangladesh", "teu_millions": 2.3},
    {"rank": 57, "port": "Colon", "country": "Panama", "teu_millions": 2.2},
    {"rank": 58, "port": "Haiphong", "country": "Vietnam", "teu_millions": 2.2},
    {"rank": 59, "port": "Mersin", "country": "Turkey", "teu_millions": 2.1},
    {"rank": 60, "port": "Barcelona", "country": "Spain", "teu_millions": 2.1},
    {"rank": 61, "port": "Charleston", "country": "United States", "teu_millions": 2.0},
    {"rank": 62, "port": "Houston", "country": "United States", "teu_millions": 2.0},
    {"rank": 63, "port": "Genoa", "country": "Italy", "teu_millions": 1.9},
    {"rank": 64, "port": "Gioia Tauro", "country": "Italy", "teu_millions": 1.9},
    {"rank": 65, "port": "Ambarli", "country": "Turkey", "teu_millions": 1.8},
    {"rank": 66, "port": "Gdansk", "country": "Poland", "teu_millions": 1.8},
    {"rank": 67, "port": "Callao", "country": "Peru", "teu_millions": 1.7},
    {"rank": 68, "port": "Seattle/Tacoma", "country": "United States", "teu_millions": 1.7},
    {"rank": 69, "port": "Tanger Med 2", "country": "Morocco", "teu_millions": 1.7},
    {"rank": 70, "port": "Bandar Abbas", "country": "Iran", "teu_millions": 1.6},
    {"rank": 71, "port": "Lazaro Cardenas", "country": "Mexico", "teu_millions": 1.6},
    {"rank": 72, "port": "Zeebrugge", "country": "Belgium", "teu_millions": 1.5},
    {"rank": 73, "port": "Oakland", "country": "United States", "teu_millions": 1.5},
    {"rank": 74, "port": "San Juan", "country": "Puerto Rico", "teu_millions": 1.4},
    {"rank": 75, "port": "Kingston", "country": "Jamaica", "teu_millions": 1.4},
    {"rank": 76, "port": "Constanta", "country": "Romania", "teu_millions": 1.4},
    {"rank": 77, "port": "Norfolk", "country": "United States", "teu_millions": 1.3},
    {"rank": 78, "port": "Sydney", "country": "Australia", "teu_millions": 1.3},
    {"rank": 79, "port": "Melbourne", "country": "Australia", "teu_millions": 1.3},
    {"rank": 80, "port": "Osaka", "country": "Japan", "teu_millions": 1.2},
    {"rank": 81, "port": "Tema", "country": "Ghana", "teu_millions": 1.2},
    {"rank": 82, "port": "Guayaquil", "country": "Ecuador", "teu_millions": 1.2},
    {"rank": 83, "port": "Alexandria", "country": "Egypt", "teu_millions": 1.1},
    {"rank": 84, "port": "East Port Said", "country": "Egypt", "teu_millions": 1.1},
    {"rank": 85, "port": "Dammam", "country": "Saudi Arabia", "teu_millions": 1.1},
    {"rank": 86, "port": "Maputo", "country": "Mozambique", "teu_millions": 1.0},
    {"rank": 87, "port": "Vancouver", "country": "Canada", "teu_millions": 1.0},
    {"rank": 88, "port": "Montreal", "country": "Canada", "teu_millions": 1.0},
    {"rank": 89, "port": "Incheon", "country": "South Korea", "teu_millions": 1.0},
    {"rank": 90, "port": "Buenos Aires", "country": "Argentina", "teu_millions": 0.9},
    {"rank": 91, "port": "Lagos (Apapa/Tin Can)", "country": "Nigeria", "teu_millions": 0.9},
    {"rank": 92, "port": "Dar es Salaam", "country": "Tanzania", "teu_millions": 0.9},
    {"rank": 93, "port": "Mombasa", "country": "Kenya", "teu_millions": 0.8},
    {"rank": 94, "port": "Limon/Moin", "country": "Costa Rica", "teu_millions": 0.8},
    {"rank": 95, "port": "Ashdod", "country": "Israel", "teu_millions": 0.8},
    {"rank": 96, "port": "Haifa", "country": "Israel", "teu_millions": 0.8},
    {"rank": 97, "port": "Fremantle", "country": "Australia", "teu_millions": 0.7},
    {"rank": 98, "port": "Veracruz", "country": "Mexico", "teu_millions": 0.7},
    {"rank": 99, "port": "Novorossiysk", "country": "Russia", "teu_millions": 0.7},
    {"rank": 100, "port": "St. Petersburg", "country": "Russia", "teu_millions": 0.7},
]

# Known congestion-prone ports
HIGH_CONGESTION_PORTS = {
    "Shanghai", "Los Angeles", "Long Beach", "Shenzhen", "Ningbo-Zhoushan",
    "Rotterdam", "Hamburg", "Felixstowe", "Savannah", "New York/New Jersey",
    "Durban", "Chittagong", "Lagos (Apapa/Tin Can)", "Santos",
}

# Country name normalization
COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom",
    "korea": "South Korea", "republic of korea": "South Korea",
    "uae": "United Arab Emirates",
}


def _resolve_country(country: str) -> str:
    """Resolve country name to standard form."""
    lower = country.lower().strip()
    if lower in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[lower]
    return country


def get_port_rankings() -> list[dict]:
    """Get the full top 100 container port rankings.

    Returns:
        list of dicts with keys: rank, port, country, teu_millions
    """
    return [dict(p) for p in PORT_RANKINGS]


def get_port_importance_score(country: str) -> dict:
    """Get port importance and congestion risk score for a country.

    Args:
        country: Country name (e.g., 'Japan', 'China', 'United States')

    Returns:
        dict with keys: ports_in_top100 (int), total_teu (float),
                        score (0-100), evidence (list of str)
    """
    resolved = _resolve_country(country)

    # Find all ports in this country
    country_ports = [
        p for p in PORT_RANKINGS
        if p["country"].lower() == resolved.lower()
    ]

    ports_in_top100 = len(country_ports)
    total_teu = sum(p["teu_millions"] for p in country_ports)

    # Identify congestion-prone ports in this country
    congested_ports = [
        p for p in country_ports
        if p["port"] in HIGH_CONGESTION_PORTS
    ]
    congestion_count = len(congested_ports)

    # Score computation:
    # High port capacity = important for supply chains
    # Congestion-prone ports = higher risk of disruption
    # Countries with high TEU but also high congestion risk score higher
    score = 0

    # Base: congestion risk (primary risk factor)
    if congestion_count > 3:
        score += 45
    elif congestion_count > 1:
        score += 30
    elif congestion_count > 0:
        score += 15

    # Concentration risk: if a country has very high TEU in few ports
    if ports_in_top100 > 0:
        avg_teu = total_teu / ports_in_top100
        if avg_teu > 20.0:
            score += 25  # Very concentrated (e.g., Singapore)
        elif avg_teu > 10.0:
            score += 15
        elif avg_teu > 5.0:
            score += 10

    # Countries with no major ports also face supply chain risk
    if ports_in_top100 == 0:
        score = 40  # No major port infrastructure

    # Volume dependency - very high volume means more exposure to disruption
    if total_teu > 100.0:
        score += 15  # Extreme volume concentration (China)
    elif total_teu > 20.0:
        score += 10

    score = min(100, max(0, score))

    evidence = [
        f"Ports in top 100: {ports_in_top100} [{resolved}]",
        f"Total container throughput: {total_teu:.1f}M TEU",
    ]

    if congested_ports:
        evidence.append(f"Congestion-prone ports: {', '.join(p['port'] for p in congested_ports)}")

    for p in country_ports[:5]:
        congested_tag = " [CONGESTION RISK]" if p["port"] in HIGH_CONGESTION_PORTS else ""
        evidence.append(f"  #{p['rank']} {p['port']}: {p['teu_millions']:.1f}M TEU{congested_tag}")

    if ports_in_top100 == 0:
        evidence.append(f"NOTE: No ports in global top 100 - limited maritime infrastructure")

    return {
        "ports_in_top100": ports_in_top100,
        "total_teu": total_teu,
        "score": score,
        "evidence": evidence,
    }


if __name__ == "__main__":
    print(f"Total ports in dataset: {len(PORT_RANKINGS)}")
    print(f"\nTop 10:")
    for p in PORT_RANKINGS[:10]:
        print(f"  #{p['rank']} {p['port']} ({p['country']}): {p['teu_millions']:.1f}M TEU")

    print("\n=== Port Importance Scores ===")
    for country in ["China", "Japan", "United States", "Singapore", "Germany"]:
        result = get_port_importance_score(country)
        print(f"\n{country}: score={result['score']}, ports={result['ports_in_top100']}, TEU={result['total_teu']:.1f}M")
        for e in result["evidence"]:
            print(f"  {e}")
