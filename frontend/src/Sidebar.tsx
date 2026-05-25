/**
 * Sidebar — conversation history panel.
 *
 * Shows past conversations grouped by date (Today / Yesterday / Older).
 * Clicking a conversation loads it into the main chat area.
 * The delete button (×) appears on hover to keep the UI clean.
 */

import type { Conversation } from "./types";


interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  isOpen: boolean;
  onSelect: (conv: Conversation) => void;
  onDelete: (id: string) => void;
  onNewChat: () => void;
}


function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function groupByDate(convs: Conversation[]) {
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const yesterdayStart = new Date(todayStart);
  yesterdayStart.setDate(yesterdayStart.getDate() - 1);

  return [
    { label: "Today",     items: convs.filter(c => c.createdAt >= todayStart.getTime()) },
    { label: "Yesterday", items: convs.filter(c => c.createdAt >= yesterdayStart.getTime() && c.createdAt < todayStart.getTime()) },
    { label: "Older",     items: convs.filter(c => c.createdAt < yesterdayStart.getTime()) },
  ].filter(g => g.items.length > 0);
}


export function Sidebar({ conversations, activeId, isOpen, onSelect, onDelete, onNewChat }: SidebarProps) {
  const groups = groupByDate(conversations);

  return (
    // Slide in/out by toggling width. transition-all animates smoothly.
    <aside
      className={`
        ${isOpen ? "w-64 min-w-[16rem]" : "w-0"} overflow-hidden
        transition-all duration-200 flex flex-col shrink-0
        border-r border-gray-200 dark:border-gray-700
        bg-gray-100 dark:bg-gray-800
      `}
    >
      {/* New chat button */}
      <div className="p-3 border-b border-gray-200 dark:border-gray-700">
        <button
          type="button"
          onClick={onNewChat}
          className="w-full px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium text-left"
        >
          + New Chat
        </button>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto p-2 space-y-4">
        {groups.map(({ label, items }) => (
          <div key={label}>
            <p className="text-xs font-medium text-gray-400 dark:text-gray-500 px-2 mb-1 uppercase tracking-wide">
              {label}
            </p>
            {items.map(conv => (
              <div
                key={conv.id}
                onClick={() => onSelect(conv)}
                className={`
                  group flex items-start gap-1 px-2 py-2 rounded-lg cursor-pointer
                  ${activeId === conv.id
                    ? "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300"
                    : "hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"}
                `}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate">{conv.title}</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                    {formatTime(conv.createdAt)}
                  </p>
                </div>
                {/* Delete button — only visible on hover */}
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onDelete(conv.id); }}
                  title="Delete conversation"
                  className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 dark:hover:text-red-400 text-sm shrink-0 mt-0.5 transition-opacity"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        ))}

        {conversations.length === 0 && (
          <p className="text-xs text-gray-400 dark:text-gray-500 text-center mt-10 px-2">
            No conversations yet. Ask something!
          </p>
        )}
      </div>
    </aside>
  );
}
