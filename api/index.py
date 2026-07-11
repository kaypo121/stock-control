import sys
from pathlib import Path

# Add project root to sys.path so that `app.*` imports resolve correctly
# in Vercel's serverless environment where the CWD may not be the project root.
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.main import app  # noqa: F401,E402 – re-export for Vercel ASGI handler
