#!/usr/bin/env python3
"""
Migrate local agriculture_stock.db (SQLite) to Render Postgres.

Reads every row from SQLite, preserves primary-key IDs and foreign-key
relationships, and batch-inserts into Postgres.  Gateway tables are skipped
by default because production bootstraps its own credentials on startup.

Examples (PowerShell):
    # Preview counts without writing
    python tools/migrate_sqlite_to_postgres.py --dry-run

    # Migrate (requires DATABASE_URL)
    $env:DATABASE_URL = "postgresql://user:pass@host:5432/agriculture_stock"
    python tools/migrate_sqlite_to_postgres.py --force

    # Custom SQLite path
    python tools/migrate_sqlite_to_postgres.py --sqlite-path "C:\\path\\to\\agriculture_stock.db" --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import Base

# Register every mapped table before create_all / metadata lookups.
import app.models.gateway_models  # noqa: F401, E402
import app.models.integration_models  # noqa: E402
import app.models.quality_models  # noqa: E402
import app.models.stock_models  # noqa: E402

DEFAULT_SQLITE = ROOT / "agriculture_stock.db"
BATCH_SIZE = 1000

# Insert order respects foreign-key dependencies (parents before children).
BUSINESS_TABLES: list[str] = [
    "farmers",
    "products",
    "warehouses",
    "stock_transactions",
    "stock_balances",
    "stock_alerts",
    "import_logs",
    "quality_assessments",
    "produce_quality_details",
    "livestock_quality_details",
    "poultry_quality_details",
    "fish_quality_details",
    "integration_sessions",
    "integration_error_records",
    "integration_reports",
]

GATEWAY_TABLES: list[str] = [
    "gateway_principals",
    "gateway_api_keys",
    "gateway_sessions",
    "gateway_request_logs",
    "gateway_audit_logs",
    "gateway_rate_limit_buckets",
    "gateway_events",
    "gateway_webhook_endpoints",
    "gateway_webhook_deliveries",
    "gateway_dead_letters",
    "gateway_tasks",
    "gateway_file_assets",
    "gateway_nonces",
    "gateway_plugins",
]

# Map table → single-column integer primary key for sequence reset.
PK_COLUMNS: dict[str, str] = {
    "farmers": "farmer_id",
    "products": "product_id",
    "warehouses": "warehouse_id",
    "stock_transactions": "transaction_id",
    "stock_balances": "balance_id",
    "stock_alerts": "alert_id",
    "import_logs": "log_id",
    "quality_assessments": "assessment_id",
    "produce_quality_details": "detail_id",
    "livestock_quality_details": "detail_id",
    "poultry_quality_details": "detail_id",
    "fish_quality_details": "detail_id",
    "integration_sessions": "session_id",
    "integration_error_records": "error_id",
    "integration_reports": "report_id",
    "gateway_principals": "id",
    "gateway_api_keys": "id",
    "gateway_sessions": "id",
    "gateway_request_logs": "id",
    "gateway_audit_logs": "id",
    "gateway_rate_limit_buckets": "id",
    "gateway_events": "id",
    "gateway_webhook_endpoints": "id",
    "gateway_webhook_deliveries": "id",
    "gateway_dead_letters": "id",
    "gateway_tasks": "id",
    "gateway_file_assets": "id",
    "gateway_nonces": "id",
    "gateway_plugins": "id",
}


def normalize_postgres_url(url: str) -> str:
    """Render uses postgres://; SQLAlchemy 2.x expects postgresql://."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def sqlite_table_names(conn: sqlite3.Connection) -> set[str]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return {row[0] for row in cur.fetchall()}


def sqlite_row_count(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM [{table}]")
    return int(cur.fetchone()[0])


def fetch_sqlite_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM [{table}]")
    return [dict(row) for row in cur.fetchall()]


def coerce_row_types(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """Convert SQLite quirks (0/1 booleans) to Python types Postgres expects."""
    table_obj = Base.metadata.tables.get(table)
    if table_obj is None:
        return row

    coerced: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            coerced[key] = None
            continue
        col = table_obj.c.get(key)
        if col is not None and isinstance(col.type, Boolean):
            coerced[key] = bool(value)
        else:
            coerced[key] = value
    return coerced


def postgres_row_count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
        return int(result.scalar_one())


def truncate_tables(engine: Engine, tables: list[str]) -> None:
    existing = set(inspect(engine).get_table_names())
    to_truncate = [t for t in tables if t in existing]
    if not to_truncate:
        return
    quoted = ", ".join(f'"{t}"' for t in to_truncate)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))


def reset_sequences(engine: Engine, tables: list[str]) -> None:
    """Advance Postgres serial sequences to MAX(pk) after explicit ID inserts."""
    with engine.begin() as conn:
        for table in tables:
            pk = PK_COLUMNS.get(table)
            if not pk:
                continue
            conn.execute(
                text(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence(:table_name, :pk_col),
                        COALESCE((SELECT MAX({pk}) FROM "{table}"), 1),
                        true
                    )
                    """
                ),
                {"table_name": table, "pk_col": pk},
            )


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_session_factory: sessionmaker,
    table: str,
    *,
    dry_run: bool,
) -> int:
    rows = fetch_sqlite_rows(sqlite_conn, table)
    if not rows:
        return 0

    if dry_run:
        return len(rows)

    table_obj = Base.metadata.tables[table]
    for offset in range(0, len(rows), BATCH_SIZE):
        batch = [
            coerce_row_types(table, row)
            for row in rows[offset : offset + BATCH_SIZE]
        ]
        with pg_session_factory.begin() as session:
            session.execute(table_obj.insert(), batch)

    return len(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate agriculture_stock.db (SQLite) to Postgres."
    )
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=DEFAULT_SQLITE,
        help=f"Path to SQLite database (default: {DEFAULT_SQLITE})",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres DATABASE_URL (default: DATABASE_URL env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report source/target counts without writing to Postgres",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Truncate target tables before inserting (DESTRUCTIVE on Postgres)",
    )
    parser.add_argument(
        "--include-gateway",
        action="store_true",
        help="Also migrate gateway_* tables (usually skip; prod bootstraps gateway)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Rows per insert batch (default: {BATCH_SIZE})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch_size = max(1, args.batch_size)

    sqlite_path: Path = args.sqlite_path.resolve()
    if not sqlite_path.exists():
        print(f"ERROR: SQLite file not found: {sqlite_path}", file=sys.stderr)
        return 1

    tables = list(BUSINESS_TABLES)
    if args.include_gateway:
        tables.extend(GATEWAY_TABLES)

    sqlite_conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    available = sqlite_table_names(sqlite_conn)
    tables = [t for t in tables if t in available]

    print(f"SQLite source : {sqlite_path}")
    print(f"Tables to copy: {len(tables)}")
    print()

    source_counts: dict[str, int] = {}
    for table in tables:
        count = sqlite_row_count(sqlite_conn, table)
        source_counts[table] = count
        print(f"  {table}: {count:,} rows")

    total_source = sum(source_counts.values())
    print(f"\nTotal source rows: {total_source:,}")

    if args.dry_run:
        db_url = args.database_url or __import__("os").environ.get("DATABASE_URL")
        if db_url:
            db_url = normalize_postgres_url(db_url)
            pg_engine = create_engine(db_url)
            print("\nPostgres target (existing data):")
            for table in tables:
                try:
                    existing = postgres_row_count(pg_engine, table)
                    print(f"  {table}: {existing:,} rows")
                except Exception as exc:  # noqa: BLE001
                    print(f"  {table}: (table missing or unreachable — {exc})")
            pg_engine.dispose()
        else:
            print("\n(dry-run) DATABASE_URL not set — skipping target inspection.")
        print("\nDry-run complete. No data was written.")
        sqlite_conn.close()
        return 0

    db_url = args.database_url or __import__("os").environ.get("DATABASE_URL")
    if not db_url:
        print(
            "\nERROR: DATABASE_URL is required for migration.\n"
            "Set it in the environment or pass --database-url.\n"
            "Get the Internal Database URL from Render Dashboard → agriculture-db-postgres → Connect.",
            file=sys.stderr,
        )
        sqlite_conn.close()
        return 1

    db_url = normalize_postgres_url(db_url)
    pg_engine = create_engine(db_url)
    pg_session_factory = sessionmaker(bind=pg_engine)

    print("\nEnsuring Postgres schema exists...")
    Base.metadata.create_all(bind=pg_engine)

    existing_total = sum(postgres_row_count(pg_engine, t) for t in tables)
    if existing_total > 0 and not args.force:
        print(
            f"\nERROR: Postgres already contains {existing_total:,} rows across "
            f"the selected tables.\n"
            "Re-run with --force to truncate and replace, or migrate to a fresh database.",
            file=sys.stderr,
        )
        sqlite_conn.close()
        pg_engine.dispose()
        return 1

    if args.force and existing_total > 0:
        print("\n--force: truncating target tables...")
        truncate_tables(pg_engine, list(reversed(tables)))

    print("\nMigrating...")
    migrated_total = 0
    # Rebind batch size globally for migrate_table
    global BATCH_SIZE  # noqa: PLW0603
    BATCH_SIZE = batch_size

    for table in tables:
        count = source_counts.get(table, 0)
        if count == 0:
            continue
        print(f"  {table}: inserting {count:,} rows...", end="", flush=True)
        inserted = migrate_table(
            sqlite_conn, pg_session_factory, table, dry_run=False
        )
        migrated_total += inserted
        print(f" done ({inserted:,})")

    print("\nResetting Postgres sequences...")
    reset_sequences(pg_engine, tables)

    print("\nVerification:")
    for table in tables:
        src = source_counts.get(table, 0)
        dst = postgres_row_count(pg_engine, table)
        status = "OK" if src == dst else "MISMATCH"
        print(f"  {table}: source={src:,}  target={dst:,}  [{status}]")

    sqlite_conn.close()
    pg_engine.dispose()

    print(f"\nMigration complete. {migrated_total:,} rows copied.")
    if not args.include_gateway:
        print(
            "Note: gateway tables were skipped. Production will bootstrap gateway "
            "credentials on next app startup."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
