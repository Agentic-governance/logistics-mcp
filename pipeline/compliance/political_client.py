"""政治リスク評価
Freedom House
静的データ
"""

# Freedom House: Freedom in the World 2025
# Scale: F=Not Free, PF=Partly Free, Free
# Score: 0-100 (100=most free)
FREEDOM_HOUSE = {
    "japan": 96, "south korea": 83, "taiwan": 94, "united states": 83,
    "germany": 94, "france": 89, "united kingdom": 93, "australia": 95,
    "canada": 97, "new zealand": 99, "singapore": 47, "malaysia": 50,
    "thailand": 29, "indonesia": 58, "philippines": 55, "india": 66,
    "vietnam": 19, "china": 9, "myanmar": 9, "north korea": 3,
    "russia": 13, "turkey": 32, "saudi arabia": 7, "uae": 17,
    "egypt": 18, "iran": 12, "iraq": 29, "syria": 1, "yemen": 9,
    "afghanistan": 8, "pakistan": 35, "bangladesh": 39, "nepal": 56,
    "sri lanka": 55, "cambodia": 24, "laos": 12,
    "brazil": 73, "mexico": 60, "colombia": 63, "venezuela": 14,
    "nigeria": 43, "south africa": 79, "kenya": 48, "ethiopia": 22,
    "sudan": 4, "south sudan": 2, "somalia": 7, "haiti": 32,
    "ukraine": 50, "poland": 81, "hungary": 66,
    "israel": 74, "palestine": 26, "lebanon": 42, "jordan": 33,
}


def get_political_risk_for_location(location: str) -> dict:
    """政治リスク評価（Freedom House）"""
    loc = location.lower().strip()
    score = 0
    evidence = []

    # Freedom House
    for country, fh_score in FREEDOM_HOUSE.items():
        if country in loc or loc in country:
            # FHスコアを逆転 (低FH = 高リスク)
            political_risk = 100 - fh_score
            score = max(score, int(political_risk * 0.85))  # 重み85%
            status = "Not Free" if fh_score < 35 else "Partly Free" if fh_score < 70 else "Free"
            evidence.append(f"[Freedom House] {location}: {fh_score}/100 ({status})")
            break

    return {"score": min(100, int(score)), "evidence": evidence}
