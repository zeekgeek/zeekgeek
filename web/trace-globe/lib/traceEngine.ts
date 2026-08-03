import { totalRouteDistanceKm } from "./geo";
import {
  formatLocation,
  geoForHop,
  lookupMany,
  lookupSelf,
} from "./geolocation";
import {
  MOCK_GEO,
  resolveTarget,
  runTraceroute,
  type ParsedHop,
} from "./traceroute";
import type { GeoLocation, TraceHop, TraceResult } from "./types";

function hopStats(rtts: number[]) {
  if (rtts.length === 0) return { avg: null, min: null, max: null };
  const sum = rtts.reduce((a, b) => a + b, 0);
  return {
    avg: Math.round((sum / rtts.length) * 10) / 10,
    min: Math.round(Math.min(...rtts) * 10) / 10,
    max: Math.round(Math.max(...rtts) * 10) / 10,
  };
}

function enrichMockGeo(ip: string): GeoLocation | null {
  const entry = MOCK_GEO[ip];
  if (!entry) return null;
  return { ...entry, isPrivate: false };
}

export async function executeTrace(target: string): Promise<TraceResult> {
  const trimmed = target.trim();
  if (!trimmed) {
    return failedTrace(trimmed, "Target is required");
  }

  const resolvedIp = await resolveTarget(trimmed);
  const origin = await lookupSelf();
  const { hops: parsed, mode } = await runTraceroute(trimmed);

  if (parsed.length === 0) {
    return failedTrace(trimmed, "Traceroute returned no hops");
  }

  const publicIps = parsed.map((h) => h.ip).filter((ip): ip is string => !!ip);
  const geoMap =
    mode === "mock"
      ? new Map(
          publicIps
            .map((ip) => [ip, enrichMockGeo(ip)] as const)
            .filter(([, g]) => g !== null) as [string, GeoLocation][],
        )
      : await lookupMany(publicIps);

  const hops: TraceHop[] = parsed.map((p) => toTraceHop(p, geoMap, origin));

  const answered = hops.filter((h) => h.avgMs !== null);
  const avgLatencyMs =
    answered.length > 0
      ? Math.round(
          (answered.reduce((s, h) => s + (h.avgMs ?? 0), 0) / answered.length) * 10,
        ) / 10
      : null;
  const maxLatencyMs =
    answered.length > 0
      ? Math.max(...answered.map((h) => h.maxMs ?? 0))
      : null;

  const geolocated = hops.filter((h) => h.geo && !h.geo.isInternal);
  const totalDistanceKm = totalRouteDistanceKm(
    geolocated.length ? geolocated : hops,
  );

  return {
    target: trimmed,
    resolvedIp,
    status: hops.some((h) => h.ip === resolvedIp) ? "complete" : "partial",
    mode,
    origin,
    hops,
    stats: {
      hopCount: hops.length,
      avgLatencyMs,
      totalDistanceKm,
      maxLatencyMs,
    },
    tracedAt: new Date().toISOString(),
  };
}

function toTraceHop(
  p: ParsedHop,
  geoMap: Map<string, GeoLocation>,
  origin: GeoLocation | null,
): TraceHop {
  const stats = hopStats(p.rttsMs);
  const lossPct =
    p.probes > 0
      ? Math.round(((p.probes - p.rttsMs.length) / p.probes) * 1000) / 10
      : 100;
  const geo = geoForHop(p.ip, geoMap, origin);
  let displayLabel = p.hostname ?? p.ip ?? "* no reply *";
  if (geo?.isInternal) displayLabel = `Internal · ${p.ip ?? "LAN"}`;
  return {
    hop: p.ttl,
    ip: p.ip,
    hostname: p.hostname,
    rttsMs: p.rttsMs,
    avgMs: stats.avg,
    minMs: stats.min,
    maxMs: stats.max,
    lossPct,
    probes: p.probes,
    geo,
    displayLabel,
  };
}

function failedTrace(target: string, error: string): TraceResult {
  return {
    target,
    resolvedIp: null,
    status: "failed",
    mode: "mock",
    origin: null,
    hops: [],
    stats: {
      hopCount: 0,
      avgLatencyMs: null,
      totalDistanceKm: 0,
      maxLatencyMs: null,
    },
    error,
    tracedAt: new Date().toISOString(),
  };
}

export { formatLocation };
