import { describe, expect, it } from "vitest";
import type { TrainStop } from "../api/client";
import { lastPassed, stopTime } from "./stopTimes";

const stop = (fields: Partial<TrainStop>): TrainStop => ({
  tiploc: "X",
  name: null,
  crs: null,
  is_call: true,
  public: true,
  planned_arrival: null,
  planned_departure: null,
  planned_pass: null,
  forecast_arrival: null,
  forecast_departure: null,
  forecast_pass: null,
  actual_arrival: null,
  actual_departure: null,
  actual_pass: null,
  platform: null,
  platform_confirmed: false,
  cancelled: false,
  ...fields,
});

describe("stopTime", () => {
  it("compares the departure at an intermediate call, and the arrival where the train ends", () => {
    const call = stop({
      planned_arrival: "2026-11-21T14:00:00Z",
      planned_departure: "2026-11-21T14:02:00Z",
      actual_arrival: "2026-11-21T14:09:00Z",
      forecast_departure: "2026-11-21T14:10:00Z",
    });
    expect(stopTime(call, false)).toMatchObject({
      event: "departure",
      expected: "2026-11-21T14:10:00Z",
      late: 8,
    });
    expect(stopTime(call, true)).toMatchObject({ event: "arrival", actual: "2026-11-21T14:09:00Z", late: 9 });
  });

  it("drops the forecast once the train has reported, and uses pass times at passing points", () => {
    const pass = stop({
      is_call: false,
      planned_pass: "2026-11-21T14:00:00Z",
      forecast_pass: "2026-11-21T14:05:00Z",
      actual_pass: "2026-11-21T13:59:30Z",
    });
    expect(stopTime(pass, false)).toEqual({
      event: "pass",
      planned: "2026-11-21T14:00:00Z",
      expected: null,
      actual: "2026-11-21T13:59:30Z",
      late: 0, // half a minute early rounds to on time
    });
  });
});

describe("lastPassed", () => {
  const stops = [
    stop({ tiploc: "A", actual_departure: "2026-11-21T14:00:00Z" }),
    stop({ tiploc: "B", actual_pass: "2026-11-21T14:05:00Z" }),
    stop({ tiploc: "C" }),
  ];
  it("follows the position's segment, which knows about trains still to report", () => {
    expect(lastPassed(stops, "C")).toBe(2);
  });
  it("falls back to the last report", () => {
    expect(lastPassed(stops, null)).toBe(1);
    expect(lastPassed(stops, "NOWHERE")).toBe(1);
  });
});
