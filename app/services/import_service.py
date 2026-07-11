import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.config import DATA_ERROR_LOGS_DIR, DATA_RAW_DIR
from app.models.stock_models import Farmer, Product
from app.repositories.stock_repo import StockRepository
from app.services.stock_service import StockService


class ImportService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = StockRepository(db)
        self.stock_service = StockService(db)

    def normalize_headers(self, df: pd.DataFrame) -> pd.DataFrame:
        """Trims, lowercases, and replaces space/punctuation in column names."""
        new_cols = []
        for col in df.columns:
            c = str(col).strip().lower()
            c = re.sub(r"[^a-z0-9_]", "_", c)
            c = re.sub(r"_+", "_", c).strip("_")
            new_cols.append(c)
        df.columns = new_cols
        return df

    def find_or_suggest_farmer(
        self, name: str
    ) -> Tuple[Optional[Farmer], Optional[str]]:
        """
        Attempts to find a farmer by name.
        If a similar name is found, returns (None, suggestion_msg).
        If no match and no close suggestion, returns (None, None).
        If exact match, returns (farmer, None).
        """
        name_clean = name.strip()
        exact = self.repo.get_farmer_by_name(name_clean)
        if exact:
            return exact, None

        # Check for close matches (fuzzy)
        similar = self.repo.find_similar_farmers(name_clean, threshold=0.8)
        if similar:
            best_match, score = similar[0]
            # If extremely high confidence, merge case-insensitively
            if score > 0.95:
                return best_match, None

            suggestion = (
                f"Fuzzy match detected: '{name_clean}' is similar to existing farmer "
                f"'{best_match.full_name}' (confidence {score:.2f}). Direct merge skipped."
            )
            return None, suggestion

        return None, None

    def find_or_suggest_product(
        self, name: str
    ) -> Tuple[Optional[Product], Optional[str]]:
        """Identical logic for products."""
        name_clean = name.strip()
        exact = self.repo.get_product_by_name(name_clean)
        if exact:
            return exact, None

        similar = self.repo.find_similar_products(name_clean, threshold=0.8)
        if similar:
            best_match, score = similar[0]
            if score > 0.95:
                return best_match, None
            suggestion = (
                f"Fuzzy match detected: '{name_clean}' is similar to existing product "
                f"'{best_match.product_name}' (confidence {score:.2f}). Direct merge skipped."
            )
            return None, suggestion

        return None, None

    def process_generic_transaction_row(
        self, row: Dict[str, Any], file_name: str, row_idx: int
    ) -> Tuple[bool, str]:
        """Validates and imports a single row containing a stock movement transaction."""
        try:
            # 1. Extract and validate critical fields
            farmer_name = row.get("farmer_name") or row.get("farmer")
            product_name = (
                row.get("product_name")
                or row.get("product")
                or row.get("crop")
                or row.get("commodity")
            )
            qty_raw = (
                row.get("quantity")
                or row.get("qty")
                or row.get("production")
                or row.get("amount")
            )
            unit_raw = row.get("unit") or row.get("units")
            tx_type = row.get("transaction_type") or row.get("type") or "STOCK_IN"

            if not farmer_name or not product_name or qty_raw is None or not unit_raw:
                return (
                    False,
                    "Missing critical columns (farmer, product, quantity, or unit)",
                )

            # Parse quantity
            try:
                qty = float(str(qty_raw).replace(",", "").strip())
            except ValueError:
                return False, f"Invalid quantity value: {qty_raw}"

            # Suspicious inputs check: negative quantities for non-adjustment types
            if qty < 0 and str(tx_type).upper() != "ADJUSTMENT":
                return (
                    False,
                    f"Negative quantity {qty} not allowed for transaction type {tx_type}",
                )

            # 2. Fuzzy match checks
            farmer, farmer_suggestion = self.find_or_suggest_farmer(str(farmer_name))
            if farmer_suggestion:
                return False, farmer_suggestion
            if not farmer:
                # Create new farmer automatically if no suggestions block it
                farmer = self.repo.create_farmer(
                    full_name=str(farmer_name),
                    region=row.get("region"),
                    district=row.get("district"),
                )

            product, product_suggestion = self.find_or_suggest_product(
                str(product_name)
            )
            if product_suggestion:
                return False, product_suggestion
            if not product:
                product = self.repo.create_product(
                    product_name=str(product_name),
                    category=row.get("category") or "Crops",
                    unit=str(unit_raw),
                )

            # Warehouse lookup
            warehouse_id = None
            warehouse_name = (
                row.get("warehouse_name")
                or row.get("warehouse")
                or row.get("market")
                or row.get("location")
            )
            if warehouse_name:
                warehouse_name_str = str(warehouse_name).strip()
                warehouse = self.repo.get_warehouse_by_name(warehouse_name_str)
                if not warehouse:
                    warehouse = self.repo.create_warehouse(
                        warehouse_name=warehouse_name_str,
                        region=row.get("region"),
                        district=row.get("district"),
                    )
                warehouse_id = warehouse.warehouse_id

            # Date parsing
            date_raw = (
                row.get("date")
                or row.get("transaction_date")
                or row.get("market_day")
                or row.get("year")
            )
            tx_date = datetime.now(timezone.utc)
            if date_raw:
                # Try common formats
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y"):
                    try:
                        tx_date = datetime.strptime(str(date_raw).strip(), fmt)
                        break
                    except ValueError:
                        continue

            note = (
                row.get("reference_note")
                or row.get("note")
                or f"Imported from {file_name}"
            )
            if "price" in row:
                note += f" | Price: {row['price']}"

            # 3. Record transaction through StockService (which handles unit conversions and negative stock constraints)
            self.stock_service.record_movement(
                farmer_id=farmer.farmer_id,
                product_id=product.product_id,
                warehouse_id=warehouse_id,
                transaction_type=str(tx_type).upper(),
                quantity=qty,
                unit=str(unit_raw),
                transaction_date=tx_date,
                reference_note=note,
            )
            return True, "Success"

        except (ValueError, TypeError, SQLAlchemyError) as e:
            return False, str(e)

    def import_dataset(self, file_path: Path) -> Dict[str, Any]:
        """Reads, normalizes, cleans, and imports a dataset from CSV or Excel."""
        file_name = file_path.name

        # 1. Read file
        try:
            if file_path.suffix.lower() == ".csv":
                df = pd.read_csv(file_path)
            elif file_path.suffix.lower() in (".xlsx", ".xls"):
                df = pd.read_excel(file_path)
            else:
                return {
                    "status": "FAILED",
                    "processed": 0,
                    "failed": 0,
                    "error": f"Unsupported file extension: {file_path.suffix}",
                }
        except (pd.errors.EmptyDataError, OSError, ValueError) as e:
            return {
                "status": "FAILED",
                "processed": 0,
                "failed": 0,
                "error": f"Error opening file: {str(e)}",
            }

        # 2. Normalize headers
        df = self.normalize_headers(df)
        df = df.where(pd.notnull(df), None)  # Replace NaN with None

        # Remove exact duplicates
        initial_rows = len(df)
        df = df.drop_duplicates()
        dedup_count = initial_rows - len(df)

        # 3. Detect Schema / Column Mapping
        # We try to find standard columns. If it's a known historical dataset, we map columns appropriately.
        # Check for production estimates: 'production_mt' or 'average_yield_mt_per_ha'
        is_production_srid = "production_mt" in df.columns or "production" in df.columns
        is_commodity_price = "price" in df.columns

        records_processed = 0
        records_failed = 0
        error_rows = []

        for idx, row in df.iterrows():
            row_dict = row.to_dict()

            # Map columns for historical datasets to make them importable as transaction flows
            if is_production_srid:
                # "Crop production Data SRID" or "production estimates"
                # Map commodity/crop to product
                crop_name = row_dict.get("crop") or row_dict.get("commodity")
                prod_qty = row_dict.get("production_mt") or row_dict.get("production")

                # We seed this as stock_in for a regional cooperative
                region = row_dict.get("region", "Ghana")
                district = row_dict.get("district", "Unknown District")
                row_dict["farmer_name"] = f"{region} Regional Cooperative"
                row_dict["product_name"] = crop_name
                row_dict["quantity"] = prod_qty
                row_dict["unit"] = "ton"
                row_dict["transaction_type"] = "STOCK_IN"
                row_dict["location"] = f"{district} District Storage"

            elif is_commodity_price:
                # "Commodity prices"
                crop_name = row_dict.get("commodity")
                price = row_dict.get("price")
                market = row_dict.get("market") or "Ghana Market"

                row_dict["farmer_name"] = "Market Supplier"
                row_dict["product_name"] = crop_name
                row_dict["quantity"] = 1.0  # Seed value
                row_dict["unit"] = "kg"
                row_dict["transaction_type"] = "STOCK_IN"
                row_dict["location"] = market
                row_dict["note"] = f"Historical retail price: GHS {price}"

            # Process the row
            success, reason = self.process_generic_transaction_row(
                row_dict, file_name, idx
            )
            if success:
                records_processed += 1
            else:
                records_failed += 1
                row_dict["_error_reason"] = reason
                row_dict["_row_index"] = idx
                error_rows.append(row_dict)

        # 4. Handle error logging
        error_log_file = None
        status = "SUCCESS"
        if records_failed > 0:
            status = "PARTIAL" if records_processed > 0 else "FAILED"
            # Write failed rows to error log folder
            log_name = f"error_{Path(file_name).stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            error_log_path = DATA_ERROR_LOGS_DIR / log_name
            error_df = pd.DataFrame(error_rows)
            error_df.to_csv(error_log_path, index=False)
            error_log_file = str(error_log_path)

        summary = f"Processed: {records_processed}, Failed: {records_failed}, Duplicates Removed: {dedup_count}"
        if error_log_file:
            summary += f". Errors logged to: {log_name}"

        # Write to db import log
        self.repo.create_import_log(
            file_name=file_name,
            status=status,
            processed=records_processed,
            failed=records_failed,
            summary=summary,
        )

        return {
            "status": status,
            "imported_count": records_processed,
            "failed_count": records_failed,
            "error_log_file": error_log_file,
            "message": summary,
        }

    def scan_and_import_raw_directory(self) -> List[Dict[str, Any]]:
        """Scans the configured raw directory and imports all supported files."""
        results = []
        # Support CSV and Excel formats
        extensions = ("*.csv", "*.xlsx", "*.xls")
        files = []
        for ext in extensions:
            files.extend(list(Path(DATA_RAW_DIR).glob(ext)))

        for f in files:
            res = self.import_dataset(f)
            results.append({"file": f.name, "result": res})
        return results
