# STREAM 7: Test Expansion & CI Preparation

**Date:** 2026-03-21
**Status:** COMPLETE (3/3 deliverables)
**Test Result:** 30/30 PASSED in 2.66s (1 slow test deselected)

---

## Summary

Stream 7 expands the SCRI Platform test suite with integration tests that exercise
the full pipeline end-to-end, adds a GitHub Actions CI workflow for automated testing,
and provides a performance benchmark script for profiling core operations.

| Deliverable | File | Description | Status |
|-------------|------|-------------|--------|
| 7-A | `tests/test_integration.py` | 15 integration tests across 7 test classes | COMPLETE |
| 7-B | `.github/workflows/test.yml` | GitHub Actions CI workflow | COMPLETE |
| 7-C | `scripts/benchmark_performance.py` | Performance benchmark with timing & memory | COMPLETE |

---

## 7-A: Integration Test Suite

**File:** `tests/test_integration.py`
**Support:** `tests/conftest.py` (pytest marker registration)

### Test Classes & Cases

| # | Test Class | Test Case | Description | Status |
|---|-----------|-----------|-------------|--------|
| 1 | `TestFullRiskAssessmentPipeline` | `test_full_risk_assessment_pipeline` | Score JP, CN, YE, SG; verify scores in [0,100] | PASSED |
| 1b | | `test_full_risk_assessment_pipeline_ordering` | Yemen riskier than Singapore | PASSED |
| 1c | | `test_full_risk_assessment_pipeline_live` | Live API scoring (marked @slow) | DESELECTED |
| 2 | `TestSanctionsScreenKnownEntity` | `test_sanctions_screen_known_entity` | Screen "Rosoboronexport"; verify match structure | PASSED |
| 2b | | `test_clean_entity_not_matched` | Toyota should not be sanctioned | PASSED |
| 3 | `TestPortfolioAnalysis` | `test_portfolio_analysis` | 5-entity portfolio; verify structure, distribution, weighted score | PASSED |
| 4 | `TestRouteRiskWithChokepoint` | `test_route_risk_with_chokepoint` | Shanghai->Rotterdam passes Suez Canal | PASSED |
| 4b | | `test_chokepoint_suez_has_risk_score` | Suez has non-zero baseline risk | PASSED |
| 4c | | `test_route_risk_alternative_routes` | Alternative routes suggested | PASSED |
| 5 | `TestTimeseriesStoreAndRetrieve` | `test_timeseries_store_and_retrieve` | Store score, retrieve via get_latest & get_history | PASSED |
| 5b | | `test_timeseries_daily_summary` | Daily summary store/retrieve via SQL | PASSED |
| 6 | `TestDDReportContainsRequiredFields` | `test_dd_report_contains_required_fields` | 11 required fields verified | PASSED |
| 6b | | `test_dd_report_edd_triggers_on_high_risk` | EDD triggered on sanctions match | PASSED |
| 7 | `TestAlertGeneration` | `test_alert_generation` | Score jump +45 triggers CRITICAL/WARNING alerts | PASSED |
| 7b | | `test_alert_critical_threshold` | Score >=80 triggers CRITICAL level alert | PASSED |
| 7c | | `test_validate_score_consistency` | Weight sum validation passes | PASSED |

### Design Decisions

- **Deterministic mock scoring:** `_make_deterministic_score()` provides per-country
  risk profiles (JP/CN/YE/SG) without calling any external APIs. This ensures tests
  are fast, repeatable, and CI-friendly.
- **Temporary databases:** Timeseries and alert history tests use `tempfile.TemporaryDirectory()`
  to avoid polluting production data.
- **`@pytest.mark.slow`:** Live API tests are marked slow and skipped by default in CI
  with `pytest -m "not slow"`.
- **Mock path correctness:** DD generator imports `screen_entity` and `calculate_risk_score`
  inside method bodies, so mocks target the source modules (`pipeline.sanctions.screener`
  and `scoring.engine`) rather than the consumer module.

---

## 7-B: GitHub Actions CI Workflow

**File:** `.github/workflows/test.yml`

### Pipeline Steps

| Step | Command | Purpose |
|------|---------|---------|
| Checkout | `actions/checkout@v4` | Clone repository |
| Python setup | `actions/setup-python@v5` (3.11) | Install Python with pip cache |
| Install deps | `pip install -r requirements.txt` | All production dependencies |
| Run tests | `pytest tests/ -v --ignore=test_connectivity -m "not slow"` | Unit + integration (skip slow) |
| Correlation diagnostics | `python scripts/diagnose_correlations.py` | Verify dimension independence |
| MCP tool count | `grep -c "@mcp.tool" mcp_server/server.py` | Verify >= 20 tools registered |

### Triggers

- Push to: `main`, `develop`, `stream-*`
- Pull requests to: `main`, `develop`

---

## 7-C: Performance Benchmark Script

**File:** `scripts/benchmark_performance.py`
**Output:** `reports/v07_STREAM7_benchmark.md`

### Operations Benchmarked

| # | Operation | Description | Mode |
|---|-----------|-------------|------|
| 1 | Single risk score | One country through 24 dimensions | Mock / Live |
| 2 | Bulk risk scores | 10 countries sequentially | Mock / Live |
| 3 | Sanctions screening | 5 entity names against sanctions DB | Always DB |
| 4 | Portfolio analysis | 5 entities with ranking | Mock / Live |

### Features

- `time.perf_counter` for high-resolution wall-clock timing
- `tracemalloc` for peak memory measurement
- `--live` flag for external API benchmarks (default: mock)
- Markdown report output with performance targets table

### Performance Targets

| Operation | Mock Target | Live Target |
|-----------|------------|-------------|
| Single score | < 0.1s | < 30s |
| Bulk 10 | < 1.0s | < 300s |
| Sanctions 5 | < 2.0s | < 2.0s |
| Portfolio 5 | < 1.0s | < 150s |

---

## Full Test Results (all test files)

```
tests/test_analytics.py    6 PASSED
tests/test_integration.py  15 PASSED (1 slow deselected)
tests/test_sanctions.py    3 PASSED
tests/test_scoring.py      6 PASSED
-----------------------------------------
TOTAL                      30 PASSED, 0 FAILED, 1 DESELECTED
Time                       2.66s
```

### Test Coverage by Module

| Module | Tests | Tested Via |
|--------|-------|-----------|
| `scoring.engine` | 9 | test_scoring + test_integration |
| `pipeline.sanctions.screener` | 5 | test_sanctions + test_integration |
| `features.analytics.portfolio_analyzer` | 2 | test_analytics + test_integration |
| `features.analytics.correlation_analyzer` | 1 | test_analytics |
| `features.analytics.benchmark_analyzer` | 1 | test_analytics |
| `features.analytics.sensitivity_analyzer` | 2 | test_analytics |
| `features.route_risk.analyzer` | 3 | test_integration |
| `features.timeseries.store` | 2 | test_integration |
| `features.reports.dd_generator` | 2 | test_integration |
| `features.monitoring.anomaly_detector` | 3 | test_integration |

---

## Files Created/Modified

| File | Action | Lines |
|------|--------|-------|
| `tests/test_integration.py` | CREATED | ~340 |
| `tests/conftest.py` | CREATED | ~12 |
| `.github/workflows/test.yml` | CREATED | ~47 |
| `scripts/benchmark_performance.py` | CREATED | ~230 |
| `reports/v07_STREAM7_complete.md` | CREATED | This file |

---

*Generated 2026-03-21 -- SCRI Platform v0.7*
