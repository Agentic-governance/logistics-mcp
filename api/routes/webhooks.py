"""Webhook Management Endpoints

POST   /api/v1/webhooks/register     - Register a new webhook
GET    /api/v1/webhooks/list          - List all registered webhooks
DELETE /api/v1/webhooks/{webhook_id}  - Unregister a webhook
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from features.monitoring.webhook_dispatcher import WebhookManager, VALID_EVENTS

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

# Singleton manager instance
_manager: Optional[WebhookManager] = None


def _get_manager() -> WebhookManager:
    global _manager
    if _manager is None:
        _manager = WebhookManager()
    return _manager


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class WebhookRegisterRequest(BaseModel):
    url: str = Field(..., description="Callback URL (should be HTTPS in production)")
    events: list[str] = Field(
        ...,
        description=f"Event types to subscribe to. Valid: {sorted(VALID_EVENTS)}",
    )
    locations: list[str] = Field(
        default_factory=list,
        description="Location filter (empty = all locations)",
    )
    secret: Optional[str] = Field(
        default=None,
        description="Shared secret for HMAC-SHA256 signature verification",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register")
def register_webhook(req: WebhookRegisterRequest):
    """Register a new webhook to receive event notifications."""
    manager = _get_manager()
    try:
        webhook = manager.register(
            url=req.url,
            events=req.events,
            locations=req.locations,
            secret=req.secret,
        )
        # Mask secret in response
        safe = dict(webhook)
        if safe.get("secret"):
            safe["secret"] = "****"
        return {"status": "registered", "webhook": safe}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/list")
def list_webhooks():
    """List all registered webhooks (secrets are masked)."""
    manager = _get_manager()
    webhooks = manager.list_webhooks()
    return {"count": len(webhooks), "webhooks": webhooks}


@router.delete("/{webhook_id}")
def delete_webhook(webhook_id: str):
    """Unregister a webhook by its ID."""
    manager = _get_manager()
    removed = manager.unregister(webhook_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} not found")
    return {"status": "deleted", "webhook_id": webhook_id}
