"""Response Standardization Middleware
Wraps all API responses in a consistent envelope format:

Success:
  {"success": true, "data": {...}, "meta": {"version": "0.7.0", ...}, "warnings": []}

Error:
  {"success": false, "error": {"code": "...", "message": "..."}, "meta": {...}}
"""
import json
import time
from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse, StreamingResponse

API_VERSION = "0.7.0"

# Paths to exclude from response wrapping (static files, docs, etc.)
EXCLUDED_PREFIXES = (
    "/static",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
)


class ResponseFormatterMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that wraps all JSON responses in a standardised envelope."""

    async def dispatch(self, request: Request, call_next):
        # Skip non-API paths
        path = request.url.path
        if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            return await call_next(request)

        # Measure processing time
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            # Unhandled exception -> 500 error envelope
            processing_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return JSONResponse(
                status_code=500,
                content=_error_envelope(
                    code="INTERNAL_SERVER_ERROR",
                    message=str(exc),
                    processing_ms=processing_ms,
                ),
            )

        processing_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Only wrap JSON responses
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # Read body from the original response
        body = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                body += chunk.encode("utf-8")
            else:
                body += chunk

        try:
            original_data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Not valid JSON -> pass through unchanged
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        status_code = response.status_code

        # Build the envelope
        if 200 <= status_code < 400:
            envelope = _success_envelope(
                data=original_data,
                processing_ms=processing_ms,
            )
        else:
            # Error responses
            error_message = (
                original_data.get("detail")
                or original_data.get("error")
                or original_data.get("message")
                or str(original_data)
            )
            error_code = _status_to_code(status_code)
            envelope = _error_envelope(
                code=error_code,
                message=error_message,
                processing_ms=processing_ms,
            )

        new_body = json.dumps(envelope, ensure_ascii=False, default=str)
        return Response(
            content=new_body,
            status_code=status_code,
            media_type="application/json",
        )


def _build_meta(processing_ms: float) -> dict:
    """Build the meta block included in every response."""
    return {
        "version": API_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "processing_time_ms": processing_ms,
        "cache_hit": False,
    }


def _success_envelope(data: dict, processing_ms: float) -> dict:
    """Wrap successful data in the standard envelope."""
    return {
        "success": True,
        "data": data,
        "meta": _build_meta(processing_ms),
        "warnings": [],
    }


def _error_envelope(code: str, message: str, processing_ms: float) -> dict:
    """Wrap an error in the standard envelope."""
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
        "meta": _build_meta(processing_ms),
    }


def _status_to_code(status_code: int) -> str:
    """Map HTTP status codes to human-readable error codes."""
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        408: "REQUEST_TIMEOUT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }
    return mapping.get(status_code, f"HTTP_{status_code}")
