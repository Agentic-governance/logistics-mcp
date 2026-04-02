"""リスクスコア予測エンジン
移動平均 + EnsembleForecaster (LightGBM + Prophet) + 先行指標検出
STREAM 3-A: LightGBM(0.6) + Prophet(0.4) アンサンブルで MAE < 6.0 を目標
"""
from datetime import datetime, timedelta
from typing import Optional
import math
import sqlite3
import os
import json
import logging

logger = logging.getLogger(__name__)

class RiskForecaster:
    """リスクスコア予測"""

    def __init__(self):
        self.store = None
        try:
            from features.timeseries.store import RiskTimeSeriesStore
            self.store = RiskTimeSeriesStore()
        except Exception:
            pass

    def forecast(self, location: str, dimension: str = "overall", horizon_days: int = 30) -> dict:
        """N日先のリスクスコア予測"""
        if not self.store:
            return {"error": "Store not initialized", "timestamp": datetime.utcnow().isoformat()}

        # Get historical data (180 days)
        end_date = datetime.utcnow().isoformat()
        start_date = (datetime.utcnow() - timedelta(days=180)).isoformat()

        history = self.store.get_history(location, start_date, end_date, [dimension])

        if len(history) < 3:
            return {
                "error": "Insufficient historical data (need at least 3 data points)",
                "data_points": len(history),
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Extract scores
        scores = [h["score"] for h in history if h.get("score") is not None]

        # Simple moving average forecast
        window = min(7, len(scores))
        recent_avg = sum(scores[-window:]) / window

        # Calculate trend (slope of last N points)
        if len(scores) >= 7:
            older_avg = sum(scores[-14:-7]) / min(7, len(scores) - 7) if len(scores) > 7 else recent_avg
            daily_trend = (recent_avg - older_avg) / 7
        else:
            daily_trend = 0

        # Standard deviation for confidence interval
        if len(scores) >= 3:
            mean = sum(scores) / len(scores)
            variance = sum((s - mean) ** 2 for s in scores) / len(scores)
            std_dev = math.sqrt(variance)
        else:
            std_dev = 10  # default uncertainty

        # Generate forecast
        forecast_points = []
        for day in range(1, horizon_days + 1):
            predicted = max(0, min(100, recent_avg + daily_trend * day))
            lower = max(0, predicted - 2 * std_dev)
            upper = min(100, predicted + 2 * std_dev)
            forecast_points.append({
                "day": day,
                "date": (datetime.utcnow() + timedelta(days=day)).strftime("%Y-%m-%d"),
                "predicted": round(predicted, 1),
                "lower_bound": round(lower, 1),
                "upper_bound": round(upper, 1),
            })

        return {
            "location": location,
            "dimension": dimension,
            "horizon_days": horizon_days,
            "current_score": round(recent_avg, 1),
            "trend": "increasing" if daily_trend > 0.5 else "decreasing" if daily_trend < -0.5 else "stable",
            "daily_trend": round(daily_trend, 2),
            "confidence_interval": round(2 * std_dev, 1),
            "forecast": forecast_points,
            "data_points_used": len(scores),
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def find_leading_indicators(self, target_dimension: str = "conflict",
                                       locations: list[str] = None,
                                       lag_days: int = 30) -> list[dict]:
        """先行指標検出: target_dimension に対して他の次元が先行するかをクロス相関で分析"""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "data", "timeseries.db")

        if not os.path.exists(db_path):
            return [{"error": "timeseries.db not found"}]

        all_dimensions = [
            "conflict", "humanitarian", "economic", "disaster", "political",
            "geo_risk", "sanctions", "compliance", "health", "food_security",
            "maritime", "trade", "energy", "climate_risk", "cyber_risk",
            "labor", "legal", "aviation", "infrastructure", "typhoon",
            "internet", "japan_economy", "port_congestion",
        ]
        candidate_dims = [d for d in all_dimensions if d != target_dimension]

        if not locations:
            from config.constants import PRIORITY_COUNTRIES
            locations = PRIORITY_COUNTRIES[:20]

        results = []
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        for loc in locations:
            # Get target dimension scores
            rows = conn.execute(
                "SELECT timestamp, dimension, score FROM risk_scores "
                "WHERE location = ? AND dimension IN (?, 'overall') "
                "ORDER BY timestamp",
                (loc, target_dimension)
            ).fetchall()

            target_scores = {}
            for row in rows:
                if row["dimension"] == target_dimension:
                    target_scores[row["timestamp"][:10]] = row["score"]

            if len(target_scores) < 10:
                continue

            for candidate in candidate_dims:
                cand_rows = conn.execute(
                    "SELECT timestamp, score FROM risk_scores "
                    "WHERE location = ? AND dimension = ? ORDER BY timestamp",
                    (loc, candidate)
                ).fetchall()

                cand_scores = {}
                for row in cand_rows:
                    cand_scores[row["timestamp"][:10]] = row["score"]

                if len(cand_scores) < 10:
                    continue

                # Align dates and compute cross-correlation at various lags
                common_dates = sorted(set(target_scores.keys()) & set(cand_scores.keys()))
                if len(common_dates) < 10:
                    continue

                target_vals = [target_scores[d] for d in common_dates]
                cand_vals = [cand_scores[d] for d in common_dates]

                best_r, best_lag, best_p = 0.0, 0, 1.0

                for lag in range(7, min(lag_days + 1, len(common_dates) // 3)):
                    if lag >= len(cand_vals):
                        break
                    x = cand_vals[:len(cand_vals) - lag]
                    y = target_vals[lag:]
                    n = min(len(x), len(y))
                    if n < 8:
                        continue

                    x, y = x[:n], y[:n]
                    mx = sum(x) / n
                    my = sum(y) / n
                    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / n)
                    sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / n)

                    if sx < 1e-6 or sy < 1e-6:
                        continue

                    r = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / (n * sx * sy)

                    # Approximate p-value using t-distribution
                    if abs(r) > 0.999:
                        p = 0.0
                    else:
                        t_stat = r * math.sqrt((n - 2) / (1 - r * r))
                        # Approximate: for n>30, t ~ normal
                        p = 2 * math.exp(-0.5 * t_stat * t_stat) / math.sqrt(2 * math.pi) if abs(t_stat) < 10 else 0.0

                    if abs(r) > abs(best_r) and abs(r) > 0.3:
                        best_r, best_lag, best_p = r, lag, p

                if abs(best_r) > 0.3 and best_p < 0.10:
                    results.append({
                        "location": loc,
                        "leading_dim": candidate,
                        "target_dim": target_dimension,
                        "r": round(best_r, 3),
                        "lag_days": best_lag,
                        "p_value": round(best_p, 4),
                        "data_points": len(common_dates),
                    })

        conn.close()
        return sorted(results, key=lambda x: -abs(x["r"]))

    def detect_anomaly(self, location: str, dimension: str = "overall") -> dict:
        """異常検知"""
        if not self.store:
            return {"error": "Store not initialized"}

        end_date = datetime.utcnow().isoformat()
        start_date = (datetime.utcnow() - timedelta(days=90)).isoformat()

        history = self.store.get_history(location, start_date, end_date, [dimension])

        if len(history) < 5:
            return {"error": "Insufficient data for anomaly detection", "data_points": len(history)}

        scores = [h["score"] for h in history if h.get("score") is not None]
        latest = scores[-1]

        # Calculate mean and std of all except latest
        historical = scores[:-1]
        mean = sum(historical) / len(historical)
        variance = sum((s - mean) ** 2 for s in historical) / len(historical)
        std_dev = math.sqrt(variance) if variance > 0 else 1

        z_score = (latest - mean) / std_dev if std_dev > 0 else 0
        is_anomaly = abs(z_score) > 2.0

        return {
            "location": location,
            "dimension": dimension,
            "is_anomaly": is_anomaly,
            "z_score": round(z_score, 2),
            "actual_value": latest,
            "expected_range": {"lower": round(mean - 2 * std_dev, 1), "upper": round(mean + 2 * std_dev, 1)},
            "mean": round(mean, 1),
            "std_dev": round(std_dev, 1),
            "timestamp": datetime.utcnow().isoformat(),
        }


# ===========================================================================
#  STREAM 3-A: EnsembleForecaster (LightGBM + Prophet)
# ===========================================================================


class EnsembleForecaster:
    """LightGBM(0.6) + Prophet(0.4) アンサンブル予測
    LightGBM 不可時は Enhanced Moving Average にフォールバック。
    """

    LGBM_WEIGHT = 0.6
    PROPHET_WEIGHT = 0.4

    def __init__(self):
        self.db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "timeseries.db",
        )
        self._lgbm_available = False
        self._prophet_available = False
        self._check_dependencies()

    def _check_dependencies(self):
        try:
            import lightgbm  # noqa: F401
            self._lgbm_available = True
        except ImportError:
            logger.info("LightGBM not available; using enhanced MA fallback")
        try:
            from prophet import Prophet  # noqa: F401
            self._prophet_available = True
        except ImportError:
            logger.info("Prophet not available; adjusting ensemble weights")

    # ------------------------------------------------------------------
    #  Feature Engineering for LightGBM
    # ------------------------------------------------------------------

    def _build_features(self, scores: list[float], timestamps: list[str] = None) -> tuple:
        """Create lag/time/statistical features for LightGBM.

        Returns:
            (X, y) where X is list of feature dicts and y is target values.
            First 30 rows are dropped (need lag-30).
        """
        if len(scores) < 35:
            return [], []

        X = []
        y = []
        for i in range(30, len(scores)):
            features = {
                # Lag features
                "lag_1": scores[i - 1],
                "lag_7": scores[i - 7],
                "lag_14": scores[i - 14],
                "lag_30": scores[i - 30],
                # Rolling statistics
                "rolling_mean_7": sum(scores[i - 7:i]) / 7,
                "rolling_std_7": math.sqrt(
                    sum((s - sum(scores[i - 7:i]) / 7) ** 2 for s in scores[i - 7:i]) / 7
                ),
                "rolling_mean_14": sum(scores[i - 14:i]) / 14,
                "rolling_mean_30": sum(scores[i - 30:i]) / 30,
                # Momentum
                "momentum_7": scores[i - 1] - scores[i - 7],
                "momentum_14": scores[i - 1] - scores[i - 14],
                # Volatility
                "volatility_7": max(scores[i - 7:i]) - min(scores[i - 7:i]),
                # Relative position
                "rel_position_30": (
                    (scores[i - 1] - min(scores[i - 30:i]))
                    / max(1, max(scores[i - 30:i]) - min(scores[i - 30:i]))
                ),
            }

            # Time features (if timestamps available)
            if timestamps and i < len(timestamps):
                try:
                    dt = datetime.fromisoformat(timestamps[i][:10])
                    features["weekday"] = dt.weekday()
                    features["month"] = dt.month
                    features["day_of_year"] = dt.timetuple().tm_yday
                    features["season"] = (dt.month % 12) // 3
                except Exception:
                    features["weekday"] = 0
                    features["month"] = 1
                    features["day_of_year"] = 1
                    features["season"] = 0
            else:
                features["weekday"] = 0
                features["month"] = 1
                features["day_of_year"] = i % 365
                features["season"] = 0

            X.append(features)
            y.append(scores[i])

        return X, y

    # ------------------------------------------------------------------
    #  Core Forecast
    # ------------------------------------------------------------------

    def forecast(
        self,
        location: str,
        dimension: str = "overall",
        horizon_days: int = 30,
    ) -> dict:
        """N日先のリスクスコア予測（アンサンブル）"""
        scores, timestamps = self._load_history(location, dimension)

        if len(scores) < 10:
            return {
                "error": "Insufficient data for ensemble forecast",
                "data_points": len(scores),
                "model": "none",
                "timestamp": datetime.utcnow().isoformat(),
            }

        lgbm_forecast = None
        if self._lgbm_available and len(scores) >= 35:
            lgbm_forecast = self._forecast_lgbm(scores, timestamps, horizon_days)

        prophet_forecast = None
        if self._prophet_available and len(scores) >= 10:
            prophet_forecast = self._forecast_prophet(scores, timestamps, horizon_days)

        ema_forecast = self._forecast_enhanced_ma(scores, horizon_days)

        forecast_points = self._blend_forecasts(
            lgbm_forecast, prophet_forecast, ema_forecast, horizon_days
        )

        if lgbm_forecast and prophet_forecast:
            model = f"ensemble(lgbm={self.LGBM_WEIGHT},prophet={self.PROPHET_WEIGHT})"
        elif lgbm_forecast:
            model = "lgbm(1.0)"
        elif prophet_forecast:
            model = "prophet(1.0)"
        else:
            model = "enhanced_ma"

        window = min(7, len(scores))
        recent_avg = sum(scores[-window:]) / window
        if len(scores) >= 14:
            older_avg = sum(scores[-14:-7]) / 7
            daily_trend = (recent_avg - older_avg) / 7
        else:
            daily_trend = 0

        return {
            "location": location,
            "dimension": dimension,
            "horizon_days": horizon_days,
            "current_score": round(scores[-1], 1),
            "trend": "increasing" if daily_trend > 0.5 else "decreasing" if daily_trend < -0.5 else "stable",
            "daily_trend": round(daily_trend, 2),
            "model": model,
            "forecast": forecast_points,
            "data_points_used": len(scores),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _forecast_lgbm(
        self, scores: list[float], timestamps: list[str], horizon: int
    ) -> Optional[list[float]]:
        """LightGBM forecast"""
        try:
            import lightgbm as lgb
            import numpy as np

            X, y = self._build_features(scores, timestamps)
            if len(X) < 20:
                return None

            feature_names = sorted(X[0].keys())
            X_arr = np.array([[row[f] for f in feature_names] for row in X])
            y_arr = np.array(y)

            train_data = lgb.Dataset(X_arr, label=y_arr, feature_name=feature_names)
            params = {
                "objective": "regression",
                "metric": "mae",
                "num_leaves": 31,
                "learning_rate": 0.05,
                "feature_fraction": 0.8,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbose": -1,
            }
            model = lgb.train(params, train_data, num_boost_round=100)

            predictions = []
            extended_scores = list(scores)
            for day in range(horizon):
                features = self._build_single_features(extended_scores, len(extended_scores))
                if features is None:
                    break
                x = np.array([[features[f] for f in feature_names]])
                pred = float(model.predict(x)[0])
                pred = max(0, min(100, pred))
                predictions.append(pred)
                extended_scores.append(pred)

            return predictions if predictions else None
        except Exception as e:
            logger.warning(f"LightGBM forecast failed: {e}")
            return None

    def _build_single_features(self, scores: list[float], idx: int) -> Optional[dict]:
        """Build features for a single prediction point"""
        if idx < 30 or idx > len(scores):
            return None
        i = idx
        s = scores
        return {
            "lag_1": s[i - 1],
            "lag_7": s[i - 7] if i >= 7 else s[i - 1],
            "lag_14": s[i - 14] if i >= 14 else s[i - 1],
            "lag_30": s[i - 30] if i >= 30 else s[i - 1],
            "rolling_mean_7": sum(s[max(0, i - 7):i]) / min(7, i),
            "rolling_std_7": math.sqrt(
                sum((v - sum(s[max(0, i - 7):i]) / min(7, i)) ** 2
                    for v in s[max(0, i - 7):i]) / min(7, i)
            ) if i > 0 else 0,
            "rolling_mean_14": sum(s[max(0, i - 14):i]) / min(14, i),
            "rolling_mean_30": sum(s[max(0, i - 30):i]) / min(30, i),
            "momentum_7": s[i - 1] - (s[i - 7] if i >= 7 else s[i - 1]),
            "momentum_14": s[i - 1] - (s[i - 14] if i >= 14 else s[i - 1]),
            "volatility_7": (
                max(s[max(0, i - 7):i]) - min(s[max(0, i - 7):i]) if i > 0 else 0
            ),
            "rel_position_30": (
                (s[i - 1] - min(s[max(0, i - 30):i]))
                / max(1, max(s[max(0, i - 30):i]) - min(s[max(0, i - 30):i]))
                if i > 0 else 0.5
            ),
            "weekday": 0,
            "month": 1,
            "day_of_year": i % 365,
            "season": 0,
        }

    def _forecast_prophet(
        self, scores: list[float], timestamps: list[str], horizon: int
    ) -> Optional[list[float]]:
        """Prophet forecast"""
        try:
            from prophet import Prophet
            import pandas as pd

            dates = []
            for i, ts in enumerate(timestamps):
                try:
                    dates.append(datetime.fromisoformat(ts[:10]))
                except Exception:
                    dates.append(datetime.utcnow() - timedelta(days=len(timestamps) - i))

            while len(dates) < len(scores):
                dates.append(dates[-1] + timedelta(days=1))

            df = pd.DataFrame({"ds": dates[-len(scores):], "y": scores})
            model = Prophet(
                daily_seasonality=False, weekly_seasonality=True,
                yearly_seasonality=True, changepoint_prior_scale=0.05,
            )
            model.fit(df)
            future = model.make_future_dataframe(periods=horizon)
            forecast = model.predict(future)
            predictions = forecast["yhat"].iloc[-horizon:].tolist()
            return [max(0, min(100, p)) for p in predictions]
        except Exception as e:
            logger.warning(f"Prophet forecast failed: {e}")
            return None

    def _forecast_enhanced_ma(self, scores: list[float], horizon: int) -> list[float]:
        """Enhanced Moving Average: double exponential smoothing"""
        alpha, beta = 0.3, 0.1
        level = scores[0]
        trend = (
            (scores[min(7, len(scores) - 1)] - scores[0]) / min(7, len(scores) - 1)
            if len(scores) > 1 else 0
        )

        for s in scores[1:]:
            prev_level = level
            level = alpha * s + (1 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend

        predictions = []
        for day in range(1, horizon + 1):
            damping = 0.95 ** day
            pred = max(0, min(100, level + trend * day * damping))
            predictions.append(pred)
        return predictions

    def _blend_forecasts(
        self, lgbm: Optional[list[float]], prophet: Optional[list[float]],
        ema: list[float], horizon: int,
    ) -> list[dict]:
        """Blend available forecasts"""
        forecast_points = []
        for day in range(horizon):
            values, weights = {}, {}
            if lgbm and day < len(lgbm):
                values["lgbm"] = lgbm[day]
                weights["lgbm"] = self.LGBM_WEIGHT
            if prophet and day < len(prophet):
                values["prophet"] = prophet[day]
                weights["prophet"] = self.PROPHET_WEIGHT
            if day < len(ema):
                values["ema"] = ema[day]

            if values and any(k != "ema" for k in values):
                total_weight = sum(weights.values())
                if total_weight > 0:
                    predicted = sum(values[k] * weights[k] / total_weight for k in weights if k in values)
                else:
                    predicted = ema[day] if day < len(ema) else 50
            else:
                predicted = values.get("ema", 50)

            predicted = max(0, min(100, predicted))
            ci = min(25, 5.0 * math.sqrt(day + 1))
            forecast_points.append({
                "day": day + 1,
                "date": (datetime.utcnow() + timedelta(days=day + 1)).strftime("%Y-%m-%d"),
                "predicted": round(predicted, 1),
                "lower_bound": round(max(0, predicted - ci), 1),
                "upper_bound": round(min(100, predicted + ci), 1),
            })
        return forecast_points

    def _load_history(self, location: str, dimension: str = "overall", days: int = 365) -> tuple:
        """timeseries.db から履歴データを読み込み"""
        if not os.path.exists(self.db_path):
            return [], []
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if dimension == "overall":
            rows = conn.execute(
                "SELECT date, overall_score FROM risk_summaries "
                "WHERE location = ? ORDER BY date ASC", (location,),
            ).fetchall()
            scores = [float(r["overall_score"]) for r in rows if r["overall_score"] is not None]
            timestamps = [r["date"] for r in rows if r["overall_score"] is not None]
        else:
            rows = conn.execute(
                "SELECT date, scores_json FROM risk_summaries "
                "WHERE location = ? ORDER BY date ASC", (location,),
            ).fetchall()
            scores, timestamps = [], []
            for r in rows:
                try:
                    sj = json.loads(r["scores_json"]) if r["scores_json"] else {}
                    if dimension in sj:
                        scores.append(float(sj[dimension]))
                        timestamps.append(r["date"])
                except Exception:
                    pass
        conn.close()
        return scores, timestamps

    def backtest(self, location: str, dimension: str = "overall", holdout_days: int = 30) -> dict:
        """Hold-out バックテスト: MAE/RMSE/MAPE を算出"""
        scores, timestamps = self._load_history(location, dimension)
        if len(scores) < holdout_days + 35:
            return {
                "error": f"Insufficient data: need {holdout_days + 35}, have {len(scores)}",
                "location": location, "dimension": dimension,
            }
        train_scores = scores[:-holdout_days]
        test_scores = scores[-holdout_days:]
        train_timestamps = timestamps[:-holdout_days] if timestamps else []

        lgbm_pred = (
            self._forecast_lgbm(train_scores, train_timestamps, holdout_days)
            if self._lgbm_available and len(train_scores) >= 35 else None
        )
        prophet_pred = (
            self._forecast_prophet(train_scores, train_timestamps, holdout_days)
            if self._prophet_available and len(train_scores) >= 10 else None
        )
        ema_pred = self._forecast_enhanced_ma(train_scores, holdout_days)

        blended = []
        for day in range(holdout_days):
            vals, wts = {}, {}
            if lgbm_pred and day < len(lgbm_pred):
                vals["lgbm"] = lgbm_pred[day]
                wts["lgbm"] = self.LGBM_WEIGHT
            if prophet_pred and day < len(prophet_pred):
                vals["prophet"] = prophet_pred[day]
                wts["prophet"] = self.PROPHET_WEIGHT
            if day < len(ema_pred):
                vals["ema"] = ema_pred[day]
            if wts:
                tw = sum(wts.values())
                blended.append(sum(vals[k] * wts[k] / tw for k in wts if k in vals))
            else:
                blended.append(vals.get("ema", test_scores[day]))

        ae_list = [abs(p - a) for p, a in zip(blended, test_scores)]
        se_list = [(p - a) ** 2 for p, a in zip(blended, test_scores)]
        ape_list = [abs(p - a) / max(abs(a), 1) * 100 for p, a in zip(blended, test_scores)]

        mae = sum(ae_list) / len(ae_list)
        rmse = math.sqrt(sum(se_list) / len(se_list))
        mape = sum(ape_list) / len(ape_list)

        model_metrics = {}
        if lgbm_pred and len(lgbm_pred) == holdout_days:
            lgbm_ae = [abs(p - a) for p, a in zip(lgbm_pred, test_scores)]
            model_metrics["lgbm"] = {"mae": round(sum(lgbm_ae) / len(lgbm_ae), 2)}
        if prophet_pred and len(prophet_pred) == holdout_days:
            prophet_ae = [abs(p - a) for p, a in zip(prophet_pred, test_scores)]
            model_metrics["prophet"] = {"mae": round(sum(prophet_ae) / len(prophet_ae), 2)}
        ema_ae = [abs(p - a) for p, a in zip(ema_pred[:holdout_days], test_scores)]
        model_metrics["enhanced_ma"] = {"mae": round(sum(ema_ae) / len(ema_ae), 2)}

        return {
            "location": location, "dimension": dimension,
            "holdout_days": holdout_days, "train_size": len(train_scores),
            "test_size": holdout_days,
            "ensemble_metrics": {"mae": round(mae, 2), "rmse": round(rmse, 2), "mape": round(mape, 2)},
            "per_model_metrics": model_metrics,
            "target_mae": 6.0, "target_met": mae < 6.0,
            "timestamp": datetime.utcnow().isoformat(),
        }
