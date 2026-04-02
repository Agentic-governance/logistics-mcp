"""Supply Chain Risk MCP Server — 24次元リスク評価"""
from fastmcp import FastMCP
from scoring.engine import calculate_risk_score
from pipeline.sanctions.screener import screen_entity
from pipeline.gdelt.monitor import RiskAlert
from pipeline.corporate.graph_builder import build_supply_chain_graph, graph_to_visualization_data
from pipeline.db import Session, engine
from pipeline.scheduler import MonitoredSupplier
import csv, io, json, logging, sqlite3

logger = logging.getLogger(__name__)

try:
    from pipeline.trade.importyeti_client import ImportYetiClient, get_customs_supplier_evidence
    from pipeline.corporate.ir_scraper import IRScraper
    from features.goods_layer.unified_api import GoodsLayerAnalyzer
except ImportError:
    pass

# Stream B: 人レイヤー（Person Layer）モジュール
try:
    from pipeline.corporate.openownership_client import OpenOwnershipClient, UBORecord
    from pipeline.corporate.icij_client import ICIJClient
    from pipeline.corporate.wikidata_client import WikidataClient
    from scoring.dimensions.person_risk_scorer import PersonRiskScorer
    from features.graph.person_company_graph import PersonCompanyGraph
except ImportError:
    pass
from datetime import datetime, timedelta
from cachetools import TTLCache
import hashlib
from mcp_server.validators import (
    validate_country, validate_dimension, validate_industry,
    validate_scenario, validate_locations_list, safe_error_response,
    VALID_DIMENSIONS,
)

# Response caches
_risk_score_cache = TTLCache(maxsize=200, ttl=3600)
_location_risk_cache = TTLCache(maxsize=200, ttl=3600)
_sanctions_cache = TTLCache(maxsize=500, ttl=86400)
_dashboard_cache = TTLCache(maxsize=1, ttl=1800)

mcp = FastMCP("Supply Chain Risk Intelligence")

# ---------------------------------------------------------------------------
#  Dimension explanation templates (TASK 5-A: explain=True)
# ---------------------------------------------------------------------------
_DIMENSION_EXPLANATIONS: dict[str, str] = {
    "sanctions": "制裁リスト（OFAC/EU/UN/METI/BIS等）との一致度。100=完全一致で取引禁止レベル。",
    "geo_risk": "GDELTニュースから算出した地政学的緊張度。高いほど紛争・外交摩擦が頻発。",
    "disaster": "GDACS/USGS/FIRMS/JMA等の自然災害データ。地震・洪水・火山・山火事リスク。",
    "legal": "訴訟・規制違反データに基づく法的リスク。高いほど法的紛争が多い。",
    "maritime": "IMF PortWatch海上輸送途絶データ。チョークポイント封鎖・港湾障害リスク。",
    "conflict": "ACLED武力紛争データ。テロ・内戦・暴動の頻度と深刻度。",
    "economic": "世界銀行マクロ経済指標。GDP成長率・インフレ・政治安定性等。",
    "currency": "為替ボラティリティ（Frankfurter/ECB）。通貨急落による調達コスト変動リスク。",
    "health": "感染症データ（Disease.sh）。パンデミック・エピデミックによる操業停止リスク。",
    "humanitarian": "人道危機データ（OCHA/ReliefWeb）。難民・飢餓・人道支援ニーズ。",
    "weather": "気象データ（Open-Meteo）。極端気象イベント（豪雨・猛暑・寒波）リスク。",
    "typhoon": "台風・サイクロン・宇宙天気（NOAA）。暴風域通過確率と季節的暴露。",
    "compliance": "FATF/INFORM/TI-CPI。マネロン対策・腐敗認識指数・ガバナンス水準。",
    "food_security": "FEWS NET/WFPデータ。食料不安定・飢饉リスク。サプライチェーン労働力への影響。",
    "trade": "UN Comtrade貿易依存度。特定国への輸出入集中リスク。",
    "internet": "Cloudflare Radar/IODA。インターネット遮断・通信インフラ障害リスク。",
    "political": "Freedom House/FSI。民主主義指数・国家脆弱性・政権安定性。",
    "labor": "DoL ILAB/GSI。強制労働・児童労働・現代奴隷リスク。ESGコンプライアンス影響。",
    "port_congestion": "UNCTAD港湾統計。主要港の混雑度・滞船日数。リードタイム延長リスク。",
    "aviation": "OpenSky Network。航空インフラ品質・空域閉鎖リスク。",
    "energy": "FRED/EIAエネルギー価格。原油・天然ガス価格変動による製造コスト影響。",
    "japan_economy": "BOJ/e-Stat。円相場・日本固有経済指標（日本関連評価時のみ適用）。",
    "climate_risk": "ND-GAIN/GloFAS/WRI/Climate TRACE。気候変動脆弱性・洪水・水リスク・排出量。",
    "cyber_risk": "OONI/CISA KEV/ITU ICT。サイバー攻撃・検閲・ICTインフラ成熟度。",
}


def _get_explanation(dimension: str, score: int) -> str:
    """Generate a human-readable explanation for a dimension score."""
    base = _DIMENSION_EXPLANATIONS.get(dimension, f"{dimension}のリスク評価。")
    if score == 0:
        level_text = "現時点でリスクは検出されていません。"
    elif score < 20:
        level_text = "リスクは最小限です。通常の監視を継続してください。"
    elif score < 40:
        level_text = "低～中程度のリスクがあります。定期的な確認を推奨します。"
    elif score < 60:
        level_text = "中程度のリスクです。対策の検討を推奨します。"
    elif score < 80:
        level_text = "高リスクです。早急な対策が必要です。"
    else:
        level_text = "重大リスクです。即座の対応と代替策の確保が必須です。"
    return f"{base} スコア {score}/100: {level_text}"


def _get_timeseries_db_path() -> str:
    """Return the path to timeseries.db."""
    import os
    return os.getenv("SQLITE_DB_PATH", "data/timeseries.db")


@mcp.tool()
def screen_sanctions(company_name: str, country: str = None) -> dict:
    """
    制裁リストをスクリーニング（OFAC/EU/UN/OpenSanctions/METI/BIS統合）。
    アンケート不要・即時結果。

    Args:
        company_name: 企業名（日本語・英語対応）
        country: 国名（オプション、精度向上）
    """
    cache_key = f"{company_name}|{country}"
    if cache_key in _sanctions_cache:
        return _sanctions_cache[cache_key]
    result = screen_entity(company_name, country)
    response = {
        "company_name": company_name,
        "matched": result.matched,
        "match_score": result.match_score,
        "source": result.source,
        "matched_entity": result.matched_entity,
        "evidence": result.evidence,
        "screened_at": datetime.utcnow().isoformat(),
    }
    _sanctions_cache[cache_key] = response
    return response


@mcp.tool()
def monitor_supplier(supplier_id: str, company_name: str, location: str) -> dict:
    """
    サプライヤーをリアルタイム監視に登録。
    15分ごとに30+データソースを自動チェック、24次元でリスク評価。

    Args:
        supplier_id: 社内管理ID
        company_name: 企業名
        location: 所在地（国名または都市名）
    """
    with Session() as session:
        supplier = MonitoredSupplier(
            supplier_id=supplier_id,
            company_name=company_name,
            location=location,
        )
        session.merge(supplier)
        session.commit()

    return {
        "status": "registered",
        "supplier_id": supplier_id,
        "monitoring": {
            "interval": "15 minutes",
            "dimensions": 24,
            "sources": [
                "OFAC", "EU", "UN", "OpenSanctions", "METI", "BIS",
                "OFSI", "SECO", "Canada", "DFAT", "MOFA Japan",
                "GDELT", "GDACS", "USGS", "FIRMS", "JMA",
                "PortWatch", "AISHub", "UNCTAD",
                "ACLED", "WorldBank", "Frankfurter/ECB", "UN Comtrade",
                "Disease.sh", "ReliefWeb", "WFP HungerMap",
                "Open-Meteo", "NOAA NHC/SWPC",
                "FATF", "Freedom House", "DoL ILAB",
                "Cloudflare Radar", "OpenSky", "FRED",
                "ND-GAIN", "GloFAS", "WRI Aqueduct", "Climate TRACE",
                "OONI", "CISA KEV", "ITU ICT",
            ],
        },
    }


@mcp.tool()
def get_risk_score(
    supplier_id: str,
    company_name: str,
    country: str = None,
    location: str = None,
    dimensions: list[str] = [],
    include_forecast: bool = False,
    include_history: bool = False,
    explain: bool = False,
) -> dict:
    """
    24次元サプライヤーリスクスコアを取得。
    制裁・地政学・災害・法的・海上輸送・紛争・経済・通貨・感染症・人道危機・
    気象・台風・コンプライアンス・食料安全保障・貿易依存・インターネット・
    政治・労働・港湾混雑・航空・エネルギー・日本経済。
    購買部門が上司に説明できるエビデンス付き。

    Args:
        supplier_id: サプライヤーID
        company_name: 企業名
        country: 国名
        location: 所在地
        dimensions: 特定次元のみに絞り込み（空=全次元）
        include_forecast: Trueで30日先の予測を追加
        include_history: Trueで過去90日のスコア推移を追加
        explain: Trueで各次元にスコアの解説テキストを追加
    """
    try:
        if country:
            country = validate_country(country)

        # Validate requested dimensions
        if dimensions:
            for dim in dimensions:
                validate_dimension(dim)

        cache_key = f"{company_name}|{country}|{location}"
        if cache_key in _risk_score_cache:
            result = _risk_score_cache[cache_key]
        else:
            score = calculate_risk_score(supplier_id, company_name, country, location)
            result = score.to_dict()
            _risk_score_cache[cache_key] = result

        # --- Filter to requested dimensions ---
        if dimensions:
            filtered_scores = {k: v for k, v in result.get("scores", {}).items() if k in dimensions}
            result = dict(result)  # shallow copy to avoid mutating cache
            result["scores"] = filtered_scores
            result["filtered_dimensions"] = dimensions

        # --- TASK 5-A: explain=True ---
        if explain:
            result = dict(result)
            explanations = {}
            for dim, val in result.get("scores", {}).items():
                explanations[dim] = _get_explanation(dim, val)
            result["explanations"] = explanations

        # --- TASK 5-A: include_history=True ---
        if include_history:
            result = dict(result)
            loc = location or country or ""
            try:
                from features.timeseries.store import RiskTimeSeriesStore
                store = RiskTimeSeriesStore()
                end_dt = datetime.utcnow().isoformat()
                start_dt = (datetime.utcnow() - timedelta(days=90)).isoformat()
                dim_filter = dimensions if dimensions else ["overall"]
                history_rows = store.get_history(loc, start_dt, end_dt, dim_filter)
                result["history"] = {
                    "period_days": 90,
                    "data_points": len(history_rows),
                    "records": [
                        {
                            "timestamp": r.get("timestamp"),
                            "dimension": r.get("dimension"),
                            "score": r.get("score"),
                        }
                        for r in history_rows
                    ],
                }
            except Exception as e:
                result["history"] = {"error": str(e), "period_days": 90, "data_points": 0}

        # --- TASK 5-A: include_forecast=True ---
        if include_forecast:
            result = dict(result)
            loc = location or country or ""
            try:
                from features.timeseries.forecaster import RiskForecaster
                forecaster = RiskForecaster()
                forecast_dims = dimensions if dimensions else ["overall"]
                forecasts = {}
                for dim in forecast_dims:
                    fc = forecaster.forecast(loc, dimension=dim, horizon_days=30)
                    forecasts[dim] = fc
                result["forecast"] = forecasts
            except Exception as e:
                result["forecast"] = {"error": str(e)}

        return result
    except ValueError as e:
        return safe_error_response(e)


@mcp.tool()
def get_location_risk(location: str) -> dict:
    """
    特定の地域/国/都市のリスクを一括評価。
    全24次元のリスクスコアとエビデンスを返す。

    Args:
        location: 国名、都市名、または地域名
    """
    try:
        location = validate_country(location)
        if location in _location_risk_cache:
            return _location_risk_cache[location]
        score = calculate_risk_score(f"loc_{location}", f"Location: {location}",
                                     country=location, location=location)
        result = score.to_dict()
        _location_risk_cache[location] = result
        return result
    except ValueError as e:
        return safe_error_response(e)


@mcp.tool()
def get_global_risk_dashboard() -> dict:
    """
    グローバルリスクダッシュボード。
    全データソースの最新状況を一覧取得。
    災害・地震・台風・港湾途絶・感染症・宇宙天気をリアルタイム表示。
    """
    cache_key = "global_dashboard"
    if cache_key in _dashboard_cache:
        return _dashboard_cache[cache_key]
    dashboard = {"timestamp": datetime.utcnow().isoformat(), "dimensions": 24, "sources": {}}

    try:
        from pipeline.disaster.gdacs_client import fetch_gdacs_alerts
        events = fetch_gdacs_alerts()
        red = [e for e in events if e.severity == "Red"]
        orange = [e for e in events if e.severity == "Orange"]
        dashboard["sources"]["disasters"] = {
            "total": len(events), "red_alerts": len(red), "orange_alerts": len(orange),
            "top_events": [{"title": e.title, "severity": e.severity, "country": e.country}
                           for e in (red + orange)[:5]],
        }
    except Exception:
        dashboard["sources"]["disasters"] = {"status": "unavailable"}

    try:
        from pipeline.disaster.usgs_client import fetch_significant_earthquakes
        quakes = fetch_significant_earthquakes()
        dashboard["sources"]["earthquakes"] = {
            "significant_month": len(quakes),
            "top": [{"mag": q["magnitude"], "place": q["place"]} for q in quakes[:3]],
        }
    except Exception:
        dashboard["sources"]["earthquakes"] = {"status": "unavailable"}

    try:
        from pipeline.weather.typhoon_client import fetch_active_tropical_cyclones, fetch_space_weather
        storms = fetch_active_tropical_cyclones()
        space = fetch_space_weather()
        dashboard["sources"]["weather"] = {
            "active_storms": len(storms),
            "storms": [{"name": s["name"], "basin": s["basin"]} for s in storms[:5]],
            "kp_index": space.get("kp_index"),
            "solar_wind_speed": space.get("solar_wind_speed"),
        }
    except Exception:
        dashboard["sources"]["weather"] = {"status": "unavailable"}

    try:
        from pipeline.maritime.portwatch_client import fetch_active_disruptions
        disruptions = fetch_active_disruptions()
        dashboard["sources"]["maritime"] = {
            "active_disruptions": len(disruptions),
            "disruptions": [{"name": d["name"], "impact": d.get("trade_impact_pct")}
                            for d in disruptions[:5]],
        }
    except Exception:
        dashboard["sources"]["maritime"] = {"status": "unavailable"}

    try:
        from pipeline.health.disease_client import fetch_covid_global
        covid = fetch_covid_global()
        dashboard["sources"]["health"] = {
            "covid_active": covid.get("active", 0),
            "today_cases": covid.get("today_cases", 0),
        }
    except Exception:
        dashboard["sources"]["health"] = {"status": "unavailable"}

    try:
        from pipeline.japan.estat_client import fetch_boj_exchange_rate
        fx = fetch_boj_exchange_rate()
        if "rates" in fx:
            dashboard["sources"]["japan_economy"] = {
                "usd_jpy": fx["rates"].get("USD"),
                "cny_jpy": fx["rates"].get("CNY"),
            }
    except Exception:
        pass

    _dashboard_cache[cache_key] = dashboard
    return dashboard


@mcp.tool()
def get_supply_chain_graph(company_name: str, country_code: str = "jp", depth: int = 2) -> dict:
    """
    Tier-N供給網グラフを取得。
    Tier-2以降の隠れた依存関係を可視化。

    Args:
        company_name: 起点企業名
        country_code: 国コード（jp/us/cn等）
        depth: 探索深度（1=Tier-1のみ、2=Tier-2まで）
    """
    G = build_supply_chain_graph(company_name, country_code, depth)
    return graph_to_visualization_data(G)


@mcp.tool()
def get_risk_alerts(since_hours: int = 24, min_score: int = 50) -> dict:
    """
    直近のリスクアラート一覧を取得。

    Args:
        since_hours: 何時間前からのアラートを取得するか
        min_score: 最小スコア閾値
    """
    since = datetime.utcnow() - timedelta(hours=since_hours)

    with Session() as session:
        alerts = session.query(RiskAlert).filter(
            RiskAlert.created_at >= since,
            RiskAlert.score >= min_score
        ).order_by(RiskAlert.created_at.desc()).limit(50).all()

        return {
            "count": len(alerts),
            "alerts": [
                {"id": a.id, "supplier": a.company_name, "type": a.alert_type,
                 "severity": a.severity, "score": a.score, "title": a.title,
                 "description": a.description, "created_at": a.created_at.isoformat()}
                for a in alerts
            ],
        }


@mcp.tool()
def bulk_screen(csv_content: str) -> dict:
    """
    CSVで複数サプライヤーを一括スクリーニング。

    Args:
        csv_content: CSVテキスト（ヘッダー: company_name,country）
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    results = []
    matched_count = 0

    for row in reader:
        name = row.get("company_name", "").strip()
        country = row.get("country", "").strip() or None
        if not name:
            continue

        result = screen_entity(name, country)
        results.append({
            "company_name": name,
            "country": country,
            "matched": result.matched,
            "match_score": result.match_score,
            "source": result.source,
        })
        if result.matched:
            matched_count += 1

    return {
        "total_screened": len(results),
        "matched_count": matched_count,
        "results": results,
    }


@mcp.tool()
def compare_locations(locations: str) -> dict:
    """
    複数の国/地域のリスクを比較。
    カンマ区切りで複数地域を指定し、全24次元でリスクを比較表示。

    Args:
        locations: カンマ区切りの地域リスト（例: "China,Vietnam,Thailand"）
    """
    try:
        loc_list = validate_locations_list(locations)
        comparisons = []

        for loc in loc_list:
            score = calculate_risk_score(f"cmp_{loc}", f"Compare: {loc}",
                                         country=loc, location=loc)
            d = score.to_dict()
            comparisons.append({
                "location": loc,
                "overall_score": d["overall_score"],
                "risk_level": d["risk_level"],
                "scores": d["scores"],
                "top_risks": sorted(
                    [(k, v) for k, v in d["scores"].items() if v > 0],
                    key=lambda x: -x[1]
                )[:5],
            })

        comparisons.sort(key=lambda x: -x["overall_score"])
        return {
            "count": len(comparisons),
            "comparisons": comparisons,
        }
    except ValueError as e:
        return safe_error_response(e)


@mcp.tool()
def analyze_route_risk(origin: str, destination: str) -> dict:
    """
    2地点間の輸送ルートリスクを分析。
    7大チョークポイント（スエズ、マラッカ、ホルムズ、バベルマンデブ、パナマ、台湾海峡、トルコ海峡）の
    通過判定とリスク評価、代替ルート提案を行う。

    Args:
        origin: 出発地（港名・都市名・国名）
        destination: 目的地（港名・都市名・国名）
    """
    try:
        origin = validate_country(origin)
        destination = validate_country(destination)
        from features.route_risk.analyzer import RouteRiskAnalyzer
        analyzer = RouteRiskAnalyzer()
        return analyzer.analyze_route(origin, destination)
    except ValueError as e:
        return safe_error_response(e)


@mcp.tool()
def get_concentration_risk(supplier_csv: str, sector: str = None) -> dict:
    """
    サプライヤー集中リスクを分析（HHI指数ベース）。
    CSVでサプライヤー名・国名・シェアを指定し、地理的・セクター集中度を評価。

    Args:
        supplier_csv: CSVテキスト（ヘッダー: name,country,share）
        sector: セクター名（semiconductor, automotive_parts等）
    """
    import csv as _csv
    import io as _io
    from features.concentration.analyzer import ConcentrationRiskAnalyzer
    reader = _csv.DictReader(_io.StringIO(supplier_csv))
    suppliers = []
    for row in reader:
        suppliers.append({
            "name": row.get("name", ""),
            "country": row.get("country", ""),
            "share": float(row.get("share", 0)),
        })
    analyzer = ConcentrationRiskAnalyzer()
    return analyzer.analyze_supplier_concentration(suppliers, sector=sector)


@mcp.tool()
def simulate_disruption(scenario: str, custom_params: str = None) -> dict:
    """
    サプライチェーン途絶シミュレーション。
    事前定義シナリオまたはカスタムパラメータで途絶の影響を分析。

    事前定義シナリオ:
    - taiwan_blockade: 台湾海峡封鎖
    - suez_closure: スエズ運河閉鎖
    - china_lockdown: 中国ロックダウン
    - semiconductor_shortage: 半導体不足

    Args:
        scenario: シナリオ名（上記参照）
        custom_params: カスタムパラメータJSON（オプション）
    """
    try:
        validate_scenario(scenario)
        from features.simulation.disruption_simulator import DisruptionSimulator
        simulator = DisruptionSimulator()
        if custom_params:
            import json as _json
            params = _json.loads(custom_params)
            return simulator.simulate_scenario(scenario, **params)
        return simulator.simulate_scenario(scenario)
    except ValueError as e:
        return safe_error_response(e)


@mcp.tool()
def generate_dd_report(entity_name: str, country: str) -> dict:
    """
    KYSデューデリジェンスレポート自動生成。
    制裁スクリーニング + 24次元リスクスコア + EDD（強化デューデリジェンス）判定を統合。

    Args:
        entity_name: 企業名
        country: 国名
    """
    from features.reports.dd_generator import DueDiligenceReportGenerator
    generator = DueDiligenceReportGenerator()
    return generator.generate_report(entity_name, country)


@mcp.tool()
def get_commodity_exposure(sector: str) -> dict:
    """
    セクター別コモディティ・エクスポージャー分析。
    原材料の地政学リスク×価格変動リスクを評価。

    対応セクター: semiconductor, battery_materials, automotive_parts, electronics, energy, food

    Args:
        sector: セクター名
    """
    from features.commodity.exposure_analyzer import CommodityExposureAnalyzer
    analyzer = CommodityExposureAnalyzer()
    return analyzer.calculate_exposure(sector)


@mcp.tool()
def bulk_assess_suppliers(csv_content: str, depth: str = "quick") -> dict:
    """
    サプライヤーCSV一括アセスメント。
    制裁スクリーニング + 24次元リスクスコア + 集中リスク分析を一括実行。

    Args:
        csv_content: CSVテキスト（ヘッダー: name,country）
        depth: "quick"（制裁+基本）または "full"（全24次元+集中リスク）
    """
    from features.bulk_assess import bulk_assess
    return bulk_assess(csv_content, assessment_depth=depth)


@mcp.tool()
def get_data_quality_report() -> dict:
    """
    データ品質レポート。
    スコア充足率・異常アラート・ソース疎通状況を返す。
    """
    from features.monitoring.anomaly_detector import (
        ScoreAnomalyDetector, _load_history,
    )
    from scoring.engine import SupplierRiskScore

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "weight_sum": sum(SupplierRiskScore.WEIGHTS.values()),
        "dimensions": 24,
        "score_coverage": {},
        "recent_anomalies": [],
        "sanctions_sources": {},
    }

    # Score coverage
    history = _load_history()
    all_dims = list(SupplierRiskScore.WEIGHTS.keys())
    total_locations = len(history)

    for dim in all_dims:
        has_data = sum(
            1 for data in history.values()
            if data.get("scores", {}).get(dim, 0) > 0
        )
        result["score_coverage"][dim] = round(has_data / max(total_locations, 1), 2)

    # Sanctions source status
    try:
        with Session() as session:
            from pipeline.db import SanctionsMetadata
            metadata = session.query(SanctionsMetadata).all()
            for m in metadata:
                result["sanctions_sources"][m.source] = {
                    "status": "ok" if m.record_count and m.record_count > 0 else "empty",
                    "records": m.record_count or 0,
                    "last_fetched": m.last_fetched.isoformat() if m.last_fetched else None,
                }
    except Exception:
        pass

    # Recent anomalies
    import os as _os
    alerts_dir = "data/alerts"
    if _os.path.exists(alerts_dir):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        filepath = _os.path.join(alerts_dir, f"{today}.jsonl")
        if _os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    for line in f:
                        if line.strip():
                            result["recent_anomalies"].append(json.loads(line))
            except Exception:
                pass

    result["anomaly_count"] = len(result["recent_anomalies"])

    return result


# --- Analytics Tools ---


@mcp.tool()
def analyze_portfolio(
    entities_json: str,
    dimensions: list[str] = [],
    include_clustering: bool = False,
) -> dict:
    """複数サプライヤーのリスクポートフォリオを一括分析・ランク付け。
    entities_json: [{"name":"...","country":"...","share":0.0},...] のJSON"""
    from features.analytics.portfolio_analyzer import PortfolioAnalyzer

    entities = json.loads(entities_json)
    analyzer = PortfolioAnalyzer()
    report = analyzer.analyze_portfolio(entities, dimensions or None)
    result = report.to_dict()

    if include_clustering and len(entities) >= 3:
        clusters = analyzer.cluster_by_risk(entities)
        result["clusters"] = clusters

    result["ranking"] = analyzer.rank_suppliers(entities)
    return result


@mcp.tool()
def analyze_risk_correlations(
    locations: list[str],
    method: str = "pearson",
) -> dict:
    """リスク次元間の相関行列を算出。高相関ペアと先行指標を返す。"""
    from features.analytics.correlation_analyzer import CorrelationAnalyzer

    analyzer = CorrelationAnalyzer()
    matrix = analyzer.compute_dimension_correlations(locations, method)
    return matrix.to_dict()


@mcp.tool()
def find_leading_risk_indicators(
    target_dimension: str,
    locations: list[str],
    lag_days: int = 30,
) -> dict:
    """指定次元の先行指標を時系列クロス相関で特定する。"""
    from features.analytics.correlation_analyzer import CorrelationAnalyzer

    analyzer = CorrelationAnalyzer()
    indicators = analyzer.find_leading_indicators(target_dimension, locations, lag_days)
    return {
        "target_dimension": target_dimension,
        "locations_analyzed": len(locations),
        "lag_days": lag_days,
        "indicators": [i.to_dict() for i in indicators],
        "count": len(indicators),
    }


@mcp.tool()
def benchmark_risk_profile(
    entity_country: str,
    industry: str,
    peer_countries: list[str] = [],
) -> dict:
    """業界平均・競合他社との相対リスク比較。百分位ランク付き。"""
    try:
        validate_industry(industry)
        from features.analytics.benchmark_analyzer import BenchmarkAnalyzer

        analyzer = BenchmarkAnalyzer()
        result = {}

        # Industry benchmark
        report = analyzer.benchmark_against_industry({
            "name": entity_country,
            "country": entity_country,
            "industry": industry,
        })
        result["industry_benchmark"] = report.to_dict()

        # Peer comparison (if peers provided)
        if peer_countries:
            peer_report = analyzer.benchmark_against_peers(
                {"name": entity_country, "country": entity_country},
                [{"name": c, "country": c} for c in peer_countries],
            )
            result["peer_benchmark"] = peer_report.to_dict()

        return result
    except ValueError as e:
        return safe_error_response(e)


@mcp.tool()
def analyze_score_sensitivity(
    location: str,
    weight_perturbation: float = 0.05,
) -> dict:
    """次元重みを変化させたときのスコア感度を分析。最影響次元をランキング。"""
    from features.analytics.sensitivity_analyzer import SensitivityAnalyzer

    analyzer = SensitivityAnalyzer()
    report = analyzer.analyze_weight_sensitivity(location, weight_perturbation)
    return report.to_dict()


@mcp.tool()
def simulate_what_if(
    location: str,
    dimension_overrides_json: str,
) -> dict:
    """指定次元のスコアを上書きしてoverall_scoreを再計算するWhat-If分析。
    dimension_overrides_json: {"conflict": 90} のJSON"""
    from features.analytics.sensitivity_analyzer import SensitivityAnalyzer

    overrides = json.loads(dimension_overrides_json)
    analyzer = SensitivityAnalyzer()
    result = analyzer.simulate_score_change(location, overrides)
    return result.to_dict()


# ===========================================================================
#  STREAM 5: MCP Tool Enhancements (TASK 5-B / 5-C / 5-D)
# ===========================================================================


@mcp.tool()
async def compare_risk_trends(
    locations: list[str],
    dimension: str = "overall",
    period_days: int = 90,
) -> dict:
    """複数地域のリスクスコア推移を比較。どの国が改善/悪化傾向にあるかを返す。

    Args:
        locations: 比較対象の地域リスト（例: ["China", "Vietnam", "Thailand"]）
        dimension: 比較する次元（"overall"または24次元名）
        period_days: 比較期間（日数、デフォルト90日）
    """
    try:
        # Validate dimension
        if dimension != "overall":
            validate_dimension(dimension)

        db_path = _get_timeseries_db_path()
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(days=period_days)
        start_str = start_dt.isoformat()
        end_str = end_dt.isoformat()

        trends: list[dict] = []

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        for loc in locations:
            normalized_loc = validate_country(loc)

            rows = conn.execute(
                "SELECT timestamp, score FROM risk_scores "
                "WHERE location = ? AND dimension = ? AND timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp ASC",
                (normalized_loc, dimension, start_str, end_str),
            ).fetchall()

            scores = [float(r["score"]) for r in rows if r["score"] is not None]
            timestamps = list(range(len(scores)))  # ordinal index for regression

            if len(scores) < 2:
                # Not enough data for trend analysis; use risk_summaries as fallback
                summary_rows = conn.execute(
                    "SELECT date, overall_score, scores_json FROM risk_summaries "
                    "WHERE location = ? ORDER BY date ASC",
                    (normalized_loc,),
                ).fetchall()

                if dimension == "overall":
                    scores = [float(r["overall_score"]) for r in summary_rows if r["overall_score"] is not None]
                else:
                    scores = []
                    for r in summary_rows:
                        try:
                            sj = json.loads(r["scores_json"]) if r["scores_json"] else {}
                            if dimension in sj:
                                scores.append(float(sj[dimension]))
                        except Exception:
                            pass
                timestamps = list(range(len(scores)))

            # Calculate linear regression slope
            if len(scores) >= 2:
                n = len(scores)
                mean_x = sum(timestamps) / n
                mean_y = sum(scores) / n
                numerator = sum((timestamps[i] - mean_x) * (scores[i] - mean_y) for i in range(n))
                denominator = sum((timestamps[i] - mean_x) ** 2 for i in range(n))
                slope = numerator / denominator if denominator != 0 else 0.0

                # Determine direction
                if slope > 0.5:
                    direction = "deteriorating"  # score rising = risk increasing
                elif slope < -0.5:
                    direction = "improving"      # score falling = risk decreasing
                else:
                    direction = "stable"

                latest = scores[-1] if scores else 0
                earliest = scores[0] if scores else 0

                trends.append({
                    "location": normalized_loc,
                    "dimension": dimension,
                    "slope": round(slope, 4),
                    "direction": direction,
                    "latest_score": round(latest, 1),
                    "earliest_score": round(earliest, 1),
                    "change": round(latest - earliest, 1),
                    "data_points": n,
                })
            else:
                trends.append({
                    "location": normalized_loc,
                    "dimension": dimension,
                    "slope": 0.0,
                    "direction": "insufficient_data",
                    "latest_score": scores[-1] if scores else None,
                    "earliest_score": scores[0] if scores else None,
                    "change": 0.0,
                    "data_points": len(scores),
                })

        conn.close()

        # Identify most improved / most deteriorated
        valid_trends = [t for t in trends if t["direction"] != "insufficient_data"]
        most_improved = None
        most_deteriorated = None
        if valid_trends:
            sorted_by_slope = sorted(valid_trends, key=lambda t: t["slope"])
            most_improved = sorted_by_slope[0]["location"]     # most negative slope
            most_deteriorated = sorted_by_slope[-1]["location"]  # most positive slope

        return {
            "dimension": dimension,
            "period_days": period_days,
            "locations_compared": len(locations),
            "trends": trends,
            "most_improved": most_improved,
            "most_deteriorated": most_deteriorated,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except ValueError as e:
        return safe_error_response(e)


@mcp.tool()
async def explain_score_change(
    location: str,
    from_date: str,
    to_date: str,
) -> dict:
    """2時点間のスコア変化の原因を説明。

    Args:
        location: 地域名（国名）
        from_date: 開始日（YYYY-MM-DD）
        to_date: 終了日（YYYY-MM-DD）
    """
    try:
        normalized_loc = validate_country(location)
        db_path = _get_timeseries_db_path()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get snapshot closest to from_date
        from_row = conn.execute(
            "SELECT * FROM risk_summaries WHERE location = ? AND date <= ? ORDER BY date DESC LIMIT 1",
            (normalized_loc, from_date),
        ).fetchone()

        # Get snapshot closest to to_date
        to_row = conn.execute(
            "SELECT * FROM risk_summaries WHERE location = ? AND date <= ? ORDER BY date DESC LIMIT 1",
            (normalized_loc, to_date),
        ).fetchone()

        conn.close()

        if not from_row and not to_row:
            return {
                "error": f"No data found for {normalized_loc} in the specified date range.",
                "location": normalized_loc,
                "from_date": from_date,
                "to_date": to_date,
            }

        # Parse scores
        from_scores: dict = {}
        to_scores: dict = {}
        from_overall = 0.0
        to_overall = 0.0
        from_actual_date = from_date
        to_actual_date = to_date

        if from_row:
            from_scores = json.loads(from_row["scores_json"]) if from_row["scores_json"] else {}
            from_overall = float(from_row["overall_score"]) if from_row["overall_score"] else 0.0
            from_actual_date = from_row["date"]

        if to_row:
            to_scores = json.loads(to_row["scores_json"]) if to_row["scores_json"] else {}
            to_overall = float(to_row["overall_score"]) if to_row["overall_score"] else 0.0
            to_actual_date = to_row["date"]

        # Calculate per-dimension deltas
        all_dims = set(list(from_scores.keys()) + list(to_scores.keys()))
        drivers = []
        for dim in all_dims:
            old_val = from_scores.get(dim, 0)
            new_val = to_scores.get(dim, 0)
            delta = new_val - old_val
            if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                drivers.append({
                    "dimension": dim,
                    "from_score": old_val,
                    "to_score": new_val,
                    "change": delta,
                    "abs_change": abs(delta),
                    "direction": "increased" if delta > 0 else "decreased" if delta < 0 else "unchanged",
                    "explanation": _get_explanation(dim, new_val) if delta != 0 else "変化なし。",
                })

        # Sort by |change| descending
        drivers.sort(key=lambda d: d["abs_change"], reverse=True)

        # Classify top drivers
        top_worsened = [d for d in drivers if d["change"] > 0][:5]
        top_improved = [d for d in drivers if d["change"] < 0][:5]

        return {
            "location": normalized_loc,
            "from_date": from_actual_date,
            "to_date": to_actual_date,
            "overall_change": {
                "from_score": from_overall,
                "to_score": to_overall,
                "change": round(to_overall - from_overall, 1),
                "direction": "worsened" if to_overall > from_overall else "improved" if to_overall < from_overall else "unchanged",
            },
            "drivers": drivers,
            "top_worsened": top_worsened,
            "top_improved": top_improved,
            "summary": (
                f"{normalized_loc}の総合リスクスコアは{from_actual_date}の{from_overall}から"
                f"{to_actual_date}の{to_overall}へ{abs(to_overall - from_overall):.0f}ポイント"
                f"{'上昇' if to_overall > from_overall else '低下' if to_overall < from_overall else '変化なし'}しました。"
                + (f" 最大変動要因: {drivers[0]['dimension']}（{drivers[0]['change']:+.0f}）。" if drivers and drivers[0]["abs_change"] > 0 else "")
            ),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except ValueError as e:
        return safe_error_response(e)


@mcp.tool()
async def get_risk_report_card(location: str) -> dict:
    """地域の総合リスクレポートカードを返す。経営層向けサマリー形式。

    Args:
        location: 地域名（国名）
    """
    try:
        normalized_loc = validate_country(location)

        # --- 1. Current risk score ---
        score_obj = calculate_risk_score(
            f"report_{normalized_loc}",
            f"Report Card: {normalized_loc}",
            country=normalized_loc,
            location=normalized_loc,
        )
        score_dict = score_obj.to_dict()
        overall_score = score_dict["overall_score"]
        risk_level = score_dict["risk_level"]
        scores = score_dict.get("scores", {})

        # --- 2. Top 3 risks ---
        sorted_risks = sorted(
            [(k, v) for k, v in scores.items() if isinstance(v, (int, float)) and v > 0],
            key=lambda x: -x[1],
        )
        top_3_risks = [
            {
                "dimension": dim,
                "score": val,
                "explanation": _get_explanation(dim, val),
            }
            for dim, val in sorted_risks[:3]
        ]

        # --- 3. Trend from timeseries.db ---
        db_path = _get_timeseries_db_path()
        trend_info = {"direction": "unknown", "slope": 0.0, "data_points": 0}
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                "SELECT date, overall_score FROM risk_summaries WHERE location = ? ORDER BY date ASC",
                (normalized_loc,),
            ).fetchall()

            if len(rows) >= 2:
                ts_scores = [float(r["overall_score"]) for r in rows if r["overall_score"] is not None]
                ts_idx = list(range(len(ts_scores)))
                n = len(ts_scores)
                mean_x = sum(ts_idx) / n
                mean_y = sum(ts_scores) / n
                num = sum((ts_idx[i] - mean_x) * (ts_scores[i] - mean_y) for i in range(n))
                den = sum((ts_idx[i] - mean_x) ** 2 for i in range(n))
                slope = num / den if den != 0 else 0.0
                if slope > 0.5:
                    direction = "deteriorating"
                elif slope < -0.5:
                    direction = "improving"
                else:
                    direction = "stable"
                trend_info = {"direction": direction, "slope": round(slope, 4), "data_points": n}
            elif len(rows) == 1:
                trend_info = {"direction": "insufficient_data", "slope": 0.0, "data_points": 1}

            conn.close()
        except Exception:
            pass

        # --- 4. Peer comparison (compare against global median) ---
        peer_comparison = {"percentile": None, "peer_count": 0, "median_score": None}
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            # Get latest scores for all locations
            all_latest = conn.execute(
                "SELECT location, overall_score FROM risk_summaries "
                "WHERE date = (SELECT MAX(date) FROM risk_summaries) "
                "ORDER BY overall_score ASC",
            ).fetchall()

            conn.close()

            if all_latest:
                all_scores_list = [float(r["overall_score"]) for r in all_latest if r["overall_score"] is not None]
                all_scores_list.sort()
                n_peers = len(all_scores_list)
                # Calculate percentile rank
                rank = sum(1 for s in all_scores_list if s < overall_score)
                percentile = round(rank / n_peers * 100, 1) if n_peers > 0 else None
                median_idx = n_peers // 2
                median_score = all_scores_list[median_idx] if all_scores_list else None

                peer_comparison = {
                    "percentile": percentile,
                    "peer_count": n_peers,
                    "median_score": median_score,
                    "interpretation": (
                        f"上位{100 - percentile:.0f}%（{n_peers}カ国中）。"
                        f"中央値は{median_score}。"
                        if percentile is not None and median_score is not None
                        else "比較データ不足"
                    ),
                }
        except Exception:
            pass

        # --- 5. Key alerts ---
        key_alerts = []
        critical_dims = [(k, v) for k, v in scores.items() if isinstance(v, (int, float)) and v >= 60]
        for dim, val in sorted(critical_dims, key=lambda x: -x[1]):
            alert_level = "CRITICAL" if val >= 80 else "HIGH"
            key_alerts.append({
                "dimension": dim,
                "score": val,
                "level": alert_level,
                "message": _get_explanation(dim, val),
            })

        # --- 6. Recommended actions ---
        recommended_actions = []
        if any(v >= 80 for _, v in critical_dims):
            recommended_actions.append("即時対応: CRITICALレベルのリスク次元について緊急レビューを実施してください。")
        if any(dim == "sanctions" and val > 0 for dim, val in scores.items()):
            recommended_actions.append("制裁リスク: 対象エンティティとの取引を法務部門と確認してください。")
        if overall_score >= 60:
            recommended_actions.append("代替サプライヤー: 高リスク地域の代替調達先を検討してください。")
        if any(dim in ("conflict", "political") and scores.get(dim, 0) >= 50 for dim in scores):
            recommended_actions.append("地政学モニタリング: 紛争/政治リスクの継続監視を強化してください。")
        if any(dim in ("disaster", "weather", "typhoon", "climate_risk") and scores.get(dim, 0) >= 40 for dim in scores):
            recommended_actions.append("BCP見直し: 自然災害・気候リスクに対するBCP（事業継続計画）を更新してください。")
        if not recommended_actions:
            recommended_actions.append("現状維持: リスクレベルは許容範囲内です。定期監視を継続してください。")

        return {
            "location": normalized_loc,
            "overall_score": overall_score,
            "risk_level": risk_level,
            "top_3_risks": top_3_risks,
            "trend": trend_info,
            "peer_comparison": peer_comparison,
            "key_alerts": key_alerts,
            "recommended_actions": recommended_actions,
            "all_scores": scores,
            "generated_at": datetime.utcnow().isoformat(),
            "report_format": "executive_summary",
        }
    except ValueError as e:
        return safe_error_response(e)


# ===========================================================================
#  STREAM 10: v0.8.0 BOM Risk Analysis & Tier-2+ Inference Tools
# ===========================================================================


@mcp.tool()
def infer_supply_chain(
    tier1_country: str,
    hs_code: str,
    material: str = "",
    max_depth: int = 3,
) -> dict:
    """Tier-1 サプライヤーの上流（Tier-2/3）を UN Comtrade 貿易データから推定。
    隠れたサプライチェーンリスクを可視化する。

    Args:
        tier1_country: Tier-1 サプライヤーの所在国（例: "South Korea"）
        hs_code: 対象材料の HS コード（例: "8507" = 電池）
        material: 材料名（表示用、例: "battery"）
        max_depth: 推定深度（2=Tier-2 まで, 3=Tier-3 まで）
    """
    from features.analytics.tier_inference import TierInferenceEngine

    engine = TierInferenceEngine()
    result = engine.estimate_risk_exposure(tier1_country, hs_code, material)

    # Add supply tree if max_depth specified
    if max_depth >= 2:
        tree = engine.build_full_supply_tree(
            tier1_country,
            [{"material": material, "hs_code": hs_code}],
            max_depth=max_depth,
        )
        result["supply_tree"] = [n.to_dict() for n in tree]

    return result


@mcp.tool()
def analyze_bom_risk(
    bom_json: str,
    product_name: str = "Product",
    include_tier2_inference: bool = False,
) -> dict:
    """BOM (部品表) のサプライチェーンリスクを分析。
    各部品のサプライヤー国リスク、集中度、ボトルネック、緩和策を返す。

    include_tier2_inference=True で Tier-2/3 推定を含めた隠れたリスクも算出。

    Args:
        bom_json: BOM データ JSON。形式:
            [{"part_id": "P001", "part_name": "バッテリーセル",
              "supplier_name": "Samsung SDI", "supplier_country": "South Korea",
              "material": "battery", "hs_code": "8507",
              "quantity": 100, "unit_cost_usd": 45.0, "is_critical": true}, ...]
        product_name: 製品名
        include_tier2_inference: Tier-2/3 推定を含めるか
    """
    from features.analytics.bom_analyzer import BOMAnalyzer, BOMNode

    data = json.loads(bom_json)
    if isinstance(data, dict):
        items = data.get("bom", data.get("parts", data.get("components", [])))
        product_name = data.get("product_name", product_name)
    else:
        items = data

    bom = []
    for item in items:
        bom.append(BOMNode(
            part_id=item.get("part_id", ""),
            part_name=item.get("part_name", ""),
            supplier_name=item.get("supplier_name", ""),
            supplier_country=item.get("supplier_country", ""),
            material=item.get("material", ""),
            hs_code=item.get("hs_code", ""),
            tier=item.get("tier", 1),
            quantity=float(item.get("quantity", 1)),
            unit_cost_usd=float(item.get("unit_cost_usd", 0)),
            is_critical=item.get("is_critical", False),
        ))

    analyzer = BOMAnalyzer()
    result = analyzer.analyze_bom(bom, product_name, include_tier2_inference)
    return result.to_dict()


@mcp.tool()
def get_hidden_risk_exposure(
    tier1_country: str,
    materials_json: str,
) -> dict:
    """Tier-1 サプライヤーの隠れたリスクエクスポージャーを一括分析。
    複数の材料/HSコードに対して、Tier-2/3 由来のリスク増分を算出。

    Args:
        tier1_country: Tier-1 サプライヤーの所在国
        materials_json: 材料リスト JSON。形式:
            [{"material": "battery", "hs_code": "8507"},
             {"material": "semiconductor", "hs_code": "8542"}]
    """
    from features.analytics.tier_inference import TierInferenceEngine

    materials = json.loads(materials_json)
    engine = TierInferenceEngine()

    exposures = []
    total_hidden_delta = 0.0

    for mat in materials:
        hs_code = mat.get("hs_code", "")
        material = mat.get("material", "")
        if not hs_code:
            continue

        exposure = engine.estimate_risk_exposure(tier1_country, hs_code, material)
        exposures.append(exposure)
        total_hidden_delta += exposure.get("hidden_risk_delta", 0)

    return {
        "tier1_country": tier1_country,
        "materials_analyzed": len(exposures),
        "total_hidden_risk_delta": round(total_hidden_delta, 1),
        "average_hidden_delta": round(total_hidden_delta / max(len(exposures), 1), 1),
        "exposures": exposures,
        "summary": (
            f"{tier1_country} の {len(exposures)} 材料を分析。"
            f"Tier-2/3 推定により合計 {total_hidden_delta:+.1f} ポイントの隠れたリスクを検出。"
        ),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ===========================================================================
#  STREAM 3-B: Forecast Accuracy Tool
# ===========================================================================


@mcp.tool()
def get_forecast_accuracy(days: int = 30) -> dict:
    """予測精度レポートを取得。累積MAE・トレンド・日次精度を返す。

    Args:
        days: 直近何日分のレポートを取得するか（デフォルト30日）
    """
    from features.timeseries.forecast_monitor import ForecastMonitor
    monitor = ForecastMonitor()
    report = monitor.get_accuracy_report(days)
    retrain = monitor.check_retrain_needed()
    report["retrain_check"] = retrain
    return report


# ===========================================================================
#  STREAM 4-B: Supplier Reputation Screening Tool
# ===========================================================================


@mcp.tool()
def screen_supplier_reputation(
    supplier_name: str,
    country: str = "",
    days_back: int = 180,
) -> dict:
    """サプライヤーの評判をGDELTニュース分析でスクリーニング。
    労働問題・腐敗・環境・安全性の4カテゴリで評価。

    Args:
        supplier_name: サプライヤー名（英語推奨）
        country: 国名（絞り込み用、オプション）
        days_back: 検索対象日数（デフォルト180日）
    """
    from features.screening.supplier_reputation import SupplierReputationScreener
    screener = SupplierReputationScreener()
    result = screener.screen_supplier(supplier_name, country, days_back)
    return result.to_dict()


# ===========================================================================
#  STREAM 5-B: Cost Impact Tools
# ===========================================================================


@mcp.tool()
def estimate_disruption_cost(
    scenario: str,
    annual_spend_usd: float = 1000000,
    daily_revenue_usd: float = 100000,
    duration_days: int = 60,
    risk_score: float = 50.0,
) -> dict:
    """サプライチェーン途絶シナリオの財務インパクトを試算。
    調達プレミアム・物流追加コスト・生産損失・復旧コストの4要素で算出。

    シナリオ: sanctions(制裁), conflict(紛争), disaster(災害),
              port_closure(港湾閉鎖), pandemic(パンデミック)

    Args:
        scenario: シナリオ名
        annual_spend_usd: 年間調達額 (USD)
        daily_revenue_usd: 1日あたり売上高 (USD)
        duration_days: 途絶期間 (日数)
        risk_score: リスクスコア (0-100)
    """
    from features.analytics.cost_impact_analyzer import CostImpactAnalyzer
    analyzer = CostImpactAnalyzer()
    result = analyzer.estimate_disruption_cost(
        scenario=scenario,
        annual_spend_usd=annual_spend_usd,
        daily_revenue_usd=daily_revenue_usd,
        duration_days=duration_days,
        risk_score=risk_score,
    )
    return result.to_dict()


@mcp.tool()
def compare_risk_scenarios(
    annual_spend_usd: float = 1000000,
    daily_revenue_usd: float = 100000,
    duration_days: int = 60,
    risk_score: float = 50.0,
) -> dict:
    """全途絶シナリオの財務インパクトを比較ランキング。
    最悪ケースの特定とシナリオ間の相対比較を提供。

    Args:
        annual_spend_usd: 年間調達額 (USD)
        daily_revenue_usd: 1日あたり売上高 (USD)
        duration_days: 途絶期間 (日数)
        risk_score: リスクスコア (0-100)
    """
    from features.analytics.cost_impact_analyzer import CostImpactAnalyzer
    analyzer = CostImpactAnalyzer()
    return analyzer.compare_scenarios(
        annual_spend_usd=annual_spend_usd,
        daily_revenue_usd=daily_revenue_usd,
        duration_days=duration_days,
        risk_score=risk_score,
    )


# ===========================================================================
#  TASK 6: Goods Layer (物レイヤー) Tools
# ===========================================================================


@mcp.tool()
def find_actual_suppliers(
    buyer_company: str,
    supplier_company: str = "",
) -> dict:
    """US税関データ(ImportYeti)で実際のサプライヤー関係を確認

    Args:
        buyer_company: バイヤー企業名（例: "APPLE INC"）
        supplier_company: サプライヤー企業名（オプション。指定時は特定サプライヤーとの関係を確認）
    """
    try:
        if supplier_company:
            # 特定サプライヤーとの関係を確認
            result = get_customs_supplier_evidence(buyer_company, supplier_company)
            return {
                "buyer": buyer_company,
                "supplier": supplier_company,
                "confirmed": result.get("confirmed", False),
                "evidence": result.get("evidence", []),
                "shipment_count": result.get("shipment_count", 0),
                "data_source": "US_CUSTOMS",
                "timestamp": datetime.utcnow().isoformat(),
            }
        else:
            # バイヤーの全サプライヤーを検索
            client = ImportYetiClient()
            suppliers = client.find_suppliers(buyer_company)
            return {
                "buyer": buyer_company,
                "supplier_count": len(suppliers),
                "suppliers": [
                    {
                        "name": s.supplier_name,
                        "country": s.supplier_country,
                        "shipment_count": s.shipment_count,
                        "latest_shipment": s.latest_shipment,
                        "product": s.product_description,
                        "hs_code": s.hs_code_detected,
                        "confidence": s.confidence,
                    }
                    for s in suppliers
                ],
                "data_source": "US_CUSTOMS",
                "timestamp": datetime.utcnow().isoformat(),
            }
    except Exception as e:
        return {
            "buyer": buyer_company,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def build_supply_chain_from_ir(
    companies: list[str],
    market: str = "auto",
) -> dict:
    """有報・10-Kからサプライチェーンを自動構築

    Args:
        companies: 企業名またはティッカーのリスト（例: ["AAPL", "トヨタ自動車"]）
        market: 市場指定 ("auto"=自動判定, "jp"=EDINET, "us"=SEC)
    """
    try:
        scraper = IRScraper()
        result = scraper.batch_build_tier1_graph(companies)
        result["market"] = market
        result["timestamp"] = datetime.utcnow().isoformat()
        return result
    except Exception as e:
        return {
            "companies": companies,
            "error": str(e),
            "nodes": [],
            "edges": [],
            "stats": {"companies_processed": 0, "total_suppliers_found": 0},
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def get_conflict_minerals_status(ticker: str) -> dict:
    """SEC紛争鉱物レポートから3TG使用状況を確認

    Args:
        ticker: ティッカーシンボル（例: "AAPL"）
    """
    try:
        scraper = IRScraper()
        report = scraper.scrape_conflict_minerals_report(ticker)
        return {
            "company": report.company,
            "filing_year": report.filing_year,
            "minerals_in_scope": report.minerals_in_scope,
            "smelters": report.smelters,
            "smelter_count": len(report.smelters),
            "drc_sourcing": report.drc_sourcing,
            "conflict_free_certified": report.conflict_free_certified,
            "data_source": "SEC_SD",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "company": ticker,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def analyze_product_complete(
    part_name: str,
    supplier_name: str,
    supplier_country: str,
    hs_code: str = "",
) -> dict:
    """物レイヤー統合分析 - 全データソースからの製品サプライチェーン分析

    Args:
        part_name: 部品名（例: "バッテリーセル"）
        supplier_name: サプライヤー名（例: "Samsung SDI"）
        supplier_country: サプライヤー所在国（例: "South Korea"）
        hs_code: HSコード（オプション、例: "8507"）
    """
    try:
        analyzer = GoodsLayerAnalyzer()
        result = analyzer.analyze_product(
            part_name=part_name,
            supplier_name=supplier_name,
            supplier_country=supplier_country,
            hs_code=hs_code,
        )
        return result.to_dict()
    except Exception as e:
        return {
            "part_name": part_name,
            "supplier_name": supplier_name,
            "supplier_country": supplier_country,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


# ===========================================================================
#  STREAM B: 人レイヤー (Person Layer) Tools
# ===========================================================================


@mcp.tool()
def screen_ownership_chain(company_name: str) -> dict:
    """UBO（実質的支配者）チェーンのリスクスクリーニング。
    OpenOwnership APIで所有構造を取得し、各UBOの制裁・PEP・オフショアリーク
    リスクをスコアリング。

    Args:
        company_name: 企業名（英語推奨）
    """
    try:
        # 1. UBO情報取得
        oo_client = OpenOwnershipClient()
        ubo_records = oo_client.get_ubo_sync(company_name)
        ownership_chain = oo_client.get_ownership_chain_sync(company_name)

        # 2. グラフ構築（スコアリングでネットワークリスクに使用）
        graph = PersonCompanyGraph()
        graph.build_from_ubo(company_name, ubo_records)

        # 3. リスクスコアリング（グラフ連携でネットワークリスク精密計算）
        scorer = PersonRiskScorer()
        chain_risk = scorer.score_ownership_chain(ubo_records, company_name, graph=graph)
        risk_exposure = graph.get_risk_exposure(company_name, max_hops=3)

        return {
            "company_name": company_name,
            "ubo_count": len(ubo_records),
            "ubo_records": [
                {
                    "person_name": r.person_name,
                    "nationality": r.nationality,
                    "ownership_pct": r.ownership_pct,
                    "is_pep": r.is_pep,
                    "sanctions_hit": r.sanctions_hit,
                }
                for r in ubo_records
            ],
            "ownership_chain": ownership_chain,
            "risk_assessment": chain_risk,
            "risk_exposure": risk_exposure,
            "graph_stats": graph.get_stats(),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "company_name": company_name,
            "error": str(e),
            "ubo_count": 0,
            "ubo_records": [],
            "risk_assessment": {"total_score": 0, "risk_level": "UNKNOWN"},
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def check_pep_connection(company_name: str, max_hops: int = 3) -> dict:
    """PEP（政治的露出者）接続検査。
    UBO・役員・取締役ネットワークから指定ホップ数以内のPEP接続を検出。

    Args:
        company_name: 企業名（英語推奨）
        max_hops: 最大探索ホップ数（デフォルト3）
    """
    max_hops = max(1, min(5, max_hops))
    try:
        graph = PersonCompanyGraph()

        # 1. UBOからグラフ構築
        oo_client = OpenOwnershipClient()
        ubo_records = oo_client.get_ubo_sync(company_name)
        graph.build_from_ubo(company_name, ubo_records)

        # 2. Wikidata役員・取締役からグラフ拡張
        wiki_client = WikidataClient()
        executives = wiki_client.get_executives_sync(company_name)
        board_members = wiki_client.get_board_members_sync(company_name)
        graph.build_from_wikidata(company_name, executives, board_members)

        # 3. リスクエクスポージャー分析
        exposure = graph.get_risk_exposure(company_name, max_hops=max_hops)

        # 4. PEP接続サマリー
        pep_connections = exposure.get("pep_persons", [])
        sanctioned_connections = exposure.get("sanctioned_persons", [])

        # リスク判定
        if sanctioned_connections:
            risk_level = "CRITICAL"
            summary = (
                f"{company_name} は {max_hops} ホップ以内に "
                f"{len(sanctioned_connections)} 名の制裁対象者を検出。即時対応が必要です。"
            )
        elif pep_connections:
            risk_level = "HIGH"
            summary = (
                f"{company_name} は {max_hops} ホップ以内に "
                f"{len(pep_connections)} 名のPEP（政治的露出者）を検出。"
                f"強化デューデリジェンス（EDD）を推奨します。"
            )
        else:
            risk_level = "LOW"
            summary = (
                f"{company_name} は {max_hops} ホップ以内にPEP・制裁対象者は検出されませんでした。"
            )

        return {
            "company_name": company_name,
            "max_hops": max_hops,
            "risk_level": risk_level,
            "summary": summary,
            "pep_connections": pep_connections,
            "sanctioned_connections": sanctioned_connections,
            "risk_exposure": exposure,
            "graph_stats": graph.get_stats(),
            "data_sources": {
                "ubo_records": len(ubo_records),
                "executives": len(executives),
                "board_members": len(board_members),
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "company_name": company_name,
            "max_hops": max_hops,
            "error": str(e),
            "risk_level": "UNKNOWN",
            "pep_connections": [],
            "sanctioned_connections": [],
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def get_officer_network(company_name: str) -> dict:
    """役員ネットワーク分析。
    Wikidataから経営幹部・取締役情報を取得し、兼任役員ネットワーク
    （インターロッキング・ダイレクトレート）を検出。
    ICIJ オフショアリークとの照合も実施。

    Args:
        company_name: 企業名（英語推奨）
    """
    try:
        # 1. Wikidata から役員情報取得
        wiki_client = WikidataClient()
        executives = wiki_client.get_executives_sync(company_name)
        board_members = wiki_client.get_board_members_sync(company_name)
        interlocking = wiki_client.find_interlocking_directorates_sync(company_name)

        # 2. グラフ構築
        graph = PersonCompanyGraph()
        graph.build_from_wikidata(company_name, executives, board_members)

        # 3. ICIJ オフショアリーク照合
        icij_client = ICIJClient()
        offshore_hits: list[dict] = []
        all_persons = set()
        for e in executives:
            name = e.name if hasattr(e, "name") else e.get("name", "")
            if name:
                all_persons.add(name)
        for m in board_members:
            name = m.name if hasattr(m, "name") else m.get("name", "")
            if name:
                all_persons.add(name)

        for person_name in all_persons:
            try:
                leaks = icij_client.search_entity_sync(person_name)
                if leaks:
                    offshore_hits.append({
                        "person_name": person_name,
                        "leak_count": len(leaks),
                        "sources": list(set(r.data_source for r in leaks)),
                        "details": [
                            {
                                "entity_name": r.entity_name,
                                "entity_type": r.entity_type,
                                "jurisdiction": r.jurisdiction,
                                "data_source": r.data_source,
                            }
                            for r in leaks[:5]
                        ],
                    })
            except Exception:
                pass

        # 4. リスクスコアリング（全役員 — グラフ連携でネットワークリスク精密計算）
        scorer = PersonRiskScorer()
        # 国籍情報を名前→国籍のマッピングで保持
        _nat_map: dict[str, str] = {}
        for e in executives:
            n = e.name if hasattr(e, "name") else e.get("name", "")
            nat = e.nationality if hasattr(e, "nationality") else e.get("nationality", "")
            if n and nat:
                _nat_map[n] = nat
        person_risks: list[dict] = []
        for person_name in all_persons:
            risk = scorer.score_person(
                person_name,
                nationality=_nat_map.get(person_name, ""),
                graph=graph,
            )
            person_risks.append(risk)
        person_risks.sort(key=lambda x: x.get("total_score", 0), reverse=True)

        return {
            "company_name": company_name,
            "executives": [
                {
                    "name": e.name,
                    "position": e.position,
                    "nationality": e.nationality,
                    "start_date": e.start_date,
                    "end_date": e.end_date,
                    "wikidata_id": e.wikidata_id,
                }
                for e in executives
            ],
            "board_members": [
                {
                    "name": m.name,
                    "board_role": m.board_role,
                    "other_boards": m.other_boards,
                    "wikidata_id": m.wikidata_id,
                }
                for m in board_members
            ],
            "interlocking_directorates": interlocking,
            "offshore_leak_hits": offshore_hits,
            "person_risk_scores": person_risks[:20],
            "graph_stats": graph.get_stats(),
            "graph_data": graph.to_dict(),
            "summary": {
                "total_executives": len(executives),
                "total_board_members": len(board_members),
                "total_unique_persons": len(all_persons),
                "offshore_leak_persons": len(offshore_hits),
                "interlocking_connections": interlocking.get("total_connections", 0),
                "connected_companies": len(interlocking.get("connected_companies", [])),
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "company_name": company_name,
            "error": str(e),
            "executives": [],
            "board_members": [],
            "summary": {"total_executives": 0, "total_board_members": 0},
            "timestamp": datetime.utcnow().isoformat(),
        }


# ===========================================================================
#  STREAM A: 物レイヤー (Goods Layer) MCP ツール — v0.9.0
# ===========================================================================


@mcp.tool()
def search_customs_records(company_name: str, country: str = "US") -> dict:
    """米国通関記録（船荷証券）を検索。
    ImportYeti の US Customs Bill-of-Lading データからシッパー/コンサイニー関係を取得。

    Args:
        company_name: 企業名（シッパーまたはコンサイニー）
        country: 対象国（現在は US のみ対応）
    """
    try:
        from pipeline.trade.importyeti_client import ImportYetiClient
        client = ImportYetiClient()
        shipments = client.get_shipments(company_name, limit=30)
        return {
            "company_name": company_name,
            "country": country,
            "record_count": len(shipments),
            "records": [
                {
                    "shipper": s.shipper_name,
                    "consignee": s.consignee_name,
                    "shipper_country": s.shipper_country,
                    "product": s.product_description[:120] if s.product_description else "",
                    "hs_code": s.hs_code,
                    "date": s.shipment_date,
                    "weight_kg": s.weight_kg,
                }
                for s in shipments[:20]
            ],
            "data_source": "ImportYeti_US_Customs",
            "note": "米国輸入データのみ対象。他国の通関データは含まない。",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "company_name": company_name,
            "error": str(e),
            "record_count": 0,
            "records": [],
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def get_supplier_materials(company_name: str) -> dict:
    """サプライヤーの取扱品目・バイヤー情報を取得。
    ImportYetiの税関データとIR（有報/10-K）からサプライヤーの詳細情報を統合。

    Args:
        company_name: サプライヤー企業名
    """
    result = {
        "company_name": company_name,
        "suppliers": [],
        "buyers": [],
        "ir_disclosures": [],
        "data_sources_used": [],
        "timestamp": datetime.utcnow().isoformat(),
    }

    # ImportYeti — サプライヤー情報
    try:
        from pipeline.trade.importyeti_client import ImportYetiClient
        client = ImportYetiClient()

        # サプライヤーとしての出荷先（バイヤー）
        buyers = client.find_buyers(company_name)
        result["buyers"] = [
            {
                "buyer_name": b.buyer_name,
                "buyer_country": b.buyer_country,
                "shipment_count": b.shipment_count,
                "product": b.product_description[:100] if b.product_description else "",
            }
            for b in buyers[:15]
        ]

        # バイヤーとしてのサプライヤー
        suppliers = client.find_suppliers(company_name)
        result["suppliers"] = [
            {
                "supplier_name": s.supplier_name,
                "supplier_country": s.supplier_country,
                "shipment_count": s.shipment_count,
                "product": s.product_description[:100] if s.product_description else "",
                "hs_code": s.hs_code_detected,
            }
            for s in suppliers[:15]
        ]
        result["data_sources_used"].append("ImportYeti_US_Customs")
    except Exception as e:
        result["importyeti_error"] = str(e)

    # IR Scraper — 有報/10-K 開示情報
    try:
        from pipeline.corporate.ir_scraper import IRScraper
        scraper = IRScraper()

        # 日本語を含むかで EDINET/SEC 切替
        is_jp = any("\u4e00" <= ch <= "\u9fff" or "\u30a0" <= ch <= "\u30ff"
                     for ch in company_name)

        disclosures = []
        if is_jp:
            disclosures = scraper.scrape_edinet_suppliers(company_name)
        else:
            disclosures = scraper.scrape_sec_10k_suppliers(company_name)
            if not disclosures:
                disclosures = scraper.scrape_edinet_suppliers(company_name)

        result["ir_disclosures"] = [
            {
                "supplier_name": d.supplier_name,
                "relationship": d.relationship,
                "disclosure_type": d.disclosure_type,
                "source": d.source,
                "confidence": d.confidence,
                "filing_date": d.filing_date,
            }
            for d in disclosures[:20]
        ]
        if disclosures:
            result["data_sources_used"].append(f"IR_{disclosures[0].source}")
    except Exception as e:
        result["ir_error"] = str(e)

    return result


@mcp.tool()
def analyze_goods_layer(product_name: str, bom_json: str = "[]") -> dict:
    """物レイヤー統合分析。
    SAP ERP・ImportYeti（US税関）・IR（有報/10-K）・BACI/Comtrade の
    4データソースを優先度付きで統合し、部品・BOM 単位でサプライヤー情報を
    確認度付きで返す。

    Args:
        product_name: 製品名（例: "リチウムイオンバッテリー"）
        bom_json: BOM部品表のJSON（[{"part_id":"MAT-001","part_name":"バッテリー","supplier_name":"LG","supplier_country":"KOR","hs_code":"8507"}, ...]）
    """
    try:
        from features.goods_layer.unified_api import GoodsLayerAnalyzer
        analyzer = GoodsLayerAnalyzer()

        bom_parts = json.loads(bom_json) if bom_json else []

        if bom_parts:
            # BOM モードで分析
            bom_result = analyzer.analyze_bom(bom_parts)
            bom_result["product_name"] = product_name
            bom_result["analysis_mode"] = "bom"

            # データ完全性レポートを追加
            completeness = analyzer.get_data_completeness_report()
            bom_result["data_completeness"] = completeness
            bom_result["timestamp"] = datetime.utcnow().isoformat()
            return bom_result
        else:
            # 単品モード — product_name をキーに分析
            result = analyzer.analyze_product(
                part_id="QUERY-001",
                part_name=product_name,
                supplier_name=product_name,
                supplier_country="",
            )
            result["product_name"] = product_name
            result["analysis_mode"] = "single_product"

            completeness = analyzer.get_data_completeness_report()
            result["data_completeness"] = completeness
            result["timestamp"] = datetime.utcnow().isoformat()
            return result
    except Exception as e:
        return {
            "product_name": product_name,
            "error": str(e),
            "analysis_mode": "error",
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def get_conflict_mineral_report(company_name: str) -> dict:
    """紛争鉱物レポート取得。
    SEC SD (Exhibit 1.01) からスズ・タンタル・タングステン・金・コバルトの
    調達状況とスメルター情報を取得。

    Args:
        company_name: 企業名またはティッカーシンボル（例: "AAPL", "トヨタ自動車"）
    """
    try:
        from pipeline.corporate.ir_scraper import IRScraper
        scraper = IRScraper()

        # ティッカーシンボル判定（英字のみかつ短い）
        cleaned = company_name.replace("-", "").replace(".", "")
        is_ticker = cleaned.isalpha() and cleaned.isascii() and len(cleaned) <= 6

        if is_ticker:
            report = scraper.scrape_conflict_minerals_report(company_name)
            return {
                "company_name": company_name,
                "filing_year": report.filing_year,
                "minerals_in_scope": report.minerals_in_scope,
                "smelter_count": len(report.smelters),
                "smelters": report.smelters[:30],
                "drc_sourcing": report.drc_sourcing,
                "conflict_free_certified": report.conflict_free_certified,
                "data_source": "SEC_SD_Exhibit_1.01",
                "note": "米国SEC提出のSD filing (紛争鉱物開示) から抽出。",
                "timestamp": datetime.utcnow().isoformat(),
            }
        else:
            # 日本企業などティッカーでない場合 — EDINET から関連情報を抽出
            disclosures = scraper.scrape_edinet_suppliers(company_name)
            mineral_related = [
                d for d in disclosures
                if any(kw in d.supplier_name for kw in
                       ["鉱山", "鉱業", "金属", "製錬", "Metal", "Mining", "Smelter"])
            ]
            return {
                "company_name": company_name,
                "filing_year": None,
                "minerals_in_scope": [],
                "smelter_count": 0,
                "smelters": [],
                "drc_sourcing": "unknown",
                "conflict_free_certified": None,
                "mineral_related_suppliers": [
                    {
                        "name": d.supplier_name,
                        "relationship": d.relationship,
                        "source": d.source,
                    }
                    for d in mineral_related
                ],
                "data_source": "EDINET",
                "note": "日本企業の場合、SEC SDは未提出。有報から鉱物関連サプライヤーを抽出。",
                "timestamp": datetime.utcnow().isoformat(),
            }
    except Exception as e:
        return {
            "company_name": company_name,
            "error": str(e),
            "minerals_in_scope": [],
            "smelters": [],
            "timestamp": datetime.utcnow().isoformat(),
        }


# ===========================================================================
#  ROLE-D: ネットワーク脆弱性分析 & 調達最適化ツール — v1.0.0
# ===========================================================================


@mcp.tool()
def analyze_network_vulnerability(bom_json: str = "", buyer_company: str = "") -> dict:
    """サプライヤーネットワーク脆弱性分析。
    BOM または企業名からサプライチェーングラフを構築し、
    中心性分析・単一障害点・カスケード障害シミュレーションを実施。

    Args:
        bom_json: BOM データ JSON（analyze_bom_risk と同形式）。
            指定時はBOMからグラフを構築。
        buyer_company: バイヤー企業名。bom_json が空の場合、
            supply chain graph builder からグラフを取得。
    """
    try:
        import networkx as nx
        from features.analytics.network_vulnerability import NetworkVulnerabilityAnalyzer

        analyzer = NetworkVulnerabilityAnalyzer()
        G = nx.Graph()

        if bom_json and bom_json.strip() not in ("", "[]", "{}"):
            # BOM からグラフを構築
            data = json.loads(bom_json)
            if isinstance(data, dict):
                items = data.get("bom", data.get("parts", data.get("components", [])))
            else:
                items = data

            # バイヤーノード
            buyer_node = buyer_company or "Buyer"
            G.add_node(buyer_node, node_type="buyer")

            for item in items:
                supplier = item.get("supplier_name", "Unknown")
                country = item.get("supplier_country", "")
                material = item.get("material", item.get("part_name", ""))

                # サプライヤーノード
                G.add_node(supplier, node_type="supplier", country=country)
                # バイヤー ↔ サプライヤー辺
                G.add_edge(buyer_node, supplier, material=material)

                # 同じ国のサプライヤー間にも辺を追加（地理的相関）
                for other in G.nodes():
                    if (other != supplier and other != buyer_node
                            and G.nodes[other].get("country") == country
                            and not G.has_edge(supplier, other)):
                        G.add_edge(supplier, other, relation="same_country")

        elif buyer_company:
            # supply chain graph builder からグラフ取得を試みる
            try:
                scg = build_supply_chain_graph(buyer_company, "jp", depth=2)
                viz = graph_to_visualization_data(scg)
                for node_data in viz.get("nodes", []):
                    node_id = node_data.get("id", node_data.get("name", ""))
                    G.add_node(node_id, **{k: v for k, v in node_data.items() if k != "id"})
                for edge_data in viz.get("edges", viz.get("links", [])):
                    src = edge_data.get("source", "")
                    tgt = edge_data.get("target", "")
                    if src and tgt:
                        G.add_edge(src, tgt)
            except Exception as e:
                return {
                    "error": f"グラフ構築に失敗: {str(e)}",
                    "buyer_company": buyer_company,
                    "timestamp": datetime.utcnow().isoformat(),
                }
        else:
            return {
                "error": "bom_json または buyer_company のいずれかを指定してください。",
                "timestamp": datetime.utcnow().isoformat(),
            }

        if G.number_of_nodes() == 0:
            return {
                "error": "グラフにノードがありません。入力データを確認してください。",
                "timestamp": datetime.utcnow().isoformat(),
            }

        # 総合脆弱性レポートを生成
        report = analyzer.generate_vulnerability_report(G)
        report["buyer_company"] = buyer_company or "BOM-based"
        report["graph_source"] = "bom" if bom_json else "supply_chain_graph"
        return report

    except Exception as e:
        return {
            "error": str(e),
            "buyer_company": buyer_company,
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def optimize_procurement(
    bom_json: str,
    max_cost_increase_pct: float = 15.0,
    min_countries: int = 2,
    max_single_share: float = 0.6,
) -> dict:
    """調達ポートフォリオ最適化。
    BOM のリスク×コストを最小化するサプライヤー配分を scipy で算出。
    コスト制約・多様化制約を満たす最適調達ミックスを提案。

    Args:
        bom_json: BOM データ JSON。形式:
            [{"part_id": "P001", "supplier_name": "Samsung SDI",
              "supplier_country": "South Korea", "unit_cost_usd": 45.0,
              "quantity": 100, "share": 0.4}, ...]
        max_cost_increase_pct: コスト増加上限（%、デフォルト15%）
        min_countries: 最低調達国数（デフォルト2）
        max_single_share: 単一サプライヤー最大シェア（0-1、デフォルト0.6）
    """
    try:
        from features.analytics.procurement_optimizer import ProcurementOptimizer

        data = json.loads(bom_json)
        if isinstance(data, dict):
            items = data.get("bom", data.get("parts", data.get("components", [])))
        else:
            items = data

        optimizer = ProcurementOptimizer()
        result = optimizer.optimize_supplier_mix(
            current_bom=items,
            constraints={
                "max_cost_increase_pct": max_cost_increase_pct,
                "min_diversification": min_countries,
                "max_single_share": max_single_share,
            },
        )

        # 代替国提案も追加
        current_countries = list(set(
            item.get("supplier_country", "") for item in items if item.get("supplier_country")
        ))
        if current_countries:
            # 材料を推定
            materials = set(
                item.get("material", "") for item in items if item.get("material")
            )
            material = list(materials)[0] if materials else ""
            alternatives = optimizer.suggest_alternative_countries(
                current_countries, material, top_n=5,
            )
            result["alternative_countries"] = alternatives

        return result

    except Exception as e:
        return {
            "error": str(e),
            "feasible": False,
            "timestamp": datetime.utcnow().isoformat(),
        }


# ===========================================================================
#  ROLE-B: 統合グラフエンジン & 3ホップ制裁検索 — v1.0.0
# ===========================================================================


@mcp.tool()
def find_sanction_network_exposure(entity_name: str, max_hops: int = 3) -> dict:
    """3ホップ制裁ネットワーク検索。
    指定エンティティからBFS探索を行い、max_hops以内の制裁対象ノードを検出。
    スコア: 1ホップ=100, 2ホップ=70, 3ホップ=40。
    PageRankベースのネットワークリスク伝播スコアも算出。

    Args:
        entity_name: 検索起点の企業名または人物名
        max_hops: 探索最大ホップ数（1-5、デフォルト3）
    """
    try:
        from features.graph.unified_graph import SCIGraph
        from features.graph.sanction_path_finder import SanctionPathFinder
        from features.graph.graph_builder_v2 import SCIGraphBuilder
        import asyncio

        max_hops = max(1, min(5, max_hops))

        # まず制裁スクリーニングで直接マッチを確認
        direct_hit = screen_entity(entity_name)

        # グラフを構築（企業グラフビルダーを活用）
        graph = SCIGraph()
        graph.add_company(entity_name)

        # OpenCorporates でTier-2まで展開
        try:
            oc_graph = build_supply_chain_graph(entity_name, depth=2)
            for node, attrs in oc_graph.nodes(data=True):
                if node != entity_name:
                    graph.add_company(node, country=attrs.get("country", ""))
            for src, dst, attrs in oc_graph.edges(data=True):
                graph.add_supply_relation(src, dst, source="opencorporates")
        except Exception:
            pass

        # 人物レイヤーも追加
        try:
            from pipeline.corporate.openownership_client import OpenOwnershipClient
            oo_client = OpenOwnershipClient()
            companies_to_check = [entity_name] + [
                n["id"] for n in graph.get_nodes_by_type("company")
                if n["id"] != entity_name
            ][:5]
            for co in companies_to_check:
                try:
                    ubo_records = oo_client.search_ubo(co)
                    for ubo in (ubo_records or []):
                        if hasattr(ubo, "person_name"):
                            name, nat, pct = ubo.person_name, ubo.nationality, ubo.ownership_pct
                            sanctioned = ubo.sanctions_hit
                        elif isinstance(ubo, dict):
                            name = ubo.get("person_name", ubo.get("name", ""))
                            nat = ubo.get("nationality", "")
                            pct = ubo.get("ownership_pct", 0)
                            sanctioned = ubo.get("sanctions_hit", False)
                        else:
                            continue
                        if name:
                            graph.add_person(name, nationality=nat, sanctioned=sanctioned)
                            graph.add_ownership(name, co, share_pct=pct)
                except Exception:
                    pass
        except ImportError:
            pass

        # 全ノードの制裁スクリーニング
        for nid in list(graph.G.nodes()):
            if nid == entity_name:
                continue
            try:
                result = screen_entity(nid)
                if result.matched:
                    graph.G.nodes[nid]["sanctioned"] = True
                    graph.G.nodes[nid]["sanction_source"] = result.source
            except Exception:
                pass

        # パス検索
        finder = SanctionPathFinder(graph)
        exposure = finder.find_sanction_exposure(entity_name, max_hops)
        network_risk = finder.get_network_risk_score(entity_name, radius=max_hops)

        # D3可視化データ
        try:
            from features.graph.graph_visualizer import to_d3_json
            vis_data = to_d3_json(graph)
        except Exception:
            vis_data = graph.to_dict()

        return {
            "entity": entity_name,
            "direct_sanction_hit": direct_hit.matched if direct_hit else False,
            "direct_match_score": direct_hit.match_score if direct_hit else 0,
            "direct_source": direct_hit.source if direct_hit and direct_hit.matched else None,
            "network_exposure": exposure,
            "network_risk_score": network_risk,
            "graph_stats": graph.get_stats(),
            "visualization": vis_data,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "entity": entity_name,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def build_supply_chain_graph_tool(
    bom_input: str,
    buyer_company: str = "",
    include_ownership: bool = True,
    include_directors: bool = True,
) -> dict:
    """BOMからサプライチェーン統合グラフを構築。
    BOM分析→Tier推定→所有構造→役員→通関確定のパイプラインを実行し、
    D3.js可視化データ・リスクハイライト・統計を返す。

    Args:
        bom_input: BOM データ JSON（analyze_bom_risk と同形式）
        buyer_company: バイヤー企業名
        include_ownership: UBO所有構造を含めるか
        include_directors: 役員情報を含めるか
    """
    try:
        from features.graph.graph_builder_v2 import build_full_graph_sync
        from features.graph.graph_visualizer import to_d3_json, generate_risk_highlights
        from features.graph.sanction_path_finder import SanctionPathFinder

        include_people = include_ownership or include_directors
        graph = build_full_graph_sync(bom_input, buyer_company, include_people)

        # 可視化データ
        vis_data = to_d3_json(graph)

        # リスクハイライト
        highlights = generate_risk_highlights(graph)

        # 制裁エクスポージャ（バイヤーが指定されている場合）
        sanction_info = None
        if buyer_company and buyer_company in graph.G:
            finder = SanctionPathFinder(graph)
            sanction_info = finder.find_sanction_exposure(buyer_company, max_hops=3)

        return {
            "buyer_company": buyer_company,
            "graph_stats": graph.get_stats(),
            "visualization": vis_data,
            "risk_highlights": highlights,
            "sanction_exposure": sanction_info,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "error": str(e),
            "buyer_company": buyer_company,
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def get_network_risk_score(entity_name: str, radius: int = 2) -> dict:
    """PageRankベースのネットワークリスク伝播スコアを算出。
    指定エンティティ周辺のサブグラフを構築し、制裁・高リスクノードからの
    リスク伝播をPageRankで計算する。

    Args:
        entity_name: 対象企業名または人物名
        radius: 探索半径ホップ数（1-5、デフォルト2）
    """
    try:
        from features.graph.unified_graph import SCIGraph
        from features.graph.sanction_path_finder import SanctionPathFinder

        radius = max(1, min(5, radius))

        # グラフ構築
        graph = SCIGraph()
        graph.add_company(entity_name)

        # OpenCorporates で関連企業を取得
        try:
            oc_graph = build_supply_chain_graph(entity_name, depth=radius)
            for node, attrs in oc_graph.nodes(data=True):
                graph.add_company(node, country=attrs.get("country", ""))
            for src, dst, attrs in oc_graph.edges(data=True):
                graph.add_supply_relation(src, dst, source="opencorporates")
        except Exception:
            pass

        # 制裁スクリーニング
        for nid in list(graph.G.nodes()):
            try:
                result = screen_entity(nid)
                if result.matched:
                    graph.G.nodes[nid]["sanctioned"] = True
                    graph.G.nodes[nid]["risk_score"] = 100
            except Exception:
                pass

        # スコア算出
        finder = SanctionPathFinder(graph)
        score = finder.get_network_risk_score(entity_name, radius)
        report = finder.get_full_exposure_report(entity_name, max_hops=radius)

        return {
            "entity": entity_name,
            "network_risk_score": score,
            "risk_level": report.get("risk_level", "LOW"),
            "recommendation": report.get("recommendation", ""),
            "graph_stats": graph.get_stats(),
            "sanction_exposure": report.get("sanction_exposure", {}),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("ネットワークリスクスコア算出エラー: %s", e, exc_info=True)
        return {
            "entity": entity_name,
            "error": "ネットワークリスクスコアの算出で内部エラーが発生しました",
            "network_risk_score": 0,
            "timestamp": datetime.utcnow().isoformat(),
        }


# ===========================================================================
#  SCRI v1.1.0: デジタルツイン分析ツール (ROLE-D)
# ===========================================================================

# --- ROLE-B/C 依存モジュール ---
_STOCKOUT_PREDICTOR = None
_PRODUCTION_CASCADE = None
_EMERGENCY_PROCUREMENT = None
_FACILITY_RISK_MAPPER = None
_TRANSPORT_RISK = None

try:
    from features.digital_twin.stockout_predictor import StockoutPredictor
    _STOCKOUT_PREDICTOR = StockoutPredictor()
except (ImportError, Exception):
    pass

try:
    from features.digital_twin.production_cascade import ProductionCascadeSimulator
    _PRODUCTION_CASCADE = ProductionCascadeSimulator()
except (ImportError, Exception):
    pass

try:
    from features.digital_twin.emergency_procurement import EmergencyProcurementOptimizer
    _EMERGENCY_PROCUREMENT = EmergencyProcurementOptimizer()
except (ImportError, Exception):
    pass

try:
    from features.digital_twin.facility_risk_mapper import FacilityRiskMapper
    _FACILITY_RISK_MAPPER = FacilityRiskMapper()
except (ImportError, Exception):
    pass

try:
    from features.digital_twin.transport_risk import TransportRiskAnalyzer
    _TRANSPORT_RISK = TransportRiskAnalyzer()
except (ImportError, Exception):
    pass


@mcp.tool()
def scan_stockout_risks(location_id: str = "", risk_threshold: int = 50) -> dict:
    """在庫枯渇リスク全部品スキャン。
    内部データ（在庫・発注・生産計画）を基に、安全在庫を下回るリスクのある
    全部品を検出。リスクスコア順にソート。

    Args:
        location_id: 拠点ID（空=全拠点スキャン）
        risk_threshold: リスク閾値（0-100、この値以上のみ返す）
    """
    risk_threshold = min(max(int(risk_threshold), 0), 100)
    if _STOCKOUT_PREDICTOR is None:
        return {
            "message": "StockoutPredictor は現在実装中です。サンプルデータで動作確認してください。",
            "status": "not_implemented",
            "timestamp": datetime.utcnow().isoformat(),
        }
    try:
        result = _STOCKOUT_PREDICTOR.scan_all_parts(
            location_id=location_id or "",
            risk_threshold=risk_threshold,
        )
        return {
            "location_id": location_id or "ALL",
            "risk_threshold": risk_threshold,
            "results": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("在庫枯渇スキャンエラー: %s", e, exc_info=True)
        return {
            "error": "在庫枯渇スキャンで内部エラーが発生しました",
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def simulate_production_impact(part_id: str, shortage_days: int, product_id: str = "") -> dict:
    """部品欠品の生産カスケードシミュレーション。
    特定部品が欠品した場合、BOM依存関係を辿って影響を受ける全製品の
    生産遅延日数・損失額を推定。

    Args:
        part_id: 欠品部品のID
        shortage_days: 欠品日数
        product_id: 対象製品ID（空=全製品の影響を計算）
    """
    shortage_days = min(max(int(shortage_days), 1), 365)
    if _PRODUCTION_CASCADE is None:
        return {
            "message": "ProductionCascadeSimulator は現在実装中です。サンプルデータで動作確認してください。",
            "status": "not_implemented",
            "timestamp": datetime.utcnow().isoformat(),
        }
    try:
        result = _PRODUCTION_CASCADE.simulate_part_shortage(
            part_id=part_id,
            shortage_days=shortage_days,
        )
        return {
            "part_id": part_id,
            "shortage_days": shortage_days,
            "product_id": product_id or "ALL",
            "cascade_impact": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("生産カスケードエラー: %s", e, exc_info=True)
        return {
            "part_id": part_id,
            "error": "生産カスケードシミュレーションで内部エラーが発生しました",
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def get_emergency_procurement_plan(
    part_id: str,
    required_qty: int,
    deadline_date: str,
    budget_limit_jpy: int = 0,
) -> dict:
    """緊急調達最適計画。
    欠品部品の代替調達先を検索し、リードタイム・コスト・リスクを考慮した
    最適な調達計画を提案。複数ソース分割も提案。

    Args:
        part_id: 緊急調達が必要な部品ID
        required_qty: 必要数量
        deadline_date: 納期（YYYY-MM-DD形式）
        budget_limit_jpy: 予算上限（円、0=無制限）
    """
    required_qty = max(int(required_qty), 1)
    if _EMERGENCY_PROCUREMENT is None:
        return {
            "message": "EmergencyProcurementOptimizer は現在実装中です。サンプルデータで動作確認してください。",
            "status": "not_implemented",
            "timestamp": datetime.utcnow().isoformat(),
        }
    try:
        result = _EMERGENCY_PROCUREMENT.optimize_emergency_order(
            part_id=part_id,
            required_qty=required_qty,
            deadline_date=deadline_date,
            budget_limit_jpy=budget_limit_jpy or None,
        )
        return {
            "part_id": part_id,
            "required_qty": required_qty,
            "deadline_date": deadline_date,
            "budget_limit_jpy": budget_limit_jpy,
            "procurement_plan": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("緊急調達エラー: %s", e, exc_info=True)
        return {
            "part_id": part_id,
            "error": "緊急調達計画の生成で内部エラーが発生しました",
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def analyze_transport_risks(
    origin_country: str,
    dest_country: str,
    cargo_value_jpy: int = 0,
    transport_mode: str = "sea",
) -> dict:
    """輸送ルートリスク分析。
    出発国から到着国への輸送における地政学・海上・気象・港湾混雑等の
    リスクを総合評価。チョークポイント通過リスクも算出。

    Args:
        origin_country: 出発国（ISO2コード or 国名）
        dest_country: 到着国（ISO2コード or 国名）
        cargo_value_jpy: 貨物価値（円、保険料計算用）
        transport_mode: 輸送モード（sea/air/rail/truck）
    """
    if _TRANSPORT_RISK is None:
        return {
            "message": "TransportRiskAnalyzer は現在実装中です。サンプルデータで動作確認してください。",
            "status": "not_implemented",
            "timestamp": datetime.utcnow().isoformat(),
        }
    try:
        shipment = {
            "shipment_id": f"{origin_country}-{dest_country}",
            "origin": origin_country,
            "destination": dest_country,
            "cargo_value_jpy": cargo_value_jpy or 0,
            "transport_mode": transport_mode,
        }
        results_list = _TRANSPORT_RISK.analyze_scheduled_shipments(
            shipments=[shipment],
        )
        result = results_list[0] if results_list else {}
        return {
            "origin": origin_country,
            "destination": dest_country,
            "transport_mode": transport_mode,
            "cargo_value_jpy": cargo_value_jpy,
            "analysis": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("輸送リスク分析エラー: %s", e, exc_info=True)
        return {
            "origin": origin_country,
            "destination": dest_country,
            "error": "輸送リスク分析で内部エラーが発生しました",
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def get_facility_risk_map() -> dict:
    """全拠点リスクヒートマップ。
    登録済み全拠点の自然災害・地政学・インフラ・治安リスクを
    一括評価し、ヒートマップデータとして返す。

    Returns:
        拠点ごとのリスクスコアと座標情報
    """
    if _FACILITY_RISK_MAPPER is None:
        return {
            "message": "FacilityRiskMapper は現在実装中です。サンプルデータで動作確認してください。",
            "status": "not_implemented",
            "timestamp": datetime.utcnow().isoformat(),
        }
    try:
        result = _FACILITY_RISK_MAPPER.map_facility_risks()
        return {
            "facility_risks": result if isinstance(result, (dict, list)) else str(result),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("拠点リスクマップエラー: %s", e, exc_info=True)
        return {
            "error": "拠点リスクマップの生成で内部エラーが発生しました",
            "timestamp": datetime.utcnow().isoformat(),
        }


@mcp.tool()
def run_scenario_simulation(
    scenario: str,
    duration_days: int = 30,
    affected_countries: str = "",
) -> dict:
    """What-Ifシナリオシミュレーション。
    仮想的な災害・紛争・パンデミック等のシナリオに対する
    サプライチェーン全体への影響をシミュレーション。

    Args:
        scenario: シナリオ名（earthquake, pandemic, port_closure, sanctions, war, typhoon）
        duration_days: シミュレーション期間（日）
        affected_countries: 影響国リスト（カンマ区切り、例: "JP,CN,TW"）
    """
    duration_days = min(max(int(duration_days), 1), 365)
    valid_scenarios = ["earthquake", "pandemic", "port_closure", "sanctions", "war", "typhoon"]
    if scenario not in valid_scenarios:
        return {
            "error": f"無効なシナリオ: {scenario}。有効値: {', '.join(valid_scenarios)}",
            "timestamp": datetime.utcnow().isoformat(),
        }

    countries = [c.strip() for c in affected_countries.split(",") if c.strip()] if affected_countries else []

    results = {
        "scenario": scenario,
        "duration_days": duration_days,
        "affected_countries": countries,
        "impacts": {},
    }

    # 在庫枯渇影響 — simulate_risk_event() を使用
    if _STOCKOUT_PREDICTOR:
        try:
            stockout_results = _STOCKOUT_PREDICTOR.simulate_risk_event(
                scenario=scenario, affected_countries=countries, duration_days=duration_days,
            )
            critical = [r for r in stockout_results if r.get("severity") == "CRITICAL"]
            results["impacts"]["stockout"] = {
                "total_affected_parts": len(stockout_results),
                "critical_parts": len(critical),
                "details": stockout_results[:10],
            }
        except Exception as e:
            logger.error("シナリオ影響(在庫枯渇)エラー: %s", e, exc_info=True)
            results["impacts"]["stockout"] = {"error": "在庫枯渇影響の算出で内部エラーが発生しました"}
    else:
        results["impacts"]["stockout"] = {"status": "not_implemented"}

    # 生産カスケード影響 — calculate_production_resilience() を使用
    if _PRODUCTION_CASCADE:
        try:
            resilience = _PRODUCTION_CASCADE.calculate_production_resilience(plant_id="ALL")
            results["impacts"]["production_cascade"] = {
                "resilience_score": resilience.get("resilience_score", 0),
                "scenario": scenario,
                "duration_days": duration_days,
                "details": resilience,
            }
        except Exception as e:
            logger.error("シナリオ影響(生産カスケード)エラー: %s", e, exc_info=True)
            results["impacts"]["production_cascade"] = {"error": "生産カスケード影響の算出で内部エラーが発生しました"}
    else:
        results["impacts"]["production_cascade"] = {"status": "not_implemented"}

    # 輸送影響 — analyze_scheduled_shipments() を使用
    if _TRANSPORT_RISK:
        try:
            transport_results = _TRANSPORT_RISK.analyze_scheduled_shipments(
                shipments=[], lookahead_days=duration_days,
            )
            high_risk = [r for r in transport_results if r.get("recommendation") == "REROUTE"]
            results["impacts"]["transport"] = {
                "total_shipments_analyzed": len(transport_results),
                "reroute_recommended": len(high_risk),
                "details": transport_results[:10],
            }
        except Exception as e:
            logger.error("シナリオ影響(輸送)エラー: %s", e, exc_info=True)
            results["impacts"]["transport"] = {"error": "輸送影響の算出で内部エラーが発生しました"}
    else:
        results["impacts"]["transport"] = {"status": "not_implemented"}

    # 拠点影響 — identify_concentration_risk() を使用
    if _FACILITY_RISK_MAPPER:
        try:
            concentration = _FACILITY_RISK_MAPPER.identify_concentration_risk()
            affected = [a for a in concentration.get("alerts", [])
                        if any(c in str(a) for c in countries)] if countries else concentration.get("alerts", [])
            results["impacts"]["facilities"] = {
                "concentration_risk": concentration,
                "affected_by_scenario": affected,
            }
        except Exception as e:
            logger.error("シナリオ影響(拠点)エラー: %s", e, exc_info=True)
            results["impacts"]["facilities"] = {"error": "拠点影響の算出で内部エラー���発生しました"}
    else:
        results["impacts"]["facilities"] = {"status": "not_implemented"}

    # 全モジュール未実装の場合
    all_not_impl = all(
        isinstance(v, dict) and v.get("status") == "not_implemented"
        for v in results["impacts"].values()
    )
    if all_not_impl:
        results["message"] = "デジタルツイン機能は現在実装中です。サンプルデータで動作確認してください。"

    results["timestamp"] = datetime.utcnow().isoformat()
    return results


# ---------------------------------------------------------------------------
#  STREAM v1.3.0: インバウンド観光リスク評価ツール (ROLE-E)
# ---------------------------------------------------------------------------

# 遅延インポート（他ROLEが未完成でもエラーにならない）
_inbound_scorer = None
_regional_dist_model = None

try:
    from features.tourism.inbound_risk_scorer import InboundTourismRiskScorer
    _inbound_scorer = InboundTourismRiskScorer()
except (ImportError, Exception) as _e:
    logger.warning("InboundTourismRiskScorer 初期化失敗: %s", _e)

try:
    from features.tourism.regional_distribution import RegionalDistributionModel
    _regional_dist_model = RegionalDistributionModel()
except (ImportError, Exception) as _e:
    logger.warning("RegionalDistributionModel 初期化失敗: %s", _e)

try:
    from pipeline.tourism.competitor_stats_client import CompetitorStatsClient
    _competitor_stats_client = CompetitorStatsClient()
except (ImportError, Exception):
    _competitor_stats_client = None

# ソースマーケット・競合DB（ROLE-A/B依存）
_source_market_clients = {}
try:
    from pipeline.tourism.source_markets import (
        ChinaSourceMarketClient, KoreaSourceMarketClient,
    )
    _source_market_clients["CHN"] = ChinaSourceMarketClient()
    _source_market_clients["KOR"] = KoreaSourceMarketClient()
except (ImportError, Exception):
    pass

try:
    from pipeline.tourism.source_markets import TaiwanSourceMarketClient
    _source_market_clients["TWN"] = TaiwanSourceMarketClient()
except (ImportError, Exception):
    pass

_competitor_db = None
try:
    from pipeline.tourism.competitors import CompetitorDatabase
    _competitor_db = CompetitorDatabase()
except (ImportError, Exception):
    pass

# 資本フロークライアント（ROLE-D依存）
_capital_flow_client = None
try:
    from pipeline.financial.capital_flow_client import CapitalFlowRiskClient
    _capital_flow_client = CapitalFlowRiskClient()
except (ImportError, Exception):
    pass


@mcp.tool()
def get_capital_flow_risk(country: str) -> dict:
    """国の資金フローリスク評価。Chinn-Ito資本開放度・IMF送金規制・SWIFT除外リスクを統合。"""
    try:
        validated = validate_country(country)
        if "error" in validated:
            return safe_error_response(validated["error"])

        if _capital_flow_client is not None:
            try:
                result = _capital_flow_client.assess(country)
                return {"status": "ok", **result}
            except Exception:
                logger.warning("CapitalFlowRiskClient エラー（フォールバック使用）")

        # フォールバック: ハードコードデータによる推定
        # SWIFT除外国
        swift_excluded = {"RUS", "BLR", "IRN", "PRK", "SYR", "CUB"}
        # 資本規制が厳しい国
        closed_economies = {"CHN": 65, "RUS": 80, "IRN": 85, "PRK": 95,
                            "CUB": 90, "VEN": 75, "BLR": 78, "SYR": 88}
        # 開放経済
        open_economies = {"USA": 12, "GBR": 10, "SGP": 8, "JPN": 15,
                          "DEU": 11, "AUS": 13, "CAN": 12, "CHE": 9,
                          "HKG": 7, "NZL": 14}

        iso3 = validated.get("iso3", country.upper())

        if iso3 in swift_excluded:
            score = max(closed_economies.get(iso3, 75), 70)
            swift_risk = True
        else:
            score = closed_economies.get(iso3, open_economies.get(iso3, 40))
            swift_risk = False

        return {
            "status": "fallback",
            "country": iso3,
            "capital_flow_risk_score": score,
            "risk_level": (
                "CRITICAL" if score >= 80 else
                "HIGH" if score >= 60 else
                "MEDIUM" if score >= 40 else
                "LOW" if score >= 20 else "MINIMAL"
            ),
            "components": {
                "chinn_ito_openness": 100 - score,
                "swift_exclusion": swift_risk,
                "remittance_restriction": score > 50,
            },
            "message": "CapitalFlowRiskClient 未初期化（フォールバックデータ）",
        }
    except Exception:
        logger.error("get_capital_flow_risk エラー", exc_info=True)
        return safe_error_response("資本フローリスク評価中に内部エラーが発生しました")


@mcp.tool()
def assess_inbound_tourism_risk(
    source_country: str, horizon_months: int = 6
) -> dict:
    """
    インバウンド観光市場リスクを評価。需要・供給・日本側の3カテゴリで統合スコアを算出。
    為替・経済・政治・フライト・ビザ・災害・台風・競合を多角評価。

    Args:
        source_country: 送客国（ISO2/ISO3コード or 国名。例: CN, KOR, China）
        horizon_months: 評価期間（1-36ヶ月、デフォルト6）
    """
    try:
        if horizon_months < 1 or horizon_months > 36:
            return safe_error_response("horizon_months は 1〜36 の範囲で指定してください")

        if _inbound_scorer is None:
            return {
                "status": "fallback",
                "message": "インバウンドリスクスコアラーが初期化されていません（サンプルデータ）",
                "source_country": source_country,
                "inbound_risk_score": 50,
                "risk_level": "MEDIUM",
                "categories": {
                    "demand_risk": {"score": 50, "weight": 0.50},
                    "supply_risk": {"score": 50, "weight": 0.30},
                    "japan_risk": {"score": 50, "weight": 0.20},
                },
            }

        result = _inbound_scorer.calculate_market_risk(source_country, horizon_months)
        return {"status": "ok", **result}
    except ValueError as ve:
        return safe_error_response(str(ve))
    except Exception:
        logger.error("assess_inbound_tourism_risk エラー", exc_info=True)
        return safe_error_response("インバウンドリスク評価中に内部エラーが発生しました")


@mcp.tool()
def get_inbound_market_ranking() -> dict:
    """
    インバウンド主要20市場のリスクランキングを取得。
    リスクスコア降順で各市場の需要・供給・日本側リスクと予測訪問者数を一覧表示。
    """
    try:
        if _inbound_scorer is None:
            # サンプルデータを返す
            sample_markets = [
                {"rank": i + 1, "iso2": c, "country_name": n,
                 "inbound_risk_score": 50, "risk_level": "MEDIUM",
                 "demand_risk": 50, "supply_risk": 50, "japan_risk": 50,
                 "forecast_visitors": None, "forecast_period_months": 6}
                for i, (c, n) in enumerate([
                    ("CN", "China"), ("KR", "South Korea"), ("TW", "Taiwan"),
                    ("HK", "Hong Kong"), ("US", "United States"),
                ])
            ]
            return {
                "status": "fallback",
                "message": "スコアラー未初期化（サンプルデータ）",
                "markets": sample_markets,
                "total_markets": len(sample_markets),
            }

        markets = _inbound_scorer.scan_all_markets(top_n=20)
        return {
            "status": "ok",
            "markets": markets,
            "total_markets": len(markets),
            "calculated_at": datetime.utcnow().isoformat(),
        }
    except Exception:
        logger.error("get_inbound_market_ranking エラー", exc_info=True)
        return safe_error_response("市場ランキング取得中に内部エラーが発生しました")


@mcp.tool()
def forecast_visitor_volume(
    source_country: str, horizon_months: int = 12
) -> dict:
    """
    送客国別の訪日観光客数を予測。重力モデル×リスク調整で信頼区間付き予測。
    シナリオ分析（為替急変・フライト減便等）にも対応。

    Args:
        source_country: 送客国（ISO2/ISO3コード or 国名）
        horizon_months: 予測期間（1-36ヶ月、デフォルト12）
    """
    try:
        if horizon_months < 1 or horizon_months > 36:
            return safe_error_response("horizon_months は 1〜36 の範囲で指定してください")

        if _inbound_scorer is None:
            return {
                "status": "fallback",
                "message": "スコアラー未初期化（サンプルデータ）",
                "source_country": source_country,
                "adjusted_forecast": 100000,
                "confidence_interval": {"lower": 80000, "upper": 120000},
            }

        result = _inbound_scorer.forecast_visitor_volume(
            source_country, horizon_months
        )
        return {"status": "ok", **result}
    except ValueError as ve:
        return safe_error_response(str(ve))
    except Exception:
        logger.error("forecast_visitor_volume エラー", exc_info=True)
        return safe_error_response("訪問者数予測中に内部エラーが発生しました")


@mcp.tool()
def analyze_competitor_performance(source_country: str = "") -> dict:
    """
    日本のインバウンド競合デスティネーション（韓国・タイ・台湾等）の
    パフォーマンスを分析。送客国を指定すると、その国からの各デスティネーション
    訪問者数シェアを比較。

    Args:
        source_country: 送客国（空欄で全体概要）
    """
    try:
        if _competitor_stats_client:
            try:
                if source_country:
                    data = _competitor_stats_client.get_competitor_index(source_country)
                else:
                    data = _competitor_stats_client.get_overview()
                return {"status": "ok", **data}
            except Exception:
                logger.warning("競合分析クライアントエラー（フォールバック使用）")

        # サンプルデータ
        competitors = ["JPN", "KOR", "THA", "TWN", "SGP", "IDN"]
        sample = {
            "status": "fallback",
            "message": "競合分析クライアント未実装（サンプルデータ）",
            "source_country": source_country or "全市場",
            "competitors": [
                {
                    "destination": c,
                    "market_share_pct": round(100 / len(competitors), 1),
                    "yoy_change_pct": 0.0,
                    "trend": "stable",
                }
                for c in competitors
            ],
            "japan_position": {
                "rank": 1,
                "market_share_pct": round(100 / len(competitors), 1),
                "strength": "文化・食・安全性",
                "weakness": "言語バリア・コスト",
            },
        }
        return sample
    except Exception:
        logger.error("analyze_competitor_performance エラー", exc_info=True)
        return safe_error_response("競合分析中に内部エラーが発生しました")


@mcp.tool()
def predict_regional_distribution(
    total_visitors: int, source_country: str, season: str = ""
) -> dict:
    """
    訪日外国人の都道府県別・地域別分布を予測。
    送客国と季節に応じた地方分散パターンを算出。

    Args:
        total_visitors: 予測総訪問者数
        source_country: 送客国（ISO2/ISO3コード or 国名）
        season: 季節（spring/summer/autumn/winter、空欄で通年）
    """
    try:
        if total_visitors < 0 or total_visitors > 100_000_000:
            return safe_error_response("total_visitors は 0〜100,000,000 の範囲で指定してください")

        valid_seasons = ("", "spring", "summer", "autumn", "winter")
        if season and season.lower() not in valid_seasons:
            return safe_error_response(
                f"season は {', '.join(s for s in valid_seasons if s)} のいずれかを指定してください"
            )

        if _regional_dist_model:
            try:
                result = _regional_dist_model.predict(
                    total_visitors=total_visitors,
                    source_country=source_country,
                    season=season or None,
                )
                return {"status": "ok", **result}
            except Exception:
                logger.warning("地域分布モデルエラー（フォールバック使用）")

        # サンプルデータ（典型的な分布）
        default_dist = {
            "関東": 0.45, "近畿": 0.25, "中部": 0.10,
            "九州": 0.08, "北海道": 0.05, "東北": 0.02,
            "中国": 0.02, "四国": 0.01, "沖縄": 0.02,
        }
        regions = []
        for region, share in default_dist.items():
            visitors = int(total_visitors * share)
            regions.append({
                "region": region,
                "share_pct": round(share * 100, 1),
                "estimated_visitors": visitors,
            })

        return {
            "status": "fallback",
            "message": "地域分布モデル未実装（デフォルト分布で推定）",
            "source_country": source_country,
            "season": season or "通年",
            "total_visitors": total_visitors,
            "regional_distribution": regions,
            "concentration_index": 0.70,
            "top_prefectures": [
                {"prefecture": "東京都", "share_pct": 25.0},
                {"prefecture": "大阪府", "share_pct": 15.0},
                {"prefecture": "京都府", "share_pct": 8.0},
                {"prefecture": "北海道", "share_pct": 5.0},
                {"prefecture": "福岡県", "share_pct": 4.0},
            ],
        }
    except Exception:
        logger.error("predict_regional_distribution エラー", exc_info=True)
        return safe_error_response("地域分布予測中に内部エラーが発生しました")


@mcp.tool()
def decompose_visitor_change(
    source_country: str, period_months: int = 12
) -> dict:
    """
    訪問者数変動の要因分解。需要側（為替・経済・政治）、供給側（フライト・ビザ・
    二国間関係）、日本側（災害・台風・競合）の3カテゴリに分解して寄与度を表示。

    Args:
        source_country: 送客国（ISO2/ISO3コード or 国名）
        period_months: 分析期間（1-36ヶ月、デフォルト12）
    """
    try:
        if period_months < 1 or period_months > 36:
            return safe_error_response("period_months は 1〜36 の範囲で指定してください")

        if _inbound_scorer is None:
            return {
                "status": "fallback",
                "message": "スコアラー未初期化（サンプルデータ）",
                "source_country": source_country,
                "period_months": period_months,
                "decomposition": {
                    "demand_factors": {"total_impact": 0, "components": {}},
                    "supply_factors": {"total_impact": 0, "components": {}},
                    "japan_factors": {"total_impact": 0, "components": {}},
                },
            }

        result = _inbound_scorer.decompose_visitor_change(
            source_country, period_months
        )
        return {"status": "ok", **result}
    except ValueError as ve:
        return safe_error_response(str(ve))
    except Exception:
        logger.error("decompose_visitor_change エラー", exc_info=True)
        return safe_error_response("変動要因分解中に内部エラーが発生しました")


# ---------------------------------------------------------------------------
#  v1.4.0: インバウンド確率分布予測ツール
# ---------------------------------------------------------------------------

_gravity_model = None
_seasonal_extractor = None
_inbound_aggregator = None

try:
    from features.tourism.gravity_model import TourismGravityModel
    _gravity_model = TourismGravityModel()
except (ImportError, Exception) as _e:
    logger.warning("TourismGravityModel 初期化失敗: %s", _e)

try:
    from features.tourism.seasonal_extractor import SeasonalExtractor
    _seasonal_extractor = SeasonalExtractor()
except (ImportError, Exception) as _e:
    logger.warning("SeasonalExtractor 初期化失敗: %s", _e)

try:
    from features.tourism.inbound_aggregator import InboundAggregator
    _inbound_aggregator = InboundAggregator()
except (ImportError, Exception) as _e:
    logger.warning("InboundAggregator 初期化失敗: %s", _e)

_risk_adjuster = None
try:
    from features.tourism.risk_adjuster import RiskAdjuster
    _risk_adjuster = RiskAdjuster()
except (ImportError, Exception) as _e:
    logger.warning("RiskAdjuster 初期化失敗: %s", _e)

# 月次ベースライン（千人）フォールバック
_FB_MONTHLY = {
    "CN": [350, 300, 470, 510, 480, 410, 600, 550, 440, 680, 500, 560],
    "KR": [640, 570, 710, 690, 630, 560, 720, 660, 610, 760, 650, 720],
    "TW": [400, 440, 395, 430, 385, 360, 450, 430, 375, 475, 420, 435],
    "US": [165, 155, 220, 260, 245, 270, 315, 280, 240, 295, 225, 195],
    "AU": [68, 62, 50, 42, 33, 35, 46, 50, 60, 64, 68, 78],
}
_FB_PREF_SHARES = {
    "東京": 0.25, "大阪": 0.15, "京都": 0.08, "北海道": 0.06,
    "福岡": 0.05, "沖縄": 0.04, "新潟": 0.01, "長野": 0.01,
}


def _mcp_montecarlo(base_values, n_samples, scenario=None, cv=0.12):
    """モンテカルロサンプリングで確率分布を生成"""
    import math as _math
    import random as _random
    shock = 1.0
    if scenario:
        shock *= (1.0 + scenario.get("exr", 0.0) * 0.8)
        br = scenario.get("bilateral_risk", 0)
        if br > 0:
            shock *= max(0.5, 1.0 - br / 100.0)
    results = []
    for base in base_values:
        adj = base * shock
        sigma = cv
        mu = _math.log(max(adj, 1)) - 0.5 * sigma * sigma
        samples = sorted(_math.exp(_random.gauss(mu, sigma)) for _ in range(n_samples))
        results.append({
            "median": round(samples[n_samples // 2]),
            "p10": round(samples[int(n_samples * 0.10)]),
            "p25": round(samples[int(n_samples * 0.25)]),
            "p75": round(samples[int(n_samples * 0.75)]),
            "p90": round(samples[int(n_samples * 0.90)]),
        })
    return results


@mcp.tool()
def forecast_japan_inbound(
    horizon_months: int = 24, n_samples: int = 1000,
    scenario: dict = None,
) -> dict:
    """
    日本全国インバウンド訪問者数の確率分布予測。
    PPML重力モデル＋STL季節分解＋ベイズ推論によるモンテカルロシミュレーション。
    シナリオショック（円安/円高/二国間関係悪化等）で分布全体をシフト可能。

    Args:
        horizon_months: 予測期間（1-36ヶ月、デフォルト24）
        n_samples: モンテカルロサンプル数（100-10000、デフォルト1000）
        scenario: シナリオショック辞書（例: {"exr": 0.10} で円安10%）
    """
    try:
        if horizon_months < 1 or horizon_months > 36:
            return safe_error_response("horizon_months は 1〜36 の範囲で指定してください")
        n_samples = max(100, min(n_samples, 10000))

        months = []
        for i in range(horizon_months):
            y = 2025 + (i // 12)
            m = (i % 12) + 1
            months.append(f"{y}/{str(m).zfill(2)}")

        # TASK1-3モジュール利用可能時
        if _gravity_model and _seasonal_extractor and _inbound_aggregator:
            try:
                country_forecasts = {}
                for cc in ["CN", "KR", "TW", "US", "AU", "TH", "HK", "SG"]:
                    try:
                        gp = _gravity_model.predict(
                            source_country=cc, months=months,
                            n_samples=n_samples, scenario=scenario,
                        )
                        sa = _seasonal_extractor.adjust(cc, months, gp)
                        country_forecasts[cc] = sa
                    except Exception:
                        continue
                agg = _inbound_aggregator.aggregate(country_forecasts, months)
                return {
                    "status": "ok",
                    "months": months,
                    "median": [a["median"] for a in agg],
                    "p10": [a["p10"] for a in agg],
                    "p25": [a["p25"] for a in agg],
                    "p75": [a["p75"] for a in agg],
                    "p90": [a["p90"] for a in agg],
                    "by_country": country_forecasts,
                    "model_info": {"method": "PPML+STL+Bayesian", "n_samples": n_samples},
                }
            except Exception:
                logger.warning("TASK1-3モジュール予測失敗（フォールバック使用）")

        # フォールバック
        total_base = []
        for m_str in months:
            m_idx = int(m_str.split("/")[1]) - 1
            total = sum(cd[m_idx % 12] for cd in _FB_MONTHLY.values())
            total_base.append(int(total * 1.12))

        dist = _mcp_montecarlo(total_base, n_samples, scenario)

        return {
            "status": "fallback",
            "message": "TASK1-3モジュール未実装（モンテカルロフォールバック）",
            "months": months,
            "median": [d["median"] for d in dist],
            "p10": [d["p10"] for d in dist],
            "p25": [d["p25"] for d in dist],
            "p75": [d["p75"] for d in dist],
            "p90": [d["p90"] for d in dist],
            "model_info": {"method": "static_montecarlo_fallback", "n_samples": n_samples},
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception:
        logger.error("forecast_japan_inbound エラー", exc_info=True)
        return safe_error_response("インバウンド予測中に内部エラーが発生しました")


@mcp.tool()
def forecast_prefecture_inbound(
    prefecture: str, horizon_months: int = 24,
    scenario: dict = None,
) -> dict:
    """
    都道府県別インバウンド訪問者数予測。国別シェア x ローカルリスク調整。
    全国予測を都道府県シェアで按分し、地域固有リスクで補正。

    Args:
        prefecture: 都道府県名（例: 東京、大阪、京都）
        horizon_months: 予測期間（1-36ヶ月、デフォルト24）
        scenario: シナリオショック辞書
    """
    try:
        if horizon_months < 1 or horizon_months > 36:
            return safe_error_response("horizon_months は 1〜36 の範囲で指定してください")

        months = []
        for i in range(horizon_months):
            y = 2025 + (i // 12)
            m = (i % 12) + 1
            months.append(f"{y}/{str(m).zfill(2)}")

        # TASK1-3モジュール利用可能時
        if _gravity_model and _inbound_aggregator:
            try:
                national = _inbound_aggregator.get_national_forecast(months, scenario=scenario)
                ps = _inbound_aggregator.get_prefecture_share(prefecture)
                lr = _inbound_aggregator.get_local_risk_factor(prefecture)
                pf = []
                for md in national:
                    pf.append({
                        k: round(v * ps * lr) if isinstance(v, (int, float)) else v
                        for k, v in md.items()
                    })
                return {
                    "status": "ok",
                    "prefecture": prefecture,
                    "months": months,
                    "median": [p["median"] for p in pf],
                    "p10": [p["p10"] for p in pf],
                    "p90": [p["p90"] for p in pf],
                    "share_pct": round(ps * 100, 2),
                    "local_risk_factor": round(lr, 3),
                }
            except Exception:
                logger.warning("都道府県予測モジュール失敗（フォールバック使用）")

        # フォールバック
        pref_share = _FB_PREF_SHARES.get(prefecture, 0.02)
        total_base = []
        for m_str in months:
            m_idx = int(m_str.split("/")[1]) - 1
            total = sum(cd[m_idx % 12] for cd in _FB_MONTHLY.values())
            total_base.append(int(total * 1.12))

        pref_base = [round(v * pref_share) for v in total_base]
        dist = _mcp_montecarlo(pref_base, min(500, 1000), scenario, cv=0.18)

        return {
            "status": "fallback",
            "message": "都道府県予測モジュール未実装（フォールバック）",
            "prefecture": prefecture,
            "months": months,
            "median": [d["median"] for d in dist],
            "p10": [d["p10"] for d in dist],
            "p25": [d["p25"] for d in dist],
            "p75": [d["p75"] for d in dist],
            "p90": [d["p90"] for d in dist],
            "share_pct": round(pref_share * 100, 2),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception:
        logger.error("forecast_prefecture_inbound エラー", exc_info=True)
        return safe_error_response("都道府県別予測中に内部エラーが発生しました")


if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8001)
