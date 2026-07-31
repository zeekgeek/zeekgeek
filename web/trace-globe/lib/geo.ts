const EARTH_RADIUS_KM = 6371;

/** Great-circle distance between two lat/lon points in kilometers. */
export function haversineKm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return EARTH_RADIUS_KM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Sum of great-circle segments along geolocated hops. */
export function totalRouteDistanceKm(
  hops: { geo: { lat: number; lon: number } | null }[],
): number {
  const points = hops
    .map((h) => h.geo)
    .filter((g): g is { lat: number; lon: number } => g !== null);
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    total += haversineKm(
      points[i - 1].lat,
      points[i - 1].lon,
      points[i].lat,
      points[i].lon,
    );
  }
  return Math.round(total);
}

/** Lat/lon → unit vector on a sphere of given radius (Three.js Y-up). */
export function latLonToVector3(lat: number, lon: number, radius = 1): [number, number, number] {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lon + 180) * (Math.PI / 180);
  const x = -(radius * Math.sin(phi) * Math.cos(theta));
  const z = radius * Math.sin(phi) * Math.sin(theta);
  const y = radius * Math.cos(phi);
  return [x, y, z];
}

/** Arc color from average RTT (ms). */
export function latencyColor(ms: number | null): string {
  if (ms === null) return "#94a3b8";
  if (ms < 50) return "#4ade80";
  if (ms <= 150) return "#fbbf24";
  return "#f87171";
}
