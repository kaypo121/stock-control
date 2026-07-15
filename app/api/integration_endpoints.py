"""
integration_endpoints.py
========================
FastAPI router for the Stock Control Data Integration AI.

Endpoints
─────────
POST   /integration/upload                    Upload & run full 7-step pipeline on a file
POST   /integration/scan                      Scan the raw data folder and run pipeline on all files
GET    /integration/sessions                  List all import sessions
GET    /integration/sessions/{id}             Session detail + stats
DELETE /integration/sessions/{id}             Delete a session and its reports
GET    /integration/sessions/{id}/reports     All reports for a session
GET    /integration/reports/standalone        Run all 5 reports on current DB (no file needed)
GET    /integration/reports/{id}              Single report (full JSON payload)
GET    /integration/inventory                 Live inventory statistics for all products
GET    /integration/health                    Quick health summary
"""

import json
from uuid import uuid4
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_permissions
from app.config import DATA_RAW_DIR, GATEWAY_FILE_SIZE_LIMIT_BYTES
from app.database import get_db
from app.models.integration_models import DataIntegrationSession
from app.schemas.integration_schemas import (
    IntegrationPipelineResult,
    InventoryStats,
    ReportListItem,
    SessionDetailResponse,
    SessionListItem,
)
from app.services.integration_service import (
    DataIntegrationService,
    _compute_inventory_stats,
)
from app.exceptions import IntegrationError

router = APIRouter(prefix="/integration", tags=["Data Integration AI"])


# ── Helper ────────────────────────────────────────────────────────────────────


def _session_to_item(s: DataIntegrationSession) -> SessionListItem:
    failed = (s.invalid_data_count or 0) + len(s.error_records)
    return SessionListItem(
        session_id=s.session_id,
        file_name=s.file_name,
        detected_schema=s.detected_schema,
        status=s.status,
        total_rows=s.total_rows or 0,
        transactions_inserted=s.transactions_inserted or 0,
        records_failed=failed,
        started_at=s.started_at,
        completed_at=s.completed_at,
    )


def _build_upload_path(filename: str) -> Path:
    original_name = Path(filename).name.strip()
    if not original_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid file name is required.",
        )
    return Path(DATA_RAW_DIR) / f"{uuid4().hex}_{original_name}"


# ── Upload & run pipeline ─────────────────────────────────────────────────────


@router.post(
    "/upload",
    response_model=IntegrationPipelineResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions("integration:write"))],
    summary="Upload a file and run the full 7-step integration pipeline",
    description="""
Upload any supported file (CSV, Excel, JSON) containing agricultural data.

The AI will automatically:
1. **Analyse** — structure, missing values, duplicates, invalid data
2. **Clean** — remove dupes, fill nulls, standardise units & formats
3. **Map** — auto-detect schema, map columns to database fields
4. **Integrate** — insert Farmers, Products, Warehouses, Transactions
5. **Process** — compute current/available/damaged stock and turnover rates
6. **Validate** — constraint checks, duplicate IDs, quantity anomalies
7. **Report** — generate 5 reports: Import, Stock Summary, Availability, Health, Low-Stock Alerts

Supported: **.csv · .xlsx · .xls · .json**
    """,
)
async def upload_and_integrate(
    file: UploadFile = File(..., description="Dataset file to import"),
    initiated_by: Optional[str] = Query(
        "API User", description="Name of the person uploading"
    ),
    db: Session = Depends(get_db),
) -> IntegrationPipelineResult:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A file name is required.",
        )
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xls", ".json"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Use .csv, .xlsx, .xls, or .json",
        )
    save_path = _build_upload_path(file.filename)
    size_bytes = 0
    try:
        with save_path.open("wb") as uploaded_file:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > GATEWAY_FILE_SIZE_LIMIT_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            "Uploaded file exceeds the configured size limit of "
                            f"{GATEWAY_FILE_SIZE_LIMIT_BYTES} bytes."
                        ),
                    )
                uploaded_file.write(chunk)
    except Exception:
        save_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    service = DataIntegrationService(db)
    return service.run_pipeline(save_path, initiated_by=initiated_by or "API User")


# ── Scan raw folder ───────────────────────────────────────────────────────────


@router.post(
    "/scan",
    dependencies=[Depends(require_permissions("integration:write"))],
    summary="Scan the raw data folder and run the pipeline on all files",
)
def scan_and_integrate(
    initiated_by: Optional[str] = Query("System Scan"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    service = DataIntegrationService(db)
    results, errors = [], []
    for ext in ("*.csv", "*.xlsx", "*.xls", "*.json"):
        for f in Path(DATA_RAW_DIR).glob(ext):
            try:
                res = service.run_pipeline(f, initiated_by=initiated_by or "System")
                results.append(
                    {
                        "file": f.name,
                        "session_id": res.session_id,
                        "status": res.status,
                        "records_imported": res.records_successfully_imported,
                        "records_failed": res.records_failed,
                    }
                )
            except IntegrationError as e:
                errors.append({"file": f.name, "error": str(e)})
    return {
        "files_processed": len(results),
        "files_failed": len(errors),
        "results": results,
        "errors": errors,
    }


# ── Sessions ──────────────────────────────────────────────────────────────────


@router.get(
    "/sessions",
    response_model=List[SessionListItem],
    dependencies=[Depends(require_permissions("integration:read"))],
    summary="List all import sessions",
)
def list_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[SessionListItem]:
    return [
        _session_to_item(s)
        for s in DataIntegrationService(db).list_sessions(skip=skip, limit=limit)
    ]


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetailResponse,
    dependencies=[Depends(require_permissions("integration:read"))],
    summary="Get full detail for one import session",
)
def get_session(
    session_id: int, db: Session = Depends(get_db)
) -> SessionDetailResponse:
    s = DataIntegrationService(db).get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")
    return SessionDetailResponse.model_validate(s)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permissions("integration:write"))],
    summary="Delete an integration session and its reports",
)
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = (
        db.query(DataIntegrationSession)
        .filter(DataIntegrationSession.session_id == session_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")
    db.delete(s)
    db.commit()


@router.get(
    "/sessions/{session_id}/reports",
    response_model=List[ReportListItem],
    dependencies=[Depends(require_permissions("integration:read"))],
    summary="List all reports generated for a session",
)
def list_session_reports(
    session_id: int, db: Session = Depends(get_db)
) -> List[ReportListItem]:
    reports = DataIntegrationService(db).get_session_reports(session_id)
    if not reports:
        raise HTTPException(
            status_code=404, detail=f"No reports for session {session_id}."
        )
    return [ReportListItem.model_validate(r) for r in reports]


# ── Reports — standalone MUST be declared before /{report_id} ─────────────────


@router.get(
    "/reports/standalone",
    dependencies=[Depends(require_permissions("integration:read"))],
    summary="Generate all 5 live reports from current DB state (no file upload needed)",
    description="""
Generates reports directly from the live database.

Returns:
- **Stock Summary** — totals and per-product inventory
- **Product Availability** — available, out-of-stock, and low-stock lists
- **Inventory Health** — overall health %, status per product
- **Low Stock Alerts** — alerts with recommended reorder actions
    """,
)
def standalone_reports(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return DataIntegrationService(db).get_standalone_reports()


@router.get(
    "/reports/{report_id}",
    dependencies=[Depends(require_permissions("integration:read"))],
    summary="Get the full JSON payload of a specific report",
)
def get_report(report_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    report = DataIntegrationService(db).get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")
    return {
        "report_id": report.report_id,
        "session_id": report.session_id,
        "report_type": report.report_type,
        "report_title": report.report_title,
        "generated_at": report.generated_at.isoformat(),
        "data": json.loads(report.report_data),
    }


# ── Live inventory ────────────────────────────────────────────────────────────


@router.get(
    "/inventory",
    response_model=List[InventoryStats],
    dependencies=[Depends(require_permissions("integration:read"))],
    summary="Live inventory statistics for all products",
)
def live_inventory(
    category: Optional[str] = Query(None, description="Filter by category e.g. Grains"),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="HEALTHY | LOW_STOCK | CRITICAL | OUT_OF_STOCK",
    ),
    db: Session = Depends(get_db),
) -> List[InventoryStats]:
    stats = _compute_inventory_stats(db)
    if category:
        stats = [s for s in stats if s.category.lower() == category.lower()]
    if status_filter:
        stats = [s for s in stats if s.status == status_filter.upper()]
    return stats


@router.get(
    "/health",
    dependencies=[Depends(require_permissions("integration:read"))],
    summary="Quick inventory health snapshot",
)
def health_snapshot(db: Session = Depends(get_db)) -> Dict[str, Any]:
    import datetime

    stats = _compute_inventory_stats(db)
    counts: Dict[str, int] = {
        "HEALTHY": 0,
        "LOW_STOCK": 0,
        "CRITICAL": 0,
        "OUT_OF_STOCK": 0,
    }
    for s in stats:
        counts[s.status] = counts.get(s.status, 0) + 1
    total = max(len(stats), 1)
    return {
        "total_products": len(stats),
        "healthy": counts["HEALTHY"],
        "low_stock": counts["LOW_STOCK"],
        "critical": counts["CRITICAL"],
        "out_of_stock": counts["OUT_OF_STOCK"],
        "overall_health_pct": round(counts["HEALTHY"] / total * 100, 1),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
