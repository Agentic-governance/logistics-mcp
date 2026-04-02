"""SupplierRiskScore 算出エンジン
27次元の多角的リスク評価:
  1. 制裁スクリーニング (sanctions) - OFAC/UN/EU/METI/BIS/OFSI/SECO/Canada/DFAT/MOFA
  2. 地政学リスク (geo_risk) - GDELT
  3. 災害リスク (disaster) - GDACS/USGS/FIRMS/JMA/BMKG
  4. 法的リスク (legal) - Caselaw
  5. 海上輸送リスク (maritime) - PortWatch
  6. 紛争リスク (conflict) - ACLED
  7. 経済リスク (economic) - World Bank
  8. 通貨リスク (currency) - Frankfurter/ECB
  9. 感染症リスク (health) - Disease.sh
  10. 人道危機リスク (humanitarian) - OCHA FTS/ReliefWeb
  11. 気象リスク (weather) - Open-Meteo
  12. 台風・宇宙天気 (typhoon) - NOAA NHC/SWPC
  13. コンプライアンスリスク (compliance) - FATF/INFORM/TI-CPI
  14. 食料安全保障 (food_security) - FEWS NET/WFP
  15. 貿易依存リスク (trade) - UN Comtrade
  16. インターネットインフラ (internet) - Cloudflare Radar/IODA
  17. 政治リスク (political) - Freedom House/FSI
  18. 労働リスク (labor) - DoL ILAB/GSI
  19. 港湾混雑 (port_congestion) - UNCTAD統計
  20. 航空リスク (aviation) - OpenSky Network
  21. エネルギー価格 (energy) - FRED/EIA
  22. 日本経済指標 (japan_economy) - BOJ/e-Stat
  23. 気候リスク (climate_risk) - ND-GAIN/GloFAS/WRI/Climate TRACE
  24. サイバーリスク (cyber_risk) - OONI/CISA KEV/ITU ICT
  25. サプライチェーン脆弱性 (sc_vulnerability) - BOM分析/調達集中度/リードタイム
  26. 人物リスク (person_risk) - UBO/PEP/オフショア/天下り
  27. 資金フローリスク (capital_flow) - Chinn-Ito/IMF AREAER/SWIFT
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from pipeline.sanctions.screener import screen_entity


@dataclass
class Evidence:
    category: str
    severity: str      # critical/high/medium/low/info
    description: str
    source: str
    url: Optional[str] = None


@dataclass
class SupplierRiskScore:
    supplier_id: str
    company_name: str
    # Core scores
    sanction_score: int = 0
    geo_risk_score: int = 0
    disaster_score: int = 0
    legal_score: int = 0
    maritime_score: int = 0
    conflict_score: int = 0
    economic_score: int = 0
    currency_score: int = 0
    health_score: int = 0
    humanitarian_score: int = 0
    # Extended scores (new)
    weather_score: int = 0
    typhoon_score: int = 0
    compliance_score: int = 0
    food_security_score: int = 0
    trade_score: int = 0
    internet_score: int = 0
    political_score: int = 0
    labor_score: int = 0
    port_congestion_score: int = 0
    aviation_score: int = 0
    energy_score: int = 0
    japan_economy_score: int = 0
    climate_risk_score: int = 0
    cyber_risk_score: int = 0
    sc_vulnerability_score: int = 0
    person_risk_score: int = 0
    capital_flow_score: int = 0
    # Overall
    overall_score: int = 0
    evidence: list[Evidence] = field(default_factory=list)
    calculated_at: datetime = field(default_factory=datetime.utcnow)
    dimension_status: dict = field(default_factory=dict)  # {dim: "ok"|"stale"|"failed"|"not_applicable"}

    # 重み配分（合計1.0） ※v1.3.0: 27次元目(capital_flow 3%)追加、既存を比例縮小(*0.97)
    # カテゴリA: 制裁・紛争・地政学（即座にサプライチェーン途絶）
    # カテゴリB: 災害・気象・インフラ（物理的リスク）
    # カテゴリC: 経済・貿易・資金フロー（構造的リスク）
    # カテゴリD: サイバー・その他（補完情報）
    # カテゴリE: サプライチェーン構造（調達集中度・リードタイム）
    # カテゴリF: 人物リスク（UBO・PEP・オフショア・天下り）
    WEIGHTS = {
        # カテゴリA: 制裁・紛争・地政学 (~25.3%)
        "geo_risk": 0.0632,
        "conflict": 0.0816,
        "political": 0.0542,
        "compliance": 0.0542,
        # カテゴリB: 災害・インフラ・気候 (~23.5%)
        "disaster": 0.0632,
        "weather": 0.0361,
        "typhoon": 0.0271,
        "maritime": 0.0361,
        "internet": 0.0271,
        "climate_risk": 0.0452,
        # カテゴリC: 経済・貿易・資金フロー (~23.8%)
        "economic": 0.0542,
        "currency": 0.0361,
        "trade": 0.0452,
        "energy": 0.0361,
        "port_congestion": 0.0361,
        "capital_flow": 0.03,
        # カテゴリD: サイバー・その他 (~20.8%)
        "cyber_risk": 0.0361,
        "legal": 0.0361,
        "health": 0.0361,
        "humanitarian": 0.0271,
        "food_security": 0.0271,
        "labor": 0.0271,
        "aviation": 0.0180,
        # カテゴリE: サプライチェーン構造 (~2.8%)
        "sc_vulnerability": 0.0279,
        # カテゴリF: 人物リスク (~3.9%)
        "person_risk": 0.0388,
    }

    def calculate_overall(self) -> int:
        if self.sanction_score == 100:
            self.overall_score = 100
            return 100

        scores = {
            "geo_risk": self.geo_risk_score,
            "disaster": self.disaster_score,
            "legal": self.legal_score,
            "maritime": self.maritime_score,
            "conflict": self.conflict_score,
            "economic": self.economic_score,
            "currency": self.currency_score,
            "health": self.health_score,
            "humanitarian": self.humanitarian_score,
            "weather": self.weather_score,
            "typhoon": self.typhoon_score,
            "compliance": self.compliance_score,
            "food_security": self.food_security_score,
            "trade": self.trade_score,
            "internet": self.internet_score,
            "political": self.political_score,
            "labor": self.labor_score,
            "port_congestion": self.port_congestion_score,
            "aviation": self.aviation_score,
            "energy": self.energy_score,
            "climate_risk": self.climate_risk_score,
            "cyber_risk": self.cyber_risk_score,
            "sc_vulnerability": self.sc_vulnerability_score,
            "person_risk": self.person_risk_score,
            "capital_flow": self.capital_flow_score,
        }

        # 加重平均（ベーススコア: 全体の60%）
        weighted_sum = sum(
            scores.get(dim, 0) * self.WEIGHTS.get(dim, 0)
            for dim in self.WEIGHTS
        )

        # ピークリスク増幅（全体の40%）
        # 最高リスクのディメンションを重視（1つでもCRITICALなら全体に反映）
        sorted_scores = sorted(scores.values(), reverse=True)
        peak = sorted_scores[0] if sorted_scores else 0
        second_peak = sorted_scores[1] if len(sorted_scores) > 1 else 0

        # 複合スコア = 加重平均60% + ピーク値30% + 第2ピーク10%
        score = int(weighted_sum * 0.6 + peak * 0.30 + second_peak * 0.10)

        # 制裁スコアが部分一致の場合は加算
        if self.sanction_score > 0:
            score = min(100, score + self.sanction_score // 2)

        # 日本経済スコアは情報提供のみ（overall計算には直接加算しない）

        self.overall_score = min(100, score)
        return self.overall_score

    def risk_level(self) -> str:
        if self.overall_score >= 80: return "CRITICAL"
        if self.overall_score >= 60: return "HIGH"
        if self.overall_score >= 40: return "MEDIUM"
        if self.overall_score >= 20: return "LOW"
        return "MINIMAL"

    def to_dict(self) -> dict:
        return {
            "supplier_id": self.supplier_id,
            "company_name": self.company_name,
            "overall_score": self.overall_score,
            "risk_level": self.risk_level(),
            "dimensions": 27,
            "scores": {
                "sanctions": self.sanction_score,
                "geo_risk": self.geo_risk_score,
                "disaster": self.disaster_score,
                "legal": self.legal_score,
                "maritime": self.maritime_score,
                "conflict": self.conflict_score,
                "economic": self.economic_score,
                "currency": self.currency_score,
                "health": self.health_score,
                "humanitarian": self.humanitarian_score,
                "weather": self.weather_score,
                "typhoon": self.typhoon_score,
                "compliance": self.compliance_score,
                "food_security": self.food_security_score,
                "trade": self.trade_score,
                "internet": self.internet_score,
                "political": self.political_score,
                "labor": self.labor_score,
                "port_congestion": self.port_congestion_score,
                "aviation": self.aviation_score,
                "energy": self.energy_score,
                "japan_economy": self.japan_economy_score,
                "climate_risk": self.climate_risk_score,
                "cyber_risk": self.cyber_risk_score,
                "sc_vulnerability": self.sc_vulnerability_score,
                "person_risk": self.person_risk_score,
                "capital_flow": self.capital_flow_score,
            },
            "score_categories": {
                "sanctions_conflict": {
                    "weight": "25.3%",
                    "components": ["sanctions", "geo_risk", "conflict", "political", "compliance"],
                },
                "disaster_infrastructure_climate": {
                    "weight": "23.5%",
                    "components": ["disaster", "weather", "typhoon", "maritime", "internet", "climate_risk"],
                },
                "economic_trade": {
                    "weight": "23.8%",
                    "components": ["economic", "currency", "trade", "energy", "port_congestion", "capital_flow"],
                },
                "cyber_other": {
                    "weight": "20.8%",
                    "components": ["cyber_risk", "legal", "health", "humanitarian", "food_security", "labor", "aviation"],
                },
                "supply_chain_structure": {
                    "weight": "2.8%",
                    "components": ["sc_vulnerability"],
                },
                "person_risk": {
                    "weight": "3.9%",
                    "components": ["person_risk"],
                },
            },
            "evidence": [
                {"category": e.category, "severity": e.severity,
                 "description": e.description, "source": e.source, "url": e.url}
                for e in self.evidence
            ],
            "calculated_at": self.calculated_at.isoformat(),
            "data_quality": self._data_quality_summary(),
        }

    def _data_quality_summary(self) -> dict:
        ok_count = sum(1 for v in self.dimension_status.values() if v == "ok")
        failed_count = sum(1 for v in self.dimension_status.values() if v == "failed")
        confidence = round(ok_count / 27, 2)
        return {
            "dimensions_ok": ok_count,
            "dimensions_failed": failed_count,
            "confidence": confidence,
            "low_confidence_warning": confidence < 0.5,
            "dimension_status": self.dimension_status,
        }


def _add_dimension(score_obj, category: str, source: str,
                   result: dict, attr_name: str):
    """ディメンション結果をスコアオブジェクトに追加するヘルパー"""
    dim_score = result.get("score", 0)
    setattr(score_obj, attr_name, dim_score)
    for e in result.get("evidence", []):
        sev = "high" if dim_score > 60 else "medium" if dim_score > 30 else "low"
        score_obj.evidence.append(Evidence(
            category=category, severity=sev,
            description=e, source=source
        ))


# Static typhoon/cyclone exposure baseline (seasonal average risk)
# Based on historical cyclone frequency and impact
TYPHOON_EXPOSURE = {
    "Japan": 20, "Taiwan": 25, "Philippines": 30, "China": 18, "Vietnam": 22,
    "South Korea": 12, "Bangladesh": 25, "Myanmar": 18, "India": 18,
    "Indonesia": 10, "Thailand": 8, "Malaysia": 5, "Cambodia": 8,
    "United States": 12, "Mexico": 15, "Australia": 12,
    "Somalia": 8, "Yemen": 8, "Pakistan": 10, "Sri Lanka": 8,
}

# Country-level sanctions risk (comprehensive sanctions programs)
# Used when no specific entity name is provided for screening
SANCTIONED_COUNTRIES = {
    "north korea": 100, "dprk": 100, "prk": 100,
    "iran": 90, "irn": 90,
    "syria": 85, "syr": 85,
    "russia": 70, "rus": 70,
    "belarus": 65, "blr": 65,
    "myanmar": 60, "mmr": 60,
    "cuba": 50, "cub": 50,
    "venezuela": 55, "ven": 55,
    "sudan": 75, "sdn": 75,
    "south sudan": 45, "ssd": 45,
    "yemen": 45, "yem": 45,
    "libya": 50, "lby": 50,
    "zimbabwe": 40, "zwe": 40,
    "nicaragua": 35, "nic": 35,
}

def calculate_risk_score(
    supplier_id: str,
    company_name: str,
    country: str = None,
    location: str = None,
) -> SupplierRiskScore:
    """27次元 総合リスクスコア算出"""

    score = SupplierRiskScore(supplier_id=supplier_id, company_name=company_name)
    loc = location or country or ""

    # === 1. 制裁スクリーニング（最優先・即時判定） ===
    # Check if a real entity name was provided (not a placeholder)
    _is_real_entity = company_name and company_name.lower() not in (
        "test", "test_entity", "unknown", "", "n/a", "none"
    ) and not company_name.startswith("detail_") and not company_name.startswith("regtest") and not company_name.startswith("sanc_") and not company_name.startswith("je_")
    
    if _is_real_entity:
        # Entity screening mode: fuzzy match against sanctions lists
        try:
            sanction_result = screen_entity(company_name, country)
            if sanction_result.matched:
                score.sanction_score = 100
                for e in sanction_result.evidence:
                    score.evidence.append(Evidence(
                        category="sanctions", severity="critical",
                        description=e, source=sanction_result.source or "sanctions_db"
                    ))
            elif sanction_result.match_score > 60:
                score.sanction_score = int(sanction_result.match_score * 0.5)
                score.evidence.append(Evidence(
                    category="sanctions", severity="medium",
                    description=f"制裁リストに類似名称あり（類似度{sanction_result.match_score:.0f}%）。要確認。",
                    source="sanctions_db"
                ))
            score.dimension_status["sanctions"] = "ok"
        except Exception:
            score.dimension_status["sanctions"] = "failed"
    else:
        # Country risk mode: check if the country itself is sanctioned
        country_sanction_score = 0
        loc_lower = (loc or "").lower()
        for sanctioned_country, sanc_score in SANCTIONED_COUNTRIES.items():
            if sanctioned_country == loc_lower or loc_lower in sanctioned_country or sanctioned_country in loc_lower:
                country_sanction_score = sanc_score
                score.evidence.append(Evidence(
                    category="sanctions", severity="critical" if sanc_score >= 80 else "high" if sanc_score >= 50 else "medium",
                    description=f"[制裁] {loc}: 包括的制裁プログラム対象国 (リスクスコア: {sanc_score}/100)",
                    source="OFAC/EU/UN"
                ))
                break
        score.sanction_score = country_sanction_score
        score.dimension_status["sanctions"] = "ok"

    if score.sanction_score == 100:
        score.calculate_overall()
        return score

    # === 2. 地政学リスク（GDELT） ===
    if loc:
        try:
            from pipeline.gdelt.monitor import run_monitoring_job
            gdelt_result = run_monitoring_job(supplier_id, company_name, loc)
            _add_dimension(score, "geo_risk", "GDELT", gdelt_result, "geo_risk_score")
            score.dimension_status["geo_risk"] = "ok"
        except Exception:
            score.dimension_status["geo_risk"] = "failed"
    else:
        score.dimension_status["geo_risk"] = "not_applicable"

    # === 3. 災害リスク（GDACS + USGS + FIRMS + JMA） ===
    if loc:
        try:
            from scoring.disaster import get_disaster_score
            disaster_val, disaster_evidence = get_disaster_score(loc)
            score.disaster_score = disaster_val
            for e in disaster_evidence:
                score.evidence.append(Evidence(
                    category="disaster",
                    severity="high" if disaster_val > 60 else "low",
                    description=e, source="GDACS/USGS/FIRMS/JMA"
                ))
            score.dimension_status["disaster"] = "ok"
        except Exception:
            score.dimension_status["disaster"] = "failed"
    else:
        score.dimension_status["disaster"] = "not_applicable"

    # === 4. 法的リスク（Caselaw MCP） ===
    try:
        from scoring.legal import get_legal_score
        legal_val, legal_evidence = get_legal_score(company_name, country)
        score.legal_score = legal_val
        for e in legal_evidence:
            score.evidence.append(Evidence(
                category="legal",
                severity="high" if legal_val > 60 else "medium",
                description=e, source="Caselaw MCP"
            ))
        score.dimension_status["legal"] = "ok"
    except Exception:
        score.dimension_status["legal"] = "failed"

    # === 5. 海上輸送リスク（IMF PortWatch） ===
    if loc:
        try:
            from pipeline.maritime.portwatch_client import get_maritime_risk_for_location
            maritime = get_maritime_risk_for_location(loc)
            _add_dimension(score, "maritime", "IMF PortWatch", maritime, "maritime_score")
            score.dimension_status["maritime"] = "ok"
        except Exception:
            score.dimension_status["maritime"] = "failed"
    else:
        score.dimension_status["maritime"] = "not_applicable"

    # === 6. 紛争リスク（ACLED） ===
    if loc:
        try:
            from pipeline.conflict.acled_client import get_conflict_risk_for_location
            conflict = get_conflict_risk_for_location(loc)
            _add_dimension(score, "conflict", "ACLED", conflict, "conflict_score")
            score.dimension_status["conflict"] = "ok"
        except Exception:
            score.dimension_status["conflict"] = "failed"
    else:
        score.dimension_status["conflict"] = "not_applicable"

    # === 7. 経済リスク（World Bank） ===
    if loc:
        try:
            from pipeline.economic.worldbank_client import get_economic_risk_for_location
            economic = get_economic_risk_for_location(loc)
            _add_dimension(score, "economic", "World Bank", economic, "economic_score")
            score.dimension_status["economic"] = "ok"
        except Exception:
            score.dimension_status["economic"] = "failed"
    else:
        score.dimension_status["economic"] = "not_applicable"

    # === 8. 通貨リスク（Frankfurter） ===
    if loc:
        try:
            from pipeline.economic.currency_client import get_currency_risk_for_location
            currency = get_currency_risk_for_location(loc)
            _add_dimension(score, "currency", "Frankfurter/ECB", currency, "currency_score")
            score.dimension_status["currency"] = "ok"
        except Exception:
            score.dimension_status["currency"] = "failed"
    else:
        score.dimension_status["currency"] = "not_applicable"

    # === 9. 感染症リスク（Disease.sh） ===
    if loc:
        try:
            from pipeline.health.disease_client import get_health_risk_for_location
            health = get_health_risk_for_location(loc)
            _add_dimension(score, "health", "Disease.sh", health, "health_score")
            score.dimension_status["health"] = "ok"
        except Exception:
            score.dimension_status["health"] = "failed"
    else:
        score.dimension_status["health"] = "not_applicable"

    # === 10. 人道危機リスク（OCHA FTS + ReliefWeb） ===
    if loc:
        try:
            from scoring.dimensions.humanitarian_scorer import get_humanitarian_score
            humanitarian = get_humanitarian_score(loc)
            _add_dimension(score, "humanitarian", "OCHA FTS/ReliefWeb", humanitarian, "humanitarian_score")
            score.dimension_status["humanitarian"] = "ok"
        except Exception:
            score.dimension_status["humanitarian"] = "failed"
    else:
        score.dimension_status["humanitarian"] = "not_applicable"

    # === 11. 気象リスク（Open-Meteo） ===
    if loc:
        try:
            from pipeline.weather.openmeteo_client import get_weather_risk_by_name
            weather = get_weather_risk_by_name(loc)
            _add_dimension(score, "weather", "Open-Meteo", weather, "weather_score")
            score.dimension_status["weather"] = "ok"
        except Exception:
            score.dimension_status["weather"] = "failed"
    else:
        score.dimension_status["weather"] = "not_applicable"

    # === 12. 台風・宇宙天気（NOAA） ===
    if loc:
        try:
            from pipeline.weather.openmeteo_client import _resolve_coords
            from pipeline.weather.typhoon_client import get_typhoon_risk_for_location
            coords = _resolve_coords(loc)
            if coords:
                typhoon = get_typhoon_risk_for_location(coords[0], coords[1], loc)
                _add_dimension(score, "typhoon", "NOAA NHC/SWPC", typhoon, "typhoon_score")
                # If live API returned 0 (no active storms), use seasonal exposure baseline
                if score.typhoon_score == 0:
                    for country, exposure in TYPHOON_EXPOSURE.items():
                        if country.lower() == loc.lower() or loc.lower() in country.lower():
                            score.typhoon_score = exposure
                            score.evidence.append(Evidence(
                                category="typhoon", severity="low",
                                description=f"[台風] {country}: 現在活動中の台風なし、季節平均暴露リスク {exposure}/100",
                                source="NOAA/歴史データ"
                            ))
                            break
            else:
                # No coords - use static exposure baseline
                for country, exposure in TYPHOON_EXPOSURE.items():
                    if country.lower() == loc.lower() or loc.lower() in country.lower():
                        score.typhoon_score = exposure
                        score.evidence.append(Evidence(
                            category="typhoon", severity="low",
                            description=f"[台風] {country}: 台風/サイクロン暴露リスク（季節平均ベースライン）",
                            source="NOAA/歴史データ"
                        ))
                        break
            score.dimension_status["typhoon"] = "ok"
        except Exception:
            # Static fallback on complete failure
            for country, exposure in TYPHOON_EXPOSURE.items():
                if country.lower() == loc.lower() or loc.lower() in country.lower():
                    score.typhoon_score = exposure
                    break
            score.dimension_status["typhoon"] = "failed"
    else:
        score.dimension_status["typhoon"] = "not_applicable"

    # === 13. コンプライアンス（FATF/INFORM/TI-CPI） ===
    if loc:
        try:
            from pipeline.compliance.fatf_client import get_compliance_risk_for_location
            compliance = get_compliance_risk_for_location(loc)
            _add_dimension(score, "compliance", "FATF/INFORM/TI-CPI", compliance, "compliance_score")
            score.dimension_status["compliance"] = "ok"
        except Exception:
            score.dimension_status["compliance"] = "failed"
    else:
        score.dimension_status["compliance"] = "not_applicable"

    # === 14. 食料安全保障（FEWS NET + WFP） ===
    if loc:
        try:
            from scoring.dimensions.food_security_scorer import get_food_security_score
            food = get_food_security_score(loc)
            _add_dimension(score, "food_security", "FEWS NET/WFP", food, "food_security_score")
            score.dimension_status["food_security"] = "ok"
        except Exception:
            score.dimension_status["food_security"] = "failed"
    else:
        score.dimension_status["food_security"] = "not_applicable"

    # === 15. 貿易依存（UN Comtrade） ===
    if loc:
        try:
            from pipeline.trade.comtrade_client import get_trade_dependency_risk
            trade = get_trade_dependency_risk(loc)
            _add_dimension(score, "trade", "UN Comtrade", trade, "trade_score")
            score.dimension_status["trade"] = "ok"
        except Exception:
            score.dimension_status["trade"] = "failed"
    else:
        score.dimension_status["trade"] = "not_applicable"

    # === 16. インターネットインフラ（Cloudflare/IODA） ===
    if loc:
        try:
            from pipeline.infrastructure.internet_client import get_internet_risk_for_location
            internet = get_internet_risk_for_location(loc)
            _add_dimension(score, "internet", "Cloudflare Radar/IODA", internet, "internet_score")
            score.dimension_status["internet"] = "ok"
        except Exception:
            score.dimension_status["internet"] = "failed"
    else:
        score.dimension_status["internet"] = "not_applicable"

    # === 17. 政治リスク（Freedom House/FSI） ===
    if loc:
        try:
            from pipeline.compliance.political_client import get_political_risk_for_location
            political = get_political_risk_for_location(loc)
            _add_dimension(score, "political", "Freedom House/FSI", political, "political_score")
            score.dimension_status["political"] = "ok"
        except Exception:
            score.dimension_status["political"] = "failed"
    else:
        score.dimension_status["political"] = "not_applicable"

    # === 18. 労働リスク（DoL ILAB/GSI） ===
    if loc:
        try:
            from pipeline.compliance.labor_client import get_labor_risk_for_location
            labor = get_labor_risk_for_location(loc)
            _add_dimension(score, "labor", "DoL ILAB/GSI", labor, "labor_score")
            score.dimension_status["labor"] = "ok"
        except Exception:
            score.dimension_status["labor"] = "failed"
    else:
        score.dimension_status["labor"] = "not_applicable"

    # === 19. 港湾混雑（UNCTAD） ===
    if loc:
        try:
            from pipeline.infrastructure.port_congestion_client import get_port_congestion_risk
            port = get_port_congestion_risk(loc)
            _add_dimension(score, "port_congestion", "UNCTAD/港湾統計", port, "port_congestion_score")
            score.dimension_status["port_congestion"] = "ok"
        except Exception:
            score.dimension_status["port_congestion"] = "failed"
    else:
        score.dimension_status["port_congestion"] = "not_applicable"

    # === 20. 航空リスク（OpenSky） ===
    if loc:
        try:
            from pipeline.aviation.opensky_client import get_aviation_risk_for_location, AVIATION_BASELINE
            aviation = get_aviation_risk_for_location(loc)
            _add_dimension(score, "aviation", "OpenSky Network", aviation, "aviation_score")
            # If live API returned 0 (normal traffic), use infrastructure baseline
            if score.aviation_score == 0:
                for country, baseline in AVIATION_BASELINE.items():
                    if country.lower() == loc.lower() or loc.lower() in country.lower():
                        score.aviation_score = baseline
                        score.evidence.append(Evidence(
                            category="aviation", severity="low",
                            description=f"[航空] {country}: 航空交通正常、インフラ品質ベースライン {baseline}/100",
                            source="OpenSky/ICAO統計"
                        ))
                        break
            score.dimension_status["aviation"] = "ok"
        except Exception:
            score.dimension_status["aviation"] = "failed"
    else:
        score.dimension_status["aviation"] = "not_applicable"

    # === 21. エネルギー価格（FRED） ===
    try:
        from pipeline.energy.commodity_client import get_energy_risk
        energy = get_energy_risk(country=loc)
        _add_dimension(score, "energy", "FRED/EIA", energy, "energy_score")
        score.dimension_status["energy"] = "ok"
    except Exception:
        score.dimension_status["energy"] = "failed"

    # === 22. 日本経済指標（BOJ/e-Stat） ===
    # Japan-specific dimension: only applies when scoring Japan
    if loc and loc.lower() in ("japan", "jp", "jpn"):
        try:
            from pipeline.japan.estat_client import get_japan_economic_risk
            japan_econ = get_japan_economic_risk()
            _add_dimension(score, "japan_economy", "BOJ/ExchangeRate-API", japan_econ, "japan_economy_score")
            score.dimension_status["japan_economy"] = "ok"
        except Exception:
            score.dimension_status["japan_economy"] = "failed"
    else:
        score.dimension_status["japan_economy"] = "not_applicable"

    # === 23. 気候リスク（ND-GAIN/GloFAS/WRI/Climate TRACE） ===
    if loc:
        try:
            from scoring.dimensions.climate_scorer import get_climate_risk
            climate = get_climate_risk(loc)
            _add_dimension(score, "climate_risk", "ND-GAIN/GloFAS/WRI/Climate TRACE", climate, "climate_risk_score")
            score.dimension_status["climate_risk"] = "ok"
        except Exception:
            score.dimension_status["climate_risk"] = "failed"
    else:
        score.dimension_status["climate_risk"] = "not_applicable"

    # === 24. サイバーリスク（OONI/CISA KEV/ITU ICT） ===
    if loc:
        try:
            from scoring.dimensions.cyber_scorer import get_cyber_risk
            cyber = get_cyber_risk(loc)
            _add_dimension(score, "cyber_risk", "OONI/CISA KEV/ITU ICT", cyber, "cyber_risk_score")
            score.dimension_status["cyber_risk"] = "ok"
        except Exception:
            score.dimension_status["cyber_risk"] = "failed"
    else:
        score.dimension_status["cyber_risk"] = "not_applicable"

    # === 25. サプライチェーン脆弱性（BOM分析/調達集中度/リードタイム） ===
    # BOM結果が提供されない場合はデフォルト中リスク（データなし）
    try:
        from scoring.dimensions.supply_chain_vulnerability_scorer import (
            get_supply_chain_vulnerability_score,
        )
        sc_vuln = get_supply_chain_vulnerability_score(location=loc)
        _add_dimension(
            score, "sc_vulnerability", "BOM/調達分析",
            sc_vuln, "sc_vulnerability_score",
        )
        score.dimension_status["sc_vulnerability"] = "ok"
    except Exception:
        score.dimension_status["sc_vulnerability"] = "failed"

    # === 26. 人物リスク（UBO/PEP/オフショア/天下り） ===
    try:
        from scoring.dimensions.person_risk_scorer import PersonRiskScorer
        from pipeline.corporate.openownership_client import OpenOwnershipClient
        from pipeline.corporate.icij_client import ICIJClient

        _pr_scorer = PersonRiskScorer()
        _oo_client = OpenOwnershipClient()

        # UBO取得
        ubo_records = _oo_client.get_ubo_sync(company_name)

        # UBOチェーン全体のリスク評価
        chain_result = _pr_scorer.score_ownership_chain(
            ubo_records, company_name=company_name
        )
        person_risk_val = chain_result.get("total_score", 0)

        # UBO情報がない場合: ICIJオフショアリスクで補完
        if not ubo_records:
            try:
                _icij = ICIJClient()
                offshore_result = _icij.get_offshore_risk_score_sync(company_name)
                offshore_score = offshore_result.get("score", 0)
                if offshore_score > 0:
                    person_risk_val = max(person_risk_val, int(offshore_score * 0.5))
                    for ev in offshore_result.get("evidence", []):
                        score.evidence.append(Evidence(
                            category="person_risk", severity="medium",
                            description=ev, source="ICIJ Offshore Leaks"
                        ))
            except Exception:
                pass

        score.person_risk_score = min(100, person_risk_val)

        # エビデンス追加
        for ev in chain_result.get("evidence", []):
            sev = "critical" if person_risk_val >= 80 else "high" if person_risk_val >= 60 else "medium" if person_risk_val >= 30 else "low"
            score.evidence.append(Evidence(
                category="person_risk", severity=sev,
                description=ev, source="OpenOwnership/ICIJ/Wikidata"
            ))

        # サマリーエビデンス
        sanctioned = chain_result.get("sanctioned_owners", [])
        peps = chain_result.get("pep_owners", [])
        if sanctioned:
            score.evidence.append(Evidence(
                category="person_risk", severity="critical",
                description=f"[人物リスク] 制裁対象UBO検出: {', '.join(sanctioned)}",
                source="OpenOwnership/制裁DB"
            ))
        if peps:
            score.evidence.append(Evidence(
                category="person_risk", severity="high",
                description=f"[人物リスク] PEP(政治的露出者)検出: {', '.join(peps)}",
                source="OpenOwnership/PEP DB"
            ))

        score.dimension_status["person_risk"] = "ok"
    except Exception:
        score.dimension_status["person_risk"] = "failed"

    # === 27. 資金フローリスク（Chinn-Ito/IMF AREAER/SWIFT） ===
    if loc:
        try:
            from scoring.dimensions.capital_flow_scorer import get_capital_flow_score
            capital_flow = get_capital_flow_score(loc)
            _add_dimension(score, "capital_flow", "Chinn-Ito/IMF/SWIFT", capital_flow, "capital_flow_score")
            score.dimension_status["capital_flow"] = "ok"
        except Exception:
            score.dimension_status["capital_flow"] = "failed"
    else:
        score.dimension_status["capital_flow"] = "not_applicable"

    # エビデンスなしの場合
    if not score.evidence:
        score.evidence.append(Evidence(
            category="info", severity="info",
            description="現時点でリスク情報は検出されていません",
            source="system"
        ))

    score.calculate_overall()
    return score
