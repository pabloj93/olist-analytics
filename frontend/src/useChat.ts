/**
 * useChat — React hook that owns the live conversation state and consumes
 * the backend's SSE streaming endpoint.
 *
 * Public surface:
 *     const { messages, sendMessage, status, error, loadMessages } = useChat();
 *
 * status drives the loading indicator in App.tsx:
 *   "thinking"   → request sent, waiting for the agent (sql/table/chart events)
 *   "generating" → tokens are streaming in (Claude is writing the answer)
 *   "idle"       → nothing in flight
 *
 * Why this hook also forwards the previous turn's data:
 *   The PRD requires "chart re-render" — the user can say "show as pie chart"
 *   and the agent should re-render the previous result without running SQL.
 *   We grab the last assistant message's sql/rows/columns and include them
 *   in the request body. The backend's route_intent decides what to do with them.
 */

import { useCallback, useState } from "react";
import type { ChatStatus, SSEEvent, UIMessage } from "./types";

// Three modes here, all handled by the same expression:
//   1. HF Spaces single-container: VITE_BACKEND_URL is explicitly set to ""
//      at build time (see root Dockerfile). Result: BACKEND_URL is "" →
//      fetch("/chat/stream") is a relative URL → FastAPI on the same origin
//      serves it. No CORS, no port mismatch.
//   2. Docker compose dev: build ARG sets it to "http://localhost:8000" →
//      BACKEND_URL hits the separate backend container via host mapping.
//   3. `npm run dev` without any env setup: VITE_BACKEND_URL is undefined →
//      `??` kicks in and we fall back to http://localhost:8000.
//
// Why `??` (nullish coalescing) and not `||`: "" is a meaningful value here
// (means "relative URL"), so we must preserve it instead of treating it as
// missing. `??` only replaces `null` or `undefined`.
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8000";


export function useChat() {
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  /**
   * Replace the current message list (used when loading a past conversation
   * from the sidebar). Resets status and error too.
   */
  function loadMessages(msgs: UIMessage[]) {
    setMessages(msgs);
    setStatus("idle");
    setError(null);
  }

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || status !== "idle") return;

      setError(null);
      setStatus("thinking"); // user sees "Thinking..." until first event arrives

      const userMessage: UIMessage = { role: "user", content: text, createdAt: Date.now() };
      const assistantPlaceholder: UIMessage = {
        role: "assistant",
        content: "",
        streaming: true,
        createdAt: Date.now(),
      };
      const currentMessages = [...messages, userMessage];
      setMessages([...currentMessages, assistantPlaceholder]);

      // Grab the last assistant message with data — used by the backend's
      // route_intent node to detect chart re-render requests.
      const lastAssistant = [...messages].reverse().find(
        m => m.role === "assistant" && (m.sql || m.rows),
      );

      const body = {
        // Backend only needs {role, content} — drop the UI-only fields.
        messages: currentMessages.map(({ role, content }) => ({ role, content })),
        previous_sql: lastAssistant?.sql ?? null,
        previous_result: lastAssistant?.rows ?? null,
        previous_columns: lastAssistant?.columns ?? null,
      };

      try {
        const response = await fetch(`${BACKEND_URL}/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

        await consumeSSE(response.body, (evt) => {
          switch (evt.event) {
            case "sql":
              // SQL produced — surface it in the assistant message.
              setMessages(prev => updateLast(prev, { sql: evt.data.query }));
              break;
            case "table":
              setMessages(prev => updateLast(prev, {
                rows: evt.data.rows,
                columns: evt.data.columns,
              }));
              break;
            case "chart":
              // Chart rendered — flip the status so the cursor appears once
              // the LLM starts writing the natural-language answer.
              setStatus("generating");
              setMessages(prev => updateLast(prev, { chart_spec: evt.data.spec }));
              break;
            case "token":
              setStatus("generating");
              setMessages(prev =>
                updateLast(prev, {
                  content: (prev[prev.length - 1]?.content ?? "") + evt.data.text,
                })
              );
              break;
            case "done":
              setMessages(prev => updateLast(prev, {
                streaming: false,
                trace_id: evt.data.trace_id,
              }));
              setStatus("idle");
              break;
            case "error":
              throw new Error(evt.data.message);
          }
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unknown error");
        setMessages(prev => updateLast(prev, { streaming: false }));
        setStatus("idle");
      }
    },
    [messages, status]
  );

  return { messages, sendMessage, status, error, loadMessages };
}


// --- helpers ----------------------------------------------------------------

/** Immutable patch of the last message in the array. */
function updateLast(messages: UIMessage[], patch: Partial<UIMessage>): UIMessage[] {
  if (messages.length === 0) return messages;
  const last = messages[messages.length - 1];
  return [...messages.slice(0, -1), { ...last, ...patch }];
}

/**
 * Read a ReadableStream of SSE bytes and dispatch parsed events.
 *
 * SSE protocol detail: events are separated by a blank line. Per RFC 8895,
 * the separator can be \n\n, \r\n\r\n, or even \r\r — and the library we
 * use on the backend (sse-starlette) emits CRLF (\r\n). We must handle ALL
 * of these to be portable. The TextDecoder reassembles UTF-8 across chunks.
 */
async function consumeSSE(
  body: ReadableStream<Uint8Array>,
  onEvent: (evt: SSEEvent) => void
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // Regex covers all three legal event separators: \n\n, \r\n\r\n, \r\r.
  // Without this, sse-starlette's \r\n\r\n events would never be split out
  // of the buffer and the UI would hang at "Thinking..." forever.
  const EVENT_SEPARATOR = /\r?\n\r?\n|\r\r/;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const chunks = buffer.split(EVENT_SEPARATOR);
    // Keep the last (possibly incomplete) chunk in the buffer for the next read.
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const evt = parseSSEEvent(chunk);
      if (evt) onEvent(evt);
    }
  }
}

/**
 * Parse one SSE event block (the text between two blank lines).
 *
 * Within an event, lines can also be terminated by \r\n — we trim() each
 * value so trailing \r does not break JSON.parse.
 */
function parseSSEEvent(raw: string): SSEEvent | null {
  let eventType = "";
  let data = "";
  // Split on \r\n or \n to cover both line-ending conventions.
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith("event: ")) eventType = line.slice(7).trim();
    else if (line.startsWith("data: ")) data = line.slice(6).trim();
  }
  if (!eventType || !data) return null;
  try {
    return { event: eventType as SSEEvent["event"], data: JSON.parse(data) } as SSEEvent;
  } catch {
    return null;
  }
}
