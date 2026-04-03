"""リスクスコア定期実行スケジューラー
APScheduler使用 + 異常検知統合 + 相関監査自動化
"""
import json
import os
import shutil
import glob
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# アラート出力先: log / file / both
ALERT_OUTPUT = os.environ.get("ALERT_OUTPUT", "log")

# 主要50カ国リスト
PRIORITY_COUNTRIES = [
    # G7
    "Japan", "United States", "Germany", "United Kingdom", "France", "Italy", "Canada",
    # BRICS+
    "China", "India", "Russia", "Brazil", "South Africa",
    # ASEAN主要国
    "Indonesia", "Vietnam", "Thailand", "Malaysia", "Singapore", "Philippines", "Myanmar", "Cambodia",
    # 中東
    "Saudi Arabia", "UAE", "Iran", "Iraq", "Turkey", "Israel", "Qatar", "Yemen",
    # 東アジア
    "South Korea", "Taiwan", "North Korea",
    # 南アジア
    "Bangladesh", "Pakistan", "Sri Lanka",
    # アフリカ
    "Nigeria", "Ethiopia", "Kenya", "Egypt", "South Sudan", "Somalia",
    # 欧州
    "Ukraine", "Poland", "Netherlands", "Switzerland",
    # 中南米
    "Mexico", "Colombia", "Venezuela", "Argentina", "Chile",
    # オセアニア
    "Australia",
]

# 相関監査用30カ国サブセット (地域バランスを考慮)
CORRELATION_AUDIT_COUNTRIES = [
    "Japan", "United States", "Germany", "United Kingdom", "France",
    "China", "India", "Russia", "Brazil", "South Africa",
    "Indonesia", "Vietnam", "Thailand", "Philippines", "Myanmar",
    "Saudi Arabia", "Iran", "Turkey", "Israel", "Yemen",
    "South Korea", "Taiwan", "Nigeria", "Ethiopia", "Egypt",
    "Ukraine", "Mexico", "Colombia", "Venezuela", "Australia",
]


def _load_accepted_correlations() -> list[dict]:
    """config/accepted_correlations.yaml から承認済みペアを読み込む"""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    yaml_path = os.path.join(project_root, "config", "accepted_correlations.yaml")
    try:
        import yaml
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        return data.get("accepted_pairs", [])
    except ImportError:
        logger.warning("PyYAML not installed; cannot load accepted_correlations.yaml")
        return []
    except FileNotFoundError:
        logger.warning(f"Accepted correlations file not found: {yaml_path}")
        return []
    except Exception as e:
        logger.error(f"Failed to load accepted correlations: {e}")
        return []


def _is_accepted_pair(dim1: str, dim2: str, r: float,
                      accepted: list[dict]) -> tuple[bool, str]:
    """ペアが承認済みかどうか判定する。

    Returns:
        (is_accepted, reason) -- 承認済みなら (True, reason文字列)
    """
    for entry in accepted:
        ed1, ed2 = entry.get("dim1", ""), entry.get("dim2", "")
        threshold = entry.get("r_threshold", 0.90)
        reason = entry.get("reason", "")
        if ((dim1 == ed1 and dim2 == ed2) or (dim1 == ed2 and dim2 == ed1)):
            if abs(r) <= threshold:
                return True, reason
            # r exceeds the per-pair threshold -- still accepted but flag it
            return True, f"{reason} (NOTE: r={r:.3f} exceeds threshold {threshold})"
    return False, ""


def _write_correlation_alert(alert: dict, project_root: str):
    """相関アラートを data/alerts/ に JSONL 追記する"""
    alerts_dir = os.path.join(project_root, "data", "alerts")
    os.makedirs(alerts_dir, exist_ok=True)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    filepath = os.path.join(alerts_dir, f"{today}.jsonl")
    with open(filepath, "a") as f:
        f.write(json.dumps(alert, ensure_ascii=False) + "\n")


class RiskScoreScheduler:
    """定期リスクスコア更新スケジューラー"""

    def __init__(self):
        self.store = None
        self._init_store()

    def _init_store(self):
        try:
            from features.timeseries.store import RiskTimeSeriesStore
            self.store = RiskTimeSeriesStore()
        except Exception as e:
            logger.error(f"Failed to initialize store: {e}")

    def run_full_assessment(self, countries: list = None):
        """全対象国のリスクスコアを計算・保存"""
        from scoring.engine import calculate_risk_score

        targets = countries or PRIORITY_COUNTRIES
        results = []

        for country in targets:
            try:
                score = calculate_risk_score(
                    f"sched_{country.lower().replace(' ', '_')}",
                    f"Scheduled: {country}",
                    country=country, location=country
                )
                score_dict = score.to_dict()

                if self.store:
                    self.store.store_score(country, score_dict)
                    self.store.store_daily_summary(country, score_dict)

                # 異常検知
                self._run_anomaly_check(country, score_dict)

                results.append({
                    "country": country,
                    "overall_score": score_dict["overall_score"],
                    "risk_level": score_dict["risk_level"],
                })
                logger.info(f"Assessed {country}: {score_dict['overall_score']} ({score_dict['risk_level']})")
            except Exception as e:
                logger.error(f"Failed to assess {country}: {e}")
                results.append({"country": country, "error": str(e)})

        return {
            "assessed": len([r for r in results if "error" not in r]),
            "errors": len([r for r in results if "error" in r]),
            "results": results,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def run_critical_update(self, threshold: int = 80):
        """CRITICALフラグ国のみ更新"""
        if not self.store:
            return {"error": "Store not initialized"}

        critical_countries = []
        for country in PRIORITY_COUNTRIES:
            latest = self.store.get_latest(country)
            if latest and latest.get("overall_score", 0) >= threshold:
                critical_countries.append(country)

        if critical_countries:
            return self.run_full_assessment(critical_countries)
        return {"message": "No critical countries to update", "timestamp": datetime.utcnow().isoformat()}

    def run_sanctions_update(self):
        """全制裁ソースの更新を実行"""
        from datetime import datetime
        import logging
        logger = logging.getLogger(__name__)

        sources = [
            ("OFAC", "pipeline.sanctions.ofac", "fetch_ofac_sdn"),
            ("UN", "pipeline.sanctions.un", "fetch_un_sanctions"),
            ("EU", "pipeline.sanctions.eu", "fetch_eu_sanctions"),
        ]

        results = []
        for source_name, module_path, func_name in sources:
            try:
                mod = __import__(module_path, fromlist=[func_name])
                func = getattr(mod, func_name, None)
                if func:
                    count = func()
                    results.append({"source": source_name, "status": "ok", "records": count})
                    logger.info(f"Sanctions update {source_name}: {count} records")
                else:
                    results.append({"source": source_name, "status": "skipped", "reason": "function not found"})
            except Exception as e:
                results.append({"source": source_name, "status": "error", "error": str(e)})
                logger.error(f"Sanctions update {source_name} failed: {e}")

        return {"timestamp": datetime.utcnow().isoformat(), "results": results}

    def run_correlation_check(self):
        """相関行列の定期チェック"""
        from datetime import datetime
        import logging
        logger = logging.getLogger(__name__)

        try:
            from features.analytics.correlation_analyzer import CorrelationAnalyzer
            analyzer = CorrelationAnalyzer()
            # Use a subset of countries for weekly check
            check_countries = ["Japan", "China", "United States", "Germany", "India",
                              "Brazil", "South Korea", "Vietnam", "Yemen", "Nigeria"]
            matrix = analyzer.compute_dimension_correlations(check_countries)

            # Find high correlation pairs
            high_pairs = []
            for pair in matrix.high_correlations:
                if abs(pair.coefficient) > 0.90:
                    high_pairs.append({
                        "dim1": pair.dim_a,
                        "dim2": pair.dim_b,
                        "correlation": pair.coefficient,
                    })
                    logger.warning(f"High correlation detected: {pair.dim_a} ↔ {pair.dim_b} r={pair.coefficient:.3f}")

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "matrix_size": f"{len(matrix.dimensions)}x{len(matrix.dimensions)}",
                "high_correlation_pairs_gt90": len(high_pairs),
                "pairs": high_pairs,
            }
        except Exception as e:
            logger.error(f"Correlation check failed: {e}")
            return {"timestamp": datetime.utcnow().isoformat(), "error": str(e)}

    def run_weekly_correlation_audit(self):
        """週次相関監査: 30カ国の相関行列を計算し、新規 r>0.85 ペアを検出。

        承認済みペア (config/accepted_correlations.yaml) と比較し、
        未承認の SOURCE_PROBLEM / DOUBLE_COUNTING ペアについて
        data/alerts/ にアラートを生成する。

        スケジュール: 毎週日曜 04:00 JST (19:00 UTC 土曜)
        """
        from datetime import datetime
        import logging
        logger = logging.getLogger(__name__)

        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        run_timestamp = datetime.utcnow().isoformat()
        logger.info(f"Weekly correlation audit started at {run_timestamp}")

        try:
            from features.analytics.correlation_analyzer import CorrelationAnalyzer
            analyzer = CorrelationAnalyzer()

            # 1. 30カ国の相関行列を計算
            matrix = analyzer.compute_dimension_correlations(
                CORRELATION_AUDIT_COUNTRIES, "pearson"
            )

            if hasattr(matrix, "to_dict"):
                d = matrix.to_dict()
            elif isinstance(matrix, dict):
                d = matrix
            else:
                d = {"dimensions": matrix.dimensions, "matrix": matrix.matrix}

            dims = d["dimensions"]
            mat = d["matrix"]

            # 2. r > 0.85 ペアを抽出
            high_pairs = []
            for i in range(len(dims)):
                for j in range(i + 1, len(dims)):
                    r = mat[i][j]
                    if abs(r) > 0.85:
                        high_pairs.append({
                            "dim1": dims[i],
                            "dim2": dims[j],
                            "r": round(r, 4),
                        })

            high_pairs.sort(key=lambda p: -abs(p["r"]))

            # 3. accepted_correlations.yaml と比較
            accepted = _load_accepted_correlations()

            # diagnose_correlations.py の分類ロジックを利用
            try:
                from scripts.diagnose_correlations import classify_correlation
            except ImportError:
                # フォールバック: 簡易分類
                def classify_correlation(d1, d2, r):
                    if abs(r) > 0.90:
                        return "SOURCE_PROBLEM", "r > 0.90"
                    return "MONITOR", "0.85 < r <= 0.90"

            new_alerts = []
            accepted_count = 0
            for pair in high_pairs:
                dim1, dim2, r = pair["dim1"], pair["dim2"], pair["r"]
                is_accepted, accept_reason = _is_accepted_pair(dim1, dim2, r, accepted)

                classification, cls_reason = classify_correlation(dim1, dim2, r)

                if is_accepted:
                    accepted_count += 1
                    logger.debug(
                        f"Accepted pair: {dim1} <-> {dim2} r={r:.3f} ({accept_reason})"
                    )
                    continue

                # 未承認ペア -- SOURCE_PROBLEM or DOUBLE_COUNTING はアラート
                if classification in ("SOURCE_PROBLEM", "DOUBLE_COUNTING"):
                    alert = {
                        "type": "correlation_audit",
                        "severity": "high",
                        "classification": classification,
                        "dim1": dim1,
                        "dim2": dim2,
                        "r": r,
                        "reason": cls_reason,
                        "country_count": len(CORRELATION_AUDIT_COUNTRIES),
                        "message": (
                            f"[CORRELATION AUDIT] {classification}: "
                            f"{dim1} <-> {dim2} r={r:.3f} -- {cls_reason}"
                        ),
                        "timestamp": run_timestamp,
                    }
                    new_alerts.append(alert)
                    _write_correlation_alert(alert, project_root)
                    logger.warning(alert["message"])

            # 4. サマリーログ
            summary = {
                "timestamp": run_timestamp,
                "country_count": len(CORRELATION_AUDIT_COUNTRIES),
                "dimensions": len(dims),
                "pairs_above_085": len(high_pairs),
                "accepted_pairs": accepted_count,
                "new_alerts": len(new_alerts),
                "alerts": new_alerts,
            }

            logger.info(
                f"Weekly correlation audit complete: "
                f"{len(high_pairs)} pairs > 0.85, "
                f"{accepted_count} accepted, "
                f"{len(new_alerts)} new alerts generated"
            )

            return summary

        except Exception as e:
            logger.error(f"Weekly correlation audit failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "timestamp": run_timestamp,
                "error": str(e),
            }

    def run_source_health_check(self):
        """データソース疎通確認"""
        import requests
        from datetime import datetime
        import logging
        logger = logging.getLogger(__name__)

        health_endpoints = [
            ("GDACS", "https://www.gdacs.org/xml/rss.xml"),
            ("USGS", "https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson&minmagnitude=4.5"),
            ("Disease.sh", "https://disease.sh/v3/covid-19/all"),
            ("Open-Meteo", "https://api.open-meteo.com/v1/forecast?latitude=35&longitude=139&current_weather=true"),
            ("Frankfurter", "https://api.frankfurter.dev/v1/latest"),
            ("WHO GHO", "https://ghoapi.azureedge.net/api/"),
        ]

        results = []
        for name, url in health_endpoints:
            try:
                resp = requests.get(url, timeout=10)
                status = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
                results.append({"source": name, "status": status, "response_ms": int(resp.elapsed.total_seconds() * 1000)})
            except requests.Timeout:
                results.append({"source": name, "status": "timeout"})
                logger.warning(f"Source health check timeout: {name}")
            except Exception as e:
                results.append({"source": name, "status": "error", "error": str(e)})
                logger.error(f"Source health check failed: {name}: {e}")

        ok_count = sum(1 for r in results if r["status"] == "ok")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total": len(results),
            "healthy": ok_count,
            "unhealthy": len(results) - ok_count,
            "results": results,
        }

    def run_daily_backup(self):
        """日次データベースバックアップ (01:00 JST / 16:00 UTC)
        - timeseries.db と risk.db を data/backups/YYYY-MM-DD/ にコピー
        - 7日を超える古いバックアップを削除
        """
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        data_dir = os.path.join(project_root, "data")
        backup_root = os.path.join(data_dir, "backups")
        today = datetime.utcnow().strftime("%Y-%m-%d")
        backup_dir = os.path.join(backup_root, today)

        os.makedirs(backup_dir, exist_ok=True)

        db_files = ["timeseries.db", "risk.db"]
        copied = []
        for db_name in db_files:
            src = os.path.join(data_dir, db_name)
            if os.path.exists(src):
                dst = os.path.join(backup_dir, db_name)
                shutil.copy2(src, dst)
                size_mb = os.path.getsize(dst) / (1024 * 1024)
                copied.append({"file": db_name, "size_mb": round(size_mb, 2)})
                logger.info(f"Backup: {db_name} -> {backup_dir} ({size_mb:.2f} MB)")
            else:
                logger.warning(f"Backup skipped: {src} not found")

        # Retention: delete backups older than 7 days
        deleted = []
        cutoff = datetime.utcnow() - timedelta(days=7)
        if os.path.isdir(backup_root):
            for entry in sorted(os.listdir(backup_root)):
                entry_path = os.path.join(backup_root, entry)
                if not os.path.isdir(entry_path):
                    continue
                try:
                    entry_date = datetime.strptime(entry, "%Y-%m-%d")
                    if entry_date < cutoff:
                        shutil.rmtree(entry_path)
                        deleted.append(entry)
                        logger.info(f"Backup retention: deleted {entry}")
                except ValueError:
                    continue

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "backup_dir": backup_dir,
            "files_copied": copied,
            "old_backups_deleted": deleted,
        }
        logger.info(f"Daily backup complete: {len(copied)} files copied, {len(deleted)} old backups deleted")
        return result

    def run_forecast_monitor(self):
        """日次予測精度モニタリング (STREAM 3-B)
        予測 vs 実績を比較し、精度を data/forecast_accuracy.jsonl に記録。
        モデルドリフト検出: 7日MAE > 全体MAE×1.5 → リトレーニングアラート。
        スケジュール: 毎日 05:00 JST (20:00 UTC)
        """
        try:
            from features.timeseries.forecast_monitor import ForecastMonitor
            monitor = ForecastMonitor()
            result = monitor.evaluate_daily()
            mae = result.get("mae")
            if mae is not None:
                logger.info(f"Forecast monitor: MAE={mae:.3f}, locations={result.get('locations_evaluated', 0)}")
            else:
                logger.info("Forecast monitor: no data to evaluate")
            if result.get("drift_alert"):
                logger.warning(f"Forecast drift: {result['drift_alert'].get('message', '')}")
            return result
        except Exception as e:
            logger.error(f"Forecast monitor failed: {e}")
            return {"error": str(e), "timestamp": datetime.utcnow().isoformat()}

    def _run_anomaly_check(self, country: str, score_dict: dict):
        """スコア異常検知を実行し、アラートを出力"""
        try:
            from features.monitoring.anomaly_detector import (
                ScoreAnomalyDetector, write_alerts_to_file,
            )
            detector = ScoreAnomalyDetector()
            alerts = detector.check_score_anomaly(country, score_dict)

            if not alerts:
                return

            # ログ出力
            if ALERT_OUTPUT in ("log", "both"):
                for alert in alerts:
                    log_fn = logger.critical if alert.severity == "CRITICAL" else logger.warning
                    log_fn(f"[ANOMALY] {alert.message}")

            # ファイル出力
            if ALERT_OUTPUT in ("file", "both"):
                write_alerts_to_file(alerts)

        except Exception as e:
            logger.error(f"Anomaly check failed for {country}: {e}")

    def start(self):
        """スケジューラー開始 (APScheduler)"""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            scheduler = BackgroundScheduler()

            # 6時間ごと: 全50カ国フルスコア
            scheduler.add_job(self.run_full_assessment, 'interval', hours=6, id='full_assessment')

            # 1時間ごと: CRITICAL国のみ
            scheduler.add_job(self.run_critical_update, 'interval', hours=1, id='critical_update')

            # 日次 02:00 JST (17:00 UTC): 制裁リスト更新
            scheduler.add_job(self.run_sanctions_update, 'cron', hour=17, minute=0, id='sanctions_update')

            # 週次 日曜 04:00 JST (19:00 UTC 土曜): 簡易相関チェック
            scheduler.add_job(self.run_correlation_check, 'cron', day_of_week='sat', hour=19, minute=0, id='correlation_check')

            # 週次 日曜 04:00 JST (19:00 UTC 土曜): 30カ国相関監査 (STREAM 2)
            scheduler.add_job(
                self.run_weekly_correlation_audit,
                'cron',
                day_of_week='sat',   # UTC Saturday 19:00 = JST Sunday 04:00
                hour=19,
                minute=0,
                id='weekly_correlation_audit',
            )

            # 毎時: ソース疎通確認
            scheduler.add_job(self.run_source_health_check, 'interval', hours=1, id='source_health')

            # 日次 01:00 JST (16:00 UTC): データベースバックアップ (STREAM 9)
            scheduler.add_job(self.run_daily_backup, 'cron', hour=16, minute=0, id='daily_backup')

            # 日次 05:00 JST (20:00 UTC): 予測精度モニタリング (STREAM 3-B)
            scheduler.add_job(self.run_forecast_monitor, 'cron', hour=20, minute=0, id='forecast_monitor')

            # 日次 06:00 JST (21:00 UTC): 為替レート更新
            scheduler.add_job(self._run_fx_update, 'cron', hour=21, minute=0, id='fx_update')

            # 月次 3日 06:00 JST (21:00 UTC 2日): JNTO訪日統計の更新
            scheduler.add_job(self._run_jnto_update, 'cron', day=3, hour=21, minute=0, id='jnto_update')

            # 週次 日曜 03:00 JST (18:00 UTC 土曜): GPモデル再訓練
            scheduler.add_job(self._run_retrain, 'cron', day_of_week='sat', hour=18, minute=0, id='retrain_gp')

            scheduler.start()
            self.scheduler = scheduler
            logger.info("Risk score scheduler started (%d jobs)", len(scheduler.get_jobs()))
            return scheduler
        except ImportError:
            logger.warning("APScheduler not installed. Scheduler not started.")
            return None

    def start_scheduler(self):
        """start() のエイリアス — self.scheduler を設定"""
        return self.start()

    # ── 追加ジョブ実装 ──

    def _run_fx_update(self):
        """為替レート更新ジョブ"""
        logger.info("為替レート更新開始")
        try:
            from pipeline.tourism.tourism_db import TourismDB
            db = TourismDB()
            db.update_exchange_rates()
            logger.info("為替レート更新完了")
        except Exception as e:
            logger.error(f"為替レート更新エラー: {e}")

    def _run_jnto_update(self):
        """JNTO訪日統計更新ジョブ"""
        logger.info("JNTO統計更新開始")
        try:
            from pipeline.tourism.jnto_client import JNTOClient
            client = JNTOClient()
            client.update_all()
            logger.info("JNTO統計更新完了")
        except Exception as e:
            logger.error(f"JNTO統計更新エラー: {e}")

    def _run_retrain(self):
        """GPモデル再訓練ジョブ"""
        logger.info("GPモデル再訓練開始")
        try:
            import sqlite3, torch, os
            from features.tourism.gaussian_process_model import GaussianProcessInboundModel
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "data", "tourism_stats.db")
            conn = sqlite3.connect(db_path)
            COUNTRIES = {'KR':'KOR','CN':'CHN','TW':'TWN','US':'USA',
                         'AU':'AUS','TH':'THA','HK':'HKG','SG':'SGP'}
            gp = GaussianProcessInboundModel()
            for iso2, iso3 in COUNTRIES.items():
                rows = conn.execute(
                    'SELECT arrivals FROM japan_inbound WHERE source_country=? AND arrivals>0 AND month>0 ORDER BY year, month',
                    (iso3,)).fetchall()
                if rows:
                    gp.fit(iso2, [float(r[0]) for r in rows], n_iterations=300)
                    model = gp._models.get(iso2)
                    if model and hasattr(model, 'state_dict'):
                        out = os.path.join(os.path.dirname(db_path), '..', 'models', 'tourism', f'gp_{iso2}.pt')
                        torch.save({'model_state': model.state_dict()}, out)
            conn.close()
            logger.info("GPモデル再訓練完了")
        except Exception as e:
            logger.error(f"GPモデル再訓練エラー: {e}")


# エイリアス
RiskScheduler = RiskScoreScheduler
