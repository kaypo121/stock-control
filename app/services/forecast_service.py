from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models.stock_models import StockBalance, StockTransaction
from app.repositories.stock_repo import StockRepository
from app.utils.unit_converter import convert_quantity


class ForecastService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = StockRepository(db)

    def generate_baseline_forecast(self, product_id: int) -> Dict[str, Any]:
        """
        Generates a baseline forecast for a specific product.
        Calculates:
        - Current stock balance across all farmers/warehouses.
        - Average weekly and monthly outflow rates.
        - Days of coverage before running out.
        - Trend projections (forecast) for the next 3 months.
        """
        product = self.repo.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product with ID {product_id} does not exist.")

        base_unit = product.unit

        # 1. Calculate total current stock
        balances = (
            self.db.query(StockBalance)
            .filter(StockBalance.product_id == product_id)
            .all()
        )
        total_current = sum(b.current_stock for b in balances)

        # 2. Retrieve last 6 months of transaction history
        six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
        txs = (
            self.db.query(StockTransaction)
            .filter(
                StockTransaction.product_id == product_id,
                StockTransaction.transaction_date >= six_months_ago,
            )
            .order_by(StockTransaction.transaction_date.asc())
            .all()
        )

        # Group outflows by week/month
        outflow_qty_list = []
        inflow_qty_list = []

        for tx in txs:
            try:
                qty_base = convert_quantity(tx.quantity, tx.unit, base_unit)
            except ValueError:
                continue

            tx_type = tx.transaction_type.upper()
            if tx_type in ["STOCK_OUT", "DAMAGE"]:
                outflow_qty_list.append((tx.transaction_date, qty_base))
            elif tx_type in ["STOCK_IN", "RETURN"]:
                inflow_qty_list.append((tx.transaction_date, qty_base))
            elif tx_type == "ADJUSTMENT":
                is_subtraction = (
                    "deduct" in str(tx.reference_note).lower()
                    or "decrease" in str(tx.reference_note).lower()
                )
                if is_subtraction:
                    outflow_qty_list.append((tx.transaction_date, qty_base))
                else:
                    inflow_qty_list.append((tx.transaction_date, qty_base))

        # 3. Compute baseline metrics (outflow rate per day)
        total_outflow = sum(qty for _, qty in outflow_qty_list)
        total_inflow = sum(qty for _, qty in inflow_qty_list)

        # Calculate average daily rates over the 6-month window (180 days)
        avg_daily_outflow = total_outflow / 180.0
        avg_daily_inflow = total_inflow / 180.0

        avg_monthly_outflow = avg_daily_outflow * 30.0
        avg_monthly_inflow = avg_daily_inflow * 30.0

        # Calculate Days of Coverage (DoC)
        days_of_coverage = 999.0  # Default infinite
        if avg_daily_outflow > 0:
            days_of_coverage = total_current / avg_daily_outflow

        # 4. Generate projected balances for next 3 months
        # Projected Stock(m) = Current Stock + m * (Avg Monthly Inflow - Avg Monthly Outflow)
        projections = []
        monthly_net_flow = avg_monthly_inflow - avg_monthly_outflow

        temp_stock = total_current
        for m in range(1, 4):
            temp_stock = max(0.0, temp_stock + monthly_net_flow)
            projections.append(
                {
                    "month_index": m,
                    "projected_stock": round(temp_stock, 2),
                    "inflow_estimate": round(avg_monthly_inflow, 2),
                    "outflow_estimate": round(avg_monthly_outflow, 2),
                }
            )

        # 5. Determine warning level and recommendations
        warning_level = "HEALTHY"
        recommendation = (
            "Stock levels are currently stable based on consumption trends."
        )

        # If total stock is less than aggregate reorder levels
        total_reorder = sum(b.reorder_level for b in balances)
        if total_current <= total_reorder:
            warning_level = "CRITICAL"
            recommendation = "Low stock alert triggered! Current stock is below cumulative reorder thresholds. Reorder immediately."
        elif days_of_coverage < 30:
            warning_level = "WARNING"
            recommendation = (
                "Stock is projected to run out within 30 days. Plan reordering soon."
            )

        return {
            "product_id": product_id,
            "product_name": product.product_name,
            "unit": base_unit,
            "total_current_stock": round(total_current, 2),
            "reorder_threshold": round(total_reorder, 2),
            "historical_metrics": {
                "six_month_outflow": round(total_outflow, 2),
                "six_month_inflow": round(total_inflow, 2),
                "average_monthly_outflow": round(avg_monthly_outflow, 2),
                "average_monthly_inflow": round(avg_monthly_inflow, 2),
            },
            "days_of_coverage": round(days_of_coverage, 1),
            "warning_level": warning_level,
            "recommendation": recommendation,
            "forecast_next_3_months": projections,
        }
