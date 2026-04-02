# STREAM 3: Data Source Clients - Complete

**Date:** 2026-03-18
**Status:** All 6 clients created and verified

---

## Summary

STREAM 3 adds 6 new data source clients to the SCRI Platform pipeline, covering health, economic, conflict, transport, and maritime risk indicators. Each client follows the established pattern: HTTP requests to public APIs (where available) with static fallback data, returning standardized `{"score": int, "evidence": [str]}` dicts.

---

## Clients Created

### 3-A: WHO Global Health Observatory
- **File:** `pipeline/health/who_gho_client.py`
- **API:** `https://ghoapi.azureedge.net/api/` (free, no key)
- **Indicators:** Life expectancy (WHOSIS_000001), Under-5 mortality (MDG_0000000026), Health infrastructure (WHS9_96)
- **Function:** `get_health_indicators(country_iso3: str) -> dict`
- **Fallback:** Static data for 40+ countries
- **Scoring:** Composite of 3 indicators (35% life expectancy, 35% mortality, 30% health infra)
- **Test result (JPN):** Score=3 (very low health risk)

### 3-B: IMF Fiscal Monitor / DataMapper
- **File:** `pipeline/economic/imf_fiscal_client.py`
- **API:** `https://www.imf.org/external/datamapper/api/v1/` (free, may return 403)
- **Indicators:** GGXWDG_NGDP (debt/GDP), GGXCNL_NGDP (deficit/GDP), BCA_NGDPD (current account/GDP)
- **Function:** `get_fiscal_indicators(country_iso3: str) -> dict`
- **Fallback:** Static data for 40 countries (IMF WEO April 2024)
- **Scoring:** 40% debt, 35% deficit, 25% current account
- **Test result (JPN):** Score=53 (elevated due to 252% debt/GDP)

### 3-C: SIPRI Military Expenditure
- **File:** `pipeline/conflict/sipri_client.py`
- **Data:** Static dataset (SIPRI provides Excel files, no public API)
- **Coverage:** 50 countries with GDP share and 3-year trend
- **Function:** `get_military_expenditure(country: str) -> dict`
- **Scoring:** >4% GDP = high risk; "increasing" trend applies 1.25x multiplier
- **Test result (Japan):** Score=6 (1.2% GDP, increasing trend)

### 3-D: Global Peace Index
- **File:** `pipeline/conflict/gpi_client.py`
- **Data:** Static dataset (GPI 2024, Institute for Economics & Peace)
- **Coverage:** 155 countries with scores from 1.0 (most peaceful) to 4.0 (least)
- **Function:** `get_peace_index(country: str) -> dict`
- **Scoring:** Linear mapping GPI 1.0-4.0 to risk 0-100
- **Categories:** Very High Peace (<1.5), High Peace (1.5-2.0), Medium Peace (2.0-2.5), Low Peace (2.5-3.0), Very Low Peace (>3.0)
- **Test result (Japan):** Score=13, Rank 13/155, "Very High Peace"

### 3-E: IATA Air Cargo
- **File:** `pipeline/transport/iata_client.py`
- **Data:** Static dataset (ACI World Airport Traffic Rankings 2023)
- **Coverage:** Top 50 cargo airports, 10 regional indices
- **Functions:**
  - `get_cargo_volume_trend(region: str) -> dict` - regional cargo volume assessment
  - `get_aviation_connectivity(country: str) -> dict` - country connectivity score
- **Scoring:** Lower cargo volume = higher risk; trend modifiers
- **Test result (east_asia):** Score=5 (index 145, 12 major hubs)

### 3-F: Lloyd's List Port Rankings
- **File:** `pipeline/maritime/lloyds_client.py`
- **Data:** Static dataset (Lloyd's List Top 100 Container Ports 2024)
- **Coverage:** 100 ports with TEU throughput in millions
- **Functions:**
  - `get_port_rankings() -> list[dict]` - full top 100 rankings
  - `get_port_importance_score(country: str) -> dict` - port importance + congestion risk
- **Scoring:** Congestion-prone ports + concentration risk + volume dependency
- **Test result:** 100 ports loaded successfully

---

## New Directory Structure

```
pipeline/
  transport/           <- NEW directory
    __init__.py
    iata_client.py     <- 3-E
  health/
    who_gho_client.py  <- 3-A
  economic/
    imf_fiscal_client.py <- 3-B
  conflict/
    sipri_client.py    <- 3-C
    gpi_client.py      <- 3-D
  maritime/
    lloyds_client.py   <- 3-F
```

---

## Verification

All 6 clients verified with test country Japan:

```
WHO GHO:    score=3   (life_exp=84.5, mortality=3.1, infra=92.0)
IMF Fiscal: score=53  (debt=252.4%, deficit=-5.6%, CA=+3.5%)
SIPRI:      score=6   (gdp_share=1.2%, trend=increasing)
GPI:        score=13  (gpi=1.405, rank=13, Very High Peace)
IATA:       score=5   (east_asia index=145, 12 hubs)
Lloyd's:    100 ports loaded
```

**ALL 6 CLIENTS OK**
