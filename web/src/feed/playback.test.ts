import { describe, expect, it } from "vitest";
import type { ReplayFrame } from "../api/client";
import { prefetchMs } from "./feed";
import { FrameBuffer, PlaybackClock } from "./playback";

const T0 = Date.UTC(2026, 10, 21, 14, 0);

function frame(seconds: number, keyframe = false): ReplayFrame {
  return {
    at: new Date(T0 + seconds * 1000).toISOString(),
    keyframe,
    source: "recorded",
    active: 0,
    trains: [],
    removed: [],
  };
}

describe("PlaybackClock", () => {
  it("runs at its speed, stands still when paused, and keeps its place across changes", () => {
    let real = 0;
    const clock = new PlaybackClock(T0, 1, true, () => real);
    real = 1000;
    expect(clock.now()).toBe(T0 + 1000);
    clock.setSpeed(60);
    real = 2000;
    expect(clock.now()).toBe(T0 + 1000 + 60_000);
    clock.setPlaying(false);
    real = 10_000;
    expect(clock.now()).toBe(T0 + 61_000);
    clock.seek(T0);
    clock.setPlaying(true);
    real = 10_500;
    expect(clock.now()).toBe(T0 + 30_000);
  });
});

describe("FrameBuffer", () => {
  it("hands out frames as the clock passes them, from the last keyframe due", () => {
    const buffer = new FrameBuffer();
    buffer.add([frame(0, true), frame(5), frame(10), frame(15, true), frame(20)], T0 + 600_000);
    expect(buffer.due(T0 - 1)).toEqual([]);
    expect(buffer.due(T0 + 7_000).map((f) => f.at)).toEqual([frame(0).at, frame(5).at]);
    // A jump past a keyframe starts from it
    expect(buffer.due(T0 + 22_000).map((f) => f.at)).toEqual([frame(15).at, frame(20).at]);
    expect(buffer.appliedAt).toBe(T0 + 20_000);
    expect(buffer.hasMore).toBe(false);
  });

  it("skips frames a later chunk repeats", () => {
    const buffer = new FrameBuffer();
    buffer.add([frame(0, true), frame(5)], T0 + 5_000);
    buffer.add([frame(0, true), frame(5), frame(10)], T0 + 10_000);
    expect(buffer.size).toBe(3);
    expect(buffer.loadedUntil).toBe(T0 + 10_000);
  });
});

describe("prefetchMs", () => {
  it("looks further ahead the faster the replay", () => {
    expect(prefetchMs(1)).toBe(60_000);
    expect(prefetchMs(60)).toBe(1_200_000);
  });
});
