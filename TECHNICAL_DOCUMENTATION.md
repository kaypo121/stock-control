# Agriculture Stock Control Module - Documentation

This document provides a comprehensive technical overview of the Agriculture Stock Control Module, covering the architecture, database design, business logic, API endpoints, and import pipeline.

---

## 1. System Architecture

The module is built using a modern Python stack designed for scalability and ease of integration:
- **Framework**: FastAPI (Asynchronous API)
- **Database**: SQLite (default) / PostgreSQL (via SQLAlchemy ORM)
- **Data Handling**: Pandas (Import pipeline)
- **Validation**: Pydantic (Request/Response schemas)
- **Testing**: Pytest

---

## 2. Database Design

The schema is normalized to track inventory across different farmers, products, and warehouse locations.

### **Entity-Relationship Overview**
- **Farmers**: Individuals or cooperatives owning the stock.
- **Products**: Agricultural commodities (e.g., Maize, Cocoa) with defined base units.
- **Warehouses**: Storage locations where stock is held.
- **Stock Transactions**: Audit trail of every movement (IN, OUT, DAMAGE, etc.).
- **Stock Balances**: Real-time inventory levels per farmer/product/location.
- **Stock Alerts**: Automated notifications for low stock or unit mismatches.
- **Import Logs**: History of data ingestion tasks.

### **Detailed Schema**
For full details on field types and relationships, refer to [stock_models.py](file:///c:/Users/ASUS/Desktop/agriculture%20database/app/models/stock_models.py).

---

## 3. Core Business Logic

### **Stock Movement Handling**
Located in [stock_service.py](file:///c:/Users/ASUS/Desktop/agriculture%20database/app/services/stock_service.py), the `record_movement` function is the heart of the system:
1. **Validation**: Checks for existing foreign keys (Farmer, Product, Warehouse).
2. **Unit Normalization**: Automatically converts transaction units (e.g., tons, bags) to the product's base unit (e.g., kg) using [unit_converter.py](file:///c:/Users/ASUS/Desktop/agriculture%20database/app/utils/unit_converter.py).
3. **Constraint Enforcement**: Prevents stock levels from dropping below zero unless `ALLOW_NEGATIVE_STOCK` is enabled in [config.py](file:///c:/Users/ASUS/Desktop/agriculture%20database/app/config.py).
4. **Automatic Alerting**: Triggers a `LOW_STOCK` alert if the current balance hits the `reorder_level`.

### **AI Forecasting Support**
The [forecast_service.py](file:///c:/Users/ASUS/Desktop/agriculture%20database/app/services/forecast_service.py) analyzes historical transaction data to provide:
- **Consumption Rates**: Average weekly and monthly outflows.
- **Runout Estimates**: "Days of Coverage" based on current stock.
- **Projections**: 3-month trend analysis for planning.

---

## 4. Data Import Pipeline

The [import_service.py](file:///c:/Users/ASUS/Desktop/agriculture%20database/app/services/import_service.py) is designed to handle messy historical data:
- **Fuzzy Matching**: Uses `difflib` to identify similar farmer or product names, preventing duplicate records.
- **Cleaning**: Trims whitespace, normalizes headers, and converts data types.
- **Error Logging**: Failed rows are written to a separate CSV in `data/error_logs/` for manual review.
- **Supported Formats**: CSV and Excel (.xlsx, .xls).

---

## 5. API Reference

The API is fully documented via Swagger UI at `http://127.0.0.1:8000/docs`. Key endpoint categories include:

| Category | Endpoint | Description |
| :--- | :--- | :--- |
| **Transactions** | `POST /stock/in` | Record incoming stock. |
| | `POST /stock/out` | Record outgoing stock. |
| | `POST /stock/adjustment` | Record damages or manual corrections. |
| **Balances** | `GET /stock/current` | List all inventory levels. |
| | `GET /stock/low-stock` | Filter items needing reorder. |
| **Automation** | `POST /stock/import` | Trigger bulk import from data folder. |
| | `GET /stock/forecast/{id}` | Get projections for a specific product. |

---

## 6. Installation & Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Configuration**:
   Modify [config.py](file:///c:/Users/ASUS/Desktop/agriculture%20database/app/config.py) or set environment variables for:
   - `DATABASE_URL`
   - `ALLOW_NEGATIVE_STOCK` (True/False)
3. **Run Server**:
   ```bash
   python run.py
   ```

---

## 7. Quality Assurance

Run the automated test suite to verify implementation:
```bash
pytest tests/test_stock_control.py
```
*Current test coverage includes: Balance updates, Negative stock prevention, Alert triggers, and Import pipeline validation.*
