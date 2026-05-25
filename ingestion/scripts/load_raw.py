"""Upload Olist CSVs to Databricks Unity Catalog as raw Delta tables.

Pipeline per file:
    data/raw/<name>.csv
      -> /Volumes/<catalog>/<raw_schema>/csv_uploads/<name>.csv   (SDK Files API)
      -> <catalog>.<raw_schema>.<name>                            (CREATE OR REPLACE TABLE AS SELECT)

Why this approach:
    Upload-then-CTAS via a Unity Catalog Volume is the modern Databricks
    pattern. It avoids row-by-row INSERTs (the warehouse reads the file
    server-side) and gives us idempotency via OVERWRITE + CREATE OR REPLACE.

Run from repo root:
    dotenv -f .env run -- python ingestion/scripts/load_raw.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from databricks import sql as dbsql
from databricks.sdk import WorkspaceClient

# --- Config: fail-fast if required env vars are missing ---
# Strip "https://" so the SDK host param accepts either form in .env.
HOST = os.environ["DATABRICKS_HOST"].replace("https://", "")
TOKEN = os.environ["DATABRICKS_TOKEN"]
HTTP_PATH = os.environ["DATABRICKS_HTTP_PATH"]

# `workspace` is the default catalog on Databricks Free Edition.
CATALOG = os.environ.get("DATABRICKS_CATALOG", "workspace")
RAW_SCHEMA = os.environ.get("DBT_SCHEMA_RAW", "olist_raw")

# Volume that stores the uploaded CSVs inside Unity Catalog.
VOLUME_NAME = "csv_uploads"

# Local source folder produced by download_olist.py.
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

# The Olist Kaggle dump has a fixed set of CSV file names. Each becomes a
# raw table with the same name minus the .csv suffix.
EXPECTED_FILES: list[str] = [
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
]


def fq(*parts: str) -> str:
    """Build a fully-qualified Unity Catalog name (catalog.schema.object)."""
    return ".".join(parts)


def volume_path(filename: str) -> str:
    """Absolute path inside the UC managed volume for a given local file."""
    return f"/Volumes/{CATALOG}/{RAW_SCHEMA}/{VOLUME_NAME}/{filename}"


def ensure_schema_and_volume(cursor) -> None:
    """Create the raw schema and the upload volume if they don't exist.

    Both DDLs are idempotent so the script is safe to rerun on a fresh
    workspace or after a partial failure.
    """
    cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {fq(CATALOG, RAW_SCHEMA)}")
    cursor.execute(
        f"CREATE VOLUME IF NOT EXISTS {fq(CATALOG, RAW_SCHEMA, VOLUME_NAME)}"
    )


def upload_csv(w: WorkspaceClient, local_path: Path) -> str:
    """Upload one CSV to the UC volume, overwriting any prior copy."""
    target = volume_path(local_path.name)
    with local_path.open("rb") as f:
        # overwrite=True keeps the script idempotent across reruns.
        w.files.upload(target, f, overwrite=True)
    return target


def create_table_from_volume(cursor, table_name: str, volume_csv: str) -> None:
    """Run CTAS that materializes the CSV as a Delta table.

    read_files() is Databricks' table-valued function for ingesting files;
    it infers the schema from the CSV header and the warehouse writes the
    resulting Delta table without round-tripping data through this client.
    """
    table_fqn = fq(CATALOG, RAW_SCHEMA, table_name)
    cursor.execute(
        f"""
        CREATE OR REPLACE TABLE {table_fqn}
        AS SELECT *
        FROM read_files(
            '{volume_csv}',
            format => 'csv',
            header => true,
            inferSchema => true
        )
        """
    )


def main() -> int:
    if not RAW_DIR.exists() or not any(RAW_DIR.glob("*.csv")):
        print(
            f"Raw folder is empty or missing: {RAW_DIR}\n"
            "Run `python ingestion/scripts/download_olist.py` first.",
            file=sys.stderr,
        )
        return 1

    missing = [f for f in EXPECTED_FILES if not (RAW_DIR / f).exists()]
    if missing:
        print(
            f"Missing expected Olist files in {RAW_DIR}:\n  - "
            + "\n  - ".join(missing),
            file=sys.stderr,
        )
        return 1

    # SDK client used only for the Files API (volume upload).
    w = WorkspaceClient(host=f"https://{HOST}", token=TOKEN)

    # Single SQL connection reused for all DDL/CTAS — avoids paying the
    # warehouse cold-start penalty on every statement.
    with dbsql.connect(
        server_hostname=HOST, http_path=HTTP_PATH, access_token=TOKEN
    ) as conn:
        with conn.cursor() as cursor:
            ensure_schema_and_volume(cursor)
            print(f"[OK] schema + volume ready: {fq(CATALOG, RAW_SCHEMA, VOLUME_NAME)}")

            for filename in EXPECTED_FILES:
                local = RAW_DIR / filename
                # Strip the .csv suffix to produce the table name.
                table = filename[:-4]

                vpath = upload_csv(w, local)
                print(f"  uploaded  -> {vpath}")

                create_table_from_volume(cursor, table, vpath)
                print(f"  created   -> {fq(CATALOG, RAW_SCHEMA, table)}")

    print(f"\n[DONE] {len(EXPECTED_FILES)} raw tables loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
