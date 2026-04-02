"""第24次元: サイバーリスクスコアラー
internet_disruption x 0.5 + (1-infrastructure_maturity) x 0.3 + vulnerability_exposure x 0.2

Components:
  - Internet disruption/censorship: OONI + existing internet_client (weight 0.5)
  - Infrastructure maturity (inverted): ITU ICT Development Index (weight 0.3)
  - Vulnerability exposure: CISA KEV global indicator (weight 0.2)
"""


def get_cyber_risk(location: str) -> dict:
    """サイバーリスク総合スコアを算出

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
    """
    evidence: list[str] = []
    disruption_score = 0
    maturity_risk_score = 0
    vulnerability_score = 0

    # --- 1. Internet Disruption / Censorship (weight 0.5) ---
    # Combine OONI censorship with existing internet infrastructure risk
    disruption_components: list[tuple[float, float]] = []

    # OONI censorship
    try:
        from pipeline.cyber.ooni_client import get_internet_censorship_score
        ooni = get_internet_censorship_score(location)
        ooni_score = ooni.get("score", 0)
        disruption_components.append((ooni_score, 0.6))
        evidence.extend(ooni.get("evidence", []))
    except Exception as e:
        evidence.append(f"[Cyber] OONI データ取得失敗: {e}")

    # Existing internet infrastructure client
    try:
        from pipeline.infrastructure.internet_client import get_internet_risk_for_location
        internet = get_internet_risk_for_location(location)
        internet_score = internet.get("score", 0)
        disruption_components.append((internet_score, 0.4))
        evidence.extend(internet.get("evidence", []))
    except Exception as e:
        evidence.append(f"[Cyber] Internet infrastructure データ取得失敗: {e}")

    # Calculate disruption score
    if disruption_components:
        total_w = sum(w for _, w in disruption_components)
        if total_w > 0:
            disruption_score = sum(s * w for s, w in disruption_components) / total_w
        else:
            disruption_score = 0
    else:
        disruption_score = 0

    # --- 2. Infrastructure Maturity (weight 0.3) ---
    # ITU ICT Development Index (already inverted: low IDI = high risk)
    try:
        from pipeline.cyber.itu_ict_client import get_ict_maturity
        ict = get_ict_maturity(location)
        maturity_risk_score = ict.get("score", 50)  # Already inverted
        evidence.extend(ict.get("evidence", []))
    except Exception as e:
        maturity_risk_score = 50
        evidence.append(f"[Cyber] ITU ICT データ取得失敗: {e}")

    # --- 3. Vulnerability Exposure (weight 0.2) ---
    # CISA KEV is a global indicator; apply as baseline
    try:
        from pipeline.cyber.cisa_kev_client import get_kev_stats
        kev = get_kev_stats(days_back=30)
        vulnerability_score = kev.get("score", 20)
        evidence.extend(kev.get("evidence", []))
    except Exception as e:
        vulnerability_score = 20
        evidence.append(f"[Cyber] CISA KEV データ取得失敗: {e}")

    # --- Combined Score ---
    # disruption * 0.5 + maturity_risk * 0.3 + vulnerability * 0.2
    combined = (
        disruption_score * 0.5
        + maturity_risk_score * 0.3
        + vulnerability_score * 0.2
    )
    score = min(100, max(0, int(combined)))

    # Summary evidence
    evidence.insert(0,
        f"[Cyber Total] {location}: "
        f"通信途絶={disruption_score:.0f}, "
        f"インフラ未成熟={maturity_risk_score}, "
        f"脆弱性露出={vulnerability_score}, "
        f"総合={score}/100"
    )

    # Risk level classification
    if score >= 70:
        evidence.append(
            "[Cyber] サイバーリスクが非常に高い。"
            "インターネット遮断・検閲、インフラ未整備、"
            "脆弱性悪用のリスクが複合的に存在"
        )
    elif score >= 45:
        evidence.append(
            "[Cyber] 中〜高のサイバーリスク。"
            "通信インフラの信頼性やセキュリティ対応に注意"
        )
    elif score >= 20:
        evidence.append(
            "[Cyber] サイバーリスクは中程度"
        )

    return {"score": score, "evidence": evidence}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import os
    # Add project root to path for imports
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    test_locations = [
        "China", "Iran", "Japan", "Germany", "USA",
        "Myanmar", "Russia", "India", "Singapore", "Bangladesh",
    ]
    print("=" * 70)
    print("Cyber Risk Scorer (Dimension 24) Test")
    print("=" * 70)
    for loc in test_locations:
        result = get_cyber_risk(loc)
        print(f"\n{'='*40}")
        print(f"{loc}: Score = {result['score']}/100")
        print(f"{'='*40}")
        for e in result["evidence"]:
            print(f"  {e}")
    print("\n" + "=" * 70)
