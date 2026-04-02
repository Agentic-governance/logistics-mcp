"""第23次元: 気候リスクスコアラー
physical_risk x 0.6 + transition_risk x 0.4

Physical risk components:
  - ND-GAIN climate vulnerability (weight 0.4)
  - GloFAS flood forecast (weight 0.3)
  - WRI Aqueduct water risk (weight 0.3)

Transition risk:
  - Climate TRACE emissions / carbon transition risk
"""


def get_climate_risk(location: str) -> dict:
    """気候リスク総合スコアを算出

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
    """
    evidence: list[str] = []
    physical_scores: list[tuple[float, float]] = []  # (score, weight)
    transition_score = 0

    # --- Physical Risk Components ---

    # 1. ND-GAIN Climate Vulnerability (weight 0.4 of physical)
    try:
        from pipeline.climate.ndgain_client import get_climate_vulnerability
        ndgain = get_climate_vulnerability(location)
        ndgain_score = ndgain.get("score", 0)
        physical_scores.append((ndgain_score, 0.4))
        evidence.extend(ndgain.get("evidence", []))
    except Exception as e:
        evidence.append(f"[Climate] ND-GAIN データ取得失敗: {e}")

    # 2. GloFAS Flood Forecast (weight 0.3 of physical)
    try:
        from pipeline.climate.glofas_client import get_flood_forecast
        flood = get_flood_forecast(location)
        flood_score = flood.get("score", 0)
        physical_scores.append((flood_score, 0.3))
        evidence.extend(flood.get("evidence", []))
    except Exception as e:
        evidence.append(f"[Climate] GloFAS データ取得失敗: {e}")

    # 3. WRI Aqueduct Water Risk (weight 0.3 of physical)
    try:
        from pipeline.climate.wri_aqueduct_client import get_water_risk
        water = get_water_risk(location)
        water_score = water.get("score", 0)
        physical_scores.append((water_score, 0.3))
        evidence.extend(water.get("evidence", []))
    except Exception as e:
        evidence.append(f"[Climate] WRI Aqueduct データ取得失敗: {e}")

    # Calculate physical risk (weighted average, normalize weights if partial data)
    if physical_scores:
        total_weight = sum(w for _, w in physical_scores)
        if total_weight > 0:
            physical_risk = sum(s * w for s, w in physical_scores) / total_weight
        else:
            physical_risk = 0
    else:
        physical_risk = 0

    # --- Transition Risk ---

    try:
        from pipeline.climate.climate_trace_client import get_transition_risk
        transition = get_transition_risk(location)
        transition_score = transition.get("score", 0)
        evidence.extend(transition.get("evidence", []))
    except Exception as e:
        evidence.append(f"[Climate] Climate TRACE データ取得失敗: {e}")

    # --- Combined Score ---
    # physical_risk x 0.6 + transition_risk x 0.4
    combined = physical_risk * 0.6 + transition_score * 0.4
    score = min(100, max(0, int(combined)))

    # Summary evidence
    evidence.insert(0,
        f"[Climate Total] {location}: "
        f"物理的リスク={physical_risk:.0f}, "
        f"移行リスク={transition_score}, "
        f"総合={score}/100"
    )

    # Risk level classification
    if score >= 70:
        evidence.append(
            "[Climate] 気候リスクが非常に高い。"
            "サプライチェーンの物理的途絶とカーボン規制の両面で影響"
        )
    elif score >= 45:
        evidence.append(
            "[Climate] 中〜高の気候リスク。"
            "物理的リスクまたは移行リスクへの備えが必要"
        )
    elif score >= 20:
        evidence.append(
            "[Climate] 気候リスクは中程度"
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
        "Bangladesh", "Japan", "China", "India", "Germany",
        "USA", "Vietnam", "Somalia", "Singapore", "Saudi Arabia",
    ]
    print("=" * 70)
    print("Climate Risk Scorer (Dimension 23) Test")
    print("=" * 70)
    for loc in test_locations:
        result = get_climate_risk(loc)
        print(f"\n{'='*40}")
        print(f"{loc}: Score = {result['score']}/100")
        print(f"{'='*40}")
        for e in result["evidence"]:
            print(f"  {e}")
    print("\n" + "=" * 70)
