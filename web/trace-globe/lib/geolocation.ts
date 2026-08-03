import type { GeoLocation } from "./types";

const IP_API_FIELDS =
  "status,query,lat,lon,city,country,countryCode,isp,org,as";

const PRIVATE_RANGES = [
  /^127\./,
  /^10\./,
  /^192\.168\./,
  /^172\.(1[6-9]|2\d|3[01])\./,
  /^169\.254\./,
  /^0\./,
  /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./,
  /^::1$/,
  /^fc00:/i,
  /^fe80:/i,
];

export function isPrivateIp(ip: string): boolean {
  return PRIVATE_RANGES.some((re) => re.test(ip));
}

interface IpApiEntry {
  status?: string;
  query?: string;
  lat?: number;
  lon?: number;
  city?: string;
  country?: string;
  countryCode?: string;
  isp?: string;
  org?: string;
  as?: string;
}

function parseEntry(ip: string, entry: IpApiEntry): GeoLocation | null {
  if (entry.status !== "success" || entry.lat == null || entry.lon == null) {
    return null;
  }
  return {
    lat: entry.lat,
    lon: entry.lon,
    city: entry.city ?? null,
    country: entry.country ?? null,
    countryCode: entry.countryCode ?? null,
    isp: entry.isp ?? null,
    org: entry.org ?? null,
    asn: entry.as ?? null,
    isPrivate: false,
  };
}

/** Fetch caller's public IP geolocation (origin for private hops). */
export async function lookupSelf(): Promise<GeoLocation | null> {
  try {
    const res = await fetch(`http://ip-api.com/json/?fields=${IP_API_FIELDS}`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return null;
    const entry = (await res.json()) as IpApiEntry;
    return parseEntry(entry.query ?? "self", entry);
  } catch {
    return null;
  }
}

/** Batch geolocate public IPs via ip-api.com. */
export async function lookupMany(ips: string[]): Promise<Map<string, GeoLocation>> {
  const results = new Map<string, GeoLocation>();
  const unique = [...new Set(ips.filter((ip) => ip && !isPrivateIp(ip)))];
  if (unique.length === 0) return results;

  // ip-api batch endpoint (max 100)
  try {
    const body = unique.map((query) => ({ query, fields: IP_API_FIELDS }));
    const res = await fetch("http://ip-api.com/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`ip-api batch HTTP ${res.status}`);
    const entries = (await res.json()) as IpApiEntry[];
    for (const entry of entries) {
      const ip = entry.query;
      if (!ip) continue;
      const geo = parseEntry(ip, entry);
      if (geo) results.set(ip, geo);
    }
  } catch {
    // Fall back to sequential lookups
    for (const ip of unique.slice(0, 15)) {
      try {
        const res = await fetch(
          `http://ip-api.com/json/${ip}?fields=${IP_API_FIELDS}`,
        );
        if (!res.ok) continue;
        const entry = (await res.json()) as IpApiEntry;
        const geo = parseEntry(ip, entry);
        if (geo) results.set(ip, geo);
      } catch {
        /* skip */
      }
    }
  }
  return results;
}

/** Build geo for a hop, substituting internal label for private IPs. */
export function geoForHop(
  ip: string | null,
  geoMap: Map<string, GeoLocation>,
  origin: GeoLocation | null,
): GeoLocation | null {
  if (!ip) return null;
  if (isPrivateIp(ip)) {
    if (origin) {
      return {
        ...origin,
        city: origin.city ?? "Local",
        country: origin.country ?? "Internal",
        isPrivate: true,
        isInternal: true,
      };
    }
    return {
      lat: 0,
      lon: 0,
      city: "Internal Network",
      country: null,
      countryCode: null,
      isp: "Private LAN",
      org: null,
      asn: null,
      isPrivate: true,
      isInternal: true,
    };
  }
  return geoMap.get(ip) ?? null;
}

export function formatLocation(geo: GeoLocation | null): string {
  if (!geo) return "Unknown";
  if (geo.isInternal) return geo.city ?? "Internal Network";
  if (geo.city && geo.country) return `${geo.city}, ${geo.country}`;
  return geo.country ?? geo.city ?? "Unknown";
}

export function formatIsp(geo: GeoLocation | null): string {
  if (!geo) return "—";
  const parts = [geo.isp, geo.asn].filter(Boolean);
  return parts.length ? parts.join(" · ") : "—";
}
