"""Alert Dispatcher - routes alerts to configured channels"""
import os
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def load_alert_config() -> dict:
    """Load alert configuration from YAML or return defaults"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "config", "alert_config.yaml")
    try:
        import yaml
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    except (ImportError, FileNotFoundError):
        # Default config if yaml not available or file not found
        return {
            "alert_channels": {"log": True, "file": True, "webhook": False},
            "alert_thresholds": {
                "score_jump": 20,
                "dimension_jump": 30,
                "new_sanctions_hit": True,
                "source_failure_count": 3,
            },
            "file_settings": {
                "output_dir": "data/alerts",
                "format": "jsonl",
            },
        }


class AlertDispatcher:
    """Routes alerts to configured channels"""

    def __init__(self):
        self.config = load_alert_config()
        self.channels = self.config.get("alert_channels", {})
        self.thresholds = self.config.get("alert_thresholds", {})

    def dispatch(self, alert: dict):
        """Send alert to all enabled channels"""
        alert["dispatched_at"] = datetime.utcnow().isoformat()

        if self.channels.get("log", True):
            self._send_to_log(alert)

        if self.channels.get("file", True):
            self._send_to_file(alert)

        if self.channels.get("webhook", False):
            self._send_to_webhook(alert)

    def check_and_alert_score_change(self, country: str, old_score: int, new_score: int):
        """Check if score change exceeds threshold and dispatch alert"""
        threshold = self.thresholds.get("score_jump", 20)
        delta = abs(new_score - old_score)
        if delta >= threshold:
            direction = "increased" if new_score > old_score else "decreased"
            severity = "critical" if delta >= 30 else "high"
            self.dispatch({
                "type": "score_change",
                "severity": severity,
                "country": country,
                "old_score": old_score,
                "new_score": new_score,
                "delta": delta,
                "direction": direction,
                "message": f"{country} risk score {direction} by {delta} points ({old_score} → {new_score})",
            })

    def check_and_alert_sanctions_hit(self, entity_name: str, source: str, match_score: float):
        """Alert on new sanctions match"""
        if self.thresholds.get("new_sanctions_hit", True):
            self.dispatch({
                "type": "sanctions_match",
                "severity": "critical",
                "entity": entity_name,
                "source": source,
                "match_score": match_score,
                "message": f"Sanctions match: {entity_name} on {source} (score: {match_score})",
            })

    def check_and_alert_source_failure(self, source_name: str, consecutive_failures: int):
        """Alert on data source failures"""
        threshold = self.thresholds.get("source_failure_count", 3)
        if consecutive_failures >= threshold:
            self.dispatch({
                "type": "source_failure",
                "severity": "high" if consecutive_failures >= 5 else "medium",
                "source": source_name,
                "consecutive_failures": consecutive_failures,
                "message": f"Data source {source_name} failed {consecutive_failures} consecutive times",
            })

    def _send_to_log(self, alert: dict):
        """Log the alert"""
        severity = alert.get("severity", "info")
        message = alert.get("message", str(alert))
        log_fn = {
            "critical": logger.critical,
            "high": logger.warning,
            "medium": logger.info,
            "low": logger.debug,
        }.get(severity, logger.info)
        log_fn(f"[ALERT:{severity.upper()}] {message}")

    def _send_to_file(self, alert: dict):
        """Write alert to JSONL file"""
        settings = self.config.get("file_settings", {})
        output_dir = settings.get("output_dir", "data/alerts")
        os.makedirs(output_dir, exist_ok=True)

        today = datetime.utcnow().strftime("%Y-%m-%d")
        filepath = os.path.join(output_dir, f"{today}.jsonl")

        with open(filepath, "a") as f:
            f.write(json.dumps(alert, ensure_ascii=False) + "\n")

    def _send_to_webhook(self, alert: dict):
        """Placeholder for webhook delivery (Slack/Teams)"""
        # Future implementation
        pass
