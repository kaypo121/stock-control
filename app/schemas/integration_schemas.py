"""
integration_schemas.py
======================
Pydantic schemas for the Data Integration AI module.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

# ── Step-level summary blocks ──────────────────────────────────────────────────


class AnalysisSummary(BaseModel):
    file_name: str
    data_source: str
    detected_schema: str
    total_rows: int
    total_columns: int
    column_list: List[str]
    missing_value_count: int
    duplicate_row_count: int
    invalid_data_count: int
    sample_issues: List[str]


class CleaningSummary(BaseModel):
    rows_before: int
    rows_after: int
    duplicates_removed: int
    nulls_filled: int
    units_standardised: int
    format_corrections: int
    actions_taken: List[str]


class MappingSummary(BaseModel):
    field_mapping: Dict[str, str]  # source_col → target_field
    unmapped_columns: List[str]
    tables_targeted: List[str]


class IntegrationSummary(BaseModel):
    farmers_created: int
    farmers_matched: int
    products_created: int
    products_matched: int
    warehouses_created: int
    warehouses_matched: int
    transactions_inserted: int
    quality_assessments_inserted: int
    balances_updated: int


class InventoryStats(BaseModel):
    product_name: str
    category: str
    unit: str
    total_current_stock: float
    total_stock_in: float
    total_stock_out: float
    total_damaged: float
    available_stock: float
    reserved_stock: float
    expired_stock: float
    reorder_level: float
    stock_turnover_rate: float  # outflow / avg_stock
    status: str  # HEALTHY | LOW_STOCK | CRITICAL | OUT_OF_STOCK


class ValidationResult(BaseModel):
    passed: bool
    duplicate_ids_found: int
    constraint_violations: int
    warehouse_mismatches: int
    quantity_anomalies: int
    issues: List[str]


# ── Report schemas ─────────────────────────────────────────────────────────────


class DataImportReport(BaseModel):
    report_type: str = "DATA_IMPORT"
    session_id: int
    file_name: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    analysis: AnalysisSummary
    cleaning: CleaningSummary
    mapping: MappingSummary
    integration: IntegrationSummary
    validation: ValidationResult
    records_imported: int
    records_failed: int
    errors_found: List[Dict[str, Any]]
    recommended_actions: List[str]


class StockSummaryReport(BaseModel):
    report_type: str = "STOCK_SUMMARY"
    generated_at: datetime
    total_products: int
    total_farmers: int
    total_warehouses: int
    total_transactions: int
    inventory: List[InventoryStats]


class ProductAvailabilityReport(BaseModel):
    report_type: str = "PRODUCT_AVAILABILITY"
    generated_at: datetime
    available_products: List[Dict[str, Any]]
    out_of_stock: List[Dict[str, Any]]
    low_stock: List[Dict[str, Any]]


class InventoryHealthReport(BaseModel):
    report_type: str = "INVENTORY_HEALTH"
    generated_at: datetime
    healthy_count: int
    low_stock_count: int
    critical_count: int
    out_of_stock_count: int
    overall_health_pct: float
    items: List[InventoryStats]


class LowStockAlertReport(BaseModel):
    report_type: str = "LOW_STOCK_ALERT"
    generated_at: datetime
    alert_count: int
    critical_count: int
    alerts: List[Dict[str, Any]]
    recommended_actions: List[str]


# ── Full pipeline output ───────────────────────────────────────────────────────


class IntegrationPipelineResult(BaseModel):
    """Complete output returned by a full pipeline run."""

    session_id: int
    file_name: str
    status: str

    # Step outputs
    cleaned_dataset_summary: CleaningSummary
    database_mapping_summary: MappingSummary
    import_results: IntegrationSummary
    errors_found: List[Dict[str, Any]]
    records_successfully_imported: int
    records_failed: int
    inventory_statistics: List[InventoryStats]
    recommended_actions: List[str]

    # Reports
    data_import_report: DataImportReport
    stock_summary_report: StockSummaryReport
    product_availability_report: ProductAvailabilityReport
    inventory_health_report: InventoryHealthReport
    low_stock_alert_report: LowStockAlertReport


# ── API request/response wrappers ─────────────────────────────────────────────


class SessionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    file_name: str
    detected_schema: Optional[str]
    status: str
    total_rows: int
    transactions_inserted: int
    records_failed: Optional[int]
    started_at: datetime
    completed_at: Optional[datetime]


class SessionDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    file_name: str
    data_source: Optional[str]
    detected_schema: Optional[str]
    status: str
    total_rows: int
    total_columns: int
    missing_value_count: int
    duplicate_row_count: int
    farmers_created: int
    farmers_matched: int
    products_created: int
    products_matched: int
    warehouses_created: int
    warehouses_matched: int
    transactions_inserted: int
    balances_updated: int
    validation_passed: bool
    duplicate_ids_found: int
    constraint_violations: int
    started_at: datetime
    completed_at: Optional[datetime]
    error_summary: Optional[str]


class ReportListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: int
    session_id: int
    report_type: str
    report_title: str
    generated_at: datetime
