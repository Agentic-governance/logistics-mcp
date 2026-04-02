# STREAM 5: MCP Tool Enhancements — Completion Report

**Date:** 2026-03-21
**Status:** COMPLETE
**File Modified:** `mcp_server/server.py`
**Total MCP Tools:** 25 (22 existing + 3 new)

---

## TASK 5-A: Enhanced `get_risk_score` Tool

### New Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dimensions` | `list[str]` | `[]` | Filter to specific dimensions (empty = all 24) |
| `include_forecast` | `bool` | `False` | Add 30-day risk score forecast |
| `include_history` | `bool` | `False` | Add past 90 days of score history from timeseries.db |
| `explain` | `bool` | `False` | Add human-readable explanation for each dimension |

### Implementation Details

- **Dimension filtering:** When `dimensions` is non-empty, only the specified dimensions are included in the `scores` dict. A `filtered_dimensions` key is added to the response.
- **`explain=True`:** Adds an `explanations` dict with keys matching `scores`. Each value is a Japanese-language string explaining the data source, what the score measures, and a severity interpretation (minimal/low/medium/high/critical).
- **`include_history=True`:** Reads from `data/timeseries.db` via `RiskTimeSeriesStore.get_history()`. Returns up to 90 days of historical data points for the requested dimensions.
- **`include_forecast=True`:** Uses `RiskForecaster.forecast()` (moving average + trend-based prediction). Returns 30-day forecasted scores with confidence intervals. Falls back gracefully if insufficient data.
- All new parameters are backward-compatible; existing callers are unaffected.

### Verification

```
get_risk_score parameters:
  supplier_id: string (required)
  company_name: string (required)
  country: string (optional)
  location: string (optional)
  dimensions: array[string] (default: [])
  include_forecast: boolean (default: false)
  include_history: boolean (default: false)
  explain: boolean (default: false)
```

---

## TASK 5-B: New Tool — `compare_risk_trends`

### Signature

```python
@mcp.tool()
async def compare_risk_trends(
    locations: list[str],
    dimension: str = "overall",
    period_days: int = 90,
) -> dict:
```

### Functionality

- Reads from `data/timeseries.db` (`risk_scores` and `risk_summaries` tables)
- Calculates **linear regression slope** for each location's score trajectory
- Classifies trend direction:
  - `slope > 0.5` → `deteriorating` (risk increasing)
  - `slope < -0.5` → `improving` (risk decreasing)
  - otherwise → `stable`
- Returns `most_improved` and `most_deteriorated` locations
- Handles insufficient data gracefully (`insufficient_data` direction)
- Country names normalized via `validate_country()`

### Response Structure

```json
{
  "dimension": "overall",
  "period_days": 90,
  "locations_compared": 3,
  "trends": [
    {
      "location": "Japan",
      "slope": 0.0,
      "direction": "stable",
      "latest_score": 16.0,
      "earliest_score": 16.0,
      "change": 0.0,
      "data_points": 5
    }
  ],
  "most_improved": "Vietnam",
  "most_deteriorated": "China"
}
```

---

## TASK 5-C: New Tool — `explain_score_change`

### Signature

```python
@mcp.tool()
async def explain_score_change(
    location: str,
    from_date: str,
    to_date: str,
) -> dict:
```

### Functionality

- Reads two snapshots from `risk_summaries` table (closest dates to requested range)
- Calculates per-dimension deltas (24 dimensions)
- Returns drivers sorted by `|change|` descending
- Provides `top_worsened` and `top_improved` lists
- Generates a Japanese-language `summary` sentence for executive communication
- Each driver includes dimension explanation text

### Response Structure

```json
{
  "location": "Japan",
  "from_date": "2026-03-01",
  "to_date": "2026-03-18",
  "overall_change": {
    "from_score": 0.0,
    "to_score": 16.0,
    "change": 16.0,
    "direction": "worsened"
  },
  "drivers": [
    {
      "dimension": "japan_economy",
      "from_score": 0,
      "to_score": 35,
      "change": 35,
      "abs_change": 35,
      "direction": "increased",
      "explanation": "..."
    }
  ],
  "top_worsened": [...],
  "top_improved": [...],
  "summary": "Japanの総合リスクスコアは..."
}
```

---

## TASK 5-D: New Tool — `get_risk_report_card`

### Signature

```python
@mcp.tool()
async def get_risk_report_card(location: str) -> dict:
```

### Functionality

Returns a comprehensive executive-summary report card with 7 sections:

| Section | Description |
|---------|-------------|
| `overall_score` | Current 24-dimension weighted risk score (0-100) |
| `risk_level` | CRITICAL / HIGH / MEDIUM / LOW / MINIMAL |
| `top_3_risks` | Top 3 risk dimensions with scores and explanations |
| `trend` | Linear regression trend from timeseries.db (improving/stable/deteriorating) |
| `peer_comparison` | Percentile rank against all 50 tracked countries, median score |
| `key_alerts` | Dimensions at HIGH (>=60) or CRITICAL (>=80) level |
| `recommended_actions` | Context-aware action items in Japanese |

### Response Structure

```json
{
  "location": "Japan",
  "overall_score": 32,
  "risk_level": "LOW",
  "top_3_risks": [
    {"dimension": "japan_economy", "score": 35, "explanation": "..."},
    {"dimension": "currency", "score": 30, "explanation": "..."},
    {"dimension": "climate_risk", "score": 29, "explanation": "..."}
  ],
  "trend": {"direction": "stable", "slope": 0.12, "data_points": 5},
  "peer_comparison": {
    "percentile": 36.0,
    "peer_count": 50,
    "median_score": 38.0,
    "interpretation": "上位64%（50カ国中）。中央値は38.0。"
  },
  "key_alerts": [],
  "recommended_actions": ["現状維持: リスクレベルは許容範囲内です。定期監視を継続してください。"],
  "all_scores": {...},
  "generated_at": "2026-03-21T...",
  "report_format": "executive_summary"
}
```

### Recommended Actions Logic

- Sanctions detected → Legal review recommendation
- Overall >= 60 → Alternative supplier recommendation
- Conflict/Political >= 50 → Geopolitical monitoring enhancement
- Disaster/Weather/Climate >= 40 → BCP update recommendation
- No alerts → Status quo maintenance

---

## Verification Results

### Syntax Check
```
py_compile: PASSED
```

### Import Test
```
from mcp_server.server import mcp
25 tools registered
```

### Tool List
```
 1. screen_sanctions
 2. monitor_supplier
 3. get_risk_score          ← ENHANCED (5-A)
 4. get_location_risk
 5. get_global_risk_dashboard
 6. get_supply_chain_graph
 7. get_risk_alerts
 8. bulk_screen
 9. compare_locations
10. analyze_route_risk
11. get_concentration_risk
12. simulate_disruption
13. generate_dd_report
14. get_commodity_exposure
15. bulk_assess_suppliers
16. get_data_quality_report
17. analyze_portfolio
18. analyze_risk_correlations
19. find_leading_risk_indicators
20. benchmark_risk_profile
21. analyze_score_sensitivity
22. simulate_what_if
23. compare_risk_trends      ← NEW (5-B)
24. explain_score_change     ← NEW (5-C)
25. get_risk_report_card     ← NEW (5-D)
```

### Functional Tests
- `get_risk_score` with `explain=True`, `dimensions=["conflict","economic","currency"]`, `include_history=True` → PASSED
- `compare_risk_trends(["Japan","China","Vietnam"])` → PASSED
- `explain_score_change("Japan", "2026-03-01", "2026-03-21")` → PASSED
- `get_risk_report_card("Japan")` → PASSED (percentile: 36th among 50 countries)

---

## Architecture Notes

- All new tools use `sqlite3` directly for `timeseries.db` reads (no ORM dependency)
- Country normalization via `validate_country()` for consistent querying
- Dimension explanations are defined in `_DIMENSION_EXPLANATIONS` dict (24 entries, Japanese)
- Async tools (`compare_risk_trends`, `explain_score_change`, `get_risk_report_card`) are compatible with FastMCP's async handling
- No breaking changes to existing API contracts; all parameters are optional with backward-compatible defaults
