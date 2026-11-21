// Keeps a TrainStore current: one gzipped snapshot over HTTP, then each tick's changes over server-sent events
import { api, type PositionChanges, type PositionsResponse } from "../api/client";
import type { TrainStore } from "../trains/store";

export type FeedStatus = "connecting" | "live" | "reconnecting";

const REPLAY_POLL_MS = 5000;

/** The moment `?at=` in the address asks for (an ISO time, UTC if no zone is given), if any. */
export function replayStart(search = window.location.search): number | null {
  // A "+" in an address reads back as a space, so "+01:00" arrives as " 01:00"
  const at = new URLSearchParams(search).get("at")?.trim().replace(" ", "+");
  if (!at) return null;
  const ms = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at : `${at}Z`);
  return Number.isNaN(ms) ? null : ms;
}

/**
 * Replays the past from `start` at 1x: asks for positions a little later every few seconds. Trains still glide in
 * between, because each position says when the train left its last stop and is due at the next.
 */
function startReplay(store: TrainStore, start: number, onStatus: (status: FeedStatus) => void): () => void {
  const began = Date.now();
  let timer = 0;
  let stopped = false;
  const poll = async () => {
    const at = new Date(start + (Date.now() - began)).toISOString();
    try {
      const { data } = await api.GET("/api/positions", { params: { query: { at } } });
      if (stopped) return;
      if (data) store.loadSnapshot(data);
      onStatus(data ? "live" : "reconnecting");
    } catch {
      onStatus("reconnecting");
    }
    if (!stopped) timer = window.setTimeout(poll, REPLAY_POLL_MS);
  };
  poll();
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}

export function startFeed(store: TrainStore, onStatus: (status: FeedStatus) => void): () => void {
  const replayFrom = replayStart();
  if (replayFrom !== null) return startReplay(store, replayFrom, onStatus);
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
