// Track paths between pairs of TIPLOCs, fetched once and kept, with what's needed to find a point along them
import CheapRuler from "cheap-ruler";

export type LonLat = [number, number];

export interface Segment {
  coords: LonLat[];
  cumulative: Float64Array; // metres from the start to each point
  length: number;
  ruler: CheapRuler;
}

export const segmentKey = (from: string, to: string) => `${from}>${to}`;

export function makeSegment(coords: LonLat[]): Segment {
  const lats = coords.map(([, lat]) => lat);
  const ruler = new CheapRuler((Math.min(...lats) + Math.max(...lats)) / 2, "meters");
  const cumulative = new Float64Array(coords.length);
  for (let i = 1; i < coords.length; i++) {
    cumulative[i] = (cumulative[i - 1] ?? 0) + ruler.distance(coords[i - 1] as LonLat, coords[i] as LonLat);
  }
  return { coords, cumulative, length: cumulative[coords.length - 1] ?? 0, ruler };
}

/** The point `fraction` of the way along a segment, and the bearing of travel there (degrees from north). */
export function pointAlong(
  segment: Segment,
  fraction: number,
): { lon: number; lat: number; bearing: number } {
  const { coords, cumulative, length } = segment;
  const distance = Math.min(Math.max(fraction, 0), 1) * length;
  // The last point at or before `distance`
  let low = 0;
  let high = coords.length - 1;
  while (low < high - 1) {
    const mid = (low + high) >> 1;
    if ((cumulative[mid] ?? 0) <= distance) low = mid;
    else high = mid;
  }
  const a = coords[low] as LonLat;
  const b = coords[Math.min(low + 1, coords.length - 1)] as LonLat;
  const span = (cumulative[low + 1] ?? 0) - (cumulative[low] ?? 0);
  const t = span > 0 ? (distance - (cumulative[low] ?? 0)) / span : 0;
  return {
    lon: a[0] + (b[0] - a[0]) * t,
    lat: a[1] + (b[1] - a[1]) * t,
    bearing: a === b ? 0 : segment.ruler.bearing(a, b),
  };
}

const BATCH = 200;

/** Fetches segments on demand, a batch at a time, and keeps them. */
export class SegmentCache {
  private segments = new Map<string, Segment>();
  private pending = new Set<string>();
  private missing = new Set<string>(); // the server couldn't place these: don't ask again

  constructor(private fetchBatch: (keys: string[]) => Promise<Record<string, LonLat[]>>) {}

  get(key: string): Segment | undefined {
    return this.segments.get(key);
  }

  get size(): number {
    return this.segments.size;
  }

  /** Start fetching any of `keys` not already here or on the way. */
  want(keys: Iterable<string>) {
    const needed = [...new Set(keys)].filter(
      (key) => !this.segments.has(key) && !this.pending.has(key) && !this.missing.has(key),
    );
    for (let i = 0; i < needed.length; i += BATCH) {
      const batch = needed.slice(i, i + BATCH);
      for (const key of batch) this.pending.add(key);
      this.fetchBatch(batch)
        .then((found) => {
          for (const key of batch) {
            const coords = found[key];
            if (coords && coords.length >= 2) this.segments.set(key, makeSegment(coords));
            else this.missing.add(key);
          }
        })
        .catch(() => undefined) // asked again next time
        .finally(() => {
          for (const key of batch) this.pending.delete(key);
        });
    }
  }
}
