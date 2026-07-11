import difflib
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock_models import (
    Farmer,
    ImportLog,
    Product,
    StockAlert,
    StockBalance,
    StockTransaction,
    Warehouse,
)


class StockRepository:
    def __init__(self, db: Session):
        self.db = db

    # ----------------- Farmer Repos -----------------
    def get_farmer_by_id(self, farmer_id: int) -> Optional[Farmer]:
        return self.db.query(Farmer).filter(Farmer.farmer_id == farmer_id).first()

    def get_farmer_by_name(self, name: str) -> Optional[Farmer]:
        """Exact case-insensitive search for a farmer."""
        return (
            self.db.query(Farmer)
            .filter(func.lower(Farmer.full_name) == name.strip().lower())
            .first()
        )

    def find_similar_farmers(
        self, name: str, threshold: float = 0.8
    ) -> List[Tuple[Farmer, float]]:
        """Finds farmers with similar names using difflib for fuzzy matching checks."""
        farmers = self.db.query(Farmer).all()
        matches = []
        name_lower = name.strip().lower()
        for f in farmers:
            ratio = difflib.SequenceMatcher(
                None, f.full_name.lower(), name_lower
            ).ratio()
            if ratio >= threshold:
                matches.append((f, ratio))
        # Sort by highest ratio first
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def create_farmer(
        self,
        full_name: str,
        phone_number: Optional[str] = None,
        region: Optional[str] = None,
        district: Optional[str] = None,
        farm_name: Optional[str] = None,
    ) -> Farmer:
        db_farmer = Farmer(
            full_name=full_name.strip(),
            phone_number=phone_number,
            region=region,
            district=district,
            farm_name=farm_name,
        )
        self.db.add(db_farmer)
        self.db.commit()
        self.db.refresh(db_farmer)
        return db_farmer

    def get_all_farmers(self, skip: int = 0, limit: int = 100) -> List[Farmer]:
        return self.db.query(Farmer).offset(skip).limit(limit).all()

    # ----------------- Product Repos -----------------
    def get_product_by_id(self, product_id: int) -> Optional[Product]:
        return self.db.query(Product).filter(Product.product_id == product_id).first()

    def get_product_by_name(self, name: str) -> Optional[Product]:
        """Exact case-insensitive search for a product."""
        return (
            self.db.query(Product)
            .filter(func.lower(Product.product_name) == name.strip().lower())
            .first()
        )

    def find_similar_products(
        self, name: str, threshold: float = 0.8
    ) -> List[Tuple[Product, float]]:
        """Finds products with similar names for fuzzy checks."""
        products = self.db.query(Product).all()
        matches = []
        name_lower = name.strip().lower()
        for p in products:
            ratio = difflib.SequenceMatcher(
                None, p.product_name.lower(), name_lower
            ).ratio()
            if ratio >= threshold:
                matches.append((p, ratio))
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def create_product(
        self,
        product_name: str,
        category: Optional[str] = None,
        unit: str = "kg",
        description: Optional[str] = None,
    ) -> Product:
        db_product = Product(
            product_name=product_name.strip(),
            category=category,
            unit=unit.strip().lower(),
            description=description,
        )
        self.db.add(db_product)
        self.db.commit()
        self.db.refresh(db_product)
        return db_product

    def get_all_products(self, skip: int = 0, limit: int = 100) -> List[Product]:
        return self.db.query(Product).offset(skip).limit(limit).all()

    # ----------------- Warehouse Repos -----------------
    def get_warehouse_by_id(self, warehouse_id: int) -> Optional[Warehouse]:
        return (
            self.db.query(Warehouse)
            .filter(Warehouse.warehouse_id == warehouse_id)
            .first()
        )

    def get_warehouse_by_name(self, name: str) -> Optional[Warehouse]:
        """Exact case-insensitive search for a warehouse."""
        return (
            self.db.query(Warehouse)
            .filter(func.lower(Warehouse.warehouse_name) == name.strip().lower())
            .first()
        )

    def create_warehouse(
        self,
        warehouse_name: str,
        region: Optional[str] = None,
        district: Optional[str] = None,
        capacity: Optional[float] = None,
    ) -> Warehouse:
        db_warehouse = Warehouse(
            warehouse_name=warehouse_name.strip(),
            region=region,
            district=district,
            capacity=capacity,
        )
        self.db.add(db_warehouse)
        self.db.commit()
        self.db.refresh(db_warehouse)
        return db_warehouse

    def get_all_warehouses(self) -> List[Warehouse]:
        return self.db.query(Warehouse).all()

    # ----------------- Stock Transaction Repos -----------------
    def create_transaction(
        self,
        farmer_id: int,
        product_id: int,
        warehouse_id: Optional[int],
        transaction_type: str,
        quantity: float,
        unit: str,
        transaction_date,
        reference_note: Optional[str],
    ) -> StockTransaction:
        db_tx = StockTransaction(
            farmer_id=farmer_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=transaction_type,
            quantity=quantity,
            unit=unit,
            transaction_date=transaction_date,
            reference_note=reference_note,
        )
        self.db.add(db_tx)
        self.db.commit()
        self.db.refresh(db_tx)
        return db_tx

    def get_transactions(
        self,
        farmer_id: Optional[int] = None,
        product_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[StockTransaction]:
        query = self.db.query(StockTransaction)
        if farmer_id is not None:
            query = query.filter(StockTransaction.farmer_id == farmer_id)
        if product_id is not None:
            query = query.filter(StockTransaction.product_id == product_id)
        if warehouse_id is not None:
            query = query.filter(StockTransaction.warehouse_id == warehouse_id)
        return (
            query.order_by(StockTransaction.transaction_date.desc()).limit(limit).all()
        )

    # ----------------- Stock Balance Repos -----------------
    def get_balance(
        self, farmer_id: int, product_id: int, warehouse_id: Optional[int]
    ) -> Optional[StockBalance]:
        return (
            self.db.query(StockBalance)
            .filter(
                StockBalance.farmer_id == farmer_id,
                StockBalance.product_id == product_id,
                StockBalance.warehouse_id == warehouse_id,
            )
            .first()
        )

    def get_or_create_balance(
        self,
        farmer_id: int,
        product_id: int,
        warehouse_id: Optional[int],
        reorder_level: float = 0.0,
    ) -> StockBalance:
        balance = self.get_balance(farmer_id, product_id, warehouse_id)
        if not balance:
            balance = StockBalance(
                farmer_id=farmer_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
                opening_stock=0.0,
                current_stock=0.0,
                reorder_level=reorder_level,
            )
            self.db.add(balance)
            self.db.commit()
            self.db.refresh(balance)
        return balance

    def get_all_balances(self) -> List[StockBalance]:
        return self.db.query(StockBalance).all()

    def get_balances_by_farmer(self, farmer_id: int) -> List[StockBalance]:
        return (
            self.db.query(StockBalance)
            .filter(StockBalance.farmer_id == farmer_id)
            .all()
        )

    # ----------------- Stock Alert Repos -----------------
    def get_active_alert(
        self,
        farmer_id: Optional[int],
        product_id: int,
        warehouse_id: Optional[int],
        alert_type: str,
    ) -> Optional[StockAlert]:
        return (
            self.db.query(StockAlert)
            .filter(
                StockAlert.farmer_id == farmer_id,
                StockAlert.product_id == product_id,
                StockAlert.warehouse_id == warehouse_id,
                StockAlert.alert_type == alert_type,
                StockAlert.is_resolved.is_(False),
            )
            .first()
        )

    def create_alert(
        self,
        farmer_id: Optional[int],
        product_id: int,
        warehouse_id: Optional[int],
        alert_type: str,
        message: str,
    ) -> StockAlert:
        alert = StockAlert(
            farmer_id=farmer_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            alert_type=alert_type,
            alert_message=message,
            is_resolved=False,
        )
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def resolve_alert(self, alert_id: int) -> Optional[StockAlert]:
        alert = (
            self.db.query(StockAlert).filter(StockAlert.alert_id == alert_id).first()
        )
        if alert and not alert.is_resolved:
            alert.is_resolved = True
            alert.resolved_at = func.now()
            self.db.commit()
            self.db.refresh(alert)
        return alert

    def get_active_alerts(self) -> List[StockAlert]:
        return self.db.query(StockAlert).filter(StockAlert.is_resolved.is_(False)).all()

    # ----------------- Import Log Repos -----------------
    def create_import_log(
        self,
        file_name: str,
        status: str,
        processed: int,
        failed: int,
        summary: Optional[str],
    ) -> ImportLog:
        log = ImportLog(
            file_name=file_name,
            import_status=status,
            records_processed=processed,
            records_failed=failed,
            error_summary=summary,
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def get_import_logs(self) -> List[ImportLog]:
        return self.db.query(ImportLog).order_by(ImportLog.created_at.desc()).all()
