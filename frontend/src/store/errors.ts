import { create } from "zustand";

export interface ErrorEntry {
  id: number;
  ts: number;
  level: "error" | "warning";
  source: string; // stt | tts | gateway | engine | client
  code?: string;
  message: string;
  requestId?: string | null;
  sessionId?: string | null;
  modelId?: string | null;
  traceback?: string;
  details?: unknown;
  count: number;
}

export type NewError = Omit<ErrorEntry, "id" | "ts" | "count"> & { ts?: number };

interface ErrorStore {
  entries: ErrorEntry[];
  unread: number;
  add: (e: NewError) => void;
  markRead: () => void;
  clear: () => void;
}

const MAX_ENTRIES = 500;
let nextId = 1;

/** The same failure can arrive twice: in the HTTP/WS response and as a server log event.
 * Both carry the request id, so they are merged into one entry (keeping the traceback). */
function sameFailure(a: ErrorEntry, b: NewError): boolean {
  if (!a.requestId || a.requestId !== b.requestId) return false;
  return !a.code || !b.code || a.code === b.code;
}

export const useErrors = create<ErrorStore>((set) => ({
  entries: [],
  unread: 0,
  add: (e) =>
    set((state) => {
      const idx = state.entries.findIndex((x) => sameFailure(x, e));
      if (idx >= 0) {
        const merged = { ...state.entries[idx] };
        merged.traceback ??= e.traceback;
        merged.code ??= e.code;
        merged.modelId ??= e.modelId;
        merged.sessionId ??= e.sessionId;
        if (e.source !== "client") merged.source = e.source;
        const entries = [...state.entries];
        entries[idx] = merged;
        return { entries };
      }
      const entry: ErrorEntry = { ...e, id: nextId++, ts: e.ts ?? Date.now(), count: 1 };
      return { entries: [entry, ...state.entries].slice(0, MAX_ENTRIES), unread: state.unread + 1 };
    }),
  markRead: () => set({ unread: 0 }),
  clear: () => set({ entries: [], unread: 0 }),
}));

export const reportError = (e: NewError) => useErrors.getState().add(e);
