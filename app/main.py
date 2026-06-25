from fastapi import FastAPI
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import engine, Base
from app.api.endpoints import router as stock_router
from app.api.quality_endpoints import router as quality_router
from app.api.integration_endpoints import router as integration_router
from pathlib import Path

# Import all models so SQLAlchemy registers them before create_all
import app.models.stock_models      # noqa: F401
import app.models.quality_models    # noqa: F401
import app.models.integration_models # noqa: F401

# Create all database tables (stock + quality + integration)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Agriculture Stock Control, Quality Assessment & Data Integration AI",
    description="""
**Complete Agricultural Management System for Ghana**

### 📦 Stock Control Module  `/stock/`
- Record stock movements (in / out / adjustments / transfers)
- Real-time balance tracking per farmer and warehouse
- Low-stock alerts and reorder level management
- CSV/Excel data import pipeline
- 3-month demand forecasting

### 🔬 Quality Assessment Module  `/quality/`
Pre-purchase quality evaluation for all agricultural products:
- **Crops / Fruits / Vegetables** — Freshness, ripeness, damage %, shelf-life
- **Livestock** — BCS, health, mobility, vaccination
- **Poultry** — Weight, feather condition, egg production
- **Fish** — Freshness, eye clarity, gill condition, odor, flesh quality

Every assessment returns Quality Score · Market Readiness · GHS Value · Grade · Buy/Caution/Reject

### 🤖 Data Integration AI  `/integration/`
Full 7-step automated data pipeline:
1. **Analyse** — Structure, missing values, duplicates, invalid data detection
2. **Clean** — Dedup, null-fill, unit standardisation, format correction
3. **Map** — Auto-detect schema, map to database fields
4. **Integrate** — Insert Farmers, Products, Warehouses, Transactions, Quality Assessments
5. **Process** — Current stock, available stock, turnover rates, reorder levels
6. **Validate** — Constraint checks, duplicate IDs, warehouse assignment, quantity anomalies
7. **Report** — Data Import · Stock Summary · Product Availability · Inventory Health · Low-Stock Alerts

Supports: **CSV · Excel · JSON** — including Ghana MoFA production datasets
    """,
    version="3.0.0",
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the dashboard at root — redirect "/" to the dashboard HTML
@app.get("/", include_in_schema=False)
def root():
    static_path = Path(__file__).parent.parent / "static" / "index.html"
    return FileResponse(str(static_path))

# Mount static files (CSS/JS if ever needed as separate files)
static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Register routes
app.include_router(stock_router)
app.include_router(quality_router)
app.include_router(integration_router)
