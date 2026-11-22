import { Profiler, useEffect, useMemo } from "react";
import { api } from "./api/client";
import { benchEnabled, countCommit, runBench } from "./bench";
import { FeedContext } from "./feed/context";
import { FeedController } from "./feed/controller";
import { replayStart } from "./feed/feed";
import { Legend } from "./map/Legend";
import { StatusBar } from "./map/StatusBar";
import { TrainMap } from "./map/TrainMap";
import { TrainPanel } from "./panel/TrainPanel";
import { Search } from "./search/Search";
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
  const setPlayback = useUi((state) => state.setPlayback);
  const feed = useMemo(
    () => new FeedController(store, setStatus, setPlayback),
    [store, setStatus, setPlayback],
  );

  useEffect(() => {
    const at = replayStart();
    if (at === null) feed.live();
    else feed.seek(at);
    return () => feed.stop();
  }, [feed]);

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
    <FeedContext.Provider value={feed}>
      <Profiler id="app" onRender={countCommit}>
        <TrainMap store={store} segments={segments} />
        <StatusBar store={store} />
        <Legend />
        <Search store={store} />
        <TrainPanel />
      </Profiler>
    </FeedContext.Provider>
  );
}
