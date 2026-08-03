import { execFile } from "node:child_process";
import { promisify } from "node:util";
import dns from "node:dns/promises";

const execFileAsync = promisify(execFile);

export interface ParsedHop {
  ttl: number;
  ip: string | null;
  hostname: string | null;
  rttsMs: number[];
  probes: number;
}

const HOP_RE =
  /^\s*(\d+)\s+(?:(?:\*\s*)+|(?:(?:(?<host>[^\s()]+)\s+)?(?:\((?<parenIp>[0-9a-fA-F:.]+)\)\s+)?(?<body>.+)))\s*$/;
const RTT_RE = /(\d+(?:\.\d+)?)\s*ms/g;
const IP_TOKEN_RE = /^(?:\d{1,3}\.){3}\d{1,3}$|^[0-9a-fA-F:]+$/;

export function parseTracerouteOutput(text: string, probes = 5): ParsedHop[] {
  const hops: ParsedHop[] = [];
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.toLowerCase().startsWith("traceroute")) continue;
    const match = HOP_RE.exec(line);
    if (!match?.groups) continue;
    const ttl = Number(match.groups[1] ?? match[1]);
    const body = match.groups.body;
    if (!body && line.includes("*")) {
      hops.push({ ttl, ip: null, hostname: null, rttsMs: [], probes });
      continue;
    }
    const bodyText = body ?? "";
    if (!RTT_RE.test(bodyText) && bodyText.includes("*")) {
      RTT_RE.lastIndex = 0;
      hops.push({ ttl, ip: null, hostname: null, rttsMs: [], probes });
      continue;
    }
    RTT_RE.lastIndex = 0;
    const rtts = [...bodyText.matchAll(RTT_RE)].map((m) => Number(m[1]));
    let hostname: string | null = match.groups.host ?? null;
    let ip: string | null = match.groups.parenIp ?? null;
    if (hostname && IP_TOKEN_RE.test(hostname) && !ip) {
      ip = hostname;
      hostname = null;
    }
    if (!ip) {
      for (const token of bodyText.split(/\s+/)) {
        const cleaned = token.replace(/[()]/g, "");
        if (IP_TOKEN_RE.test(cleaned)) {
          ip = cleaned;
          break;
        }
      }
    }
    const stars = (bodyText.match(/\*/g) ?? []).length;
    hops.push({
      ttl,
      ip: ip ?? null,
      hostname: hostname === "*" ? null : hostname,
      rttsMs: rtts,
      probes: Math.max(probes, rtts.length + stars),
    });
  }
  return hops;
}

export function parseTracepathOutput(text: string): ParsedHop[] {
  const hops: ParsedHop[] = [];
  const lineRe =
    /^\s*(\d+)(?:\?)?:\s+(?:(?<host>\S+)\s+)?(?:(?<rtt>\d+(?:\.\d+)?)\s*ms|no reply)/i;
  for (const rawLine of text.split("\n")) {
    if (/pmtu/i.test(rawLine)) continue;
    const match = lineRe.exec(rawLine.trim());
    if (!match?.groups) continue;
    const ttl = Number(match[1]);
    const host = match.groups.host;
    const rtt = match.groups.rtt;
    if (!rtt || host?.toLowerCase() === "no") {
      hops.push({ ttl, ip: null, hostname: null, rttsMs: [], probes: 1 });
      continue;
    }
    const ip = host && IP_TOKEN_RE.test(host) ? host : null;
    hops.push({
      ttl,
      ip,
      hostname: ip ? null : host ?? null,
      rttsMs: [Number(rtt)],
      probes: 1,
    });
  }
  return hops;
}

async function findTraceroute(): Promise<string | null> {
  for (const cmd of ["traceroute", "traceroute6"]) {
    try {
      await execFileAsync("which", [cmd]);
      return cmd;
    } catch {
      /* next */
    }
  }
  return null;
}

export async function runTraceroute(
  target: string,
  probes = 5,
  maxHops = 30,
): Promise<{ hops: ParsedHop[]; mode: "live" | "mock" }> {
  const cmd = await findTraceroute();
  if (cmd) {
    try {
      const { stdout } = await execFileAsync(
        cmd,
        ["-n", "-q", String(probes), "-m", String(maxHops), "-w", "2", target],
        { timeout: 120_000, maxBuffer: 2 * 1024 * 1024 },
      );
      const hops = parseTracerouteOutput(stdout, probes);
      if (hops.length > 0) return { hops, mode: "live" };
    } catch (err) {
      const partial = (err as { stdout?: string }).stdout;
      if (partial) {
        const hops = parseTracerouteOutput(partial, probes);
        if (hops.length > 0) return { hops, mode: "live" };
      }
    }
  }
  try {
    const { stdout } = await execFileAsync(
      "tracepath",
      ["-n", target],
      { timeout: 120_000, maxBuffer: 2 * 1024 * 1024 },
    );
    const hops = parseTracepathOutput(stdout);
    if (hops.length > 0) return { hops, mode: "live" };
  } catch {
    /* mock fallback */
  }
  return { hops: mockRoute(target), mode: "mock" };
}

export async function resolveTarget(target: string): Promise<string | null> {
  try {
    if (IP_TOKEN_RE.test(target)) return target;
    const records = await dns.lookup(target);
    return records.address;
  } catch {
    return null;
  }
}

/** Realistic demo routes when ICMP/traceroute is unavailable. */
function mockRoute(target: string): ParsedHop[] {
  const key = target.toLowerCase().replace(/^www\./, "");
  const routes: Record<string, ParsedHop[]> = {
    "google.com": [
      hop(1, "192.168.1.1", "home-gateway.local", [1.1, 1.0, 1.2]),
      hop(2, "24.7.128.1", "isp-edge.net", [9.2, 8.8, 9.0]),
      hop(3, "4.69.140.94", "backbone.level3.net", [42.0, 41.5, 42.2]),
      hop(4, "142.250.72.14", "lga-in-f14.1e100.net", [18.5, 18.2, 18.8]),
    ],
    "github.com": [
      hop(1, "192.168.1.1", "home-gateway.local", [1.0, 1.1]),
      hop(2, "24.7.128.1", "isp-edge.net", [10.0, 9.8]),
      hop(3, "151.101.1.67", "github.map.fastly.net", [14.2, 14.0, 14.5]),
    ],
    "bbc.co.uk": [
      hop(1, "10.0.0.1", "office-gw.local", [0.9, 1.0]),
      hop(2, "24.7.128.1", "isp-edge.net", [11.0, 10.5]),
      hop(3, "4.69.219.94", "nyc-backbone.net", [78.0, 77.5]),
      hop(4, "151.101.65.67", "bbc.map.fastly.net", [95.0, 94.2]),
    ],
    "tokyo.ac.jp": [
      hop(1, "192.168.1.1", "home-gateway.local", [1.2, 1.1]),
      hop(2, "24.7.128.1", "isp-edge.net", [9.5, 9.8]),
      hop(3, "4.15.180.50", "atl-backbone.net", [85.0, 84.5]),
      hop(4, "133.11.0.1", "tokyo.ac.jp", [168.0, 170.0, 165.0]),
    ],
    "1.1.1.1": [
      hop(1, "192.168.1.1", "home-gateway.local", [1.0]),
      hop(2, "24.7.128.1", "isp-edge.net", [8.5]),
      hop(3, "104.16.248.249", "one.one.one.one", [14.0]),
      hop(4, "1.1.1.1", "one.one.one.one", [15.0]),
    ],
    "8.8.8.8": [
      hop(1, "192.168.1.1", "home-gateway.local", [1.0]),
      hop(2, "24.7.128.1", "isp-edge.net", [9.0]),
      hop(4, "8.8.8.8", "dns.google", [20.0]),
    ],
  };
  if (routes[key]) return routes[key];
  return [
    hop(1, "192.168.1.1", "home-gateway.local", [1.0, 1.1, 1.0]),
    hop(2, "24.7.128.1", "isp-edge.example.net", [10.0, 9.5, 10.2]),
    hop(3, "4.69.140.94", "backbone.example.net", [45.0, 44.0, 46.0]),
    hop(4, "8.8.8.8", target, [22.0, 21.5, 22.5]),
  ];
}

function hop(
  ttl: number,
  ip: string,
  hostname: string,
  rttsMs: number[],
): ParsedHop {
  return { ttl, ip, hostname, rttsMs, probes: Math.max(3, rttsMs.length) };
}

/** Static geo for mock IPs (server-side enrichment when ip-api skipped in mock). */
export const MOCK_GEO: Record<
  string,
  Omit<import("./types").GeoLocation, "isPrivate">
> = {
  "24.7.128.1": geo(37.34, -121.89, "San Jose", "United States", "Comcast", "AS7922"),
  "4.69.140.94": geo(39.04, -77.49, "Ashburn", "United States", "Level 3", "AS3356"),
  "4.69.219.94": geo(40.71, -74.01, "New York", "United States", "Level 3", "AS3356"),
  "4.15.180.50": geo(33.75, -84.39, "Atlanta", "United States", "Level 3", "AS3356"),
  "142.250.72.14": geo(37.42, -122.08, "Mountain View", "United States", "Google", "AS15169"),
  "151.101.1.67": geo(37.78, -122.41, "San Francisco", "United States", "Fastly", "AS54113"),
  "151.101.65.67": geo(51.51, -0.13, "London", "United Kingdom", "Fastly", "AS54113"),
  "104.16.248.249": geo(37.77, -122.39, "San Francisco", "United States", "Cloudflare", "AS13335"),
  "1.1.1.1": geo(-33.87, 151.21, "Sydney", "Australia", "Cloudflare", "AS13335"),
  "8.8.8.8": geo(37.39, -122.08, "Mountain View", "United States", "Google", "AS15169"),
  "133.11.0.1": geo(35.68, 139.76, "Tokyo", "Japan", "UTokyo", "AS2907"),
};

function geo(
  lat: number,
  lon: number,
  city: string,
  country: string,
  isp: string,
  asn: string,
) {
  return {
    lat,
    lon,
    city,
    country,
    countryCode: null,
    isp,
    org: isp,
    asn,
    isPrivate: false,
  };
}
