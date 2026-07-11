"""
quality_models.py
=================
SQLAlchemy ORM models for the Agricultural Quality Assessment module.
Covers: Crops/Fruits/Vegetables, Livestock, Poultry, Fish.
Each assessment is stored in its own table with a shared parent QualityAssessment
record that holds the common fields (score, grade, recommendation, etc.).
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Ensure Farmer and Warehouse are registered in the same metadata before QualityAssessment
import app.models.stock_models  # noqa: F401
from app.database import Base

# ── Enum types ────────────────────────────────────────────────────────────────


class ProductCategory(str, enum.Enum):
    CROP = "Crop"
    FRUIT = "Fruit"
    VEGETABLE = "Vegetable"
    LIVESTOCK = "Livestock"
    POULTRY = "Poultry"
    FISH = "Fish"
    OTHER = "Other"


class GradeClassification(str, enum.Enum):
    PREMIUM = "Premium"
    GRADE_A = "Grade A"
    GRADE_B = "Grade B"
    GRADE_C = "Grade C"
    REJECT = "Reject"


class RiskLevel(str, enum.Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class PurchaseRecommendation(str, enum.Enum):
    BUY = "Buy"
    BUY_WITH_CAUTION = "Buy with Caution"
    DO_NOT_BUY = "Do Not Buy"


class RipenessLevel(str, enum.Enum):
    UNRIPE = "Unripe"
    NEARLY_RIPE = "Nearly Ripe"
    RIPE = "Ripe"
    OVERRIPE = "Overripe"


class HealthStatus(str, enum.Enum):
    EXCELLENT = "Excellent"
    GOOD = "Good"
    FAIR = "Fair"
    POOR = "Poor"
    CRITICAL = "Critical"


class FreshnessLevel(str, enum.Enum):
    VERY_FRESH = "Very Fresh"
    FRESH = "Fresh"
    ACCEPTABLE = "Acceptable"
    STALE = "Stale"
    SPOILED = "Spoiled"


# ── Master Assessment Record ──────────────────────────────────────────────────


class QualityAssessment(Base):
    """
    Master record for every quality assessment performed.
    Links to farmer and product, holds all scoring and recommendation outputs.
    """

    __tablename__ = "quality_assessments"

    assessment_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    batch_number: Mapped[str] = mapped_column(String, nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)  # ProductCategory value
    farmer_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("farmers.farmer_id", ondelete="SET NULL"),
        nullable=True,
    )
    farmer_supplier: Mapped[str | None] = mapped_column(String, nullable=True)  # Free-text supplier name
    warehouse_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("warehouses.warehouse_id", ondelete="SET NULL"),
        nullable=True,
    )
    assessed_by: Mapped[str | None] = mapped_column(String, nullable=True)  # Inspector / assessor name
    assessment_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # ── Scoring outputs ───────────────────────────────────────────────────────
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0–100
    market_readiness_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0–100
    estimated_market_value: Mapped[float | None] = mapped_column(Float, nullable=True)  # in GHS
    risk_level: Mapped[str] = mapped_column(String, nullable=False)  # RiskLevel value
    grade_classification: Mapped[str] = mapped_column(String, nullable=False)  # GradeClassification value
    purchase_recommendation: Mapped[str] = mapped_column(
        String, nullable=False
    )  # PurchaseRecommendation value
    recommendation_reason: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Metadata ─────────────────────────────────────────────────────────────
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    farmer: Mapped["app.models.stock_models.Farmer | None"] = relationship("Farmer", foreign_keys=[farmer_id])
    warehouse: Mapped["app.models.stock_models.Warehouse | None"] = relationship("Warehouse", foreign_keys=[warehouse_id])

    # One-to-one detail sub-records (only one will be populated per assessment)
    produce_detail: Mapped["ProduceQualityDetail | None"] = relationship(
        "ProduceQualityDetail",
        back_populates="assessment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    livestock_detail: Mapped["LivestockQualityDetail | None"] = relationship(
        "LivestockQualityDetail",
        back_populates="assessment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    poultry_detail: Mapped["PoultryQualityDetail | None"] = relationship(
        "PoultryQualityDetail",
        back_populates="assessment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    fish_detail: Mapped["FishQualityDetail | None"] = relationship(
        "FishQualityDetail",
        back_populates="assessment",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ── Crops / Fruits / Vegetables Detail ───────────────────────────────────────


class ProduceQualityDetail(Base):
    """
    Detailed physical attributes for Crops, Fruits, and Vegetables.
    """

    __tablename__ = "produce_quality_details"

    detail_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("quality_assessments.assessment_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Physical measurements
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    width_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    diameter_cm: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Quality attributes
    color_quality: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "Bright Red", "Uniform Yellow"
    freshness_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0–10
    ripeness_level: Mapped[str | None] = mapped_column(String, nullable=True)  # RipenessLevel value
    moisture_content_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # percentage
    visible_damage_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # percentage
    pest_damage_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # percentage
    disease_symptoms: Mapped[str | None] = mapped_column(Text, nullable=True)  # Description or "None"
    estimated_shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    assessment: Mapped["QualityAssessment"] = relationship("QualityAssessment", back_populates="produce_detail")


# ── Livestock Detail ──────────────────────────────────────────────────────────


class LivestockQualityDetail(Base):
    """
    Detailed attributes for Livestock assessments (cattle, goats, sheep, pigs, etc.)
    """

    __tablename__ = "livestock_quality_details"

    detail_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("quality_assessments.assessment_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    species: Mapped[str | None] = mapped_column(String, nullable=True)
    breed: Mapped[str | None] = mapped_column(String, nullable=True)
    age_months: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_cm: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Health & condition
    body_condition_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 1–5 scale (BCS)
    health_status: Mapped[str | None] = mapped_column(String, nullable=True)  # HealthStatus value
    vaccination_status: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "Up to date", "Partial", "None"
    disease_indicators: Mapped[str | None] = mapped_column(Text, nullable=True)  # Description or "None observed"
    mobility_assessment: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "Normal", "Slight limp", "Lame"
    feeding_condition: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "Well-fed", "Thin", "Emaciated"
    reproductive_status: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "Pregnant", "Lactating", "Dry"

    assessment: Mapped["QualityAssessment"] = relationship("QualityAssessment", back_populates="livestock_detail")


# ── Poultry Detail ────────────────────────────────────────────────────────────


class PoultryQualityDetail(Base):
    """
    Detailed attributes for Poultry assessments (chickens, turkeys, ducks, guinea fowl, etc.)
    """

    __tablename__ = "poultry_quality_details"

    detail_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("quality_assessments.assessment_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    species: Mapped[str | None] = mapped_column(String, nullable=True)
    breed: Mapped[str | None] = mapped_column(String, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    age_weeks: Mapped[float | None] = mapped_column(Float, nullable=True)
    health_condition: Mapped[str | None] = mapped_column(String, nullable=True)  # HealthStatus value
    egg_production_rate_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # % for layers (None for broilers)
    feather_condition: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "Full, Glossy", "Patchy", "Bare"
    disease_signs: Mapped[str | None] = mapped_column(Text, nullable=True)  # Description or "None observed"

    assessment: Mapped["QualityAssessment"] = relationship("QualityAssessment", back_populates="poultry_detail")


# ── Fish Detail ───────────────────────────────────────────────────────────────


class FishQualityDetail(Base):
    """
    Detailed attributes for Fish assessments (tilapia, catfish, tuna, etc.)
    """

    __tablename__ = "fish_quality_details"

    detail_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("quality_assessments.assessment_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    species: Mapped[str | None] = mapped_column(String, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    freshness_level: Mapped[str | None] = mapped_column(String, nullable=True)  # FreshnessLevel value
    eye_clarity: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "Clear, Bright", "Cloudy", "Sunken"
    gill_condition: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "Bright Red", "Pink", "Grey/Brown"
    odor_assessment: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "Fresh Sea Smell", "Mild", "Foul"
    flesh_quality: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. "Firm, Elastic", "Soft", "Mushy"

    assessment: Mapped["QualityAssessment"] = relationship("QualityAssessment", back_populates="fish_detail")
