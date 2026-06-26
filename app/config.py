import os
import shutil
from pathlib import Path

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# ── Database Configuration ────────────────────────────────────────────────────
# On Windows (development), use the project-root SQLite file.
# On Linux/Vercel (serverless), copy the pre-seeded DB from the bundled source
# to /tmp (the only writeable path in serverless runtimes) so that:
#   a) The app starts with regional data already seeded, and
#   b) Write operations (new transactions) don't crash with "Read-only filesystem".
#
# Override completely via the DATABASE_URL environment variable (e.g. PostgreSQL
# for a fully persistent production setup).

if os.name == "nt":
    # Development on Windows
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'agriculture_stock.db'}",
    )
else:
    # Serverless / Linux (Vercel)
    _tmp_db = Path("/tmp/agriculture_stock.db")
    _src_db = BASE_DIR / "agriculture_stock.db"

    # Copy the pre-seeded DB to /tmp on first cold-start (or if it was wiped)
    if not _tmp_db.exists() and _src_db.exists():
        try:
            shutil.copy2(str(_src_db), str(_tmp_db))
        except OSError:
            pass  # If copy fails (e.g. source not bundled), start with blank DB

    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:////tmp/agriculture_stock.db")

# ── Business Logic ────────────────────────────────────────────────────────────
ALLOW_NEGATIVE_STOCK = os.getenv("ALLOW_NEGATIVE_STOCK", "False").lower() in ("true", "1", "yes")

# ── Data Directory Configuration ─────────────────────────────────────────────
if os.name == "nt":
    DATA_RAW_DIR = Path(os.getenv("DATA_RAW_DIR", str(BASE_DIR / "datesets folder")))
    DATA_PROCESSED_DIR = Path(os.getenv("DATA_PROCESSED_DIR", str(BASE_DIR / "data" / "processed")))
    DATA_ERROR_LOGS_DIR = Path(os.getenv("DATA_ERROR_LOGS_DIR", str(BASE_DIR / "data" / "error_logs")))
else:
    # Serverless or read-only UNIX environments like Vercel — write to /tmp only
    DATA_RAW_DIR = Path(os.getenv("DATA_RAW_DIR", "/tmp/datesets_folder"))
    DATA_PROCESSED_DIR = Path(os.getenv("DATA_PROCESSED_DIR", "/tmp/data/processed"))
    DATA_ERROR_LOGS_DIR = Path(os.getenv("DATA_ERROR_LOGS_DIR", "/tmp/data/error_logs"))

# Ensure paths exist — wrapped in try/except to survive read-only build contexts
for _dir in (DATA_RAW_DIR, DATA_PROCESSED_DIR, DATA_ERROR_LOGS_DIR):
    try:
        _dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # Read-only filesystem during Vercel build step — safe to skip
