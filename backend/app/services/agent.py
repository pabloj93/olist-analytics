"""
Agent pipeline — LangGraph state machine for the NL -> SQL -> Chart -> Answer cycle.

Why LangGraph instead of a plain LCEL chain:
  - Retry with error feedback becomes an explicit conditional edge in the
    graph (not an external Python loop wrapping the chain).
  - Intent routing (new query vs chart-only re-render) is a clean fork
    at the entry of the graph.
  - Each node is an isolated span in LangFuse: easy to debug and measure.
  - Multi-model: swapping the LLM means editing ONE line in a single node.
  - Native streaming via astream_events — captures node events AND LLM
    tokens in a unified stream, no manual orchestration code.

Graph flow:

         START
           |
           v
   +-----------------+
   |  route_intent   |  <- detects "show as pie chart" requests
   +-----------------+
           |
           +--> chart_only? --------------+
           | new_query                    |
           v                              |
   +-----------------+                    |
   |  generate_sql   | <----+             |
   +-----------------+      |             |
           |                |             |
           v                | (retry on   |
   +-----------------+      |  validation |
   |  validate_sql   |      |  or execute |
   +-----------------+      |  error)     |
           |                |             |
           +--> invalid? ---+             |
           | valid                        |
           v                              |
   +-----------------+                    |
   |   execute_sql   |                    |
   +-----------------+                    |
           |                              |
           +--> execution error? ---------+
           | success (or out of retries)  |
           v                              |
   +-----------------+   <----------------+ (chart_only path joins here)
   |    visualize    |  <- Plotly HTML chart
   +-----------------+
           |
           v
   +-----------------+
   |     respond     |  <- streams response tokens via SSE
   +-----------------+
           |
           v
          END
"""

from typing import TypedDict

import pandas as pd
from langgraph.graph import StateGraph, END, START
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    BaseMessage,
)

from app.config import settings
from app.services.database import get_schema, run_query
from app.services.validator import validate_sql
from app.services.visualizer import (
    render_chart,
    parse_chart_request,
    is_pure_chart_request,
)


# --- Shared state schema ---------------------------------------------------

class AgentState(TypedDict):
    """
    State shared across every node in the graph.

    LangGraph performs an automatic shallow merge: each node returns a
    partial dict, and the returned fields overwrite the previous values
    in the global state.

    Why TypedDict instead of a Pydantic BaseModel:
      LangGraph is optimized for TypedDict — zero validation overhead on
      every node transition. Pydantic validation would be expensive in a
      long graph with many hops.
    """

    # --- User input ---
    messages: list[BaseMessage]   # Full conversation history (last item = new question)

    # --- generate_sql output ---
    sql: str                      # SQL query produced by Claude

    # --- execute_sql output ---
    result: list[dict]            # Result rows in JSON-friendly format
    columns: list[str]            # Column names of the result
    error: str                    # Error message from DuckDB (empty = success)

    # --- Retry control ---
    attempts: int                 # Number of SQL generation attempts so far

    # --- Visualization ---
    chart_type: str               # "auto" by default; or "bar", "line", "pie", "scatter", "table"
    chart_spec: dict              # Plotly figure JSON: {data, layout} — consumed by react-plotly.js

    # --- Intent routing ---
    # Set by route_intent_node. True means: skip SQL pipeline and just
    # re-render the existing result with a new chart_type. Requires the
    # frontend to have included the previous result/columns in the request.
    is_chart_only: bool

    # --- Final output ---
    answer: str                   # Natural-language response


# --- LLM model (singleton) -------------------------------------------------

# Why singleton: ChatAnthropic keeps a reusable HTTP client internally.
# Creating a new instance per request would waste the connection pool.
# streaming=True is REQUIRED so astream_events can capture per-token events.
_llm = ChatAnthropic(
    model=settings.claude_model,
    api_key=settings.anthropic_api_key,
    max_tokens=2048,
    streaming=True,
)


# --- Prompt templates ------------------------------------------------------

# System prompt for the generate_sql node.
# {schema}, {catalog}, {db_schema} are replaced at runtime.
# Note: we instruct the LLM to reply in the user's language so the same
# code base serves both Portuguese-speaking analysts and English recruiters.
_SQL_SYSTEM_TEMPLATE = """You are a SQL expert generating queries for the Olist Brazilian E-Commerce dbt marts (orders, customers, sellers, products, reviews).

MARTS SCHEMA (Unity Catalog: {catalog}.{db_schema}):
{schema}

MANDATORY RULES:
- Reply with PURE SQL only. No markdown, no ```sql fences, no explanations.
- Use exactly the table and column names shown in the schema above.
- Dialect: Databricks SQL (Spark SQL on Delta Lake). Supported features
  include window functions, CTEs, INTERVAL arithmetic on TIMESTAMPs,
  date_format() / date_trunc(), unix_timestamp(), ntile() over (...).
- ALWAYS fully-qualify tables as `{catalog}.{db_schema}.<table>` — the
  warehouse has no default schema set.
- Add LIMIT 100 if the query could return many rows.
- Use JOINs when you need to combine tables.
- Two fact tables are available — pick by question grain:
    * fct_orders         (1 row per ORDER)  — use for order-level metrics:
                          delivery lead times, on-time flag, payment funnel,
                          customer-level aggregations.
                          Has total_revenue (item price + freight pre-summed)
                          and pivoted payment_<method>_value columns.
    * fct_order_items    (1 row per LINE ITEM, ~113k rows) — use for any
                          seller, product, or category question. Already
                          carries seller_state, customer_state, product
                          category_en, item_revenue. NO further joins needed.
- For customer-level (person) analysis, group by customer_unique_id
  (carried as a degenerate dimension on both facts). Skip orders with
  order_status IN ('canceled', 'unavailable') unless the user asks otherwise."""

# Appended to the system prompt when retrying after a previous error.
# Why we show the previous query: Claude needs to see what it tried so it
# can understand the error in the right context.
_RETRY_HINT = """

ATTENTION: your previous attempt produced this error:
{error}

Previous query:
{previous_sql}

Fix the issue and produce a new SQL query."""

# System prompt for the respond node.
# Receives the executed SQL + the result + row count for analysis.
#
# Notice the explicit ban on ASCII art: Claude likes to be "helpful" by drawing
# text-based charts in markdown. A real interactive chart is already rendered
# on the page, so the ASCII version is pure visual noise.
_RESPOND_SYSTEM_TEMPLATE = """You are a data analyst answering a question about the Olist Brazilian E-Commerce marketplace (orders, customers, sellers, products, reviews).

EXECUTED SQL:
{sql}

RESULT ({n_rows} rows, columns: {columns}):
{result_preview}

OUTPUT RULES:
- Respond in the SAME language as the user's question.
- Be clear and concise. Focus on the insight, not the mechanics.
- Do NOT repeat the SQL in your answer.
- Do NOT draw ASCII art, text-based charts, or pseudo-graphics — a real
  interactive Plotly chart is rendered separately on the page.
- Markdown tables are fine for small summaries (<= 10 rows). For larger
  datasets, summarize trends in prose instead of pasting the whole table."""


# --- Graph nodes -----------------------------------------------------------

def route_intent_node(state: AgentState) -> dict:
    """
    Node 0 — Decide whether to run a new SQL query or just re-render the chart.

    Reads from state: messages (looks at the LAST user message), result (presence)
    Writes to state: chart_type, is_chart_only

    Why this exists:
      The PRD requires the user to be able to say "show as pie chart" and have
      the agent re-render the previous result with a new chart type — without
      running SQL again (saves latency and tokens).

    How it decides:
      1. Parse the user message for a chart-type keyword ("pie", "bar", etc.).
      2. Check if previous data is in the initial state (frontend includes
         it as state.result/columns when the user has seen a prior answer).
      3. Check if the message is SHORT and has no question words (i.e. it is
         a pure style change, not a new question with chart preference).
      4. Combine: only skip SQL when all three conditions hold.
    """
    # Get the last user message (the new question / instruction).
    last_message = ""
    if state["messages"]:
        last = state["messages"][-1]
        # Defensive: works for both BaseMessage and a plain str content.
        last_message = getattr(last, "content", str(last))

    # Parse the message for an explicit chart-type request.
    requested_chart = parse_chart_request(last_message)

    # Previous data is in state when the frontend forwarded it from a prior turn.
    has_previous_data = bool(state.get("result"))

    # Chart-only flow needs all three: keyword, previous data, short message.
    is_chart_only = bool(
        requested_chart
        and has_previous_data
        and is_pure_chart_request(last_message)
    )

    return {
        # Default "auto" lets the heuristic in visualize pick later.
        "chart_type": requested_chart or "auto",
        "is_chart_only": is_chart_only,
    }


def generate_sql_node(state: AgentState) -> dict:
    """
    Node 1 — Generate SQL from the user question + history + retry error (if any).

    Reads from state: messages, error (optional), sql (previous, for the retry hint)
    Writes to state: sql, attempts (+1), error (cleared for the next pass)

    Why separate generation from execution into distinct nodes:
      Each node has a single responsibility. Generate only talks to Claude,
      Execute only talks to DuckDB. This makes the code easy to test, debug,
      and swap (e.g. plug a different LLM or a different database).
    """
    schema = get_schema()

    # Build the system prompt with the current database schema + catalog/schema
    # so the LLM can fully-qualify every table it generates.
    system_text = _SQL_SYSTEM_TEMPLATE.format(
        schema=schema,
        catalog=settings.databricks_catalog,
        db_schema=settings.databricks_chatbot_schema,
    )

    # If we have an error from a previous attempt, append the retry hint
    # so Claude knows what to fix.
    if state.get("error"):
        system_text += _RETRY_HINT.format(
            error=state["error"],
            previous_sql=state.get("sql", ""),
        )

    # System prompt + full conversation history (last message is the question).
    messages = [SystemMessage(content=system_text)] + state["messages"]

    # Call Claude. streaming=True on _llm lets astream_events capture tokens,
    # but here we use .invoke() because we need the full SQL before continuing.
    response = _llm.invoke(messages)
    sql = response.content.strip()

    # Defense against Claude ignoring the rule and returning markdown anyway.
    # Strip ```sql ... ``` fences if present.
    if sql.startswith("```"):
        # Drop the first and last lines (the fences) and keep the inner SQL.
        lines = sql.split("\n")
        sql = "\n".join(lines[1:-1]).strip()

    return {
        "sql": sql,
        "attempts": state.get("attempts", 0) + 1,
        "error": "",  # Clear the error before validating the new query
    }


def validate_sql_node(state: AgentState) -> dict:
    """
    Node 2 — Validate the generated SQL before execution.

    Reads from state: sql
    Writes to state: sql (normalized with LIMIT), error (if invalid)

    Why validate as a separate node (rather than inside generate_sql):
      - Single Responsibility: every node does one thing.
      - Isolated span in LangFuse — we can see how long validation takes.
      - Lets the conditional edge after validate_sql decide retry using the
        exact same error pattern used by execute_sql.
    """
    result = validate_sql(state["sql"])

    if not result.valid:
        # Validation error lives in the same `error` field as execution errors,
        # so the conditional edge can treat both uniformly.
        return {"error": f"Validation failed: {result.reason}"}

    # Validation passed — update sql with the normalized version (LIMIT added
    # if missing). Clear any error left over from a previous attempt.
    return {"sql": result.cleaned_sql, "error": ""}


def execute_sql_node(state: AgentState) -> dict:
    """
    Node 3 — Execute the SQL against DuckDB and capture any error.

    Reads from state: sql
    Writes to state: result, columns, error

    Why we catch exceptions here (instead of letting them propagate):
      The graph needs to DECIDE whether to retry or give up based on the
      error. If the exception bubbled up, the graph would crash with no
      chance to retry.
    """
    try:
        # run_query returns a DataFrame; we serialize it to JSON-friendly dicts.
        df = run_query(state["sql"])
        return {
            "result": df.to_dict(orient="records"),
            "columns": list(df.columns),
            "error": "",
        }
    except Exception as exc:
        # Capture the error message as a string so Claude can read it on retry.
        return {
            "result": [],
            "columns": [],
            "error": str(exc),
        }


def visualize_node(state: AgentState) -> dict:
    """
    Node 4 — Render the current result as a Plotly figure spec (JSON).

    Reads from state: result, columns, chart_type
    Writes to state: chart_spec

    This node runs in BOTH flows:
      - new query path: visualizes the freshly executed result.
      - chart-only path: visualizes the previous result with a new type.

    Why JSON spec (and not HTML): the React frontend mounts the chart with
    react-plotly.js, which needs the figure as a {data, layout} dict. Going
    JSON also avoids the "wrong initial width" bug HTML embedding had.
    """
    # No data to chart — leave chart_spec empty (the frontend treats it as a no-op).
    if not state.get("result"):
        return {"chart_spec": {}}

    # Build a DataFrame from the JSON-friendly rows + columns in state.
    # Why pandas: Plotly expects a DataFrame and our render_chart helper
    # uses pandas API for shape detection (date columns, dtypes, etc.).
    df = pd.DataFrame(state["result"], columns=state.get("columns") or None)

    # render_chart handles "auto" via heuristics, or honors the explicit type.
    chart_type = state.get("chart_type") or "auto"

    # Why we catch every exception here: rendering can fail on edge-case data
    # shapes (mixed types in wide-form, unsupported column dtypes, etc.). We
    # would rather degrade gracefully — return an empty chart — than abort
    # the entire request and show the user a "network error".
    try:
        spec = render_chart(df, chart_type)
    except Exception as exc:
        print(f"[visualize] chart generation failed ({type(exc).__name__}): {exc}")
        spec = {}

    return {"chart_spec": spec}


def respond_node(state: AgentState) -> dict:
    """
    Node 5 — Generate the natural-language answer from the query result.

    Reads from state: messages, sql, result, columns, error
    Writes to state: answer

    This is the most token-heavy node — the response is free-form and can be long.
    Streaming ensures the user sees the first tokens in ~500ms even if the full
    response takes a few seconds.
    """
    # Chart-only flow: the user did not ask a new question, just for a
    # different chart type. Short acknowledgement is better than re-narrating
    # the same data — we save tokens and the user sees the new chart faster.
    if state.get("is_chart_only"):
        return {
            "answer": (
                f"Here is the same data displayed as a {state['chart_type']} chart."
            )
        }

    # Special case: we reached this node with an error -> we ran out of retries.
    # Respond explaining what happened instead of pretending things worked.
    if state.get("error") and not state.get("result"):
        return {
            "answer": (
                f"I could not produce a valid SQL query after {state['attempts']} "
                f"attempts. Last error: {state['error']}. "
                "Could you rephrase the question?"
            )
        }

    # Show up to 20 rows so we do not blow Claude's context window.
    # 20 rows are usually enough for the LLM to see the pattern.
    result = state["result"]
    preview_rows = result[:20]
    preview = "\n".join(str(row) for row in preview_rows)
    if len(result) > 20:
        preview += f"\n... ({len(result) - 20} more rows omitted)"

    system_text = _RESPOND_SYSTEM_TEMPLATE.format(
        sql=state["sql"],
        n_rows=len(result),
        columns=", ".join(state["columns"]),
        result_preview=preview,
    )

    # Same pattern: system prompt + full user history.
    messages = [SystemMessage(content=system_text)] + state["messages"]
    response = _llm.invoke(messages)

    return {"answer": response.content}


# --- Conditional edges (routing decisions) ---------------------------------

def after_intent(state: AgentState) -> str:
    """
    Decide the next node after route_intent.

    Returns:
      "visualize"     -> chart-only request, skip SQL pipeline entirely.
      "generate_sql"  -> normal flow, run a new SQL query.
    """
    return "visualize" if state.get("is_chart_only") else "generate_sql"


def after_validate(state: AgentState) -> str:
    """
    Decide the next node after validate_sql.

    Returns:
      "execute_sql"   -> SQL is valid, ready to execute
      "generate_sql"  -> SQL is invalid AND we still have retries (loop back)
      "respond"        -> SQL is invalid AND we are out of retries (give up)
    """
    if not state.get("error"):
        return "execute_sql"
    if state["attempts"] < settings.max_retries:
        return "generate_sql"
    return "respond"


def after_execute(state: AgentState) -> str:
    """
    Decide the next node after execute_sql.

    Returns:
      "visualize"     -> execution succeeded, render the chart next
      "generate_sql"  -> execution error AND we still have retries (loop back)
      "respond"        -> execution error AND we are out of retries (give up)
    """
    if not state.get("error"):
        return "visualize"
    if state["attempts"] < settings.max_retries:
        return "generate_sql"
    return "respond"


# --- Graph build and compile -----------------------------------------------

def _build_graph():
    """
    Build the graph, register nodes and edges, and compile it.

    .compile() turns the declarative definition into a LangChain Runnable —
    the same interface used by every other LangChain component (chains,
    agents, tools).
    """
    graph = StateGraph(AgentState)

    # Register each node by name (string used as the label on edges).
    graph.add_node("route_intent", route_intent_node)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("execute_sql", execute_sql_node)
    graph.add_node("visualize", visualize_node)
    graph.add_node("respond", respond_node)

    # Entry edge: every request starts by deciding the intent.
    graph.add_edge(START, "route_intent")

    # Conditional edge after route_intent: chart-only path or full SQL path.
    graph.add_conditional_edges(
        "route_intent",
        after_intent,
        {
            "visualize": "visualize",
            "generate_sql": "generate_sql",
        },
    )

    # Static edge: generate_sql always flows to validate_sql.
    graph.add_edge("generate_sql", "validate_sql")

    # Conditional edge after validate: execute_sql (valid), generate_sql (retry), or respond (give up).
    graph.add_conditional_edges(
        "validate_sql",
        after_validate,
        {
            "execute_sql": "execute_sql",
            "generate_sql": "generate_sql",
            "respond": "respond",
        },
    )

    # Conditional edge after execute: visualize (success), generate_sql (retry), or respond (give up).
    graph.add_conditional_edges(
        "execute_sql",
        after_execute,
        {
            "visualize": "visualize",
            "generate_sql": "generate_sql",
            "respond": "respond",
        },
    )

    # Static edge: visualize always flows to respond next.
    graph.add_edge("visualize", "respond")

    # respond is the final node: it flows directly to END.
    graph.add_edge("respond", END)

    return graph.compile()


# Compiled singleton — built once on the first import of this module.
_compiled_graph = _build_graph()


# --- Public API ------------------------------------------------------------

def _build_initial_state(
    messages: list[BaseMessage],
    previous_sql: str = "",
    previous_result: list[dict] | None = None,
    previous_columns: list[str] | None = None,
) -> AgentState:
    """
    Construct the initial AgentState passed to the graph on every invocation.

    Why this helper: run_agent and stream_agent share the same boilerplate.
    Keeping it in one place ensures both code paths start from the same
    shape and avoids subtle bugs from forgetting a field.

    The previous_* fields come from the frontend when the user sees a chart
    and then asks for a different chart type — route_intent_node uses them
    to skip the SQL pipeline and re-render the existing data.
    """
    return {
        "messages": messages,
        "sql": previous_sql,
        "result": previous_result or [],
        "columns": previous_columns or [],
        "error": "",
        "attempts": 0,
        "chart_type": "auto",
        "chart_spec": {},
        "is_chart_only": False,
        "answer": "",
    }


def run_agent(
    messages: list[BaseMessage],
    previous_sql: str = "",
    previous_result: list[dict] | None = None,
    previous_columns: list[str] | None = None,
    callbacks: list | None = None,
) -> AgentState:
    """
    Execute the graph synchronously — used by the eval harness and by the
    non-streaming /chat endpoint.

    Returns the full final state: sql, result, columns, chart_html, answer.

    The previous_* arguments enable the "chart re-render" flow described
    in the PRD — the frontend passes back the prior result so the agent
    can switch chart type without re-running SQL.

    The `callbacks` list is forwarded to LangChain via the RunnableConfig.
    Typically contains the LangFuse handler returned by tracing.new_trace().
    Empty list = no observability, app still works.
    """
    initial_state = _build_initial_state(
        messages, previous_sql, previous_result, previous_columns
    )
    # config={"callbacks": [...]} is LangChain's standard way to hook into
    # every step of the graph (LangFuse handler, custom loggers, etc.).
    config = {"callbacks": callbacks or []}
    return _compiled_graph.invoke(initial_state, config=config)


async def stream_agent(
    messages: list[BaseMessage],
    previous_sql: str = "",
    previous_result: list[dict] | None = None,
    previous_columns: list[str] | None = None,
    callbacks: list | None = None,
):
    """
    Execute the graph asynchronously and yield events for SSE delivery.

    Each yield is a dict {type, data} that the /chat/stream router turns
    into a Server-Sent Event for the frontend.

    Event types emitted:
      - sql:    after validate_sql succeeds (the normalized query)
      - table:  after execute_sql succeeds (rows + columns)
      - chart:  after visualize finishes (Plotly HTML snippet)
      - token:  every chunk of the final response (from respond_node)
      - done:   at the end of the graph

    Why astream_events instead of astream:
      astream only yields state snapshots between nodes. astream_events
      also yields real-time LLM token chunks, which is essential for the
      typewriter chat UX.

    The `callbacks` list (typically the LangFuse handler) is forwarded so the
    streaming run shows up as a trace in the dashboard exactly like sync runs.
    """
    initial_state = _build_initial_state(
        messages, previous_sql, previous_result, previous_columns
    )
    # Same config shape as run_agent — passes the callback handler down to
    # every LLM call and every node automatically.
    config = {"callbacks": callbacks or []}

    # version="v2" is the modern, stable event API for LangChain/LangGraph.
    async for event in _compiled_graph.astream_events(initial_state, version="v2", config=config):
        kind = event["event"]
        name = event["name"]

        # --- End of a node: emit a snapshot of the output ---
        if kind == "on_chain_end":
            output = event["data"].get("output") or {}

            # Why we emit sql HERE (after validate) and not after generate_sql:
            # the user only sees the VALIDATED, normalized SQL (with LIMIT).
            # Invalid attempts that triggered a retry stay invisible — better
            # UX, no noise from SQLs that never even reached the database.
            if name == "validate_sql" and not output.get("error") and output.get("sql"):
                yield {"type": "sql", "data": {"query": output["sql"]}}

            elif name == "execute_sql" and not output.get("error"):
                yield {
                    "type": "table",
                    "data": {
                        "rows": output.get("result", []),
                        "columns": output.get("columns", []),
                    },
                }

            elif name == "visualize" and output.get("chart_spec"):
                # Plotly figure spec — frontend hands it to react-plotly.js.
                yield {"type": "chart", "data": {"spec": output["chart_spec"]}}

        # --- LLM token streaming ---
        # astream_events emits on_chat_model_stream for every chunk received.
        # We filter by langgraph_node to forward ONLY the tokens from `respond`
        # (not from generate_sql, whose output is SQL — not user-facing).
        elif kind == "on_chat_model_stream":
            metadata = event.get("metadata", {})
            if metadata.get("langgraph_node") == "respond":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield {"type": "token", "data": {"text": chunk.content}}

    # Final event: the frontend uses this to know it can stop listening.
    yield {"type": "done", "data": {}}
