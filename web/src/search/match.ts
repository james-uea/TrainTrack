import type { Operator, Station, TrainPosition } from "../api/client";

/**
 * Stations for a search, best first: the CRS code exactly, then names starting with the query, then names with a
 * word starting with it, then names containing it. Shorter names win ties, so "Leeds" comes before "Leeds Bradford".
 */
export function matchStations(stations: Station[], query: string, limit = 8): Station[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const scored: [number, Station][] = [];
  for (const station of stations) {
    const name = station.name.toLowerCase();
    const score =
      station.crs.toLowerCase() === q
        ? 0
        : name.startsWith(q)
          ? 1
          : name.split(/[\s(-]+/).some((word) => word.startsWith(q))
            ? 2
            : name.includes(q)
              ? 3
              : -1;
    if (score >= 0) scored.push([score, station]);
  }
  scored.sort(([a, x], [b, y]) => a - b || x.name.length - y.name.length || x.name.localeCompare(y.name));
  return scored.slice(0, limit).map(([, station]) => station);
}

/** Trains whose headcode starts with the query (2C, 1A4, 1A48), in headcode order. */
export function matchTrains(trains: Iterable<TrainPosition>, query: string, limit = 8): TrainPosition[] {
  const q = query.trim().toUpperCase();
  if (!q || q.length > 4) return [];
  const found: TrainPosition[] = [];
  for (const train of trains) if (train.headcode?.startsWith(q)) found.push(train);
  found.sort(
    (a, b) => (a.headcode ?? "").localeCompare(b.headcode ?? "") || (a.toc ?? "").localeCompare(b.toc ?? ""),
  );
  return found.slice(0, limit);
}

/** Operators whose code is the query, or whose name has a word starting with it ("lner", "great", "GW"). */
export function matchOperators(operators: Operator[], query: string, limit = 4): Operator[] {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  return operators
    .filter(
      ({ code, name }) =>
        code.toLowerCase() === q ||
        name
          .toLowerCase()
          .split(/\s+/)
          .some((word) => word.startsWith(q)),
    )
    .sort((a, b) => Number(b.code.toLowerCase() === q) - Number(a.code.toLowerCase() === q))
    .slice(0, limit);
}
