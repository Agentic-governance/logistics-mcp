# Performance Benchmarks -- SCRI Platform v0.9.0

> Benchmark results for core SCRI operations.
> Run `python scripts/benchmark_performance.py [--live]` to reproduce.

---

## Benchmark Environment

| Item | Value |
|---|---|
| Platform | macOS (Darwin) |
| Python | 3.11 |
| Mode | Mock (deterministic, no network) and Live (real API calls) |
| Measurement | `time.perf_counter()` (wall-clock), `tracemalloc` (peak memory) |

---

## Core Operation Benchmarks

### 1. Single Country Risk Score (`get_risk_score`)

Compute a full 24-dimension risk score for one country.

| Mode | Elapsed | Peak Memory | Notes |
|---|---|---|---|
| Mock | ~0.01s | ~2 MB | Deterministic scoring, no API calls |
| Live | 5-15s | ~15 MB | All 24 dimensions, 30+ API calls in parallel |

**Breakdown (live mode):**
- Sanctions screening: ~1s (10 list lookups, cached after first)
- GDELT geopolitical: ~2s (BigQuery, requires API key)
- Disaster (GDACS/USGS/FIRMS): ~1.5s (3 parallel calls)
- Economic (World Bank): ~1s
- Weather (Open-Meteo): ~0.5s
- Remaining dimensions: ~2-5s (parallel)

**Optimization notes:**
- Results cached for 1 hour (TTL) -- subsequent calls return in <10ms
- Sanctions DB pre-loaded on startup (~18K entities in SQLite)

---

### 2. Bulk Risk Scores (10 Countries)

Score 10 PRIORITY_COUNTRIES sequentially.

| Mode | Elapsed | Peak Memory | Notes |
|---|---|---|---|
| Mock | ~0.1s | ~5 MB | 10 sequential mock scores |
| Live | 50-150s | ~50 MB | 10 x 24 dimensions, rate-limited |

**Expected countries:** Japan, China, South Korea, Taiwan, Vietnam, Thailand, Indonesia, Malaysia, Singapore, India

---

### 3. Sanctions Screening

Screen a single entity against 10 consolidated lists.

| Mode | Elapsed | Peak Memory | Notes |
|---|---|---|---|
| Cached (SQLite) | ~0.05s | ~3 MB | Fuzzy match against pre-loaded DB |
| Cold start | ~0.5s | ~10 MB | First query loads DB into memory |

**Throughput:** ~20 entities/second (sequential), limited by fuzzy matching.

---

### 4. BOM Risk Analysis

Analyze a Bill of Materials with cost-weighted risk scoring.

| BOM Size | Elapsed (mock) | Elapsed (live) | Peak Memory |
|---|---|---|---|
| 10 parts (EV Powertrain) | ~0.5s | ~30s | ~20 MB |
| 24 parts (Smartphone) | ~1s | ~60s | ~30 MB |
| 18 parts (Wind Turbine) | ~0.8s | ~45s | ~25 MB |

**With Tier-2/3 inference:** Add ~5s per unique country (UN Comtrade lookup).

---

### 5. Monte Carlo Simulation (n=1000)

1000 simulations with random dimension perturbation.

| n | Elapsed | Peak Memory | Notes |
|---|---|---|---|
| 100 | ~2.7s | ~8 MB | Quick estimate |
| 1000 | ~27s | ~15 MB | Standard (vectorized with numpy) |
| 5000 | ~135s | ~40 MB | High precision |

**Optimization:** v0.5.1 introduced numpy matrix operations, reducing from ~4.5min to ~27s for n=1000.

---

### 6. Portfolio Analysis (5 Entities)

Multi-supplier portfolio analysis with optional clustering.

| Operation | Elapsed (mock) | Peak Memory |
|---|---|---|
| Portfolio analysis (5 entities) | ~0.3s | ~10 MB |
| + KMeans clustering | ~0.5s | ~12 MB |
| + Ranking | ~0.1s | ~5 MB |

---

### 7. 50-Country Baseline Scoring

Score all 50 PRIORITY_COUNTRIES (scheduler job, runs every 6 hours).

| Mode | Elapsed | Notes |
|---|---|---|
| Live | 20-40 min | Rate-limited, with backoff |
| Cached | 5-10 min | Most data cached from previous run |

---

## API Response Times

### Endpoint Latency (typical, cached data)

| Endpoint | P50 | P95 | P99 |
|---|---|---|---|
| `GET /health` | 5ms | 15ms | 50ms |
| `POST /api/v1/screen` | 50ms | 200ms | 500ms |
| `GET /api/v1/risk/{id}` | 100ms (cached) | 5s (cold) | 15s (cold) |
| `GET /api/v1/dashboard/global` | 50ms (cached) | 3s (cold) | 8s |
| `GET /api/v1/disasters/global` | 200ms | 1s | 3s |
| `POST /api/v1/analytics/portfolio` | 500ms | 2s | 5s |
| `POST /api/v1/analytics/sensitivity/montecarlo` | 27s | 35s | 60s |
| `POST /api/v1/bom/analyze` | 1s (mock) | 60s (live) | 120s |
| `POST /api/v1/cost-impact/estimate` | 100ms | 500ms | 1s |

---

## Rate Limiting Configuration

| Tier | Limit | Endpoints |
|---|---|---|
| General | 60/minute | Most GET endpoints |
| Heavy computation | 10/minute | Analytics, BOM, Monte Carlo, route-risk |
| Screening | 30/minute | Sanctions screening, reputation |

---

## Memory Profile

### Startup Memory

| Component | Memory |
|---|---|
| Python interpreter | ~30 MB |
| FastAPI + middleware | ~15 MB |
| SQLAlchemy + SQLite | ~10 MB |
| Sanctions DB (18K entities) | ~25 MB |
| Scoring engine (lazy imports) | ~5 MB |
| **Total startup** | **~85 MB** |

### Runtime Memory (steady state)

| Cache | Size | TTL |
|---|---|---|
| Risk score cache (200 entries) | ~20 MB | 1 hour |
| Sanctions screening cache (500 entries) | ~10 MB | 24 hours |
| Dashboard cache (1 entry) | ~1 MB | 30 minutes |
| Location risk cache (200 entries) | ~20 MB | 1 hour |

---

## Scaling Considerations

### Current Architecture Limits

| Dimension | Limit | Bottleneck |
|---|---|---|
| Concurrent users | ~50 | In-memory rate limiter, SQLite writes |
| Countries scored/hour | ~50 | External API rate limits |
| Sanctions entities | 20K+ | SQLite query speed |
| TimeSeries data points | 100K+ | SQLite file size |
| BOM parts per analysis | ~100 | Sequential scoring |

### Improvement Opportunities

1. **Async scoring**: Convert sequential dimension scoring to asyncio for ~3x speedup
2. **Redis caching**: Replace in-memory TTLCache for multi-worker deployments
3. **PostgreSQL**: Replace SQLite for concurrent write support
4. **Worker pool**: Celery/RQ for background BOM analysis and bulk scoring
5. **CDN/Edge**: Cache static dashboard assets

---

## Reproducing Benchmarks

```bash
# Mock benchmarks (fast, no network required)
python scripts/benchmark_performance.py

# Live benchmarks (slow, requires network and API keys)
python scripts/benchmark_performance.py --live

# Results are written to reports/v07_STREAM7_benchmark.md
```
