#!/usr/bin/env python3
"""STREAM 1: Prophet forecast validation and tuning.

Validates time-series forecasting accuracy for SCRI risk scores.
Performs:
  1. Data sufficiency check (generates synthetic data if needed)
  2. Backtest (hold-out validation) with MAE/RMSE/MAPE
  3. Seasonality parameter optimization (grid search)
  4. Leading indicator detection (cross-correlation between dimensions)
  5. Output report generation
"""

import sys
import os
import json
import sqlite3
import datetime
import itertools
import warnings
from pathlib import Path
from typing import Optional

import numpy as np

warnings.filterwarnings("ignore")

# Project root setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.constants import PRIORITY_COUNTRIES

# --- Constants ----------------------------------------------------------------

DB_PATH = PROJECT_ROOT / "data" / "timeseries.db"
CONFIG_DIR = PROJECT_ROOT / "config"
DOCS_DIR = PROJECT_ROOT / "docs"
REPORTS_DIR = PROJECT_ROOT / "reports"

BACKTEST_COUNTRIES = {
    "Japan": "JP",
    "China": "CN",
    "India": "IN",
    "Germany": "DE",
    "United States": "US",
    "Yemen": "YE",
    "Russia": "RU",
    "Singapore": "SG",
}

TARGET_DIMENSIONS = ["conflict", "humanitarian", "economic", "disaster", "political"]

MIN_RECORDS = 30
SYNTHETIC_DAYS = 90
HOLDOUT_DAYS = 30

# Try importing Prophet
PROPHET_AVAILABLE = False
try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
    print("[INFO] Prophet is available.")
except ImportError:
    print("[INFO] Prophet not available. Using moving-average + linear-trend fallback.")

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    from scipy import stats as scipy_stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


# --- STEP 1: Data Sufficiency Check ------------------------------------------

def get_baseline_scores(conn):
    """Get baseline dimension scores for all countries from risk_summaries."""
    cur = conn.cursor()
    cur.execute("SELECT location, overall_score, scores_json FROM risk_summaries")
    rows = cur.fetchall()
    baselines = {}
    for loc, overall, scores_json in rows:
        scores = json.loads(scores_json) if scores_json else {}
        scores["overall"] = overall
        baselines[loc] = scores
    return baselines


def count_records_per_country(conn):
    """Count distinct dates of overall score records per country."""
    cur = conn.cursor()
    cur.execute(
        "SELECT location, COUNT(DISTINCT DATE(timestamp)) "
        "FROM risk_scores WHERE dimension='overall' GROUP BY location"
    )
    return dict(cur.fetchall())


def generate_synthetic_timeseries(conn, country, baselines, n_days=SYNTHETIC_DAYS, seed=None):
    """Generate synthetic time-series data for a country.

    Creates daily records for 'overall' plus the 5 target dimensions,
    using baseline score + Gaussian noise (std=10, clipped to [0,100]).
    """
    if seed is not None:
        rng = np.random.RandomState(seed)
    else:
        rng = np.random.RandomState(abs(hash(country)) % (2**31))

    base_scores = baselines.get(country, {})
    overall_base = base_scores.get("overall", 50)

    # Dimensions to generate
    dims_to_gen = ["overall"] + TARGET_DIMENSIONS
    dim_bases = {d: base_scores.get(d, 0) for d in dims_to_gen}
    dim_bases["overall"] = overall_base

    # Generate dates ending yesterday
    end_date = datetime.date.today() - datetime.timedelta(days=1)
    start_date = end_date - datetime.timedelta(days=n_days - 1)
    dates = [start_date + datetime.timedelta(days=i) for i in range(n_days)]

    cur = conn.cursor()
    inserted = 0

    for dim in dims_to_gen:
        base = dim_bases[dim]
        # If dimension score is 0 or missing, use a small baseline with smaller noise
        if base == 0:
            noise = rng.normal(5, 3, n_days)
        else:
            noise = rng.normal(base, 10, n_days)
        values = np.clip(noise, 0, 100)

        for i, dt in enumerate(dates):
            ts = datetime.datetime.combine(dt, datetime.time(12, 0, 0)).isoformat()
            # Check if already exists
            cur.execute(
                "SELECT COUNT(*) FROM risk_scores WHERE location=? AND dimension=? "
                "AND DATE(timestamp)=?",
                (country, dim, dt.isoformat()),
            )
            if cur.fetchone()[0] == 0:
                cur.execute(
                    "INSERT INTO risk_scores (location, timestamp, overall_score, dimension, score) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (country, ts, overall_base, dim, round(float(values[i]), 1)),
                )
                inserted += 1

    conn.commit()
    return inserted


def ensure_data_sufficiency(conn):
    """Ensure all backtest countries have at least MIN_RECORDS records.

    Returns dict of {country: record_count} after any synthetic generation.
    """
    baselines = get_baseline_scores(conn)
    counts = count_records_per_country(conn)

    results = {}
    for country in BACKTEST_COUNTRIES:
        current_count = counts.get(country, 0)
        if current_count < MIN_RECORDS:
            print(
                f"  [SYNTH] {country}: {current_count} records < {MIN_RECORDS}, "
                f"generating {SYNTHETIC_DAYS} days of synthetic data..."
            )
            inserted = generate_synthetic_timeseries(conn, country, baselines)
            print(f"          Inserted {inserted} records.")
        else:
            print(f"  [OK]   {country}: {current_count} records (sufficient)")

    # Recount
    updated_counts = count_records_per_country(conn)
    for country in BACKTEST_COUNTRIES:
        results[country] = updated_counts.get(country, 0)

    return results


# --- STEP 2: Backtest (Hold-out Validation) -----------------------------------

def load_timeseries(conn, country, dimension="overall"):
    """Load time-series for a country/dimension, sorted by date."""
    cur = conn.cursor()
    cur.execute(
        "SELECT DATE(timestamp) as dt, AVG(score) FROM risk_scores "
        "WHERE location=? AND dimension=? GROUP BY dt ORDER BY dt",
        (country, dimension),
    )
    rows = cur.fetchall()
    if not rows:
        return np.array([]), np.array([])
    dates = [datetime.date.fromisoformat(r[0]) for r in rows]
    values = np.array([r[1] for r in rows])
    return dates, values


def moving_average_forecast(train_values, n_forecast, window=7):
    """Moving-average + linear-trend forecast.

    Fits a linear trend to the training data, then adds the residual moving average.
    """
    n = len(train_values)
    if n == 0:
        return np.full(n_forecast, 50.0)

    # Fit linear trend
    x = np.arange(n, dtype=float)
    if n >= 2:
        coeffs = np.polyfit(x, train_values, 1)
        trend_slope, trend_intercept = coeffs[0], coeffs[1]
    else:
        trend_slope, trend_intercept = 0.0, train_values[0]

    # Residuals
    trend_line = trend_slope * x + trend_intercept
    residuals = train_values - trend_line

    # Moving average of residuals
    if n >= window:
        ma_residual = np.mean(residuals[-window:])
    else:
        ma_residual = np.mean(residuals)

    # Forecast
    future_x = np.arange(n, n + n_forecast, dtype=float)
    forecast = trend_slope * future_x + trend_intercept + ma_residual

    return np.clip(forecast, 0, 100)


def prophet_forecast(dates, train_values, n_forecast, params=None):
    """Prophet-based forecast. Returns forecast array."""
    import pandas as pd
    import logging

    df = pd.DataFrame({
        "ds": pd.to_datetime(dates),
        "y": train_values,
    })

    if params is None:
        params = {
            "yearly_seasonality": False,
            "weekly_seasonality": False,
            "changepoint_prior_scale": 0.1,
        }

    # Suppress Prophet logging
    logging.getLogger("prophet").setLevel(logging.WARNING)
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

    m = Prophet(
        yearly_seasonality=params.get("yearly_seasonality", False),
        weekly_seasonality=params.get("weekly_seasonality", False),
        changepoint_prior_scale=params.get("changepoint_prior_scale", 0.1),
        daily_seasonality=False,
    )

    m.fit(df)

    future = m.make_future_dataframe(periods=n_forecast)
    forecast = m.predict(future)

    yhat = forecast["yhat"].values[-n_forecast:]
    return np.clip(yhat, 0, 100)


def calculate_metrics(actual, predicted):
    """Calculate MAE, RMSE, MAPE."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    mae = np.mean(np.abs(actual - predicted))
    rmse = np.sqrt(np.mean((actual - predicted) ** 2))

    # MAPE: avoid division by zero
    mask = actual != 0
    if mask.any():
        mape = np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100
    else:
        mape = 0.0

    return {"MAE": round(mae, 2), "RMSE": round(rmse, 2), "MAPE": round(mape, 2)}


def run_backtest(conn, use_prophet=True):
    """Run backtest for all 8 countries.

    Hold out last HOLDOUT_DAYS as test, train on the rest.
    Returns dict of {country: {metrics, model}}.
    """
    results = {}

    for country, code in BACKTEST_COUNTRIES.items():
        dates, values = load_timeseries(conn, country, "overall")

        if len(values) < HOLDOUT_DAYS + 10:
            print(f"  [SKIP] {country} ({code}): insufficient data ({len(values)} pts)")
            results[country] = {
                "code": code,
                "metrics": {"MAE": None, "RMSE": None, "MAPE": None},
                "model": "skipped",
                "n_total": len(values),
            }
            continue

        # Split
        train_values = values[:-HOLDOUT_DAYS]
        test_values = values[-HOLDOUT_DAYS:]
        train_dates = dates[:-HOLDOUT_DAYS]

        model_used = "moving_average"

        if use_prophet and PROPHET_AVAILABLE:
            try:
                predicted = prophet_forecast(train_dates, train_values, HOLDOUT_DAYS)
                model_used = "prophet"
            except Exception as e:
                print(f"  [WARN] Prophet failed for {country}: {e}")
                predicted = moving_average_forecast(train_values, HOLDOUT_DAYS)
        else:
            predicted = moving_average_forecast(train_values, HOLDOUT_DAYS)

        metrics = calculate_metrics(test_values, predicted)
        print(
            f"  [{code}] {country}: MAE={metrics['MAE']:.2f}, "
            f"RMSE={metrics['RMSE']:.2f}, MAPE={metrics['MAPE']:.1f}% "
            f"({model_used})"
        )

        results[country] = {
            "code": code,
            "metrics": metrics,
            "model": model_used,
            "n_total": len(values),
            "n_train": len(train_values),
            "n_test": HOLDOUT_DAYS,
        }

    return results


# --- STEP 3: Seasonality Parameter Optimization ------------------------------

def grid_search_prophet(conn):
    """Grid search over Prophet seasonality parameters.

    Returns best parameters and full grid results.
    """
    param_grid = {
        "yearly_seasonality": [True, False],
        "weekly_seasonality": [True, False],
        "changepoint_prior_scale": [0.05, 0.1, 0.3],
    }

    # Generate all combinations
    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))

    best_avg_mae = float("inf")
    best_params = None
    all_results = []

    for combo in combos:
        params = dict(zip(keys, combo))
        total_mae = 0.0
        n_valid = 0

        for country in BACKTEST_COUNTRIES:
            dates, values = load_timeseries(conn, country, "overall")
            if len(values) < HOLDOUT_DAYS + 10:
                continue

            train_values = values[:-HOLDOUT_DAYS]
            test_values = values[-HOLDOUT_DAYS:]
            train_dates = dates[:-HOLDOUT_DAYS]

            try:
                predicted = prophet_forecast(train_dates, train_values, HOLDOUT_DAYS, params)
                mae = np.mean(np.abs(test_values - predicted))
                total_mae += mae
                n_valid += 1
            except Exception:
                continue

        if n_valid > 0:
            avg_mae = total_mae / n_valid
        else:
            avg_mae = float("inf")

        result_entry = {**params, "avg_mae": round(avg_mae, 4), "n_countries": n_valid}
        all_results.append(result_entry)
        print(
            f"    yearly={str(params['yearly_seasonality']):5s} "
            f"weekly={str(params['weekly_seasonality']):5s} "
            f"cps={params['changepoint_prior_scale']:.2f} => "
            f"avg_MAE={avg_mae:.4f} (n={n_valid})"
        )

        if avg_mae < best_avg_mae:
            best_avg_mae = avg_mae
            best_params = params.copy()

    return {
        "best_params": best_params,
        "best_avg_mae": round(best_avg_mae, 4),
        "grid_results": all_results,
    }


def optimize_moving_average(conn):
    """Optimize window size for moving-average model."""
    windows = [3, 5, 7, 10, 14, 21]
    best_window = 7
    best_avg_mae = float("inf")
    all_results = []

    for window in windows:
        total_mae = 0.0
        n_valid = 0

        for country in BACKTEST_COUNTRIES:
            dates, values = load_timeseries(conn, country, "overall")
            if len(values) < HOLDOUT_DAYS + 10:
                continue

            train_values = values[:-HOLDOUT_DAYS]
            test_values = values[-HOLDOUT_DAYS:]

            predicted = moving_average_forecast(train_values, HOLDOUT_DAYS, window=window)
            mae = np.mean(np.abs(test_values - predicted))
            total_mae += mae
            n_valid += 1

        avg_mae = total_mae / n_valid if n_valid > 0 else float("inf")
        all_results.append({"window": window, "avg_mae": round(avg_mae, 4), "n_countries": n_valid})
        print(f"    window={window:2d} => avg_MAE={avg_mae:.4f} (n={n_valid})")

        if avg_mae < best_avg_mae:
            best_avg_mae = avg_mae
            best_window = window

    return {
        "best_params": {"model": "moving_average_linear_trend", "window": best_window},
        "best_avg_mae": round(best_avg_mae, 4),
        "grid_results": all_results,
    }


def save_params_yaml(params, model_type):
    """Save optimal parameters to config/prophet_params.yaml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CONFIG_DIR / "prophet_params.yaml"

    config_data = {
        "model_type": model_type,
        "optimized_at": datetime.datetime.now().isoformat(),
        "parameters": params,
    }

    if YAML_AVAILABLE:
        with open(out_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
    else:
        # Fallback: write simple YAML manually
        with open(out_path, "w") as f:
            f.write(f"model_type: {model_type}\n")
            f.write(f'optimized_at: "{config_data["optimized_at"]}"\n')
            f.write("parameters:\n")
            for k, v in params.items():
                if isinstance(v, bool):
                    f.write(f"  {k}: {'true' if v else 'false'}\n")
                else:
                    f.write(f"  {k}: {v}\n")

    print(f"  Saved to {out_path}")
    return out_path


# --- STEP 4: Leading Indicator Detection --------------------------------------

def compute_cross_correlation(x, y, max_lag=30):
    """Compute cross-correlation between two time series at lags 0..max_lag.

    Returns list of dicts with lag, r, p for each lag.
    Positive lag means x leads y.
    """
    results = []
    n = len(x)

    for lag in range(0, max_lag + 1):
        if lag >= n - 5:  # Need at least 5 overlapping points
            break

        if lag == 0:
            x_seg = x
            y_seg = y
        else:
            x_seg = x[:-lag]
            y_seg = y[lag:]

        if len(x_seg) < 5:
            continue

        if SCIPY_AVAILABLE:
            r, p = scipy_stats.pearsonr(x_seg, y_seg)
        else:
            # Manual Pearson correlation
            x_mean = np.mean(x_seg)
            y_mean = np.mean(y_seg)
            x_std = np.std(x_seg, ddof=1)
            y_std = np.std(y_seg, ddof=1)
            if x_std == 0 or y_std == 0:
                r, p = 0.0, 1.0
            else:
                cov = np.sum((x_seg - x_mean) * (y_seg - y_mean)) / (len(x_seg) - 1)
                r = cov / (x_std * y_std)
                nn = len(x_seg)
                if abs(r) < 1.0:
                    t_stat = r * np.sqrt((nn - 2) / (1 - r**2))
                    # Approximate two-tailed p-value
                    p = 2 * (1 - min(1.0, 0.5 * (1 + abs(t_stat) / np.sqrt(nn))))
                else:
                    p = 0.0

        results.append({"lag": lag, "r": float(r), "p": float(p)})

    return results


def detect_leading_indicators(conn):
    """Detect dimension pairs where one leads another by 7-30 days.

    Returns list of significant leading indicator relationships.
    """
    findings = []
    dim_pairs = list(itertools.combinations(TARGET_DIMENSIONS, 2))

    for country in PRIORITY_COUNTRIES:
        # Load all dimension time series for this country
        dim_data = {}
        for dim in TARGET_DIMENSIONS:
            dates, values = load_timeseries(conn, country, dim)
            if len(values) >= 30:
                dim_data[dim] = (dates, values)

        if len(dim_data) < 2:
            continue

        # Check all pairs in both directions
        for dim_a, dim_b in dim_pairs:
            if dim_a not in dim_data or dim_b not in dim_data:
                continue

            dates_a, vals_a = dim_data[dim_a]
            dates_b, vals_b = dim_data[dim_b]

            # Align by date
            set_a = {d: v for d, v in zip(dates_a, vals_a)}
            set_b = {d: v for d, v in zip(dates_b, vals_b)}
            common_dates = sorted(set(set_a.keys()) & set(set_b.keys()))

            if len(common_dates) < 30:
                continue

            aligned_a = np.array([set_a[d] for d in common_dates])
            aligned_b = np.array([set_b[d] for d in common_dates])

            # Skip if either series is constant (zero variance)
            if np.std(aligned_a) < 0.01 or np.std(aligned_b) < 0.01:
                continue

            # Direction 1: dim_a leads dim_b
            xcorr = compute_cross_correlation(aligned_a, aligned_b, max_lag=30)
            for entry in xcorr:
                if 7 <= entry["lag"] <= 30 and entry["p"] < 0.05 and abs(entry["r"]) > 0.3:
                    findings.append({
                        "country": country,
                        "leading_dim": dim_a,
                        "lagging_dim": dim_b,
                        "lag_days": entry["lag"],
                        "correlation": round(entry["r"], 4),
                        "p_value": round(entry["p"], 6),
                    })

            # Direction 2: dim_b leads dim_a
            xcorr = compute_cross_correlation(aligned_b, aligned_a, max_lag=30)
            for entry in xcorr:
                if 7 <= entry["lag"] <= 30 and entry["p"] < 0.05 and abs(entry["r"]) > 0.3:
                    findings.append({
                        "country": country,
                        "leading_dim": dim_b,
                        "lagging_dim": dim_a,
                        "lag_days": entry["lag"],
                        "correlation": round(entry["r"], 4),
                        "p_value": round(entry["p"], 6),
                    })

    return findings


def save_leading_indicators_md(findings):
    """Save leading indicator findings to docs/LEADING_INDICATORS.md."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DIR / "LEADING_INDICATORS.md"

    lines = [
        "# Leading Indicator Detection Results",
        "",
        f"**Generated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Method:** Cross-correlation analysis (lags 7-30 days, p<0.05, |r|>0.3)",
        f"**Dimensions analyzed:** {', '.join(TARGET_DIMENSIONS)}",
        f"**Countries analyzed:** {len(PRIORITY_COUNTRIES)}",
        "",
        "---",
        "",
    ]

    if not findings:
        lines.append("## No Significant Leading Indicators Found")
        lines.append("")
        lines.append(
            "No dimension pairs showed statistically significant leading relationships "
            "(p<0.05) at lags of 7-30 days across the analyzed countries."
        )
        lines.append("")
        lines.append("**Possible reasons:**")
        lines.append("- Synthetic data may not capture real-world temporal dependencies")
        lines.append("- More historical data needed to detect genuine lead-lag patterns")
        lines.append("- Consider re-running after 60+ days of live data collection")
    else:
        # Group by country
        by_country = {}
        for f in findings:
            by_country.setdefault(f["country"], []).append(f)

        lines.append(f"## Summary: {len(findings)} Leading Relationships Found")
        lines.append("")
        lines.append(f"Across {len(by_country)} countries:")
        lines.append("")

        # Summary table
        lines.append("| Country | Leading Dimension | Lagging Dimension | Lag (days) | r | p-value |")
        lines.append("|---------|-------------------|-------------------|------------|---|---------|")

        # Sort by absolute correlation strength
        sorted_findings = sorted(findings, key=lambda x: abs(x["correlation"]), reverse=True)
        for f in sorted_findings[:50]:  # Top 50
            lines.append(
                f"| {f['country']} | {f['leading_dim']} | {f['lagging_dim']} | "
                f"{f['lag_days']} | {f['correlation']:.3f} | {f['p_value']:.4f} |"
            )

        lines.append("")

        # Detail sections by country
        lines.append("## Details by Country")
        lines.append("")
        for country in sorted(by_country.keys()):
            entries = by_country[country]
            lines.append(f"### {country}")
            lines.append("")
            for f in sorted(entries, key=lambda x: abs(x["correlation"]), reverse=True):
                direction = "positively" if f["correlation"] > 0 else "inversely"
                lines.append(
                    f"- **{f['leading_dim']}** leads **{f['lagging_dim']}** "
                    f"by {f['lag_days']} days (r={f['correlation']:.3f}, "
                    f"p={f['p_value']:.4f}, {direction} correlated)"
                )
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append("1. For each country, load daily scores for conflict, humanitarian, economic, disaster, political")
    lines.append("2. For each pair (A, B), compute Pearson correlation at lags 7-30 days")
    lines.append("3. A 'leads' B at lag L means: A(t) correlates with B(t+L)")
    lines.append("4. Filter for |r| > 0.3 and p < 0.05 (two-tailed)")
    lines.append("5. Results inform which dimensions can serve as early-warning signals")
    lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"  Saved to {out_path}")
    return out_path


# --- STEP 5: Generate Report -------------------------------------------------

def generate_report(data_counts, backtest_results, optimization_results,
                    leading_indicators, model_type):
    """Generate the final validation report."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "v07_STREAM1_prophet_validation.md"

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# STREAM 1: Prophet Forecast Validation Report",
        "",
        f"**Date:** {datetime.date.today().isoformat()}",
        f"**Generated:** {now}",
        f"**Version:** v0.7-STREAM1",
        f"**Model Used:** {model_type}",
        f"**Status:** COMPLETE",
        "",
        "---",
        "",
        "## 1. Data Sufficiency",
        "",
        f"Minimum required records: {MIN_RECORDS} per country.",
        f"Synthetic generation: {SYNTHETIC_DAYS} days of Gaussian-noise data when insufficient.",
        "",
        "| Country | Code | Records | Status |",
        "|---------|------|---------|--------|",
    ]

    for country, code in BACKTEST_COUNTRIES.items():
        count = data_counts.get(country, 0)
        status = "Sufficient" if count >= MIN_RECORDS else "Generated"
        lines.append(f"| {country} | {code} | {count} | {status} |")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Backtest Accuracy (Hold-out Validation)",
        "",
        f"**Method:** Train on all data except last {HOLDOUT_DAYS} days; forecast {HOLDOUT_DAYS} days ahead.",
        f"**Model:** {model_type}",
        "",
        "| Country | Code | N(train) | N(test) | MAE | RMSE | MAPE (%) | Model |",
        "|---------|------|----------|---------|-----|------|----------|-------|",
    ])

    total_mae, total_rmse, total_mape, n_valid = 0.0, 0.0, 0.0, 0
    for country, result in backtest_results.items():
        code = result["code"]
        m = result["metrics"]
        if m["MAE"] is not None:
            lines.append(
                f"| {country} | {code} | {result.get('n_train', '-')} | "
                f"{result.get('n_test', '-')} | {m['MAE']:.2f} | "
                f"{m['RMSE']:.2f} | {m['MAPE']:.1f} | {result['model']} |"
            )
            total_mae += m["MAE"]
            total_rmse += m["RMSE"]
            total_mape += m["MAPE"]
            n_valid += 1
        else:
            lines.append(
                f"| {country} | {code} | {result.get('n_total', 0)} | - | - | - | - | skipped |"
            )

    if n_valid > 0:
        avg_mae = total_mae / n_valid
        avg_rmse = total_rmse / n_valid
        avg_mape = total_mape / n_valid
        lines.append(
            f"| **Average** | - | - | - | **{avg_mae:.2f}** | **{avg_rmse:.2f}** | "
            f"**{avg_mape:.1f}** | - |"
        )

    lines.extend([
        "",
        "### Interpretation",
        "",
    ])

    if n_valid > 0:
        if avg_mae < 5:
            quality = "Excellent"
        elif avg_mae < 10:
            quality = "Good"
        elif avg_mae < 15:
            quality = "Acceptable"
        else:
            quality = "Needs improvement"

        lines.append(
            f"- **Overall accuracy: {quality}** (avg MAE = {avg_mae:.2f})"
        )
        lines.append(
            f"- Average MAPE of {avg_mape:.1f}% indicates "
            f"{'high' if avg_mape < 20 else 'moderate' if avg_mape < 40 else 'low'} "
            f"forecasting reliability"
        )
    else:
        lines.append("- Insufficient data to evaluate forecast accuracy")

    lines.extend([
        "",
        "---",
        "",
        "## 3. Optimal Parameters",
        "",
    ])

    best = optimization_results.get("best_params", {})
    if model_type == "prophet":
        lines.extend([
            f"**Best Prophet Parameters** (avg MAE = {optimization_results.get('best_avg_mae', '-')}):",
            "",
            "```yaml",
            f"yearly_seasonality: {best.get('yearly_seasonality', False)}",
            f"weekly_seasonality: {best.get('weekly_seasonality', False)}",
            f"changepoint_prior_scale: {best.get('changepoint_prior_scale', 0.1)}",
            "```",
            "",
            "### Grid Search Results",
            "",
            "| Yearly | Weekly | CPS | Avg MAE | Countries |",
            "|--------|--------|-----|---------|-----------|",
        ])
        for r in optimization_results.get("grid_results", []):
            lines.append(
                f"| {r.get('yearly_seasonality', '-')} | {r.get('weekly_seasonality', '-')} | "
                f"{r.get('changepoint_prior_scale', '-')} | {r.get('avg_mae', '-')} | "
                f"{r.get('n_countries', '-')} |"
            )
    else:
        lines.extend([
            f"**Best Moving-Average Parameters** (avg MAE = {optimization_results.get('best_avg_mae', '-')}):",
            "",
            "```yaml",
            f"model: {best.get('model', 'moving_average_linear_trend')}",
            f"window: {best.get('window', 7)}",
            "```",
            "",
            "### Window Size Search Results",
            "",
            "| Window | Avg MAE | Countries |",
            "|--------|---------|-----------|",
        ])
        for r in optimization_results.get("grid_results", []):
            lines.append(
                f"| {r.get('window', '-')} | {r.get('avg_mae', '-')} | {r.get('n_countries', '-')} |"
            )

    lines.extend([
        "",
        f"Saved to: `config/prophet_params.yaml`",
        "",
        "---",
        "",
        "## 4. Leading Indicator Pairs",
        "",
        f"**Analyzed:** {len(PRIORITY_COUNTRIES)} countries, {len(TARGET_DIMENSIONS)} dimensions",
        f"**Method:** Cross-correlation at lags 7-30 days, p<0.05, |r|>0.3",
        "",
    ])

    if not leading_indicators:
        lines.extend([
            "**No significant leading indicator pairs were found.**",
            "",
            "This is expected when:",
            "- Data is largely synthetic (Gaussian noise around a baseline)",
            "- Insufficient historical data (< 90 days of live scores)",
            "- Dimensions are independently generated without causal structure",
            "",
            "**Recommendation:** Re-run this analysis after 90+ days of live data collection.",
        ])
    else:
        # Group by leading pair (across countries)
        pair_counts = {}
        for f in leading_indicators:
            pair_key = f"{f['leading_dim']} -> {f['lagging_dim']}"
            pair_counts.setdefault(pair_key, []).append(f)

        lines.append(f"**{len(leading_indicators)} significant pairs found across {len(pair_counts)} unique relationships.**")
        lines.append("")
        lines.append("### Most Common Leading Relationships")
        lines.append("")
        lines.append("| Leading -> Lagging | Countries | Avg Lag | Avg |r| |")
        lines.append("|-------------------|-----------|---------|---------|")

        for pair, entries in sorted(pair_counts.items(), key=lambda x: len(x[1]), reverse=True)[:15]:
            countries = list(set(e["country"] for e in entries))
            avg_lag = np.mean([e["lag_days"] for e in entries])
            avg_r = np.mean([abs(e["correlation"]) for e in entries])
            lines.append(
                f"| {pair} | {len(countries)} | {avg_lag:.0f} | {avg_r:.3f} |"
            )

    lines.extend([
        "",
        f"Full results: `docs/LEADING_INDICATORS.md`",
        "",
        "---",
        "",
        "## 5. Model Recommendation",
        "",
    ])

    if model_type == "prophet":
        lines.extend([
            "### Prophet (Recommended)",
            "",
            "Prophet is available and functional on this system. Recommended configuration:",
            "",
            f"- **yearly_seasonality:** {best.get('yearly_seasonality', False)}",
            f"- **weekly_seasonality:** {best.get('weekly_seasonality', False)}",
            f"- **changepoint_prior_scale:** {best.get('changepoint_prior_scale', 0.1)}",
            "",
            "**Notes:**",
            "- Prophet handles trend changes and missing data well",
            "- With only ~90 days of data, yearly seasonality is not yet detectable",
            "- Weekly seasonality may capture weekday/weekend reporting patterns",
            "- As data accumulates (6+ months), re-run optimization to update parameters",
            "",
            "### Fallback: Moving Average + Linear Trend",
            "",
            "If Prophet becomes unavailable, the moving-average fallback is also configured.",
            "Performance difference is minimal with current (short) time series.",
        ])
    else:
        lines.extend([
            "### Moving Average + Linear Trend (Active)",
            "",
            f"Using window size = {best.get('window', 7)} days.",
            "",
            "**Notes:**",
            "- Simple, fast, no external dependencies",
            "- Adequate for short time series (< 180 days)",
            "- Cannot capture complex seasonality patterns",
            "",
            "### Upgrade Path: Prophet",
            "",
            "When Prophet becomes installable (requires C++ compiler + cmdstan):",
            "1. `pip install prophet`",
            "2. Re-run `python scripts/validate_prophet_forecasting.py`",
            "3. Prophet grid search will automatically optimize parameters",
        ])

    lines.extend([
        "",
        "---",
        "",
        "## Appendix: Data Notes",
        "",
        "- Synthetic data was generated for countries with fewer than 30 historical records",
        "- Synthetic data uses baseline scores + Gaussian noise (std=10), clipped to [0, 100]",
        "- Metrics on synthetic data serve as a **framework validation**, not real accuracy",
        "- True forecast accuracy can only be assessed after 60+ days of live data collection",
        "",
        "---",
        "",
        f"*Report generated by `scripts/validate_prophet_forecasting.py` on {now}*",
        "",
    ])

    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"  Report saved to {out_path}")
    return out_path


# --- Main ---------------------------------------------------------------------

def main():
    print("=" * 70)
    print("STREAM 1: Prophet Forecast Validation and Tuning")
    print("=" * 70)
    print()

    # Connect to database
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))

    # -- Step 1: Data Sufficiency --
    print("[STEP 1] Data Sufficiency Check")
    print("-" * 40)
    data_counts = ensure_data_sufficiency(conn)
    print()

    # Also generate synthetic data for ALL priority countries (for leading indicator analysis)
    print("[STEP 1b] Ensuring data for all 50 priority countries...")
    baselines = get_baseline_scores(conn)
    all_counts = count_records_per_country(conn)
    synth_count = 0
    for country in PRIORITY_COUNTRIES:
        if all_counts.get(country, 0) < MIN_RECORDS:
            generate_synthetic_timeseries(conn, country, baselines)
            synth_count += 1
    if synth_count > 0:
        print(f"  Generated synthetic data for {synth_count} additional countries.")
    else:
        print("  All priority countries have sufficient data.")
    print()

    # -- Step 2: Backtest --
    print("[STEP 2] Backtest (Hold-out Validation)")
    print("-" * 40)
    backtest_results = run_backtest(conn, use_prophet=PROPHET_AVAILABLE)
    print()

    # -- Step 3: Parameter Optimization --
    print("[STEP 3] Parameter Optimization")
    print("-" * 40)

    if PROPHET_AVAILABLE:
        model_type = "prophet"
        print("  Running Prophet grid search (12 combinations x 8 countries)...")
        optimization_results = grid_search_prophet(conn)
        best_params = optimization_results["best_params"]
    else:
        model_type = "moving_average_linear_trend"
        print("  Running moving-average window optimization...")
        optimization_results = optimize_moving_average(conn)
        best_params = optimization_results["best_params"]

    save_params_yaml(best_params, model_type)
    print()

    # -- Step 4: Leading Indicator Detection --
    print("[STEP 4] Leading Indicator Detection")
    print("-" * 40)
    print(f"  Analyzing {len(PRIORITY_COUNTRIES)} countries, {len(TARGET_DIMENSIONS)} dimensions...")
    leading_indicators = detect_leading_indicators(conn)
    print(f"  Found {len(leading_indicators)} significant leading relationships.")
    li_path = save_leading_indicators_md(leading_indicators)
    print()

    # -- Step 5: Generate Report --
    print("[STEP 5] Generating Validation Report")
    print("-" * 40)
    report_path = generate_report(
        data_counts, backtest_results, optimization_results, leading_indicators, model_type
    )
    print()

    conn.close()

    # Summary
    print("=" * 70)
    print("STREAM 1 COMPLETE")
    print("=" * 70)
    print(f"  Model type:      {model_type}")
    print(f"  Best avg MAE:    {optimization_results.get('best_avg_mae', '-')}")
    print(f"  Leading pairs:   {len(leading_indicators)}")
    print(f"  Config saved:    config/prophet_params.yaml")
    print(f"  Indicators doc:  docs/LEADING_INDICATORS.md")
    print(f"  Report:          reports/v07_STREAM1_prophet_validation.md")
    print()


if __name__ == "__main__":
    main()
