import sys
import time
from pathlib import Path

# Add project root to sys.path to allow absolute imports in Vercel/serverless environments
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.database import engine, Base
from app.api.endpoints import router as stock_router
from app.api.gateway_endpoints import router as gateway_router
from app.api.quality_endpoints import router as quality_router
from app.api.integration_endpoints import router as integration_router
from app.config import APP_VERSION, GATEWAY_ALLOWED_ORIGINS, GATEWAY_CORS_ALLOW_CREDENTIALS
from app.middleware.gateway_middleware import IPAllowListMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.schemas.gateway_schemas import GatewayResponseEnvelope
from app.services.gateway_security import GatewayAPIError
from app.services.gateway_service import gateway_orchestrator
from app.database import SessionLocal

# Import all models so SQLAlchemy registers them before create_all
import app.models.stock_models      # noqa: F401
import app.models.quality_models    # noqa: F401
import app.models.integration_models # noqa: F401
import app.models.gateway_models    # noqa: F401

app = FastAPI(
    title="Agriculture Stock Control, Quality Assessment & Data Integration AI",
    description="""
**Complete Agricultural Management System for Ghana**

### 📦 Stock Control Module  `/stock/`
- Record stock movements (in / out / adjustments / transfers)
- Real-time balance tracking per farmer and warehouse
- Low-stock alerts and reorder level management
- CSV/Excel data import pipeline
- 3-month demand forecasting

### 🔬 Quality Assessment Module  `/quality/`
Pre-purchase quality evaluation for all agricultural products:
- **Crops / Fruits / Vegetables** — Freshness, ripeness, damage %, shelf-life
- **Livestock** — BCS, health, mobility, vaccination
- **Poultry** — Weight, feather condition, egg production
- **Fish** — Freshness, eye clarity, gill condition, odor, flesh quality

Every assessment returns Quality Score · Market Readiness · GHS Value · Grade · Buy/Caution/Reject

### 🤖 Data Integration AI  `/integration/`
Full 7-step automated data pipeline:
1. **Analyse** — Structure, missing values, duplicates, invalid data detection
2. **Clean** — Dedup, null-fill, unit standardisation, format correction
3. **Map** — Auto-detect schema, map to database fields
4. **Integrate** — Insert Farmers, Products, Warehouses, Transactions, Quality Assessments
5. **Process** — Current stock, available stock, turnover rates, reorder levels
6. **Validate** — Constraint checks, duplicate IDs, warehouse assignment, quantity anomalies
7. **Report** — Data Import · Stock Summary · Product Availability · Inventory Health · Low-Stock Alerts

Supports: **CSV · Excel · JSON** — including Ghana MoFA production datasets
    """,
    version=APP_VERSION,
)


@app.on_event("startup")
def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)

def _processing_time_ms(request: Request) -> float:
    started_at = getattr(request.state, "started_at", None)
    if started_at is None:
        return 0.0
    return round((time.perf_counter() - started_at) * 1000.0, 2)


def _error_response(request: Request, status_code: int, code: str, message: str, detail=None) -> JSONResponse:
    body = GatewayResponseEnvelope(
        status="error",
        success=False,
        message=message,
        data=None,
        errors=[{"code": code, "message": message, "detail": detail}],
        warnings=[],
        metadata={"path": request.url.path},
        processingTime=_processing_time_ms(request),
        traceId=getattr(request.state, "trace_id", request.headers.get("X-Trace-Id", "")),
        requestId=getattr(request.state, "request_id", request.headers.get("X-Request-Id", "")),
        version="v1",
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(by_alias=True, mode="json"))


@app.exception_handler(GatewayAPIError)
async def handle_gateway_api_error(request: Request, exc: GatewayAPIError):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "GATEWAY_ERROR", "message": str(exc.detail)}
    code = detail.get("code", "GATEWAY_ERROR")
    message = detail.get("message", "Gateway request failed.")
    log_db = SessionLocal()
    try:
        if request.url.path.startswith("/v1"):
            gateway_orchestrator.log_failure(
                db=log_db,
                request_id=getattr(request.state, "request_id", request.headers.get("X-Request-Id", "")),
                trace_id=getattr(request.state, "trace_id", request.headers.get("X-Trace-Id", "")),
                path=request.url.path,
                http_method=request.method,
                caller_ip=request.client.host if request.client else "unknown",
                request_body=None,
                status_code_value=exc.status_code,
                error_code=code,
                message=message,
                identity=None,
            )
    except Exception:
        pass
    finally:
        log_db.close()
    return _error_response(request, exc.status_code, code, message, detail.get("detail"))


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(request: Request, exc: RequestValidationError):
    errors = [
        {
            "code": "VALIDATION_ERROR",
            "message": item.get("msg", "Invalid request value."),
            "field": ".".join(str(part) for part in item.get("loc", [])),
            "detail": item.get("input"),
        }
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
        traceId=getattr(request.state, "trace_id", request.headers.get("X-Trace-Id", "")),
        requestId=getattr(request.state, "request_id", request.headers.get("X-Request-Id", "")),
        version="v1",
    )
    return JSONResponse(status_code=422, content=body.model_dump(by_alias=True, mode="json"))


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
    return _error_response(request, exc.status_code, detail.get("code", "HTTP_ERROR"), detail.get("message", "Request failed."), detail.get("detail"))


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception):
    return _error_response(request, 500, "INTERNAL_SERVER_ERROR", "An unexpected gateway error occurred.", str(exc))


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
