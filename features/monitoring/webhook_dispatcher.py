"""Webhook Notification System
Dispatches event notifications to registered webhook URLs with HMAC-SHA256 signatures.

Events:
  - CRITICAL_SCORE   : A location's overall risk score reached CRITICAL level (>=80)
  - SANCTIONS_HIT    : A new sanctions match was detected
  - SCORE_JUMP       : A location's score changed by >= threshold points

Usage:
    manager = WebhookManager()
    manager.register(url="https://example.com/hook", events=["CRITICAL_SCORE"],
                     locations=["JP","CN"], secret="my-secret")
    manager.dispatch("CRITICAL_SCORE", {"location": "CN", "score": 92})
"""
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import requests

logger = logging.getLogger(__name__)

VALID_EVENTS = {"CRITICAL_SCORE", "SANCTIONS_HIT", "SCORE_JUMP"}
WEBHOOKS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "webhooks.json",
)
DELIVERY_TIMEOUT_SECONDS = 10
MAX_RETRIES = 2

_executor = ThreadPoolExecutor(max_workers=4)


class WebhookManager:
    """Manages webhook registrations and event dispatch."""

    def __init__(self, webhooks_path: Optional[str] = None):
        self.webhooks_path = webhooks_path or WEBHOOKS_FILE
        self._webhooks: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        """Load registrations from disk."""
        if os.path.exists(self.webhooks_path):
            try:
                with open(self.webhooks_path, "r") as f:
                    self._webhooks = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._webhooks = []
        else:
            self._webhooks = []

    def _save(self):
        """Persist registrations to disk."""
        os.makedirs(os.path.dirname(self.webhooks_path), exist_ok=True)
        with open(self.webhooks_path, "w") as f:
            json.dump(self._webhooks, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Registration API
    # ------------------------------------------------------------------

    def register(
        self,
        url: str,
        events: list[str],
        locations: Optional[list[str]] = None,
        secret: Optional[str] = None,
    ) -> dict:
        """Register a new webhook endpoint.

        Args:
            url: The HTTPS callback URL.
            events: List of event types to subscribe to.
            locations: Optional list of location filters (empty = all).
            secret: Shared secret used for HMAC-SHA256 signing.

        Returns:
            The created webhook record including its ``webhook_id``.
        """
        # Validate events
        invalid = set(events) - VALID_EVENTS
        if invalid:
            raise ValueError(f"Invalid event types: {invalid}. Valid: {VALID_EVENTS}")

        webhook = {
            "webhook_id": str(uuid.uuid4()),
            "url": url,
            "events": events,
            "locations": locations or [],
            "secret": secret,
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_triggered": None,
            "delivery_count": 0,
            "failure_count": 0,
        }
        self._webhooks.append(webhook)
        self._save()
        logger.info("Webhook registered: id=%s url=%s events=%s", webhook["webhook_id"], url, events)
        return webhook

    def unregister(self, webhook_id: str) -> bool:
        """Remove a webhook by its ID. Returns True if found and removed."""
        before = len(self._webhooks)
        self._webhooks = [w for w in self._webhooks if w["webhook_id"] != webhook_id]
        removed = len(self._webhooks) < before
        if removed:
            self._save()
            logger.info("Webhook removed: %s", webhook_id)
        return removed

    def list_webhooks(self) -> list[dict]:
        """Return all registered webhooks (secrets are masked)."""
        safe = []
        for w in self._webhooks:
            entry = dict(w)
            if entry.get("secret"):
                entry["secret"] = "****"
            safe.append(entry)
        return safe

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, event_type: str, payload: dict):
        """Dispatch an event to all matching registered webhooks.

        Matching rules:
          1. Webhook must subscribe to ``event_type``.
          2. If webhook has ``locations`` filter, the payload must contain a
             ``location`` key whose value is in the filter list.

        Delivery is performed in background threads so the caller is not blocked.
        """
        if event_type not in VALID_EVENTS:
            logger.warning("Ignoring unknown event type: %s", event_type)
            return

        payload_location = (payload.get("location") or "").upper()

        for webhook in self._webhooks:
            if not webhook.get("active", True):
                continue
            if event_type not in webhook.get("events", []):
                continue
            # Location filter
            wh_locations = [loc.upper() for loc in webhook.get("locations", [])]
            if wh_locations and payload_location and payload_location not in wh_locations:
                continue

            # Fire-and-forget delivery in background
            _executor.submit(self._deliver, webhook, event_type, payload)

    def _deliver(self, webhook: dict, event_type: str, payload: dict):
        """POST the event payload to the webhook URL with HMAC signature."""
        body = json.dumps({
            "event": event_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "webhook_id": webhook["webhook_id"],
        }, ensure_ascii=False, default=str)

        headers = {
            "Content-Type": "application/json",
            "X-SCRI-Event": event_type,
            "X-SCRI-Delivery": str(uuid.uuid4()),
        }

        # HMAC-SHA256 signature
        secret = webhook.get("secret")
        if secret:
            signature = hmac.new(
                secret.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            headers["X-SCRI-Signature"] = f"sha256={signature}"

        url = webhook["url"]
        success = False

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    url,
                    data=body,
                    headers=headers,
                    timeout=DELIVERY_TIMEOUT_SECONDS,
                )
                if resp.status_code < 300:
                    success = True
                    break
                logger.warning(
                    "Webhook %s returned %s on attempt %d",
                    webhook["webhook_id"], resp.status_code, attempt,
                )
            except requests.RequestException as exc:
                logger.warning(
                    "Webhook %s delivery failed (attempt %d): %s",
                    webhook["webhook_id"], attempt, exc,
                )
            # Backoff before retry
            if attempt < MAX_RETRIES:
                time.sleep(1 * attempt)

        # Update stats (best-effort, no lock required for JSONL-style usage)
        webhook["last_triggered"] = datetime.now(timezone.utc).isoformat()
        webhook["delivery_count"] = webhook.get("delivery_count", 0) + 1
        if not success:
            webhook["failure_count"] = webhook.get("failure_count", 0) + 1
            logger.error("Webhook %s: delivery failed after %d attempts", webhook["webhook_id"], MAX_RETRIES)
        self._save()
