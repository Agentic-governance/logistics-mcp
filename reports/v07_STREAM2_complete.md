# STREAM 2: Correlation Audit Automation -- Implementation Complete

**Date:** 2026-03-21
**Version:** v0.7-STREAM2
**Status:** COMPLETE

---

## Summary

STREAM 2 adds automated weekly correlation auditing to the SCRI Platform.
The system detects new high-correlation dimension pairs, compares them against
a curated list of accepted causal/geographic-overlap pairs, and generates
alerts for unexpected SOURCE_PROBLEM or DOUBLE_COUNTING correlations.

---

## TASK 2-A: Weekly Correlation Audit Scheduler Job

**File:** `features/timeseries/scheduler.py`

### Changes

- Added `run_weekly_correlation_audit()` method to `RiskScoreScheduler`
- Registered as APScheduler cron job: `day_of_week='sat', hour=19, minute=0`
  (UTC Saturday 19:00 = JST Sunday 04:00)
- Added `CORRELATION_AUDIT_COUNTRIES` -- 30-country geographically balanced subset
- Added helper functions:
  - `_load_accepted_correlations()` -- reads `config/accepted_correlations.yaml`
  - `_is_accepted_pair()` -- checks if a pair is in the accepted list (with per-pair r_threshold)
  - `_write_correlation_alert()` -- writes JSONL alerts to `data/alerts/`

### Audit Logic

1. Compute Pearson correlation matrix for 30 countries across all 24 dimensions
2. Extract all pairs with |r| > 0.85
3. Load accepted pairs from `config/accepted_correlations.yaml`
4. For each non-accepted pair, classify using `diagnose_correlations.classify_correlation()`
5. Generate `data/alerts/{date}.jsonl` entries for SOURCE_PROBLEM and DOUBLE_COUNTING pairs
6. Return summary dict with counts and alert details

### Scheduler Jobs (now 6 total)

| Job ID                      | Schedule                    | Description                      |
|-----------------------------|-----------------------------|----------------------------------|
| `full_assessment`           | Every 6 hours               | Full 50-country risk scoring     |
| `critical_update`           | Every 1 hour                | CRITICAL-only country updates    |
| `sanctions_update`          | Daily 02:00 JST (17:00 UTC) | OFAC/UN/EU sanctions refresh     |
| `correlation_check`         | Sunday 04:00 JST            | Quick 10-country correlation     |
| `weekly_correlation_audit`  | Sunday 04:00 JST            | **NEW** 30-country full audit    |
| `source_health`             | Every 1 hour                | Data source health checks        |

---

## TASK 2-B: Accepted Correlations Configuration

**File:** `config/accepted_correlations.yaml`

### All 9 Accepted CAUSAL_ACCEPTABLE Pairs

| dim1          | dim2          | r_threshold | Reason                                                                |
|---------------|---------------|-------------|-----------------------------------------------------------------------|
| conflict      | humanitarian  | 0.90        | Causal: conflict drives humanitarian crises                           |
| climate_risk  | conflict      | 0.92        | Geographic overlap: sub-Saharan Africa                                |
| geo_risk      | conflict      | 0.90        | Causal: geopolitical tensions drive armed conflicts                   |
| conflict      | political     | 0.90        | Causal: political instability correlates with conflict                |
| food_security | humanitarian  | 0.90        | Causal: food insecurity drives humanitarian emergencies               |
| political     | compliance    | 0.85        | Causal: weak institutions = poor compliance                           |
| internet      | cyber_risk    | 0.90        | Causal: internet maturity affects cyber risk exposure                 |
| conflict      | typhoon       | 0.85        | Geographic overlap: conflict zones overlap cyclone-prone regions      |
| humanitarian  | typhoon       | 0.85        | Geographic overlap: cyclone-prone regions need humanitarian aid       |

### YAML Format

Each entry includes:
- `dim1`, `dim2`: dimension names
- `r_threshold`: maximum expected |r| before flagging
- `reason`: human-readable justification
- `approved_date`: date the pair was reviewed and approved

---

## TASK 2-C: Correlation History Tracking

**File:** `scripts/diagnose_correlations.py` (v2.0 -> v2.1)

### Changes

- Added `_append_to_history()` function
- Called at end of `main()` (skippable with `--no-history` flag)
- Output: `data/correlation_history.jsonl`

### JSONL Record Format

```json
{
  "timestamp": "2026-03-21T10:30:00.000000",
  "country_count": 17,
  "pairs": [
    {"dim1": "conflict", "dim2": "humanitarian", "r": 0.8794, "classification": "CAUSAL_ACCEPTABLE"},
    {"dim1": "geo_risk", "dim2": "conflict", "r": 0.8512, "classification": "CAUSAL_ACCEPTABLE"}
  ]
}
```

### Filtering

- Only pairs with |r| > 0.70 are recorded (lower correlations are noise)
- Each pair includes its classification from `classify_correlation()`
- Creates `data/` directory if it does not exist

### New CLI Flag

```
--no-history    Skip appending results to correlation_history.jsonl
```

---

## Verification

All files pass syntax validation:

```
python -m py_compile features/timeseries/scheduler.py     # OK
python -m py_compile scripts/diagnose_correlations.py      # OK
python -c "import yaml; yaml.safe_load(open(...))"         # OK (9 pairs loaded)
```

---

## File Inventory

| File                                        | Action   | Description                                 |
|---------------------------------------------|----------|---------------------------------------------|
| `features/timeseries/scheduler.py`          | Modified | Added weekly correlation audit job + helpers |
| `config/accepted_correlations.yaml`         | Replaced | Full 9-pair CAUSAL_ACCEPTABLE config         |
| `scripts/diagnose_correlations.py`          | Modified | v2.1 with correlation_history.jsonl append   |
| `reports/v07_STREAM2_complete.md`           | Created  | This report                                  |
