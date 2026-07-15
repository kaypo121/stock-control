import logging
import time
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.endpoints import router as stock_router
from app.api.gateway_endpoints import router as gateway_router
from app.api.integration_endpoints import router as integration_router
from app.api.quality_endpoints import router as quality_router
from app.config import (
    APP_VERSION,
    GATEWAY_ALLOWED_ORIGINS,
    GATEWAY_CORS_ALLOW_CREDENTIALS,
    IS_PRODUCTION,
)
from app.database import Base
import app.database as database
from app.middleware.gateway_middleware import (
    IPAllowListMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.schemas.gateway_schemas import GatewayResponseEnvelope, GatewayErrorDetail, GatewayWarning
from app.services.gateway_security import GatewayAPIError
from app.exceptions import AppError
from app.services.gateway_service import gateway_orchestrator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan_context(_: FastAPI):
    Base.metadata.create_all(bind=database.engine)
    db = database.SessionLocal()
    try:
        gateway_orchestrator.bootstrap(db)
        yield
    finally:
        db.close()


# Import models before create_all so SQLAlchemy knows every mapped class.
for module_name in [
    "app.models.gateway_models",
    "app.models.integration_models",
    "app.models.quality_models",
    "app.models.stock_models",
]:
    import_module(module_name)

app = FastAPI(
    title=("Agriculture Stock Control, Quality Assessment & Data " "Integration AI"),
    description="""
**Complete Agricultural Management System for Ghana**

### 📦 Stock Control Module `/stock/`
- Record stock movements (in / out / adjustments,
  transfers)
- Real-time balance tracking per farmer and warehouse
- Low-stock alerts and reorder level management
- CSV/Excel data import pipeline
- 3-month demand forecasting

### 🔬 Quality Assessment Module `/quality/`
Pre-purchase quality evaluation for all agricultural products:
- **Crops / Fruits / Vegetables** — Freshness, ripeness, damage percentage,
  shelf-life
- **Livestock** — Body condition, health, mobility, vaccination
- **Poultry** — Weight, feather condition, egg production
- **Fish** — Freshness, eye clarity, gill condition, odor, flesh quality

Every assessment returns quality score, market readiness, estimated value,
grade, and recommendation.

### 🤖 Data Integration AI `/integration/`
Full 7-step pipeline:
1. **Analyse** — Structure, missing values, duplicates, invalid data
2. **Clean** — Deduplicate, fill nulls, standardize units and formats
3. **Map** — Detect schema, map fields to DB model
4. **Integrate** — Insert Farmers, Products, Warehouses, Transactions,
   Quality Assessments
5. **Process** — Compute current stock, available stock, turnover,
   reorder status
6. **Validate** — Check constraints, duplicates, warehouse assignments,
   quantity anomalies
7. **Report** — Import, stock summary, availability, health, and low-stock
   alert reports

Supports: CSV, Excel, and JSON file ingestion.
    """,
    version=APP_VERSION,
    lifespan=lifespan_context,
)


def _processing_time_ms(request: Request) -> float:
    started_at = getattr(request.state, "started_at", None)
    if started_at is None:
        return 0.0
    return round((time.perf_counter() - started_at) * 1000.0, 2)


def _error_response(
    request: Request, status_code: int, code: str, message: str, detail=None
) -> JSONResponse:
    body = GatewayResponseEnvelope(
        status="error",
        success=False,
        message=message,
        data=None,
        errors=[GatewayErrorDetail(code=code, message=message, detail=detail)],
        warnings=[],
        metadata={"path": request.url.path},
        processingTime=_processing_time_ms(request),
        traceId=getattr(
            request.state, "trace_id", request.headers.get("X-Trace-Id", "")
        ),
        requestId=getattr(
            request.state,
            "request_id",
            request.headers.get("X-Request-Id", ""),
        ),
        version="v1",
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(by_alias=True, mode="json"),
    )


@app.exception_handler(GatewayAPIError)
async def handle_gateway_api_error(request: Request, exc: GatewayAPIError):
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": "GATEWAY_ERROR", "message": str(exc.detail)}
    )
    code = detail.get("code", "GATEWAY_ERROR")
    message = detail.get("message", "Gateway request failed.")
    log_db = database.SessionLocal()
    try:
        if request.url.path.startswith("/v1"):
            gateway_orchestrator.log_failure(
                db=log_db,
                request_id=getattr(
                    request.state,
                    "request_id",
                    request.headers.get("X-Request-Id", ""),
                ),
                trace_id=getattr(
                    request.state,
                    "trace_id",
                    request.headers.get("X-Trace-Id", ""),
                ),
                path=request.url.path,
                http_method=request.method,
                caller_ip=request.client.host if request.client else "unknown",
                request_body=None,
                status_code_value=exc.status_code,
                error_code=code,
                message=message,
                identity=None,
            )
    except (RuntimeError, ValueError, AttributeError, TypeError):
        pass
    finally:
        log_db.close()
    return _error_response(
        request, exc.status_code, code, message, detail.get("detail")
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
):
    errors = [
        GatewayErrorDetail(
            code="VALIDATION_ERROR",
            message=item.get("msg", "Invalid request value."),
            field=".".join(str(part) for part in item.get("loc", [])),
        )
        for item in exc.errors()
    ]
    body = GatewayResponseEnvelope(
        status="error",
        success=False,
        message="Request validation failed.",
        data=None,
        errors=errors,
        warnings=[],
        metadata={"path": request.url.path},
        processingTime=_processing_time_ms(request),
        traceId=getattr(
            request.state, "trace_id", request.headers.get("X-Trace-Id", "")
        ),
        requestId=getattr(
            request.state,
            "request_id",
            request.headers.get("X-Request-Id", ""),
        ),
        version="v1",
    )
    return JSONResponse(
        status_code=422, content=body.model_dump(by_alias=True, mode="json")
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": "HTTP_ERROR", "message": str(exc.detail)}
    )
    return _error_response(
        request,
        exc.status_code,
        detail.get("code", "HTTP_ERROR"),
        detail.get("message", "Request failed."),
        detail.get("detail"),
    )


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception):
    logger.exception("Unhandled application exception on %s", request.url.path, exc_info=exc)
    # Convert known AppError subclasses into structured gateway errors
    if isinstance(exc, AppError):
        code = getattr(exc, "code", "APP_ERROR") or "APP_ERROR"
        return _error_response(
            request,
            500,
            code,
            str(exc),
            getattr(exc, "details", None) if not IS_PRODUCTION else None,
        )
    return _error_response(
        request,
        500,
        "INTERNAL_SERVER_ERROR",
        "An unexpected gateway error occurred.",
        None,
    )


# Enable CORS for frontend and gateway integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=GATEWAY_ALLOWED_ORIGINS or ["*"],
    allow_credentials=GATEWAY_CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(IPAllowListMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


# Serve the dashboard at root — redirect "/" to the dashboard HTML
@app.get("/", include_in_schema=False)
def root():
    static_path = Path(__file__).parent.parent / "static" / "index.html"
    return FileResponse(str(static_path))


@app.get("/health", include_in_schema=False)
def health_check():
    with database.engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "up",
        "environment": "production" if IS_PRODUCTION else "development",
        "version": APP_VERSION,
    }


@app.get("/favicon.png", include_in_schema=False)
def favicon():
    favicon_path = Path(__file__).parent.parent / "static" / "favicon.png"
    return FileResponse(str(favicon_path))


# Mount static files (CSS/JS if ever needed as separate files)
static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Register routes
app.include_router(stock_router)
app.include_router(quality_router)
app.include_router(integration_router)
app.include_router(gateway_router)
