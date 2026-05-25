"""
Database service — Databricks SQL warehouse + Olist dbt marts.

Responsibilities:
  1. Open a connection to the SQL warehouse on first use (singleton).
  2. Expose get_schema()  -> formatted schema string for the LLM prompt.
  3. Expose run_query()   -> DataFrame with the query results.

Why singleton:
  databricks-sql-connector keeps an HTTP session + Thrift transport open
  per Connection. Reusing one connection across all requests avoids
  paying the TLS + auth handshake on every chat turn.

The schema returned by get_schema() is restricted to the dbt marts schema
(fact, dims, RFM mart) — staging and intermediate models are intentionally
hidden so the LLM cannot accidentally query raw or partial data.
"""

from typing import Optional

import pandas as pd
from databricks import sql as dbsql
from databricks.sql.client import Connection

from app.config import settings


# --- Connection singleton --------------------------------------------------

_conn: Optional[Connection] = None


def _init_connection() -> Connection:
    """
    Open the Databricks SQL warehouse connection.

    The host is stripped of any "https://" prefix so the connector accepts
    either form in .env (it requires the bare hostname).
    """
    hostname = (
        settings.databricks_host.replace("https://", "").replace("http://", "")
    )

    conn = dbsql.connect(
        server_hostname=hostname,
        http_path=settings.databricks_http_path,
        access_token=settings.databricks_token,
    )

    # Confirm we can reach the warehouse and that the chatbot schema is
    # accessible. Failing fast here gives a clearer error than waiting for
    # the first user query to blow up inside the agent.
    with conn.cursor() as cur:
        cur.execute(
            f"SHOW TABLES IN {settings.databricks_catalog}."
            f"{settings.databricks_chatbot_schema}"
        )
        tables = [r[1] for r in cur.fetchall()]
    print(
        f"[database] connected to {hostname}, "
        f"{settings.databricks_catalog}.{settings.databricks_chatbot_schema} "
        f"({len(tables)} tables visible)"
    )
    return conn


def get_connection() -> Connection:
    """
    Return the warehouse connection, initializing it on first call.

    Lazy init so the app can boot before the warehouse is awake — the
    first chat turn then takes the warehouse wake-up hit (~30-60s on
    Databricks Free Edition serverless), subsequent turns are fast.
    """
    global _conn
    if _conn is None:
        _conn = _init_connection()
    return _conn


# --- Schema introspection --------------------------------------------------

# The LLM is only allowed to "see" these mart tables. Restricting visibility
# keeps prompts smaller and prevents the agent from joining staging /
# intermediate tables that were never intended as a public contract.
_MART_TABLES = [
    "fct_orders",        # order-grain fact (1 row per order)
    "fct_order_items",   # item-grain fact (1 row per line item) — seller/product/category questions live here
    "dim_customer",
    "dim_product",
    "dim_seller",
    "dim_date",
    "mart_customer_rfm",
]


def get_schema() -> str:
    """
    Return the curated marts schema as a formatted string for the LLM prompt.

    Output format (one line per table, columns comma-separated):
        - fct_orders: order_id (STRING), customer_id (STRING), ...
        - dim_customer: customer_id (STRING), ...

    We pull from INFORMATION_SCHEMA.COLUMNS filtered to our marts schema
    and the allow-listed tables. Ordering by ORDINAL_POSITION preserves
    the original column order, which is more intuitive to read.
    """
    conn = get_connection()

    in_clause = ", ".join(f"'{t}'" for t in _MART_TABLES)
    query = f"""
        SELECT table_name, column_name, data_type
        FROM {settings.databricks_catalog}.information_schema.columns
        WHERE table_schema = '{settings.databricks_chatbot_schema}'
          AND table_name IN ({in_clause})
        ORDER BY table_name, ordinal_position
    """

    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()

    # Group columns by table so we can format one line per table.
    schema: dict[str, list[str]] = {}
    for table_name, col_name, data_type in rows:
        schema.setdefault(table_name, []).append(f"{col_name} ({data_type})")

    # Build the final string: one line per table, columns separated by commas.
    lines = [
        f"- {table}: {', '.join(cols)}" for table, cols in sorted(schema.items())
    ]
    return "\n".join(lines)


# --- Query execution -------------------------------------------------------


def run_query(sql: str) -> pd.DataFrame:
    """
    Execute a SQL query against the warehouse and return a DataFrame.

    We instruct the LLM to use fully-qualified `<catalog>.<schema>.<table>`
    names, so the connection has no default schema set — that lets us catch
    missing qualifiers early instead of silently resolving them.

    Raises:
        databricks.sql.exc.* if the SQL is invalid or the query fails.
        The caller (agent.py) catches and feeds the message back to the
        LLM for the retry step.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql)
        # `description` is a list of column metadata tuples (name, type, ...).
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=columns)
