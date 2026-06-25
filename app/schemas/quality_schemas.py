"""
quality_schemas.py
==================
Pydantic v2 schemas for the Quality Assessment module.
Input schemas accept inspector-provided field data.
Output schemas return the full structured assessment result (JSON-ready for DB storage).
"""

from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.quality_models import (
    ProductCategory, GradeClassification, RiskLevel,
    PurchaseRecommendation, RipenessLevel, HealthStatus, FreshnessLevel
)


# ═══════════════════════════════════════════════════════════════════════════════
#  SUB-SCHEMAS: Physical attribute inputs per category
# ═══════════════════════════════════════════════════════════════════════════════

class ProduceAttributesInput(BaseModel):
    """Physical attributes for Crops, Fruits, and Vegetables."""
    weight_kg:                  Optional[float] = Field(None, ge=0, description="Weight in kilograms")
    length_cm:                  Optional[float] = Field(None, ge=0, description="Length in centimetres")
    width_cm:                   Optional[float] = Field(None, ge=0, description="Width in centimetres")
    height_cm:                  Optional[float] = Field(None, ge=0, description="Height in centimetres")
    diameter_cm:                Optional[float] = Field(None, ge=0, description="Diameter in centimetres (if applicable)")
    color_quality:              Optional[str]   = Field(None, description="Color description (e.g. 'Bright Red', 'Pale Yellow')")
    freshness_score:            Optional[float] = Field(None, ge=0, le=10, description="Freshness score out of 10")
    ripeness_level:             Optional[RipenessLevel] = Field(None)
    moisture_content_pct:       Optional[float] = Field(None, ge=0, le=100, description="Moisture content %")
    visible_damage_pct:         Optional[float] = Field(None, ge=0, le=100, description="% of surface with visible damage")
    pest_damage_pct:            Optional[float] = Field(None, ge=0, le=100, description="% showing pest damage")
    disease_symptoms:           Optional[str]   = Field(None, description="Describe disease symptoms or 'None'")
    estimated_shelf_life_days:  Optional[int]   = Field(None, ge=0, description="Estimated shelf life in days")


class LivestockAttributesInput(BaseModel):
    """Physical and health attributes for Livestock."""
    species:                Optional[str]   = Field(None, description="Species (e.g. Cattle, Goat, Sheep, Pig)")
    breed:                  Optional[str]   = Field(None, description="Breed name")
    age_months:             Optional[float] = Field(None, ge=0, description="Age in months")
    weight_kg:              Optional[float] = Field(None, ge=0, description="Live weight in kg")
    height_cm:              Optional[float] = Field(None, ge=0, description="Height at withers in cm")
    length_cm:              Optional[float] = Field(None, ge=0, description="Body length in cm")
    body_condition_score:   Optional[float] = Field(None, ge=1, le=5, description="BCS (1=emaciated, 5=obese)")
    health_status:          Optional[HealthStatus]  = Field(None)
    vaccination_status:     Optional[str]   = Field(None, description="e.g. 'Up to date', 'Partial', 'None'")
    disease_indicators:     Optional[str]   = Field(None, description="Describe or 'None observed'")
    mobility_assessment:    Optional[str]   = Field(None, description="e.g. 'Normal', 'Slight limp', 'Lame'")
    feeding_condition:      Optional[str]   = Field(None, description="e.g. 'Well-fed', 'Thin', 'Emaciated'")
    reproductive_status:    Optional[str]   = Field(None, description="e.g. 'Pregnant', 'Lactating', 'Dry', 'N/A'")


class PoultryAttributesInput(BaseModel):
    """Physical and health attributes for Poultry."""
    species:                    Optional[str]   = Field(None, description="Species (e.g. Chicken, Turkey, Duck, Guinea Fowl)")
    breed:                      Optional[str]   = Field(None, description="Breed (e.g. Broiler, Layer, Kuroiler)")
    weight_kg:                  Optional[float] = Field(None, ge=0, description="Weight in kg")
    age_weeks:                  Optional[float] = Field(None, ge=0, description="Age in weeks")
    health_condition:           Optional[HealthStatus] = Field(None)
    egg_production_rate_pct:    Optional[float] = Field(None, ge=0, le=100, description="Egg production rate % (layers only)")
    feather_condition:          Optional[str]   = Field(None, description="e.g. 'Full, Glossy', 'Patchy', 'Bare patches'")
    disease_signs:              Optional[str]   = Field(None, description="Describe or 'None observed'")


class FishAttributesInput(BaseModel):
    """Physical and quality attributes for Fish."""
    species:            Optional[str]   = Field(None, description="Species (e.g. Tilapia, Catfish, Tuna, Herring)")
    weight_kg:          Optional[float] = Field(None, ge=0, description="Weight in kg")
    length_cm:          Optional[float] = Field(None, ge=0, description="Length in cm")
    freshness_level:    Optional[FreshnessLevel] = Field(None)
    eye_clarity:        Optional[str]   = Field(None, description="e.g. 'Clear, Bright', 'Slightly Cloudy', 'Sunken'")
    gill_condition:     Optional[str]   = Field(None, description="e.g. 'Bright Red', 'Pink', 'Brown/Grey'")
    odor_assessment:    Optional[str]   = Field(None, description="e.g. 'Fresh Sea Smell', 'Mild Odor', 'Foul'")
    flesh_quality:      Optional[str]   = Field(None, description="e.g. 'Firm, Elastic', 'Soft', 'Mushy'")


# ═══════════════════════════════════════════════════════════════════════════════
#  ASSESSMENT REQUEST SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

class QualityAssessmentRequest(BaseModel):
    """
    Full input payload for a quality assessment.
    Provide exactly one of: produce_attributes, livestock_attributes,
    poultry_attributes, or fish_attributes — matching the declared category.
    """

    # General details
    product_name:       str             = Field(...,  description="Name of the product being assessed")
    category:           ProductCategory = Field(...,  description="Product category")
    batch_number:       str             = Field(...,  description="Batch / lot identifier")
    farmer_supplier:    Optional[str]   = Field(None, description="Farmer or supplier name")
    farmer_id:          Optional[int]   = Field(None, description="Linked farmer ID (optional)")
    warehouse_id:       Optional[int]   = Field(None, description="Warehouse where item is located")
    assessed_by:        Optional[str]   = Field(None, description="Name of inspector/assessor")
    assessment_date:    Optional[datetime] = Field(default_factory=datetime.utcnow)
    notes:              Optional[str]   = Field(None, description="Additional observations")

    # Category-specific attributes (provide only the matching one)
    produce_attributes:   Optional[ProduceAttributesInput]   = None
    livestock_attributes: Optional[LivestockAttributesInput] = None
    poultry_attributes:   Optional[PoultryAttributesInput]   = None
    fish_attributes:      Optional[FishAttributesInput]      = None

    @model_validator(mode="after")
    def check_attributes_match_category(self) -> "QualityAssessmentRequest":
        cat = self.category
        if cat in (ProductCategory.CROP, ProductCategory.FRUIT, ProductCategory.VEGETABLE):
            if self.produce_attributes is None:
                raise ValueError(
                    f"'produce_attributes' is required for category '{cat.value}'"
                )
        elif cat == ProductCategory.LIVESTOCK:
            if self.livestock_attributes is None:
                raise ValueError("'livestock_attributes' is required for category 'Livestock'")
        elif cat == ProductCategory.POULTRY:
            if self.poultry_attributes is None:
                raise ValueError("'poultry_attributes' is required for category 'Poultry'")
        elif cat == ProductCategory.FISH:
            if self.fish_attributes is None:
                raise ValueError("'fish_attributes' is required for category 'Fish'")
        return self


# ═══════════════════════════════════════════════════════════════════════════════
#  RESPONSE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class ProduceDetailResponse(BaseModel):
    weight_kg:                  Optional[float]
    length_cm:                  Optional[float]
    width_cm:                   Optional[float]
    height_cm:                  Optional[float]
    diameter_cm:                Optional[float]
    color_quality:              Optional[str]
    freshness_score:            Optional[float]
    ripeness_level:             Optional[str]
    moisture_content_pct:       Optional[float]
    visible_damage_pct:         Optional[float]
    pest_damage_pct:            Optional[float]
    disease_symptoms:           Optional[str]
    estimated_shelf_life_days:  Optional[int]

    class Config:
        from_attributes = True


class LivestockDetailResponse(BaseModel):
    species:                Optional[str]
    breed:                  Optional[str]
    age_months:             Optional[float]
    weight_kg:              Optional[float]
    height_cm:              Optional[float]
    length_cm:              Optional[float]
    body_condition_score:   Optional[float]
    health_status:          Optional[str]
    vaccination_status:     Optional[str]
    disease_indicators:     Optional[str]
    mobility_assessment:    Optional[str]
    feeding_condition:      Optional[str]
    reproductive_status:    Optional[str]

    class Config:
        from_attributes = True


class PoultryDetailResponse(BaseModel):
    species:                    Optional[str]
    breed:                      Optional[str]
    weight_kg:                  Optional[float]
    age_weeks:                  Optional[float]
    health_condition:           Optional[str]
    egg_production_rate_pct:    Optional[float]
    feather_condition:          Optional[str]
    disease_signs:              Optional[str]

    class Config:
        from_attributes = True


class FishDetailResponse(BaseModel):
    species:            Optional[str]
    weight_kg:          Optional[float]
    length_cm:          Optional[float]
    freshness_level:    Optional[str]
    eye_clarity:        Optional[str]
    gill_condition:     Optional[str]
    odor_assessment:    Optional[str]
    flesh_quality:      Optional[str]

    class Config:
        from_attributes = True


class QualityScoring(BaseModel):
    """The computed scoring block."""
    quality_score:              float = Field(..., description="Overall quality score 0–100")
    market_readiness_score:     float = Field(..., description="Market readiness score 0–100")
    estimated_market_value_ghs: Optional[float] = Field(None, description="Estimated value in Ghana Cedis")
    risk_level:                 str   = Field(..., description="Low / Medium / High")
    grade_classification:       str   = Field(..., description="Premium / Grade A / Grade B / Grade C / Reject")


class PurchaseDecision(BaseModel):
    """The purchase recommendation block."""
    recommendation: str = Field(..., description="Buy / Buy with Caution / Do Not Buy")
    reason:         str = Field(..., description="Detailed explanation for the recommendation")


class QualityAssessmentResponse(BaseModel):
    """
    Full structured response — suitable for direct database storage and API return.
    """
    assessment_id:      int
    batch_number:       str
    product_name:       str
    category:           str
    farmer_supplier:    Optional[str]
    farmer_id:          Optional[int]
    warehouse_id:       Optional[int]
    assessed_by:        Optional[str]
    assessment_date:    datetime
    notes:              Optional[str]

    # Scored outputs
    scoring:            QualityScoring
    purchase_decision:  PurchaseDecision

    # Detail block (only one will be non-null)
    produce_detail:     Optional[ProduceDetailResponse]   = None
    livestock_detail:   Optional[LivestockDetailResponse] = None
    poultry_detail:     Optional[PoultryDetailResponse]   = None
    fish_detail:        Optional[FishDetailResponse]      = None

    created_at:         datetime
    updated_at:         datetime

    class Config:
        from_attributes = True


class AssessmentListItem(BaseModel):
    """Lightweight summary for list views."""
    assessment_id:          int
    batch_number:           str
    product_name:           str
    category:               str
    farmer_supplier:        Optional[str]
    assessment_date:        datetime
    quality_score:          float
    grade_classification:   str
    purchase_recommendation: str
    risk_level:             str

    class Config:
        from_attributes = True
