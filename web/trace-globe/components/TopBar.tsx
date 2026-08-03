"use client";

import { motion } from "framer-motion";
import { Globe2, Loader2, Play, RotateCcw } from "lucide-react";
import { PRESETS, useTraceStore } from "@/store/traceStore";

export function TopBar() {
  const {
    target,
    setTarget,
    startTrace,
    status,
    reset,
    setSidebarOpen,
    sidebarOpen,
  } = useTraceStore();
  const tracing = status === "tracing";

  return (
    <motion.header
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="pointer-events-auto flex flex-col gap-3 rounded-2xl border border-white/10 bg-surface-overlay p-4 shadow-2xl backdrop-blur-xl"
    >
      <div className="flex items-center gap-3">
        <Globe2 className="h-6 w-6 text-accent-cyan shrink-0" />
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold tracking-tight text-white">
            Trace Globe
          </h1>
          <p className="text-xs text-slate-400">
            Interactive 3D traceroute · geolocation · latency arcs
          </p>
        </div>
        <button
          type="button"
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5"
        >
          {sidebarOpen ? "Hide hops" : "Show hops"}
        </button>
      </div>

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void startTrace(target);
        }}
      >
        <input
          type="text"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="Domain or IP — google.com, 8.8.8.8"
          className="min-w-[220px] flex-1 rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white placeholder:text-slate-500 focus:border-accent-cyan/50 focus:outline-none focus:ring-1 focus:ring-accent-cyan/30"
          disabled={tracing}
        />
        <button
          type="submit"
          disabled={tracing || !target.trim()}
          className="inline-flex items-center gap-2 rounded-xl bg-accent-cyan px-4 py-2.5 text-sm font-semibold text-slate-950 disabled:opacity-50"
        >
          {tracing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          Trace Route
        </button>
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-1 rounded-xl border border-white/10 px-3 py-2.5 text-sm text-slate-300 hover:bg-white/5"
        >
          <RotateCcw className="h-4 w-4" />
        </button>
      </form>

      <div className="flex flex-wrap gap-2">
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            disabled={tracing}
            onClick={() => {
              setTarget(preset);
              void startTrace(preset);
            }}
            className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300 transition hover:border-accent-cyan/40 hover:text-white disabled:opacity-50"
          >
            {preset}
          </button>
        ))}
      </div>
    </motion.header>
  );
}
