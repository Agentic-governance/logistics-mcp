"""KYSデューデリジェンスレポート自動生成
制裁スクリーニング + 24次元リスクスコア + EDD判定を統合
"""
from datetime import datetime
from typing import Optional

class DueDiligenceReportGenerator:
    """デューデリジェンスレポート生成"""

    def generate_report(self, entity_name: str, country: str,
                       report_format: str = "json", edd_depth: str = "standard") -> dict:
        """統合DDレポート生成"""
        timestamp = datetime.utcnow().isoformat()

        # 1. Sanctions screening
        screening_result = {}
        try:
            from pipeline.sanctions.screener import screen_entity
            result = screen_entity(entity_name, country)
            screening_result = {
                "matched": result.matched,
                "match_score": result.match_score,
                "matched_entity": result.matched_entity,
                "source": result.source,
                "evidence": result.evidence,
            }
        except Exception as e:
            screening_result = {"error": str(e)}

        # 2. Risk scoring (24 dimensions)
        risk_scores = {}
        try:
            from scoring.engine import calculate_risk_score
            score = calculate_risk_score(f"dd_{entity_name}", entity_name,
                                        country=country, location=country)
            risk_scores = score.to_dict()
        except Exception as e:
            risk_scores = {"error": str(e)}

        # 3. EDD trigger assessment
        edd_recommended = False
        edd_triggers = []

        if screening_result.get("matched"):
            edd_recommended = True
            edd_triggers.append("制裁リストにヒット")

        overall = risk_scores.get("overall_score", 0)
        if overall >= 60:
            edd_recommended = True
            edd_triggers.append(f"総合リスクスコア {overall} >= 60")

        scores = risk_scores.get("scores", {})
        if scores.get("compliance", 0) >= 70:
            edd_recommended = True
            edd_triggers.append(f"コンプライアンスリスク {scores['compliance']} >= 70")

        if scores.get("labor", 0) >= 70:
            edd_triggers.append(f"労働リスク {scores['labor']} >= 70 (強制労働疑い)")

        # 4. Data source confidence
        evidence_count = len(risk_scores.get("evidence", []))
        data_sources_used = set()
        for e in risk_scores.get("evidence", []):
            if isinstance(e, dict):
                data_sources_used.add(e.get("source", "unknown"))
            elif isinstance(e, str) and "[" in e:
                source = e.split("]")[0].replace("[", "").strip()
                data_sources_used.add(source)

        confidence = min(1.0, evidence_count / 20)  # 20+ evidence items = full confidence

        report = {
            "entity": {
                "name": entity_name,
                "country": country,
            },
            "screening_result": screening_result,
            "risk_scores": risk_scores,
            "edd_recommended": edd_recommended,
            "edd_triggers": edd_triggers,
            "edd_depth": edd_depth,
            "data_sources": list(data_sources_used),
            "data_sources_count": len(data_sources_used),
            "evidence_count": evidence_count,
            "confidence_level": round(confidence, 2),
            "risk_summary": {
                "overall_score": overall,
                "risk_level": risk_scores.get("risk_level", "UNKNOWN"),
                "top_risks": sorted(
                    [(k, v) for k, v in scores.items() if v > 0],
                    key=lambda x: -x[1]
                )[:5],
            },
            "generated_at": timestamp,
            "report_format": report_format,
            "version": "0.9.0",
        }

        return report
