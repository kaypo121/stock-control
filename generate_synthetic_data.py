"""
generate_synthetic_data.py
==========================
1. Consolidates duplicate products (keeps Tomato, Yam, Maize, Rice as the canonical ones)
2. Generates realistic synthetic transaction datasets for all 4 focus crops
   based on Ghana's agricultural seasons, regional production patterns, and
   market dynamics (1993–2024)
3. Saves the datasets as CSVs in the datasets folder
4. Seeds all transactions into the stock database

Ghana Seasonal Context:
  - Major season (season 1): March–July  (harvest peak: June-July)
  - Minor season (season 2): August–November (harvest peak: Oct-Nov)
  - Tomato: Northern Ghana major producer; dry-season farming Jan-Apr
  - Yam: Northern/Brong-Ahafo; harvest Oct-Jan
  - Maize: Nationwide; dual seasons
  - Rice: Volta/Northern; harvest Nov-Jan (irrigated year-round in some areas)

Run:
    python generate_synthetic_data.py
"""

import sys
import random
import math
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import numpy as np
from sqlalchemy.orm import Session

from app.database import engine, Base, SessionLocal
from app.models.stock_models import (
    Farmer, Product, Warehouse, StockTransaction, StockBalance, StockAlert, ImportLog
)

Base.metadata.create_all(bind=engine)
random.seed(42)
np.random.seed(42)

# ── Output directory for CSV exports ─────────────────────────────────────────
OUTPUT_DIR = Path("datesets folder") / "synthetic_datasets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Canonical product definitions ────────────────────────────────────────────
CANONICAL = {
    "Tomato": {"unit": "crate",  "category": "Vegetables",    "description": "Fresh garden tomatoes (Ghana standard 25 kg crate)"},
    "Yam":    {"unit": "kg",     "category": "Roots & Tubers","description": "Yam tubers – puna, water, and white yam varieties"},
    "Maize":  {"unit": "kg",     "category": "Grains",        "description": "Maize grain – white and yellow varieties"},
    "Rice":   {"unit": "kg",     "category": "Grains",        "description": "Paddy and milled rice"},
}

# Duplicate product names that will be merged into the canonical ones
DUPLICATES = {
    "Tomato":  ["Tomato Local"],
    "Yam":     ["Yam Puna"],
    "Maize":   ["White Maize", "Maize Yellow"],
    "Rice":    ["Rice Local"],
}

# ── Regional production weights (based on MoFA data patterns) ────────────────
# Keys match the regional cooperative farmer names seeded earlier
REGIONAL_WEIGHTS = {
    "Tomato": {
        "Northern":      0.35,  # Dominant tomato region
        "Upper East":    0.18,
        "Brong-Ahafo":   0.12,   # Techiman market hub
        "Ashanti":       0.10,
        "Greater Accra": 0.08,
        "Volta":         0.07,
        "Eastern":       0.05,
        "Central":       0.03,
        "Western":       0.02,
    },
    "Yam": {
        "Brong-Ahafo":   0.32,
        "Northern":      0.28,
        "Volta":         0.15,
        "Ashanti":       0.12,
        "Eastern":       0.08,
        "Upper East":    0.03,
        "Central":       0.02,
    },
    "Maize": {
        "Ashanti":       0.22,
        "Brong-Ahafo":   0.20,
        "Northern":      0.16,
        "Eastern":       0.12,
        "Volta":         0.10,
        "Western":       0.08,
        "Central":       0.06,
        "Greater Accra": 0.04,
        "Upper East":    0.02,
    },
    "Rice": {
        "Northern":      0.30,
        "Upper East":    0.20,
        "Upper West":    0.18,
        "Volta":         0.15,
        "Ashanti":       0.08,
        "Brong-Ahafo":   0.06,
        "Eastern":       0.03,
    },
}

# ── Seasonal production multipliers by month (1=Jan … 12=Dec) ────────────────
# Values represent relative harvest/supply intensity (1.0 = average month)
SEASONAL_PROFILE = {
    "Tomato": {
        # Dry-season (irrigated): Jan-Apr peak; dip in rainy season
        1: 1.8, 2: 2.0, 3: 1.7, 4: 1.4,
        5: 0.7, 6: 0.5, 7: 0.4, 8: 0.6,
        9: 0.8, 10: 1.1, 11: 1.3, 12: 1.5,
    },
    "Yam": {
        # Main harvest: Oct-Jan
        1: 1.4, 2: 1.0, 3: 0.7, 4: 0.5,
        5: 0.4, 6: 0.5, 7: 0.6, 8: 0.8,
        9: 1.0, 10: 1.6, 11: 1.8, 12: 1.7,
    },
    "Maize": {
        # Season 1 harvest: Jul-Aug; Season 2 harvest: Nov-Dec
        1: 0.6, 2: 0.5, 3: 0.6, 4: 0.8,
        5: 0.9, 6: 1.0, 7: 1.6, 8: 1.8,
        9: 1.2, 10: 1.0, 11: 1.5, 12: 1.3,
    },
    "Rice": {
        # Main harvest: Nov-Feb (dry season / Volta irrigated)
        1: 1.6, 2: 1.4, 3: 1.0, 4: 0.7,
        5: 0.6, 6: 0.6, 7: 0.7, 8: 0.9,
        9: 1.0, 10: 1.1, 11: 1.8, 12: 1.7,
    },
}

# ── Annual national production baselines (metric tons) ───────────────────────
# Based on Ghana MoFA published figures, interpolated for 1993-2024
ANNUAL_PRODUCTION_MT = {
    "Tomato": {
        1993: 120000, 1995: 130000, 2000: 155000, 2005: 175000,
        2010: 195000, 2015: 210000, 2017: 220000, 2020: 235000, 2024: 250000,
    },
    "Yam": {
        1993: 2100000, 1995: 2300000, 2000: 2700000, 2005: 3200000,
        2010: 4200000, 2015: 5800000, 2017: 6300000, 2020: 7100000, 2024: 7800000,
    },
    "Maize": {
        1993: 850000, 1995: 950000, 2000: 1100000, 2005: 1300000,
        2010: 1600000, 2015: 1850000, 2017: 2000000, 2020: 2200000, 2024: 2400000,
    },
    "Rice": {
        1993: 120000, 1995: 140000, 2000: 175000, 2005: 210000,
        2010: 280000, 2015: 320000, 2017: 350000, 2020: 390000, 2024: 430000,
    },
}


def interpolate_annual(crop: str, year: int) -> float:
    """Linear interpolation between known annual production points."""
    data = ANNUAL_PRODUCTION_MT[crop]
    years = sorted(data.keys())
    if year <= years[0]:
        return data[years[0]]
    if year >= years[-1]:
        return data[years[-1]]
    for i in range(len(years) - 1):
        y0, y1 = years[i], years[i + 1]
        if y0 <= year <= y1:
            t = (year - y0) / (y1 - y0)
            return data[y0] + t * (data[y1] - data[y0])
    return data[years[-1]]


def generate_crop_dataset(crop: str, start_year: int = 1993, end_year: int = 2024) -> pd.DataFrame:
    """
    Generates a realistic monthly transaction dataset for a crop.
    Returns a DataFrame with columns matching the stock system's import schema.
    """
    records = []
    regions = list(REGIONAL_WEIGHTS[crop].keys())
    seasonal = SEASONAL_PROFILE[crop]

    for year in range(start_year, end_year + 1):
        annual_mt = interpolate_annual(crop, year)
        # Add ±8% inter-annual noise
        annual_mt *= (1.0 + np.random.uniform(-0.08, 0.08))

        for month in range(1, 13):
            month_multiplier = seasonal[month]
            monthly_mt = (annual_mt / 12.0) * month_multiplier
            # Add ±12% intra-month noise
            monthly_mt *= (1.0 + np.random.uniform(-0.12, 0.12))

            # Distribute across regions by weight
            for region in regions:
                weight = REGIONAL_WEIGHTS[crop].get(region, 0)
                if weight == 0:
                    continue

                region_mt = monthly_mt * weight
                # Add ±15% regional variation
                region_mt *= (1.0 + np.random.uniform(-0.15, 0.15))
                region_mt = max(0.01, region_mt)

                # Pick a random day in that month for the transaction date
                import calendar
                max_day = calendar.monthrange(year, month)[1]
                day = random.randint(1, max_day)
                tx_date = datetime(year, month, day)

                # Convert MT to crop unit
                if crop == "Tomato":
                    # 1 MT = 40 crates (25 kg each)
                    qty = round(region_mt * 40.0, 2)
                    unit = "crate"
                else:
                    # 1 MT = 1000 kg
                    qty = round(region_mt * 1000.0, 2)
                    unit = "kg"

                # Also generate an outflow (market sales/consumption) — roughly 70-85% of inflow
                outflow_ratio = random.uniform(0.70, 0.85)
                out_qty = round(qty * outflow_ratio, 2)

                farmer_name = f"{region} Regional Cooperative"
                warehouse_map = {
                    "Northern":      "Northern Region Agro Store",
                    "Upper East":    "Upper East Grain Silo",
                    "Upper West":    "Upper West Storage Centre",
                    "Brong-Ahafo":   "Brong-Ahafo Grain Depot",
                    "Ashanti":       "Ashanti Regional Store",
                    "Greater Accra": "Greater Accra Storage Hub",
                    "Volta":         "Volta Region Produce Store",
                    "Eastern":       "Eastern Region Farm Hub",
                    "Western":       "Western Region Cold Store",
                    "Central":       "Central Region Produce Hub",
                }
                warehouse = warehouse_map.get(region, "Greater Accra Storage Hub")

                # STOCK_IN row (harvest/supply)
                records.append({
                    "farmer_name":      farmer_name,
                    "product_name":     crop,
                    "quantity":         qty,
                    "unit":             unit,
                    "transaction_type": "STOCK_IN",
                    "transaction_date": tx_date.strftime("%Y-%m-%d"),
                    "warehouse_name":   warehouse,
                    "region":           region,
                    "year":             year,
                    "month":            month,
                    "season":           "Season1" if month in [3,4,5,6,7,8] else "Season2",
                    "production_mt":    round(region_mt, 4),
                    "reference_note":   f"Synthetic harvest {year}-{month:02d} {region}",
                })

                # STOCK_OUT row (sales/distribution)
                records.append({
                    "farmer_name":      farmer_name,
                    "product_name":     crop,
                    "quantity":         out_qty,
                    "unit":             unit,
                    "transaction_type": "STOCK_OUT",
                    "transaction_date": tx_date.strftime("%Y-%m-%d"),
                    "warehouse_name":   warehouse,
                    "region":           region,
                    "year":             year,
                    "month":            month,
                    "season":           "Season1" if month in [3,4,5,6,7,8] else "Season2",
                    "production_mt":    round(region_mt * outflow_ratio, 4),
                    "reference_note":   f"Synthetic market sale {year}-{month:02d} {region}",
                })

    df = pd.DataFrame(records)
    df = df.sort_values(["year", "month", "region", "transaction_type"]).reset_index(drop=True)
    return df


def consolidate_duplicate_products(db: Session) -> dict:
    """
    Merges duplicate products into the canonical ones using raw SQL to avoid
    SQLAlchemy session state conflicts. Returns canonical name → Product map.
    """
    print("\n── Consolidating duplicate products ──")
    from sqlalchemy import text

    product_map = {}

    for canon_name, props in CANONICAL.items():
        # Get or create the canonical product
        canon = db.query(Product).filter(Product.product_name == canon_name).first()
        if not canon:
            canon = Product(
                product_name=canon_name,
                category=props["category"],
                unit=props["unit"],
                description=props["description"],
            )
            db.add(canon)
            db.commit()
            db.refresh(canon)
            print(f"  ✓ Created canonical product: {canon_name}")
        else:
            canon.unit = props["unit"]
            canon.category = props["category"]
            canon.description = props["description"]
            db.commit()
            print(f"  → Confirmed canonical product: {canon_name} (id={canon.product_id})")

        product_map[canon_name] = canon

        # Merge duplicates via raw SQL to avoid identity map issues
        for dup_name in DUPLICATES.get(canon_name, []):
            dup = db.query(Product).filter(Product.product_name == dup_name).first()
            if not dup:
                continue

            dup_id = dup.product_id
            canon_id = canon.product_id
            print(f"    Merging '{dup_name}' (id={dup_id}) → '{canon_name}' (id={canon_id})")

            # Expire all tracked objects to avoid stale state
            db.expire_all()

            # Reassign transactions
            db.execute(text(
                "UPDATE stock_transactions SET product_id = :cid WHERE product_id = :did"
            ), {"cid": canon_id, "did": dup_id})

            # Reassign alerts
            db.execute(text(
                "UPDATE stock_alerts SET product_id = :cid WHERE product_id = :did"
            ), {"cid": canon_id, "did": dup_id})

            # For balances: merge stock into canonical, then delete duplicates
            dup_balances = db.execute(text(
                "SELECT balance_id, farmer_id, warehouse_id, current_stock, opening_stock "
                "FROM stock_balances WHERE product_id = :did"
            ), {"did": dup_id}).fetchall()

            for row in dup_balances:
                bal_id, farmer_id, wh_id, cur, opn = row
                # Check if a canonical balance already exists
                existing = db.execute(text(
                    "SELECT balance_id FROM stock_balances "
                    "WHERE farmer_id = :fid AND product_id = :cid AND warehouse_id IS :wid"
                ), {"fid": farmer_id, "cid": canon_id, "wid": wh_id}).fetchone()

                if existing:
                    db.execute(text(
                        "UPDATE stock_balances SET current_stock = current_stock + :cur, "
                        "opening_stock = opening_stock + :opn "
                        "WHERE balance_id = :bid"
                    ), {"cur": cur, "opn": opn, "bid": existing[0]})
                    db.execute(text(
                        "DELETE FROM stock_balances WHERE balance_id = :bid"
                    ), {"bid": bal_id})
                else:
                    db.execute(text(
                        "UPDATE stock_balances SET product_id = :cid WHERE balance_id = :bid"
                    ), {"cid": canon_id, "bid": bal_id})

            # Delete the duplicate product
            db.execute(text("DELETE FROM products WHERE product_id = :did"), {"did": dup_id})
            db.commit()
            db.expire_all()
            print(f"    ✓ Merged and removed '{dup_name}'")

    return product_map


def seed_synthetic_transactions(db: Session, crop: str, df: pd.DataFrame, product_map: dict):
    """
    Seeds the synthetic dataframe into the stock database.
    Skips rows that already exist (idempotent).
    """
    print(f"\n── Seeding synthetic data for {crop} ──")

    product = product_map[crop]

    # Build farmer cache: name → Farmer
    all_farmers = db.query(Farmer).all()
    farmer_cache = {f.full_name: f for f in all_farmers}

    # Build warehouse cache: name → Warehouse
    all_wh = db.query(Warehouse).all()
    wh_cache = {w.warehouse_name: w for w in all_wh}

    # Build balance cache: (farmer_id, product_id, wh_id) → StockBalance
    existing_balances = db.query(StockBalance).filter(
        StockBalance.product_id == product.product_id
    ).all()
    balance_cache = {(b.farmer_id, b.product_id, b.warehouse_id): b for b in existing_balances}

    # Reorder levels per crop
    reorder_levels = {"Tomato": 50.0, "Yam": 500.0, "Maize": 1000.0, "Rice": 800.0}
    reorder = reorder_levels[crop]

    imported = 0
    skipped = 0

    for _, row in df.iterrows():
        farmer = farmer_cache.get(row["farmer_name"])
        if not farmer:
            continue

        warehouse = wh_cache.get(row["warehouse_name"])
        warehouse_id = warehouse.warehouse_id if warehouse else None

        try:
            tx_date = datetime.strptime(str(row["transaction_date"]), "%Y-%m-%d")
        except ValueError:
            skipped += 1
            continue

        qty = float(row["quantity"])
        unit = str(row["unit"])
        tx_type = str(row["transaction_type"])
        note = str(row["reference_note"])

        # Idempotency: skip if reference note already exists for same farmer+product+date
        existing = db.query(StockTransaction).filter(
            StockTransaction.farmer_id == farmer.farmer_id,
            StockTransaction.product_id == product.product_id,
            StockTransaction.transaction_date == tx_date,
            StockTransaction.reference_note == note,
        ).first()
        if existing:
            skipped += 1
            continue

        # Insert transaction
        tx = StockTransaction(
            farmer_id=farmer.farmer_id,
            product_id=product.product_id,
            warehouse_id=warehouse_id,
            transaction_type=tx_type,
            quantity=qty,
            unit=unit,
            transaction_date=tx_date,
            reference_note=note,
        )
        db.add(tx)

        # Update balance
        bal_key = (farmer.farmer_id, product.product_id, warehouse_id)
        balance = balance_cache.get(bal_key)
        if not balance:
            balance = StockBalance(
                farmer_id=farmer.farmer_id,
                product_id=product.product_id,
                warehouse_id=warehouse_id,
                opening_stock=0.0,
                current_stock=0.0,
                reorder_level=reorder,
                last_updated=datetime.utcnow(),
            )
            db.add(balance)
            db.flush()
            balance_cache[bal_key] = balance

        if tx_type == "STOCK_IN":
            balance.current_stock += qty
        elif tx_type == "STOCK_OUT":
            balance.current_stock = max(0.0, balance.current_stock - qty)

        balance.last_updated = datetime.utcnow()
        imported += 1

        if imported % 1000 == 0:
            db.commit()
            print(f"    ... {imported} rows committed ...")

    db.commit()
    print(f"  ✓ {crop}: {imported} transactions seeded, {skipped} skipped")
    return imported


def print_final_summary(db: Session):
    print("\n" + "=" * 65)
    print("  FINAL DATABASE SUMMARY — FOCUS CROPS")
    print("=" * 65)
    for crop in ["Tomato", "Yam", "Maize", "Rice"]:
        product = db.query(Product).filter(Product.product_name == crop).first()
        if not product:
            print(f"\n  {crop}: NOT FOUND")
            continue
        balances = db.query(StockBalance).filter(StockBalance.product_id == product.product_id).all()
        total_stock = sum(b.current_stock for b in balances)
        tx_in = db.query(StockTransaction).filter(
            StockTransaction.product_id == product.product_id,
            StockTransaction.transaction_type == "STOCK_IN"
        ).count()
        tx_out = db.query(StockTransaction).filter(
            StockTransaction.product_id == product.product_id,
            StockTransaction.transaction_type == "STOCK_OUT"
        ).count()
        print(f"\n  {'─'*45}")
        print(f"  Crop         : {product.product_name}")
        print(f"  Unit         : {product.unit}")
        print(f"  STOCK_IN txs : {tx_in:,}")
        print(f"  STOCK_OUT txs: {tx_out:,}")
        print(f"  Balance Recs : {len(balances)}")
        print(f"  Current Stock: {total_stock:,.0f} {product.unit}")

    print(f"\n  {'─'*45}")
    print(f"  Total Farmers   : {db.query(Farmer).count()}")
    print(f"  Total Warehouses: {db.query(Warehouse).count()}")
    print(f"  Total Products  : {db.query(Product).count()}")
    print(f"  Total Txs       : {db.query(StockTransaction).count():,}")
    print("=" * 65)


def main():
    print("=" * 65)
    print("  SYNTHETIC DATASET GENERATOR — AGRICULTURE STOCK CONTROL")
    print("  Crops: Tomato | Yam | Maize | Rice  |  Years: 1993–2024")
    print("=" * 65)

    db: Session = SessionLocal()
    try:
        # Step 1: Clean up duplicate products
        product_map = consolidate_duplicate_products(db)

        # Step 2: Generate and seed synthetic data for each crop
        for crop in ["Tomato", "Yam", "Maize", "Rice"]:
            print(f"\n── Generating synthetic dataset for {crop} ──")
            df = generate_crop_dataset(crop, start_year=1993, end_year=2024)

            # Save to CSV
            csv_path = OUTPUT_DIR / f"{crop.lower()}_synthetic_1993_2024.csv"
            df.to_csv(csv_path, index=False)
            print(f"  ✓ Saved {len(df):,} rows → {csv_path}")

            # Seed into DB
            seed_synthetic_transactions(db, crop, df, product_map)

        print_final_summary(db)

    finally:
        db.close()

    print(f"\n  CSV files saved to: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
