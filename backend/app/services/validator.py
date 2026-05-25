"""
SQL query validator — static analysis before execution.

Why this module exists:
  1. Defense in depth. DuckDB is already in read-only mode (last line of
     defense), but app-level validation gives BETTER UX: clear messages
     and guided retry feedback.
  2. Blocks data-mutating operations (INSERT/UPDATE/DELETE/DROP/ALTER).
  3. Blocks multiple statements in a single query (classic SQL-injection guard).
  4. Auto-adds LIMIT to prevent huge result sets that would freeze the
     frontend or blow up the JSON serialization.

Technical strategy: AST parser via sqlparse.
  Why AST instead of string-matching:
    - No false positives for keywords appearing in column names
      (e.g. a column named "drop_date" does NOT trigger as DROP).
    - No confusion with keywords inside string literals.
    - Reliable detection of the statement type (SELECT vs DDL/DML).
"""

from dataclasses import dataclass

import sqlparse
from sqlparse.tokens import Keyword, DML, DDL


# --- Forbidden operation sets ----------------------------------------------

# Dangerous DML — anything that mutates data.
_FORBIDDEN_DML = {"INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE"}

# All DDL — anything that mutates the schema.
_FORBIDDEN_DDL = {"DROP", "ALTER", "CREATE", "TRUNCATE", "RENAME"}

# Other operations that have no place in a read-only analytical agent.
_FORBIDDEN_OTHER = {"GRANT", "REVOKE", "ATTACH", "DETACH", "COPY", "EXPORT", "IMPORT"}

# Union of all categories — used for the token-level scan.
_FORBIDDEN_ALL = _FORBIDDEN_DML | _FORBIDDEN_DDL | _FORBIDDEN_OTHER


# --- Validation result -----------------------------------------------------

@dataclass
class ValidationResult:
    """
    Validator return type.

    Why a dataclass instead of a tuple or dict:
      - Clear typing with IDE autocomplete.
      - Easy to extend later (e.g. warnings, estimated cost).
    """

    valid: bool          # True if the query passed every check
    reason: str = ""     # Human-readable rejection reason (empty when valid)
    cleaned_sql: str = ""  # Normalized SQL (LIMIT added if needed)


# --- Public API ------------------------------------------------------------

def validate_sql(sql: str, default_limit: int = 100) -> ValidationResult:
    """
    Validate a SQL query and return a normalized version.

    Checks executed (in order):
      1. Query is not empty.
      2. Parses without error.
      3. Exactly ONE statement (no ; separating multiples).
      4. Statement type is SELECT.
      5. No forbidden tokens (DDL, DML, etc.) at any depth.

    If all checks pass, adds LIMIT N when the query has none — protects
    against huge result sets that would freeze the frontend.
    """
    # Strip whitespace and trailing ; — Claude often adds those.
    sql = sql.strip().rstrip(";").strip()

    if not sql:
        return ValidationResult(valid=False, reason="Empty query.")

    # --- Check 1: parse ---
    # sqlparse is tolerant and rarely raises, but we handle it defensively.
    try:
        parsed = sqlparse.parse(sql)
    except Exception as exc:
        return ValidationResult(
            valid=False,
            reason=f"SQL parse error: {exc}",
        )

    # --- Check 2: statement count ---
    # Filter out whitespace-only elements that sqlparse may include between ;
    statements = [s for s in parsed if str(s).strip()]

    if len(statements) == 0:
        return ValidationResult(valid=False, reason="No valid statement found.")

    if len(statements) > 1:
        return ValidationResult(
            valid=False,
            reason=(
                "Multiple statements detected. "
                "Only a single SELECT query is allowed."
            ),
        )

    stmt = statements[0]

    # --- Check 3: statement type ---
    # get_type() returns 'SELECT', 'INSERT', 'UPDATE', 'UNKNOWN', etc.
    # Why check here before scanning tokens: fast reject with a clear message.
    stmt_type = stmt.get_type()
    if stmt_type != "SELECT":
        return ValidationResult(
            valid=False,
            reason=(
                f"Only SELECT queries are allowed. "
                f"Detected type: {stmt_type}."
            ),
        )

    # --- Check 4: forbidden tokens at any depth ---
    # flatten() walks ALL tokens recursively, including subqueries and CTEs.
    # Why this check on top of get_type():
    #   Defense in depth — catches edge cases like malicious CTEs or syntax
    #   that sqlparse classifies as UNKNOWN but still contains DROP/DELETE.
    for token in stmt.flatten():
        if token.ttype in (Keyword, DML, DDL):
            value = token.value.upper()
            if value in _FORBIDDEN_ALL:
                return ValidationResult(
                    valid=False,
                    reason=f"Forbidden operation detected: {value}.",
                )

    # --- All checks passed: normalize by adding LIMIT if needed ---
    cleaned_sql = _ensure_limit(sql, default_limit)

    return ValidationResult(valid=True, cleaned_sql=cleaned_sql)


# --- Internal helpers ------------------------------------------------------

def _ensure_limit(sql: str, default_limit: int) -> str:
    """
    Append LIMIT N to the query if it has no LIMIT clause.

    Uses AST (not string matching) to avoid false positives where 'LIMIT'
    might appear inside string literals or column names.

    Why auto-LIMIT:
      Unbounded queries can return tens of thousands of rows, blow up JSON
      serialization, or freeze the frontend. Better to cap early with a
      sensible default and let the user ask for more if needed.
    """
    parsed = sqlparse.parse(sql)
    if not parsed:
        return sql

    # Look for the LIMIT keyword at any depth in the statement.
    for token in parsed[0].flatten():
        if token.ttype is Keyword and token.value.upper() == "LIMIT":
            return sql  # already has LIMIT — respect what Claude generated

    return f"{sql} LIMIT {default_limit}"
