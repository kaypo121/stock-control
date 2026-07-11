import tempfile
from pathlib import Path

import pandas as pd
import pytest

from app.models.stock_models import ImportLog, StockAlert
from app.repositories.stock_repo import StockRepository
from app.services.import_service import ImportService
from app.services.stock_service import StockService


def test_stock_in_increases_balance(db_session):
    repo = StockRepository(db_session)
    service = StockService(db_session)

    # Setup seed entities
    farmer = repo.create_farmer(
        full_name="Kojo Annan", region="Ashanti", district="Ejura"
    )
    product = repo.create_product(product_name="Maize", category="Grains", unit="kg")

    # Record stock in
    tx = service.record_movement(
        farmer_id=farmer.farmer_id,
        product_id=product.product_id,
        warehouse_id=None,
        transaction_type="STOCK_IN",
        quantity=100.0,
        unit="kg",
        reference_note="Harvest A",
    )

    # Assert transaction
    assert tx.quantity == 100.0
    assert tx.unit == "kg"
    assert tx.transaction_type == "STOCK_IN"

    # Assert balance updated
    balance = repo.get_balance(farmer.farmer_id, product.product_id, None)
    assert balance is not None
    assert balance.current_stock == 100.0


def test_stock_out_decreases_balance(db_session):
    repo = StockRepository(db_session)
    service = StockService(db_session)

    farmer = repo.create_farmer(full_name="Ama Serwaa", region="Volta", district="Ho")
    product = repo.create_product(product_name="Yam", category="Tubers", unit="piece")

    # Record initial stock
    service.record_movement(
        farmer_id=farmer.farmer_id,
        product_id=product.product_id,
        warehouse_id=None,
        transaction_type="STOCK_IN",
        quantity=50.0,
        unit="piece",
    )

    # Record stock out
    service.record_movement(
        farmer_id=farmer.farmer_id,
        product_id=product.product_id,
        warehouse_id=None,
        transaction_type="STOCK_OUT",
        quantity=20.0,
        unit="piece",
    )

    # Assert balance decreased
    balance = repo.get_balance(farmer.farmer_id, product.product_id, None)
    assert balance.current_stock == 30.0


def test_negative_stock_prevention(db_session):
    repo = StockRepository(db_session)
    service = StockService(db_session)

    farmer = repo.create_farmer(full_name="Ama Serwaa", region="Volta", district="Ho")
    product = repo.create_product(product_name="Yam", category="Tubers", unit="piece")

    # Attempt to stock out when current stock is 0
    with pytest.raises(ValueError) as excinfo:
        service.record_movement(
            farmer_id=farmer.farmer_id,
            product_id=product.product_id,
            warehouse_id=None,
            transaction_type="STOCK_OUT",
            quantity=10.0,
            unit="piece",
        )
    assert "Negative stock not allowed" in str(excinfo.value)


def test_low_stock_alert_triggers(db_session):
    repo = StockRepository(db_session)
    service = StockService(db_session)

    farmer = repo.create_farmer(
        full_name="Yaw Boateng", region="Eastern", district="Suhum"
    )
    product = repo.create_product(
        product_name="Cocoa Beans", category="Cash Crops", unit="kg"
    )

    # Setup reorder level
    balance = repo.get_or_create_balance(
        farmer.farmer_id, product.product_id, None, reorder_level=20.0
    )
    assert balance.current_stock == 0.0

    # Stock in below reorder level (say 15kg) -> triggers alert because 15 <= 20
    service.record_movement(
        farmer_id=farmer.farmer_id,
        product_id=product.product_id,
        warehouse_id=None,
        transaction_type="STOCK_IN",
        quantity=15.0,
        unit="kg",
    )

    # Check alert exists
    alert = repo.get_active_alert(
        farmer.farmer_id, product.product_id, None, "LOW_STOCK"
    )
    assert alert is not None
    assert "Low stock alert" in alert.alert_message

    # Stock in more to recover above threshold -> resolves alert
    service.record_movement(
        farmer_id=farmer.farmer_id,
        product_id=product.product_id,
        warehouse_id=None,
        transaction_type="STOCK_IN",
        quantity=10.0,
        unit="kg",
    )

    # Check alert is resolved
    alert_after = (
        db_session.query(StockAlert)
        .filter(StockAlert.alert_id == alert.alert_id)
        .first()
    )
    assert alert_after.is_resolved is True


def test_current_stock_recalculation(db_session):
    repo = StockRepository(db_session)
    service = StockService(db_session)

    farmer = repo.create_farmer(
        full_name="Kofi Mensah", region="Bono", district="Sunyani"
    )
    product = repo.create_product(product_name="Soybeans", category="Grains", unit="kg")

    # Add transaction in (100)
    service.record_movement(
        farmer.farmer_id, product.product_id, None, "STOCK_IN", 100.0, "kg"
    )
    # Add transaction out (40)
    service.record_movement(
        farmer.farmer_id, product.product_id, None, "STOCK_OUT", 40.0, "kg"
    )
    # Add adjustment (+10)
    service.record_movement(
        farmer.farmer_id,
        product.product_id,
        None,
        "ADJUSTMENT",
        10.0,
        "kg",
        reference_note="increase",
    )

    # Force current stock field corruption to test recalculate
    balance = repo.get_balance(farmer.farmer_id, product.product_id, None)
    balance.current_stock = 999.0  # Corrupted state
    db_session.commit()

    # Recalculate
    recalc_qty = service.recalculate_balance(farmer.farmer_id, product.product_id, None)
    assert recalc_qty == 70.0  # 100 - 40 + 10

    # Assert DB is corrected
    corrected_balance = repo.get_balance(farmer.farmer_id, product.product_id, None)
    assert corrected_balance.current_stock == 70.0


def test_invalid_and_duplicate_file_import(db_session):
    repo = StockRepository(db_session)
    importer = ImportService(db_session)

    # Seed product & farmer to avoid dynamic creation warnings
    repo.create_farmer(full_name="Abena Osei", region="Greater Accra", district="Tema")
    repo.create_product(product_name="Cassava", category="Roots", unit="kg")

    # Create temporary CSV file containing:
    # 1. Valid row
    # 2. Duplicate of valid row
    # 3. Invalid row (missing unit)
    # 4. Invalid row (negative quantity where forbidden)
    data = {
        "Farmer Name": [
            "Abena Osei",
            "Abena Osei",
            "Abena Osei",
            "Abena Osei",
        ],
        "Product Name": ["Cassava", "Cassava", "Cassava", "Cassava"],
        "Quantity": [100.0, 100.0, 50.0, -10.0],
        "Unit": ["kg", "kg", None, "kg"],
        "Transaction Type": ["STOCK_IN", "STOCK_IN", "STOCK_IN", "STOCK_IN"],
    }
    df = pd.DataFrame(data)

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "test_import.csv"
        df.to_csv(file_path, index=False)

        res = importer.import_dataset(file_path)

        # 1 valid row imported.
        # 1 duplicate row dropped by pandas drop_duplicates.
        # 2 invalid rows failed.
        assert res["imported_count"] == 1
        assert res["failed_count"] == 2
        assert res["status"] == "PARTIAL"
        assert res["error_log_file"] is not None

        # Assert log was written to import_logs
        log = db_session.query(ImportLog).first()
        assert log is not None
        assert log.import_status == "PARTIAL"
        assert log.records_processed == 1
        assert log.records_failed == 2

        # Check balance is updated for the single valid row
        farmer = repo.get_farmer_by_name("Abena Osei")
        product = repo.get_product_by_name("Cassava")
        balance = repo.get_balance(farmer.farmer_id, product.product_id, None)
        assert balance.current_stock == 100.0
