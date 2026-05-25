/**
 * Domain types shared across the frontend.
 */

/** One turn in the conversation, as the backend's /chat schema expects. */
export interface Message {
  role: "user" | "assistant";
  content: string;
}

/** Row of a query result — keys are column names, values are anything DuckDB can return. */
export type TableRow = Record<string, unknown>;

/**
 * Plotly figure spec — what react-plotly.js consumes.
 * The backend emits this shape via plotly.io.to_json(fig).
 */
export interface PlotlySpec {
  data?: unknown[];
  layout?: Record<string, unknown>;
  config?: Record<string, unknown>;
}

/**
 * Conversation turn enriched with UI state.
 *
 * Assistant messages can carry up to four extra fields filled in by the SSE
 * events: sql (the validated query), rows + columns (the result table),
 * and chart_html (the Plotly snippet). The natural-language response lives
 * in `content` (markdown).
 */
export interface UIMessage extends Message {
  /** SQL query executed against DuckDB (after the `sql` SSE event). */
  sql?: string;
  /** Result rows (after the `table` SSE event). */
  rows?: TableRow[];
  /** Result column names (after the `table` SSE event). */
  columns?: string[];
  /** Plotly figure spec (after the `chart` SSE event). */
  chart_spec?: PlotlySpec;
  /** LangFuse trace id from the `done` event — useful for debugging. */
  trace_id?: string;
  /** True while the assistant is still streaming this message. */
  streaming?: boolean;
  /** Unix timestamp (ms) — used to render the per-message time badge. */
  createdAt?: number;
}

/**
 * Discriminated union of every SSE event the backend can emit.
 * TypeScript narrows `data` based on `event` — stays type-safe without casts.
 *
 * Mirror of the schema in backend/app/routers/chat.py (chat_stream).
 */
export type SSEEvent =
  | { event: "sql"; data: { query: string } }
  | { event: "table"; data: { rows: TableRow[]; columns: string[] } }
  | { event: "chart"; data: { spec: PlotlySpec } }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: { trace_id: string } }
  | { event: "error"; data: { message: string } };

/**
 * Progressive status of the chat pipeline.
 *   idle       → nothing in flight
 *   thinking   → request sent, agent is generating SQL / running query / rendering chart
 *   generating → tokens streaming in from the LLM (chart already shown)
 */
export type ChatStatus = "idle" | "thinking" | "generating";

/**
 * A persisted conversation stored in localStorage.
 * `title` is the first user question (truncated to 50 chars).
 */
export interface Conversation {
  id: string;
  title: string;
  messages: UIMessage[];
  createdAt: number;
}
