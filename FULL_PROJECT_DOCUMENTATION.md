# Ghana Agricultural Stock Management System
## Full Project Documentation

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Project Structure](#3-project-structure)
4. [Datasets Used](#4-datasets-used)
5. [Core Modules](#5-core-modules)
6. [API Reference](#6-api-reference)
7. [Installation & Setup](#7-installation--setup)
8. [Usage Guide](#8-usage-guide)
9. [Database Schema](#9-database-schema)
10. [Testing](#10-testing)

---

## 1. Project Overview

This system is a complete agricultural stock management and quality assessment platform built specifically for Ghana's agricultural sector. Key features include:
- **Stock Control Module**: Track inventory movements (in/out/adjustment/transfer/damage), real-time balances, low-stock alerts
- **Quality Assessment Module**: Evaluate crops, fruits, vegetables, livestock, poultry, and fish with auto-scoring
- **Data Integration AI**: 7-step pipeline for importing Ghana MoFA datasets and other agricultural data
- **Forecasting**: Predict demand, days-of-coverage, and 3-month projections
- **Dashboard UI**: Simple web interface for accessing all features

---

## 2. System Architecture

The application uses a modern, layered architecture:
```
┌─────────────────────────────────────────┐
│         Web Interface (Static)          │
└─────────────────────┬───────────────────┘
┌─────────────────────▼───────────────────┐
│         FastAPI Application             │
│  • API Endpoints                        │
│  • Dependency Injection (DB sessions)   │
└─────────────────────┬───────────────────┘
┌─────────────────────▼───────────────────┐
│         Services Layer                  │
│  • StockService (movement logic)        │
│  • QualityAssessmentService             │
│  • ImportService / DataIntegrationService│
│  • ForecastService                      │
└─────────────────────┬───────────────────┘
┌─────────────────────▼───────────────────┐
│         Repository Layer                │
│  • StockRepository (CRUD operations)    │
└─────────────────────┬───────────────────┘
┌─────────────────────▼───────────────────┐
│         Database Layer                  │
│  • SQLAlchemy ORM                       │
│  • SQLite (default) / PostgreSQL        │
└─────────────────────────────────────────┘
```

Tech stack:
- **Backend Framework**: FastAPI (async, auto-documenting via OpenAPI/Swagger)
- **ORM**: SQLAlchemy 2.0+
- **Data Handling**: Pandas, OpenPyXL
- **Validation**: Pydantic 2.x
- **Database**: SQLite (default, dev) / PostgreSQL (prod)

---

## 3. Project Structure

```
agriculture-database/
├── app/
│   ├── __init__.py
│   ├── config.py              # Configuration settings
│   ├── database.py            # DB engine, session management
│   ├── main.py                # FastAPI app entrypoint
│   │
│   ├── models/
│   │   ├── stock_models.py    # Stock control DB models
│   │   ├── quality_models.py  # Quality assessment DB models
│   │   └── integration_models.py # Data integration DB models
│   │
│   ├── schemas/
│   │   ├── stock_schemas.py   # Pydantic for stock module
│   │   ├── quality_schemas.py # Pydantic for quality module
│   │   └── integration_schemas.py # Pydantic for integration module
│   │
│   ├── services/
│   │   ├── stock_service.py       # Stock movement logic
│   │   ├── quality_service.py     # Quality scoring & recommendations
│   │   ├── import_service.py      # CSV/Excel import pipeline
│   │   ├── integration_service.py # Full AI integration pipeline
│   │   └── forecast_service.py    # Demand forecasting
│   │
│   ├── repositories/
│   │   └── stock_repo.py          # CRUD operations for DB
│   │
│   ├── utils/
│   │   └── unit_converter.py      # Unit conversion (e.g. tons → kg)
│   │
│   └── api/
│       ├── endpoints.py           # Stock control API
│       ├── quality_endpoints.py   # Quality assessment API
│       └── integration_endpoints.py # Integration AI API
│
├── static/
│   ├── index.html          # Web dashboard
│   └── favicon.png
│
├── datesets folder/               # Raw datasets directory
│   ├── agricultural-production-estimates-1993-2017-All-2026-06-04_2242 (1)/
│   ├── crop-production-estimates-in-major-regions-in-ghana-All-2026-06-04_2240/
│   ├── Production_Crops_Livestock_E_All_Data/
│   ├── synthetic_datasets/       # AI-generated synthetic data
│   ├── national cropped area 2019 to 2023.csv
│   ├── national production 2019 to 2023.csv
│   └── [other datasets & docs]
│
├── tests/
│   ├── conftest.py
│   └── test_stock_control.py
│
├── generate_synthetic_data.py  # Generate & seed synthetic data
├── seed_crops.py               # Seed Ghana MoFA crop/region data
├── seed_data.py                # Seed test data
├── inspect_docx.py             # Read dataset documentation DOCX files
├── run.py                      # Run development server
├── requirements.txt
├── vercel.json                 # Vercel deployment config
└── agriculture_stock.db        # Default SQLite DB
```

---

## 4. Datasets Used

### Primary Datasets (Used Directly in the App)
| Dataset Name | Type | Source | Access Status | Purpose |
|---|---|---|---|---|
| `national cropped area 2019 to 2023.csv` | CSV | Ghana MoFA - SRID | Available | Cropped area statistics by commodity |
| `national production 2019 to 2023.csv` | CSV | Ghana MoFA - SRID | Available | National production volumes by commodity |
| `PRODUCTION ESTIMATES.csv` (from `agricultural-production-estimates-1993-2017-All-2026-06-04_2242 (1)` ) | CSV | Ghana Open Data (data.gov.gh) | Available | Historical production estimates used in `seed_crops.py` |
| `Crop production Data SRID (2).csv` (from `crop-production-estimates-in-major-regions-in-ghana-All-2026-06-04_2240`) | CSV | Ghana Open Data (data.gov.gh) | Available | Regional production estimates |
| Synthetic datasets (`maize_synthetic_1993_2024.csv`, etc.) | CSV | Generated | Available | Synthetic transaction data for Tomato, Yam, Maize, Rice (used in `generate_synthetic_data.py`) |

### Secondary Datasets (Reference/Background)
| Dataset Name | Type | Source |
|---|---|---|
| Commodity Prices (04.11.25) | CSV | Ghana MoFA - SRID |
| GHA 2017/18 Country Assessment (Main Results, Full Report, Methodology, Questionnaires) | PDF | FAO Microdata Library |
| Ghana Admin Boundaries | Shapefile/GeoJSON | [Unspecified] |
| `Production_Crops_Livestock_E_All_Data.csv` | CSV | FAO (FAOSTAT) |
| Valuing post-harvest losses among tomato smallholder farmers | PDF | [Unspecified] |
| WLD RTP details (World food price data) | CSV | [Unspecified] |

---

## 5. Core Modules

### 5.1 Stock Control Module (`app/models/stock_models.py`, `app/services/stock_service.py`)

Key Entities:
- **Farmer**: Individual or cooperative farmer (region, district, farm name)
- **Product**: Agricultural commodity (name, category, base unit)
- **Warehouse**: Storage location (name, region, capacity)
- **StockTransaction**: Movement log (in/out/adjustment/damage/transfer/return)
- **StockBalance**: Real-time inventory level for (farmer, product, warehouse)
- **StockAlert**: Low-stock and unit-mismatch alerts
- **ImportLog**: History of import pipeline runs

Features:
- Auto unit conversion (via `unit_converter.py`)
- Prevents negative stock (configurable via `ALLOW_NEGATIVE_STOCK`)
- Auto-generates low-stock alerts

### 5.2 Quality Assessment Module (`app/models/quality_models.py`, `app/services/quality_service.py`)

Covers:
- **Crops / Fruits / Vegetables**: Ripeness, freshness, damage, shelf life
- **Livestock**: BCS, health, mobility, vaccination
- **Poultry**: Weight, feather condition, egg production
- **Fish**: Freshness, eye clarity, gill condition, odor, flesh quality

Scoring & Outputs:
- Quality Score (0–100)
- Market Readiness Score
- Estimated Market Value (GHS)
- Grade Classification (Premium → Reject)
- Purchase Recommendation (Buy / Buy with Caution / Do Not Buy)

### 5.3 Data Integration AI Module (`app/models/integration_models.py`, `app/services/integration_service.py`)

7-Step Pipeline:
1. **Analyse**: Detect schema, missing values, duplicates, invalid data
2. **Clean**: Remove duplicates, fill nulls, standardise units, correct formats
3. **Map**: Auto-detect and map columns to DB fields
4. **Integrate**: Insert farmers, products, warehouses, transactions
5. **Process**: Compute balances, turnover rates, reorder levels
6. **Validate**: Constraint checks, duplicate IDs, quantity anomalies
7. **Report**: Generate 5 reports (import, stock summary, availability, health, alerts)

### 5.4 Forecast Module (`app/services/forecast_service.py`)

Generates:
- Total current stock
- 6-month historical inflow/outflow
- Average daily/monthly outflow rates
- Days of Coverage (DoC)
- 3-month stock projections
- Warning levels & recommendations

---

## 6. API Reference

The full auto-generated API docs are available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Stock Control Endpoints (`/stock`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/in` | Record stock incoming |
| POST | `/out` | Record stock outgoing |
| POST | `/adjustment` | Record adjustment/damage/transfer/return |
| GET | `/current` | List all inventory balances |
| GET | `/current/{farmer_id}` | Farmer-specific balances |
| GET | `/current/{farmer_id}/{product_id}` | Specific farmer-product balance |
| GET | `/transactions` | Audit log of movements |
| GET | `/alerts` | Active alerts |
| GET | `/low-stock` | Items below reorder level |
| POST | `/import` | Run import pipeline on raw data dir |
| GET | `/import/logs` | Import history |
| GET | `/forecast/{product_id}` | Get product forecast |
| POST | `/farmers` | Register new farmer |
| GET | `/farmers` | List farmers |
| POST | `/products` | Register new product |
| GET | `/products` | List products |
| POST | `/warehouses` | Register new warehouse |
| GET | `/warehouses` | List warehouses |

### Quality Assessment Endpoints (`/quality`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/assess` | Submit new quality assessment |
| GET | `/assessments` | List assessments (filterable) |
| GET | `/assessments/{id}` | Get single assessment |
| DELETE | `/assessments/{id}` | Delete assessment |
| GET | `/summary` | Aggregated quality stats |
| GET | `/categories` | Enum reference for categories, grades, etc. |

### Data Integration AI Endpoints (`/integration`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/upload` | Upload file & run full pipeline |
| POST | `/scan` | Scan raw data dir & run pipeline |
| GET | `/sessions` | List import sessions |
| GET | `/sessions/{id}` | Session detail |
| DELETE | `/sessions/{id}` | Delete session |
| GET | `/sessions/{id}/reports` | List reports for a session |
| GET | `/reports/standalone` | Generate reports from live DB |
| GET | `/reports/{id}` | Get full report JSON |
| GET | `/inventory` | Live inventory stats |
| GET | `/health` | Quick inventory health snapshot |

---

## 7. Installation & Setup

### 7.1 Prerequisites
- Python 3.10 or higher

### 7.2 Step-by-Step Installation
```bash
# 1. Navigate to project directory
cd "agriculture database"

# 2. (Optional) Create & activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

### 7.3 Configuration
Edit `app/config.py` or set environment variables to configure:
- `DATABASE_URL`: Path to SQLite file or PostgreSQL connection string
- `ALLOW_NEGATIVE_STOCK`: Set to `True` to allow negative stock (default: `False`)
- `DATA_RAW_DIR`: Path to raw datasets folder
- `DATA_PROCESSED_DIR`: Path for processed data
- `DATA_ERROR_LOGS_DIR`: Path for error logs

### 7.4 Initialize Database & Seed Data
Run the seeding scripts (optional but recommended):
```bash
# Seed MoFA crop/region data
python seed_crops.py

# Generate & seed synthetic data
python generate_synthetic_data.py
```

### 7.5 Run the Server
```bash
# Run development server
python run.py
# OR directly with uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The app will be available at: http://localhost:8000

---

## 8. Usage Guide

### 8.1 Web Dashboard
Open http://localhost:8000 in your browser to access the simple dashboard.

### 8.2 Recording Stock Movements
Use `/stock/in`, `/stock/out`, or `/stock/adjustment` endpoints. All movements automatically:
- Convert units to the product's base unit
- Update real-time stock balances
- Check for negative stock
- Trigger low-stock alerts if needed

### 8.3 Importing Historical Data
1. Place CSV/Excel files in `datesets folder/`
2. Call `POST /stock/import` or `POST /integration/scan` (for full AI pipeline)

### 8.4 Quality Assessment Example
For a batch of tomatoes:
```json
POST /quality/assess
{
  "batch_number": "TOM-2025-06-001",
  "product_name": "Tomato",
  "category": "Vegetable",
  "assessed_by": "Inspector 1",
  "produce_attributes": {
    "weight_kg": 500,
    "color_quality": "Bright Red",
    "freshness_score": 8.5,
    "ripeness_level": "Ripe",
    "visible_damage_pct": 5,
    "pest_damage_pct": 2,
    "disease_symptoms": "None",
    "estimated_shelf_life_days": 7
  }
}
```
Returns full scoring, grade, and purchase recommendation.

---

## 9. Database Schema

### Stock Control Tables (`app/models/stock_models.py`)
- **farmers** (`farmer_id`, `full_name`, `phone_number`, `region`, `district`, `farm_name`, `created_at`, `updated_at`)
- **products** (`product_id`, `product_name`, `category`, `unit`, `description`, `created_at`, `updated_at`)
- **warehouses** (`warehouse_id`, `warehouse_name`, `region`, `district`, `capacity`, `created_at`, `updated_at`)
- **stock_transactions** (`transaction_id`, `farmer_id`, `product_id`, `warehouse_id`, `transaction_type`, `quantity`, `unit`, `transaction_date`, `reference_note`, `created_at`, `updated_at`)
- **stock_balances** (`balance_id`, `farmer_id`, `product_id`, `warehouse_id`, `opening_stock`, `current_stock`, `reorder_level`, `last_updated`)
- **stock_alerts** (`alert_id`, `farmer_id`, `product_id`, `warehouse_id`, `alert_type`, `alert_message`, `is_resolved`, `created_at`, `resolved_at`)
- **import_logs** (`log_id`, `file_name`, `import_status`, `records_processed`, `records_failed`, `error_summary`, `created_at`)

### Quality Assessment Tables (`app/models/quality_models.py`)
- **quality_assessments** (master record)
- **produce_quality_details** (Crop/Fruit/Vegetable attributes)
- **livestock_quality_details** (Livestock attributes)
- **poultry_quality_details** (Poultry attributes)
- **fish_quality_details** (Fish attributes)

### Data Integration Tables (`app/models/integration_models.py`)
- **integration_sessions** (master import session record)
- **integration_error_records** (row-level errors)
- **integration_reports** (generated reports JSON)

---

## 10. Testing

Run the test suite with:
```bash
pytest tests/test_stock_control.py -v
```
Current test coverage includes:
- Stock balance updates
- Negative stock constraint
- Alert triggers
- Import pipeline validation

---

## Deployment

The app is configured for deployment on Vercel (see `vercel.json`). For other platforms:
- Use Gunicorn + Uvicorn workers for production
- Use PostgreSQL instead of SQLite
- Set environment variables for configuration

---

## License & Attributions

- Ghana MoFA datasets courtesy of Ghana Ministry of Food and Agriculture - Statistics, Research and Information Directorate (SRID)
- FAO datasets courtesy of the Food and Agriculture Organization of the United Nations
- Other datasets as documented in the `datesets folder/`

