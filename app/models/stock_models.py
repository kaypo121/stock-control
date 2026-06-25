from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base

class Farmer(Base):
    __tablename__ = "farmers"

    farmer_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    full_name = Column(String, nullable=False, index=True)
    phone_number = Column(String, nullable=True)
    region = Column(String, nullable=True, index=True)
    district = Column(String, nullable=True, index=True)
    farm_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    transactions = relationship("StockTransaction", back_populates="farmer", cascade="all, delete-orphan")
    balances = relationship("StockBalance", back_populates="farmer", cascade="all, delete-orphan")
    alerts = relationship("StockAlert", back_populates="farmer", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    product_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    product_name = Column(String, nullable=False, unique=True, index=True)
    category = Column(String, nullable=True, index=True)
    unit = Column(String, nullable=False)  # Base unit (e.g., kg, bags, crates, liters, tons)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    transactions = relationship("StockTransaction", back_populates="product", cascade="all, delete-orphan")
    balances = relationship("StockBalance", back_populates="product", cascade="all, delete-orphan")
    alerts = relationship("StockAlert", back_populates="product", cascade="all, delete-orphan")


class Warehouse(Base):
    __tablename__ = "warehouses"

    warehouse_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    warehouse_name = Column(String, nullable=False, unique=True, index=True)
    region = Column(String, nullable=True, index=True)
    district = Column(String, nullable=True, index=True)
    capacity = Column(Float, nullable=True)  # Storage capacity in base units or tons
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    transactions = relationship("StockTransaction", back_populates="warehouse")
    balances = relationship("StockBalance", back_populates="warehouse")
    alerts = relationship("StockAlert", back_populates="warehouse")


class StockTransaction(Base):
    __tablename__ = "stock_transactions"

    transaction_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    farmer_id = Column(Integer, ForeignKey("farmers.farmer_id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.warehouse_id", ondelete="SET NULL"), nullable=True)
    
    # Transaction types: STOCK_IN, STOCK_OUT, DAMAGE, RETURN, TRANSFER, ADJUSTMENT
    transaction_type = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)  # Stored in base unit of product (or after conversion)
    unit = Column(String, nullable=False)      # Transaction unit recorded
    transaction_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    reference_note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    farmer = relationship("Farmer", back_populates="transactions")
    product = relationship("Product", back_populates="transactions")
    warehouse = relationship("Warehouse", back_populates="transactions")


class StockBalance(Base):
    __tablename__ = "stock_balances"

    balance_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    farmer_id = Column(Integer, ForeignKey("farmers.farmer_id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.warehouse_id", ondelete="CASCADE"), nullable=True)
    
    opening_stock = Column(Float, default=0.0, nullable=False)
    current_stock = Column(Float, default=0.0, nullable=False)
    reorder_level = Column(Float, default=0.0, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    farmer = relationship("Farmer", back_populates="balances")
    product = relationship("Product", back_populates="balances")
    warehouse = relationship("Warehouse", back_populates="balances")

    # Enforce uniqueness of balance record per farmer, product, and warehouse location
    __table_args__ = (
        UniqueConstraint('farmer_id', 'product_id', 'warehouse_id', name='_farmer_product_warehouse_uc'),
    )


class StockAlert(Base):
    __tablename__ = "stock_alerts"

    alert_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    farmer_id = Column(Integer, ForeignKey("farmers.farmer_id", ondelete="CASCADE"), nullable=True)
    product_id = Column(Integer, ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.warehouse_id", ondelete="CASCADE"), nullable=True)
    
    alert_type = Column(String, nullable=False)  # e.g., LOW_STOCK, UNIT_MISMATCH
    alert_message = Column(String, nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    # Relationships
    farmer = relationship("Farmer", back_populates="alerts")
    product = relationship("Product", back_populates="alerts")
    warehouse = relationship("Warehouse", back_populates="alerts")


class ImportLog(Base):
    __tablename__ = "import_logs"

    log_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    file_name = Column(String, nullable=False)
    import_status = Column(String, nullable=False)  # SUCCESS, FAILED, PARTIAL
    records_processed = Column(Integer, default=0, nullable=False)
    records_failed = Column(Integer, default=0, nullable=False)
    error_summary = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
