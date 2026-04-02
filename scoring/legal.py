"""Caselaw MCP連携 + 行政処分スクレイピング + WJP Rule of Law Index"""
import requests
import json

CASELAW_MCP_URL = "https://caselaw.patent-space.dev/mcp"

# 行政処分の重要度マッピング
ADMIN_PENALTY_WEIGHT = {
    "公正取引委員会": 80,  # 独禁法違反は重大
    "金融庁": 75,
    "厚生労働省": 70,  # 強制労働・労働基準法
    "経済産業省": 65,
    "環境省": 60,
}

# 検索すべき法令・キーワード（日英）
RISK_KEYWORDS_EN = [
    "forced labor", "human trafficking", "sanctions violation",
    "export control", "bribery", "corruption", "antitrust"
]
RISK_KEYWORDS_JA = [
    "強制労働", "人身取引", "制裁違反", "輸出規制違反",
    "贈収賄", "独占禁止法", "不正競争"
]

# Legal/regulatory risk baseline (WJP Rule of Law Index 2023 + IP protection)
# Focuses on: contract enforcement, IP protection, judicial independence, regulatory quality
# Distinct from geo_risk: domestic legal framework quality, not interstate tensions
LEGAL_RISK_BASELINE = {
    "Japan": 10, "United States": 15, "Germany": 8, "United Kingdom": 8, "France": 12,
    "Italy": 20, "Canada": 8, "China": 55, "India": 45, "Russia": 60,
    "Brazil": 42, "South Africa": 38, "Indonesia": 45, "Vietnam": 52, "Thailand": 40,
    "Malaysia": 32, "Singapore": 5, "Philippines": 48, "Myanmar": 72, "Cambodia": 62,
    "Saudi Arabia": 35, "UAE": 22, "Iran": 65, "Iraq": 68, "Turkey": 50,
    "Israel": 18, "Qatar": 25, "Yemen": 78, "South Korea": 12, "Taiwan": 10,
    "North Korea": 85, "Bangladesh": 58, "Pakistan": 60, "Sri Lanka": 45,
    "Nigeria": 62, "Ethiopia": 58, "Kenya": 50, "Egypt": 55, "South Sudan": 80,
    "Somalia": 88, "Ukraine": 52, "Poland": 18, "Netherlands": 6, "Switzerland": 4,
    "Mexico": 55, "Colombia": 48, "Venezuela": 75, "Argentina": 38, "Chile": 14,
    "Australia": 8,
}


_caselaw_available = None  # cached connectivity status

def call_caselaw_mcp(tool: str, params: dict) -> dict:
    """Caselaw MCPツール呼び出し（DNS失敗時はセッション中スキップ）"""
    global _caselaw_available
    if _caselaw_available is False:
        return {}

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool, "arguments": params},
        "id": 1
    }
    try:
        resp = requests.post(
            f"{CASELAW_MCP_URL}/messages",
            json=payload, timeout=5
        )
        _caselaw_available = True
        data = resp.json()
        return data.get("result", {})
    except Exception:
        _caselaw_available = False
        return {}


def _get_blended_baseline(country: str) -> tuple[int, list[str]]:
    """Blend LEGAL_RISK_BASELINE with WJP Rule of Law Index for richer scoring.

    Combines the existing static baseline (60% weight) with the WJP index (40%)
    when available. This improves data coverage and cross-validates both sources.
    """
    evidence = []
    baseline_score = None
    wjp_score = None

    # 1. Existing baseline lookup
    lookup = country or ""
    matched_country = None
    for c, val in LEGAL_RISK_BASELINE.items():
        if c.lower() == lookup.lower() or lookup.lower() in c.lower() or c.lower() in lookup.lower():
            baseline_score = val
            matched_country = c
            break

    # 2. WJP Rule of Law Index lookup
    try:
        from pipeline.compliance.wjp_client import get_rule_of_law_score
        wjp_result = get_rule_of_law_score(lookup)
        if wjp_result["score"] > 0 or wjp_result["evidence"]:
            wjp_score = wjp_result["score"]
            evidence.extend(wjp_result["evidence"])
    except Exception:
        pass

    # 3. Blend scores
    if baseline_score is not None and wjp_score is not None:
        # Weighted blend: existing baseline 60%, WJP 40%
        blended = int(baseline_score * 0.6 + wjp_score * 0.4)
        evidence.insert(0, f"[法的] {matched_country}: ベースライン {baseline_score}/100 + WJP {wjp_score}/100 -> ブレンド {blended}/100")
        return blended, evidence
    elif baseline_score is not None:
        evidence.append(f"[法的] {matched_country}: 法的環境リスクスコア {baseline_score}/100（Rule of Law Index ベースライン）")
        return baseline_score, evidence
    elif wjp_score is not None:
        # WJP data available but no existing baseline
        return wjp_score, evidence
    else:
        return 0, evidence


def get_legal_score(company_name: str, country: str = None) -> tuple[int, list[str]]:
    """企業の訴訟・行政処分リスクスコアを取得"""
    evidence = []
    score = 0

    # 英語キーワードで検索
    for keyword in RISK_KEYWORDS_EN[:3]:  # 最初の3キーワードのみ（APIコスト削減）
        result = call_caselaw_mcp("search_cases", {
            "query": f'"{company_name}" {keyword}',
            "jurisdiction": country or "US",
            "limit": 5,
        })

        cases = result.get("cases", [])
        if cases:
            score += min(30, len(cases) * 10)
            evidence.append(
                f"関連訴訟: '{keyword}'で{len(cases)}件のケースヒット"
            )
            # 直近の判例を証拠として追加
            for case in cases[:2]:
                evidence.append(
                    f"  - {case.get('name', '')}) ({case.get('date', '')}) "
                    f"[{case.get('jurisdiction', '')}]"
                )

    # 日本語: 行政処分公表DBを直接スクレイピング
    admin_result = check_admin_penalties_japan(company_name)
    if admin_result["found"]:
        score += admin_result["max_weight"]
        evidence.extend(admin_result["evidence"])

    # If no data from MCP, use blended country baseline (existing + WJP)
    if score == 0 and not evidence:
        blended_score, blended_evidence = _get_blended_baseline(country)
        score = blended_score
        evidence.extend(blended_evidence)

    return min(100, score), evidence


def check_admin_penalties_japan(company_name: str) -> dict:
    """
    日本の行政処分公表データベースを確認。
    公取委・金融庁・厚労省の公表情報をスクレイピング。
    """
    found = False
    max_weight = 0
    evidence = []

    # 公正取引委員会: https://www.jftc.go.jp/shinketsu/index.html
    # 金融庁: https://www.fsa.go.jp/news/
    # 厚生労働省: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/

    # TODO: 各省庁サイトのスクレイピング実装
    # 現在は企業名検索APIが存在しないため、定期クロール+全文検索が現実的
    # Day 4では基本構造のみ実装し、クローラーはDay 5と並行で追加

    return {"found": found, "max_weight": max_weight, "evidence": evidence}
