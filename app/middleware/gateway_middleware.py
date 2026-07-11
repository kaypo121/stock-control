import time
import uuid

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import GATEWAY_ALLOWED_IPS


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
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        forwarded_ip = forwarded_for.split(",")[0].strip() if forwarded_for else None
        client_ip = forwarded_ip or (
            request.client.host if request.client else "unknown"
        )
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
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline';"
        )
        return response
