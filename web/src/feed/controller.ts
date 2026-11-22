// Switches the map between live and replay, and drives replay's play, pause, speed and seek
import type { TrainStore } from "../trains/store";
import { type FeedStatus, ReplayFeed, startLive } from "./feed";
import type { Speed } from "./playback";

export type Playback = { mode: "live" } | { mode: "replay"; speed: Speed; playing: boolean };

export class FeedController {
  private stopLive: (() => void) | null = null;
  private replay: ReplayFeed | null = null;
  playback: Playback = { mode: "live" };

  constructor(
    private store: TrainStore,
    private onStatus: (status: FeedStatus) => void,
    private onPlayback: (playback: Playback) => void = () => {},
  ) {}

  live() {
    this.replay?.stop();
    this.replay = null;
    if (!this.stopLive) {
      this.store.clear();
      this.onStatus("connecting");
      this.stopLive = startLive(this.store, this.onStatus);
    }
    this.set({ mode: "live" });
  }

  /** Replay from `at`, keeping the current speed and play state unless given. */
  seek(at: number, speed?: Speed, playing?: boolean) {
    const current = this.playback.mode === "replay" ? this.playback : { speed: 1 as Speed, playing: true };
    const next = {
      mode: "replay" as const,
      speed: speed ?? current.speed,
      playing: playing ?? current.playing,
    };
    this.stopLive?.();
    this.stopLive = null;
    if (this.replay) {
      this.replay.setSpeed(next.speed);
      this.replay.setPlaying(next.playing);
      this.replay.seek(at);
    } else {
      this.onStatus("connecting");
      this.replay = new ReplayFeed(this.store, this.onStatus, at, next.speed, next.playing);
    }
    this.set(next);
  }

  setSpeed(speed: Speed) {
    if (this.playback.mode !== "replay" || !this.replay) return;
    this.replay.setSpeed(speed);
    this.set({ ...this.playback, speed });
  }

  setPlaying(playing: boolean) {
    if (this.playback.mode !== "replay" || !this.replay) {
      // Pausing live freezes the moment on screen and carries on as a replay from there
      if (!playing) this.seek(this.store.clock.now(), 1, false);
      return;
    }
    this.replay.setPlaying(playing);
    this.set({ ...this.playback, playing });
  }

  /** The moment the map shows. */
  now(): number {
    return this.store.clock.now();
  }

  stop() {
    this.stopLive?.();
    this.replay?.stop();
    this.stopLive = null;
    this.replay = null;
  }

  private set(playback: Playback) {
    this.playback = playback;
    this.onPlayback(playback);
  }
}
