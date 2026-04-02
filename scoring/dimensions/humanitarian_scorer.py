"""第10次元: 人道危機リスクスコアラー (v0.5.1)
ソース差し替え: ReliefWeb (primary) → OCHA FTS 資金ギャップ (primary) + ReliefWeb (補助)

コンポーネント:
  1. ocha_fts_funding_gap (50%): 資金要請に対する未調達率
  2. ocha_fts_active_emergencies (30%): アクティブ緊急事態の数
  3. reliefweb_report_count (20%): 過去30日の緊急レポート数 (既存、補助に格下げ)
"""


def get_humanitarian_score(location: str) -> dict:
    """人道危機リスク総合スコアを算出。

    Args:
        location: 国名または国コード

    Returns:
        {"score": int (0-100), "evidence": list[str]}
    """
    evidence: list[str] = []
    component_scores: list[tuple[float, float]] = []  # (score, weight)

    # --- 1. OCHA FTS 資金ギャップ (50%) ---
    try:
        from pipeline.health.ocha_fts_client import get_humanitarian_indicators
        fts_data = get_humanitarian_indicators(location)
        fts_score = fts_data.get("score", 0)
        evidence.extend(fts_data.get("evidence", []))

        if fts_data.get("source") != "none":
            component_scores.append((fts_score, 0.80))  # FTS は 50%+30% = 80% を占める
    except Exception:
        pass

    # --- 2. ReliefWeb レポート数 (20%) ---
    try:
        from pipeline.health.reliefweb_client import fetch_crisis_reports
        reports = fetch_crisis_reports(country=location, days_back=30, limit=20)
        n_reports = len(reports)
        if n_reports >= 10:
            report_score = 100
        elif n_reports >= 5:
            report_score = 60
        elif n_reports >= 2:
            report_score = 30
        elif n_reports >= 1:
            report_score = 15
        else:
            report_score = 0

        component_scores.append((report_score, 0.20))

        if n_reports > 0:
            evidence.append(f"[ReliefWeb] 直近30日の人道レポート: {n_reports}件")
    except Exception:
        pass

    # --- 総合スコア ---
    if component_scores:
        total_weight = sum(w for _, w in component_scores)
        if total_weight > 0:
            weighted = sum(s * w for s, w in component_scores) / total_weight
            score = int(min(100, weighted))
        else:
            score = 0
    else:
        # 全ソース不達の場合、静的フォールバック
        score = _static_fallback(location)
        if score > 0:
            evidence.append(f"[静的評価] {location}: 人道危機リスク {score}")

    return {"score": score, "evidence": evidence}


def _static_fallback(location: str) -> int:
    """API不到達時の静的フォールバック。"""
    from pipeline.health.reliefweb_client import HUMANITARIAN_RISK_MAP
    location_lower = location.lower()
    for region, risk_score in HUMANITARIAN_RISK_MAP.items():
        if region in location_lower or location_lower in region:
            return risk_score
    return 0
