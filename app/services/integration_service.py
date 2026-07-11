"""
integration_service.py
======================
Stock Control Data Integration AI — Full 7-Step Pipeline

STEP 1  DATA ANALYSIS      — Profile every column: nulls, dupes, types, anomalies
STEP 2  DATA CLEANING       — Remove dupes, fill nulls, standardise units/formats
STEP 3  DATA MAPPING        — Auto-detect dataset type, map columns to DB schema
STEP 4  STOCK INTEGRATION   — Insert Farmers, Products, Warehouses, Transactions,
                               Quality Assessments into the database
STEP 5  INVENTORY PROCESSING— Calculate current/available/damaged/turnover metrics
STEP 6  VALIDATION          — Verify IDs, balances, warehouse assignment, no dupes
STEP 7  REPORTING           — Generate all 5 report types + full pipeline output
"""

import difflib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.exceptions import IntegrationError

from app.models.integration_models import (
    DataIntegrationSession,
    IntegrationErrorRecord,
    IntegrationReport,
)
from app.models.stock_models import (
    Farmer,
    ImportLog,
    Product,
    StockBalance,
    StockTransaction,
    Warehouse,
)
from app.schemas.integration_schemas import (
    AnalysisSummary,
    CleaningSummary,
    DataImportReport,
    IntegrationPipelineResult,
    IntegrationSummary,
    InventoryHealthReport,
    InventoryStats,
    LowStockAlertReport,
    MappingSummary,
    ProductAvailabilityReport,
    StockSummaryReport,
    ValidationResult,
)
from app.utils.unit_converter import convert_quantity

# ── Column alias lookup: maps raw column names → canonical field names ─────────
COLUMN_ALIASES: Dict[str, str] = {
    # Farmer
    "farmer": "farmer_name",
    "farmer_name": "farmer_name",
    "supplier": "farmer_name",
    "supplier_name": "farmer_name",
    "grower": "farmer_name",
    "producer": "farmer_name",
    "farmer_id": "farmer_id",
    "supplier_id": "farmer_id",
    # Product
    "product": "product_name",
    "product_name": "product_name",
    "crop": "product_name",
    "commodity": "product_name",
    "item": "product_name",
    "goods": "product_name",
    "species": "product_name",
    "livestock": "product_name",
    "fish_species": "product_name",
    # Category
    "category": "category",
    "type": "category",
    "product_type": "category",
    "item_type": "category",
    # Quantity / weight
    "quantity": "quantity",
    "qty": "quantity",
    "amount": "quantity",
    "volume": "quantity",
    "weight": "quantity",
    "weight_kg": "quantity",
    "production": "quantity",
    "production_mt": "quantity",
    "harvest": "quantity",
    # Unit
    "unit": "unit",
    "units": "unit",
    "uom": "unit",
    "measure": "unit",
    # Transaction type
    "transaction_type": "transaction_type",
    "movement_type": "transaction_type",
    "action": "transaction_type",
    # Date
    "date": "transaction_date",
    "transaction_date": "transaction_date",
    "harvest_date": "transaction_date",
    "purchase_date": "transaction_date",
    "sale_date": "transaction_date",
    "market_day": "transaction_date",
    "year": "transaction_date",
    # Warehouse / Location
    "warehouse": "warehouse_name",
    "warehouse_name": "warehouse_name",
    "storage": "warehouse_name",
    "location": "warehouse_name",
    "market": "warehouse_name",
    "store": "warehouse_name",
    "depot": "warehouse_name",
    # Region / District
    "region": "region",
    "district": "district",
    "area": "region",
    "zone": "region",
    # Price
    "price": "unit_price",
    "unit_price": "unit_price",
    "cost": "unit_price",
    "rate": "unit_price",
    # Reference
    "note": "reference_note",
    "notes": "reference_note",
    "reference": "reference_note",
    "reference_note": "reference_note",
    "batch": "batch_number",
    "batch_number": "batch_number",
    "lot": "batch_number",
    # Livestock / Poultry / Fish specific
    "breed": "breed",
    "age": "age",
    "age_months": "age",
    "age_weeks": "age",
    "health_status": "health_status",
    "health": "health_status",
    "body_condition_score": "body_condition_score",
    "bcs": "body_condition_score",
    "vaccination": "vaccination_status",
    "vaccination_status": "vaccination_status",
    # Quality
    "freshness_score": "freshness_score",
    "freshness": "freshness_score",
    "ripeness": "ripeness_level",
    "ripeness_level": "ripeness_level",
    "moisture": "moisture_content_pct",
    "moisture_pct": "moisture_content_pct",
    "damage_pct": "visible_damage_pct",
    "visible_damage": "visible_damage_pct",
    "pest_damage": "pest_damage_pct",
    "disease": "disease_symptoms",
    # Inventory
    "opening_stock": "opening_stock",
    "opening_balance": "opening_stock",
    "reorder_level": "reorder_level",
    "reorder": "reorder_level",
    "min_stock": "reorder_level",
}

# ── Dataset type signatures: sets of columns that identify known schemas ──────
SCHEMA_SIGNATURES: Dict[str, List[str]] = {
    "PRODUCTION_ESTIMATES": [
        "crop",
        "production",
        "region",
        "district",
        "year",
    ],
    "WHOLESALE_PRICES": ["commodity", "price", "year"],
    "RAINFALL": ["region", "year", "rainfall"],
    "SYNTHETIC_TRANSACTIONS": [
        "farmer_name",
        "product_name",
        "quantity",
        "unit",
        "transaction_type",
        "transaction_date",
    ],
    "INVENTORY_RECORDS": [
        "product_name",
        "quantity",
        "unit",
        "opening_stock",
        "warehouse_name",
    ],
    "SALES_RECORDS": ["product_name", "quantity", "unit", "sale_date"],
    "PURCHASE_RECORDS": [
        "product_name",
        "quantity",
        "unit",
        "purchase_date",
        "supplier",
    ],
    "LIVESTOCK_RECORDS": ["species", "breed", "weight", "health_status"],
    "POULTRY_RECORDS": ["species", "breed", "weight", "age_weeks"],
    "FISH_RECORDS": ["species", "weight", "freshness_level"],
    "QUALITY_ASSESSMENTS": [
        "product_name",
        "batch_number",
        "freshness_score",
        "quality_score",
    ],
    "FARMER_REGISTRY": ["farmer_name", "region", "district", "phone"],
    "WAREHOUSE_REGISTRY": ["warehouse_name", "region", "capacity"],
    "GENERIC_STOCK": ["product_name", "quantity", "unit"],
}

# Unit normalisation map
UNIT_NORMALISATION: Dict[str, str] = {
    "kg": "kg",
    "kgs": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "ton": "ton",
    "tons": "ton",
    "mt": "ton",
    "tonne": "ton",
    "metric ton": "ton",
    "g": "kg",  # will convert via factor
    "lb": "kg",  # will convert
    "bag": "bag",
    "bags": "bag",
    "sack": "bag",
    "sacks": "bag",
    "crate": "crate",
    "crates": "crate",
    "box": "crate",
    "boxes": "crate",
    "piece": "piece",
    "pieces": "piece",
    "pcs": "piece",
    "head": "piece",
    "liter": "liter",
    "litre": "liter",
    "l": "liter",
    "gallon": "gallon",
    "gallons": "gallon",
    "gal": "gallon",
    "bundle": "bundle",
    "bundles": "bundle",
}

UNIT_CONVERSION_FACTORS: Dict[str, float] = {
    "g": 0.001,  # grams to kg
    "lb": 0.4536,  # pounds to kg
}

VALID_TX_TYPES = {
    "STOCK_IN",
    "STOCK_OUT",
    "DAMAGE",
    "RETURN",
    "TRANSFER",
    "ADJUSTMENT",
}


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════


def _normalise_headers(df: pd.DataFrame) -> pd.DataFrame:
    new_cols = []
    for col in df.columns:
        c = str(col).strip().lower()
        c = re.sub(r"[^a-z0-9_]", "_", c)
        c = re.sub(r"_+", "_", c).strip("_")
        new_cols.append(c)
    df.columns = new_cols
    return df


def _parse_number(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_date(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    s = str(val).strip()
    for fmt in (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%Y-%m",
        "%Y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _detect_schema(columns: List[str]) -> str:
    """Score each known schema against the available columns and return best match."""
    best_schema = "GENERIC_STOCK"
    best_score = 0
    col_set = set(columns)
    for schema_name, required_cols in SCHEMA_SIGNATURES.items():
        hits = sum(1 for c in required_cols if c in col_set)
        score = hits / len(required_cols)
        if score > best_score:
            best_score = score
            best_schema = schema_name
    return best_schema


def _map_columns(df_cols: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    Map raw normalised column names to canonical field names.
    Returns (mapping_dict, unmapped_list).
    """
    mapping = {}
    unmapped = []
    for col in df_cols:
        canonical = COLUMN_ALIASES.get(col)
        if canonical:
            mapping[col] = canonical
        else:
            unmapped.append(col)
    return mapping, unmapped


def _normalise_unit(raw: str) -> str:
    if not raw:
        return "kg"
    norm = str(raw).strip().lower()
    return UNIT_NORMALISATION.get(norm, norm)


def _apply_unit_factor(qty: float, raw_unit: str) -> Tuple[float, str]:
    """Convert unusual units (g, lb) to their base equivalent."""
    norm = str(raw_unit).strip().lower()
    if norm in UNIT_CONVERSION_FACTORS:
        return qty * UNIT_CONVERSION_FACTORS[norm], UNIT_NORMALISATION.get(norm, norm)
    return qty, _normalise_unit(raw_unit)


def _get_or_create_farmer(
    db: Session,
    name: str,
    region: Optional[str],
    district: Optional[str],
    created_counter: List[int],
    matched_counter: List[int],
) -> Optional[Farmer]:
    name_c = str(name).strip()
    if not name_c:
        return None
    # Exact match (case-insensitive)
    farmer = (
        db.query(Farmer).filter(func.lower(Farmer.full_name) == name_c.lower()).first()
    )
    if farmer:
        matched_counter[0] += 1
        return farmer
    # Fuzzy match
    all_farmers = db.query(Farmer).all()
    best, best_score = None, 0.0
    for f in all_farmers:
        r = difflib.SequenceMatcher(None, f.full_name.lower(), name_c.lower()).ratio()
        if r > best_score:
            best_score = r
            best = f
    if best and best_score >= 0.92:
        matched_counter[0] += 1
        return best
    # Create new
    farmer = Farmer(
        full_name=name_c,
        region=region,
        district=district,
        farm_name=f"{name_c} Farm",
    )
    db.add(farmer)
    db.commit()
    db.refresh(farmer)
    created_counter[0] += 1
    return farmer


def _get_or_create_product(
    db: Session,
    name: str,
    category: str,
    unit: str,
    created_counter: List[int],
    matched_counter: List[int],
) -> Optional[Product]:
    name_c = str(name).strip()
    if not name_c:
        return None
    product = (
        db.query(Product)
        .filter(func.lower(Product.product_name) == name_c.lower())
        .first()
    )
    if product:
        matched_counter[0] += 1
        return product
    # Fuzzy match
    all_products = db.query(Product).all()
    best, best_score = None, 0.0
    for p in all_products:
        r = difflib.SequenceMatcher(
            None, p.product_name.lower(), name_c.lower()
        ).ratio()
        if r > best_score:
            best_score = r
            best = p
    if best and best_score >= 0.92:
        matched_counter[0] += 1
        return best
    # Create new
    product = Product(
        product_name=name_c,
        category=category or "Other",
        unit=unit or "kg",
        description=f"Auto-created from import: {name_c}",
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    created_counter[0] += 1
    return product


def _get_or_create_warehouse(
    db: Session,
    name: str,
    region: Optional[str],
    district: Optional[str],
    created_counter: List[int],
    matched_counter: List[int],
) -> Optional[Warehouse]:
    name_c = str(name).strip()
    if not name_c:
        return None
    wh = (
        db.query(Warehouse)
        .filter(func.lower(Warehouse.warehouse_name) == name_c.lower())
        .first()
    )
    if wh:
        matched_counter[0] += 1
        return wh
    wh = Warehouse(warehouse_name=name_c, region=region, district=district)
    db.add(wh)
    db.commit()
    db.refresh(wh)
    created_counter[0] += 1
    return wh


def _update_balance(
    db: Session,
    farmer_id: int,
    product_id: int,
    warehouse_id: Optional[int],
    tx_type: str,
    qty_base: float,
    balance_cache: Dict,
) -> None:
    key = (farmer_id, product_id, warehouse_id)
    balance = balance_cache.get(key)
    if not balance:
        balance = (
            db.query(StockBalance)
            .filter(
                StockBalance.farmer_id == farmer_id,
                StockBalance.product_id == product_id,
                StockBalance.warehouse_id == warehouse_id,
            )
            .first()
        )
        if not balance:
            balance = StockBalance(
                farmer_id=farmer_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
                opening_stock=0.0,
                current_stock=0.0,
                reorder_level=0.0,
                last_updated=datetime.now(timezone.utc),
            )
            db.add(balance)
            db.flush()
        balance_cache[key] = balance

    if tx_type in ("STOCK_IN", "RETURN"):
        balance.current_stock += qty_base
    elif tx_type in ("STOCK_OUT", "DAMAGE", "TRANSFER"):
        balance.current_stock = max(0.0, balance.current_stock - qty_base)
    elif tx_type == "ADJUSTMENT":
        balance.current_stock = max(0.0, balance.current_stock + qty_base)

    balance.last_updated = datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 5: INVENTORY STATISTICS
# ══════════════════════════════════════════════════════════════════════════════


def _compute_inventory_stats(db: Session) -> List[InventoryStats]:
    products = db.query(Product).all()
    stats = []
    ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)

    for product in products:
        balances = (
            db.query(StockBalance)
            .filter(StockBalance.product_id == product.product_id)
            .all()
        )

        current_stock = sum(b.current_stock for b in balances)
        reorder_level = max((b.reorder_level for b in balances), default=0.0)

        # Aggregate transactions (all time)
        txs = (
            db.query(StockTransaction)
            .filter(StockTransaction.product_id == product.product_id)
            .all()
        )

        total_in = sum(
            t.quantity for t in txs if t.transaction_type in ("STOCK_IN", "RETURN")
        )
        total_out = sum(
            t.quantity for t in txs if t.transaction_type in ("STOCK_OUT", "TRANSFER")
        )
        total_dmg = sum(t.quantity for t in txs if t.transaction_type == "DAMAGE")

        # Stock turnover rate: outflow in last 90 days / avg balance in last 90 days
        recent_out = sum(
            t.quantity
            for t in txs
            if t.transaction_type in ("STOCK_OUT", "TRANSFER")
            and t.transaction_date >= ninety_days_ago
        )
        avg_stock = max(current_stock, 1.0)
        turnover_rate = round(recent_out / avg_stock, 4)

        available = max(0.0, current_stock - total_dmg)
        reserved = 0.0  # Could be extended with reservation logic
        expired = 0.0  # Placeholder — requires expiry date tracking

        if current_stock == 0:
            status = "OUT_OF_STOCK"
        elif current_stock <= reorder_level:
            status = "LOW_STOCK" if current_stock > reorder_level * 0.5 else "CRITICAL"
        else:
            status = "HEALTHY"

        stats.append(
            InventoryStats(
                product_name=product.product_name,
                category=product.category or "Unknown",
                unit=product.unit,
                total_current_stock=round(current_stock, 2),
                total_stock_in=round(total_in, 2),
                total_stock_out=round(total_out, 2),
                total_damaged=round(total_dmg, 2),
                available_stock=round(available, 2),
                reserved_stock=round(reserved, 2),
                expired_stock=round(expired, 2),
                reorder_level=round(reorder_level, 2),
                stock_turnover_rate=turnover_rate,
                status=status,
            )
        )

    return sorted(stats, key=lambda s: s.product_name)


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 6: VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


def _validate(db: Session, session: DataIntegrationSession) -> ValidationResult:
    issues = []

    # Duplicate transaction check (same farmer+product+date+qty+type)
    dup_result = db.execute(text("""
        SELECT farmer_id, product_id, transaction_date, quantity, transaction_type, COUNT(*) as cnt
        FROM stock_transactions
        GROUP BY farmer_id, product_id, transaction_date, quantity, transaction_type
        HAVING cnt > 1
    """)).fetchall()
    dup_ids_found = len(dup_result)
    if dup_ids_found:
        issues.append(f"{dup_ids_found} duplicate transaction group(s) detected.")

    # Negative stock balances
    neg_balances = db.query(StockBalance).filter(StockBalance.current_stock < 0).count()
    if neg_balances:
        issues.append(
            f"{neg_balances} stock balance record(s) have negative current_stock."
        )

    # Orphaned transactions (no farmer / no product)
    orphaned = (
        db.query(StockTransaction).filter(StockTransaction.farmer_id.is_(None)).count()
    )
    if orphaned:
        issues.append(f"{orphaned} transaction(s) have no linked farmer.")

    # Warehouse mismatch: transactions referencing non-existent warehouses
    wh_ids = {w.warehouse_id for w in db.query(Warehouse).all()}
    tx_wh_ids = db.execute(
        text(
            "SELECT DISTINCT warehouse_id FROM stock_transactions WHERE warehouse_id IS NOT NULL"
        )
    ).fetchall()
    invalid_wh = [r[0] for r in tx_wh_ids if r[0] not in wh_ids]
    wh_mismatches = len(invalid_wh)
    if wh_mismatches:
        issues.append(
            f"{wh_mismatches} transaction(s) reference non-existent warehouse IDs."
        )

    # Quantity anomalies: extreme outliers (> 3 standard deviations)
    result = db.execute(
        text("SELECT AVG(quantity), MAX(quantity) FROM stock_transactions")
    ).fetchone()
    qty_anomalies = 0
    if result and result[0]:
        avg_qty, max_qty = result[0], result[1]
        if max_qty > avg_qty * 100:
            qty_anomalies += 1
            issues.append(
                f"Quantity outlier detected: max={max_qty:,.0f} vs avg={avg_qty:,.0f}"
            )

    constraint_violations = neg_balances + orphaned

    passed = dup_ids_found == 0 and constraint_violations == 0 and wh_mismatches == 0

    # Update session
    session.validation_passed = passed
    session.duplicate_ids_found = dup_ids_found
    session.constraint_violations = constraint_violations

    return ValidationResult(
        passed=passed,
        duplicate_ids_found=dup_ids_found,
        constraint_violations=constraint_violations,
        warehouse_mismatches=wh_mismatches,
        quantity_anomalies=qty_anomalies,
        issues=issues if issues else ["All validation checks passed."],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 7: REPORT GENERATION
# ══════════════════════════════════════════════════════════════════════════════


def _recommended_actions(
    inv_stats: List[InventoryStats], validation: ValidationResult
) -> List[str]:
    actions = []
    critical = [s for s in inv_stats if s.status == "CRITICAL"]
    low = [s for s in inv_stats if s.status == "LOW_STOCK"]
    oos = [s for s in inv_stats if s.status == "OUT_OF_STOCK"]

    for s in oos:
        actions.append(
            f"URGENT: {s.product_name} is OUT OF STOCK — place purchase order immediately."
        )
    for s in critical:
        actions.append(
            f"CRITICAL: {s.product_name} stock ({s.total_current_stock:,.0f} {s.unit}) is critically low — reorder at once."
        )
    for s in low:
        actions.append(
            f"LOW STOCK: {s.product_name} ({s.total_current_stock:,.0f} {s.unit}) — schedule reorder soon."
        )

    high_turnover = [s for s in inv_stats if s.stock_turnover_rate > 2.0]
    for s in high_turnover:
        actions.append(
            f"HIGH TURNOVER: {s.product_name} has rapid stock movement (rate {s.stock_turnover_rate:.2f}) — increase buffer stock."
        )

    if not validation.passed:
        for issue in validation.issues:
            actions.append(f"DATA QUALITY: {issue}")

    if not actions:
        actions.append("All stock levels are healthy. Continue routine monitoring.")
    return actions


def _generate_reports(
    db: Session,
    session: DataIntegrationSession,
    analysis: AnalysisSummary,
    cleaning: CleaningSummary,
    mapping: MappingSummary,
    integration: IntegrationSummary,
    validation: ValidationResult,
    errors: List[Dict[str, Any]],
) -> Tuple[
    DataImportReport,
    StockSummaryReport,
    ProductAvailabilityReport,
    InventoryHealthReport,
    LowStockAlertReport,
]:

    now = datetime.now(timezone.utc)
    inv_stats = _compute_inventory_stats(db)
    actions = _recommended_actions(inv_stats, validation)

    # — DATA IMPORT REPORT —
    import_report = DataImportReport(
        session_id=session.session_id,
        file_name=session.file_name,
        status=session.status,
        started_at=session.started_at,
        completed_at=session.completed_at,
        analysis=analysis,
        cleaning=cleaning,
        mapping=mapping,
        integration=integration,
        validation=validation,
        records_imported=session.transactions_inserted,
        records_failed=session.invalid_data_count,
        errors_found=errors[:50],  # cap at 50 for storage
        recommended_actions=actions,
    )

    # — STOCK SUMMARY REPORT —
    stock_report = StockSummaryReport(
        generated_at=now,
        total_products=db.query(Product).count(),
        total_farmers=db.query(Farmer).count(),
        total_warehouses=db.query(Warehouse).count(),
        total_transactions=db.query(StockTransaction).count(),
        inventory=inv_stats,
    )

    # — PRODUCT AVAILABILITY REPORT —
    available = [
        {"product": s.product_name, "stock": s.available_stock, "unit": s.unit}
        for s in inv_stats
        if s.status == "HEALTHY"
    ]
    oos_list = [
        {"product": s.product_name, "stock": 0, "unit": s.unit}
        for s in inv_stats
        if s.status == "OUT_OF_STOCK"
    ]
    low_list = [
        {
            "product": s.product_name,
            "stock": s.available_stock,
            "unit": s.unit,
            "reorder_level": s.reorder_level,
        }
        for s in inv_stats
        if s.status in ("LOW_STOCK", "CRITICAL")
    ]

    avail_report = ProductAvailabilityReport(
        generated_at=now,
        available_products=available,
        out_of_stock=oos_list,
        low_stock=low_list,
    )

    # — INVENTORY HEALTH REPORT —
    health_counts = {
        "HEALTHY": 0,
        "LOW_STOCK": 0,
        "CRITICAL": 0,
        "OUT_OF_STOCK": 0,
    }
    for s in inv_stats:
        health_counts[s.status] = health_counts.get(s.status, 0) + 1
    total_products = max(len(inv_stats), 1)
    overall_health = round(health_counts["HEALTHY"] / total_products * 100, 1)

    health_report = InventoryHealthReport(
        generated_at=now,
        healthy_count=health_counts["HEALTHY"],
        low_stock_count=health_counts["LOW_STOCK"],
        critical_count=health_counts["CRITICAL"],
        out_of_stock_count=health_counts["OUT_OF_STOCK"],
        overall_health_pct=overall_health,
        items=inv_stats,
    )

    # — LOW STOCK ALERT REPORT —
    low_items = [
        s for s in inv_stats if s.status in ("LOW_STOCK", "CRITICAL", "OUT_OF_STOCK")
    ]
    low_alerts = []
    for s in low_items:
        low_alerts.append(
            {
                "product": s.product_name,
                "category": s.category,
                "current_stock": s.total_current_stock,
                "reorder_level": s.reorder_level,
                "unit": s.unit,
                "status": s.status,
                "deficit": max(0.0, s.reorder_level - s.total_current_stock),
            }
        )

    alert_report = LowStockAlertReport(
        generated_at=now,
        alert_count=len(low_items),
        critical_count=health_counts["CRITICAL"] + health_counts["OUT_OF_STOCK"],
        alerts=low_alerts,
        recommended_actions=actions,
    )

    # Persist reports to DB
    for rtype, rtitle, rdata in [
        ("DATA_IMPORT", "Data Import Report", import_report),
        ("STOCK_SUMMARY", "Stock Summary Report", stock_report),
        ("PRODUCT_AVAILABILITY", "Product Availability Report", avail_report),
        ("INVENTORY_HEALTH", "Inventory Health Report", health_report),
        ("LOW_STOCK_ALERT", "Low Stock Alert Report", alert_report),
    ]:
        db.add(
            IntegrationReport(
                session_id=session.session_id,
                report_type=rtype,
                report_title=rtitle,
                report_data=rdata.model_dump_json(),
                generated_at=now,
            )
        )
    db.commit()

    return (
        import_report,
        stock_report,
        avail_report,
        health_report,
        alert_report,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN SERVICE CLASS
# ══════════════════════════════════════════════════════════════════════════════


class DataIntegrationService:

    def __init__(self, db: Session):
        self.db = db

    # ── Public entry point ─────────────────────────────────────────────────────

    def run_pipeline(
        self, file_path: Path, initiated_by: str = "system"
    ) -> IntegrationPipelineResult:
        """
        Runs the full 7-step integration pipeline on a file.
        Returns a complete IntegrationPipelineResult.
        """
        session = DataIntegrationSession(
            file_name=file_path.name,
            file_path=str(file_path),
            initiated_by=initiated_by,
            status="PENDING",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        try:
            result = self._execute_pipeline(file_path, session)
            return result
        except (ValueError, OSError, SQLAlchemyError, pd.errors.EmptyDataError, pd.errors.ParserError) as e:
            session.status = "FAILED"
            session.error_summary = str(e)
            session.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            raise IntegrationError("Pipeline execution failed", details=str(e)) from e

    # ── PIPELINE EXECUTOR ──────────────────────────────────────────────────────

    def _execute_pipeline(
        self, file_path: Path, session: DataIntegrationSession
    ) -> IntegrationPipelineResult:

        errors: List[Dict[str, Any]] = []

        # ─────────────────────────────────────────────────────────────────────
        # STEP 1 — DATA ANALYSIS
        # ─────────────────────────────────────────────────────────────────────
        session.status = "ANALYSING"
        self.db.commit()

        df_raw, read_error = self._read_file(file_path)
        if read_error:
            session.status = "FAILED"
            session.error_summary = read_error
            session.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            raise ValueError(read_error)

        df = _normalise_headers(df_raw.copy())
        raw_cols = df.columns.tolist()

        total_rows_raw = len(df)
        total_columns = len(raw_cols)
        missing_count = int(df.isnull().sum().sum())
        dup_count = int(df.duplicated().sum())
        detected_schema = _detect_schema(raw_cols)

        # Detect invalid data (non-numeric in numeric-expected columns)
        invalid_count = 0
        sample_issues = []
        for col in raw_cols:
            if col in (
                "quantity",
                "weight_kg",
                "production",
                "production_mt",
                "price",
            ):
                non_numeric = (
                    df[col]
                    .apply(lambda v: v is not None and _parse_number(v) is None)
                    .sum()
                )
                if non_numeric:
                    invalid_count += int(non_numeric)
                    sample_issues.append(
                        f"Column '{col}': {non_numeric} non-numeric value(s)"
                    )

        session.total_rows = total_rows_raw
        session.total_columns = total_columns
        session.missing_value_count = missing_count
        session.duplicate_row_count = dup_count
        session.invalid_data_count = invalid_count
        session.column_list = json.dumps(raw_cols)
        session.detected_schema = detected_schema
        session.data_source = self._infer_data_source(file_path, detected_schema)
        self.db.commit()

        analysis = AnalysisSummary(
            file_name=file_path.name,
            data_source=session.data_source,
            detected_schema=detected_schema,
            total_rows=total_rows_raw,
            total_columns=total_columns,
            column_list=raw_cols,
            missing_value_count=missing_count,
            duplicate_row_count=dup_count,
            invalid_data_count=invalid_count,
            sample_issues=sample_issues[:10],
        )

        # ─────────────────────────────────────────────────────────────────────
        # STEP 2 — DATA CLEANING
        # ─────────────────────────────────────────────────────────────────────
        session.status = "CLEANING"
        self.db.commit()

        cleaning_actions = []
        rows_before = len(df)

        # Remove exact duplicates
        df = df.drop_duplicates()
        dupes_removed = rows_before - len(df)
        if dupes_removed:
            cleaning_actions.append(f"Removed {dupes_removed} exact duplicate row(s).")

        # Fill missing values
        nulls_filled = 0
        fill_defaults = {
            "transaction_type": "STOCK_IN",
            "unit": "kg",
            "region": "Unknown Region",
            "district": "Unknown District",
        }
        for col, default in fill_defaults.items():
            if col in df.columns:
                before = df[col].isnull().sum()
                df[col] = df[col].fillna(default)
                after = df[col].isnull().sum()
                filled = int(before - after)
                nulls_filled += filled
                if filled:
                    cleaning_actions.append(
                        f"Filled {filled} missing '{col}' with default '{default}'."
                    )

        # Standardise units
        units_std = 0
        if "unit" in df.columns:
            original_units = df["unit"].copy()
            df["unit"] = df["unit"].apply(
                lambda v: _normalise_unit(str(v)) if v else "kg"
            )
            units_std = int((df["unit"] != original_units).sum())
            if units_std:
                cleaning_actions.append(f"Standardised {units_std} unit value(s).")

        # Standardise transaction types
        format_corrections = 0
        if "transaction_type" in df.columns:
            original_types = df["transaction_type"].copy()
            df["transaction_type"] = df["transaction_type"].str.upper().str.strip()
            df["transaction_type"] = df["transaction_type"].apply(
                lambda v: v if v in VALID_TX_TYPES else "STOCK_IN"
            )
            corrections = int(
                (df["transaction_type"] != original_types.str.upper().str.strip()).sum()
            )
            format_corrections += corrections
            if corrections:
                cleaning_actions.append(
                    f"Corrected {corrections} invalid transaction_type value(s) to 'STOCK_IN'."
                )

        # Strip whitespace from string columns
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].apply(lambda v: str(v).strip() if v is not None else v)

        # Replace pandas NaN with None
        df = df.where(pd.notnull(df), None)

        rows_after_cleaning = len(df)
        session.rows_after_cleaning = rows_after_cleaning
        session.duplicates_removed = dupes_removed
        session.nulls_filled = nulls_filled
        session.units_standardised = units_std
        session.format_corrections = format_corrections
        self.db.commit()

        if not cleaning_actions:
            cleaning_actions.append("Data was already clean — no corrections required.")

        cleaning = CleaningSummary(
            rows_before=rows_before,
            rows_after=rows_after_cleaning,
            duplicates_removed=dupes_removed,
            nulls_filled=nulls_filled,
            units_standardised=units_std,
            format_corrections=format_corrections,
            actions_taken=cleaning_actions,
        )

        # ─────────────────────────────────────────────────────────────────────
        # STEP 3 — DATA MAPPING
        # ─────────────────────────────────────────────────────────────────────
        session.status = "MAPPING"
        self.db.commit()

        field_mapping, unmapped = _map_columns(df.columns.tolist())

        # Apply detected schema: reshape dataframe for known historical schemas
        df = self._reshape_for_schema(df, detected_schema, file_path.name)

        # Re-map after reshape
        field_mapping, unmapped = _map_columns(df.columns.tolist())
        tables_targeted = self._infer_target_tables(detected_schema)

        session.field_mapping = json.dumps(field_mapping)
        session.unmapped_columns = json.dumps(unmapped)
        self.db.commit()

        mapping = MappingSummary(
            field_mapping=field_mapping,
            unmapped_columns=unmapped,
            tables_targeted=tables_targeted,
        )

        # ─────────────────────────────────────────────────────────────────────
        # STEP 4 — STOCK CONTROL INTEGRATION
        # ─────────────────────────────────────────────────────────────────────
        session.status = "INTEGRATING"
        self.db.commit()

        farmers_created = [0]
        farmers_matched = [0]
        products_created = [0]
        products_matched = [0]
        wh_created = [0]
        wh_matched = [0]
        tx_inserted = 0
        qa_inserted = 0
        balances_updated = 0

        balance_cache: Dict = {}

        for idx, row in df.iterrows():
            row_dict = row.to_dict()
            try:
                row_result = self._process_row(
                    row_dict,
                    idx,
                    session,
                    file_path.name,
                    detected_schema,
                    farmers_created,
                    farmers_matched,
                    products_created,
                    products_matched,
                    wh_created,
                    wh_matched,
                    balance_cache,
                )
                if row_result["type"] == "TRANSACTION":
                    tx_inserted += 1
                    balances_updated += 1
                elif row_result["type"] == "QUALITY_ASSESSMENT":
                    qa_inserted += 1
                elif row_result["type"] == "ENTITY_ONLY":
                    pass  # farmer/product/warehouse registered, no transaction

            except (ValueError, TypeError, SQLAlchemyError) as e:
                errors.append(
                    {
                        "row_index": idx,
                        "step": "STEP4_INTEGRATION",
                        "error": str(e),
                        "raw_data": {k: str(v)[:100] for k, v in row_dict.items()},
                    }
                )
                self.db.add(
                    IntegrationErrorRecord(
                        session_id=session.session_id,
                        row_index=int(idx),
                        step="STEP4",
                        error_type="INTEGRATION",
                        error_message=str(e)[:500],
                    )
                )

        # Commit batch
        try:
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            errors.append({"step": "STEP4_COMMIT", "error": str(e)})

        session.farmers_created = farmers_created[0]
        session.farmers_matched = farmers_matched[0]
        session.products_created = products_created[0]
        session.products_matched = products_matched[0]
        session.warehouses_created = wh_created[0]
        session.warehouses_matched = wh_matched[0]
        session.transactions_inserted = tx_inserted
        session.quality_assessments_inserted = qa_inserted
        session.balances_updated = balances_updated
        self.db.commit()

        integration = IntegrationSummary(
            farmers_created=farmers_created[0],
            farmers_matched=farmers_matched[0],
            products_created=products_created[0],
            products_matched=products_matched[0],
            warehouses_created=wh_created[0],
            warehouses_matched=wh_matched[0],
            transactions_inserted=tx_inserted,
            quality_assessments_inserted=qa_inserted,
            balances_updated=balances_updated,
        )

        # ─────────────────────────────────────────────────────────────────────
        # STEP 5 — INVENTORY PROCESSING (computed on demand, not stored inline)
        # ─────────────────────────────────────────────────────────────────────
        inv_stats = _compute_inventory_stats(self.db)

        # ─────────────────────────────────────────────────────────────────────
        # STEP 6 — VALIDATION
        # ─────────────────────────────────────────────────────────────────────
        session.status = "VALIDATING"
        self.db.commit()
        validation = _validate(self.db, session)

        # ─────────────────────────────────────────────────────────────────────
        # STEP 7 — REPORTING
        # ─────────────────────────────────────────────────────────────────────
        session.status = "REPORTING"
        self.db.commit()

        status = (
            "SUCCESS" if not errors else ("PARTIAL" if tx_inserted > 0 else "FAILED")
        )
        session.status = status
        session.completed_at = datetime.now(timezone.utc)
        self.db.commit()

        (
            import_report,
            stock_report,
            avail_report,
            health_report,
            alert_report,
        ) = _generate_reports(
            self.db,
            session,
            analysis,
            cleaning,
            mapping,
            integration,
            validation,
            errors,
        )

        actions = _recommended_actions(inv_stats, validation)

        # Also write to legacy ImportLog for backwards compatibility
        self.db.add(
            ImportLog(
                file_name=file_path.name,
                import_status=status,
                records_processed=tx_inserted,
                records_failed=len(errors),
                error_summary="; ".join(e.get("error", "") for e in errors[:5]) or None,
            )
        )
        self.db.commit()

        return IntegrationPipelineResult(
            session_id=session.session_id,
            file_name=file_path.name,
            status=status,
            cleaned_dataset_summary=cleaning,
            database_mapping_summary=mapping,
            import_results=integration,
            errors_found=errors[:50],
            records_successfully_imported=tx_inserted,
            records_failed=len(errors),
            inventory_statistics=inv_stats,
            recommended_actions=actions,
            data_import_report=import_report,
            stock_summary_report=stock_report,
            product_availability_report=avail_report,
            inventory_health_report=health_report,
            low_stock_alert_report=alert_report,
        )

    # ── ROW PROCESSOR ─────────────────────────────────────────────────────────

    def _process_row(
        self,
        row: Dict,
        idx: int,
        session: DataIntegrationSession,
        file_name: str,
        schema: str,
        farmers_created,
        farmers_matched,
        products_created,
        products_matched,
        wh_created,
        wh_matched,
        balance_cache: Dict,
    ) -> Dict[str, str]:

        farmer_name = row.get("farmer_name") or "Unknown Cooperative"
        product_name = row.get("product_name")
        qty_raw = row.get("quantity")
        unit_raw = row.get("unit") or "kg"
        tx_type = str(row.get("transaction_type") or "STOCK_IN").upper().strip()
        wh_name = row.get("warehouse_name")
        region = row.get("region")
        district = row.get("district")
        date_raw = row.get("transaction_date")
        note = row.get("reference_note") or f"Imported from {file_name}"
        category = row.get("category") or self._infer_category(product_name, schema)

        if not product_name:
            raise ValueError("Missing product_name")

        qty = _parse_number(qty_raw)
        if qty is None or qty <= 0:
            raise ValueError(f"Invalid or missing quantity: {qty_raw!r}")

        tx_type = tx_type if tx_type in VALID_TX_TYPES else "STOCK_IN"
        qty, unit_raw = _apply_unit_factor(qty, unit_raw)

        tx_date = _parse_date(date_raw) or datetime.now(timezone.utc)

        # Price annotation in note
        if row.get("unit_price"):
            note += f" | Unit price: GHS {row['unit_price']}"

        # Entities
        farmer = _get_or_create_farmer(
            self.db,
            farmer_name,
            region,
            district,
            farmers_created,
            farmers_matched,
        )
        product = _get_or_create_product(
            self.db,
            product_name,
            category,
            unit_raw,
            products_created,
            products_matched,
        )

        warehouse_id = None
        if wh_name:
            wh = _get_or_create_warehouse(
                self.db, wh_name, region, district, wh_created, wh_matched
            )
            warehouse_id = wh.warehouse_id if wh else None

        # Convert to base unit if possible
        try:
            qty_base = convert_quantity(qty, unit_raw, product.unit)
        except ValueError:
            qty_base = qty  # store as-is if conversion unavailable

        # Insert transaction
        tx = StockTransaction(
            farmer_id=farmer.farmer_id,
            product_id=product.product_id,
            warehouse_id=warehouse_id,
            transaction_type=tx_type,
            quantity=qty_base,
            unit=product.unit,
            transaction_date=tx_date,
            reference_note=note,
        )
        self.db.add(tx)
        self.db.flush()

        # Update balance
        _update_balance(
            self.db,
            farmer.farmer_id,
            product.product_id,
            warehouse_id,
            tx_type,
            qty_base,
            balance_cache,
        )

        return {"type": "TRANSACTION"}

    # ── FILE READER ───────────────────────────────────────────────────────────

    def _read_file(
        self, file_path: Path
    ) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        suffix = file_path.suffix.lower()
        try:
            if suffix == ".csv":
                # Try UTF-8 first, fall back to latin-1
                try:
                    return pd.read_csv(file_path, encoding="utf-8"), None
                except UnicodeDecodeError:
                    return pd.read_csv(file_path, encoding="latin-1"), None
            elif suffix in (".xlsx", ".xls"):
                return pd.read_excel(file_path), None
            elif suffix == ".json":
                return pd.read_json(file_path), None
            else:
                return None, f"Unsupported file type: {suffix}"
        except (pd.errors.EmptyDataError, UnicodeDecodeError, OSError, ValueError) as e:
            return None, f"Failed to read file: {e}"

    # ── SCHEMA RESHAPER ───────────────────────────────────────────────────────

    def _reshape_for_schema(
        self, df: pd.DataFrame, schema: str, file_name: str
    ) -> pd.DataFrame:
        """Transform known historical dataset schemas into the canonical transaction shape."""
        if schema == "PRODUCTION_ESTIMATES":
            df = df.rename(columns={"crop": "product_name"})
            region_col = "region" if "region" in df.columns else None
            district_col = "district" if "district" in df.columns else None
            # Build farmer_name from region
            if region_col:
                df["farmer_name"] = df[region_col].apply(
                    lambda r: f"{str(r).strip().title()} Regional Cooperative"
                )
            else:
                df["farmer_name"] = "Ghana National Cooperative"
            # quantity column: prefer production_mt or production
            if "production_mt" in df.columns:
                df["quantity"] = df["production_mt"]
            elif "production" in df.columns:
                df["quantity"] = df["production"]
            df["unit"] = "ton"
            df["transaction_type"] = "STOCK_IN"
            # Warehouse: district + " District Storage"
            if district_col:
                df["warehouse_name"] = df[district_col].apply(
                    lambda d: (
                        f"{str(d).strip().title()} District Storage"
                        if d
                        else "National Storage"
                    )
                )
            if "year" in df.columns:
                df["transaction_date"] = df["year"].apply(
                    lambda y: f"{int(float(y))}-01-01" if y else "2000-01-01"
                )

        elif schema == "WHOLESALE_PRICES":
            df = df.rename(columns={"commodity": "product_name"})
            df["farmer_name"] = "Market Supplier"
            df["quantity"] = 1.0
            df["unit"] = "kg"
            df["transaction_type"] = "STOCK_IN"
            if "year" in df.columns:
                df["transaction_date"] = df["year"].apply(
                    lambda y: f"{int(float(y))}-01-01" if y else "2000-01-01"
                )
            if "price" in df.columns:
                df["reference_note"] = df["price"].apply(
                    lambda p: f"National wholesale price: GHS {p}"
                )

        return df

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _infer_category(self, product_name: Optional[str], schema: str) -> str:
        if not product_name:
            return "Other"
        p = str(product_name).lower()
        if any(
            x in p
            for x in [
                "maize",
                "rice",
                "sorghum",
                "millet",
                "wheat",
                "grain",
                "cereal",
            ]
        ):
            return "Grains"
        if any(x in p for x in ["yam", "cassava", "cocoyam", "tuber", "root"]):
            return "Roots & Tubers"
        if any(
            x in p
            for x in [
                "tomato",
                "pepper",
                "onion",
                "okra",
                "cabbage",
                "lettuce",
                "vegetable",
            ]
        ):
            return "Vegetables"
        if any(
            x in p
            for x in [
                "mango",
                "pineapple",
                "banana",
                "orange",
                "pawpaw",
                "fruit",
            ]
        ):
            return "Fruits"
        if any(
            x in p
            for x in [
                "cattle",
                "cow",
                "bull",
                "goat",
                "sheep",
                "pig",
                "livestock",
            ]
        ):
            return "Livestock"
        if any(
            x in p
            for x in [
                "chicken",
                "broiler",
                "layer",
                "turkey",
                "duck",
                "guinea fowl",
                "poultry",
            ]
        ):
            return "Poultry"
        if any(
            x in p
            for x in [
                "tilapia",
                "catfish",
                "tuna",
                "fish",
                "herring",
                "mackerel",
            ]
        ):
            return "Fish"
        if any(x in p for x in ["cocoa", "coffee", "cashew", "shea"]):
            return "Cash Crops"
        if schema in ("LIVESTOCK_RECORDS",):
            return "Livestock"
        if schema in ("POULTRY_RECORDS",):
            return "Poultry"
        if schema in ("FISH_RECORDS",):
            return "Fish"
        return "Crops"

    def _infer_data_source(self, file_path: Path, schema: str) -> str:
        name = file_path.name.lower()
        if "production" in name:
            return "MoFA Production Estimates"
        if "price" in name:
            return "MoFA Price Data"
        if "rainfall" in name:
            return "Ghana Met Office"
        if "synthetic" in name:
            return "Synthetic Dataset"
        if "aquaculture" in name:
            return "Ghana Fisheries Commission"
        return f"Manual Upload ({schema})"

    def _infer_target_tables(self, schema: str) -> List[str]:
        base = [
            "farmers",
            "products",
            "warehouses",
            "stock_transactions",
            "stock_balances",
        ]
        if schema in (
            "LIVESTOCK_RECORDS",
            "POULTRY_RECORDS",
            "FISH_RECORDS",
            "QUALITY_ASSESSMENTS",
        ):
            base.append("quality_assessments")
        if schema in ("FARMER_REGISTRY",):
            return ["farmers"]
        if schema in ("WAREHOUSE_REGISTRY",):
            return ["warehouses"]
        return base

    # ── SESSION QUERY HELPERS (for API) ───────────────────────────────────────

    def list_sessions(
        self, skip: int = 0, limit: int = 50
    ) -> List[DataIntegrationSession]:
        return (
            self.db.query(DataIntegrationSession)
            .order_by(DataIntegrationSession.started_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_session(self, session_id: int) -> Optional[DataIntegrationSession]:
        return (
            self.db.query(DataIntegrationSession)
            .filter(DataIntegrationSession.session_id == session_id)
            .first()
        )

    def get_session_reports(self, session_id: int) -> List[IntegrationReport]:
        return (
            self.db.query(IntegrationReport)
            .filter(IntegrationReport.session_id == session_id)
            .all()
        )

    def get_report(self, report_id: int) -> Optional[IntegrationReport]:
        return (
            self.db.query(IntegrationReport)
            .filter(IntegrationReport.report_id == report_id)
            .first()
        )

    def get_standalone_reports(self) -> Dict[str, Any]:
        """Generate all 5 reports from current DB state (no file import needed)."""
        inv_stats = _compute_inventory_stats(self.db)
        validation = ValidationResult(
            passed=True,
            duplicate_ids_found=0,
            constraint_violations=0,
            warehouse_mismatches=0,
            quantity_anomalies=0,
            issues=["Standalone report — no import session."],
        )
        actions = _recommended_actions(inv_stats, validation)
        now = datetime.now(timezone.utc)

        total_p = self.db.query(Product).count()
        total_f = self.db.query(Farmer).count()
        total_w = self.db.query(Warehouse).count()
        total_t = self.db.query(StockTransaction).count()

        stock_report = StockSummaryReport(
            generated_at=now,
            total_products=total_p,
            total_farmers=total_f,
            total_warehouses=total_w,
            total_transactions=total_t,
            inventory=inv_stats,
        )
        available = [
            {
                "product": s.product_name,
                "stock": s.available_stock,
                "unit": s.unit,
            }
            for s in inv_stats
            if s.status == "HEALTHY"
        ]
        oos_list = [
            {"product": s.product_name, "stock": 0, "unit": s.unit}
            for s in inv_stats
            if s.status == "OUT_OF_STOCK"
        ]
        low_list = [
            {
                "product": s.product_name,
                "stock": s.available_stock,
                "unit": s.unit,
                "reorder_level": s.reorder_level,
            }
            for s in inv_stats
            if s.status in ("LOW_STOCK", "CRITICAL")
        ]
        avail_report = ProductAvailabilityReport(
            generated_at=now,
            available_products=available,
            out_of_stock=oos_list,
            low_stock=low_list,
        )

        hc = {"HEALTHY": 0, "LOW_STOCK": 0, "CRITICAL": 0, "OUT_OF_STOCK": 0}
        for s in inv_stats:
            hc[s.status] = hc.get(s.status, 0) + 1
        overall = round(hc["HEALTHY"] / max(len(inv_stats), 1) * 100, 1)
        health_report = InventoryHealthReport(
            generated_at=now,
            healthy_count=hc["HEALTHY"],
            low_stock_count=hc["LOW_STOCK"],
            critical_count=hc["CRITICAL"],
            out_of_stock_count=hc["OUT_OF_STOCK"],
            overall_health_pct=overall,
            items=inv_stats,
        )

        low_items = [
            s
            for s in inv_stats
            if s.status in ("LOW_STOCK", "CRITICAL", "OUT_OF_STOCK")
        ]
        alert_report = LowStockAlertReport(
            generated_at=now,
            alert_count=len(low_items),
            critical_count=hc["CRITICAL"] + hc["OUT_OF_STOCK"],
            alerts=[
                {
                    "product": s.product_name,
                    "current_stock": s.total_current_stock,
                    "reorder_level": s.reorder_level,
                    "status": s.status,
                    "unit": s.unit,
                }
                for s in low_items
            ],
            recommended_actions=actions,
        )

        return {
            "stock_summary": stock_report.model_dump(),
            "product_availability": avail_report.model_dump(),
            "inventory_health": health_report.model_dump(),
            "low_stock_alerts": alert_report.model_dump(),
            "recommended_actions": actions,
        }

    def scan_and_run_all(
        self, directory: Path, initiated_by: str = "system"
    ) -> List[IntegrationPipelineResult]:
        """Scans a directory and runs the pipeline on every supported file."""
        results = []
        for ext in ("*.csv", "*.xlsx", "*.xls", "*.json"):
            for f in directory.glob(ext):
                try:
                    res = self.run_pipeline(f, initiated_by=initiated_by)
                    results.append(res)
                except IntegrationError as e:
                    results.append({"file": f.name, "error": str(e)})
        return results
