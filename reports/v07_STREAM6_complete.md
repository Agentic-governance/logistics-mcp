# STREAM 6: Data Quality and Coverage Improvements

**Date:** 2026-03-21
**Status:** COMPLETE
**Platform Version:** v0.7.0

---

## Summary

STREAM 6 adds three new governance/compliance data sources and a comprehensive coverage report generator. These improvements increase the SCRI Platform's data coverage to **97.1%** across 50 priority countries and 27 data dimensions (24 core + 3 supplementary).

| Task | Description | Status |
|------|-------------|--------|
| 6-A | WJP Rule of Law Index client | COMPLETE |
| 6-B | Basel AML Index client | COMPLETE |
| 6-C | V-Dem Democracy Index client | COMPLETE |
| 6-D | Coverage report generator | COMPLETE |

---

## Task 6-A: WJP Rule of Law Index Client

**File:** `pipeline/compliance/wjp_client.py`

### Implementation
- Static data for **73 countries** from WJP Rule of Law Index 2023
- Score inversion: WJP 1.0 (strongest rule of law) maps to risk 0, WJP 0.0 maps to risk 100
- Function `get_rule_of_law_score(location: str) -> dict` returns `{"score": int 0-100, "evidence": [...]}`
- Alias resolution for common abbreviations (USA, UK, DPRK, etc.)

### Integration with scoring/legal.py
- New `_get_blended_baseline()` function blends existing `LEGAL_RISK_BASELINE` (60% weight) with WJP scores (40% weight)
- When both sources are available, produces a cross-validated composite score
- When only one source is available, uses that source alone
- This enriches the legal dimension with an internationally recognized governance index

### Sample Scores
| Country | WJP Raw | Risk Score | Label |
|---------|---------|------------|-------|
| Denmark | 0.90 | 9/100 | Strong Rule of Law |
| Japan | 0.77 | 23/100 | Strong Rule of Law |
| Singapore | 0.78 | 21/100 | Strong Rule of Law |
| United States | 0.71 | 29/100 | Moderate Rule of Law |
| China | 0.40 | 60/100 | Weak Rule of Law |
| Myanmar | 0.27 | 73/100 | Very Weak Rule of Law |
| North Korea | 0.12 | 88/100 | Very Weak Rule of Law |

### Blended Legal Scores (baseline + WJP)
| Country | Baseline | WJP | Blended (60/40) |
|---------|----------|-----|-----------------|
| Japan | 10 | 23 | 15 |
| China | 55 | 60 | 57 |
| Singapore | 5 | 21 | 11 |
| Myanmar | 72 | 73 | 72 |
| North Korea | 85 | 88 | 86 |

---

## Task 6-B: Basel AML Index Client

**File:** `pipeline/compliance/basel_aml_client.py`

### Implementation
- Live API attempt: `https://index.baselgovernance.org/api/v1/results` (no key required)
- Static fallback with **80 countries** on 0-10 scale (higher = riskier)
- Automatic conversion from 0-10 to 0-100 scale
- Function `get_aml_score(location: str) -> dict` returns `{"score": int 0-100, "evidence": [...]}`
- Risk tier classification: Very High (7+), High (6-7), Medium-High (5-6), Medium (4-5), Medium-Low (3-4), Low (<3)

### Sample Scores
| Country | Basel Raw | Risk Score | Tier |
|---------|-----------|------------|------|
| Myanmar | 8.07 | 80/100 | Very High Risk |
| Nigeria | 7.30 | 73/100 | Very High Risk |
| Vietnam | 6.78 | 67/100 | High Risk |
| China | 5.48 | 54/100 | Medium-High Risk |
| Japan | 4.22 | 42/100 | Medium Risk |
| United States | 3.95 | 39/100 | Medium-Low Risk |
| Denmark | 2.68 | 26/100 | Low Risk |
| Finland | 2.55 | 25/100 | Low Risk |

---

## Task 6-C: V-Dem Democracy Index Client

**File:** `pipeline/compliance/vdem_client.py`

### Implementation
- Static data for **68 countries** from V-Dem Dataset v14 (Electoral Democracy Index, v2x_polyarchy)
- Score inversion: 1.0 (fully democratic) maps to risk 0, 0.0 maps to risk 100
- Function `get_democracy_score(location: str) -> dict` returns `{"score": int 0-100, "evidence": [...]}`
- Regime type classification: Full Democracy (0.80+), Democracy (0.60-0.79), Electoral Autocracy (0.30-0.59), Closed Autocracy (<0.30)

### Sample Scores
| Country | V-Dem Raw | Risk Score | Regime Type |
|---------|-----------|------------|-------------|
| Denmark | 0.92 | 7/100 | Full Democracy |
| Japan | 0.82 | 18/100 | Full Democracy |
| United States | 0.79 | 20/100 | Democracy |
| India | 0.57 | 43/100 | Electoral Autocracy |
| Russia | 0.25 | 75/100 | Closed Autocracy |
| China | 0.15 | 85/100 | Closed Autocracy |
| North Korea | 0.04 | 96/100 | Closed Autocracy |

---

## Task 6-D: Coverage Report Generator

**File:** `scripts/generate_coverage_report.py`
**Output:** `docs/DATA_COVERAGE.md`

### Implementation
- Checks all 27 dimensions (24 core + 3 supplementary) x 50 priority countries
- For each combination, determines data availability:
  - Live API data available
  - Static fallback data available
  - No data coverage
  - Not applicable (e.g., Japan Economy for non-Japan countries)
- Outputs formatted Markdown table with summary statistics, dimension coverage, country coverage, and full matrix

### Coverage Summary
| Metric | Value |
|--------|-------|
| Total data points | 1,350 |
| Live API data | 865 (64.1%) |
| Static fallback | 363 (26.9%) |
| No data | 37 (2.7%) |
| Not applicable | 85 (6.3%) |
| **Overall coverage** | **1,228/1,265 (97.1%)** |

### Dimensions at 100% Coverage (22/27)
Sanctions, Geo Risk, Disaster, Legal, Maritime, Conflict, Economic, Currency, Health, Humanitarian, Weather, Typhoon, Food Security, Trade, Internet, Port Congestion, Aviation, Energy, Japan Econ, Climate, Cyber, WJP RoL, Basel AML, V-Dem

### Dimensions Below 100%
| Dimension | Coverage | Reason |
|-----------|----------|--------|
| Compliance (FATF/TI CPI) | 76% | Some low-risk countries not in FATF/TI lists |
| Political (Freedom House) | 88% | 6 countries missing (Netherlands, Switzerland, etc.) |
| Labor (DoL ILAB/GSI) | 62% | 19 countries not in forced labor watchlists (low-risk countries) |

---

## Files Changed

### New Files
| File | Lines | Description |
|------|-------|-------------|
| `pipeline/compliance/wjp_client.py` | ~130 | WJP Rule of Law Index 2023 (73 countries) |
| `pipeline/compliance/basel_aml_client.py` | ~170 | Basel AML Index 2023 (80 countries, API + static) |
| `pipeline/compliance/vdem_client.py` | ~130 | V-Dem Electoral Democracy Index (68 countries) |
| `scripts/generate_coverage_report.py` | ~340 | Coverage matrix generator |
| `docs/DATA_COVERAGE.md` | ~150 | Generated coverage report |
| `reports/v07_STREAM6_complete.md` | this file | Completion report |

### Modified Files
| File | Changes |
|------|---------|
| `scoring/legal.py` | Added `_get_blended_baseline()` to blend LEGAL_RISK_BASELINE with WJP scores (60/40 weighting) |

---

## Verification

All files pass Python syntax verification:
```
wjp_client.py:             OK
basel_aml_client.py:       OK
vdem_client.py:            OK
scoring/legal.py:          OK
generate_coverage_report.py: OK
```

Functional tests confirm:
- WJP: 73 countries, correct score inversion, alias resolution
- Basel AML: 80 countries, correct 0-10 to 0-100 conversion, API fallback
- V-Dem: 68 countries, correct score inversion, regime classification
- Legal blending: 60/40 weighted composite produces expected scores
- Coverage report: 1,350 data points analyzed, 97.1% coverage, Markdown output

---

## Architecture Notes

1. **Alias Resolution Order:** All three new clients check common aliases (USA, UK, DPRK, etc.) before partial string matching to prevent false matches (e.g., "UK" matching "Ukraine").

2. **Score Inversion Pattern:** WJP and V-Dem both use "higher = better" scales that are inverted for risk scoring. The formula `risk = int((1.0 - raw) * 100)` provides consistent 0-100 risk scores.

3. **Blending Strategy:** The legal dimension blends two independent sources (LEGAL_RISK_BASELINE at 60% + WJP at 40%) to improve accuracy through cross-validation. When sources disagree, the blend smooths outliers.

4. **Basel API Resilience:** The Basel client tries the live API first, falling back to static data. This pattern matches existing clients (e.g., sanctions_csl_client.py).

5. **Coverage Report as CI Artifact:** The coverage report can be regenerated at any time via `python scripts/generate_coverage_report.py` and committed to track coverage over time.
