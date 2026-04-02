# Data Sources Reference -- SCRI Platform v0.9.0

> Complete reference of all external data sources integrated into the SCRI platform.
> Auto-generated from pipeline source code. Run `python scripts/generate_data_source_reference.py` to regenerate.

---

## Summary

| Category | Sources | API Key Required | Real-time |
|---|---|---|---|
| Sanctions & Compliance | 19 | 0 | 11 daily+ |
| Geopolitical & Conflict | 6 | 2 (GDELT, ACLED) | 2 |
| Disaster & Weather | 7 | 0 | 6 |
| Economic & Trade | 12 | 2 (FRED, Comtrade opt.) | 3 daily |
| Maritime & Transport | 6 | 0 | 2 |
| Health & Humanitarian | 6 | 0 | 3 |
| Infrastructure & Cyber | 5 | 0 | 2 |
| Climate & Environment | 4 | 0 | 1 |
| Japan-Specific | 3 | 0 | 2 |
| Regional Statistics | 10 | 0 | 0 |
| Corporate & ERP | 10 | 0-1 (SAP internal) | 3 |
| **Total** | **88 named sources** | **4 required** | **35 real-time/daily** |

> Note: With sub-sources, regional variants, and cached data, the total unique data endpoints exceed 100.

---

## Sanctions & Compliance (19 sources)

### Sanctions Lists (11)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| OFAC SDN | `pipeline/sanctions/ofac.py` | US Treasury sanctions (18,712 entities) | Daily | No | High -- official |
| EU Consolidated List | `pipeline/sanctions/eu.py` | EU sanctions (403 Forbidden fallback) | Daily | No | High -- official |
| UN Security Council | `pipeline/sanctions/un.py` | Global UN sanctions (1,002 entities) | Daily | No | High -- official |
| METI Foreign User List | `pipeline/sanctions/meti.py` | Japan export control (end-users) | Monthly | No | High -- official |
| BIS Entity List | `pipeline/sanctions/bis.py` | US Commerce Dept export control | Monthly | No | High -- official |
| UK OFSI | `pipeline/sanctions/ofsi.py` | UK financial sanctions | Daily | No | High -- official |
| Switzerland SECO | `pipeline/sanctions/seco.py` | Swiss sanctions (background cache) | Weekly | No | High -- official |
| Canada DFATD | `pipeline/sanctions/canada.py` | Canadian consolidated list | Weekly | No | High -- official |
| Australia DFAT | `pipeline/sanctions/dfat.py` | Australian sanctions | Weekly | No | High -- official |
| Japan MOFA | `pipeline/sanctions/mofa.py` | Japan foreign policy sanctions | Monthly | No | High -- official |
| OpenSanctions | `pipeline/opensanctions/client.py` | Aggregated global (250K+ entities) | Daily | No | High -- aggregated |

### Compliance & Governance (8)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| FATF | `pipeline/compliance/fatf_client.py` | AML/CFT mutual evaluation (200+ countries) | Annual | No | High |
| TI CPI | `pipeline/compliance/fatf_client.py` | Corruption Perception Index (180 countries) | Annual | No | High |
| WJP Rule of Law | `pipeline/compliance/fatf_client.py` | Judicial independence (73 countries) | Annual | No | High |
| Basel AML Index | `pipeline/compliance/fatf_client.py` | Money laundering risk (80 countries) | Annual | No | Medium |
| V-Dem | `pipeline/compliance/political_client.py` | Democracy indices (68 countries) | Annual | No | High |
| Freedom House | `pipeline/compliance/political_client.py` | Freedom ratings (195 countries) | Annual | No | High |
| INFORM Risk API | `pipeline/compliance/fatf_client.py` | Risk index (45K+ records, WorkflowId=503) | Annual | No | High |
| DoL ILAB / GSI | `pipeline/compliance/labor_client.py` | Child labor, forced labor, modern slavery | Annual | No | Medium |

---

## Geopolitical & Conflict (6 sources)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| GDELT BigQuery | `pipeline/gdelt/monitor.py` | Global events (billions of records) | Real-time | Yes (GCP) | Medium -- needs filtering |
| ACLED | `pipeline/conflict/acled_client.py` | Armed conflict data (100+ countries) | Weekly | Yes (free) | High |
| SIPRI | `pipeline/conflict/sipri_client.py` | Military expenditure (170+ countries) | Annual | No | High |
| Global Peace Index | `pipeline/conflict/gpi_client.py` | Peace rankings (163 countries) | Annual | No | High |
| GDELT v2 Article Search | `features/screening/supplier_reputation.py` | News sentiment analysis | Daily | No | Medium |
| ILO (ILOSTAT) | `pipeline/regional/ilo_client.py` | Global labor statistics | Quarterly | No | High |

---

## Disaster & Weather (7 sources)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| GDACS | `pipeline/disaster/gdacs_client.py` | Global disaster alerts (Red/Orange/Green) | Real-time | No | High |
| USGS Earthquake | `pipeline/disaster/usgs_client.py` | Global seismic activity (M2.5+) | Real-time | No | High |
| NASA FIRMS | `pipeline/disaster/firms_client.py` | Active fire detection (satellite) | Real-time | No | High |
| JMA | `pipeline/disaster/jma_client.py` | Japan weather/earthquake alerts | Real-time | No | High |
| BMKG | `pipeline/disaster/bmkg_client.py` | Indonesia seismic data | Real-time | No | High |
| Open-Meteo | `pipeline/weather/openmeteo_client.py` | Global weather forecasts (60+ locations) | Hourly | No | High |
| NOAA NHC/SWPC | `pipeline/weather/typhoon_client.py` | Tropical cyclones + space weather | Real-time | No | High |

---

## Economic & Trade (12 sources)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| World Bank | `pipeline/economic/worldbank_client.py` | Macro indicators (200+ countries) | Quarterly | No | High |
| IMF Fiscal Monitor | `pipeline/economic/imf_client.py` | Fiscal data (190+ countries) | Quarterly | No | High |
| Frankfurter/ECB | `pipeline/economic/currency_client.py` | Exchange rates (32 currencies) | Daily | No | High |
| ExchangeRate-API | `pipeline/japan/estat_client.py` | FX rates (fallback for BOJ) | Daily | No | High |
| UN Comtrade | `pipeline/trade/comtrade_client.py` | Bilateral trade (HS-level, 200+ countries) | Monthly | Optional | High |
| FRED | `pipeline/energy/commodity_client.py` | US economic indicators, commodity prices | Daily | Yes (free) | High |
| EIA | `pipeline/energy/commodity_client.py` | Energy market data | Daily | No | High |
| IEA/OWID | `pipeline/energy/commodity_client.py` | Energy import dependency (46 countries) | Annual | No | Medium |
| ImportYeti | `pipeline/trade/importyeti_client.py` | US customs Bill of Lading data | On-demand | No | High -- official |
| BACI (CEPII) | `pipeline/trade/baci_client.py` | Bilateral trade flows (HS4, 200+ countries) | Annual | No | High |
| EU Customs | `pipeline/trade/eu_customs_client.py` | EU trade statistics | Monthly | No | High |
| Japan Customs | `pipeline/trade/japan_customs_client.py` | Japan trade statistics | Monthly | No | High |

---

## Maritime & Transport (6 sources)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| IMF PortWatch | `pipeline/maritime/portwatch_client.py` | Port disruptions, trade impact | Daily | No | High |
| AISHub | `pipeline/maritime/ais_client.py` | Ship tracking, lane congestion | Real-time | No | Medium |
| UNCTAD Port Stats | `pipeline/infrastructure/port_congestion_client.py` | Port congestion metrics | Monthly | No | Medium |
| Lloyd's List | `pipeline/maritime/lloyds_client.py` | Shipping intelligence | Daily | No | High |
| OpenSky Network | `pipeline/aviation/opensky_client.py` | Air traffic (54 airports, 51 countries) | Hourly | No | Medium |
| IATA | `pipeline/transport/iata_client.py` | Air cargo statistics | Monthly | No | High |

---

## Health & Humanitarian (6 sources)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| Disease.sh | `pipeline/health/disease_client.py` | Pandemic tracking (COVID, etc.) | Real-time | No | Medium |
| OCHA FTS | `pipeline/health/ocha_client.py` | Humanitarian funding gaps | Daily | No | High |
| ReliefWeb | `pipeline/health/reliefweb_client.py` | Crisis reports and updates | Daily | No | Medium |
| WHO GHO | `pipeline/health/who_client.py` | Global health indicators | Monthly | No | High |
| FEWS NET | `pipeline/food/fewsnet_client.py` | Famine early warning (IPC, 38 countries) | Monthly | No | High |
| WFP HungerMap | `pipeline/food/wfp_client.py` | Food security (v1 API) | Daily | No | Medium |

---

## Infrastructure & Cyber (5 sources)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| Cloudflare Radar | `pipeline/infrastructure/internet_client.py` | Internet traffic anomalies | Real-time | No | High |
| IODA | `pipeline/infrastructure/internet_client.py` | Internet outage detection | Real-time | No | High |
| OONI | `pipeline/cyber/ooni_client.py` | Censorship measurement probes | Weekly | No | Medium |
| CISA KEV | `pipeline/cyber/cisa_client.py` | Known Exploited Vulnerabilities | Weekly | No | High |
| ITU ICT | `pipeline/cyber/itu_client.py` | ICT Development Index | Annual | No | High |

---

## Climate & Environment (4 sources)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| ND-GAIN | `pipeline/climate/ndgain_client.py` | Climate vulnerability (181 countries) | Annual | No | High |
| GloFAS | `pipeline/climate/glofas_client.py` | Flood awareness system | Real-time | No | Medium |
| WRI Aqueduct | `pipeline/climate/wri_client.py` | Water risk atlas | Monthly | No | High |
| Climate TRACE | `pipeline/climate/climatetrace_client.py` | GHG emissions tracking | Annual | No | Medium |

---

## Japan-Specific (3 sources)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| BOJ | `pipeline/japan/estat_client.py` | Central bank statistics | Daily | No | High |
| ExchangeRate-API | `pipeline/japan/estat_client.py` | JPY exchange rates (fallback) | Daily | No | High |
| e-Stat | `pipeline/japan/estat_client.py` | Government statistics portal | Monthly | No | High |

---

## Regional Statistics (10 sources)

| Source | Pipeline Module | Region | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| KOSIS | `pipeline/regional/kosis_client.py` | South Korea | Monthly | No | High |
| Taiwan DGBAS | `pipeline/regional/taiwan_client.py` | Taiwan | Monthly | No | High |
| China NBS | `pipeline/regional/china_client.py` | China | Quarterly | No | Medium |
| Vietnam GSO | `pipeline/regional/vietnam_client.py` | Vietnam | Quarterly | No | Medium |
| DOSM Malaysia | `pipeline/regional/malaysia_client.py` | Malaysia | Quarterly | No | High |
| MPA Singapore | `pipeline/regional/singapore_client.py` | Singapore | Monthly | No | High |
| ASEAN Stats | `pipeline/regional/asean_client.py` | ASEAN region | Annual | No | Medium |
| Eurostat | `pipeline/regional/eurostat_client.py` | Europe | Quarterly | No | High |
| ILO (ILOSTAT) | `pipeline/regional/ilo_client.py` | Global | Quarterly | No | High |
| AfDB | `pipeline/regional/afdb_client.py` | Africa | Annual | No | Medium |

---

## Corporate & ERP (10 sources)

| Source | Pipeline Module | Coverage | Update Freq | API Key | Accuracy |
|---|---|---|---|---|---|
| EDINET | `pipeline/corporate/ir_scraper.py` | Japan filings (有価証券報告書) | Daily | No | High |
| SEC EDGAR | `pipeline/corporate/ir_scraper.py` | US filings (10-K, SD) | Daily | No | High |
| SAP ERP | `pipeline/erp/sap_connector.py` | Purchase orders (EKKO/EKPO/MARA/MARC) | On-demand | Internal | High |
| Houjin Bangou | `pipeline/corporate/houjin.py` | Japan company registry | Daily | No | High |
| ICIJ Offshore Leaks | `pipeline/corporate/icij_client.py` | Panama Papers, Paradise Papers, etc. | Periodic | No | High |
| OpenOwnership | `pipeline/corporate/openownership_client.py` | Beneficial ownership (UBO) | Daily | No | Medium |
| Wikidata | `pipeline/corporate/wikidata_client.py` | Entity/person/executive data | Real-time | No | Medium |
| SEC Conflict Minerals | `pipeline/corporate/ir_scraper.py` | 3TG (SD/Exhibit 1.01) | Annual | No | High |
| OpenSanctions | `pipeline/opensanctions/client.py` | Entity relationship graph | Daily | No | High |
| BACI (CEPII) | `pipeline/trade/baci_client.py` | HS-level bilateral trade | Annual | No | High |

---

## Known API Issues (as of 2026-03-27)

| Source | Issue | Workaround |
|---|---|---|
| EU Consolidated List | 403 Forbidden | Authentication token + fallback URL |
| BOJ API | 404 as of 2026-03-15 | Use open.er-api.com for exchange rates |
| CSL (trade.gov) | All endpoints returning HTML | Fallback to static CSV with local fuzzy search |
| Caselaw MCP | DNS failing | Cached failure to avoid timeout |
| Frankfurter/ECB | No UAH/RUB rates | Skip for Ukraine/Russia |
| Disease.sh | City names return 404 | Must use country names |
| INFORM Risk API | WorkflowId=503 works, 504 empty | Use WorkflowId=503 |
| WFP HungerMap | v2 returns 404 | Use v1 endpoint |
| UN Comtrade | Old API deprecated | Use `comtradeapi.un.org/public/v1/preview/` |
| BIS Entity List | URL changed | Updated to trade.gov CSV |
| METI Foreign User List | 404 with old URL | Dynamic URL extraction + TLS 1.2 adapter |
