import { Profiler, useEffect, useMemo } from "react";
import { api } from "./api/client";
import { benchEnabled, countCommit, runBench } from "./bench";
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

  useEffect(() => {
    if (!benchEnabled) return;
    // Start once trains are on the map and their segments have had a moment to arrive
    const wait = setInterval(() => {
      if (store.order.length === 0) return;
      clearInterval(wait);
      setTimeout(() => runBench(() => store.order.length), 5000);
    }, 500);
    return () => clearInterval(wait);
  }, [store]);

  return (
    <Profiler id="app" onRender={countCommit}>
      <TrainMap store={store} segments={segments} />
      <StatusBar store={store} />
      <Legend />
    </Profiler>
  );
}
