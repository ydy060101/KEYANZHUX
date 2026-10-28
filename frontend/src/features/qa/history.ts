import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { QaMode, QaScope, QaTurn } from "./api";

/**
 * Conversation history (02 §4.3).
 *
 * The contract has `session_id` on `QARequest` but no session endpoint, so
 * there is nothing on the server to read back. The list is therefore kept in
 * the browser: real turns the user produced, never fixture data. It is a
 * convenience, not durable storage — clearing site data loses it, which is the
 * honest behaviour of a local-only list.
 */
export interface QaSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  scope: QaScope;
  mode: QaMode;
  turns: QaTurn[];
}

interface HistoryState {
  sessions: QaSession[];
  upsert: (session: QaSession) => void;
  remove: (id: string) => void;
}

const MAX_SESSIONS = 20;
const MAX_TURNS = 50;

export const useQaHistory = create<HistoryState>()(
  persist(
    (set) => ({
      sessions: [],
      upsert: (session) =>
        set((state) => {
          const trimmed: QaSession = {
            ...session,
            turns: session.turns.slice(-MAX_TURNS),
            updatedAt: new Date().toISOString(),
          };
          return {
            sessions: [trimmed, ...state.sessions.filter((item) => item.id !== session.id)].slice(
              0,
              MAX_SESSIONS,
            ),
          };
        }),
      remove: (id) =>
        set((state) => ({ sessions: state.sessions.filter((item) => item.id !== id) })),
    }),
    { name: "keyan-qa-history.v1", version: 1 },
  ),
);

/** The history row's label: the first question, shortened for the rail. */
export function sessionTitle(turns: QaTurn[]): string {
  const first = turns[0];
  if (!first) return "新会话";
  const title = first.question.replace(/\s+/g, " ").trim();
  return title.length > 28 ? `${title.slice(0, 28)}…` : title;
}

export function newId(): string {
  return crypto.randomUUID();
}
