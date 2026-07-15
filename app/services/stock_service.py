from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import ALLOW_NEGATIVE_STOCK
from app.models.stock_models import StockBalance, StockTransaction
from app.repositories.stock_repo import StockRepository
from app.utils.unit_converter import convert_quantity


class StockService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = StockRepository(db)

    def record_movement(
        self,
        farmer_id: int,
        product_id: int,
        warehouse_id: Optional[int],
        transaction_type: str,  # STOCK_IN, STOCK_OUT, DAMAGE, RETURN, TRANSFER, ADJUSTMENT
        quantity: float,  # Always positive on input; direction determined by type
        unit: str,
        transaction_date: Optional[datetime] = None,
        reference_note: Optional[str] = None,
    ) -> StockTransaction:
        if not transaction_date:
            transaction_date = datetime.now(timezone.utc)

        # 1. Verify foreign keys exist
        farmer = self.repo.get_farmer_by_id(farmer_id)
        if not farmer:
            raise ValueError(f"Farmer with ID {farmer_id} does not exist.")

        product = self.repo.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product with ID {product_id} does not exist.")

        if warehouse_id is not None:
            warehouse = self.repo.get_warehouse_by_id(warehouse_id)
            if not warehouse:
                raise ValueError(f"Warehouse with ID {warehouse_id} does not exist.")

        # 2. Normalize and check unit compatibility
        base_unit = product.unit
        try:
            converted_qty = convert_quantity(quantity, unit, base_unit)
        except ValueError as ue:
            # Trigger unit mismatch alert in the database and raise error
            alert_msg = f"Unit mismatch: Transaction unit '{unit}' is incompatible with product '{product.product_name}' base unit '{base_unit}'."
            self.repo.create_alert(
                farmer_id, product_id, warehouse_id, "UNIT_MISMATCH", alert_msg
            )
            raise ValueError(alert_msg) from ue

        # 3. Determine flow direction
        tx_type_upper = transaction_type.upper()
        # STOCK_IN, RETURN, positive ADJUSTMENT (indicated by positive quantity) are Additions.
        # STOCK_OUT, DAMAGE, TRANSFER, negative ADJUSTMENT are Deductions.
        is_deduction = tx_type_upper in ["STOCK_OUT", "DAMAGE", "TRANSFER"]

        # If type is ADJUSTMENT, we check the sign of quantity to see if it is a deduction
        if tx_type_upper == "ADJUSTMENT" and quantity < 0:
            is_deduction = True
            # For transaction storage, we keep quantity positive, but we will track sign in recalculate
            quantity = abs(quantity)
            converted_qty = abs(converted_qty)

        # 4. Fetch/Create stock balance record
        balance = self.repo.get_or_create_balance(farmer_id, product_id, warehouse_id)

        # 5. Check negative stock constraint
        current_stock = balance.current_stock
        change = -converted_qty if is_deduction else converted_qty
        new_stock = current_stock + change

        if new_stock < 0 and not ALLOW_NEGATIVE_STOCK:
            raise ValueError(
                f"Negative stock not allowed. Attempted deduction of {converted_qty} {base_unit} "
                f"on current balance of {current_stock} {base_unit}."
            )

        # 6. Save the transaction (we store raw transaction details)
        tx = self.repo.create_transaction(
            farmer_id=farmer_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=tx_type_upper,
            quantity=quantity,
            unit=unit,
            transaction_date=transaction_date,
            reference_note=reference_note,
        )

        # 7. Update current stock balance
        balance.current_stock = new_stock
        balance.last_updated = datetime.now(timezone.utc)
        self.db.commit()

        # 8. Check reorder thresholds and generate alerts
        self._check_alerts(balance)

        return tx

    def recalculate_balance(
        self, farmer_id: int, product_id: int, warehouse_id: Optional[int]
    ) -> float:
        """Recalculates the stock balance from the complete transaction history."""
        balance = self.repo.get_or_create_balance(farmer_id, product_id, warehouse_id)
        product = self.repo.get_product_by_id(product_id)
        if product is None:
            raise ValueError(f"Product with id {product_id} was not found.")
        base_unit = product.unit

        # Fetch all transactions sorted chronologically
        txs = (
            self.db.query(StockTransaction)
            .filter(
                StockTransaction.farmer_id == farmer_id,
                StockTransaction.product_id == product_id,
                StockTransaction.warehouse_id == warehouse_id,
            )
            .order_by(StockTransaction.transaction_date.asc())
            .all()
        )

        current_qty = balance.opening_stock
        for tx in txs:
            # Convert transaction quantity to base unit
            # If a unit mismatch is present, we log the issue but carry on or skip
            try:
                converted_qty = convert_quantity(tx.quantity, tx.unit, base_unit)
            except ValueError:
                # Skip invalid transactions for stock balance
                continue

            tx_type = tx.transaction_type.upper()
            if tx_type in ["STOCK_IN", "RETURN"]:
                current_qty += converted_qty
            elif tx_type in ["STOCK_OUT", "DAMAGE", "TRANSFER"]:
                current_qty -= converted_qty
            elif tx_type == "ADJUSTMENT":
                # For recorded adjustment transactions, reference_note or standard format indicates sign
                # If quantity is stored, we look for negative in note or store signed quantities
                # To be robust, let's treat reference notes containing 'deduct' or similar as negative,
                # or verify if quantity was originally recorded with a sign.
                # In our standard, ADJUSTMENT quantity in transaction is positive. Let's see if the note says deduction:
                is_subtraction = (
                    "deduct" in str(tx.reference_note).lower()
                    or "decrease" in str(tx.reference_note).lower()
                )
                if is_subtraction:
                    current_qty -= converted_qty
                else:
                    current_qty += converted_qty

        # Save recalculated balance
        balance.current_stock = current_qty
        balance.last_updated = datetime.now(timezone.utc)
        self.db.commit()

        self._check_alerts(balance)
        return current_qty

    def _check_alerts(self, balance: StockBalance):
        """Checks if current balance is below reorder level and manages alerts."""
        active_alert = self.repo.get_active_alert(
            balance.farmer_id,
            balance.product_id,
            balance.warehouse_id,
            "LOW_STOCK",
        )

        product_name = balance.product.product_name
        farmer_name = balance.farmer.full_name
        warehouse_suffix = (
            f" in warehouse '{balance.warehouse.warehouse_name}'"
            if balance.warehouse
            else ""
        )

        if balance.current_stock <= balance.reorder_level:
            # Trigger alert if not already active
            if not active_alert:
                msg = (
                    f"Low stock alert: Farmer '{farmer_name}' product '{product_name}'"
                    f"{warehouse_suffix} is at {balance.current_stock} {balance.product.unit} "
                    f"(reorder level: {balance.reorder_level} {balance.product.unit})."
                )
                self.repo.create_alert(
                    balance.farmer_id,
                    balance.product_id,
                    balance.warehouse_id,
                    "LOW_STOCK",
                    msg,
                )
        else:
            # Resolve alert if stock has recovered
            if active_alert:
                self.repo.resolve_alert(active_alert.alert_id)
