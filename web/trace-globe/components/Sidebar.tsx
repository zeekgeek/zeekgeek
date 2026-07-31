"use client";

import { motion, AnimatePresence } from "framer-motion";
import { ChevronLeft, ChevronRight, MapPin, Server, Wifi } from "lucide-react";
import { formatLocation, formatIsp } from "@/lib/geolocation";
import { latencyColor } from "@/lib/geo";
import { useTraceStore } from "@/store/traceStore";

export function Sidebar() {
  const {
    sidebarOpen,
    setSidebarOpen,
    result,
    status,
    selectedHop,
    setSelectedHop,
    error,
    target,
  } = useTraceStore();

  const hops = result?.hops ?? [];

  return (
    <AnimatePresence>
      {sidebarOpen && (
        <motion.aside
          initial={{ x: 40, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 40, opacity: 0 }}
          className="pointer-events-auto flex h-full max-h-[calc(100vh-14rem)] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-white/10 bg-surface-overlay shadow-2xl backdrop-blur-xl"
        >
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
                Hop feed
              </h2>
              <p className="truncate text-sm text-white">
                {target || "No active trace"}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              className="rounded-lg p-1 text-slate-400 hover:bg-white/5 hover:text-white"
            >
              <ChevronRight className="h-5 w-5" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            {status === "idle" && (
              <p className="p-4 text-center text-sm text-slate-500">
                Enter a domain or IP and click Trace Route.
              </p>
            )}
            {status === "tracing" && (
              <div className="flex flex-col items-center gap-3 p-8 text-slate-400">
                <Wifi className="h-8 w-8 animate-pulse text-accent-cyan" />
                <p className="text-sm">Tracing route…</p>
              </div>
            )}
            {status === "failed" && (
              <p className="rounded-xl border border-accent-red/30 bg-accent-red/10 p-4 text-sm text-accent-red">
                {error ?? "Trace failed"}
              </p>
            )}
            {hops.map((hop) => {
              const active = selectedHop === hop.hop;
              const color = latencyColor(hop.avgMs);
              return (
                <button
                  key={hop.hop}
                  type="button"
                  onClick={() => setSelectedHop(hop.hop)}
                  className={`mb-2 w-full rounded-xl border p-3 text-left transition ${
                    active
                      ? "border-accent-cyan/50 bg-accent-cyan/10 shadow-glow"
                      : "border-white/5 bg-white/[0.03] hover:border-white/15"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/10 text-xs font-bold text-white">
                        {hop.hop}
                      </span>
                      <div className="min-w-0">
                        <p className="truncate font-mono text-xs text-white">
                          {hop.ip ?? "*"}
                        </p>
                        <p className="truncate text-xs text-slate-400">
                          {hop.hostname ?? hop.displayLabel}
                        </p>
                      </div>
                    </div>
                    <span
                      className="shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold"
                      style={{ color, backgroundColor: `${color}22` }}
                    >
                      {hop.avgMs != null ? `${hop.avgMs} ms` : "—"}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-400">
                    <span className="inline-flex items-center gap-1">
                      <MapPin className="h-3 w-3" />
                      {formatLocation(hop.geo)}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Server className="h-3 w-3" />
                      {formatIsp(hop.geo)}
                    </span>
                    {hop.lossPct > 0 && (
                      <span className="text-accent-amber">{hop.lossPct}% loss</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </motion.aside>
      )}
      {!sidebarOpen && (
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          className="pointer-events-auto absolute left-4 top-1/2 z-20 -translate-y-1/2 rounded-r-xl border border-l-0 border-white/10 bg-surface-overlay p-2 text-slate-300 backdrop-blur-xl hover:text-white"
        >
          <ChevronLeft className="h-5 w-5" />
        </button>
      )}
    </AnimatePresence>
  );
}
