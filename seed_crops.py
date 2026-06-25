"""
seed_crops.py
=============
Seeds the agriculture_stock.db with:
  - The 4 focus crops: Tomato, Yam, Maize, Rice (with correct units)
  - 10 Ghana regional warehouses
  - Imports production data from the CSV dataset for the 4 focus crops

Run from the project root:
    python seed_crops.py
"""

import sys
import os
import re
from pathlib import Path
from datetime import datetime

# Make sure app/ is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from sqlalchemy.orm import Session

from app.database import engine, Base, SessionLocal
from app.models.stock_models import Farmer, Product, Warehouse, StockTransaction, StockBalance, StockAlert, ImportLog

# ── Ensure all tables exist ──────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)


# ── Focus crops definition ───────────────────────────────────────────────────
FOCUS_CROPS = [
    {
        "product_name": "Tomato",
        "category": "Vegetables",
        "unit": "crate",          # Ghana standard: ~25 kg crate
        "description": "Fresh garden tomatoes (standard 25 kg crate)",
        "dataset_names": ["TOMATO", "TOMATOES"],
        "reorder_level": 50.0,
    },
    {
        "product_name": "Yam",
        "category": "Roots & Tubers",
        "unit": "kg",
        "description": "Yam tubers (puna/water yam)",
        "dataset_names": ["YAM"],
        "reorder_level": 500.0,
    },
    {
        "product_name": "Maize",
        "category": "Grains",
        "unit": "kg",
        "description": "Maize grain (white and yellow varieties)",
        "dataset_names": ["MAIZE", "MAIZE "],
        "reorder_level": 1000.0,
    },
    {
        "product_name": "Rice",
        "category": "Grains",
        "unit": "kg",
        "description": "Paddy/milled rice",
        "dataset_names": ["RICE", "RICE "],
        "reorder_level": 800.0,
    },
]

# ── Regional warehouses for Ghana ────────────────────────────────────────────
WAREHOUSES = [
    {"warehouse_name": "Ashanti Regional Store",       "region": "Ashanti",       "district": "Kumasi Metro",         "capacity": 50000.0},
    {"warehouse_name": "Greater Accra Storage Hub",    "region": "Greater Accra", "district": "Accra Metro",          "capacity": 40000.0},
    {"warehouse_name": "Brong-Ahafo Grain Depot",      "region": "Bono",          "district": "Sunyani Municipal",    "capacity": 35000.0},
    {"warehouse_name": "Northern Region Agro Store",   "region": "Northern",      "district": "Tamale Metro",         "capacity": 60000.0},
    {"warehouse_name": "Volta Region Produce Store",   "region": "Volta",         "district": "Ho Municipal",         "capacity": 30000.0},
    {"warehouse_name": "Eastern Region Farm Hub",      "region": "Eastern",       "district": "Koforidua Municipal",  "capacity": 28000.0},
    {"warehouse_name": "Western Region Cold Store",    "region": "Western",       "district": "Sekondi-Takoradi",     "capacity": 25000.0},
    {"warehouse_name": "Upper East Grain Silo",        "region": "Upper East",    "district": "Bolgatanga Municipal", "capacity": 45000.0},
    {"warehouse_name": "Upper West Storage Centre",    "region": "Upper West",    "district": "Wa Municipal",         "capacity": 40000.0},
    {"warehouse_name": "Central Region Produce Hub",   "region": "Central",       "district": "Cape Coast Metro",     "capacity": 22000.0},
]

# ── Regional cooperative farmers (one per region in the dataset) ─────────────
REGION_FARMERS = [
    {"full_name": "Western Regional Cooperative",       "region": "Western",      "district": "Various Districts"},
    {"full_name": "Greater Accra Regional Cooperative", "region": "Greater Accra","district": "Various Districts"},
    {"full_name": "Ashanti Regional Cooperative",       "region": "Ashanti",      "district": "Various Districts"},
    {"full_name": "Brong-Ahafo Regional Cooperative",   "region": "Bono",         "district": "Various Districts"},
    {"full_name": "Northern Regional Cooperative",      "region": "Northern",     "district": "Various Districts"},
    {"full_name": "Upper East Regional Cooperative",    "region": "Upper East",   "district": "Various Districts"},
    {"full_name": "Upper West Regional Cooperative",    "region": "Upper West",   "district": "Various Districts"},
    {"full_name": "Volta Regional Cooperative",         "region": "Volta",        "district": "Various Districts"},
    {"full_name": "Eastern Regional Cooperative",       "region": "Eastern",      "district": "Various Districts"},
    {"full_name": "Central Regional Cooperative",       "region": "Central",      "district": "Various Districts"},
    {"full_name": "Bono East Regional Cooperative",     "region": "Bono East",    "district": "Various Districts"},
    {"full_name": "Oti Regional Cooperative",           "region": "Oti",          "district": "Various Districts"},
    {"full_name": "Savannah Regional Cooperative",      "region": "Savannah",     "district": "Various Districts"},
    {"full_name": "North East Regional Cooperative",    "region": "North East",   "district": "Various Districts"},
    {"full_name": "Ahafo Regional Cooperative",         "region": "Ahafo",        "district": "Various Districts"},
    {"full_name": "Western North Regional Cooperative", "region": "Western North","district": "Various Districts"},
]


def get_or_create(db: Session, model, filter_kwargs: dict, create_kwargs: dict = None):
    """Generic get-or-create helper — commits immediately to avoid pending-state issues."""
    instance = db.query(model).filter_by(**filter_kwargs).first()
    if instance:
        return instance, False
    kwargs = {**filter_kwargs, **(create_kwargs or {})}
    instance = model(**kwargs)
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance, True


def normalize_region_name(raw_region: str) -> str:
    """Maps old region names from dataset to modern Ghana region names."""
    mapping = {
        "BRONG AHAFO": "Bono",
        "BRONG-AHAFO": "Bono",
        "NORTHERN": "Northern",
        "UPPER EAST": "Upper East",
        "UPPER WEST": "Upper West",
        "ASHANTI": "Ashanti",
        "WESTERN": "Western",
        "CENTRAL": "Central",
        "EASTERN": "Eastern",
        "VOLTA": "Volta",
        "GREATER ACCRA": "Greater Accra",
    }
    return mapping.get(raw_region.strip().upper(), raw_region.strip().title())


def parse_number(val) -> float:
    """Parses numbers that may contain commas."""
    if val is None:
        return 0.0
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def seed_focus_products(db: Session) -> dict:
    """Ensures the 4 focus crop products exist. Returns name→Product map."""
    print("\n── Seeding focus crop products ──")
    product_map = {}
    for crop in FOCUS_CROPS:
        product, created = get_or_create(
            db,
            Product,
            {"product_name": crop["product_name"]},
            {
                "category": crop["category"],
                "unit": crop["unit"],
                "description": crop["description"],
            }
        )
        if created:
            print(f"  ✓ Created product: {crop['product_name']} (unit={crop['unit']})")
        else:
            # Update unit/description in case they differ
            product.unit = crop["unit"]
            product.description = crop["description"]
            product.category = crop["category"]
            print(f"  → Product already exists, confirmed: {crop['product_name']}")
        product_map[crop["product_name"]] = product

    db.commit()
    return product_map


def seed_warehouses(db: Session) -> dict:
    """Ensures all regional warehouses exist. Returns name→Warehouse map."""
    print("\n── Seeding regional warehouses ──")
    wh_map = {}
    for wh in WAREHOUSES:
        warehouse, created = get_or_create(
            db,
            Warehouse,
            {"warehouse_name": wh["warehouse_name"]},
            {
                "region": wh["region"],
                "district": wh["district"],
                "capacity": wh["capacity"],
            }
        )
        if created:
            print(f"  ✓ Created warehouse: {wh['warehouse_name']}")
        else:
            print(f"  → Warehouse already exists: {wh['warehouse_name']}")
        wh_map[wh["warehouse_name"]] = warehouse

    db.commit()
    return wh_map


def seed_regional_farmers(db: Session) -> dict:
    """Ensures all regional cooperative farmers exist. Returns region→Farmer map."""
    print("\n── Seeding regional cooperative farmers ──")
    farmer_map = {}
    for f in REGION_FARMERS:
        farmer, created = get_or_create(
            db,
            Farmer,
            {"full_name": f["full_name"]},
            {
                "region": f["region"],
                "district": f["district"],
                "farm_name": f"{f['region']} Regional Agricultural Cooperative",
            }
        )
        if created:
            print(f"  ✓ Created farmer: {f['full_name']}")
        else:
            print(f"  → Farmer already exists: {f['full_name']}")
        farmer_map[f["region"]] = farmer

    db.commit()
    return farmer_map


def get_warehouse_for_region(region_name: str, wh_map: dict) -> Warehouse:
    """Maps a dataset region name to the closest regional warehouse."""
    region_to_wh = {
        "Western":      "Western Region Cold Store",
        "Greater Accra": "Greater Accra Storage Hub",
        "Ashanti":      "Ashanti Regional Store",
        "Bono":         "Brong-Ahafo Grain Depot",
        "Northern":     "Northern Region Agro Store",
        "Upper East":   "Upper East Grain Silo",
        "Upper West":   "Upper West Storage Centre",
        "Volta":        "Volta Region Produce Store",
        "Eastern":      "Eastern Region Farm Hub",
        "Central":      "Central Region Produce Hub",
    }
    wh_name = region_to_wh.get(region_name, "Greater Accra Storage Hub")
    return wh_map.get(wh_name)


def import_production_data(db: Session, product_map: dict, farmer_map: dict, wh_map: dict):
    """
    Reads the PRODUCTION ESTIMATES CSV and imports MAIZE, RICE, YAM, TOMATO rows
    as STOCK_IN transactions in the stock system.
    Production is in metric tons (MT) — converted to kg (×1000) for weight-based crops,
    or to crates (÷0.025) for Tomato.
    """
    dataset_path = Path("datesets folder") / "agricultural-production-estimates-1993-2017-All-2026-06-04_2242 (1)" / "PRODUCTION ESTIMATES.csv"

    if not dataset_path.exists():
        print(f"\n⚠ Dataset not found: {dataset_path}")
        return

    print(f"\n── Importing production data from: {dataset_path.name} ──")
    df = pd.read_csv(dataset_path)

    # Normalize column names
    df.columns = [c.strip().upper() for c in df.columns]

    # Build lookup: dataset crop name → (Product object, conversion factor from MT)
    # 1 MT = 1000 kg; 1 MT tomato ÷ 0.025 t/crate = 40 crates
    crop_lookup = {}
    for crop_def in FOCUS_CROPS:
        for ds_name in crop_def["dataset_names"]:
            product = product_map.get(crop_def["product_name"])
            if crop_def["unit"] == "crate":
                # 1 MT = 40 crates (each ~25 kg)
                factor = 40.0
                tx_unit = "crate"
            else:
                # 1 MT = 1000 kg
                factor = 1000.0
                tx_unit = "kg"
            crop_lookup[ds_name.strip().upper()] = (product, factor, tx_unit)

    # Filter to focus crops only
    df["CROP_CLEAN"] = df["CROP"].str.strip().str.upper()
    df_focus = df[df["CROP_CLEAN"].isin(crop_lookup.keys())].copy()

    print(f"  Total rows in dataset: {len(df)}")
    print(f"  Rows for focus crops:  {len(df_focus)}")

    imported = 0
    skipped = 0
    errors = []

    # Pre-load all existing balances into a dict keyed by (farmer_id, product_id, warehouse_id)
    # to avoid repeated queries and UNIQUE constraint races
    balance_cache: dict = {}
    existing_balances = db.query(StockBalance).all()
    for b in existing_balances:
        balance_cache[(b.farmer_id, b.product_id, b.warehouse_id)] = b

    for _, row in df_focus.iterrows():
        try:
            crop_clean = str(row["CROP_CLEAN"]).strip()
            region_raw = str(row.get("REGION", "Unknown")).strip()
            district   = str(row.get("DISTRICT", "Unknown District")).strip()
            year       = str(row.get("YEAR", "2000")).strip()
            prod_mt    = parse_number(row.get("PRODUCTION (MT)", 0))

            if prod_mt <= 0:
                skipped += 1
                continue

            product, factor, tx_unit = crop_lookup[crop_clean]
            region_modern = normalize_region_name(region_raw)
            quantity_converted = prod_mt * factor

            # Get or use fallback farmer
            farmer = farmer_map.get(region_modern)
            if not farmer:
                farmer = farmer_map.get("Greater Accra")  # fallback

            # Get warehouse
            warehouse = get_warehouse_for_region(region_modern, wh_map)
            warehouse_id = warehouse.warehouse_id if warehouse else None

            # Parse year to Jan 1 of that year
            try:
                tx_date = datetime(int(float(year)), 1, 1)
            except (ValueError, TypeError):
                tx_date = datetime(2000, 1, 1)

            ref_note = f"Production estimate {year} - {district}"

            # Check if this exact transaction already exists (idempotency)
            existing = db.query(StockTransaction).filter(
                StockTransaction.farmer_id == farmer.farmer_id,
                StockTransaction.product_id == product.product_id,
                StockTransaction.warehouse_id == warehouse_id,
                StockTransaction.transaction_date == tx_date,
                StockTransaction.reference_note == ref_note
            ).first()

            if existing:
                skipped += 1
                continue

            # Insert transaction
            tx = StockTransaction(
                farmer_id=farmer.farmer_id,
                product_id=product.product_id,
                warehouse_id=warehouse_id,
                transaction_type="STOCK_IN",
                quantity=quantity_converted,
                unit=tx_unit,
                transaction_date=tx_date,
                reference_note=ref_note,
            )
            db.add(tx)

            # Update or create stock balance using cache to avoid UNIQUE conflicts
            bal_key = (farmer.farmer_id, product.product_id, warehouse_id)
            balance = balance_cache.get(bal_key)

            if not balance:
                reorder = next(
                    c["reorder_level"] for c in FOCUS_CROPS
                    if product_map.get(c["product_name"]) == product
                )
                balance = StockBalance(
                    farmer_id=farmer.farmer_id,
                    product_id=product.product_id,
                    warehouse_id=warehouse_id,
                    opening_stock=0.0,
                    current_stock=0.0,
                    reorder_level=reorder,
                )
                db.add(balance)
                db.flush()  # get the balance_id assigned
                balance_cache[bal_key] = balance

            balance.current_stock += quantity_converted
            balance.last_updated = datetime.utcnow()

            imported += 1

            # Commit every 500 rows to avoid massive transactions
            if imported % 500 == 0:
                db.commit()
                print(f"    ... {imported} rows committed so far ...")

        except Exception as e:
            db.rollback()
            skipped += 1
            errors.append(f"Row error: {str(e)}")
            # Reload balance cache after rollback
            balance_cache = {}
            existing_balances = db.query(StockBalance).all()
            for b in existing_balances:
                balance_cache[(b.farmer_id, b.product_id, b.warehouse_id)] = b

    db.commit()

    print(f"\n  ✓ Import complete: {imported} transactions imported, {skipped} skipped/duplicate")
    if errors[:5]:
        print(f"  ⚠ Sample errors (first 5): {errors[:5]}")

    # Log the import
    log = ImportLog(
        file_name="PRODUCTION ESTIMATES.csv",
        import_status="SUCCESS" if imported > 0 else "FAILED",
        records_processed=imported,
        records_failed=len(errors),
        error_summary="; ".join(errors[:10]) if errors else None,
    )
    db.add(log)
    db.commit()


def print_summary(db: Session):
    """Prints a summary of what's in the database after seeding."""
    print("\n" + "="*60)
    print("DATABASE SUMMARY AFTER SEEDING")
    print("="*60)

    for crop_def in FOCUS_CROPS:
        product = db.query(Product).filter(Product.product_name == crop_def["product_name"]).first()
        if not product:
            print(f"\n{crop_def['product_name']}: NOT FOUND")
            continue

        balances = db.query(StockBalance).filter(StockBalance.product_id == product.product_id).all()
        total_stock = sum(b.current_stock for b in balances)
        tx_count = db.query(StockTransaction).filter(StockTransaction.product_id == product.product_id).count()

        print(f"\n{'─'*40}")
        print(f"  Crop        : {product.product_name}")
        print(f"  Unit        : {product.unit}")
        print(f"  Transactions: {tx_count}")
        print(f"  Total Stock : {total_stock:,.0f} {product.unit}")
        print(f"  Reorder Lvl : {crop_def['reorder_level']:,.0f} {product.unit}")
        if total_stock <= crop_def["reorder_level"]:
            print(f"  Status      : ⚠ LOW STOCK")
        else:
            print(f"  Status      : ✓ HEALTHY")

    print("\n")
    total_farmers = db.query(Farmer).count()
    total_warehouses = db.query(Warehouse).count()
    total_txs = db.query(StockTransaction).count()
    print(f"  Farmers     : {total_farmers}")
    print(f"  Warehouses  : {total_warehouses}")
    print(f"  Total Txs   : {total_txs}")
    print("="*60)


def main():
    print("="*60)
    print("AGRICULTURE STOCK CONTROL — CROP SEEDER")
    print("Focus Crops: Tomato | Yam | Maize | Rice")
    print("="*60)

    db: Session = SessionLocal()
    try:
        product_map = seed_focus_products(db)
        wh_map = seed_warehouses(db)
        farmer_map = seed_regional_farmers(db)
        import_production_data(db, product_map, farmer_map, wh_map)
        print_summary(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
