"""一括アセスメント機能"""
import csv
import io
import time
from datetime import datetime
from typing import Optional

def bulk_assess(csv_data: str, assessment_depth: str = "quick") -> dict:
    """
    サプライヤーCSVを一括アセスメント。
    csv_data: CSV文字列。必須カラム: name, country
    assessment_depth: "quick" (制裁+基本スコア) | "full" (全24次元+集中リスク)
    """
    start_time = time.time()
    reader = csv.DictReader(io.StringIO(csv_data))

    results = {"HIGH": [], "MEDIUM": [], "LOW": [], "MINIMAL": []}
    sanctions_hits = []
    all_suppliers = []
    errors = []

    from pipeline.sanctions.screener import screen_entity

    for row in reader:
        name = row.get("name", "").strip()
        country = row.get("country", "").strip()
        if not name:
            continue

        supplier_info = {"name": name, "country": country}

        # Sanctions screening (always)
        try:
            screening = screen_entity(name, country or None)
            if screening.matched:
                sanctions_hits.append({
                    "name": name, "country": country,
                    "match_score": screening.match_score,
                    "source": screening.source,
                })
                supplier_info["sanctions_hit"] = True
        except Exception as e:
            errors.append({"name": name, "error": str(e)})
            continue

        # Risk scoring
        if assessment_depth == "full":
            try:
                from scoring.engine import calculate_risk_score
                score = calculate_risk_score(f"bulk_{name}", name, country=country, location=country)
                d = score.to_dict()
                supplier_info["overall_score"] = d["overall_score"]
                supplier_info["risk_level"] = d["risk_level"]
                supplier_info["top_risks"] = sorted(
                    [(k, v) for k, v in d["scores"].items() if v > 0],
                    key=lambda x: -x[1]
                )[:3]
                results[d["risk_level"]].append(supplier_info)
            except Exception as e:
                errors.append({"name": name, "error": str(e)})
        else:
            # Quick mode: just sanctions + basic classification
            supplier_info["overall_score"] = 100 if supplier_info.get("sanctions_hit") else 0
            supplier_info["risk_level"] = "CRITICAL" if supplier_info.get("sanctions_hit") else "MINIMAL"
            results.get(supplier_info["risk_level"], results["MINIMAL"]).append(supplier_info)

        all_suppliers.append(supplier_info)

    elapsed = time.time() - start_time

    # Concentration analysis if full depth
    concentration = {}
    if assessment_depth == "full" and all_suppliers:
        country_counts = {}
        for s in all_suppliers:
            c = s.get("country", "Unknown")
            country_counts[c] = country_counts.get(c, 0) + 1
        total = len(all_suppliers)
        country_shares = {c: cnt/total for c, cnt in country_counts.items()}
        hhi = sum(s**2 for s in country_shares.values())
        concentration = {
            "hhi": round(hhi, 4),
            "country_distribution": country_counts,
            "concentration_level": "HIGH" if hhi >= 0.25 else "MODERATE" if hhi >= 0.15 else "LOW",
        }

    return {
        "total_suppliers": len(all_suppliers),
        "screened": len(all_suppliers),
        "sanctions_hits": sanctions_hits,
        "risk_summary": {k: len(v) for k, v in results.items()},
        "risk_details": results,
        "concentration_analysis": concentration,
        "errors": errors,
        "assessment_depth": assessment_depth,
        "processing_time_seconds": round(elapsed, 2),
        "timestamp": datetime.utcnow().isoformat(),
    }
