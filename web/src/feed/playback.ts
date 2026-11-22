// The pieces of replay that don't touch the network: a clock that runs at a chosen speed, and a buffer of stored
// frames that hands out the ones due as the clock passes them
import type { ReplayFrame } from "../api/client";

export type Speed = 1 | 10 | 60;
export const SPEEDS: readonly Speed[] = [1, 10, 60];

/** The moment being replayed: runs at `speed` times real time while playing, stands still while paused. */
export class PlaybackClock {
  private anchorAt: number;
  private anchorReal: number;

  constructor(
    at: number,
    public speed: Speed = 1,
    public playing = true,
    private real: () => number = () => Date.now(),
  ) {
    this.anchorAt = at;
    this.anchorReal = real();
  }

  now(): number {
    return this.anchorAt + (this.playing ? (this.real() - this.anchorReal) * this.speed : 0);
  }

  seek(at: number) {
    this.anchorAt = at;
    this.anchorReal = this.real();
  }

  setSpeed(speed: Speed) {
    this.seek(this.now());
    this.speed = speed;
  }

  setPlaying(playing: boolean) {
    this.seek(this.now());
    this.playing = playing;
  }
}

/**
 * Frames fetched so far, in order, and how far along they've been applied. Frames arrive in chunks that each start
 * with the keyframe before them, so a chunk can repeat frames already held; those are skipped.
 */
export class FrameBuffer {
  private frames: ReplayFrame[] = [];
  private times: number[] = [];
  private next = 0; // the first frame not yet handed out
  /** The end of the last chunk asked for: every stored frame up to here is held. */
  loadedUntil: number | null = null;

  reset() {
    this.frames = [];
    this.times = [];
    this.next = 0;
    this.loadedUntil = null;
  }

  add(frames: ReplayFrame[], end: number) {
    const last = this.times.at(-1) ?? Number.NEGATIVE_INFINITY;
    for (const frame of frames) {
      const at = Date.parse(frame.at);
      if (at <= last) continue;
      this.frames.push(frame);
      this.times.push(at);
    }
    this.loadedUntil = Math.max(this.loadedUntil ?? end, end);
  }

  /** The frames to apply to reach `at`, starting from the last keyframe among them (earlier ones are moot). */
  due(at: number): ReplayFrame[] {
    let end = this.next;
    while (end < this.times.length && (this.times[end] as number) <= at) end++;
    let start = this.next;
    for (let i = end - 1; i >= this.next; i--) {
      if (this.frames[i]?.keyframe) {
        start = i;
        break;
      }
    }
    this.next = end;
    return this.frames.slice(start, end);
  }

  /** When the last frame handed out was for, or null before any. */
  get appliedAt(): number | null {
    return this.next > 0 ? (this.times[this.next - 1] as number) : null;
  }

  /** Whether a frame is held after the ones handed out. */
  get hasMore(): boolean {
    return this.next < this.frames.length;
  }

  get size(): number {
    return this.frames.length;
  }
}
