"""
quality_endpoints.py
====================
FastAPI router for the Agricultural Quality Assessment module.

Endpoints
─────────
POST   /quality/assess             — Submit a new quality assessment
GET    /quality/assessments        — List assessments (filterable)
GET    /quality/assessments/{id}   — Get one assessment by ID
DELETE /quality/assessments/{id}   — Delete an assessment
GET    /quality/summary            — Aggregated stats by crop/category
GET    /quality/categories         — Enum reference list
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import require_permissions
from app.database import get_db
from app.models.quality_models import (
    FreshnessLevel,
    GradeClassification,
    HealthStatus,
    ProductCategory,
    PurchaseRecommendation,
    QualityAssessment,
    RipenessLevel,
    RiskLevel,
)
from app.schemas.quality_schemas import (
    AssessmentListItem,
    FishDetailResponse,
    LivestockDetailResponse,
    PoultryDetailResponse,
    ProduceDetailResponse,
    PurchaseDecision,
    QualityAssessmentRequest,
    QualityAssessmentResponse,
    QualityScoring,
)
from app.services.quality_service import QualityAssessmentService

router = APIRouter(prefix="/quality", tags=["Quality Assessment"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_response(a: QualityAssessment) -> QualityAssessmentResponse:
    """Convert ORM record to full Pydantic response."""
    scoring = QualityScoring(
        quality_score=a.quality_score,
        market_readiness_score=a.market_readiness_score,
        estimated_market_value_ghs=a.estimated_market_value,
        risk_level=a.risk_level,
        grade_classification=a.grade_classification,
    )
    decision = PurchaseDecision(
        recommendation=a.purchase_recommendation,
        reason=a.recommendation_reason,
    )

    produce_resp = (
        ProduceDetailResponse.model_validate(a.produce_detail)
        if a.produce_detail
        else None
    )
    livestock_resp = (
        LivestockDetailResponse.model_validate(a.livestock_detail)
        if a.livestock_detail
        else None
    )
    poultry_resp = (
        PoultryDetailResponse.model_validate(a.poultry_detail)
        if a.poultry_detail
        else None
    )
    fish_resp = (
        FishDetailResponse.model_validate(a.fish_detail) if a.fish_detail else None
    )

    return QualityAssessmentResponse(
        assessment_id=a.assessment_id,
        batch_number=a.batch_number,
        product_name=a.product_name,
        category=a.category,
        farmer_supplier=a.farmer_supplier,
        farmer_id=a.farmer_id,
        warehouse_id=a.warehouse_id,
        assessed_by=a.assessed_by,
        assessment_date=a.assessment_date,
        notes=a.notes,
        scoring=scoring,
        purchase_decision=decision,
        produce_detail=produce_resp,
        livestock_detail=livestock_resp,
        poultry_detail=poultry_resp,
        fish_detail=fish_resp,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/assess",
    response_model=QualityAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions("quality:write"))],
    summary="Submit a new quality assessment",
    description="""
Runs a full quality assessment on any agricultural product.

**Supported categories:** Crop · Fruit · Vegetable · Livestock · Poultry · Fish

Provide exactly the attribute block that matches your category:
- `produce_attributes`   → for Crop, Fruit, Vegetable
- `livestock_attributes` → for Livestock
- `poultry_attributes`   → for Poultry
- `fish_attributes`      → for Fish

Returns a fully scored JSON record with:
- Quality Score (0–100)
- Market Readiness Score
- Estimated Market Value (GHS)
- Risk Level
- Grade Classification
- Purchase Recommendation + Reason
    """,
)
def submit_assessment(
    payload: QualityAssessmentRequest,
    db: Session = Depends(get_db),
) -> QualityAssessmentResponse:
    service = QualityAssessmentService(db)
    try:
        assessment = service.assess(payload)
        return _build_response(assessment)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.get(
    "/assessments",
    response_model=List[AssessmentListItem],
    dependencies=[Depends(require_permissions("quality:read"))],
    summary="List quality assessments",
)
def list_assessments(
    product_name: Optional[str] = Query(
        None, description="Filter by product name (partial match)"
    ),
    category: Optional[str] = Query(
        None, description="Filter by category (e.g. Crop, Fish)"
    ),
    farmer_id: Optional[int] = Query(None, description="Filter by farmer ID"),
    recommendation: Optional[str] = Query(
        None,
        description="Filter by recommendation: Buy | Buy with Caution | Do Not Buy",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[AssessmentListItem]:
    service = QualityAssessmentService(db)
    records = service.list_assessments(
        product_name=product_name,
        category=category,
        farmer_id=farmer_id,
        recommendation=recommendation,
        skip=skip,
        limit=limit,
    )
    return [
        AssessmentListItem(
            assessment_id=r.assessment_id,
            batch_number=r.batch_number,
            product_name=r.product_name,
            category=r.category,
            farmer_supplier=r.farmer_supplier,
            assessment_date=r.assessment_date,
            quality_score=r.quality_score,
            grade_classification=r.grade_classification,
            purchase_recommendation=r.purchase_recommendation,
            risk_level=r.risk_level,
        )
        for r in records
    ]


@router.get(
    "/assessments/{assessment_id}",
    response_model=QualityAssessmentResponse,
    dependencies=[Depends(require_permissions("quality:read"))],
    summary="Get a single assessment by ID",
)
def get_assessment(
    assessment_id: int,
    db: Session = Depends(get_db),
) -> QualityAssessmentResponse:
    service = QualityAssessmentService(db)
    record = service.get_assessment(assessment_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment with ID {assessment_id} not found.",
        )
    return _build_response(record)


@router.delete(
    "/assessments/{assessment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permissions("quality:write"))],
    summary="Delete an assessment record",
)
def delete_assessment(
    assessment_id: int,
    db: Session = Depends(get_db),
):
    service = QualityAssessmentService(db)
    deleted = service.delete_assessment(assessment_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment with ID {assessment_id} not found.",
        )


@router.get(
    "/summary",
    response_model=List[Dict[str, Any]],
    dependencies=[Depends(require_permissions("quality:read"))],
    summary="Aggregated quality statistics by product",
)
def quality_summary(
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Returns aggregated quality stats per product:
    - Average quality score
    - Average market readiness
    - Grade distribution
    - Recommendation breakdown
    - Total assessments
    """
    q = db.query(
        QualityAssessment.product_name,
        QualityAssessment.category,
        func.count(QualityAssessment.assessment_id).label("total"),
        func.avg(QualityAssessment.quality_score).label("avg_quality"),
        func.avg(QualityAssessment.market_readiness_score).label("avg_readiness"),
        func.avg(QualityAssessment.estimated_market_value).label("avg_value"),
    )
    if category:
        q = q.filter(QualityAssessment.category == category)
    rows = (
        q.group_by(
            QualityAssessment.product_name,
            QualityAssessment.category,
        )
        .order_by(func.avg(QualityAssessment.quality_score).desc())
        .all()
    )

    results = []
    for row in rows:
        # Grade and recommendation breakdown for this product
        grades = (
            db.query(
                QualityAssessment.grade_classification,
                func.count(QualityAssessment.assessment_id),
            )
            .filter(QualityAssessment.product_name == row.product_name)
            .group_by(QualityAssessment.grade_classification)
            .all()
        )

        recs = (
            db.query(
                QualityAssessment.purchase_recommendation,
                func.count(QualityAssessment.assessment_id),
            )
            .filter(QualityAssessment.product_name == row.product_name)
            .group_by(QualityAssessment.purchase_recommendation)
            .all()
        )

        results.append(
            {
                "product_name": row.product_name,
                "category": row.category,
                "total_assessments": row.total,
                "average_quality_score": round(row.avg_quality or 0, 2),
                "average_market_readiness": round(row.avg_readiness or 0, 2),
                "average_market_value_ghs": round(row.avg_value or 0, 2),
                "grade_distribution": {g: c for g, c in grades},
                "recommendation_summary": {r: c for r, c in recs},
            }
        )

    return results


@router.get(
    "/categories",
    dependencies=[Depends(require_permissions("quality:read"))],
    summary="Reference: valid categories, grades, risk levels, and recommendations",
)
def get_reference_enums() -> Dict[str, List[str]]:
    """Returns all valid enum values for use in frontend dropdowns."""
    return {
        "categories": [e.value for e in ProductCategory],
        "grade_classifications": [e.value for e in GradeClassification],
        "risk_levels": [e.value for e in RiskLevel],
        "recommendations": [e.value for e in PurchaseRecommendation],
        "ripeness_levels": [e.value for e in RipenessLevel],
        "health_statuses": [e.value for e in HealthStatus],
        "freshness_levels": [e.value for e in FreshnessLevel],
    }
