"""労働リスク評価
ILO (国際労働機関) + US DoL ILAB (強制労働リスト)
サプライチェーンにおける労働人権リスク
"""

# US Department of Labor - ILAB Sweat & Toil
# 強制労働・児童労働が確認された品目/国
# Source: https://www.dol.gov/agencies/ilab/reports/child-labor/list-of-goods
FORCED_LABOR_GOODS = {
    "china": ["electronics", "garments", "cotton", "polysilicon", "tomatoes",
              "gloves", "hair products", "nails", "thread", "toys",
              "artificial flowers", "bricks", "christmas decorations",
              "coal", "fireworks", "footwear", "sugarcane"],
    "india": ["garments", "bricks", "carpets", "cotton", "embellished textiles",
              "gems", "rice", "shoes", "silk", "stones", "sugarcane", "tea"],
    "myanmar": ["jade", "rubies", "beans", "rice", "rubber", "sesame",
                "shrimp", "sugarcane", "teak"],
    "vietnam": ["bricks", "cashews", "garments", "leather", "timber"],
    "thailand": ["fish", "garments", "shrimp", "sugarcane", "pornography"],
    "bangladesh": ["bricks", "dried fish", "garments", "leather", "shrimp"],
    "indonesia": ["fish", "gold", "oil palm", "rubber", "tin", "tobacco"],
    "malaysia": ["electronics", "garments", "oil palm", "rubber"],
    "philippines": ["bananas", "coconuts", "fashion accessories", "gold",
                    "hogs", "pyrotechnics", "rice", "rubber", "sugarcane", "tobacco"],
    "pakistan": ["bricks", "carpets", "coal", "cotton", "glass bangles",
                "leather", "surgical instruments", "wheat"],
    "cambodia": ["bricks", "fish", "rubber", "salt", "sugarcane", "timber"],
    "north korea": ["coal", "textiles", "timber"],
    "brazil": ["brazil nuts", "cashews", "cattle", "charcoal", "cocoa",
               "coffee", "cotton", "footwear", "garments", "sugarcane", "timber", "tobacco"],
    "mexico": ["chile peppers", "coffee", "electronics", "garments",
               "pornography", "sugarcane", "tobacco", "tomatoes"],
    "turkey": ["citrus fruits", "cotton", "cumin", "garments", "hazelnuts"],
    "russia": ["timber", "pornography"],
    "nigeria": ["cocoa", "granite", "gravel"],
    "ethiopia": ["coffee", "gold", "opal", "sugarcane", "tea", "tobacco"],
    "ghana": ["cocoa", "fish", "gold", "timber"],
    "egypt": ["cotton", "limestone"],
    "tanzania": ["cloves", "coffee", "gems", "gold", "tea", "tobacco"],
}

# Global Slavery Index 2023 - 推定現代奴隷人口率（per 1000 population）
MODERN_SLAVERY_PREVALENCE = {
    "north korea": 104.6, "eritrea": 90.3, "mauritania": 32.0,
    "saudi arabia": 21.3, "turkey": 15.6, "tajikistan": 14.0,
    "uae": 13.5, "russia": 13.4, "afghanistan": 13.1,
    "kuwait": 13.0, "myanmar": 12.1, "qatar": 11.6,
    "iraq": 10.8, "pakistan": 9.8, "yemen": 9.4,
    "china": 7.8, "iran": 7.6, "india": 7.5, "thailand": 7.1,
    "malaysia": 6.4, "indonesia": 5.2, "vietnam": 5.0,
    "philippines": 4.9, "brazil": 3.7, "mexico": 3.5,
    "south korea": 2.5, "japan": 1.8, "united states": 1.2,
    "germany": 1.0, "australia": 0.8, "united kingdom": 0.8,
}


def get_labor_risk_for_location(location: str) -> dict:
    """労働リスク評価"""
    loc = location.lower().strip()
    score = 0
    evidence = []

    # 強制労働品目チェック
    for country, goods in FORCED_LABOR_GOODS.items():
        if country in loc or loc in country:
            score = max(score, min(80, 30 + len(goods) * 3))
            evidence.append(
                f"[DoL/ILAB] {location}: 強制労働・児童労働リスク品目 {len(goods)}件 "
                f"({', '.join(goods[:5])}{'...' if len(goods) > 5 else ''})"
            )
            break

    # 現代奴隷指数
    for country, prevalence in MODERN_SLAVERY_PREVALENCE.items():
        if country in loc or loc in country:
            if prevalence > 20:
                score = max(score, 85)
            elif prevalence > 10:
                score = max(score, 65)
            elif prevalence > 5:
                score = max(score, 45)
            elif prevalence > 2:
                score = max(score, 25)
            evidence.append(f"[GSI] 現代奴隷推定率: {prevalence}/1000人")
            break

    return {"score": min(100, score), "evidence": evidence}
