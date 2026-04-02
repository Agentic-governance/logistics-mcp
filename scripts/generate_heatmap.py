"""Generate 50-country x 24-dimension risk heatmap as CSV"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from config.constants import PRIORITY_COUNTRIES
from scoring.engine import calculate_risk_score, SupplierRiskScore

DIMENSIONS = list(SupplierRiskScore.WEIGHTS.keys()) + ["sanctions", "japan_economy"]

def generate_heatmap():
    results = []
    for country in PRIORITY_COUNTRIES:
        try:
            score = calculate_risk_score(f"hm_{country}", country, country=country, location=country)
            d = score.to_dict()
            row = {"country": country, "overall": d["overall_score"]}
            for dim in DIMENSIONS:
                row[dim] = d["scores"].get(dim, 0)
            results.append(row)
        except Exception as e:
            print(f"Failed: {country}: {e}")

    # Sort by overall score descending
    results.sort(key=lambda x: -x["overall"])

    # Write CSV
    os.makedirs("reports", exist_ok=True)
    with open("reports/risk_heatmap.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["country", "overall"] + sorted(DIMENSIONS))
        writer.writeheader()
        writer.writerows(results)

    print(f"Heatmap CSV written: {len(results)} countries x {len(DIMENSIONS)} dimensions")
    return results

if __name__ == "__main__":
    generate_heatmap()
