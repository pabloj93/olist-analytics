"""
Evaluation harness for the chatbot backend.

Loads NL questions + expected criteria from questions.yaml, calls the
backend's sync /chat endpoint for each one, evaluates the response
against the criteria, and writes a timestamped JSON report under
eval/results/.

Run (from repo root, with the backend up on :8000):

    dotenv -f .env run -- python eval/run_eval.py

Exit code is 0 if pass_rate >= TARGET, 1 otherwise — usable in CI.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml

# --- Config ----------------------------------------------------------------

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
QUESTIONS_FILE = EVAL_DIR / "questions.yaml"

# Backend URL — sync /chat returns the full result in one shot, which is
# what the harness needs (no SSE parsing).
BACKEND_URL = "http://127.0.0.1:8000/chat"

# Per-request timeout. Warehouse cold-start can take ~60s on Databricks
# Free Edition, so generous but bounded.
REQUEST_TIMEOUT_SECONDS = 300

# Pass-rate threshold for the harness to exit 0.
TARGET_PASS_RATE = 0.80


# --- I/O -------------------------------------------------------------------


def load_questions() -> list[dict]:
    """Load the question bank from YAML."""
    with QUESTIONS_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def call_chat(question: str) -> dict:
    """POST the question to the sync /chat endpoint and return the JSON body."""
    r = requests.post(
        BACKEND_URL,
        json={"messages": [{"role": "user", "content": question}]},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()


# --- Evaluation ------------------------------------------------------------


def _matches(actual: Any, expected: Any) -> bool:
    """
    Compare a single column value to its expected target.

    Strings are matched case-insensitively after trim. Other types use
    plain equality. None on either side never matches anything.
    """
    if actual is None or expected is None:
        return actual == expected
    if isinstance(expected, str):
        return str(actual).strip().lower() == expected.strip().lower()
    return actual == expected


def evaluate(expects: dict, response: dict) -> tuple[bool, list[str]]:
    """
    Return (passed, reasons). Empty reasons list = passed.

    Every supported criterion is checked even when an earlier one fails,
    so the JSON report surfaces ALL issues per question — not just the
    first one.
    """
    reasons: list[str] = []

    sql = (response.get("sql") or "").lower()
    result = response.get("result") or []
    columns = response.get("columns") or []
    attempts = response.get("attempts", 99)

    # --- SQL substring checks ---
    for sub in expects.get("sql_contains") or []:
        if sub.lower() not in sql:
            reasons.append(f"SQL missing substring '{sub}'")

    # --- Required tables ---
    for table in expects.get("must_query") or []:
        if table.lower() not in sql:
            reasons.append(f"SQL does not reference table '{table}'")

    # --- Row count bounds ---
    n_rows = len(result)
    min_rows = expects.get("min_rows")
    if min_rows is not None and n_rows < min_rows:
        reasons.append(f"got {n_rows} rows, expected >= {min_rows}")
    max_rows = expects.get("max_rows")
    if max_rows is not None and n_rows > max_rows:
        reasons.append(f"got {n_rows} rows, expected <= {max_rows}")

    # --- Required columns ---
    for col in expects.get("must_have_columns") or []:
        if col not in columns:
            reasons.append(f"missing column '{col}' in result")

    # --- First-row value assertions ---
    top_row = expects.get("top_row")
    if top_row:
        if not result:
            reasons.append("top_row check requested but result is empty")
        else:
            first = result[0]
            for col, expected_val in top_row.items():
                if not _matches(first.get(col), expected_val):
                    reasons.append(
                        f"top row {col}={first.get(col)!r}, expected {expected_val!r}"
                    )

    # --- LLM retries ---
    # Default 2 aligns with the agent's MAX_RETRIES setting (services/agent.py).
    # The agent is allowed to self-correct once; if it does, the user got a
    # correct answer and the question should still pass. Per-question override
    # to 1 if you want a stricter "no retries" bar.
    attempts_max = expects.get("attempts_max", 2)
    if attempts > attempts_max:
        reasons.append(f"took {attempts} attempts, max allowed {attempts_max}")

    return (len(reasons) == 0, reasons)


# --- Main ------------------------------------------------------------------


def main() -> int:
    questions = load_questions()
    if not questions:
        print("No questions found in questions.yaml", file=sys.stderr)
        return 2

    print(
        f"Running eval over {len(questions)} questions against {BACKEND_URL}\n",
        flush=True,
    )

    started_at = datetime.utcnow().isoformat()
    results: list[dict] = []
    pass_count = 0

    for q in questions:
        qid = q["id"]
        question = q["question"]
        # Truncate long questions in the live log so the table stays readable.
        print(
            f"  [{qid:<32}] {question[:60]}{'...' if len(question) > 60 else ''}",
            flush=True,
        )

        t0 = time.perf_counter()
        try:
            response = call_chat(question)
            error = None
        except Exception as exc:
            response = {}
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - t0

        if error:
            passed, reasons = False, [f"request error: {error}"]
        else:
            passed, reasons = evaluate(q["expects"], response)

        if passed:
            pass_count += 1
            verdict = "PASS"
        else:
            verdict = "FAIL"
        # First reason inline for quick scanning; full list in the JSON.
        tail = f"  -> {reasons[0]}" if reasons else ""
        print(f"     {verdict}  ({elapsed:>5.1f}s){tail}", flush=True)

        results.append(
            {
                "id": qid,
                "question": question,
                "passed": passed,
                "reasons": reasons,
                "elapsed_seconds": round(elapsed, 2),
                "sql": response.get("sql", ""),
                "n_rows": len(response.get("result") or []),
                "attempts": response.get("attempts"),
                "trace_id": response.get("trace_id", ""),
            }
        )

    pass_rate = pass_count / len(questions)
    summary = {
        "started_at": started_at,
        "finished_at": datetime.utcnow().isoformat(),
        "total": len(questions),
        "passed": pass_count,
        "failed": len(questions) - pass_count,
        "pass_rate": round(pass_rate, 3),
        "target": TARGET_PASS_RATE,
        "results": results,
    }

    # Save timestamped JSON. UTC + ISO8601-ish so files sort chronologically.
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(
        f"Pass rate: {pass_count}/{len(questions)} = {pass_rate:.1%}  "
        f"(target {TARGET_PASS_RATE:.0%})"
    )
    print(f"Saved: {out_path}")

    return 0 if pass_rate >= TARGET_PASS_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
