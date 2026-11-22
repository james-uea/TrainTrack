import { Profiler, useEffect, useMemo } from "react";
import { api } from "./api/client";
import { benchEnabled, countCommit, runBench } from "./bench";
import { readPlayback, writePlayback } from "./feed/address";
import { FeedContext } from "./feed/context";
import { FeedController } from "./feed/controller";
import { Legend } from "./map/Legend";
import { StatusBar } from "./map/StatusBar";
import { TrainMap } from "./map/TrainMap";
import { TrainPanel } from "./panel/TrainPanel";
import { Search } from "./search/Search";
import { useUi } from "./state";
import { Timeline } from "./timeline/Timeline";
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
    const { at, speed, playing } = readPlayback();
    if (at === null) feed.live();
    else feed.seek(at, speed, playing);
    return () => feed.stop();
  }, [feed]);

  // Keep the moment, speed and play state in the address, so it can be shared
  useEffect(() => {
    const write = () => {
      const playback = useUi.getState().playback;
      const replaying = playback.mode === "replay";
      const url = writePlayback(new URL(window.location.href), {
        at: replaying ? feed.now() : null,
        speed: replaying ? playback.speed : 1,
        playing: replaying ? playback.playing : true,
      });
      if (url.href !== window.location.href) window.history.replaceState(null, "", url);
    };
    const timer = setInterval(write, 2000);
    const unsubscribe = useUi.subscribe((state, previous) => {
      if (state.playback !== previous.playback) write();
    });
    return () => {
      clearInterval(timer);
      unsubscribe();
    };
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
        <Timeline />
      </Profiler>
    </FeedContext.Provider>
  );
}
