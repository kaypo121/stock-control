import os
from pathlib import Path

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Database Config — use absolute path so it always resolves to the project root
# Determine database URL. Use local SQLite during development, and a /tmp SQLite file when running in a non‑Windows (e.g., Vercel) environment.
if os.name == "nt":
    # Development on Windows – allow configurable path via env var or default to project directory.
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'agriculture_stock.db'}",
    )
else:
    # Non‑Windows (Vercel/Linux) – SQLite must live in a writeable temporary directory.
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "sqlite:////tmp/agriculture_stock.db",
    )

# Business Logic Config
ALLOW_NEGATIVE_STOCK = os.getenv("ALLOW_NEGATIVE_STOCK", "False").lower() in ("true", "1", "yes")

# Data Directories Config
if os.name == "nt":
    DATA_RAW_DIR = Path(os.getenv("DATA_RAW_DIR", BASE_DIR / "datesets folder"))
    DATA_PROCESSED_DIR = Path(os.getenv("DATA_PROCESSED_DIR", BASE_DIR / "data" / "processed"))
    DATA_ERROR_LOGS_DIR = Path(os.getenv("DATA_ERROR_LOGS_DIR", BASE_DIR / "data" / "error_logs"))
else:
    # Serverless or read-only UNIX environments like Vercel
    DATA_RAW_DIR = Path(os.getenv("DATA_RAW_DIR", Path("/tmp") / "datesets_folder"))
    DATA_PROCESSED_DIR = Path(os.getenv("DATA_PROCESSED_DIR", Path("/tmp") / "data" / "processed"))
    DATA_ERROR_LOGS_DIR = Path(os.getenv("DATA_ERROR_LOGS_DIR", Path("/tmp") / "data" / "error_logs"))

# Ensure paths exist
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
DATA_ERROR_LOGS_DIR.mkdir(parents=True, exist_ok=True)
