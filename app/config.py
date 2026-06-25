import os
from pathlib import Path

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Database Config — use absolute path so it always resolves to the project root
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'agriculture_stock.db'}")

# For Vercel/Serverless environments, SQLite is read-only unless stored in /tmp.
# If hosting on Vercel, it is highly recommended to use a PostgreSQL database.
if os.getenv("VERCEL"):
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/agriculture_stock.db")

# Business Logic Config
ALLOW_NEGATIVE_STOCK = os.getenv("ALLOW_NEGATIVE_STOCK", "False").lower() in ("true", "1", "yes")

# Data Directories Config
DATA_RAW_DIR = Path(os.getenv("DATA_RAW_DIR", BASE_DIR / "datesets folder"))
DATA_PROCESSED_DIR = Path(os.getenv("DATA_PROCESSED_DIR", BASE_DIR / "data" / "processed"))
DATA_ERROR_LOGS_DIR = Path(os.getenv("DATA_ERROR_LOGS_DIR", BASE_DIR / "data" / "error_logs"))

# Ensure paths exist
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
DATA_ERROR_LOGS_DIR.mkdir(parents=True, exist_ok=True)
