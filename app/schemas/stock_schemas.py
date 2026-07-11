from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ----------------- Farmer Schemas -----------------
class FarmerBase(BaseModel):
    full_name: str = Field(..., description="Farmer's full name")
    phone_number: Optional[str] = Field(None, description="Contact phone number")
    region: Optional[str] = Field(
        None, description="Ghana administrative region (e.g. Ashanti, Volta)"
    )
    district: Optional[str] = Field(None, description="District location")
    farm_name: Optional[str] = Field(None, description="Name of the farm")


class FarmerCreate(FarmerBase):
    pass


class FarmerResponse(FarmerBase):
    model_config = ConfigDict(from_attributes=True)

    farmer_id: int
    created_at: datetime
    updated_at: datetime


# ----------------- Product Schemas -----------------
class ProductBase(BaseModel):
    product_name: str = Field(
        ..., description="Unique name of agricultural crop/product"
    )
    category: Optional[str] = Field(
        None, description="Product category (e.g. Grains, Tubers, Vegetables)"
    )
    unit: str = Field(
        ...,
        description="Base standard unit of measure (e.g. kg, bags, crates, liters)",
    )
    description: Optional[str] = Field(None, description="Description of the product")


class ProductCreate(ProductBase):
    pass


class ProductResponse(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    created_at: datetime
    updated_at: datetime


# ----------------- Warehouse Schemas -----------------
class WarehouseBase(BaseModel):
    warehouse_name: str = Field(
        ..., description="Unique name of storage location/warehouse"
    )
    region: Optional[str] = Field(None, description="Region of warehouse")
    district: Optional[str] = Field(None, description="District of warehouse")
    capacity: Optional[float] = Field(
        None, description="Storage capacity in base units"
    )


class WarehouseCreate(WarehouseBase):
    pass


class WarehouseResponse(WarehouseBase):
    model_config = ConfigDict(from_attributes=True)

    warehouse_id: int
    created_at: datetime
    updated_at: datetime


# ----------------- Transaction Schemas -----------------
class StockTransactionBase(BaseModel):
    farmer_id: int = Field(..., description="ID of the associated farmer")
    product_id: int = Field(..., description="ID of the product being moved")
    warehouse_id: Optional[int] = Field(
        None, description="ID of warehouse location (optional)"
    )
    quantity: float = Field(..., description="Quantity of product moved")
    unit: str = Field(..., description="Unit of measurement used in the transaction")
    reference_note: Optional[str] = Field(
        None, description="Reference notes (e.g., harvest ID, sales invoice)"
    )

    @field_validator("quantity")
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError(
                "Quantity must be strictly positive. Deductions must be specified via transaction types."
            )
        return v


class StockTransactionCreate(StockTransactionBase):
    transaction_date: Optional[datetime] = Field(
        default_factory=datetime.now(timezone.utc),
        description="Date of transaction",
    )


class StockTransactionResponse(StockTransactionBase):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: int
    transaction_type: str
    transaction_date: datetime
    created_at: datetime


class StockAdjustmentCreate(BaseModel):
    farmer_id: int
    product_id: int
    warehouse_id: Optional[int] = None
    quantity: float = Field(
        ...,
        description="Quantity adjustment amount (positive to add, negative to deduct)",
    )
    unit: str
    reference_note: str = Field(
        ..., description="Reason/Reference note for the adjustment"
    )
    transaction_type: str = Field(
        "ADJUSTMENT",
        description="Must be either DAMAGE, RETURN, ADJUSTMENT, or TRANSFER",
    )

    @field_validator("transaction_type")
    def validate_type(cls, v):
        allowed = ["DAMAGE", "RETURN", "ADJUSTMENT", "TRANSFER"]
        if v not in allowed:
            raise ValueError(f"Transaction type must be one of {allowed}")
        return v


# ----------------- Stock Balance Schemas -----------------
class StockBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    balance_id: int
    farmer_id: int
    product_id: int
    warehouse_id: Optional[int]
    opening_stock: float
    current_stock: float
    reorder_level: float
    last_updated: datetime


class BalanceSummary(BaseModel):
    farmer_name: str
    product_name: str
    warehouse_name: Optional[str]
    current_stock: float
    unit: str
    reorder_level: float
    status: str  # 'NORMAL' or 'LOW_STOCK'


# ----------------- Stock Alert Schemas -----------------
class StockAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_id: int
    farmer_id: Optional[int]
    product_id: int
    warehouse_id: Optional[int]
    alert_type: str
    alert_message: str
    is_resolved: bool
    created_at: datetime
    resolved_at: Optional[datetime]


# ----------------- Import Log Schemas -----------------
class ImportLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    log_id: int
    file_name: str
    import_status: str
    records_processed: int
    records_failed: int
    error_summary: Optional[str]
    created_at: datetime


class ImportResult(BaseModel):
    status: str
    imported_count: int
    failed_count: int
    error_log_file: Optional[str] = None
    message: str
