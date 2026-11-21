import { describe, expect, it } from "vitest";
import type { Station, TrainPosition } from "../api/client";
import { matchStations, matchTrains } from "./match";

const station = (crs: string, name: string): Station => ({ crs, name, lon: 0, lat: 0 });
const STATIONS = [
  station("LBA", "Leeds Bradford Airport"),
  station("LDS", "Leeds"),
  station("BDQ", "Bradford Forster Square"),
  station("NWB", "Newbury"),
  station("ALD", "Aldershot"),
];

describe("matchStations", () => {
  it("puts an exact CRS first, then names that start with the query, shortest first", () => {
    expect(matchStations(STATIONS, "lds").map((s) => s.crs)).toEqual(["LDS"]);
    expect(matchStations(STATIONS, "leeds").map((s) => s.crs)).toEqual(["LDS", "LBA"]);
  });

  it("finds a word inside a name before a fragment inside a word", () => {
    expect(matchStations(STATIONS, "brad").map((s) => s.crs)).toEqual(["BDQ", "LBA"]);
    expect(matchStations(STATIONS, "bury").map((s) => s.crs)).toEqual(["NWB"]);
  });

  it("returns nothing for an empty query", () => {
    expect(matchStations(STATIONS, "  ")).toEqual([]);
  });
});

describe("matchTrains", () => {
  const train = (rid: string, headcode: string, toc: string) => ({ rid, headcode, toc }) as TrainPosition;
  const trains = [
    train("a", "1A48", "VT"),
    train("b", "2C10", "SW"),
    train("c", "1A48", "SW"),
    train("d", "1A40", "VT"),
  ];

  it("matches headcode prefixes, case-insensitively", () => {
    expect(matchTrains(trains, "1a4").map((t) => t.rid)).toEqual(["d", "c", "a"]);
  });

  it("ignores queries that can't be a headcode", () => {
    expect(matchTrains(trains, "Leeds")).toEqual([]);
  });
});
