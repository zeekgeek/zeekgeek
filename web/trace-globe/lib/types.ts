export type TraceStatus = "idle" | "tracing" | "complete" | "failed";

export interface GeoLocation {
  lat: number;
  lon: number;
  city: string | null;
  country: string | null;
  countryCode: string | null;
  isp: string | null;
  org: string | null;
  asn: string | null;
  isPrivate: boolean;
  isInternal?: boolean;
}

export interface TraceHop {
  hop: number;
  ip: string | null;
  hostname: string | null;
  rttsMs: number[];
  avgMs: number | null;
  minMs: number | null;
  maxMs: number | null;
  lossPct: number;
  probes: number;
  geo: GeoLocation | null;
  displayLabel: string;
}

export interface TraceResult {
  target: string;
  resolvedIp: string | null;
  status: "complete" | "partial" | "failed";
  mode: "live" | "mock";
  origin: GeoLocation | null;
  hops: TraceHop[];
  stats: {
    hopCount: number;
    avgLatencyMs: number | null;
    totalDistanceKm: number;
    maxLatencyMs: number | null;
  };
  error?: string;
  tracedAt: string;
}

export interface TraceApiResponse {
  ok: boolean;
  result?: TraceResult;
  error?: string;
}
