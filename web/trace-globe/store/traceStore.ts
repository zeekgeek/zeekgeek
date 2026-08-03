import { create } from "zustand";
import type { TraceHop, TraceResult, TraceStatus } from "@/lib/types";

interface TraceStore {
  status: TraceStatus;
  target: string;
  result: TraceResult | null;
  error: string | null;
  selectedHop: number | null;
  sidebarOpen: boolean;
  autoRotate: boolean;
  setTarget: (target: string) => void;
  setSelectedHop: (hop: number | null) => void;
  setSidebarOpen: (open: boolean) => void;
  setAutoRotate: (on: boolean) => void;
  startTrace: (target: string) => Promise<void>;
  reset: () => void;
}

export const useTraceStore = create<TraceStore>((set, get) => ({
  status: "idle",
  target: "",
  result: null,
  error: null,
  selectedHop: null,
  sidebarOpen: true,
  autoRotate: true,

  setTarget: (target) => set({ target }),
  setSelectedHop: (selectedHop) => set({ selectedHop, autoRotate: selectedHop === null }),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setAutoRotate: (autoRotate) => set({ autoRotate }),

  startTrace: async (target) => {
    const trimmed = target.trim();
    if (!trimmed) return;
    set({
      status: "tracing",
      target: trimmed,
      error: null,
      result: null,
      selectedHop: null,
      autoRotate: false,
    });
    try {
      const res = await fetch("/api/trace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: trimmed }),
      });
      const data = (await res.json()) as {
        ok: boolean;
        result?: TraceResult;
        error?: string;
      };
      if (!data.ok || !data.result) {
        set({
          status: "failed",
          error: data.error ?? "Trace failed",
          result: data.result ?? null,
        });
        return;
      }
      const firstLocated = data.result.hops.find((h: TraceHop) => h.geo)?.hop ?? null;
      set({
        status: "complete",
        result: data.result,
        selectedHop: firstLocated,
        error: data.result.error ?? null,
      });
    } catch (err) {
      set({
        status: "failed",
        error: err instanceof Error ? err.message : "Network error",
      });
    }
  },

  reset: () =>
    set({
      status: "idle",
      target: "",
      result: null,
      error: null,
      selectedHop: null,
      autoRotate: true,
    }),
}));

export const PRESETS = [
  "github.com",
  "google.com",
  "bbc.co.uk",
  "tokyo.ac.jp",
  "1.1.1.1",
  "8.8.8.8",
] as const;
