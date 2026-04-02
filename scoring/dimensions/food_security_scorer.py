"""第14次元: 食料安全保障スコアラー (v0.5.1)
ソース差し替え: WFP HungerMap (primary) → FEWS NET IPC Phase (primary) + WFP (補助)

FEWS NET カバレッジに応じてロジックを切り替える:
  対象国 (主にアフリカ・中東・南アジア):
    score = ipc_score*0.60 + price_alert_score*0.25 + wfp_score*0.15
  非対象国 (日本・ドイツ等):
    score = wfp_score  # 既存ロジック継続
"""


def get_food_security_score(location: str) -> dict:
    """食料安全保障リスクスコアを算出。

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
    """
    evidence: list[str] = []

    # --- FEWS NET チェック ---
    fews_result = None
    try:
        from pipeline.food.fews_net_client import get_food_security_indicators
        fews_result = get_food_security_indicators(location)
    except Exception:
        pass

    if fews_result is not None:
        # FEWS NET カバレッジ対象国
        fews_score = fews_result["score"]
        evidence.extend(fews_result.get("evidence", []))

        # WFP 補助分 (15%)
        wfp_score = _get_wfp_score(location)
        if wfp_score > 0:
            evidence.append(f"[WFP 補助] 食料不安定スコア: {wfp_score}")

        # FEWS NET(85%) + WFP(15%) の加重平均
        total_score = int(fews_score * 0.85 + wfp_score * 0.15)
        return {"score": min(100, total_score), "evidence": evidence}

    # --- 非対象国: WFP のみ ---
    wfp_score = _get_wfp_score(location)
    wfp_evidence = _get_wfp_evidence(location)
    evidence.extend(wfp_evidence)

    return {"score": wfp_score, "evidence": evidence}


def _get_wfp_score(location: str) -> int:
    """WFP HungerMap からスコアを取得。"""
    try:
        from pipeline.food.wfp_client import get_food_security_risk
        result = get_food_security_risk(location)
        return result.get("score", 0)
    except Exception:
        return 0


def _get_wfp_evidence(location: str) -> list[str]:
    """WFP HungerMap からエビデンスを取得。"""
    try:
        from pipeline.food.wfp_client import get_food_security_risk
        result = get_food_security_risk(location)
        return result.get("evidence", [])
    except Exception:
        return []
