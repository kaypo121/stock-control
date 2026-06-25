"""
quality_models.py
=================
SQLAlchemy ORM models for the Agricultural Quality Assessment module.
Covers: Crops/Fruits/Vegetables, Livestock, Poultry, Fish.
Each assessment is stored in its own table with a shared parent QualityAssessment
record that holds the common fields (score, grade, recommendation, etc.).
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, Text, Enum
)
from sqlalchemy.orm import relationship
import enum

from app.database import Base

# Ensure Farmer and Warehouse are registered in the same metadata before QualityAssessment
import app.models.stock_models  # noqa: F401


# ── Enum types ────────────────────────────────────────────────────────────────

class ProductCategory(str, enum.Enum):
    CROP        = "Crop"
    FRUIT       = "Fruit"
    VEGETABLE   = "Vegetable"
    LIVESTOCK   = "Livestock"
    POULTRY     = "Poultry"
    FISH        = "Fish"
    OTHER       = "Other"

class GradeClassification(str, enum.Enum):
    PREMIUM = "Premium"
    GRADE_A = "Grade A"
    GRADE_B = "Grade B"
    GRADE_C = "Grade C"
    REJECT  = "Reject"

class RiskLevel(str, enum.Enum):
    LOW    = "Low"
    MEDIUM = "Medium"
    HIGH   = "High"

class PurchaseRecommendation(str, enum.Enum):
    BUY             = "Buy"
    BUY_WITH_CAUTION = "Buy with Caution"
    DO_NOT_BUY      = "Do Not Buy"

class RipenessLevel(str, enum.Enum):
    UNRIPE      = "Unripe"
    NEARLY_RIPE = "Nearly Ripe"
    RIPE        = "Ripe"
    OVERRIPE    = "Overripe"

class HealthStatus(str, enum.Enum):
    EXCELLENT = "Excellent"
    GOOD      = "Good"
    FAIR      = "Fair"
    POOR      = "Poor"
    CRITICAL  = "Critical"

class FreshnessLevel(str, enum.Enum):
    VERY_FRESH  = "Very Fresh"
    FRESH       = "Fresh"
    ACCEPTABLE  = "Acceptable"
    STALE       = "Stale"
    SPOILED     = "Spoiled"


# ── Master Assessment Record ──────────────────────────────────────────────────

class QualityAssessment(Base):
    """
    Master record for every quality assessment performed.
    Links to farmer and product, holds all scoring and recommendation outputs.
    """
    __tablename__ = "quality_assessments"

    assessment_id       = Column(Integer, primary_key=True, index=True, autoincrement=True)
    batch_number        = Column(String,  nullable=False, index=True)
    product_name        = Column(String,  nullable=False, index=True)
    category            = Column(String,  nullable=False, index=True)   # ProductCategory value
    farmer_id           = Column(Integer, ForeignKey("farmers.farmer_id", ondelete="SET NULL"), nullable=True)
    farmer_supplier     = Column(String,  nullable=True)                # Free-text supplier name
    warehouse_id        = Column(Integer, ForeignKey("warehouses.warehouse_id", ondelete="SET NULL"), nullable=True)
    assessed_by         = Column(String,  nullable=True)                # Inspector / assessor name
    assessment_date     = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # ── Scoring outputs ───────────────────────────────────────────────────────
    quality_score           = Column(Float,  nullable=False)   # 0–100
    market_readiness_score  = Column(Float,  nullable=False)   # 0–100
    estimated_market_value  = Column(Float,  nullable=True)    # in GHS
    risk_level              = Column(String, nullable=False)   # RiskLevel value
    grade_classification    = Column(String, nullable=False)   # GradeClassification value
    purchase_recommendation = Column(String, nullable=False)   # PurchaseRecommendation value
    recommendation_reason   = Column(Text,   nullable=False)

    # ── Metadata ─────────────────────────────────────────────────────────────
    notes       = Column(Text,     nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    farmer    = relationship("Farmer",    foreign_keys=[farmer_id])
    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id])

    # One-to-one detail sub-records (only one will be populated per assessment)
    produce_detail   = relationship("ProduceQualityDetail",   back_populates="assessment", uselist=False, cascade="all, delete-orphan")
    livestock_detail = relationship("LivestockQualityDetail", back_populates="assessment", uselist=False, cascade="all, delete-orphan")
    poultry_detail   = relationship("PoultryQualityDetail",   back_populates="assessment", uselist=False, cascade="all, delete-orphan")
    fish_detail      = relationship("FishQualityDetail",      back_populates="assessment", uselist=False, cascade="all, delete-orphan")


# ── Crops / Fruits / Vegetables Detail ───────────────────────────────────────

class ProduceQualityDetail(Base):
    """
    Detailed physical attributes for Crops, Fruits, and Vegetables.
    """
    __tablename__ = "produce_quality_details"

    detail_id       = Column(Integer, primary_key=True, autoincrement=True)
    assessment_id   = Column(Integer, ForeignKey("quality_assessments.assessment_id", ondelete="CASCADE"), nullable=False, unique=True)

    # Physical measurements
    weight_kg       = Column(Float,  nullable=True)
    length_cm       = Column(Float,  nullable=True)
    width_cm        = Column(Float,  nullable=True)
    height_cm       = Column(Float,  nullable=True)
    diameter_cm     = Column(Float,  nullable=True)

    # Quality attributes
    color_quality       = Column(String, nullable=True)   # e.g. "Bright Red", "Uniform Yellow"
    freshness_score     = Column(Float,  nullable=True)   # 0–10
    ripeness_level      = Column(String, nullable=True)   # RipenessLevel value
    moisture_content_pct= Column(Float,  nullable=True)   # percentage
    visible_damage_pct  = Column(Float,  nullable=True)   # percentage
    pest_damage_pct     = Column(Float,  nullable=True)   # percentage
    disease_symptoms    = Column(Text,   nullable=True)   # Description or "None"
    estimated_shelf_life_days = Column(Integer, nullable=True)

    assessment = relationship("QualityAssessment", back_populates="produce_detail")


# ── Livestock Detail ──────────────────────────────────────────────────────────

class LivestockQualityDetail(Base):
    """
    Detailed attributes for Livestock assessments (cattle, goats, sheep, pigs, etc.)
    """
    __tablename__ = "livestock_quality_details"

    detail_id       = Column(Integer, primary_key=True, autoincrement=True)
    assessment_id   = Column(Integer, ForeignKey("quality_assessments.assessment_id", ondelete="CASCADE"), nullable=False, unique=True)

    species             = Column(String, nullable=True)
    breed               = Column(String, nullable=True)
    age_months          = Column(Float,  nullable=True)
    weight_kg           = Column(Float,  nullable=True)
    height_cm           = Column(Float,  nullable=True)
    length_cm           = Column(Float,  nullable=True)

    # Health & condition
    body_condition_score    = Column(Float,  nullable=True)  # 1–5 scale (BCS)
    health_status           = Column(String, nullable=True)  # HealthStatus value
    vaccination_status      = Column(String, nullable=True)  # e.g. "Up to date", "Partial", "None"
    disease_indicators      = Column(Text,   nullable=True)  # Description or "None observed"
    mobility_assessment     = Column(String, nullable=True)  # e.g. "Normal", "Slight limp", "Lame"
    feeding_condition       = Column(String, nullable=True)  # e.g. "Well-fed", "Thin", "Emaciated"
    reproductive_status     = Column(String, nullable=True)  # e.g. "Pregnant", "Lactating", "Dry"

    assessment = relationship("QualityAssessment", back_populates="livestock_detail")


# ── Poultry Detail ────────────────────────────────────────────────────────────

class PoultryQualityDetail(Base):
    """
    Detailed attributes for Poultry assessments (chickens, turkeys, ducks, guinea fowl, etc.)
    """
    __tablename__ = "poultry_quality_details"

    detail_id       = Column(Integer, primary_key=True, autoincrement=True)
    assessment_id   = Column(Integer, ForeignKey("quality_assessments.assessment_id", ondelete="CASCADE"), nullable=False, unique=True)

    species                 = Column(String, nullable=True)
    breed                   = Column(String, nullable=True)
    weight_kg               = Column(Float,  nullable=True)
    age_weeks               = Column(Float,  nullable=True)
    health_condition        = Column(String, nullable=True)  # HealthStatus value
    egg_production_rate_pct = Column(Float,  nullable=True)  # % for layers (None for broilers)
    feather_condition       = Column(String, nullable=True)  # e.g. "Full, Glossy", "Patchy", "Bare"
    disease_signs           = Column(Text,   nullable=True)  # Description or "None observed"

    assessment = relationship("QualityAssessment", back_populates="poultry_detail")


# ── Fish Detail ───────────────────────────────────────────────────────────────

class FishQualityDetail(Base):
    """
    Detailed attributes for Fish assessments (tilapia, catfish, tuna, etc.)
    """
    __tablename__ = "fish_quality_details"

    detail_id       = Column(Integer, primary_key=True, autoincrement=True)
    assessment_id   = Column(Integer, ForeignKey("quality_assessments.assessment_id", ondelete="CASCADE"), nullable=False, unique=True)

    species         = Column(String, nullable=True)
    weight_kg       = Column(Float,  nullable=True)
    length_cm       = Column(Float,  nullable=True)
    freshness_level = Column(String, nullable=True)  # FreshnessLevel value
    eye_clarity     = Column(String, nullable=True)  # e.g. "Clear, Bright", "Cloudy", "Sunken"
    gill_condition  = Column(String, nullable=True)  # e.g. "Bright Red", "Pink", "Grey/Brown"
    odor_assessment = Column(String, nullable=True)  # e.g. "Fresh Sea Smell", "Mild", "Foul"
    flesh_quality   = Column(String, nullable=True)  # e.g. "Firm, Elastic", "Soft", "Mushy"

    assessment = relationship("QualityAssessment", back_populates="fish_detail")
