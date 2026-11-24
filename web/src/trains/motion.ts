// Where a train is drawn at a given moment. The server sends each train's segment and when it left and is due;
// in between updates the browser moves it along the segment's track path itself
import type { TrainPosition } from "../api/client";
import { pointAlong, type Segment, segmentKey } from "./segments";

export interface Placement {
  lon: number;
  lat: number;
  bearing: number | null;
}

/** How far along its segment a moving train is at `nowMs`: the server's own formula, so the two agree. */
export function fractionAt(train: TrainPosition, nowMs: number): number {
  if (train.state === "held") return 1;
  if (!train.left || !train.due) return train.fraction;
  const left = Date.parse(train.left);
  const due = Date.parse(train.due);
  if (due <= left) return 1;
  return Math.min(Math.max((nowMs - left) / (due - left), 0), 1);
}

export function isMoving(train: TrainPosition): boolean {
  return (train.state === "running" || train.state === "held") && train.from_tiploc !== train.to_tiploc;
}

export function placeTrain(
  train: TrainPosition,
  nowMs: number,
  segment: (key: string) => Segment | undefined,
): Placement {
  if (isMoving(train)) {
    const path = segment(segmentKey(train.from_tiploc, train.to_tiploc));
    if (path) return pointAlong(path, fractionAt(train, nowMs));
  }
  return { lon: train.lon, lat: train.lat, bearing: train.bearing };
}

// Trains ease toward where the server puts them rather than jumping there. A correction backwards (a later
// forecast, or a report showing the train hadn't got as far) is the "rubber banding" people notice, so a drawn
// train never goes back faster than MAX_BACK_MPS. On the 24 Nov 07:00-09:00 replay this took pull-backs of over
// 50 m from 9.7 per train-hour to none, and forward jumps from 7.6 to none (.memory/rubber-banding-bench.md)
const EASE_SECONDS = 20;
const MAX_BACK_MPS = 3;
const MAX_FORWARD_MPS = 60;
// After a longer gap (a hidden tab, a seek in a replay) a train goes straight to where it should be
const SNAP_AFTER_MS = 10_000;

type SegmentSource = (key: string) => Segment | undefined;

/** A point on the network: `distance` metres along the segment between two TIPLOCs (the same one at a stop). */
interface Spot {
  from: string;
  to: string;
  distance: number;
}

function lengthOf(from: string, to: string, segment: SegmentSource): number | undefined {
  return from === to ? 0 : segment(segmentKey(from, to))?.length;
}

/** Where the server puts the train, or null while its segment's path hasn't arrived. */
function targetSpot(train: TrainPosition, nowMs: number, segment: SegmentSource): Spot | null {
  if (!isMoving(train)) return { from: train.from_tiploc, to: train.from_tiploc, distance: 0 };
  const length = lengthOf(train.from_tiploc, train.to_tiploc, segment);
  if (length === undefined) return null;
  return { from: train.from_tiploc, to: train.to_tiploc, distance: fractionAt(train, nowMs) * length };
}

/**
 * Two spots as distances along one stretch of track, when they're on the same segment or ones that join: the
 * pieces it's made of, with their lengths, and each spot's distance from its start. Null for anything further apart.
 */
function stretch(a: Spot, b: Spot, segment: SegmentSource) {
  const la = lengthOf(a.from, a.to, segment);
  const lb = lengthOf(b.from, b.to, segment);
  if (la === undefined || lb === undefined) return null;
  const pieces = (first: Spot, second?: Spot): [Spot, number][] =>
    second
      ? [
          [first, first === a ? la : lb],
          [second, second === a ? la : lb],
        ]
      : [[first, la]];
  if (a.from === b.from && a.to === b.to) return { pieces: pieces(a), a: a.distance, b: b.distance };
  if (a.to === b.from) return { pieces: pieces(a, b), a: a.distance, b: la + b.distance };
  if (b.to === a.from) return { pieces: pieces(b, a), a: lb + a.distance, b: b.distance };
  return null;
}

function spotAt(pieces: [Spot, number][], offset: number): Spot {
  let rest = Math.max(offset, 0);
  for (const [index, [piece, length]] of pieces.entries()) {
    if (rest <= length || index === pieces.length - 1) {
      return { from: piece.from, to: piece.to, distance: Math.min(rest, length) };
    }
    rest -= length;
  }
  return (pieces[0] as [Spot, number])[0];
}

/** Remembers where each train was last drawn and moves it toward the server's position at a believable speed. */
export class Smoother {
  private drawn = new Map<string, { spot: Spot; atMs: number }>();

  place(train: TrainPosition, nowMs: number, segment: SegmentSource): Placement {
    const target = targetSpot(train, nowMs, segment);
    if (!target) {
      this.drawn.delete(train.rid);
      return placeTrain(train, nowMs, segment);
    }
    const previous = this.drawn.get(train.rid);
    const elapsed = previous ? nowMs - previous.atMs : -1;
    const span =
      previous && elapsed >= 0 && elapsed <= SNAP_AFTER_MS ? stretch(previous.spot, target, segment) : null;
    let spot = target;
    if (span) {
      const seconds = elapsed / 1000;
      const eased = (span.b - span.a) * (1 - Math.exp(-seconds / EASE_SECONDS));
      spot = spotAt(
        span.pieces,
        span.a + Math.min(Math.max(eased, -MAX_BACK_MPS * seconds), MAX_FORWARD_MPS * seconds),
      );
    }
    this.drawn.set(train.rid, { spot, atMs: nowMs });

    if (spot.from !== spot.to) {
      const path = segment(segmentKey(spot.from, spot.to));
      if (path) return pointAlong(path, path.length > 0 ? spot.distance / path.length : 0);
    } else if (target.from !== target.to) {
      // Standing at one end of the segment the server has the train on
      const path = segment(segmentKey(target.from, target.to));
      if (path) return pointAlong(path, spot.from === target.from ? 0 : 1);
    }
    return placeTrain(train, nowMs, segment);
  }

  /** Forget trains that are no longer on the map. */
  keepOnly(rids: Set<string>) {
    for (const rid of this.drawn.keys()) if (!rids.has(rid)) this.drawn.delete(rid);
  }
}
