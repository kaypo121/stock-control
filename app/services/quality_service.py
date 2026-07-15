"""
quality_service.py
==================
Core engine for the Agricultural Quality Assessment module.

Scoring Logic Overview
──────────────────────
Each category has a bespoke weighted scoring formula:

PRODUCE (Crops / Fruits / Vegetables)
  freshness_score      30 %
  ripeness_level       20 %
  visible_damage_pct   20 %  (inverted — lower is better)
  pest_damage_pct      15 %  (inverted)
  moisture_content     10 %  (optimal range matters)
  disease_symptoms      5 %  (binary penalty)

LIVESTOCK
  body_condition_score 30 %
  health_status        25 %
  mobility_assessment  20 %
  vaccination_status   15 %
  feeding_condition    10 %

POULTRY
  health_condition     35 %
  feather_condition    25 %
  weight_adequacy      20 %
  egg_production_rate  20 % (layers) / age_weight_ratio (broilers)

FISH
  freshness_level      35 %
  eye_clarity          20 %
  gill_condition       20 %
  odor_assessment      15 %
  flesh_quality        10 %

Grade thresholds: Premium ≥ 85 | Grade A ≥ 70 | Grade B ≥ 55 | Grade C ≥ 40 | Reject < 40
Risk thresholds:  Low ≥ 70 | Medium ≥ 45 | High < 45
Buy thresholds:   Buy ≥ 70 | Caution ≥ 45 | Do Not Buy < 45
"""

from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.quality_models import (
    FishQualityDetail,
    FreshnessLevel,
    GradeClassification,
    HealthStatus,
    LivestockQualityDetail,
    PoultryQualityDetail,
    ProduceQualityDetail,
    PurchaseRecommendation,
    QualityAssessment,
    RipenessLevel,
    RiskLevel,
)
from app.schemas.quality_schemas import (
    FishAttributesInput,
    LivestockAttributesInput,
    PoultryAttributesInput,
    ProduceAttributesInput,
    QualityAssessmentRequest,
)

# ── Reference price table (GHS per unit) ──────────────────────────────────────
# Used for estimated market value calculation.  Update as needed.
MARKET_PRICE_GHS = {
    # Produce (per kg unless noted)
    "tomato": 8.50,
    "maize": 3.20,
    "rice": 6.50,
    "yam": 4.80,
    "cassava": 2.50,
    "plantain": 3.80,
    "pepper": 12.00,
    "onion": 9.00,
    "garden egg": 10.00,
    "mango": 5.50,
    "pineapple": 4.00,
    "orange": 2.50,
    "watermelon": 3.00,
    "pawpaw": 4.50,
    "banana": 3.50,
    "cocoa": 18.00,
    "groundnut": 7.00,
    "soyabean": 5.50,
    "cowpea": 8.00,
    "sorghum": 4.00,
    "millet": 4.50,
    # Livestock (per head)
    "cattle": 3500.0,
    "cow": 3500.0,
    "bull": 4500.0,
    "goat": 550.0,
    "sheep": 600.0,
    "pig": 800.0,
    # Poultry (per bird)
    "chicken": 45.0,
    "broiler": 55.0,
    "layer": 40.0,
    "turkey": 180.0,
    "duck": 65.0,
    "guinea fowl": 50.0,
    # Fish (per kg)
    "tilapia": 25.0,
    "catfish": 30.0,
    "tuna": 40.0,
    "herring": 15.0,
    "salmon": 55.0,
    "mackerel": 20.0,
    "default": 10.0,
}


def _get_base_price(product_name: str, category: str) -> float:
    name_lower = product_name.lower()
    for key, price in MARKET_PRICE_GHS.items():
        if key in name_lower:
            return price
    # Fallback by category
    cat_defaults = {
        "Livestock": 800.0,
        "Poultry": 50.0,
        "Fish": 25.0,
    }
    return cat_defaults.get(category, MARKET_PRICE_GHS["default"])


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _grade(score: float) -> str:
    if score >= 85:
        return GradeClassification.PREMIUM
    if score >= 70:
        return GradeClassification.GRADE_A
    if score >= 55:
        return GradeClassification.GRADE_B
    if score >= 40:
        return GradeClassification.GRADE_C
    return GradeClassification.REJECT


def _risk(score: float) -> str:
    if score >= 70:
        return RiskLevel.LOW
    if score >= 45:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


def _grade_display(grade: str | GradeClassification) -> str:
    if isinstance(grade, GradeClassification):
        return grade.value
    return grade


def _recommendation(
    score: float, grade: str | GradeClassification
) -> Tuple[str, str]:
    """Returns (recommendation, reason)."""
    grade_display = _grade_display(grade)
    reject_grades = {GradeClassification.GRADE_C.value, GradeClassification.REJECT.value}

    if score >= 70 and grade_display not in reject_grades:
        rec = PurchaseRecommendation.BUY
        reason = (
            f"Product achieved a quality score of {score:.1f}/100 and is graded {grade_display}. "
            "Physical condition, freshness, and health indicators are all within acceptable standards. "
            "Recommended for immediate purchase and stock-in."
        )
    elif score >= 45:
        rec = PurchaseRecommendation.BUY_WITH_CAUTION
        reason = (
            f"Product scored {score:.1f}/100 (grade: {grade_display}). "
            "Some quality concerns were detected — consider negotiating a lower price, "
            "inspecting the batch more thoroughly, or fast-tracking sales to minimise further deterioration."
        )
    else:
        rec = PurchaseRecommendation.DO_NOT_BUY
        reason = (
            f"Product scored only {score:.1f}/100 (grade: {grade_display}). "
            "Significant quality defects, health risks, or spoilage indicators were found. "
            "Purchasing this batch is not recommended."
        )
    return rec, reason


# ── Produce Scoring ───────────────────────────────────────────────────────────

_RIPENESS_SCORES = {
    RipenessLevel.UNRIPE: 50.0,
    RipenessLevel.NEARLY_RIPE: 80.0,
    RipenessLevel.RIPE: 100.0,
    RipenessLevel.OVERRIPE: 30.0,
}

_RIPENESS_SHELF_DAYS = {
    RipenessLevel.UNRIPE: 14,
    RipenessLevel.NEARLY_RIPE: 7,
    RipenessLevel.RIPE: 3,
    RipenessLevel.OVERRIPE: 1,
}


def score_produce(
    attrs: ProduceAttributesInput, product_name: str, category: str
) -> dict:
    """Score produce and return a dict of computed values."""

    # Freshness (30 pts)
    freshness_raw = attrs.freshness_score if attrs.freshness_score is not None else 7.0
    freshness_pts = (freshness_raw / 10.0) * 30.0

    # Ripeness (20 pts)
    ripeness_lvl = attrs.ripeness_level or RipenessLevel.RIPE
    ripeness_pts = (_RIPENESS_SCORES.get(ripeness_lvl, 80.0) / 100.0) * 20.0

    # Visible damage (20 pts, inverted)
    vis_dmg = attrs.visible_damage_pct if attrs.visible_damage_pct is not None else 5.0
    vis_dmg_pts = max(0.0, (1.0 - vis_dmg / 100.0)) * 20.0

    # Pest damage (15 pts, inverted)
    pest_dmg = attrs.pest_damage_pct if attrs.pest_damage_pct is not None else 0.0
    pest_dmg_pts = max(0.0, (1.0 - pest_dmg / 100.0)) * 15.0

    # Moisture (10 pts) — optimal band depends on produce type
    # Grains: 12–14%; Vegetables: 85–95%; Fruits: 75–90%; default 70–95%
    moisture = attrs.moisture_content_pct
    moisture_pts = 10.0  # default full if not provided
    if moisture is not None:
        name_lower = product_name.lower()
        if any(
            g in name_lower
            for g in ["maize", "rice", "sorghum", "millet", "grain", "cereal"]
        ):
            optimal_lo, optimal_hi = 10.0, 15.0
        elif category in ("Vegetable",):
            optimal_lo, optimal_hi = 80.0, 95.0
        else:
            optimal_lo, optimal_hi = 70.0, 92.0
        if optimal_lo <= moisture <= optimal_hi:
            moisture_pts = 10.0
        else:
            deviation = min(abs(moisture - optimal_lo), abs(moisture - optimal_hi))
            moisture_pts = max(0.0, 10.0 - (deviation / 5.0) * 10.0)

    # Disease symptoms (5 pts) — binary penalty
    disease_raw = (attrs.disease_symptoms or "").strip().lower()
    disease_pts = 0.0 if disease_raw not in ("", "none", "none observed", "no") else 5.0

    total = _clamp(
        freshness_pts
        + ripeness_pts
        + vis_dmg_pts
        + pest_dmg_pts
        + moisture_pts
        + disease_pts
    )

    # Shelf life estimate
    shelf_life = attrs.estimated_shelf_life_days
    if shelf_life is None:
        shelf_life = _RIPENESS_SHELF_DAYS.get(ripeness_lvl, 5)
        # Adjust based on damage
        damage_factor = 1.0 - (vis_dmg + pest_dmg) / 200.0
        shelf_life = max(0, int(shelf_life * damage_factor))

    # Market value
    base_price = _get_base_price(product_name, category)
    weight = attrs.weight_kg or 1.0
    value_multiplier = total / 100.0
    market_value = round(base_price * weight * value_multiplier, 2)

    return {
        "quality_score": round(total, 2),
        "market_value": market_value,
        "shelf_life_days": shelf_life,
    }


# ── Livestock Scoring ─────────────────────────────────────────────────────────

_HEALTH_STATUS_SCORES = {
    HealthStatus.EXCELLENT: 100.0,
    HealthStatus.GOOD: 80.0,
    HealthStatus.FAIR: 55.0,
    HealthStatus.POOR: 30.0,
    HealthStatus.CRITICAL: 10.0,
}

_VACC_SCORES = {
    "up to date": 100.0,
    "partial": 60.0,
    "none": 20.0,
    "unknown": 40.0,
}

_MOBILITY_SCORES = {
    "normal": 100.0,
    "slight limp": 60.0,
    "lame": 20.0,
    "immobile": 5.0,
}

_FEEDING_SCORES = {
    "well-fed": 100.0,
    "good": 90.0,
    "adequate": 70.0,
    "thin": 40.0,
    "emaciated": 10.0,
}


def score_livestock(attrs: LivestockAttributesInput, product_name: str) -> dict:
    # BCS (30 pts) — optimal BCS is 3.0–3.5 for most species
    bcs = attrs.body_condition_score if attrs.body_condition_score is not None else 3.0
    bcs_pts = max(0.0, (1.0 - abs(bcs - 3.0) / 2.0)) * 30.0

    # Health status (25 pts)
    hs = attrs.health_status or HealthStatus.GOOD
    health_pts = (_HEALTH_STATUS_SCORES.get(hs, 80.0) / 100.0) * 25.0

    # Mobility (20 pts)
    mob_raw = (attrs.mobility_assessment or "normal").strip().lower()
    mob_score = 100.0
    for key, val in _MOBILITY_SCORES.items():
        if key in mob_raw:
            mob_score = val
            break
    mobility_pts = (mob_score / 100.0) * 20.0

    # Vaccination (15 pts)
    vacc_raw = (attrs.vaccination_status or "unknown").strip().lower()
    vacc_score = 40.0
    for key, val in _VACC_SCORES.items():
        if key in vacc_raw:
            vacc_score = val
            break
    vacc_pts = (vacc_score / 100.0) * 15.0

    # Feeding condition (10 pts)
    feed_raw = (attrs.feeding_condition or "well-fed").strip().lower()
    feed_score = 80.0
    for key, val in _FEEDING_SCORES.items():
        if key in feed_raw:
            feed_score = val
            break
    feed_pts = (feed_score / 100.0) * 10.0

    # Disease indicator penalty
    disease_raw = (attrs.disease_indicators or "").strip().lower()
    if disease_raw not in ("", "none", "none observed", "no"):
        # Apply 15-point penalty for observable disease signs
        total = _clamp(bcs_pts + health_pts + mobility_pts + vacc_pts + feed_pts - 15.0)
    else:
        total = _clamp(bcs_pts + health_pts + mobility_pts + vacc_pts + feed_pts)

    base_price = _get_base_price(product_name, "Livestock")
    value_multiplier = total / 100.0
    market_value = round(base_price * value_multiplier, 2)

    return {"quality_score": round(total, 2), "market_value": market_value}


# ── Poultry Scoring ───────────────────────────────────────────────────────────

_FEATHER_SCORES = {
    "full, glossy": 100.0,
    "full": 90.0,
    "glossy": 90.0,
    "slight patchy": 65.0,
    "patchy": 45.0,
    "bare patches": 25.0,
    "bare": 15.0,
}


def score_poultry(attrs: PoultryAttributesInput, product_name: str) -> dict:
    # Health condition (35 pts)
    hc = attrs.health_condition or HealthStatus.GOOD
    health_pts = (_HEALTH_STATUS_SCORES.get(hc, 80.0) / 100.0) * 35.0

    # Feather condition (25 pts)
    feather_raw = (attrs.feather_condition or "full, glossy").strip().lower()
    feather_score = 80.0
    for key, val in _FEATHER_SCORES.items():
        if key in feather_raw:
            feather_score = val
            break
    feather_pts = (feather_score / 100.0) * 25.0

    # Egg production (20 pts for layers) / weight adequacy (20 pts for broilers)
    is_layer = "layer" in (attrs.breed or "").lower() or "layer" in product_name.lower()
    if is_layer and attrs.egg_production_rate_pct is not None:
        prod_pts = (attrs.egg_production_rate_pct / 100.0) * 20.0
    else:
        # Weight adequacy: broilers target 2.0–2.5 kg at 6 weeks
        weight = attrs.weight_kg or 1.8
        age_wks = attrs.age_weeks or 6.0
        expected_weight = 0.35 * age_wks  # rough linear target
        weight_ratio = min(weight / max(expected_weight, 0.1), 1.0)
        prod_pts = weight_ratio * 20.0

    # Age-weight ratio (20 pts)
    weight = attrs.weight_kg or 1.8
    age_wks = attrs.age_weeks or 6.0
    expected = 0.35 * age_wks
    ratio = min(weight / max(expected, 0.1), 1.3)  # cap at 130%
    age_wt_pts = min(ratio, 1.0) * 20.0

    # Disease penalty
    disease_raw = (attrs.disease_signs or "").strip().lower()
    disease_pen = (
        15.0 if disease_raw not in ("", "none", "none observed", "no") else 0.0
    )

    total = _clamp(health_pts + feather_pts + prod_pts + age_wt_pts - disease_pen)

    base_price = _get_base_price(product_name, "Poultry")
    market_value = round(base_price * (total / 100.0), 2)

    return {"quality_score": round(total, 2), "market_value": market_value}


# ── Fish Scoring ──────────────────────────────────────────────────────────────

_FRESHNESS_SCORES = {
    FreshnessLevel.VERY_FRESH: 100.0,
    FreshnessLevel.FRESH: 80.0,
    FreshnessLevel.ACCEPTABLE: 55.0,
    FreshnessLevel.STALE: 25.0,
    FreshnessLevel.SPOILED: 0.0,
}

_EYE_SCORES = {
    "clear, bright": 100.0,
    "clear": 90.0,
    "bright": 90.0,
    "slightly cloudy": 55.0,
    "cloudy": 35.0,
    "sunken": 10.0,
}

_GILL_SCORES = {
    "bright red": 100.0,
    "red": 90.0,
    "pink": 70.0,
    "pale pink": 50.0,
    "brown": 20.0,
    "grey": 15.0,
    "grey/brown": 10.0,
}

_ODOR_SCORES = {
    "fresh sea smell": 100.0,
    "fresh": 90.0,
    "mild odor": 60.0,
    "mild": 60.0,
    "slightly off": 30.0,
    "off": 15.0,
    "foul": 0.0,
}

_FLESH_SCORES = {
    "firm, elastic": 100.0,
    "firm": 90.0,
    "elastic": 90.0,
    "slightly soft": 60.0,
    "soft": 35.0,
    "mushy": 5.0,
}


def _lookup_score(raw: str, score_map: dict, default: float = 70.0) -> float:
    raw_lower = raw.strip().lower()
    for key, val in score_map.items():
        if key in raw_lower:
            return val
    return default


def score_fish(attrs: FishAttributesInput, product_name: str) -> dict:
    # Freshness (35 pts)
    fl = attrs.freshness_level or FreshnessLevel.FRESH
    fresh_pts = (_FRESHNESS_SCORES.get(fl, 80.0) / 100.0) * 35.0

    # Eye clarity (20 pts)
    eye_score = _lookup_score(attrs.eye_clarity or "clear, bright", _EYE_SCORES)
    eye_pts = (eye_score / 100.0) * 20.0

    # Gill condition (20 pts)
    gill_score = _lookup_score(attrs.gill_condition or "bright red", _GILL_SCORES)
    gill_pts = (gill_score / 100.0) * 20.0

    # Odor (15 pts)
    odor_score = _lookup_score(attrs.odor_assessment or "fresh sea smell", _ODOR_SCORES)
    odor_pts = (odor_score / 100.0) * 15.0

    # Flesh quality (10 pts)
    flesh_score = _lookup_score(attrs.flesh_quality or "firm, elastic", _FLESH_SCORES)
    flesh_pts = (flesh_score / 100.0) * 10.0

    total = _clamp(fresh_pts + eye_pts + gill_pts + odor_pts + flesh_pts)

    weight = attrs.weight_kg or 1.0
    base_price = _get_base_price(product_name, "Fish")
    market_value = round(base_price * weight * (total / 100.0), 2)

    return {"quality_score": round(total, 2), "market_value": market_value}


# ── Market Readiness Score ────────────────────────────────────────────────────


def market_readiness(quality_score: float, category: str, attrs) -> float:
    """
    Market readiness considers quality score + category-specific
    shelf-life / immediate-sale urgency factors.
    """
    base = quality_score

    if category in ("Crop", "Fruit", "Vegetable") and isinstance(
        attrs, ProduceAttributesInput
    ):
        rl = attrs.ripeness_level or RipenessLevel.RIPE
        if rl == RipenessLevel.OVERRIPE:
            base *= 0.60
        elif rl == RipenessLevel.RIPE:
            base *= 1.00
        elif rl == RipenessLevel.NEARLY_RIPE:
            base *= 0.90
        else:  # unripe
            base *= 0.70

    elif category == "Fish" and isinstance(attrs, FishAttributesInput):
        fl = attrs.freshness_level or FreshnessLevel.FRESH
        if fl == FreshnessLevel.SPOILED:
            base = 0.0
        elif fl == FreshnessLevel.STALE:
            base *= 0.50
        elif fl == FreshnessLevel.VERY_FRESH:
            base *= 1.05  # slight bonus

    return round(_clamp(base), 2)


# ── Main Service Class ────────────────────────────────────────────────────────


class QualityAssessmentService:

    def __init__(self, db: Session):
        self.db = db

    def assess(self, request: QualityAssessmentRequest) -> QualityAssessment:
        """
        Runs the full assessment pipeline:
          1. Score the product
          2. Derive grade, risk, and recommendation
          3. Persist to DB
          4. Return the ORM assessment object
        """
        cat = request.category.value
        name = request.product_name

        # ── 1. Score ──────────────────────────────────────────────────────────
        if cat in ("Crop", "Fruit", "Vegetable"):
            if request.produce_attributes is None:
                raise ValueError(
                    "produce_attributes is required for Crop, Fruit, and Vegetable categories."
                )
            result = score_produce(request.produce_attributes, name, cat)
        elif cat == "Livestock":
            if request.livestock_attributes is None:
                raise ValueError(
                    "livestock_attributes is required for Livestock category."
                )
            result = score_livestock(request.livestock_attributes, name)
        elif cat == "Poultry":
            if request.poultry_attributes is None:
                raise ValueError(
                    "poultry_attributes is required for Poultry category."
                )
            result = score_poultry(request.poultry_attributes, name)
        elif cat == "Fish":
            if request.fish_attributes is None:
                raise ValueError("fish_attributes is required for Fish category.")
            result = score_fish(request.fish_attributes, name)
        else:
            # Generic fallback
            result = {"quality_score": 60.0, "market_value": 0.0}

        quality_score = result["quality_score"]
        market_value = result.get("market_value", 0.0)

        # ── 2. Market readiness ───────────────────────────────────────────────
        active_attrs = (
            request.produce_attributes
            or request.livestock_attributes
            or request.poultry_attributes
            or request.fish_attributes
        )
        mr_score = market_readiness(quality_score, cat, active_attrs)

        # ── 3. Derive grade, risk, recommendation ─────────────────────────────
        grade = _grade(quality_score)
        risk = _risk(quality_score)
        rec, reason = _recommendation(quality_score, grade)

        # ── 4. Build master record ────────────────────────────────────────────
        assessment = QualityAssessment(
            batch_number=request.batch_number,
            product_name=name,
            category=cat,
            farmer_id=request.farmer_id,
            farmer_supplier=request.farmer_supplier,
            warehouse_id=request.warehouse_id,
            assessed_by=request.assessed_by,
            assessment_date=request.assessment_date or datetime.now(timezone.utc),
            quality_score=quality_score,
            market_readiness_score=mr_score,
            estimated_market_value=market_value,
            risk_level=risk,
            grade_classification=grade,
            purchase_recommendation=rec,
            recommendation_reason=reason,
            notes=request.notes,
        )
        self.db.add(assessment)
        self.db.flush()  # get assessment_id

        # ── 5. Persist category detail ────────────────────────────────────────
        if cat in ("Crop", "Fruit", "Vegetable"):
            a = request.produce_attributes
            if a is None:
                raise ValueError(
                    "produce_attributes is required for Crop, Fruit, and Vegetable categories."
                )
            detail = ProduceQualityDetail(
                assessment_id=assessment.assessment_id,
                weight_kg=a.weight_kg,
                length_cm=a.length_cm,
                width_cm=a.width_cm,
                height_cm=a.height_cm,
                diameter_cm=a.diameter_cm,
                color_quality=a.color_quality,
                freshness_score=a.freshness_score,
                ripeness_level=(a.ripeness_level.value if a.ripeness_level else None),
                moisture_content_pct=a.moisture_content_pct,
                visible_damage_pct=a.visible_damage_pct,
                pest_damage_pct=a.pest_damage_pct,
                disease_symptoms=a.disease_symptoms,
                estimated_shelf_life_days=result.get(
                    "shelf_life_days", a.estimated_shelf_life_days
                ),
            )
            self.db.add(detail)

        elif cat == "Livestock":
            a = request.livestock_attributes
            if a is None:
                raise ValueError(
                    "livestock_attributes is required for Livestock category."
                )
            detail = LivestockQualityDetail(
                assessment_id=assessment.assessment_id,
                species=a.species,
                breed=a.breed,
                age_months=a.age_months,
                weight_kg=a.weight_kg,
                height_cm=a.height_cm,
                length_cm=a.length_cm,
                body_condition_score=a.body_condition_score,
                health_status=(a.health_status.value if a.health_status else None),
                vaccination_status=a.vaccination_status,
                disease_indicators=a.disease_indicators,
                mobility_assessment=a.mobility_assessment,
                feeding_condition=a.feeding_condition,
                reproductive_status=a.reproductive_status,
            )
            self.db.add(detail)

        elif cat == "Poultry":
            a = request.poultry_attributes
            if a is None:
                raise ValueError(
                    "poultry_attributes is required for Poultry category."
                )
            detail = PoultryQualityDetail(
                assessment_id=assessment.assessment_id,
                species=a.species,
                breed=a.breed,
                weight_kg=a.weight_kg,
                age_weeks=a.age_weeks,
                health_condition=(
                    a.health_condition.value if a.health_condition else None
                ),
                egg_production_rate_pct=a.egg_production_rate_pct,
                feather_condition=a.feather_condition,
                disease_signs=a.disease_signs,
            )
            self.db.add(detail)

        elif cat == "Fish":
            a = request.fish_attributes
            if a is None:
                raise ValueError("fish_attributes is required for Fish category.")
            detail = FishQualityDetail(
                assessment_id=assessment.assessment_id,
                species=a.species,
                weight_kg=a.weight_kg,
                length_cm=a.length_cm,
                freshness_level=(
                    a.freshness_level.value if a.freshness_level else None
                ),
                eye_clarity=a.eye_clarity,
                gill_condition=a.gill_condition,
                odor_assessment=a.odor_assessment,
                flesh_quality=a.flesh_quality,
            )
            self.db.add(detail)

        self.db.commit()
        self.db.refresh(assessment)
        return assessment

    def get_assessment(self, assessment_id: int) -> Optional[QualityAssessment]:
        return (
            self.db.query(QualityAssessment)
            .filter(QualityAssessment.assessment_id == assessment_id)
            .first()
        )

    def list_assessments(
        self,
        product_name: Optional[str] = None,
        category: Optional[str] = None,
        farmer_id: Optional[int] = None,
        recommendation: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ):
        q = self.db.query(QualityAssessment)
        if product_name:
            q = q.filter(QualityAssessment.product_name.ilike(f"%{product_name}%"))
        if category:
            q = q.filter(QualityAssessment.category == category)
        if farmer_id:
            q = q.filter(QualityAssessment.farmer_id == farmer_id)
        if recommendation:
            q = q.filter(QualityAssessment.purchase_recommendation == recommendation)
        return (
            q.order_by(QualityAssessment.assessment_date.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def delete_assessment(self, assessment_id: int) -> bool:
        record = self.get_assessment(assessment_id)
        if not record:
            return False
        self.db.delete(record)
        self.db.commit()
        return True
