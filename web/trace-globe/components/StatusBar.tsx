"use client";

import { motion } from "framer-motion";
import { Activity, Gauge, MapPinned, Route } from "lucide-react";
import { useTraceStore } from "@/store/traceStore";

const STATUS_LABEL: Record<string, string> = {
  idle: "Idle",
  tracing: "Tracing…",
  complete: "Complete",
  failed: "Failed",
};

const STATUS_COLOR: Record<string, string> = {
  idle: "text-slate-400",
  tracing: "text-accent-cyan",
  complete: "text-accent-green",
  failed: "text-accent-red",
};

export function StatusBar() {
  const { status, result, error } = useTraceStore();
  const stats = result?.stats;
  const mode = result?.mode;

  return (
    <motion.footer
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="pointer-events-auto flex flex-wrap items-center gap-4 rounded-2xl border border-white/10 bg-surface-overlay px-4 py-3 text-sm shadow-2xl backdrop-blur-xl"
    >
      <Stat
        icon={Activity}
        label="Status"
        value={
          <span className={STATUS_COLOR[status] ?? "text-white"}>
            {STATUS_LABEL[status] ?? status}
            {mode === "mock" && status === "complete" && (
              <span className="ml-2 text-xs text-accent-amber">(simulated)</span>
            )}
          </span>
        }
      />
      <Stat
        icon={Route}
        label="Hops"
        value={stats?.hopCount ?? "—"}
      />
      <Stat
        icon={Gauge}
        label="Avg latency"
        value={
          stats?.avgLatencyMs != null ? `${stats.avgLatencyMs} ms` : "—"
        }
      />
      <Stat
        icon={MapPinned}
        label="Distance"
        value={
          stats?.totalDistanceKm != null
            ? `${stats.totalDistanceKm.toLocaleString()} km`
            : "—"
        }
      />
      {error && status === "failed" && (
        <span className="text-xs text-accent-red">{error}</span>
      )}
    </motion.footer>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-4 w-4 text-slate-500" />
      <div>
        <p className="text-[10px] uppercase tracking-wider text-slate-500">
          {label}
        </p>
        <p className="font-medium text-white">{value}</p>
      </div>
    </div>
  );
}
