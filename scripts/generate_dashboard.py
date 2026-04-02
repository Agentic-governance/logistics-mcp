#!/usr/bin/env python3
"""STREAM 3: Generate Interactive HTML Dashboard using Plotly.js

Produces a single self-contained HTML file at dashboard/index.html
with 5 interactive tabs:
  1. Global Risk Map (choropleth + radar on click)
  2. Portfolio Analyzer (input form, bar chart, heatmap)
  3. Correlation Matrix (24x24 heatmap)
  4. Time Series (line charts from timeseries.db)
  5. Alerts (table from data/alerts/)

Data sources:
  - data/timeseries.db (SQLite) for risk scores
  - data/alerts/*.jsonl for alert data
  - config/constants.py for PRIORITY_COUNTRIES and dimensions
"""
import sys
import os
import json
import sqlite3
import glob
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config.constants import PRIORITY_COUNTRIES, RISK_THRESHOLDS, VERSION

# 24 dimension keys (canonical order)
DIMENSION_KEYS = [
    "sanctions", "geo_risk", "disaster", "legal",
    "maritime", "conflict", "economic", "currency",
    "health", "humanitarian", "weather", "typhoon",
    "compliance", "food_security", "trade", "internet",
    "political", "labor", "port_congestion", "aviation",
    "energy", "japan_economy", "climate_risk", "cyber_risk",
]

DIMENSION_LABELS = [
    "Sanctions", "Geo Risk", "Disaster", "Legal",
    "Maritime", "Conflict", "Economic", "Currency",
    "Health", "Humanitarian", "Weather", "Typhoon",
    "Compliance", "Food Security", "Trade", "Internet",
    "Political", "Labor", "Port Congestion", "Aviation",
    "Energy", "Japan Economy", "Climate Risk", "Cyber Risk",
]

# Country name to ISO-3166 alpha-3 mapping
COUNTRY_ISO3 = {
    "Japan": "JPN", "United States": "USA", "Germany": "DEU",
    "United Kingdom": "GBR", "France": "FRA", "Italy": "ITA",
    "Canada": "CAN", "China": "CHN", "India": "IND",
    "Russia": "RUS", "Brazil": "BRA", "South Africa": "ZAF",
    "Indonesia": "IDN", "Vietnam": "VNM", "Thailand": "THA",
    "Malaysia": "MYS", "Singapore": "SGP", "Philippines": "PHL",
    "Myanmar": "MMR", "Cambodia": "KHM", "Saudi Arabia": "SAU",
    "UAE": "ARE", "Iran": "IRN", "Iraq": "IRQ",
    "Turkey": "TUR", "Israel": "ISR", "Qatar": "QAT",
    "Yemen": "YEM", "South Korea": "KOR", "Taiwan": "TWN",
    "North Korea": "PRK", "Bangladesh": "BGD", "Pakistan": "PAK",
    "Sri Lanka": "LKA", "Nigeria": "NGA", "Ethiopia": "ETH",
    "Kenya": "KEN", "Egypt": "EGY", "South Sudan": "SSD",
    "Somalia": "SOM", "Ukraine": "UKR", "Poland": "POL",
    "Netherlands": "NLD", "Switzerland": "CHE", "Mexico": "MEX",
    "Colombia": "COL", "Venezuela": "VEN", "Argentina": "ARG",
    "Chile": "CHL", "Australia": "AUS",
}

ISO3_TO_NAME = {v: k for k, v in COUNTRY_ISO3.items()}

DB_PATH = os.path.join(PROJECT_ROOT, "data", "timeseries.db")
ALERTS_DIR = os.path.join(PROJECT_ROOT, "data", "alerts")
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "dashboard", "index.html")


# ---------------------------------------------------------------------------
#  Data loading
# ---------------------------------------------------------------------------

def load_risk_summaries():
    """Load latest risk summaries from timeseries.db."""
    summaries = {}
    if not os.path.exists(DB_PATH):
        print(f"  [WARN] timeseries.db not found at {DB_PATH}, using fallback data")
        return _generate_fallback_data()

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT location, date, overall_score, scores_json, evidence_count
            FROM risk_summaries
            WHERE date = (SELECT MAX(date) FROM risk_summaries)
            ORDER BY overall_score DESC
        """)
        rows = cursor.fetchall()
        for row in rows:
            location, date, overall_score, scores_json, evidence_count = row
            scores = json.loads(scores_json) if scores_json else {}
            summaries[location] = {
                "overall_score": overall_score or 0,
                "date": date,
                "scores": scores,
                "evidence_count": evidence_count or 0,
            }
        conn.close()
        print(f"  Loaded {len(summaries)} country summaries from timeseries.db")
    except Exception as e:
        print(f"  [WARN] Failed to read timeseries.db: {e}")
        return _generate_fallback_data()

    if not summaries:
        return _generate_fallback_data()
    return summaries


def load_timeseries_data():
    """Load time-series risk score history from timeseries.db."""
    ts_data = {}
    if not os.path.exists(DB_PATH):
        return ts_data

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT location, timestamp, dimension, score
            FROM risk_scores
            ORDER BY location, timestamp
        """)
        for row in cursor.fetchall():
            loc, ts, dim, score = row
            if loc not in ts_data:
                ts_data[loc] = {}
            if dim not in ts_data[loc]:
                ts_data[loc][dim] = {"x": [], "y": []}
            ts_data[loc][dim]["x"].append(ts)
            ts_data[loc][dim]["y"].append(score or 0)
        conn.close()
    except Exception as e:
        print(f"  [WARN] Failed to read time-series data: {e}")
    return ts_data


def load_alerts():
    """Load alert data from data/alerts/*.jsonl files."""
    alerts = []
    if not os.path.isdir(ALERTS_DIR):
        print(f"  [WARN] Alerts directory not found at {ALERTS_DIR}")
        return alerts

    jsonl_files = sorted(glob.glob(os.path.join(ALERTS_DIR, "*.jsonl")), reverse=True)
    for fpath in jsonl_files[:30]:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        alert = json.loads(line)
                        alert["_file"] = os.path.basename(fpath)
                        alerts.append(alert)
        except Exception:
            pass
    print(f"  Loaded {len(alerts)} alerts from {len(jsonl_files)} files")
    return alerts


def _generate_fallback_data():
    """Generate deterministic fallback scores for all 50 countries."""
    import hashlib
    summaries = {}
    for country in PRIORITY_COUNTRIES:
        h = int(hashlib.md5(country.encode()).hexdigest(), 16)
        overall = (h % 80) + 5
        scores = {}
        for i, dim in enumerate(DIMENSION_KEYS):
            dim_h = int(hashlib.md5(f"{country}_{dim}".encode()).hexdigest(), 16)
            scores[dim] = (dim_h % 80) + 2
        summaries[country] = {
            "overall_score": overall,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "scores": scores,
            "evidence_count": (h % 30) + 10,
        }
    print(f"  Generated fallback data for {len(summaries)} countries")
    return summaries


def compute_correlation_matrix(summaries):
    """Compute 24x24 correlation matrix from country dimension scores."""
    import math

    n_dims = len(DIMENSION_KEYS)
    matrix_data = []
    for country, data in summaries.items():
        scores = data.get("scores", {})
        row = [scores.get(dim, 0) for dim in DIMENSION_KEYS]
        matrix_data.append(row)

    n = len(matrix_data)
    if n < 3:
        return [[1.0 if i == j else 0.0 for j in range(n_dims)] for i in range(n_dims)]

    cols = [[matrix_data[r][d] for r in range(n)] for d in range(n_dims)]

    def pearson(x, y):
        n = len(x)
        if n == 0:
            return 0.0
        mx = sum(x) / n
        my = sum(y) / n
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
        dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
        if dx == 0 or dy == 0:
            return 0.0
        return num / (dx * dy)

    corr = [[0.0] * n_dims for _ in range(n_dims)]
    for i in range(n_dims):
        for j in range(n_dims):
            if i == j:
                corr[i][j] = 1.0
            elif j > i:
                r = pearson(cols[i], cols[j])
                corr[i][j] = round(r, 3)
                corr[j][i] = round(r, 3)
    return corr


# ---------------------------------------------------------------------------
#  HTML generation
# ---------------------------------------------------------------------------

def risk_level(score):
    if score >= 80: return "CRITICAL"
    if score >= 60: return "HIGH"
    if score >= 40: return "MEDIUM"
    if score >= 20: return "LOW"
    return "MINIMAL"


def generate_html(summaries, ts_data, alerts, corr_matrix):
    """Generate the complete single-file HTML dashboard."""

    # Prepare data for JS
    map_locations = []
    map_z = []
    map_text = []
    country_scores_js = {}

    for country, data in summaries.items():
        iso3 = COUNTRY_ISO3.get(country)
        if not iso3:
            continue
        overall = data["overall_score"]
        map_locations.append(iso3)
        map_z.append(overall)
        level = risk_level(overall)
        map_text.append(f"{country}<br>Score: {overall}<br>Level: {level}")
        country_scores_js[iso3] = {
            "name": country,
            "overall": overall,
            "scores": data.get("scores", {}),
        }

    # Time series data
    ts_js = {}
    for loc, dims in ts_data.items():
        ts_js[loc] = dims

    # Alerts data
    alerts_js = []
    for alert in alerts:
        alerts_js.append({
            "type": alert.get("type", "unknown"),
            "severity": alert.get("severity", "INFO").upper(),
            "message": alert.get("message", ""),
            "dispatched_at": alert.get("dispatched_at", ""),
            "file": alert.get("_file", ""),
            "country": alert.get("country", ""),
            "dimension": alert.get("dimension", ""),
        })

    corr_js = corr_matrix
    all_countries = sorted(summaries.keys())
    gen_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Build country options for dropdowns
    country_options = ''.join(f'<option value="{c}">{c}</option>' for c in all_countries)
    dim_options = ''.join(
        f'<option value="{d}">{DIMENSION_LABELS[i]}</option>'
        for i, d in enumerate(DIMENSION_KEYS)
    )
    available_codes = ', '.join(sorted(COUNTRY_ISO3.values()))

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SCRI Dashboard - Supply Chain Risk Intelligence</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}}
a{{color:#58a6ff;text-decoration:none}}
.header{{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);padding:18px 32px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #30363d;box-shadow:0 2px 16px rgba(0,0,0,0.4)}}
.header h1{{font-size:22px;font-weight:700;color:#f0f6fc;letter-spacing:.5px}}
.header h1 span{{color:#58a6ff}}
.header .meta{{font-size:12px;color:#8b949e}}
.tab-nav{{display:flex;background:#161b22;border-bottom:1px solid #30363d;padding:0 24px;overflow-x:auto}}
.tab-btn{{padding:12px 24px;cursor:pointer;border:none;background:none;color:#8b949e;font-size:14px;font-weight:500;border-bottom:2px solid transparent;transition:all .2s;white-space:nowrap}}
.tab-btn:hover{{color:#c9d1d9;background:rgba(88,166,255,.05)}}
.tab-btn.active{{color:#58a6ff;border-bottom-color:#58a6ff}}
.tab-content{{display:none;padding:24px 32px}}
.tab-content.active{{display:block}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin-bottom:20px;box-shadow:0 1px 6px rgba(0,0,0,.3)}}
.card-title{{font-size:16px;font-weight:600;color:#f0f6fc;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid #21262d}}
.stats-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}}
.stat-card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 20px;text-align:center}}
.stat-value{{font-size:32px;font-weight:700;color:#f0f6fc}}
.stat-label{{font-size:12px;color:#8b949e;margin-top:4px;text-transform:uppercase;letter-spacing:1px}}
input[type="text"],select{{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:8px 12px;border-radius:6px;font-size:14px;outline:none;transition:border-color .2s}}
input[type="text"]:focus,select:focus{{border-color:#58a6ff}}
button.btn{{background:#238636;color:#fff;border:none;padding:8px 20px;border-radius:6px;font-size:14px;cursor:pointer;font-weight:500;transition:background .2s}}
button.btn:hover{{background:#2ea043}}
button.btn-secondary{{background:#30363d}}
button.btn-secondary:hover{{background:#484f58}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#21262d;color:#f0f6fc;padding:10px 12px;text-align:left;font-weight:600;border-bottom:1px solid #30363d;position:sticky;top:0}}
td{{padding:8px 12px;border-bottom:1px solid #21262d}}
tr:hover{{background:rgba(88,166,255,.04)}}
.badge{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;text-transform:uppercase}}
.badge-critical{{background:rgba(255,23,68,.2);color:#ff1744}}
.badge-high{{background:rgba(255,145,0,.2);color:#ff9100}}
.badge-medium{{background:rgba(255,234,0,.15);color:#ffd600}}
.badge-low{{background:rgba(0,230,118,.15);color:#00e676}}
.badge-minimal{{background:rgba(0,176,255,.15);color:#00b0ff}}
.badge-warning{{background:rgba(255,145,0,.2);color:#ff9100}}
.badge-info{{background:rgba(0,176,255,.15);color:#00b0ff}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.flex-row{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
.mt-16{{margin-top:16px}}
.mb-16{{margin-bottom:16px}}
.text-center{{text-align:center}}
.text-muted{{color:#8b949e}}
.scrollable{{max-height:500px;overflow-y:auto}}
.filter-group{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.filter-btn{{padding:5px 14px;border-radius:16px;border:1px solid #30363d;background:none;color:#8b949e;cursor:pointer;font-size:12px;transition:all .2s}}
.filter-btn:hover{{border-color:#58a6ff;color:#58a6ff}}
.filter-btn.active{{background:rgba(88,166,255,.15);border-color:#58a6ff;color:#58a6ff}}
@media(max-width:768px){{.grid-2{{grid-template-columns:1fr}}.header{{padding:12px 16px}}.tab-content{{padding:16px}}.tab-btn{{padding:10px 14px;font-size:13px}}}}
</style>
</head>
<body>

<div class="header">
    <h1><span>SCRI</span> Supply Chain Risk Intelligence</h1>
    <div class="meta">
        v{VERSION} &middot; {len(summaries)} countries &middot; 24 dimensions<br>
        Generated: {gen_time}
    </div>
</div>

<div class="tab-nav">
    <button class="tab-btn active" onclick="switchTab('tab-map')">Global Risk Map</button>
    <button class="tab-btn" onclick="switchTab('tab-portfolio')">Portfolio Analyzer</button>
    <button class="tab-btn" onclick="switchTab('tab-correlation')">Correlation Matrix</button>
    <button class="tab-btn" onclick="switchTab('tab-timeseries')">Time Series</button>
    <button class="tab-btn" onclick="switchTab('tab-alerts')">Alerts</button>
</div>

<!-- TAB 1: GLOBAL RISK MAP -->
<div id="tab-map" class="tab-content active">
    <div class="stats-row" id="stats-row"></div>
    <div class="card">
        <div class="card-title">World Risk Choropleth &mdash; Click a country to see its 24-dimension radar</div>
        <div id="choropleth-map" style="width:100%;height:520px;"></div>
    </div>
    <div class="card" id="radar-card" style="display:none;">
        <div class="card-title" id="radar-title">Dimension Radar</div>
        <div id="radar-chart" style="width:100%;height:480px;"></div>
    </div>
</div>

<!-- TAB 2: PORTFOLIO ANALYZER -->
<div id="tab-portfolio" class="tab-content">
    <div class="card">
        <div class="card-title">Analyze Country Portfolio</div>
        <div class="flex-row mb-16">
            <input type="text" id="portfolio-input"
                   placeholder="Enter ISO-3 codes: JPN, USA, DEU, CHN ..."
                   style="flex:1;min-width:300px;">
            <button class="btn" onclick="analyzePortfolio()">Analyze</button>
            <button class="btn btn-secondary" onclick="loadPreset('asia')">Asia Preset</button>
            <button class="btn btn-secondary" onclick="loadPreset('g7')">G7 Preset</button>
            <button class="btn btn-secondary" onclick="loadPreset('high_risk')">High Risk</button>
        </div>
        <p class="text-muted" style="font-size:12px;">
            Available codes: {available_codes}
        </p>
    </div>
    <div id="portfolio-results" style="display:none;">
        <div class="grid-2">
            <div class="card">
                <div class="card-title">Risk Ranking</div>
                <div id="portfolio-table-wrap" class="scrollable"></div>
            </div>
            <div class="card">
                <div class="card-title">Overall Score Comparison</div>
                <div id="portfolio-bar" style="width:100%;height:400px;"></div>
            </div>
        </div>
        <div class="card">
            <div class="card-title">Dimension Heatmap &mdash; Selected Countries &times; 24 Dimensions</div>
            <div id="portfolio-heatmap" style="width:100%;height:500px;"></div>
        </div>
    </div>
</div>

<!-- TAB 3: CORRELATION MATRIX -->
<div id="tab-correlation" class="tab-content">
    <div class="card">
        <div class="card-title">24&times;24 Dimension Correlation Matrix</div>
        <p class="text-muted mb-16" style="font-size:13px;">
            Pearson correlation across {len(summaries)} countries.
            Cells with |r| &gt; 0.70 are highlighted with annotation markers.
        </p>
        <div id="corr-heatmap" style="width:100%;height:700px;"></div>
    </div>
    <div class="card">
        <div class="card-title">Strongly Correlated Dimension Pairs (|r| &gt; 0.70)</div>
        <div id="corr-table-wrap" class="scrollable"></div>
    </div>
</div>

<!-- TAB 4: TIME SERIES -->
<div id="tab-timeseries" class="tab-content">
    <div class="card">
        <div class="card-title">Score History</div>
        <div class="flex-row mb-16">
            <label style="color:#8b949e;">Country:</label>
            <select id="ts-country" onchange="updateTimeSeries()" style="min-width:200px;">
                {country_options}
            </select>
            <label style="color:#8b949e;margin-left:16px;">Dimension:</label>
            <select id="ts-dimension" onchange="updateTimeSeries()" style="min-width:180px;">
                <option value="overall">Overall Score</option>
                {dim_options}
            </select>
        </div>
        <div id="ts-chart" style="width:100%;height:450px;"></div>
        <div id="ts-placeholder" class="text-center text-muted mt-16" style="display:none;padding:40px;">
            <p style="font-size:18px;">No historical data available for this selection.</p>
            <p style="font-size:13px;margin-top:8px;">
                Run <code>python scripts/build_baseline_scores.py</code> multiple times over different days to build time-series history.
            </p>
        </div>
    </div>
</div>

<!-- TAB 5: ALERTS -->
<div id="tab-alerts" class="tab-content">
    <div class="card">
        <div class="card-title">Recent Alerts</div>
        <div class="filter-group" id="alert-filters">
            <button class="filter-btn active" onclick="filterAlerts('ALL')">All</button>
            <button class="filter-btn" onclick="filterAlerts('CRITICAL')">Critical</button>
            <button class="filter-btn" onclick="filterAlerts('WARNING')">Warning</button>
            <button class="filter-btn" onclick="filterAlerts('INFO')">Info</button>
            <button class="filter-btn" onclick="filterAlerts('LOW')">Low</button>
        </div>
        <div id="alerts-table-wrap" class="scrollable"></div>
        <div id="alerts-empty" class="text-center text-muted" style="display:none;padding:40px;">
            <p style="font-size:18px;">No alerts found.</p>
            <p style="font-size:13px;margin-top:8px;">
                Alerts are generated during risk scoring runs and stored in <code>data/alerts/</code>.
            </p>
        </div>
    </div>
</div>

<script>
// Embedded Data
const MAP_LOCATIONS = {json.dumps(map_locations)};
const MAP_Z = {json.dumps(map_z)};
const MAP_TEXT = {json.dumps(map_text)};
const COUNTRY_SCORES = {json.dumps(country_scores_js)};
const DIM_KEYS = {json.dumps(DIMENSION_KEYS)};
const DIM_LABELS = {json.dumps(DIMENSION_LABELS)};
const TS_DATA = {json.dumps(ts_js)};
const ALERTS_DATA = {json.dumps(alerts_js)};
const CORR_MATRIX = {json.dumps(corr_js)};
const ISO3_TO_NAME = {json.dumps(ISO3_TO_NAME)};
const ALL_COUNTRIES = {json.dumps(all_countries)};

const DARK_LAYOUT = {{
    paper_bgcolor: '#161b22',
    plot_bgcolor: '#161b22',
    font: {{ color: '#c9d1d9', family: 'Segoe UI, system-ui, sans-serif' }},
    margin: {{ t: 30, b: 40, l: 60, r: 20 }},
}};

function switchTab(id) {{
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    document.querySelectorAll('.tab-btn').forEach(btn => {{
        if (btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(id)) btn.classList.add('active');
    }});
    if (id === 'tab-correlation' && !window._corrInit) {{ initCorrelation(); window._corrInit = true; }}
    if (id === 'tab-timeseries' && !window._tsInit) {{ updateTimeSeries(); window._tsInit = true; }}
    if (id === 'tab-alerts' && !window._alertsInit) {{ renderAlerts('ALL'); window._alertsInit = true; }}
}}

function riskLevel(score) {{
    if (score >= 80) return 'CRITICAL';
    if (score >= 60) return 'HIGH';
    if (score >= 40) return 'MEDIUM';
    if (score >= 20) return 'LOW';
    return 'MINIMAL';
}}
function riskColor(score) {{
    if (score >= 80) return '#ff1744';
    if (score >= 60) return '#ff9100';
    if (score >= 40) return '#ffea00';
    if (score >= 20) return '#00e676';
    return '#00b0ff';
}}
function badgeClass(level) {{
    return 'badge badge-' + level.toLowerCase();
}}

// TAB 1: Global Risk Map
function initMap() {{
    let critCnt=0,highCnt=0,medCnt=0,lowCnt=0,minCnt=0,sumScore=0;
    MAP_Z.forEach(s => {{
        sumScore += s;
        if (s>=80) critCnt++; else if (s>=60) highCnt++; else if (s>=40) medCnt++; else if (s>=20) lowCnt++; else minCnt++;
    }});
    const avgScore = MAP_Z.length > 0 ? (sumScore/MAP_Z.length).toFixed(1) : 0;
    document.getElementById('stats-row').innerHTML = `
        <div class="stat-card"><div class="stat-value">${{MAP_Z.length}}</div><div class="stat-label">Countries Monitored</div></div>
        <div class="stat-card"><div class="stat-value">${{avgScore}}</div><div class="stat-label">Avg Risk Score</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#ff1744">${{critCnt}}</div><div class="stat-label">Critical</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#ff9100">${{highCnt}}</div><div class="stat-label">High</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#ffea00">${{medCnt}}</div><div class="stat-label">Medium</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#00e676">${{lowCnt+minCnt}}</div><div class="stat-label">Low / Minimal</div></div>
    `;

    const trace = {{
        type: 'choropleth',
        locations: MAP_LOCATIONS,
        z: MAP_Z,
        text: MAP_TEXT,
        hoverinfo: 'text',
        colorscale: [[0,'#00b0ff'],[0.2,'#00e676'],[0.4,'#ffea00'],[0.6,'#ff9100'],[0.8,'#ff1744'],[1.0,'#b71c1c']],
        zmin: 0, zmax: 100,
        colorbar: {{
            title: 'Risk', tickvals: [0,20,40,60,80,100],
            ticktext: ['Minimal','Low','Medium','High','Critical','100'],
            len: 0.6, thickness: 15, outlinewidth: 0,
        }},
        marker: {{ line: {{ color: '#30363d', width: 0.5 }} }},
    }};

    const layout = {{
        ...DARK_LAYOUT,
        geo: {{
            bgcolor: '#0d1117', showframe: false, showcoastlines: true,
            coastlinecolor: '#30363d', showland: true, landcolor: '#21262d',
            showocean: true, oceancolor: '#0d1117', showlakes: false,
            projection: {{ type: 'natural earth' }},
            countrycolor: '#30363d', countrywidth: 0.5,
        }},
        margin: {{ t: 10, b: 10, l: 10, r: 10 }},
    }};

    Plotly.newPlot('choropleth-map', [trace], layout, {{
        responsive: true, displayModeBar: true,
        modeBarButtonsToRemove: ['toImage','sendDataToCloud'],
    }});

    document.getElementById('choropleth-map').on('plotly_click', function(data) {{
        const iso3 = data.points[0].location;
        showRadar(iso3);
    }});
}}

function showRadar(iso3) {{
    const info = COUNTRY_SCORES[iso3];
    if (!info) return;
    document.getElementById('radar-card').style.display = 'block';
    document.getElementById('radar-title').textContent =
        info.name + ' - 24 Dimension Risk Profile (Overall: ' + info.overall + ')';

    const values = DIM_KEYS.map(d => info.scores[d] || 0);
    const radarValues = [...values, values[0]];
    const radarLabels = [...DIM_LABELS, DIM_LABELS[0]];

    const trace = {{
        type: 'scatterpolar', r: radarValues, theta: radarLabels,
        fill: 'toself', fillcolor: 'rgba(88,166,255,0.15)',
        line: {{ color: '#58a6ff', width: 2 }},
        marker: {{ size: 5, color: '#58a6ff' }}, name: info.name,
    }};
    const layout = {{
        ...DARK_LAYOUT,
        polar: {{
            bgcolor: '#161b22',
            radialaxis: {{ visible: true, range: [0,100], tickvals: [20,40,60,80],
                tickfont: {{ size: 10, color: '#8b949e' }}, gridcolor: '#21262d', linecolor: '#30363d' }},
            angularaxis: {{ tickfont: {{ size: 11, color: '#c9d1d9' }}, gridcolor: '#21262d', linecolor: '#30363d' }},
        }},
        showlegend: false, margin: {{ t: 40, b: 40, l: 80, r: 80 }},
    }};
    Plotly.newPlot('radar-chart', [trace], layout, {{ responsive: true }});
    document.getElementById('radar-card').scrollIntoView({{ behavior: 'smooth' }});
}}

// TAB 2: Portfolio Analyzer
const PRESETS = {{
    asia: 'JPN,CHN,KOR,TWN,VNM,THA,MYS,SGP,IDN,PHL',
    g7: 'JPN,USA,DEU,GBR,FRA,ITA,CAN',
    high_risk: 'PRK,IRN,RUS,MMR,VEN,SOM,SSD,YEM,IRQ,UKR',
}};

function loadPreset(name) {{
    document.getElementById('portfolio-input').value = PRESETS[name] || '';
    analyzePortfolio();
}}

function analyzePortfolio() {{
    const raw = document.getElementById('portfolio-input').value.trim();
    if (!raw) return;
    const codes = raw.toUpperCase().split(/[,\\s]+/).filter(c => c.length === 3);
    const selected = [];
    codes.forEach(iso3 => {{
        const name = ISO3_TO_NAME[iso3];
        if (name && COUNTRY_SCORES[iso3]) {{
            selected.push({{ iso3, name, ...COUNTRY_SCORES[iso3] }});
        }}
    }});
    if (selected.length === 0) {{
        alert('No matching countries found. Use ISO-3 codes like JPN, USA, DEU.');
        return;
    }}
    document.getElementById('portfolio-results').style.display = 'block';
    selected.sort((a,b) => b.overall - a.overall);

    let tableHTML = '<table><thead><tr><th>#</th><th>Country</th><th>Code</th><th>Score</th><th>Level</th></tr></thead><tbody>';
    selected.forEach((c,i) => {{
        const level = riskLevel(c.overall);
        tableHTML += '<tr><td>'+(i+1)+'</td><td>'+c.name+'</td><td>'+c.iso3+'</td><td style="font-weight:700;color:'+riskColor(c.overall)+'">'+c.overall+'</td><td><span class="'+badgeClass(level)+'">'+level+'</span></td></tr>';
    }});
    tableHTML += '</tbody></table>';
    document.getElementById('portfolio-table-wrap').innerHTML = tableHTML;

    const barTrace = {{
        type: 'bar',
        x: selected.map(c => c.name), y: selected.map(c => c.overall),
        marker: {{ color: selected.map(c => riskColor(c.overall)), line: {{ color: '#30363d', width: 1 }} }},
        text: selected.map(c => c.overall), textposition: 'outside',
        textfont: {{ color: '#c9d1d9', size: 12 }},
    }};
    Plotly.newPlot('portfolio-bar', [barTrace], {{
        ...DARK_LAYOUT,
        yaxis: {{ title: 'Risk Score', range: [0,110], gridcolor: '#21262d' }},
        xaxis: {{ tickangle: -30 }},
    }}, {{ responsive: true }});

    const zData = selected.map(c => DIM_KEYS.map(d => c.scores[d] || 0));
    const heatTrace = {{
        type: 'heatmap', z: zData, x: DIM_LABELS, y: selected.map(c => c.name),
        colorscale: [[0,'#0d1117'],[0.2,'#00b0ff'],[0.4,'#00e676'],[0.5,'#ffea00'],[0.7,'#ff9100'],[1.0,'#ff1744']],
        zmin: 0, zmax: 100,
        colorbar: {{ title: 'Score', len: 0.6, thickness: 15 }},
        hovertemplate: '%{{y}}<br>%{{x}}: %{{z}}<extra></extra>',
    }};
    Plotly.newPlot('portfolio-heatmap', [heatTrace], {{
        ...DARK_LAYOUT,
        xaxis: {{ tickangle: -45, tickfont: {{ size: 11 }} }},
        yaxis: {{ tickfont: {{ size: 12 }} }},
        margin: {{ t: 20, b: 120, l: 140, r: 20 }},
    }}, {{ responsive: true }});
}}

// TAB 3: Correlation Matrix
function initCorrelation() {{
    const annotations = [];
    const strongPairs = [];
    for (let i = 0; i < DIM_KEYS.length; i++) {{
        for (let j = i + 1; j < DIM_KEYS.length; j++) {{
            const r = CORR_MATRIX[i][j];
            if (Math.abs(r) > 0.70) {{
                annotations.push({{ x: DIM_LABELS[j], y: DIM_LABELS[i], text: r.toFixed(2), showarrow: false,
                    font: {{ color: '#f0f6fc', size: 9, family: 'monospace' }} }});
                annotations.push({{ x: DIM_LABELS[i], y: DIM_LABELS[j], text: r.toFixed(2), showarrow: false,
                    font: {{ color: '#f0f6fc', size: 9, family: 'monospace' }} }});
                strongPairs.push({{ dim1: DIM_LABELS[i], dim2: DIM_LABELS[j], r: r }});
            }}
        }}
    }}

    const trace = {{
        type: 'heatmap', z: CORR_MATRIX, x: DIM_LABELS, y: DIM_LABELS,
        colorscale: [[0,'#b71c1c'],[0.25,'#ff9100'],[0.5,'#161b22'],[0.75,'#00b0ff'],[1.0,'#1565c0']],
        zmin: -1, zmax: 1,
        colorbar: {{ title: 'r', len: 0.6, thickness: 15 }},
        hovertemplate: '%{{x}} vs %{{y}}<br>r = %{{z:.3f}}<extra></extra>',
    }};
    Plotly.newPlot('corr-heatmap', [trace], {{
        ...DARK_LAYOUT,
        xaxis: {{ tickangle: -45, tickfont: {{ size: 10 }} }},
        yaxis: {{ tickfont: {{ size: 10 }}, autorange: 'reversed' }},
        margin: {{ t: 20, b: 120, l: 120, r: 20 }},
        annotations: annotations,
    }}, {{ responsive: true }});

    strongPairs.sort((a,b) => Math.abs(b.r) - Math.abs(a.r));
    let tbl = '<table><thead><tr><th>Dimension 1</th><th>Dimension 2</th><th>r</th><th>Strength</th></tr></thead><tbody>';
    if (strongPairs.length === 0) {{
        tbl += '<tr><td colspan="4" class="text-center text-muted" style="padding:20px;">No dimension pairs with |r| > 0.70 found.</td></tr>';
    }}
    strongPairs.forEach(p => {{
        const strength = Math.abs(p.r) > 0.90 ? 'Very Strong' : Math.abs(p.r) > 0.80 ? 'Strong' : 'Moderate-Strong';
        const color = p.r > 0 ? '#00b0ff' : '#ff9100';
        tbl += '<tr><td>'+p.dim1+'</td><td>'+p.dim2+'</td><td style="font-weight:700;color:'+color+'">'+p.r.toFixed(3)+'</td><td>'+strength+' '+(p.r > 0 ? '(positive)' : '(negative)')+'</td></tr>';
    }});
    tbl += '</tbody></table>';
    document.getElementById('corr-table-wrap').innerHTML = tbl;
}}

// TAB 4: Time Series
function updateTimeSeries() {{
    const country = document.getElementById('ts-country').value;
    const dimension = document.getElementById('ts-dimension').value;
    const countryData = TS_DATA[country];
    let xVals = [], yVals = [];
    if (countryData) {{
        const dimData = countryData[dimension];
        if (dimData) {{ xVals = dimData.x; yVals = dimData.y; }}
    }}
    if (xVals.length === 0) {{
        document.getElementById('ts-chart').style.display = 'none';
        document.getElementById('ts-placeholder').style.display = 'block';
        return;
    }}
    document.getElementById('ts-chart').style.display = 'block';
    document.getElementById('ts-placeholder').style.display = 'none';

    const dimLabel = dimension === 'overall' ? 'Overall Score'
        : DIM_LABELS[DIM_KEYS.indexOf(dimension)] || dimension;

    const trace = {{
        type: 'scatter', mode: 'lines+markers',
        x: xVals, y: yVals,
        line: {{ color: '#58a6ff', width: 2.5 }},
        marker: {{ size: 6, color: '#58a6ff' }},
        fill: 'tozeroy', fillcolor: 'rgba(88,166,255,0.08)',
        name: dimLabel,
    }};
    const shapes = [
        {{ type:'line', y0:80, y1:80, x0:xVals[0], x1:xVals[xVals.length-1], line:{{ color:'rgba(255,23,68,0.3)', width:1, dash:'dash' }} }},
        {{ type:'line', y0:60, y1:60, x0:xVals[0], x1:xVals[xVals.length-1], line:{{ color:'rgba(255,145,0,0.3)', width:1, dash:'dash' }} }},
        {{ type:'line', y0:40, y1:40, x0:xVals[0], x1:xVals[xVals.length-1], line:{{ color:'rgba(255,234,0,0.2)', width:1, dash:'dash' }} }},
    ];
    Plotly.newPlot('ts-chart', [trace], {{
        ...DARK_LAYOUT,
        xaxis: {{ title: 'Date', gridcolor: '#21262d' }},
        yaxis: {{ title: 'Score', range: [0,105], gridcolor: '#21262d' }},
        shapes: shapes,
        annotations: [
            {{ x: xVals[xVals.length-1], y: 80, text: 'CRITICAL', showarrow: false, font: {{ color: '#ff1744', size: 10 }}, xanchor: 'right' }},
            {{ x: xVals[xVals.length-1], y: 60, text: 'HIGH', showarrow: false, font: {{ color: '#ff9100', size: 10 }}, xanchor: 'right' }},
        ],
    }}, {{ responsive: true }});
}}

// TAB 5: Alerts
function filterAlerts(severity) {{
    document.querySelectorAll('#alert-filters .filter-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    renderAlerts(severity);
}}

function renderAlerts(filterSeverity) {{
    let data = ALERTS_DATA;
    if (filterSeverity !== 'ALL') {{
        data = data.filter(a => a.severity.toUpperCase() === filterSeverity);
    }}
    if (data.length === 0) {{
        document.getElementById('alerts-table-wrap').innerHTML = '';
        document.getElementById('alerts-empty').style.display = 'block';
        return;
    }}
    document.getElementById('alerts-empty').style.display = 'none';
    let tbl = '<table><thead><tr><th>Time</th><th>Severity</th><th>Type</th><th>Message</th><th>Country</th><th>Source</th></tr></thead><tbody>';
    data.forEach(a => {{
        const sev = a.severity.toUpperCase();
        const cls = sev==='CRITICAL' ? 'badge-critical' : sev==='WARNING'||sev==='HIGH' ? 'badge-warning' : sev==='LOW' ? 'badge-low' : 'badge-info';
        tbl += '<tr><td style="white-space:nowrap">'+(a.dispatched_at||'-')+'</td><td><span class="badge '+cls+'">'+sev+'</span></td><td>'+(a.type||'-')+'</td><td>'+(a.message||'-')+'</td><td>'+(a.country||'-')+'</td><td style="font-size:11px;color:#8b949e">'+(a.file||'-')+'</td></tr>';
    }});
    tbl += '</tbody></table>';
    document.getElementById('alerts-table-wrap').innerHTML = tbl;
}}

// Init
document.addEventListener('DOMContentLoaded', function() {{
    initMap();
    renderAlerts('ALL');
    window._alertsInit = true;
}});
</script>

<div style="text-align:center;padding:16px;color:#484f58;font-size:11px;border-top:1px solid #21262d;margin-top:20px;">
    SCRI Platform v{VERSION} &middot; Dashboard generated {gen_time} &middot; {len(summaries)} countries &middot; 24 dimensions
</div>

</body>
</html>'''

    return html


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("STREAM 3: Interactive HTML Dashboard Generator")
    print("=" * 60)

    print("\n[1/5] Loading risk summaries...")
    summaries = load_risk_summaries()

    print("[2/5] Loading time-series data...")
    ts_data = load_timeseries_data()

    print("[3/5] Loading alerts...")
    alerts = load_alerts()

    print("[4/5] Computing correlation matrix...")
    corr_matrix = compute_correlation_matrix(summaries)

    print("[5/5] Generating dashboard HTML...")
    html = generate_html(summaries, ts_data, alerts, corr_matrix)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    file_size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"\n{'=' * 60}")
    print(f"Dashboard generated successfully!")
    print(f"  Output: {OUTPUT_PATH}")
    print(f"  Size:   {file_size_kb:.1f} KB")
    print(f"  Countries: {len(summaries)}")
    print(f"  Dimensions: {len(DIMENSION_KEYS)}")
    print(f"  Time-series locations: {len(ts_data)}")
    print(f"  Alerts: {len(alerts)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
