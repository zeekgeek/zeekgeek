"use client";

import { motion } from "framer-motion";
import { useTraceStore } from "@/store/traceStore";
import { formatLocation, formatIsp } from "@/lib/geolocation";
import { latencyColor } from "@/lib/geo";

/** Fixed-position tooltip when a hop is selected. */
export function HopTooltip() {
  const selectedHop = useTraceStore((s) => s.selectedHop);
  const result = useTraceStore((s) => s.result);
  const hop = result?.hops.find((h) => h.hop === selectedHop);

  if (!hop) return null;

  const color = latencyColor(hop.avgMs);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="pointer-events-none absolute bottom-28 right-4 z-30 w-72 rounded-2xl border border-white/15 bg-black/85 p-4 shadow-2xl backdrop-blur-xl"
    >
      <div className="mb-2 flex items-center gap-2">
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg text-sm font-bold text-slate-950"
          style={{ backgroundColor: color }}
        >
          {hop.hop}
        </span>
        <div className="min-w-0">
          <p className="truncate font-mono text-sm text-white">{hop.ip ?? "*"}</p>
          <p className="truncate text-xs text-slate-400">
            {hop.hostname ?? hop.displayLabel}
          </p>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt className="text-slate-500">Latency</dt>
        <dd className="font-semibold" style={{ color }}>
          {hop.avgMs != null ? `${hop.avgMs} ms avg` : "—"}
        </dd>
        <dt className="text-slate-500">Loss</dt>
        <dd className="text-white">{hop.lossPct}%</dd>
        <dt className="text-slate-500">Location</dt>
        <dd className="col-span-1 text-accent-cyan">{formatLocation(hop.geo)}</dd>
        <dt className="text-slate-500">ISP / ASN</dt>
        <dd className="col-span-1 text-slate-200">{formatIsp(hop.geo)}</dd>
      </dl>
    </motion.div>
  );
}
