import { create } from "zustand";
import type { SttMode } from "../../api/types";

export interface SttRowConfig {
  id: string;
  modelId: string;
  mode: SttMode;
  language: string; // "" = auto-detect
  source: "fixture" | "file" | "mic";
  fixtureIds: string[];
  files: File[];
  micMode: "hold" | "toggle";
  frameMs: number;
  realtime: boolean;
  beamSize: number;
  vad: { threshold: number; silence_ms: number; pre_roll_ms: number; partial_interval_ms: number };
  window: { size_ms: number; stride_ms: number; tail_ms: number };
}

let counter = 0;
export const newRowId = () => `stt-${Date.now().toString(36)}-${counter++}`;

export const defaultSttRow = (): SttRowConfig => ({
  id: newRowId(),
  modelId: "",
  mode: "file_single",
  language: "en",
  source: "fixture",
  fixtureIds: [],
  files: [],
  micMode: "hold",
  frameMs: 40,
  realtime: true,
  beamSize: 1,
  vad: { threshold: 0.5, silence_ms: 600, pre_roll_ms: 300, partial_interval_ms: 0 },
  window: { size_ms: 6000, stride_ms: 1000, tail_ms: 1500 },
});

interface RowsStore<T extends { id: string }> {
  rows: T[];
  runTick: number;
  add: (row: T) => void;
  update: (id: string, patch: Partial<T>) => void;
  remove: (id: string) => void;
  clone: (id: string, n: number, makeId: () => string) => void;
  runAll: () => void;
}

export function createRowsStore<T extends { id: string }>(initial: T[]) {
  return create<RowsStore<T>>((set) => ({
    rows: initial,
    runTick: 0,
    add: (row) => set((s) => ({ rows: [...s.rows, row] })),
    update: (id, patch) => set((s) => ({ rows: s.rows.map((r) => (r.id === id ? { ...r, ...patch } : r)) })),
    remove: (id) => set((s) => ({ rows: s.rows.filter((r) => r.id !== id) })),
    clone: (id, n, makeId) =>
      set((s) => {
        const idx = s.rows.findIndex((r) => r.id === id);
        if (idx < 0) return s;
        const copies = Array.from({ length: n }, () => ({ ...s.rows[idx], id: makeId() }));
        return { rows: [...s.rows.slice(0, idx + 1), ...copies, ...s.rows.slice(idx + 1)] };
      }),
    runAll: () => set((s) => ({ runTick: s.runTick + 1 })),
  }));
}

export const useSttRows = createRowsStore<SttRowConfig>([defaultSttRow()]);
