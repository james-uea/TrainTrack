import { describe, expect, it } from "vitest";
import type { TrainPosition } from "../api/client";
import { fractionAt, placeTrain } from "./motion";
import { makeSegment, pointAlong } from "./segments";

const train = (changes: Partial<TrainPosition> = {}): TrainPosition => ({
  rid: "R1",
  headcode: "1A01",
  toc: "LE",
  lat: 52.6,
  lon: 1.3,
  bearing: 90,
  state: "running",
  confidence: "high",
  delay: 0,
  from_tiploc: "AAA",
  to_tiploc: "BBB",
  fraction: 0.25,
  left: "2026-11-21T14:00:00Z",
  due: "2026-11-21T14:10:00Z",
  ...changes,
});

// About 1.4 km along a line of latitude, then 1.1 km north: an L-shaped path
const L = makeSegment([
  [1.3, 52.6],
  [1.32, 52.6],
  [1.32, 52.61],
]);

describe("pointAlong", () => {
  it("follows the corner rather than cutting it", () => {
    const corner = L.cumulative[1] as number;
    const atCorner = pointAlong(L, corner / L.length);
    expect(atCorner.lon).toBeCloseTo(1.32, 6);
    expect(atCorner.lat).toBeCloseTo(52.6, 6);
    const end = pointAlong(L, 1);
    expect([end.lon, end.lat]).toEqual([1.32, 52.61]);
    expect(pointAlong(L, 0.99).bearing).toBeCloseTo(0, 0); // heading north on the last leg
  });
});

describe("fractionAt", () => {
  it("works out progress from when the train left and is due, as the server does", () => {
    expect(fractionAt(train(), Date.parse("2026-11-21T14:05:00Z"))).toBeCloseTo(0.5);
    expect(fractionAt(train(), Date.parse("2026-11-21T14:20:00Z"))).toBe(1); // waits at the end, never overshoots
  });

  it("keeps a held train at the end of its segment", () => {
    expect(fractionAt(train({ state: "held" }), Date.parse("2026-11-21T14:01:00Z"))).toBe(1);
  });
});

describe("placeTrain", () => {
  it("uses the server's point until the segment's path arrives", () => {
    const now = Date.parse("2026-11-21T14:05:00Z");
    expect(placeTrain(train(), now, () => undefined)).toEqual({ lon: 1.3, lat: 52.6, bearing: 90 });
    expect(placeTrain(train(), now, () => L).lon).toBeGreaterThan(1.3);
  });

  it("leaves a dwelling train where the server put it", () => {
    const dwelling = train({ state: "dwelling", to_tiploc: "AAA" });
    expect(placeTrain(dwelling, 0, () => L)).toEqual({ lon: 1.3, lat: 52.6, bearing: 90 });
  });
});

describe("replayStart", () => {
  it("reads ?at= as UTC unless it gives a zone, and ignores nonsense", async () => {
    const { replayStart } = await import("../feed/feed");
    expect(replayStart("?at=2026-11-21T14:30")).toBe(Date.UTC(2026, 10, 21, 14, 30));
    expect(replayStart("?at=2026-11-21T14:30Z")).toBe(Date.UTC(2026, 10, 21, 14, 30));
    expect(replayStart("?at=2026-11-21T14:30+01:00")).toBe(Date.UTC(2026, 10, 21, 13, 30));
    expect(replayStart("?at=soon")).toBeNull();
    expect(replayStart("")).toBeNull();
  });
});
