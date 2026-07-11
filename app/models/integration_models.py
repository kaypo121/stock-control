"""
integration_models.py
=====================
Database models for the Stock Control Data Integration AI.
Tracks every import session, field mappings, validation results,
and generated reports — all stored for audit and replay.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.models.quality_models  # noqa: F401
import app.models.stock_models  # noqa: F401
from app.database import Base


class DataIntegrationSession(Base):
    """
    Master record for one full import pipeline run.
    One session = one file processed through all 7 steps.
    """

    __tablename__ = "integration_sessions"

    session_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    file_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    data_source: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "MoFA CSV", "Manual Upload"
    detected_schema: Mapped[str | None] = mapped_column(String, nullable=True)  # Detected category of dataset
    initiated_by: Mapped[str | None] = mapped_column(String, nullable=True)  # User/system that triggered import

    # Step 1 — Analysis
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    total_columns: Mapped[int] = mapped_column(Integer, default=0)
    missing_value_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_row_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_data_count: Mapped[int] = mapped_column(Integer, default=0)
    column_list: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-serialised list

    # Step 2 — Cleaning
    rows_after_cleaning: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_removed: Mapped[int] = mapped_column(Integer, default=0)
    nulls_filled: Mapped[int] = mapped_column(Integer, default=0)
    units_standardised: Mapped[int] = mapped_column(Integer, default=0)
    format_corrections: Mapped[int] = mapped_column(Integer, default=0)

    # Step 3 — Mapping
    field_mapping: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: {source_col: target_field}
    unmapped_columns: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list

    # Step 4-5 — Integration & inventory processing
    farmers_created: Mapped[int] = mapped_column(Integer, default=0)
    farmers_matched: Mapped[int] = mapped_column(Integer, default=0)
    products_created: Mapped[int] = mapped_column(Integer, default=0)
    products_matched: Mapped[int] = mapped_column(Integer, default=0)
    warehouses_created: Mapped[int] = mapped_column(Integer, default=0)
    warehouses_matched: Mapped[int] = mapped_column(Integer, default=0)
    transactions_inserted: Mapped[int] = mapped_column(Integer, default=0)
    quality_assessments_inserted: Mapped[int] = mapped_column(Integer, default=0)
    balances_updated: Mapped[int] = mapped_column(Integer, default=0)

    # Step 6 — Validation
    validation_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_ids_found: Mapped[int] = mapped_column(Integer, default=0)
    constraint_violations: Mapped[int] = mapped_column(Integer, default=0)

    # Overall status & timing
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    # PENDING | ANALYSING | CLEANING | MAPPING | INTEGRATING | VALIDATING | REPORTING | SUCCESS | PARTIAL | FAILED
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    error_records: Mapped[list["IntegrationErrorRecord"]] = relationship(
        "IntegrationErrorRecord",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    reports: Mapped[list["IntegrationReport"]] = relationship(
        "IntegrationReport",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class IntegrationErrorRecord(Base):
    """Individual row-level error captured during import."""

    __tablename__ = "integration_error_records"

    error_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("integration_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    step: Mapped[str | None] = mapped_column(String, nullable=True)  # Which step produced the error
    field_name: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_value: Mapped[str | None] = mapped_column(String, nullable=True)
    error_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # MISSING | INVALID | DUPLICATE | CONSTRAINT | MAPPING
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    session: Mapped["DataIntegrationSession"] = relationship("DataIntegrationSession", back_populates="error_records")


class IntegrationReport(Base):
    """
    Generated report artifact for a completed integration session.
    Stores the full JSON report payload for each report type.
    """

    __tablename__ = "integration_reports"

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("integration_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    report_type: Mapped[str] = mapped_column(String, nullable=False)
    # DATA_IMPORT | STOCK_SUMMARY | PRODUCT_AVAILABILITY | INVENTORY_HEALTH | LOW_STOCK_ALERT
    report_title: Mapped[str] = mapped_column(String, nullable=False)
    report_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON blob
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    session: Mapped["DataIntegrationSession"] = relationship("DataIntegrationSession", back_populates="reports")
