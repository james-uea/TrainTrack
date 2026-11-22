import { describe, expect, it } from "vitest";
import { delayBand } from "./delay";

describe("delayBand", () => {
  it("puts the band edges where the legend says", () => {
    expect([-2, 0, 1, 5, 6, 15, 16].map(delayBand)).toEqual([
      "on_time",
      "on_time",
      "minor",
      "minor",
      "late",
      "late",
      "major",
    ]);
  });

  it("marks a train with no report yet", () => {
    expect(delayBand(null)).toBe("unknown");
  });
});
