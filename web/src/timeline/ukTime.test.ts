import { describe, expect, it } from "vitest";
import { nextUkDay, ukDay, ukDayStart } from "./ukTime";

describe("UK days", () => {
  it("start at UK midnight in winter and in summer", () => {
    expect(ukDayStart("2026-11-21")).toBe(Date.UTC(2026, 10, 21));
    expect(ukDayStart("2026-07-01")).toBe(Date.UTC(2026, 5, 30, 23));
  });

  it("are 23 and 25 hours long when the clocks change", () => {
    expect(ukDayStart("2026-03-30") - ukDayStart("2026-03-29")).toBe(23 * 3_600_000);
    expect(ukDayStart("2026-10-26") - ukDayStart("2026-10-25")).toBe(25 * 3_600_000);
    expect(nextUkDay("2026-10-25")).toBe("2026-10-26");
  });

  it("name the UK date of a moment", () => {
    expect(ukDay(Date.UTC(2026, 5, 30, 23, 30))).toBe("2026-07-01");
    expect(ukDay(Date.UTC(2026, 10, 21, 23, 59))).toBe("2026-11-21");
  });
});
