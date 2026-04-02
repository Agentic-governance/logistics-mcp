"""Input Sanitization Middleware"""
import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# Dangerous patterns to reject
DANGEROUS_PATTERNS = [
    re.compile(r'[;\'"\\].*(?:DROP|DELETE|INSERT|UPDATE|ALTER|CREATE)\s', re.IGNORECASE),
    re.compile(r'<script', re.IGNORECASE),
    re.compile(r'javascript:', re.IGNORECASE),
    re.compile(r'\.\./\.\./'),  # Path traversal
]

MAX_PARAM_LENGTH = 500  # Maximum length for any single parameter


class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """Sanitize and validate all incoming request parameters"""

    async def dispatch(self, request: Request, call_next):
        # Check query parameters
        for key, value in request.query_params.items():
            if len(value) > MAX_PARAM_LENGTH:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Parameter '{key}' exceeds maximum length of {MAX_PARAM_LENGTH}"},
                )
            for pattern in DANGEROUS_PATTERNS:
                if pattern.search(value):
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"Parameter '{key}' contains invalid characters"},
                    )

        # Check path parameters
        path = request.url.path
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(path):
                return JSONResponse(
                    status_code=400,
                    content={"error": "Request path contains invalid characters"},
                )

        response = await call_next(request)
        return response
