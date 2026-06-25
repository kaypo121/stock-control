from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import stock_schemas
from app.repositories.stock_repo import StockRepository
from app.services.stock_service import StockService
from app.services.import_service import ImportService
from app.services.forecast_service import ForecastService

router = APIRouter(prefix="/stock", tags=["Stock Control"])

# ----------------- Stock In/Out/Adjustment -----------------

@router.post("/in", response_model=stock_schemas.StockTransactionResponse, status_code=status.HTTP_201_CREATED)
def stock_in(tx_in: stock_schemas.StockTransactionCreate, db: Session = Depends(get_db)):
    """Records stock incoming for a farmer. Increments inventory balance."""
    service = StockService(db)
    try:
        tx = service.record_movement(
            farmer_id=tx_in.farmer_id,
            product_id=tx_in.product_id,
            warehouse_id=tx_in.warehouse_id,
            transaction_type="STOCK_IN",
            quantity=tx_in.quantity,
            unit=tx_in.unit,
            transaction_date=tx_in.transaction_date,
            reference_note=tx_in.reference_note
        )
        return tx
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.post("/out", response_model=stock_schemas.StockTransactionResponse, status_code=status.HTTP_201_CREATED)
def stock_out(tx_out: stock_schemas.StockTransactionCreate, db: Session = Depends(get_db)):
    """Records stock outgoing. Decrements inventory. Validates against negative stock unless configured otherwise."""
    service = StockService(db)
    try:
        tx = service.record_movement(
            farmer_id=tx_out.farmer_id,
            product_id=tx_out.product_id,
            warehouse_id=tx_out.warehouse_id,
            transaction_type="STOCK_OUT",
            quantity=tx_out.quantity,
            unit=tx_out.unit,
            transaction_date=tx_out.transaction_date,
            reference_note=tx_out.reference_note
        )
        return tx
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.post("/adjustment", response_model=stock_schemas.StockTransactionResponse, status_code=status.HTTP_201_CREATED)
def stock_adjustment(adj: stock_schemas.StockAdjustmentCreate, db: Session = Depends(get_db)):
    """
    Registers a custom adjustment, damage, return, or transfer transaction.
    If quantity is negative, behaves as a deduction.
    """
    service = StockService(db)
    try:
        tx = service.record_movement(
            farmer_id=adj.farmer_id,
            product_id=adj.product_id,
            warehouse_id=adj.warehouse_id,
            transaction_type=adj.transaction_type,
            quantity=adj.quantity,
            unit=adj.unit,
            reference_note=adj.reference_note
        )
        return tx
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


# ----------------- Balance Retrieval -----------------

@router.get("/current", response_model=List[stock_schemas.StockBalanceResponse])
def get_all_current_balances(db: Session = Depends(get_db)):
    """Returns all current inventory balances in the system."""
    repo = StockRepository(db)
    return repo.get_all_balances()


@router.get("/current/{farmer_id}", response_model=List[stock_schemas.StockBalanceResponse])
def get_farmer_balances(farmer_id: int, db: Session = Depends(get_db)):
    """Returns all inventory balances associated with a specific farmer."""
    repo = StockRepository(db)
    farmer = repo.get_farmer_by_id(farmer_id)
    if not farmer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Farmer with ID {farmer_id} not found.")
    return repo.get_balances_by_farmer(farmer_id)


@router.get("/current/{farmer_id}/{product_id}", response_model=stock_schemas.StockBalanceResponse)
def get_specific_balance(farmer_id: int, product_id: int, warehouse_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """Returns the inventory balance for a specific farmer, product, and optional warehouse."""
    repo = StockRepository(db)
    balance = repo.get_balance(farmer_id, product_id, warehouse_id)
    if not balance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="No balance record found for the specified farmer, product, and warehouse combination."
        )
    return balance


@router.get("/transactions", response_model=List[stock_schemas.StockTransactionResponse])
def get_transaction_history(
    farmer_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    warehouse_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Retrieves chronological transaction log (audit trail), optionally filtered."""
    repo = StockRepository(db)
    return repo.get_transactions(farmer_id=farmer_id, product_id=product_id, warehouse_id=warehouse_id, limit=limit)


# ----------------- Stock Alerts & Reorder Level -----------------

@router.get("/alerts", response_model=List[stock_schemas.StockAlertResponse])
def get_active_alerts(db: Session = Depends(get_db)):
    """Fetches all active stock alerts (e.g. low-stock or unit-mismatch issues)."""
    repo = StockRepository(db)
    return repo.get_active_alerts()


@router.get("/low-stock", response_model=List[stock_schemas.BalanceSummary])
def get_low_stock_items(db: Session = Depends(get_db)):
    """Retrieves all product balances that have dropped below or equal to their reorder thresholds."""
    repo = StockRepository(db)
    balances = repo.get_all_balances()
    low_stock_list = []
    
    for b in balances:
        if b.current_stock <= b.reorder_level:
            low_stock_list.append(stock_schemas.BalanceSummary(
                farmer_name=b.farmer.full_name,
                product_name=b.product.product_name,
                warehouse_name=b.warehouse.warehouse_name if b.warehouse else None,
                current_stock=b.current_stock,
                unit=b.product.unit,
                reorder_level=b.reorder_level,
                status="LOW_STOCK"
            ))
    return low_stock_list


# ----------------- Import pipeline -----------------

@router.post("/import", response_model=List[stock_schemas.ImportResult])
def run_import_pipeline(db: Session = Depends(get_db)):
    """
    Scans the raw data folder (`data/raw/`), cleans files,
    resolves mappings, registers new models, logs failures, and imports transactions.
    """
    service = ImportService(db)
    try:
        raw_results = service.scan_and_import_raw_directory()
        # Map raw dictionary to Pydantic responses
        results = []
        for r in raw_results:
            file_name = r["file"]
            res = r["result"]
            
            results.append(stock_schemas.ImportResult(
                status=res["status"],
                imported_count=res["imported_count"],
                failed_count=res["failed_count"],
                error_log_file=res["error_log_file"],
                message=f"File: {file_name} - {res['message']}"
            ))
        return results
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/import/logs", response_model=List[stock_schemas.ImportLogResponse])
def get_import_logs(db: Session = Depends(get_db)):
    """Retrieves database records of all import runs."""
    repo = StockRepository(db)
    return repo.get_import_logs()


# ----------------- AI Forecasting Support -----------------

@router.get("/forecast/{product_id}")
def get_product_forecast(product_id: int, db: Session = Depends(get_db)):
    """Generates Weekly/Monthly consumption forecasts and Runout coverage estimates for a product."""
    service = ForecastService(db)
    try:
        return service.generate_baseline_forecast(product_id)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))


# ----------------- Entity Registration Helpers -----------------

@router.post("/farmers", response_model=stock_schemas.FarmerResponse, status_code=status.HTTP_201_CREATED)
def register_farmer(farmer: stock_schemas.FarmerCreate, db: Session = Depends(get_db)):
    repo = StockRepository(db)
    existing = repo.get_farmer_by_name(farmer.full_name)
    if existing:
        raise HTTPException(status_code=400, detail="Farmer with this name already registered.")
    return repo.create_farmer(
        full_name=farmer.full_name,
        phone_number=farmer.phone_number,
        region=farmer.region,
        district=farmer.district,
        farm_name=farmer.farm_name
    )


@router.get("/farmers", response_model=List[stock_schemas.FarmerResponse])
def list_farmers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    repo = StockRepository(db)
    return repo.get_all_farmers(skip=skip, limit=limit)


@router.post("/products", response_model=stock_schemas.ProductResponse, status_code=status.HTTP_201_CREATED)
def register_product(product: stock_schemas.ProductCreate, db: Session = Depends(get_db)):
    repo = StockRepository(db)
    existing = repo.get_product_by_name(product.product_name)
    if existing:
        raise HTTPException(status_code=400, detail="Product with this name already registered.")
    return repo.create_product(
        product_name=product.product_name,
        category=product.category,
        unit=product.unit,
        description=product.description
    )


@router.get("/products", response_model=List[stock_schemas.ProductResponse])
def list_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    repo = StockRepository(db)
    return repo.get_all_products(skip=skip, limit=limit)


@router.post("/warehouses", response_model=stock_schemas.WarehouseResponse, status_code=status.HTTP_201_CREATED)
def register_warehouse(wh: stock_schemas.WarehouseCreate, db: Session = Depends(get_db)):
    repo = StockRepository(db)
    existing = repo.get_warehouse_by_name(wh.warehouse_name)
    if existing:
        raise HTTPException(status_code=400, detail="Warehouse with this name already registered.")
    return repo.create_warehouse(
        warehouse_name=wh.warehouse_name,
        region=wh.region,
        district=wh.district,
        capacity=wh.capacity
    )


@router.get("/warehouses", response_model=List[stock_schemas.WarehouseResponse])
def list_warehouses(db: Session = Depends(get_db)):
    repo = StockRepository(db)
    return repo.get_all_warehouses()
