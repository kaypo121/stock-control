from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Farmer(Base):
    __tablename__ = "farmers"

    farmer_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    phone_number: Mapped[str | None] = mapped_column(String, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    district: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    farm_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    # Relationships
    transactions: Mapped[list["StockTransaction"]] = relationship(
        "StockTransaction",
        back_populates="farmer",
        cascade="all, delete-orphan",
    )
    balances: Mapped[list["StockBalance"]] = relationship(
        "StockBalance", back_populates="farmer", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["StockAlert"]] = relationship(
        "StockAlert", back_populates="farmer", cascade="all, delete-orphan"
    )


class Product(Base):
    __tablename__ = "products"

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    product_name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    unit: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Base unit (e.g., kg, bags, crates, liters, tons)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    # Relationships
    transactions: Mapped[list["StockTransaction"]] = relationship(
        "StockTransaction",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    balances: Mapped[list["StockBalance"]] = relationship(
        "StockBalance", back_populates="product", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["StockAlert"]] = relationship(
        "StockAlert", back_populates="product", cascade="all, delete-orphan"
    )


class Warehouse(Base):
    __tablename__ = "warehouses"

    warehouse_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    warehouse_name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    district: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    capacity: Mapped[float | None] = mapped_column(Float, nullable=True)  # Storage capacity in base units or tons
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    # Relationships
    transactions: Mapped[list["StockTransaction"]] = relationship("StockTransaction", back_populates="warehouse")
    balances: Mapped[list["StockBalance"]] = relationship("StockBalance", back_populates="warehouse")
    alerts: Mapped[list["StockAlert"]] = relationship("StockAlert", back_populates="warehouse")


class StockTransaction(Base):
    __tablename__ = "stock_transactions"

    transaction_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    farmer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("farmers.farmer_id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.product_id", ondelete="CASCADE"),
        nullable=False,
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("warehouses.warehouse_id", ondelete="SET NULL"),
        nullable=True,
    )

    # Transaction types: STOCK_IN, STOCK_OUT, DAMAGE, RETURN, TRANSFER, ADJUSTMENT
    transaction_type: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[float] = mapped_column(
        Float, nullable=False
    )  # Stored in base unit of product (or after conversion)
    unit: Mapped[str] = mapped_column(String, nullable=False)  # Transaction unit recorded
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    reference_note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
    )

    # Relationships
    farmer: Mapped["Farmer"] = relationship("Farmer", back_populates="transactions")
    product: Mapped["Product"] = relationship("Product", back_populates="transactions")
    warehouse: Mapped["Warehouse | None"] = relationship("Warehouse", back_populates="transactions")


class StockBalance(Base):
    __tablename__ = "stock_balances"

    balance_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    farmer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("farmers.farmer_id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.product_id", ondelete="CASCADE"),
        nullable=False,
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("warehouses.warehouse_id", ondelete="CASCADE"),
        nullable=True,
    )

    opening_stock: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_stock: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reorder_level: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda context: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    farmer: Mapped["Farmer"] = relationship("Farmer", back_populates="balances")
    product: Mapped["Product"] = relationship("Product", back_populates="balances")
    warehouse: Mapped["Warehouse | None"] = relationship("Warehouse", back_populates="balances")

    # Enforce uniqueness of balance record per farmer, product, and warehouse location
    __table_args__ = (
        UniqueConstraint(
            "farmer_id",
            "product_id",
            "warehouse_id",
            name="_farmer_product_warehouse_uc",
        ),
    )


class StockAlert(Base):
    __tablename__ = "stock_alerts"

    alert_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    farmer_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("farmers.farmer_id", ondelete="CASCADE"),
        nullable=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.product_id", ondelete="CASCADE"),
        nullable=False,
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("warehouses.warehouse_id", ondelete="CASCADE"),
        nullable=True,
    )

    alert_type: Mapped[str] = mapped_column(String, nullable=False)  # e.g., LOW_STOCK, UNIT_MISMATCH
    alert_message: Mapped[str] = mapped_column(String, nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    farmer: Mapped["Farmer | None"] = relationship("Farmer", back_populates="alerts")
    product: Mapped["Product"] = relationship("Product", back_populates="alerts")
    warehouse: Mapped["Warehouse | None"] = relationship("Warehouse", back_populates="alerts")


class ImportLog(Base):
    __tablename__ = "import_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    import_status: Mapped[str] = mapped_column(String, nullable=False)  # SUCCESS, FAILED, PARTIAL
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
