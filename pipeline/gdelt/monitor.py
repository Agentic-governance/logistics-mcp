"""サプライヤー監視エンジン"""
import json
from datetime import datetime
from dataclasses import dataclass
from .bigquery_client import query_supplier_mentions, query_location_risk, TONE_RISK_THRESHOLD
from pipeline.db import Session, engine
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
from pipeline.db import Base


class RiskAlert(Base):
    """リスクアラートテーブル"""
    __tablename__ = "risk_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(String(100), nullable=False)
    company_name = Column(String(500))
    alert_type = Column(String(50))  # gdelt_negative/sanctions_match/disaster/legal
    severity = Column(String(20))    # critical/high/medium/low
    score = Column(Float)
    title = Column(String(500))
    description = Column(Text)
    source_url = Column(String(1000))
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# CAMEOテーマ → リスクカテゴリマッピング
RISK_THEMES = {
    "LABOR_DISPUTE": ("labor_risk", "high"),
    "SANCTION": ("sanctions_risk", "critical"),
    "PROTEST": ("political_risk", "medium"),
    "NATURAL_DISASTER": ("disaster_risk", "high"),
    "TAX_FRAUD": ("legal_risk", "high"),
    "CORRUPTION": ("legal_risk", "high"),
    "HUMAN_RIGHTS": ("human_rights_risk", "high"),
    "FORCED_LABOR": ("human_rights_risk", "critical"),
    "BANKRUPTCY": ("financial_risk", "critical"),
    "SUPPLY_CHAIN": ("supply_chain_risk", "medium"),
}

# Geopolitical tension baseline (territorial disputes, diplomatic crises, military conflicts)
# Distinct from legal risk: focuses on interstate relations, not domestic rule of law
# Sources: GDELT Conflict Events, ICG CrisisWatch, IISS Armed Conflict Survey
GEO_RISK_BASELINE = {
    "Japan": 25, "United States": 20, "Germany": 8, "United Kingdom": 10, "France": 12,
    "Italy": 5, "Canada": 5, "China": 55, "India": 35, "Russia": 90,
    "Brazil": 5, "South Africa": 10, "Indonesia": 12, "Vietnam": 20, "Thailand": 8,
    "Malaysia": 10, "Singapore": 3, "Philippines": 25, "Myanmar": 65, "Cambodia": 8,
    "Saudi Arabia": 40, "UAE": 15, "Iran": 85, "Iraq": 60, "Turkey": 35,
    "Israel": 75, "Qatar": 15, "Yemen": 80, "South Korea": 30, "Taiwan": 60,
    "North Korea": 95, "Bangladesh": 15, "Pakistan": 50, "Sri Lanka": 12,
    "Nigeria": 35, "Ethiopia": 55, "Kenya": 15, "Egypt": 20, "South Sudan": 70,
    "Somalia": 65, "Ukraine": 95, "Poland": 15, "Netherlands": 5, "Switzerland": 3,
    "Mexico": 15, "Colombia": 20, "Venezuela": 45, "Argentina": 8, "Chile": 5,
    "Australia": 8,
}


def calculate_gdelt_risk_score(mentions: list[dict]) -> tuple[int, list[str]]:
    """
    GDELT言及リストからgeo_risk_scoreを算出。
    根拠エビデンスも返す。
    """
    if not mentions:
        return 0, []

    negative_count = sum(1 for m in mentions if m["tone"] < TONE_RISK_THRESHOLD)
    avg_tone = sum(m["tone"] for m in mentions) / len(mentions)

    # テーマ解析
    risk_themes_found = []
    for mention in mentions:
        themes = mention.get("themes", "").split(";")
        for theme in themes:
            theme_key = theme.strip().split(",")[0]
            if theme_key in RISK_THEMES:
                category, severity = RISK_THEMES[theme_key]
                risk_themes_found.append((category, severity, theme_key))

    # スコア算出
    base_score = min(100, int(negative_count / len(mentions) * 100))
    tone_penalty = max(0, int((-avg_tone - 2) * 5))  # トーンが-2を下回るとペナルティ

    # クリティカルテーマがあれば加点
    critical_themes = [t for t in risk_themes_found if t[1] == "critical"]
    critical_bonus = min(40, len(critical_themes) * 20)

    score = min(100, base_score + tone_penalty + critical_bonus)

    evidence = []
    if negative_count > 0:
        evidence.append(f"直近{len(mentions)}件の報道のうち{negative_count}件がネガティブ評価")
    if avg_tone < -3:
        evidence.append(f"報道トーン平均: {avg_tone:.2f}（著しくネガティブ）")
    for cat, sev, theme in list(set(risk_themes_found))[:5]:
        evidence.append(f"検知テーマ: {theme} -> {cat}（{sev}）")

    return score, evidence


def run_monitoring_job(supplier_id: str, company_name: str, location: str):
    """単一サプライヤーの監視実行"""
    print(f"Monitoring: {company_name} ({location})")

    try:
        # GDELT言及取得
        mentions = query_supplier_mentions(company_name, location, hours_back=24)
        gdelt_score, evidence = calculate_gdelt_risk_score(mentions)

        # 地域リスク
        location_risk = query_location_risk(location, hours_back=168)
        geo_score = location_risk["geo_risk_score"]
    except Exception:
        # BigQuery unavailable - use static geopolitical risk baseline
        gdelt_score = 0
        geo_score = 0
        evidence = []
        for country, baseline in GEO_RISK_BASELINE.items():
            if country.lower() == location.lower() or location.lower() in country.lower() or country.lower() in location.lower():
                geo_score = baseline
                evidence.append(f"[地政学] {country}: 地政学リスクスコア {baseline}/100（GDELTベースライン）")
                break

    combined_score = max(gdelt_score, geo_score)

    if combined_score >= 50:
        severity = "critical" if combined_score >= 80 else "high" if combined_score >= 60 else "medium"

        try:
            alert = RiskAlert(
                supplier_id=supplier_id,
                company_name=company_name,
                alert_type="gdelt_risk",
                severity=severity,
                score=combined_score,
                title=f"{company_name}のリスクスコアが{combined_score}に上昇",
                description="\n".join(evidence),
                source_url=None,
            )

            with Session() as session:
                session.add(alert)
                session.commit()

            print(f"Alert generated: score={combined_score}, severity={severity}")
        except Exception:
            pass

    return {"score": combined_score, "evidence": evidence, "alerts_generated": combined_score >= 50}
