"""
Chat routes: POST /chat (sync) and POST /chat/stream (SSE).

The /chat endpoint is used by the eval harness — returns the full result
in one shot. The /chat/stream endpoint is what the React frontend uses —
streams tokens via Server-Sent Events as Claude generates the response.

SSE event schema emitted by /chat/stream (see services/agent.stream_agent):
    event: sql     -> {query: "..."}             validated SQL ready to run
    event: table   -> {rows: [...], columns: [...]} executed query result
    event: chart   -> {html: "..."}              Plotly HTML snippet
    event: token   -> {text: "..."}              natural-language token chunks
    event: done    -> {}                          final event (close stream)

Why SSE instead of WebSockets: the client only needs to RECEIVE data
(not send mid-stream). SSE is simpler — no persistent bidirectional
connection to manage — and runs over plain HTTP.

Why sse-starlette instead of a raw StreamingResponse: it handles heartbeats
(prevents reverse-proxy timeouts), retry directives, and correct event
formatting. Same approach the rag-chatbot-template uses.
"""

import json
import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from app.services.agent import run_agent, stream_agent
from app.services.tracing import new_trace, flush as flush_traces

router = APIRouter()


# --- Request / response schemas --------------------------------------------

class Message(BaseModel):
    """
    A single chat message in the conversation history.

    role: "user" for questions, "assistant" for previous answers.
    content: the message text.
    """
    role: str
    content: str


class ChatRequest(BaseModel):
    """
    Body shared by /chat and /chat/stream.

    The LAST message must always have role "user" — that is the new question.
    Everything before it is conversation history.

    The previous_* fields enable the chart-re-render flow described in the
    PRD: when the user asks "show as pie chart" after a prior answer, the
    frontend sends back the previous result + SQL so the agent can skip
    the SQL pipeline and just re-render the chart with the new type.
    """
    messages: list[Message]

    # Optional carry-over from the previous turn (used by route_intent_node
    # to detect chart re-render requests). All three default to None.
    previous_sql: Optional[str] = None
    previous_result: Optional[list[dict]] = None
    previous_columns: Optional[list[str]] = None


class ChatResponse(BaseModel):
    """
    Response body for the sync /chat endpoint — used by the eval harness.

    Includes everything the frontend would also see across SSE events, so
    a non-streaming client gets the full picture in a single payload.
    """
    answer: str             # Natural-language answer
    sql: str                # SQL that was executed (after validation)
    chart_spec: dict        # Plotly figure spec ({data, layout}) for react-plotly.js
    result: list[dict]      # Result rows (JSON-friendly)
    columns: list[str]      # Column names of the result
    attempts: int           # Number of SQL generation attempts
    latency_ms: float       # Total request latency in milliseconds
    trace_id: str           # LangFuse trace ID — empty when tracing is disabled


# --- Internal helpers ------------------------------------------------------

def _to_langchain_messages(messages: list[Message]) -> list[BaseMessage]:
    """
    Convert the API Message objects to LangChain BaseMessage types.

    Why this conversion exists:
      The HTTP API uses simple {role, content} dicts (matches the Anthropic
      Messages API). LangChain internally uses typed classes (HumanMessage,
      AIMessage) so it can route messages correctly to the LLM. We translate
      at the edge and keep the agent code typed.
    """
    converted: list[BaseMessage] = []
    for m in messages:
        if m.role == "user":
            converted.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            converted.append(AIMessage(content=m.content))
        # Silently ignore unknown roles (defensive — should not happen).
    return converted


# --- Endpoints -------------------------------------------------------------

@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """
    Synchronous chat — returns the full response in a single call.
    Used by the eval harness and by tools that cannot consume SSE.
    """
    start = time.perf_counter()

    # Create a new LangFuse trace for this request. Callbacks attach to the
    # graph so every node/LLM call becomes a span under this trace.
    # trace_id is "" and callbacks is [] when LangFuse keys are not configured.
    trace_id, callbacks = new_trace(
        name="chat-sync",
        last_user_message=req.messages[-1].content if req.messages else "",
        chart_change=bool(req.previous_result),
    )

    # Convert the API messages into LangChain types and run the agent graph.
    lc_messages = _to_langchain_messages(req.messages)
    result = run_agent(
        lc_messages,
        previous_sql=req.previous_sql or "",
        previous_result=req.previous_result,
        previous_columns=req.previous_columns,
        callbacks=callbacks,
    )

    latency_ms = (time.perf_counter() - start) * 1000

    # Push pending events to LangFuse before returning so the trace shows up
    # in the dashboard immediately (the SDK buffers events otherwise).
    flush_traces()

    return ChatResponse(
        answer=result["answer"],
        sql=result["sql"],
        chart_spec=result["chart_spec"],
        result=result["result"],
        columns=result["columns"],
        attempts=result["attempts"],
        latency_ms=latency_ms,
        trace_id=trace_id,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """
    Streaming chat over SSE — used by the React frontend.

    Emits incremental events as the agent walks the graph:
      sql -> table -> chart -> token (many) -> done

    Why default=str on json.dumps: pandas may produce non-JSON-native types
    (Decimal, numpy scalars, Timestamp) in the result rows. default=str
    falls back to their string representation instead of raising.
    """
    lc_messages = _to_langchain_messages(req.messages)

    # Create a LangFuse trace for this streaming request. The handler attaches
    # to every node and LLM call so the dashboard shows the full execution.
    trace_id, callbacks = new_trace(
        name="chat-stream",
        last_user_message=req.messages[-1].content if req.messages else "",
        chart_change=bool(req.previous_result),
    )

    async def event_generator():
        # stream_agent yields {"type": <name>, "data": <payload>}.
        # We re-shape each yield into the SSE schema sse-starlette expects.
        # The "done" event is overridden below to include the trace_id, so
        # the frontend can correlate logs with the LangFuse dashboard.
        async for event in stream_agent(
            lc_messages,
            previous_sql=req.previous_sql or "",
            previous_result=req.previous_result,
            previous_columns=req.previous_columns,
            callbacks=callbacks,
        ):
            # Enrich the final event with the trace_id (empty string when
            # tracing is disabled — frontend handles that gracefully).
            if event["type"] == "done":
                event = {"type": "done", "data": {"trace_id": trace_id}}

            yield {
                "event": event["type"],
                "data": json.dumps(event["data"], default=str),
            }

        # Push pending LangFuse events after the stream closes so the trace
        # is visible in the dashboard immediately.
        flush_traces()

    # EventSourceResponse sets the correct headers (Content-Type, Cache-Control,
    # X-Accel-Buffering) and handles heartbeats so reverse proxies do not
    # close idle connections during long generations.
    return EventSourceResponse(event_generator())
