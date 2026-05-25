/**
 * useConversations — manages the conversation history stored in localStorage.
 *
 * Each "conversation" is a session with a title (first question) and a list
 * of messages. The sidebar reads this list; App.tsx creates/updates entries.
 *
 * Why localStorage: keeps the sidebar persistent across browser refreshes
 * without a backend session store. History is local to the user's device,
 * consistent with the project's stateless-backend design.
 */

import { useState } from "react";
import type { Conversation, UIMessage } from "./types";

const STORAGE_KEY = "sqlagent_conversations";
const MAX_STORED = 50; // cap to avoid unbounded localStorage growth


function load(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Conversation[]) : [];
  } catch {
    return [];
  }
}

function persist(convs: Conversation[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(convs.slice(0, MAX_STORED)));
}


export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>(load);
  const [activeId, setActiveId] = useState<string | null>(null);

  function save(updated: Conversation[]) {
    setConversations(updated);
    persist(updated);
  }

  /** Create a new conversation entry and return its id. */
  function createConversation(firstQuestion: string): string {
    const id = crypto.randomUUID();
    const conv: Conversation = {
      id,
      title: firstQuestion.length > 50
        ? firstQuestion.slice(0, 47) + "..."
        : firstQuestion,
      messages: [],
      createdAt: Date.now(),
    };
    save([conv, ...conversations]);
    setActiveId(id);
    return id;
  }

  /** Overwrite the stored messages for a conversation (called on chat done). */
  function updateConversation(id: string, messages: UIMessage[]) {
    save(conversations.map(c => c.id === id ? { ...c, messages } : c));
  }

  /** Remove a conversation from the list. */
  function deleteConversation(id: string) {
    save(conversations.filter(c => c.id !== id));
    if (activeId === id) setActiveId(null);
  }

  /** Look up a conversation by id. */
  function getConversation(id: string): Conversation | undefined {
    return conversations.find(c => c.id === id);
  }

  return {
    conversations,
    activeId,
    setActiveId,
    createConversation,
    updateConversation,
    deleteConversation,
    getConversation,
  };
}
