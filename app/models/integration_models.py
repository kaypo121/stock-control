"""
integration_models.py
=====================
Database models for the Stock Control Data Integration AI.
Tracks every import session, field mappings, validation results,
and generated reports — all stored for audit and replay.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.database import Base
import app.models.stock_models   # noqa: F401
import app.models.quality_models # noqa: F401


class DataIntegrationSession(Base):
    """
    Master record for one full import pipeline run.
    One session = one file processed through all 7 steps.
    """
    __tablename__ = "integration_sessions"

    session_id          = Column(Integer, primary_key=True, autoincrement=True, index=True)
    file_name           = Column(String,  nullable=False, index=True)
    file_path           = Column(String,  nullable=True)
    data_source         = Column(String,  nullable=True)   # e.g. "MoFA CSV", "Manual Upload"
    detected_schema     = Column(String,  nullable=True)   # Detected category of dataset
    initiated_by        = Column(String,  nullable=True)   # User/system that triggered import

    # Step 1 — Analysis
    total_rows          = Column(Integer, default=0)
    total_columns       = Column(Integer, default=0)
    missing_value_count = Column(Integer, default=0)
    duplicate_row_count = Column(Integer, default=0)
    invalid_data_count  = Column(Integer, default=0)
    column_list         = Column(Text,    nullable=True)   # JSON-serialised list

    # Step 2 — Cleaning
    rows_after_cleaning     = Column(Integer, default=0)
    duplicates_removed      = Column(Integer, default=0)
    nulls_filled            = Column(Integer, default=0)
    units_standardised      = Column(Integer, default=0)
    format_corrections      = Column(Integer, default=0)

    # Step 3 — Mapping
    field_mapping           = Column(Text,  nullable=True)  # JSON: {source_col: target_field}
    unmapped_columns        = Column(Text,  nullable=True)  # JSON list

    # Step 4-5 — Integration & inventory processing
    farmers_created         = Column(Integer, default=0)
    farmers_matched         = Column(Integer, default=0)
    products_created        = Column(Integer, default=0)
    products_matched        = Column(Integer, default=0)
    warehouses_created      = Column(Integer, default=0)
    warehouses_matched      = Column(Integer, default=0)
    transactions_inserted   = Column(Integer, default=0)
    quality_assessments_inserted = Column(Integer, default=0)
    balances_updated        = Column(Integer, default=0)

    # Step 6 — Validation
    validation_passed       = Column(Boolean, default=False)
    duplicate_ids_found     = Column(Integer, default=0)
    constraint_violations   = Column(Integer, default=0)

    # Overall status & timing
    status              = Column(String, nullable=False, default="PENDING")
    # PENDING | ANALYSING | CLEANING | MAPPING | INTEGRATING | VALIDATING | REPORTING | SUCCESS | PARTIAL | FAILED
    error_summary       = Column(Text,  nullable=True)
    started_at          = Column(DateTime, default=datetime.utcnow)
    completed_at        = Column(DateTime, nullable=True)

    # Relationships
    error_records   = relationship("IntegrationErrorRecord",  back_populates="session", cascade="all, delete-orphan")
    reports         = relationship("IntegrationReport",        back_populates="session", cascade="all, delete-orphan")


class IntegrationErrorRecord(Base):
    """Individual row-level error captured during import."""
    __tablename__ = "integration_error_records"

    error_id        = Column(Integer, primary_key=True, autoincrement=True)
    session_id      = Column(Integer, ForeignKey("integration_sessions.session_id", ondelete="CASCADE"), nullable=False)
    row_index       = Column(Integer, nullable=True)
    step            = Column(String,  nullable=True)   # Which step produced the error
    field_name      = Column(String,  nullable=True)
    raw_value       = Column(String,  nullable=True)
    error_type      = Column(String,  nullable=False)  # MISSING | INVALID | DUPLICATE | CONSTRAINT | MAPPING
    error_message   = Column(Text,    nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)

    session = relationship("DataIntegrationSession", back_populates="error_records")


class IntegrationReport(Base):
    """
    Generated report artifact for a completed integration session.
    Stores the full JSON report payload for each report type.
    """
    __tablename__ = "integration_reports"

    report_id       = Column(Integer, primary_key=True, autoincrement=True)
    session_id      = Column(Integer, ForeignKey("integration_sessions.session_id", ondelete="CASCADE"), nullable=False)
    report_type     = Column(String,  nullable=False)
    # DATA_IMPORT | STOCK_SUMMARY | PRODUCT_AVAILABILITY | INVENTORY_HEALTH | LOW_STOCK_ALERT
    report_title    = Column(String,  nullable=False)
    report_data     = Column(Text,    nullable=False)   # JSON blob
    generated_at    = Column(DateTime, default=datetime.utcnow)

    session = relationship("DataIntegrationSession", back_populates="reports")
