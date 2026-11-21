import { useEffect, useMemo } from "react";
import { api } from "./api/client";
import { startFeed } from "./feed/feed";
import { Legend } from "./map/Legend";
import { StatusBar } from "./map/StatusBar";
import { TrainMap } from "./map/TrainMap";
import { useUi } from "./state";
import { type LonLat, SegmentCache } from "./trains/segments";
import { TrainStore } from "./trains/store";

async function fetchSegments(keys: string[]): Promise<Record<string, LonLat[]>> {
  const { data } = await api.GET("/api/segments", { params: { query: { pairs: keys } } });
  return (data ?? {}) as Record<string, LonLat[]>;
}

export function App() {
  const segments = useMemo(() => new SegmentCache(fetchSegments), []);
  const store = useMemo(() => new TrainStore(segments), [segments]);
  const setStatus = useUi((state) => state.setStatus);

  useEffect(() => startFeed(store, setStatus), [store, setStatus]);

  return (
    <>
      <TrainMap store={store} segments={segments} />
      <StatusBar store={store} />
      <Legend />
    </>
  );
}
