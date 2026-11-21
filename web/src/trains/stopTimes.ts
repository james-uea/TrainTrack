import type { TrainStop } from "../api/client";

export interface StopTime {
  event: "arrival" | "departure" | "pass";
  planned: string | null;
  expected: string | null; // a forecast, only while the train hasn't reported here
  actual: string | null;
  late: number | null; // minutes after planned, from the actual time or else the forecast
}

const MINUTE = 60_000;

/**
 * The one time a stop list shows for a stop: its departure, or its arrival where the train ends, or the pass time at a
 * passing point. Planned, forecast and actual are always the same event, so they compare.
 */
export function stopTime(stop: TrainStop, last: boolean): StopTime {
  const event =
    stop.planned_pass && !stop.is_call ? "pass" : last || !stop.planned_departure ? "arrival" : "departure";
  const planned = stop[`planned_${event}`];
  const actual = stop[`actual_${event}`];
  const expected = actual ? null : stop[`forecast_${event}`];
  const compare = actual ?? expected;
  const late =
    planned && compare ? Math.round((Date.parse(compare) - Date.parse(planned)) / MINUTE) || 0 : null; // no -0
  return { event, planned, expected, actual, late };
}

/** The index of the last stop the train has left or passed: from its position if it has one, else its reports. */
export function lastPassed(stops: TrainStop[], fromTiploc: string | null): number {
  if (fromTiploc) {
    const at = stops.findIndex((stop) => stop.tiploc === fromTiploc);
    if (at !== -1) return at;
  }
  let passed = -1;
  stops.forEach((stop, i) => {
    if (stop.actual_departure || stop.actual_pass || stop.actual_arrival) passed = i;
  });
  return passed;
}
