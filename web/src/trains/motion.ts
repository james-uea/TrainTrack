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
