import time
import uuid

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import (
    GATEWAY_ALLOWED_IPS,
    GATEWAY_TRUST_PROXY_HEADERS,
    GATEWAY_TRUSTED_PROXIES,
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
        correlation_id = request.headers.get("X-Correlation-Id") or request_id
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request.state.correlation_id = correlation_id
        started = time.perf_counter()
        request.state.started_at = started
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Processing-Time-Ms"] = (
            f"{(time.perf_counter() - started) * 1000.0:.2f}"
        )
        return response


class IPAllowListMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not GATEWAY_ALLOWED_IPS or not request.url.path.startswith("/v1"):
            return await call_next(request)
        direct_client_ip = request.client.host if request.client else "unknown"
        forwarded_ip = None
        if GATEWAY_TRUST_PROXY_HEADERS:
            if not GATEWAY_TRUSTED_PROXIES or direct_client_ip in GATEWAY_TRUSTED_PROXIES:
                forwarded_for = request.headers.get("X-Forwarded-For", "")
                if forwarded_for:
                    forwarded_ip = forwarded_for.split(",")[0].strip()
        client_ip = forwarded_ip or direct_client_ip
        if client_ip in GATEWAY_ALLOWED_IPS:
            return await call_next(request)
        return JSONResponse(
            status_code=403,
            content={
                "status": "forbidden",
                "success": False,
                "message": "The caller IP address is not allowed to access the gateway.",
                "data": None,
                "errors": [
                    {
                        "code": "IP_NOT_ALLOWED",
                        "message": "The caller IP address is not allow-listed.",
                    }
                ],
                "warnings": [],
                "metadata": {"ipAddress": client_ip},
                "processingTime": 0.0,
                "traceId": getattr(request.state, "trace_id", ""),
                "requestId": getattr(request.state, "request_id", ""),
                "timestamp": "",
                "version": "v1",
            },
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        return response
