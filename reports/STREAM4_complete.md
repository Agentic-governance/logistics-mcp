# STREAM 4-A: Data Quality Flags in Scoring Engine

## Status: COMPLETE

## Date: 2026-03-18

## Summary

Added data quality tracking to `scoring/engine.py` to monitor each dimension's data fetch status across all 24 risk dimensions.

## Changes Made

### 1. `SupplierRiskScore` dataclass - New field
- Added `dimension_status: dict` field (default_factory=dict)
- Tracks per-dimension status: `"ok"`, `"stale"`, `"failed"`, or `"not_applicable"`

### 2. `to_dict()` method - New `data_quality` section
- Added `_data_quality_summary()` helper method
- Output includes:
  - `dimensions_ok`: count of dimensions with "ok" status
  - `dimensions_failed`: count of dimensions with "failed" status
  - `confidence`: ratio of ok dimensions to total (24), rounded to 2 decimal places
  - `low_confidence_warning`: boolean flag when confidence < 0.5
  - `dimension_status`: full dict of per-dimension statuses

### 3. `calculate_risk_score()` - Status tracking for all 24 dimensions
- **Dim 1 (sanctions)**: Wrapped existing try block; tracks "ok"/"failed"
- **Dims 2-20 (location-dependent)**: Each dimension tracks "ok" on success, "failed" on exception, "not_applicable" when `loc` is empty
- **Dims 21-22 (energy, japan_economy)**: No location dependency; tracks "ok"/"failed" only
- **Dims 23-24 (climate_risk, cyber_risk)**: Location-dependent; tracks "ok"/"failed"/"not_applicable"

### 4. What was NOT changed
- Scoring formula and weights remain untouched
- Import structure unchanged
- `calculate_overall()` logic unchanged
- `risk_level()` logic unchanged

## Verification Results

```
Overall: 32
Data quality: {
  'dimensions_ok': 23,
  'dimensions_failed': 1,
  'confidence': 0.96,
  'low_confidence_warning': False,
  'dimension_status': {
    'sanctions': 'ok',
    'geo_risk': 'failed',
    'disaster': 'ok',
    'legal': 'ok',
    'maritime': 'ok',
    'conflict': 'ok',
    'economic': 'ok',
    'currency': 'ok',
    'health': 'ok',
    'humanitarian': 'ok',
    'weather': 'ok',
    'typhoon': 'ok',
    'compliance': 'ok',
    'food_security': 'ok',
    'trade': 'ok',
    'internet': 'ok',
    'political': 'ok',
    'labor': 'ok',
    'port_congestion': 'ok',
    'aviation': 'ok',
    'energy': 'ok',
    'japan_economy': 'ok',
    'climate_risk': 'ok',
    'cyber_risk': 'ok'
  }
}
```

- 23/24 dimensions returned "ok"
- 1/24 dimension returned "failed" (geo_risk / GDELT monitor)
- Confidence: 0.96 (above 0.5 threshold)
- No low confidence warning triggered

## File Modified

- `scoring/engine.py` (507 lines -> 588 lines)
