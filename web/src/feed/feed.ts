// Keeps a TrainStore current: one gzipped snapshot over HTTP, then each tick's changes over server-sent events
import { api, type PositionChanges, type PositionsResponse } from "../api/client";
import type { TrainStore } from "../trains/store";

export type FeedStatus = "connecting" | "live" | "reconnecting";

export function startFeed(store: TrainStore, onStatus: (status: FeedStatus) => void): () => void {
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
