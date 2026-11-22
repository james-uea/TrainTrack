// Keeps a TrainStore current, live or replaying the past. Live: one gzipped snapshot over HTTP, then each tick's
// changes over server-sent events. Replay: stored frames fetched in chunks ahead of a playback clock
import { api, type PositionChanges, type PositionsResponse } from "../api/client";
import type { TrainStore } from "../trains/store";
import { FrameBuffer, PlaybackClock, type Speed } from "./playback";

// "estimated": replaying a moment with no stored frames, so positions are computed by the server from today's data
export type FeedStatus = "connecting" | "live" | "reconnecting" | "estimated";

const CHUNK_MS = 10 * 60_000; // frames fetched per request (the API allows up to 15 minutes)
const APPLY_EVERY_MS = 200;
// Frames further apart than this leave a gap (the API's FRAME_GAP)
const GAP_MS = 30_000;
const ESTIMATE_EVERY_MS = 3000; // real time between computed positions while in a gap

/** The moment `?at=` in the address asks for (an ISO time, UTC if no zone is given), if any. */
export function replayStart(search = window.location.search): number | null {
  // A "+" in an address reads back as a space, so "+01:00" arrives as " 01:00"
  const at = new URLSearchParams(search).get("at")?.trim().replace(" ", "+");
  if (!at) return null;
  const ms = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at : `${at}Z`);
  return Number.isNaN(ms) ? null : ms;
}

/** How far ahead of the playhead frames are fetched: enough for 20 s of real time, and at least a minute. */
export function prefetchMs(speed: Speed): number {
  return Math.max(60_000, speed * 20_000);
}

export function startLive(store: TrainStore, onStatus: (status: FeedStatus) => void): () => void {
  let source: EventSource | null = null;
  let stopped = false;

  (async () => {
    const { data } = await api.GET("/api/positions");
    if (stopped) return;
    if (data) store.loadSnapshot(data);
    source = new EventSource(`/api/stream${data ? `?since=${data.version}` : ""}`);
    source.addEventListener("snapshot", (event) => {
      store.loadSnapshot(JSON.parse((event as MessageEvent).data) as PositionsResponse);
      onStatus("live");
    });
    source.addEventListener("changes", (event) => {
      store.applyChanges(JSON.parse((event as MessageEvent).data) as PositionChanges);
      onStatus("live");
    });
    source.onopen = () => onStatus("live");
    // The browser reconnects by itself, sending the last version it had
    source.onerror = () => onStatus("reconnecting");
  })().catch(() => onStatus("reconnecting"));

  return () => {
    stopped = true;
    source?.close();
  };
}

/**
 * Replays stored frames. The playback clock drives the store's clock, so trains glide between frames exactly as
 * they do live. Where nothing was stored, the server computes positions every few seconds instead.
 */
export class ReplayFeed {
  readonly clock: PlaybackClock;
  private buffer = new FrameBuffer();
  private timer = 0;
  private generation = 0; // bumped on each seek, so a late chunk for an old position is dropped
  private fetching = false;
  private lastEstimate = 0;
  private status: FeedStatus = "connecting";

  constructor(
    private store: TrainStore,
    private onStatus: (status: FeedStatus) => void,
    at: number,
    speed: Speed = 1,
    playing = true,
  ) {
    this.clock = new PlaybackClock(at, speed, playing);
    store.clear();
    store.clock.follow(() => this.clock.now());
    this.seek(at);
    this.timer = window.setInterval(() => this.tick(), APPLY_EVERY_MS);
  }

  seek(at: number) {
    this.generation++;
    this.buffer.reset();
    this.fetching = false;
    this.lastEstimate = 0;
    this.clock.seek(at);
    this.fetchChunk(at);
  }

  setSpeed(speed: Speed) {
    this.clock.setSpeed(speed);
  }

  setPlaying(playing: boolean) {
    this.clock.setPlaying(playing);
  }

  stop() {
    this.generation++;
    clearInterval(this.timer);
    this.store.clock.follow(null);
  }

  private setStatus(status: FeedStatus) {
    if (status === this.status) return;
    this.status = status;
    this.onStatus(status);
  }

  private async fetchChunk(start: number) {
    const generation = this.generation;
    this.fetching = true;
    const end = start + CHUNK_MS;
    try {
      const { data } = await api.GET("/api/replay", {
        params: { query: { start: new Date(start).toISOString(), end: new Date(end).toISOString() } },
      });
      if (generation !== this.generation) return;
      if (!data) throw new Error("No replay data");
      this.buffer.add(data.frames, end);
      this.fetching = false;
      this.tick();
    } catch {
      if (generation !== this.generation) return;
      this.fetching = false;
      this.setStatus("reconnecting");
    }
  }

  private tick() {
    const now = this.clock.now();
    const frames = this.buffer.due(now);
    if (frames.length) {
      this.store.applyFrames(frames);
      this.setStatus("live");
    }

    const loaded = this.buffer.loadedUntil;
    if (loaded !== null && !this.fetching && loaded - now < prefetchMs(this.clock.speed))
      this.fetchChunk(loaded);

    // Nothing stored here: no frame reached yet (or the last is stale) and none waiting before the next chunk
    const applied = this.buffer.appliedAt;
    const inGap = loaded !== null && (applied === null || now - applied > GAP_MS) && !this.buffer.hasMore;
    if (inGap && Date.now() - this.lastEstimate > ESTIMATE_EVERY_MS) {
      this.lastEstimate = Date.now();
      this.estimate(now);
    }
  }

  private async estimate(at: number) {
    const generation = this.generation;
    try {
      const { data } = await api.GET("/api/positions", {
        params: { query: { at: new Date(at).toISOString() } },
      });
      if (generation !== this.generation || !data) return;
      // A frame may have arrived meanwhile; stored frames win
      const applied = this.buffer.appliedAt;
      if (applied !== null && at - applied <= GAP_MS) return;
      this.store.loadSnapshot(data);
      this.setStatus("estimated");
    } catch {
      this.setStatus("reconnecting");
    }
  }
}
