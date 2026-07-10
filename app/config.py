import os
import shutil
from pathlib import Path

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent
APP_VERSION = os.getenv("APP_VERSION", "4.0.0")

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

# ── AI Gateway Configuration ──────────────────────────────────────────────────
GATEWAY_SECRET_KEY = os.getenv("GATEWAY_SECRET_KEY", "change-this-gateway-secret-in-production")
GATEWAY_REQUEST_SIGNING_SECRET = os.getenv(
    "GATEWAY_REQUEST_SIGNING_SECRET",
    "change-this-signing-secret-in-production",
)
GATEWAY_JWT_ALGORITHM = os.getenv("GATEWAY_JWT_ALGORITHM", "HS256")
GATEWAY_JWT_EXPIRES_MINUTES = int(os.getenv("GATEWAY_JWT_EXPIRES_MINUTES", "60"))
GATEWAY_API_KEY_EXPIRY_DAYS = int(os.getenv("GATEWAY_API_KEY_EXPIRY_DAYS", "90"))
GATEWAY_REQUEST_BODY_LIMIT_BYTES = int(os.getenv("GATEWAY_REQUEST_BODY_LIMIT_BYTES", str(2 * 1024 * 1024)))
GATEWAY_FILE_SIZE_LIMIT_BYTES = int(os.getenv("GATEWAY_FILE_SIZE_LIMIT_BYTES", str(25 * 1024 * 1024)))
GATEWAY_CACHE_TTL_SECONDS = int(os.getenv("GATEWAY_CACHE_TTL_SECONDS", "120"))
GATEWAY_RATE_LIMIT_MINUTE = int(os.getenv("GATEWAY_RATE_LIMIT_MINUTE", "120"))
GATEWAY_RATE_LIMIT_HOUR = int(os.getenv("GATEWAY_RATE_LIMIT_HOUR", "2000"))
GATEWAY_RATE_LIMIT_DAY = int(os.getenv("GATEWAY_RATE_LIMIT_DAY", "10000"))
GATEWAY_BURST_LIMIT = int(os.getenv("GATEWAY_BURST_LIMIT", "30"))
GATEWAY_ENABLE_CSRF = os.getenv("GATEWAY_ENABLE_CSRF", "true").lower() in ("true", "1", "yes")
GATEWAY_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("GATEWAY_ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]
GATEWAY_ALLOWED_IPS = {
    ip.strip()
    for ip in os.getenv("GATEWAY_ALLOWED_IPS", "").split(",")
    if ip.strip()
}
GATEWAY_CORS_ALLOW_CREDENTIALS = os.getenv("GATEWAY_CORS_ALLOW_CREDENTIALS", "false").lower() in ("true", "1", "yes")
if os.name == "nt":
    _default_gateway_upload_dir = BASE_DIR / "data" / "gateway_uploads"
else:
    _default_gateway_upload_dir = Path("/tmp/data/gateway_uploads")
GATEWAY_UPLOAD_DIR = Path(os.getenv("GATEWAY_UPLOAD_DIR", str(_default_gateway_upload_dir)))
try:
    GATEWAY_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
GATEWAY_SUPPORTED_FILE_TYPES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".csv",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
    ".json",
    ".zip",
    ".mp3",
    ".wav",
    ".mp4",
    ".mov",
}
AI_PROVIDER_TIMEOUT_SECONDS = int(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "60"))
