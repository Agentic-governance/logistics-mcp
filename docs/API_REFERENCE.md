# SCRI Platform -- API Reference (v0.5.1)

Base URL: `http://localhost:8000`
Interactive docs: `http://localhost:8000/docs`
All responses are JSON. Errors return HTTP 502 with `{detail: "..."}`.

---

## Health

### GET /health

Health check with sanctions source status, alert counts, and data freshness.

**Parameters**: None

**Response**:
```json
{
  "status": "ok",
  "version": "0.5.1",
  "dimensions": 24,
  "mcp_tools": 16,
  "timestamp": "2026-03-18T00:00:00",
  "sanctions_sources": {
    "ofac": {"status": "ok", "records": 12000, "last_updated": "..."}
  },
  "active_alerts": 5,
  "data_staleness": {"stale_dimensions": [], "oldest_source": "CN (4h ago)"},
  "last_score_run": "2026-03-18T00:00:00"
}
```

---

## Sanctions Screening

### POST /api/v1/screen

Screen a single entity against 11 sanctions lists.

**Request Body**:
```json
{
  "company_name": "Huawei Technologies",
  "country": "China"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| company_name | string | Yes | Entity name |
| country | string | No | Country for improved accuracy |

**Response**:
```json
{
  "company_name": "Huawei Technologies",
  "matched": true,
  "match_score": 95.0,
  "source": "BIS",
  "matched_entity": "HUAWEI TECHNOLOGIES CO., LTD.",
  "evidence": ["BIS Entity List match"],
  "screened_at": "2026-03-18T00:00:00"
}
```

---

### POST /api/v1/screen/bulk

Bulk sanctions screening for multiple entities.

**Request Body**:
```json
{
  "companies": [
    {"company_name": "Company A", "country": "CN"},
    {"company_name": "Company B", "country": "RU"}
  ]
}
```

**Response**:
```json
{
  "total_screened": 2,
  "matched_count": 1,
  "results": [
    {"company_name": "Company A", "country": "CN", "matched": false, "match_score": 0, "source": null, "evidence": []},
    {"company_name": "Company B", "country": "RU", "matched": true, "match_score": 92.0, "source": "OFAC", "evidence": ["..."]}
  ]
}
```

---

## Risk Scoring

### GET /api/v1/risk/{supplier_id}

Calculate 24-dimension composite risk score.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| supplier_id | string | Supplier identifier |

**Query Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| company_name | string | Yes | Company name |
| country | string | No | Country name |
| location | string | No | City or region |

**Response**:
```json
{
  "supplier_id": "SUP-001",
  "company_name": "Example Corp",
  "overall_score": 45,
  "risk_level": "MEDIUM",
  "dimensions": 24,
  "scores": {
    "sanctions": 0, "geo_risk": 35, "disaster": 20, "legal": 10,
    "maritime": 15, "conflict": 50, "economic": 40, "currency": 25,
    "health": 10, "humanitarian": 30, "weather": 15, "typhoon": 5,
    "compliance": 45, "food_security": 20, "trade": 35, "internet": 10,
    "political": 55, "labor": 40, "port_congestion": 20, "aviation": 5,
    "energy": 30, "japan_economy": 15, "climate_risk": 25, "cyber_risk": 20
  },
  "score_categories": {
    "sanctions_conflict": {"weight": "28%", "components": ["sanctions", "geo_risk", "conflict", "political", "compliance"]},
    "disaster_infrastructure_climate": {"weight": "26%", "components": ["disaster", "weather", "typhoon", "maritime", "internet", "climate_risk"]},
    "economic_trade": {"weight": "23%", "components": ["economic", "currency", "trade", "energy", "port_congestion"]},
    "cyber_other": {"weight": "23%", "components": ["cyber_risk", "legal", "health", "humanitarian", "food_security", "labor", "aviation"]}
  },
  "evidence": [
    {"category": "conflict", "severity": "high", "description": "...", "source": "ACLED", "url": null}
  ],
  "calculated_at": "2026-03-18T00:00:00",
  "data_quality": {
    "dimensions_ok": 20, "dimensions_failed": 4, "confidence": 0.83,
    "low_confidence_warning": false, "dimension_status": {}
  }
}
```

---

## Disasters

### GET /api/v1/disasters/global

GDACS global disaster alerts.

**Parameters**: None

**Response**:
```json
{
  "count": 15,
  "events": [
    {"id": "EQ-2026-001", "type": "earthquake", "title": "M6.5 Earthquake",
     "severity": "Red", "country": "JP", "lat": 35.6, "lon": 139.7, "date": "2026-03-17"}
  ],
  "source": "GDACS"
}
```

---

### GET /api/v1/disasters/earthquakes

USGS earthquake data with configurable magnitude threshold.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| min_magnitude | float | 4.5 | Minimum magnitude filter |
| days | int | 7 | Lookback days (1-30) |

**Response**:
```json
{
  "count": 8,
  "earthquakes": [
    {"magnitude": 6.2, "place": "120km SW of Tokyo", "time": "2026-03-17T12:00:00", "lat": 35.0, "lon": 139.0}
  ],
  "source": "USGS"
}
```

---

## Maritime

### GET /api/v1/maritime/disruptions

IMF PortWatch active port disruption events.

**Parameters**: None

**Response**:
```json
{
  "count": 3,
  "disruptions": [
    {"name": "Suez Canal Disruption", "type": "blockage", "trade_impact_pct": 12.5}
  ],
  "source": "IMF PortWatch"
}
```

---

### GET /api/v1/maritime/port-activity

Port activity data with optional filters.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| port_name | string | null | Specific port name |
| country | string | null | Country filter |
| days | int | 30 | Lookback days (1-90) |

**Response**:
```json
{
  "count": 12,
  "activity": [{"port": "Shanghai", "vessels": 450, "throughput_change_pct": -5.2}],
  "source": "IMF PortWatch"
}
```

---

### GET /api/v1/maritime/congestion/{region}

AIS-based shipping lane congestion for a region.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| region | string | Region identifier (e.g., "south_china_sea") |

**Response**:
```json
{
  "region": "south_china_sea",
  "congestion_level": "high",
  "vessel_density": 245,
  "source": "AISHub"
}
```

---

### GET /api/v1/maritime/port-congestion/{location}

Port congestion and chokepoint risk metrics.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Location name |

**Response**:
```json
{
  "location": "Singapore",
  "score": 35,
  "evidence": ["Average waiting time: 2.1 days"],
  "source": "UNCTAD/Port Statistics"
}
```

---

## Conflict

### GET /api/v1/conflict/{location}

ACLED conflict and political violence risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country or region name |

**Response**:
```json
{
  "location": "Myanmar",
  "score": 85,
  "evidence": ["423 conflict events in past 30 days"],
  "source": "ACLED"
}
```

---

## Economic

### GET /api/v1/economic/{location}

World Bank economic risk indicators.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Argentina",
  "score": 70,
  "evidence": ["Inflation rate: 120%", "GDP growth: -2.1%"],
  "source": "World Bank"
}
```

---

### GET /api/v1/economic/profile/{location}

Detailed World Bank economic profile.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Japan",
  "gdp": 4.2e12,
  "gdp_growth": 1.2,
  "inflation": 2.8,
  "unemployment": 2.5,
  "source": "World Bank"
}
```

---

### GET /api/v1/currency/{location}

Currency volatility and depreciation risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Turkey",
  "score": 65,
  "evidence": ["30-day volatility: 8.5%", "90-day depreciation: -12%"],
  "source": "Frankfurter/ECB"
}
```

---

### GET /api/v1/trade/{location}

UN Comtrade trade dependency risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Vietnam",
  "score": 40,
  "evidence": ["Top partner concentration (HHI): 0.35"],
  "source": "UN Comtrade"
}
```

---

### GET /api/v1/energy/commodities

FRED commodity price data and energy risk.

**Parameters**: None

**Response**:
```json
{
  "score": 45,
  "evidence": ["WTI crude: $78.50 (+5.2% 30d)", "Natural gas: $3.20 (+8.1% 30d)"],
  "source": "FRED/EIA"
}
```

---

## Health & Humanitarian

### GET /api/v1/health/{location}

Disease.sh pandemic and infectious disease risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "India",
  "score": 30,
  "evidence": ["Active cases: 15000", "Cases per million: 10.7"],
  "source": "Disease.sh"
}
```

---

### GET /api/v1/humanitarian/{location}

ReliefWeb/OCHA humanitarian crisis risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Yemen",
  "score": 90,
  "evidence": ["Active humanitarian appeals: 3", "Displaced persons: 4.5M"],
  "source": "ReliefWeb/OCHA"
}
```

---

### GET /api/v1/food-security/{location}

WFP food security risk assessment.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Ethiopia",
  "score": 75,
  "evidence": ["Food insecurity phase: Crisis (IPC 3)"],
  "source": "WFP HungerMap"
}
```

---

## Weather

### GET /api/v1/weather/{location}

Open-Meteo weather risk assessment.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country or city name |

**Response**:
```json
{
  "location": "Philippines",
  "score": 55,
  "evidence": ["Heavy rainfall warning", "Temperature anomaly: +3.2C"],
  "source": "Open-Meteo"
}
```

---

### GET /api/v1/weather/typhoon/{location}

NOAA tropical cyclone and space weather risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Location name |

**Response**:
```json
{
  "location": "Taiwan",
  "score": 40,
  "evidence": ["Nearest storm: Typhoon X, 800km away"],
  "source": "NOAA NHC/SWPC"
}
```

---

### GET /api/v1/weather/space

NOAA SWPC space weather data (solar storms, geomagnetic activity).

**Parameters**: None

**Response**:
```json
{
  "kp_index": 3,
  "solar_wind_speed": 450,
  "alerts": [],
  "source": "NOAA SWPC"
}
```

---

## Compliance

### GET /api/v1/compliance/{location}

FATF/INFORM/TI-CPI compliance risk assessment.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Iran",
  "score": 90,
  "evidence": ["FATF blacklisted", "TI CPI score: 25/100"],
  "source": "FATF/INFORM/TI-CPI"
}
```

---

### GET /api/v1/compliance/political/{location}

Freedom House / Fragile States Index political risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "North Korea",
  "score": 95,
  "evidence": ["Freedom status: Not Free", "FSI rank: 3"],
  "source": "Freedom House/FSI"
}
```

---

### GET /api/v1/compliance/labor/{location}

DoL ILAB / Global Slavery Index labor risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Bangladesh",
  "score": 60,
  "evidence": ["12 goods on ILAB list", "GSI vulnerability: High"],
  "source": "DoL ILAB/GSI"
}
```

---

## Infrastructure

### GET /api/v1/infrastructure/internet/{location}

Cloudflare Radar / IODA internet infrastructure risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Myanmar",
  "score": 70,
  "evidence": ["Internet shutdowns detected", "BGP instability: High"],
  "source": "Cloudflare Radar/IODA"
}
```

---

## Aviation

### GET /api/v1/aviation/{location}

OpenSky Network aviation traffic risk.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Ukraine",
  "score": 80,
  "evidence": ["Airspace restrictions active", "Flight count: -90% vs baseline"],
  "source": "OpenSky Network"
}
```

---

## Japan-Specific

### GET /api/v1/japan/economy

BOJ / e-Stat / ExchangeRate-API Japan economic indicators.

**Parameters**: None

**Response**:
```json
{
  "usd_jpy": 150.5,
  "eur_jpy": 163.2,
  "cpi_yoy": 2.8,
  "tankan": 12,
  "source": "BOJ/ExchangeRate-API"
}
```

---

## Dashboard

### GET /api/v1/dashboard/global

Integrated global risk dashboard across all data sources.

**Parameters**: None

**Response**:
```json
{
  "timestamp": "2026-03-18T00:00:00",
  "version": "0.4.0",
  "dimensions": 24,
  "sources": {
    "gdacs": {"status": "ok", "total_events": 15, "red_alerts": 2, "orange_alerts": 5, "top_events": []},
    "usgs": {"status": "ok", "significant_earthquakes_month": 3, "top_quakes": []},
    "noaa": {"status": "ok", "active_storms": 1, "storms": [], "kp_index": 3},
    "portwatch": {"status": "ok", "active_disruptions": 2, "disruptions": []},
    "covid": {"status": "ok", "active_global": 5000000, "today_cases": 50000},
    "japan_economy": {"status": "ok", "usd_jpy": 150.5}
  },
  "db": {"sanctions_entities": 45000, "monitored_suppliers": 12, "active_alerts": 5}
}
```

---

## Alerts

### GET /api/v1/alerts

List recent risk alerts.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| since_hours | int | 24 | Lookback hours (1-720) |
| min_score | int | 50 | Minimum score threshold (0-100) |

**Response**:
```json
{
  "count": 5,
  "alerts": [
    {"id": 1, "supplier": "Corp A", "type": "geo_risk", "severity": "high",
     "score": 75, "title": "Escalation detected", "description": "...",
     "created_at": "2026-03-18T00:00:00"}
  ]
}
```

---

## Monitoring

### POST /api/v1/monitor

Register a supplier for automated monitoring.

**Request Body**:
```json
{
  "supplier_id": "SUP-001",
  "company_name": "Example Corp",
  "location": "Vietnam"
}
```

**Response**:
```json
{
  "status": "registered",
  "supplier_id": "SUP-001",
  "monitoring": {"interval": "15 minutes", "dimensions": 24, "sources": ["OFAC", "EU", "..."]}
}
```

---

### GET /api/v1/monitors

List all actively monitored suppliers.

**Parameters**: None

**Response**:
```json
{
  "count": 12,
  "suppliers": [
    {"supplier_id": "SUP-001", "company_name": "Example Corp", "location": "Vietnam"}
  ]
}
```

---

### GET /api/v1/monitoring/quality

Data quality dashboard with score coverage and anomalies.

**Parameters**: None

**Response**:
```json
{
  "timestamp": "2026-03-18T00:00:00",
  "score_coverage": {"geo_risk": 0.85, "conflict": 0.90, "economic": 0.78},
  "recent_anomalies": [],
  "source_health": {"ofac": {"status": "ok", "records": 12000}},
  "last_full_run": "2026-03-18T00:00:00"
}
```

---

## Stats

### GET /api/v1/stats

Database statistics and data source status.

**Parameters**: None

**Response**:
```json
{
  "sanctions_entities": 45000,
  "screenings_performed": 1200,
  "active_alerts": 5,
  "monitored_suppliers": 12,
  "sources": {"ofac": {"record_count": 12000, "last_fetched": "..."}},
  "dimensions": 24,
  "data_pipelines": {
    "sanctions": ["OFAC", "EU", "UN", "..."],
    "geopolitical": ["GDELT BigQuery"],
    "disaster": ["GDACS", "USGS", "NASA FIRMS", "JMA"]
  }
}
```

---

## Supply Chain Graph

### GET /api/v1/graph/{company_name}

Retrieve Tier-N supply chain network graph.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| company_name | string | Root company name |

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| country_code | string | "jp" | Country code |
| depth | int | 2 | Graph depth (1-3) |

**Response**:
```json
{
  "nodes": [{"id": "company_a", "name": "Company A", "tier": 0}],
  "edges": [{"source": "company_a", "target": "company_b", "relationship": "supplier"}],
  "stats": {"node_count": 15, "edge_count": 22, "max_depth": 2}
}
```

---

## Route Risk

### POST /api/v1/route-risk

Analyze transport route risk with chokepoint assessment.

**Request Body**:
```json
{
  "origin": "Shanghai",
  "destination": "Rotterdam"
}
```

**Response**:
```json
{
  "route": {"origin": "Shanghai", "destination": "Rotterdam"},
  "chokepoints_passed": ["Strait of Malacca", "Suez Canal"],
  "risk_score": 55,
  "alternative_routes": [],
  "recommendations": []
}
```

---

### GET /api/v1/chokepoints

List all 7 major chokepoints with current risk assessment.

**Parameters**: None

**Response**:
```json
{
  "count": 7,
  "chokepoints": [
    {"id": "suez", "name": "Suez Canal", "risk_score": 40, "status": "open"}
  ]
}
```

---

### GET /api/v1/chokepoint/{chokepoint_id}

Individual chokepoint risk detail.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| chokepoint_id | string | Chokepoint identifier |

**Response**:
```json
{
  "id": "malacca",
  "name": "Strait of Malacca",
  "risk_score": 30,
  "daily_traffic": 85000,
  "recent_incidents": []
}
```

---

## Concentration Risk

### POST /api/v1/concentration

Analyze supplier concentration risk.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| sector | string | null | Sector name filter |

**Response**:
```json
{
  "hhi": 0.35,
  "concentration_level": "moderate",
  "geographic_distribution": {},
  "recommendations": []
}
```

---

## Simulation

### GET /api/v1/simulate/{scenario}

Run disruption simulation scenario.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| scenario | string | Scenario: taiwan_blockade, suez_closure, china_lockdown, semiconductor_shortage |

**Response**:
```json
{
  "scenario": "taiwan_blockade",
  "impact_score": 85,
  "affected_trade_pct": 40,
  "recovery_weeks": 12,
  "affected_sectors": ["semiconductor", "electronics"],
  "mitigation_options": []
}
```

---

## DD Reports

### POST /api/v1/dd-report

Generate KYS due diligence report.

**Request Body**:
```json
{
  "entity_name": "Example Corp",
  "country": "China"
}
```

**Response**:
```json
{
  "entity": "Example Corp",
  "country": "China",
  "sanctions_result": {"matched": false},
  "risk_score": {"overall_score": 45, "risk_level": "MEDIUM"},
  "edd_required": false,
  "report_id": "DD-2026-001"
}
```

---

## Commodity

### GET /api/v1/commodity/{sector}

Commodity exposure analysis by sector.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| sector | string | Sector: semiconductor, battery_materials, automotive_parts, electronics, energy, food |

**Response**:
```json
{
  "sector": "semiconductor",
  "commodities": ["silicon", "copper", "aluminum", "rare_earth"],
  "exposure_score": 60,
  "price_risk": {},
  "geopolitical_risk": {}
}
```

---

## Bulk Assessment

### POST /api/v1/bulk-assess

Bulk supplier assessment via CSV.

**Request Body**:
```json
{
  "csv_data": "name,country\nCompany A,CN\nCompany B,VN",
  "depth": "quick"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| csv_data | string | -- | CSV with name,country header |
| depth | string | "quick" | "quick" or "full" |

**Response**:
```json
{
  "total": 2,
  "results": [
    {"name": "Company A", "country": "CN", "sanctions": {"matched": false}, "risk_score": 45, "risk_level": "MEDIUM"}
  ]
}
```

---

## Climate Risk

### GET /api/v1/climate/{location}

Climate risk from ND-GAIN, GloFAS, WRI Aqueduct, Climate TRACE.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "Bangladesh",
  "score": 70,
  "evidence": ["ND-GAIN vulnerability: High", "Flood risk: Severe"],
  "source": "ND-GAIN/GloFAS/WRI/Climate TRACE"
}
```

---

## Cyber Risk

### GET /api/v1/cyber/{location}

Cyber risk from OONI, CISA KEV, ITU ICT.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country name |

**Response**:
```json
{
  "location": "China",
  "score": 55,
  "evidence": ["Internet censorship detected", "ICT development index: 0.65"],
  "source": "OONI/CISA KEV/ITU ICT"
}
```

---

## Analytics

### GET /api/v1/analytics/overview

Index of all analytics features with sample requests.

**Parameters**: None

**Response**:
```json
{
  "available_analyses": [
    {"name": "portfolio", "endpoint": "POST /api/v1/analytics/portfolio", "description": "...", "sample_request": {}},
    {"name": "correlations", "endpoint": "POST /api/v1/analytics/correlations", "description": "...", "sample_request": {}},
    {"name": "benchmark", "endpoint": "POST /api/v1/analytics/benchmark/industry", "description": "...", "sample_request": {}},
    {"name": "sensitivity", "endpoint": "POST /api/v1/analytics/sensitivity/weights", "description": "...", "sample_request": {}}
  ]
}
```

---

### POST /api/v1/analytics/portfolio

Portfolio risk analysis for multiple suppliers.

**Request Body**:
```json
{
  "entities": [
    {"name": "TSMC", "country": "TW", "tier": 1, "share": 0.35},
    {"name": "Samsung", "country": "KR", "tier": 1, "share": 0.25}
  ],
  "dimensions": [],
  "include_clustering": false
}
```

**Response**:
```json
{
  "portfolio_summary": {"avg_score": 42, "max_score": 55, "entity_count": 2},
  "entity_scores": [],
  "concentration": {}
}
```

---

### POST /api/v1/analytics/portfolio/rank

Rank suppliers by risk score.

**Request Body**:
```json
{
  "entities": [{"name": "Company A", "country": "CN"}],
  "sort_by": "overall",
  "ascending": true
}
```

**Response**:
```json
{
  "ranking": [
    {"rank": 1, "name": "Company A", "overall_score": 35}
  ]
}
```

---

### POST /api/v1/analytics/portfolio/cluster

Cluster suppliers by risk profile using k-means.

**Request Body**:
```json
{
  "entities": [{"name": "A", "country": "CN"}, {"name": "B", "country": "VN"}, {"name": "C", "country": "TH"}],
  "n_clusters": 3
}
```

**Response**:
```json
{
  "clusters": [
    {"cluster_id": 0, "members": ["A"], "centroid": {}, "risk_level": "HIGH"}
  ]
}
```

---

### POST /api/v1/analytics/correlations

Compute risk dimension correlation matrix.

**Request Body**:
```json
{
  "locations": ["JP", "CN", "KR", "TW", "US"],
  "method": "pearson"
}
```

**Response**:
```json
{
  "matrix": {},
  "high_correlations": [{"dim_a": "conflict", "dim_b": "political", "correlation": 0.85}],
  "dimensions_analyzed": 22,
  "locations_count": 5
}
```

---

### POST /api/v1/analytics/correlations/leading-indicators

Find leading indicators via cross-correlation.

**Request Body**:
```json
{
  "target_dimension": "conflict",
  "locations": ["MM", "UA", "YE"],
  "lag_days": 30
}
```

**Response**:
```json
{
  "target_dimension": "conflict",
  "indicators": [{"dimension": "political", "lag_days": 7, "correlation": 0.72}],
  "count": 3
}
```

---

### GET /api/v1/analytics/correlations/cascades/{location}

Detect risk cascade chains for a location.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| location | string | Country code or name |

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| start_date | string | "2026-01-01" | Analysis start date |
| end_date | string | "2026-03-17" | Analysis end date |

**Response**:
```json
{
  "location": "MM",
  "cascades": [{"trigger": "conflict", "chain": ["political", "economic", "currency"], "severity": "high"}],
  "count": 2
}
```

---

### POST /api/v1/analytics/benchmark/industry

Benchmark entity against industry average.

**Request Body**:
```json
{
  "entity": {"name": "Test Corp", "country": "JP", "industry": "automotive"}
}
```

**Response**:
```json
{
  "entity": "Test Corp",
  "industry": "automotive",
  "percentile_ranks": {"overall": 65, "conflict": 30},
  "vs_industry_avg": {"overall": -5, "conflict": -10}
}
```

---

### POST /api/v1/analytics/benchmark/peers

Benchmark entity against peer group.

**Request Body**:
```json
{
  "target": {"name": "Target Corp", "country": "JP"},
  "peers": [
    {"name": "Peer A", "country": "KR"},
    {"name": "Peer B", "country": "TW"}
  ]
}
```

**Response**:
```json
{
  "target": "Target Corp",
  "peer_comparisons": [],
  "relative_position": {}
}
```

---

### GET /api/v1/analytics/benchmark/regional/{region}

Compute regional risk baseline.

**Path Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| region | string | Region name (e.g., "east_asia", "southeast_asia") |

**Response**:
```json
{
  "region": "east_asia",
  "baseline_scores": {"overall": 40, "conflict": 25},
  "countries_included": ["JP", "KR", "CN", "TW"]
}
```

---

### POST /api/v1/analytics/sensitivity/weights

Analyze weight sensitivity for a location.

**Request Body**:
```json
{
  "location": "CN",
  "weight_perturbation": 0.05
}
```

**Response**:
```json
{
  "location": "CN",
  "sensitivity_ranking": [
    {"dimension": "conflict", "sensitivity": 4.5, "current_weight": 0.09}
  ],
  "most_influential": ["conflict", "political"]
}
```

---

### POST /api/v1/analytics/sensitivity/what-if

What-If scenario simulation.

**Request Body**:
```json
{
  "location": "CN",
  "dimension_overrides": {"conflict": 90, "political": 80}
}
```

**Response**:
```json
{
  "location": "CN",
  "original_score": 45,
  "simulated_score": 68,
  "delta": 23,
  "overrides_applied": {"conflict": 90, "political": 80},
  "risk_level_change": {"from": "MEDIUM", "to": "HIGH"}
}
```

---

### POST /api/v1/analytics/sensitivity/threshold

Find which dimensions drive score to a target risk level.

**Request Body**:
```json
{
  "location": "JP",
  "target_level": "HIGH"
}
```

**Response**:
```json
{
  "location": "JP",
  "current_level": "LOW",
  "target_level": "HIGH",
  "threshold_score": 60,
  "drivers": [{"dimension": "disaster", "required_increase": 45}]
}
```

---

### POST /api/v1/analytics/sensitivity/montecarlo

Monte Carlo simulation for score distribution.

**Request Body**:
```json
{
  "location": "CN",
  "n_simulations": 1000,
  "noise_std": 10.0
}
```

**Response**:
```json
{
  "location": "CN",
  "n_simulations": 1000,
  "mean_score": 46.2,
  "std_score": 8.5,
  "percentiles": {"5": 32, "25": 40, "50": 46, "75": 52, "95": 62},
  "prob_high_risk": 0.12
}
```

---

## UI Endpoints

### GET /

Serves the web dashboard (index.html) if the `ui/` directory exists, otherwise returns API info JSON.

### /static/*

Static file serving for the web UI assets.

---

## Error Handling

All endpoints return standard HTTP error codes:

| Code | Meaning |
|------|---------|
| 200 | Success |
| 422 | Validation error (missing/invalid parameters) |
| 502 | Upstream data source failure |

Error response format:
```json
{
  "detail": "GDACS fetch failed: Connection timeout"
}
```

---

## Endpoint Count Summary

| Category | Count |
|----------|-------|
| Health | 1 |
| Sanctions | 2 |
| Risk Scoring | 1 |
| Disasters | 2 |
| Maritime | 4 |
| Conflict | 1 |
| Economic | 5 |
| Health & Humanitarian | 3 |
| Weather | 3 |
| Compliance | 3 |
| Infrastructure | 1 |
| Aviation | 1 |
| Japan | 1 |
| Dashboard | 1 |
| Alerts | 1 |
| Monitoring | 3 |
| Stats | 1 |
| Graph | 1 |
| Route Risk | 3 |
| Concentration | 1 |
| Simulation | 1 |
| DD Reports | 1 |
| Commodity | 1 |
| Bulk Assessment | 1 |
| Climate | 1 |
| Cyber | 1 |
| Analytics | 14 |
| UI | 2 |
| **Total** | **58 + 6 analytics sub-endpoints = 64** |
