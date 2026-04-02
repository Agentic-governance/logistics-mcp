# ROLE-4 (Platform Engineer) — Changes Summary for SCRI v0.9.0

**Date:** 2026-03-27
**Engineer:** ROLE-4 (Platform Engineer)

---

## Task 4-A: OpenAPI Documentation

**File:** `docs/openapi_spec.yaml`

- Created comprehensive OpenAPI 3.0.3 specification covering **75 API paths** and **35 component schemas**
- All endpoints organized by tags: Health & Status, Sanctions Screening, Risk Scoring, Disasters, Maritime, Conflict, Economic, Trade, Energy, Health, Food Security, Weather, Compliance, Infrastructure, Aviation, Japan, Dashboard, Alerts & Monitoring, Supply Chain Graph, Route Risk, Concentration, Simulation, Due Diligence, Commodity Exposure, Bulk Assessment, Climate, Cyber, Data Quality, Analytics, Forecasting, Screening, Cost Impact, BOM Analysis
- Every endpoint includes: path, HTTP method, description, parameters (with types, defaults, constraints), request body schemas, and response schemas
- Reusable schemas defined in `components/schemas` for all Pydantic models
- Standard error responses (429 Rate Limited, 502 Upstream Error) defined in `components/responses`

---

## Task 4-B: BOM & Cost Impact Dashboard Tabs

**File:** `dashboard/index.html` (modified)

### BOM Analysis Tab
- Textarea for pasting/uploading BOM JSON with syntax-highlighted placeholder
- Product name input field and Tier-2/3 inference checkbox
- "Load Sample BOM" button that fetches from `/api/v1/bom/sample`
- "Analyze BOM" button that calls `/api/v1/bom/analyze`
- Results display: overall BOM risk score, parts count, resilience score, financial exposure
- Interactive bar chart of per-part risk scores (via Plotly)
- Bottleneck analysis panel with color-coded severity
- Tier-2 inferred parts table with country and risk columns
- Financial exposure summary table

### Cost Impact Tab
- Scenario dropdown: sanctions, conflict, disaster, port_closure, pandemic
- Annual spend input field (USD)
- Daily revenue input field (USD)
- Duration slider: 30-180 days with live value display
- "Estimate Cost" button calling `/api/v1/cost-impact/estimate`
- "Compare All" button calling `/api/v1/cost-impact/compare`
- Results: total estimated cost, procurement premium, logistics surcharge, production loss
- Detailed breakdown table with percentage of total
- Scenario comparison bar chart (Plotly) showing all scenarios side by side
- Comparison table with per-category costs for all scenarios

---

## Task 4-C: Rate Limiting

**Files:**
- `api/rate_limiter.py` (new)
- `api/main.py` (modified)

### In-Memory Rate Limiter (`api/rate_limiter.py`)
- Dependency-free sliding-window counter implementation
- Three tiers: `general` (60 req/min), `heavy` (10 req/min), `screening` (30 req/min)
- Thread-safe with periodic cleanup to prevent memory growth
- Returns `RateLimitExceededError` with `retry_after` value
- Endpoint classification helper (`classify_endpoint`) for automatic tier assignment
- `get_remaining()` method for rate limit headers

### Rate Limit Coverage in `api/main.py`
- Added `@limiter.limit("60/minute")` to **34 previously unprotected general endpoints**
- Added `@limiter.limit("10/minute")` to **19 previously unprotected heavy computation endpoints**
- Added `request: Request` parameter to all endpoints for slowapi compatibility
- Only `/metrics` (Prometheus scraping) and `/dashboard` (static HTML) remain unlimited
- Total rate-limited endpoints: **67** (up from 12)

---

## Task 4-D: Expanded Prometheus Metrics

**File:** `features/monitoring/metrics.py` (new)

Built-in metric types (no external dependencies required):
- `_Counter` — thread-safe monotonic counter
- `_Histogram` — thread-safe histogram with configurable buckets
- `_Gauge` — thread-safe gauge (set/inc/dec)

Metric instances:
1. **`scri_http_requests_total`** — Request count by method, endpoint, status code
2. **`scri_http_request_duration_seconds`** — Request latency histogram (10 buckets)
3. **`scri_active_scoring_jobs`** — Active scoring jobs gauge
4. **`scri_data_source_health`** — Per-source health status (1=up, 0=down)
5. **`scri_score_computation_duration_seconds`** — Score computation time histogram
6. **`scri_sanctions_screenings_total`** — Screening count by match status
7. **`scri_bom_analyses_total`** — BOM analysis count
8. **`scri_cost_impact_estimates_total`** — Cost estimates by scenario
9. **`scri_forecast_requests_total`** — Forecast requests by location/dimension
10. **`scri_alerts_dispatched_total`** — Alerts by severity
11. **`scri_active_monitors`** — Active supplier monitor count

Utilities:
- `ScoreTimer` context manager for timing score computations
- `record_*()` helper functions for each metric type
- `generate_metrics_text()` — Full Prometheus text exposition format exporter

Note: The existing `server/middleware/metrics.py` (using `prometheus_client`) continues to operate via the `/metrics` endpoint. The new module in `features/monitoring/metrics.py` provides a complementary, dependency-free metrics layer that can be wired into domain-specific code paths.

---

## Task 4-E: MCP Tools Catalog

**File:** `docs/mcp_tools_catalog.md` (new, replaces outdated version)

- **Complete table of all 32 MCP tools** with: name, description, parameters (types and defaults), and return type
- **Detailed usage examples for top 10 tools** with JSON request/response pairs:
  1. `screen_sanctions`
  2. `get_risk_score`
  3. `get_location_risk`
  4. `compare_locations`
  5. `analyze_bom_risk`
  6. `estimate_disruption_cost`
  7. `analyze_portfolio`
  8. `screen_supplier_reputation`
  9. `analyze_route_risk`
  10. `get_global_risk_dashboard`
- **Integration guide** covering:
  - Prerequisites and setup
  - Claude Desktop configuration
  - Standalone MCP server execution
  - Tool invocation patterns
  - Caching strategy (4 TTL caches with sizes and durations)
  - Input validation rules
  - Error handling patterns
  - All 24 risk dimensions enumerated
  - 9 disruption scenarios documented
  - Rate limit tiers per endpoint category

---

## Version Updates

- API version bumped from `0.8.0` to `0.9.0` in `api/main.py`
- Dashboard version updated from `v0.6.3` to `v0.9.0`

## Files Changed/Created

| File | Status | Lines |
|------|--------|-------|
| `docs/openapi_spec.yaml` | **New** | 2,578 |
| `docs/mcp_tools_catalog.md` | **New** | 427 |
| `features/monitoring/metrics.py` | **New** | 317 |
| `api/rate_limiter.py` | **New** | 171 |
| `dashboard/index.html` | **Modified** | 937 (was 525) |
| `api/main.py` | **Modified** | 1,671 (was 1,606) |
| `docs/ROLE4_CHANGES_SUMMARY.md` | **New** | this file |
