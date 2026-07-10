import json
from pathlib import Path

from app.main import app


def main() -> None:
    output_dir = Path("openapi")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "ai_gateway_openapi.json"
    output_path.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"OpenAPI specification exported to {output_path}")


if __name__ == "__main__":
    main()
