"""
LangFuse tracing service — LLM observability.

What this gives us:
  - Every request becomes a TRACE in the LangFuse dashboard.
  - Every LangGraph node becomes a SPAN inside that trace, with input/output.
  - Every Claude call becomes a GENERATION with prompt, completion, tokens, cost.
  - The trace_id is returned to the client so logs can be correlated with the
    dashboard for debugging (e.g. "user reported a bad answer — show me trace abc").

Why optional: LangFuse keys are not required for the app to run. If they are
empty in the .env, this module returns None / empty lists, and the agent runs
without observability — perfect for local hacking without setting up an account.

Why a thin wrapper around the LangFuse SDK:
  - Centralizes the "is tracing enabled?" check in ONE place.
  - Keeps the rest of the code free of conditional `if handler is not None:`.
"""

from typing import Optional

from langfuse import Langfuse
from langfuse.callback import CallbackHandler

from app.config import settings


# --- Client singleton ------------------------------------------------------

# Cached client instance. Created once on first call to get_client().
# None means tracing is disabled (no LangFuse keys configured).
_client: Optional[Langfuse] = None
# Sentinel to remember we already tried to initialize (avoids re-checking env on every call).
_initialized: bool = False


def get_client() -> Optional[Langfuse]:
    """
    Return the LangFuse client singleton, or None if tracing is disabled.

    Tracing is disabled when either LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY
    is empty in the .env. Returning None (instead of a no-op fake) keeps the
    contract explicit — callers MUST check before using.
    """
    global _client, _initialized

    if _initialized:
        return _client

    _initialized = True

    # Both keys are required. Either being empty means tracing is off.
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        print("[tracing] LangFuse keys not configured — tracing disabled")
        return None

    _client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    print(f"[tracing] LangFuse client initialized (host={settings.langfuse_host})")
    return _client


# --- Per-request trace setup -----------------------------------------------

def new_trace(name: str, **metadata) -> tuple[str, list[CallbackHandler]]:
    """
    Create a new trace for an incoming request.

    Returns: (trace_id, callbacks)
      - trace_id: empty string when tracing is disabled, else the LangFuse trace UUID.
      - callbacks: list to pass to graph.invoke(config={"callbacks": ...}).
                   Empty list when tracing is disabled.

    Why this shape: the caller can ALWAYS pass `callbacks` to LangChain without
    checking — an empty list is harmless. And the caller can ALWAYS include
    trace_id in the response — an empty string just signals "no tracing".

    Example:
        trace_id, callbacks = new_trace("chat-request", user="anon")
        result = run_agent(messages, callbacks=callbacks)
        return {"answer": result["answer"], "trace_id": trace_id}
    """
    client = get_client()
    if client is None:
        return "", []

    # Create a parent trace. The LangChain handler will attach all spans /
    # generations to this trace as nested children.
    trace = client.trace(name=name, metadata=metadata or None)
    handler = trace.get_langchain_handler()

    return trace.id, [handler]


def flush() -> None:
    """
    Flush pending LangFuse events to the server.

    Why we need this: the SDK buffers events for efficiency. In long-running
    services this is fine — they get sent eventually. But for short-lived
    request handlers, we want the events visible in the dashboard immediately.

    Safe to call when tracing is disabled (no-op).
    """
    client = get_client()
    if client is not None:
        client.flush()
