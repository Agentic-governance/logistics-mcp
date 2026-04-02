"""FATF Grey/Black List + TI CPI
マネーロンダリング・テロ資金供与リスク評価
APIキー不要
"""

# FATF High-Risk Jurisdictions (Black List) - 2025/2026
# 更新頻度: 年3回 (2/6/10月)
FATF_BLACK_LIST = {
    "iran", "north korea", "dprk", "myanmar",
}

# FATF Increased Monitoring (Grey List) - 2025/2026
FATF_GREY_LIST = {
    "algeria", "angola", "bulgaria", "burkina faso", "cameroon",
    "cote d'ivoire", "ivory coast", "croatia", "democratic republic of congo",
    "drc", "haiti", "kenya", "lebanon", "mali", "monaco", "mozambique",
    "namibia", "nepal", "nigeria", "south africa", "south sudan",
    "syria", "tanzania", "venezuela", "vietnam", "yemen",
}

# Transparency International CPI 2024 (抜粋 0-100, 高い=クリーン)
TI_CPI = {
    "denmark": 90, "finland": 87, "new zealand": 85, "norway": 84,
    "singapore": 83, "sweden": 82, "switzerland": 82,
    "germany": 78, "united kingdom": 71, "japan": 73, "usa": 65,
    "taiwan": 68, "south korea": 63, "malaysia": 50, "china": 42,
    "india": 39, "vietnam": 41, "indonesia": 34, "thailand": 36,
    "philippines": 34, "bangladesh": 27, "myanmar": 20, "pakistan": 29,
    "russia": 26, "nigeria": 25, "iran": 24, "iraq": 23,
    "north korea": 17, "somalia": 11, "south sudan": 13, "syria": 13,
    "yemen": 16, "haiti": 17, "libya": 18, "sudan": 11,
    "afghanistan": 20, "turkey": 34, "brazil": 36, "mexico": 31,
    "egypt": 30, "south africa": 41, "saudi arabia": 52, "uae": 68,
    "australia": 75, "canada": 76, "france": 71, "italy": 56,
}


def get_compliance_risk_for_location(location: str) -> dict:
    """コンプライアンスリスク評価（FATF + TI CPI）"""
    loc = location.lower().strip()
    score = 0
    evidence = []

    # FATF Black List (最高リスク)
    for country in FATF_BLACK_LIST:
        if country in loc or loc in country:
            score = max(score, 95)
            evidence.append(f"[FATF] {location}はFATFブラックリスト（高リスク管轄区域）")
            break

    # FATF Grey List
    if score < 95:
        for country in FATF_GREY_LIST:
            if country in loc or loc in country:
                score = max(score, 60)
                evidence.append(f"[FATF] {location}はFATFグレーリスト（強化モニタリング対象）")
                break

    # Transparency International CPI (increased weight since INFORM removed)
    for country, cpi in TI_CPI.items():
        if country in loc or loc in country:
            corruption_score = 100 - cpi  # CPI逆転: 低CPI = 高リスク
            score = max(score, int(corruption_score * 0.7))  # 重み70%
            evidence.append(f"[TI CPI] 腐敗認識指数: {cpi}/100 (高い=クリーン)")
            break

    return {"score": min(100, score), "evidence": evidence}
