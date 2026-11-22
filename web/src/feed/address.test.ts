import { describe, expect, it } from "vitest";
import { readPlayback, readView, viewHash, writePlayback } from "./address";

const AT = Date.UTC(2026, 10, 12, 7, 40);

describe("the address", () => {
  it("round-trips a paused replay at 10x", () => {
    const url = writePlayback(new URL("http://x/?train=R1"), { at: AT + 450, speed: 10, playing: false });
    expect(url.search).toBe("?train=R1&at=2026-11-12T07%3A40%3A00Z&speed=10&paused=1");
    expect(readPlayback(url.search)).toEqual({ at: AT, speed: 10, playing: false });
  });

  it("leaves live addresses clean and ignores speeds it doesn't offer", () => {
    const url = writePlayback(new URL("http://x/?at=2026-11-12T07:40Z&speed=10&train=R1"), {
      at: null,
      speed: 1,
      playing: true,
    });
    expect(url.search).toBe("?train=R1");
    expect(readPlayback("?at=2026-11-12T07:40Z&speed=7")).toEqual({ at: AT, speed: 1, playing: true });
  });

  it("keeps the map view in the hash", () => {
    const hash = viewHash({ zoom: 11, latitude: 51.46423, longitude: -0.17041 });
    expect(hash).toBe("#map=11.00/51.4642/-0.1704");
    expect(readView(hash)).toEqual({ zoom: 11, latitude: 51.4642, longitude: -0.1704 });
    expect(readView("#nothing")).toBeNull();
  });
});
