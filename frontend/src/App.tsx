/**
 * Olist Chat — main layout.
 *
 * Structure:
 *   ├── Sidebar (conversation history, dark mode toggle manages its own theme)
 *   └── Main area
 *       ├── Header (title + dark mode toggle + sidebar toggle)
 *       ├── Message list (user + assistant messages with SQL, chart, markdown)
 *       ├── Progressive loading indicator ("Thinking..." / streaming cursor)
 *       └── Auto-resize textarea + Send button
 *
 * Per assistant message we render up to four blocks:
 *   1. SQL query  (collapsible <details>)
 *   2. Plotly chart  (rendered via dangerouslySetInnerHTML — chart_html comes
 *      from our own backend, so it is safe).
 *   3. Natural-language answer (markdown, streamed token-by-token)
 *   4. Footer: trace_id (debugging) + timestamp
 */

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
// remark-gfm enables GitHub Flavored Markdown features in react-markdown:
// tables, strikethrough, autolinked URLs, task lists. Without this plugin,
// markdown tables collapse into a single line of pipes.
import remarkGfm from "remark-gfm";
import { Sidebar } from "./Sidebar";
import { PlotlyChart } from "./PlotlyChart";
import { useChat } from "./useChat";
import { useConversations } from "./useConversations";
import type { Conversation } from "./types";


const SUGGESTED_QUESTIONS = [
  "What are the top 10 sellers by total revenue?",
  "Which Brazilian state has the most orders?",
  "Show monthly order revenue as a line chart",
  "How many customers fall in each RFM segment?",
];


function formatTime(ts?: number) {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}


export default function App() {
  // ── hooks ─────────────────────────────────────────────────────────────────
  const { messages, sendMessage, status, error, loadMessages } = useChat();
  const {
    conversations, activeId, setActiveId,
    createConversation, updateConversation, deleteConversation,
  } = useConversations();

  // ── local state ───────────────────────────────────────────────────────────
  const [input, setInput] = useState("");
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  // Initialise from localStorage; fall back to OS preference if never set.
  const [isDark, setIsDark] = useState<boolean>(() => {
    const saved = localStorage.getItem("olistchat_theme");
    if (saved) return saved === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  // Index of the message whose content was just copied (for feedback).
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  // Tracks which conversation the current chat belongs to (not in React state
  // to avoid stale-closure issues inside async callbacks).
  const activeConvIdRef = useRef<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ── effects ───────────────────────────────────────────────────────────────
  // Sync dark class on <html> whenever isDark changes.
  // Using explicit add/remove instead of toggle() for predictable behaviour.
  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    localStorage.setItem("olistchat_theme", isDark ? "dark" : "light");
  }, [isDark]);

  // Auto-scroll to the latest message.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Persist the conversation whenever a chat round-trip completes.
  useEffect(() => {
    if (status === "idle" && messages.length > 0 && activeConvIdRef.current) {
      updateConversation(activeConvIdRef.current, messages);
    }
  }, [status]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── handlers ──────────────────────────────────────────────────────────────
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || status !== "idle") return;

    // On the very first message of a session, create a sidebar entry.
    if (!activeConvIdRef.current) {
      const id = createConversation(input.trim());
      activeConvIdRef.current = id;
    }

    sendMessage(input.trim());
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }

  // Load a past conversation into the chat area.
  const handleSelectConversation = useCallback((conv: Conversation) => {
    loadMessages(conv.messages);
    activeConvIdRef.current = conv.id;
    setActiveId(conv.id);
    // Close sidebar on narrow screens after selection.
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  }, [loadMessages, setActiveId]);

  function handleNewChat() {
    loadMessages([]);
    activeConvIdRef.current = null;
    setActiveId(null);
    textareaRef.current?.focus();
  }

  function handleDeleteConversation(id: string) {
    deleteConversation(id);
    if (activeConvIdRef.current === id) handleNewChat();
  }

  async function handleCopy(text: string, idx: number) {
    await navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 1500);
  }

  // Auto-resize textarea as user types.
  function handleTextareaChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 overflow-hidden">
      {/* ── Sidebar ── */}
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        isOpen={isSidebarOpen}
        onSelect={handleSelectConversation}
        onDelete={handleDeleteConversation}
        onNewChat={handleNewChat}
      />

      {/* ── Main ── */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex items-center gap-3">
            {/* Sidebar toggle */}
            <button
              type="button"
              onClick={() => setIsSidebarOpen(v => !v)}
              title={isSidebarOpen ? "Hide sidebar" : "Show sidebar"}
              className="text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-100 transition-colors"
            >
              ☰
            </button>
            <div>
              <h1 className="font-bold text-base leading-tight">Olist Chat</h1>
              <p className="text-xs text-gray-500 dark:text-gray-400">dbt marts on Databricks · NL → SQL</p>
            </div>
          </div>
          {/* Dark mode toggle */}
          <button
            type="button"
            onClick={() => setIsDark(d => !d)}
            title={isDark ? "Light mode" : "Dark mode"}
            className="text-xl hover:scale-110 transition-transform"
          >
            {isDark ? "☀️" : "🌙"}
          </button>
        </header>

        {/* Message area */}
        <main className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Empty state with suggested questions */}
          {messages.length === 0 && status === "idle" && (
            <div className="flex flex-col items-center gap-4 mt-12 text-center">
              <p className="text-gray-500 dark:text-gray-400 text-sm">
                Ask anything about the Olist Brazilian e-commerce data. Try one of these:
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-lg w-full">
                {SUGGESTED_QUESTIONS.map(q => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => { setInput(q); textareaRef.current?.focus(); }}
                    className="text-left text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Messages */}
          {messages.map((m, i) => (
            <div
              key={i}
              className={m.role === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={`rounded-2xl px-4 py-3 relative group ${
                  m.role === "user"
                    // User bubbles hug their content: short questions look natural.
                    ? "max-w-[85%] bg-indigo-600 text-white rounded-br-sm"
                    // Assistant bubbles take a wide fixed share so charts have
                    // real width to render into (Plotly's responsive sizing
                    // needs a container with non-trivial width to look right).
                    : "w-[90%] max-w-[900px] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-bl-sm"
                }`}
              >
                {/* ── User message ── */}
                {m.role === "user" && (
                  <p className="whitespace-pre-wrap text-sm">{m.content}</p>
                )}

                {/* ── Assistant message ── */}
                {m.role === "assistant" && (
                  <div className="space-y-3 text-sm">
                    {/* Thinking placeholder — shows BEFORE anything else arrives */}
                    {m.streaming && !m.sql && !m.chart_spec && !m.content && (
                      <span className="text-gray-400 dark:text-gray-500 animate-pulse text-xs">
                        Thinking…
                      </span>
                    )}

                    {/* 1) SQL block (collapsible) */}
                    {m.sql && (
                      <details className="bg-gray-50 dark:bg-gray-900 rounded border border-gray-200 dark:border-gray-700">
                        <summary className="cursor-pointer px-3 py-1.5 text-xs font-mono text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">
                          📜 SQL Query
                        </summary>
                        <pre className="px-3 pb-3 pt-1 overflow-x-auto text-xs text-gray-800 dark:text-gray-200">
                          <code>{m.sql}</code>
                        </pre>
                      </details>
                    )}

                    {/* 2) Plotly chart — react-plotly.js handles resize and
                        ResizeObserver so the chart paints at the correct width
                        even when the chat bubble is still animating in. */}
                    {m.chart_spec && (
                      <div className="rounded overflow-hidden bg-white p-2">
                        <PlotlyChart spec={m.chart_spec} />
                      </div>
                    )}

                    {/* 3) Natural-language response (markdown + streaming cursor)
                        remarkGfm enables GitHub-flavored markdown so tables,
                        strikethrough and task lists render correctly. */}
                    {m.content && (
                      <div className="prose prose-sm dark:prose-invert max-w-none prose-pre:bg-gray-100 dark:prose-pre:bg-gray-900 prose-headings:mt-3 prose-headings:mb-1 prose-p:my-1 prose-table:text-xs">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {m.content}
                        </ReactMarkdown>
                      </div>
                    )}
                    {m.streaming && m.content && (
                      <span className="animate-pulse">▋</span>
                    )}
                  </div>
                )}

                {/* Copy button — assistant messages only, appears on hover */}
                {m.role === "assistant" && !m.streaming && m.content && (
                  <button
                    type="button"
                    onClick={() => handleCopy(m.content, i)}
                    title="Copy answer"
                    className="absolute -top-2 -right-2 opacity-0 group-hover:opacity-100 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-full px-2 py-0.5 text-xs text-gray-500 dark:text-gray-300 hover:text-gray-800 dark:hover:text-white transition-all shadow-sm"
                  >
                    {copiedIdx === i ? "Copied!" : "Copy"}
                  </button>
                )}

                {/* Footer: timestamp + trace_id */}
                {m.createdAt && (
                  <div className={`text-xs mt-1 flex items-center gap-2 ${
                    m.role === "user" ? "text-indigo-200" : "text-gray-400 dark:text-gray-500"
                  }`}>
                    <span>{formatTime(m.createdAt)}</span>
                    {m.trace_id && (
                      <span className="font-mono opacity-60" title="LangFuse trace ID">
                        · {m.trace_id.slice(0, 8)}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Error */}
          {error && (
            <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg px-4 py-2">
              {error}
            </div>
          )}

          <div ref={bottomRef} />
        </main>

        {/* Input */}
        <form
          onSubmit={handleSubmit}
          className="p-4 border-t border-gray-200 dark:border-gray-700 shrink-0"
        >
          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={handleTextareaChange}
              onKeyDown={(e) => {
                // Enter submits; Shift+Enter inserts newline.
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e as unknown as React.FormEvent);
                }
              }}
              placeholder="Ask about Olist orders, sellers, RFM segments..."
              disabled={status !== "idle"}
              className="flex-1 resize-none px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 max-h-48 overflow-y-auto text-sm"
            />
            <button
              type="submit"
              disabled={status !== "idle" || !input.trim()}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg disabled:bg-gray-300 dark:disabled:bg-gray-600 disabled:cursor-not-allowed transition-colors shrink-0 text-sm font-medium"
            >
              {status === "idle" ? "Send" : "..."}
            </button>
          </div>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
            Shift+Enter for newline · Try "show as pie chart" after a result
          </p>
        </form>
      </div>
    </div>
  );
}
