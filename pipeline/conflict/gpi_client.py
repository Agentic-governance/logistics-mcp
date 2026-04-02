"""Global Peace Index (GPI) - Peace and Conflict Assessment
Static dataset of GPI 2024 scores for 163 countries.
GPI scores range from 1.0 (most peaceful) to 4.0 (least peaceful).
Source: Institute for Economics and Peace, Global Peace Index 2024
https://www.visionofhumanity.org/maps/
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# GPI 2024 scores: country -> score
# 1.0 = most peaceful, 4.0 = least peaceful
# Source: Global Peace Index 2024 Report (Institute for Economics & Peace)
PEACE_INDEX = {
    "Iceland": 1.124,
    "Ireland": 1.290,
    "Austria": 1.300,
    "New Zealand": 1.315,
    "Singapore": 1.326,
    "Switzerland": 1.339,
    "Portugal": 1.341,
    "Denmark": 1.353,
    "Slovenia": 1.369,
    "Malaysia": 1.384,
    "Czech Republic": 1.387,
    "Finland": 1.399,
    "Japan": 1.405,
    "Croatia": 1.410,
    "Canada": 1.413,
    "Hungary": 1.419,
    "Mauritius": 1.427,
    "Australia": 1.461,
    "Germany": 1.463,
    "Norway": 1.469,
    "Romania": 1.472,
    "Estonia": 1.477,
    "Bhutan": 1.481,
    "Slovakia": 1.488,
    "Netherlands": 1.497,
    "Sweden": 1.513,
    "Belgium": 1.523,
    "Lithuania": 1.536,
    "Poland": 1.544,
    "Latvia": 1.545,
    "Botswana": 1.548,
    "Ghana": 1.559,
    "Bulgaria": 1.567,
    "Taiwan": 1.575,
    "Italy": 1.586,
    "Spain": 1.603,
    "Mongolia": 1.611,
    "Laos": 1.613,
    "Uruguay": 1.625,
    "Vietnam": 1.633,
    "Kuwait": 1.638,
    "South Korea": 1.642,
    "Costa Rica": 1.647,
    "Chile": 1.655,
    "Albania": 1.660,
    "Panama": 1.671,
    "Sierra Leone": 1.678,
    "United Kingdom": 1.680,
    "Qatar": 1.685,
    "Timor-Leste": 1.690,
    "Zambia": 1.696,
    "Jordan": 1.699,
    "Namibia": 1.703,
    "Tanzania": 1.716,
    "Serbia": 1.721,
    "United Arab Emirates": 1.724,
    "Senegal": 1.730,
    "Montenegro": 1.738,
    "Tunisia": 1.741,
    "Oman": 1.745,
    "Madagascar": 1.749,
    "Indonesia": 1.752,
    "North Macedonia": 1.756,
    "Gambia": 1.760,
    "Greece": 1.763,
    "Equatorial Guinea": 1.770,
    "Nepal": 1.775,
    "France": 1.793,
    "Malawi": 1.798,
    "Rwanda": 1.803,
    "Togo": 1.808,
    "Georgia": 1.812,
    "Bosnia and Herzegovina": 1.817,
    "Bolivia": 1.826,
    "Argentina": 1.834,
    "Cuba": 1.838,
    "Tajikistan": 1.844,
    "Ivory Coast": 1.850,
    "Peru": 1.858,
    "Morocco": 1.862,
    "Benin": 1.868,
    "Angola": 1.876,
    "Sri Lanka": 1.878,
    "Kazakhstan": 1.886,
    "Jamaica": 1.893,
    "Paraguay": 1.898,
    "Eswatini": 1.906,
    "Mongolia": 1.611,
    "Dominican Republic": 1.910,
    "Turkmenistan": 1.915,
    "Haiti": 1.924,
    "Uzbekistan": 1.930,
    "Ecuador": 1.939,
    "Papua New Guinea": 1.946,
    "Guyana": 1.950,
    "Thailand": 1.955,
    "Trinidad and Tobago": 1.960,
    "China": 1.977,
    "Guinea": 1.982,
    "Bangladesh": 1.990,
    "Honduras": 2.004,
    "Bahrain": 2.011,
    "Djibouti": 2.019,
    "Zimbabwe": 2.026,
    "Guatemala": 2.035,
    "Kyrgyzstan": 2.040,
    "Azerbaijan": 2.049,
    "Egypt": 2.058,
    "Cambodia": 2.065,
    "Philippines": 2.073,
    "Iran": 2.088,
    "Belarus": 2.094,
    "Gabon": 2.098,
    "Mauritania": 2.103,
    "Kenya": 2.111,
    "Mozambique": 2.119,
    "United States": 2.126,
    "El Salvador": 2.131,
    "Ethiopia": 2.140,
    "South Africa": 2.148,
    "Uganda": 2.155,
    "Eritrea": 2.164,
    "Algeria": 2.173,
    "Chad": 2.184,
    "Burundi": 2.193,
    "Niger": 2.201,
    "India": 2.213,
    "Saudi Arabia": 2.228,
    "Turkey": 2.239,
    "Cameroon": 2.247,
    "Libya": 2.259,
    "Lebanon": 2.268,
    "Central African Republic": 2.283,
    "Colombia": 2.293,
    "Venezuela": 2.310,
    "Congo Republic": 2.318,
    "North Korea": 2.326,
    "Palestine": 2.339,
    "Mexico": 2.355,
    "Myanmar": 2.405,
    "Brazil": 2.416,
    "Burkina Faso": 2.432,
    "Mali": 2.451,
    "Pakistan": 2.481,
    "Nigeria": 2.498,
    "Democratic Republic of Congo": 2.524,
    "Israel": 2.592,
    "Iraq": 2.656,
    "Somalia": 2.718,
    "South Sudan": 2.884,
    "Russia": 2.963,
    "Sudan": 3.025,
    "Syria": 3.129,
    "Afghanistan": 3.448,
    "Yemen": 3.350,
    "Ukraine": 3.377,
}

# Country name normalization
COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom",
    "korea": "South Korea", "republic of korea": "South Korea",
    "uae": "United Arab Emirates",
    "drc": "Democratic Republic of Congo",
    "car": "Central African Republic",
    "cote d'ivoire": "Ivory Coast",
    "ivory coast": "Ivory Coast",
    "north korea": "North Korea", "dprk": "North Korea",
    "czechia": "Czech Republic",
    "east timor": "Timor-Leste",
    "cape verde": "Cabo Verde",
}


def _resolve_country(country: str) -> str:
    """Resolve country name to standard form."""
    lower = country.lower().strip()
    if lower in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[lower]
    for name in PEACE_INDEX:
        if name.lower() == lower:
            return name
    for name in PEACE_INDEX:
        if lower in name.lower() or name.lower() in lower:
            return name
    return country


def _gpi_to_category(gpi_score: float) -> str:
    """Map GPI score to peace category."""
    if gpi_score < 1.5:
        return "Very High Peace"
    elif gpi_score < 2.0:
        return "High Peace"
    elif gpi_score < 2.5:
        return "Medium Peace"
    elif gpi_score < 3.0:
        return "Low Peace"
    else:
        return "Very Low Peace"


def _gpi_to_risk_score(gpi_score: float) -> int:
    """Map GPI score (1.0-4.0) to risk score (0-100)."""
    # Linear mapping: 1.0 -> 0, 4.0 -> 100
    risk = (gpi_score - 1.0) / 3.0 * 100.0
    return min(100, max(0, int(risk)))


def _get_rank(country_name: str) -> int:
    """Get the GPI rank of a country (1 = most peaceful)."""
    sorted_countries = sorted(PEACE_INDEX.items(), key=lambda x: x[1])
    for i, (name, _) in enumerate(sorted_countries, 1):
        if name == country_name:
            return i
    return 0


def get_peace_index(country: str) -> dict:
    """Get Global Peace Index data for a country.

    Args:
        country: Country name (e.g., 'Japan', 'United States')

    Returns:
        dict with keys: gpi_score, rank, category, score (0-100), evidence (list of str)
    """
    resolved = _resolve_country(country)
    gpi_score = PEACE_INDEX.get(resolved)

    if gpi_score is None:
        return {
            "gpi_score": None,
            "rank": None,
            "category": "Unknown",
            "score": 0,
            "evidence": [f"No GPI data available for '{country}'"],
        }

    rank = _get_rank(resolved)
    category = _gpi_to_category(gpi_score)
    score = _gpi_to_risk_score(gpi_score)
    total_countries = len(PEACE_INDEX)

    evidence = [
        f"Global Peace Index: {gpi_score:.3f} (rank {rank}/{total_countries}) [GPI 2024]",
        f"Peace category: {category}",
    ]

    if category == "Very Low Peace":
        evidence.append("WARNING: Country is among the least peaceful globally - elevated conflict/instability risk")
    elif category == "Low Peace":
        evidence.append("NOTE: Significant peace and security concerns present")

    return {
        "gpi_score": gpi_score,
        "rank": rank,
        "category": category,
        "score": score,
        "evidence": evidence,
    }


def get_top_risks(n: int = 20) -> list[dict]:
    """Get the N least peaceful countries."""
    sorted_countries = sorted(PEACE_INDEX.items(), key=lambda x: x[1], reverse=True)
    results = []
    for i, (name, gpi_score) in enumerate(sorted_countries[:n]):
        results.append({
            "country": name,
            "gpi_score": gpi_score,
            "category": _gpi_to_category(gpi_score),
            "risk_score": _gpi_to_risk_score(gpi_score),
        })
    return results


if __name__ == "__main__":
    for country in ["Japan", "Iceland", "United States", "Ukraine", "Afghanistan", "Yemen"]:
        result = get_peace_index(country)
        print(f"\n{country}: score={result['score']}, GPI={result['gpi_score']}, rank={result['rank']}")
        for e in result["evidence"]:
            print(f"  {e}")
