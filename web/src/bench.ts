import { geojsonRenderer, geojsonUpdates } from "./map/geojsonTrains";
import { frameTimes } from "./map/TrainMap";

/**
 * `?bench=1`: measures the map for 60 s once trains are on it, then logs the result and leaves it on
 * `window.__bench` for scripts. Frame intervals come from requestAnimationFrame; draw time is the map's own loop
 * (placing every train and handing deck.gl the buffers); commits counts React renders, which should stay at the few
 * the status bar makes each second.
 */
export const benchEnabled = new URLSearchParams(window.location.search).get("bench") === "1";

export interface BenchResult {
  seconds: number;
  frames: number;
  fps: number;
  frameP50: number;
  frameP95: number;
  slowFrames: number; // intervals over 25 ms, i.e. a dropped frame at 60 Hz
  drawP50: number;
  drawP95: number;
  drawMax: number;
  commits: number | null; // React's Profiler only reports in development builds
  trains: number;
  renderer: "deck.gl" | "geojson";
  dataUpdatesPerSecond: number | null; // GeoJSON only: new positions MapLibre finished loading each second
}

let commits = 0;
export function countCommit() {
  commits++;
}

const percentile = (values: number[], p: number) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] ?? 0;
};
const round = (value: number) => Math.round(value * 100) / 100;

export function runBench(trains: () => number, seconds = 60): Promise<BenchResult> {
  return new Promise((resolve) => {
    const intervals: number[] = [];
    let last = 0;
    let started = 0;
    const startDraw = frameTimes.length;
    const startCommits = commits;
    const startUpdates = geojsonUpdates.count;
    const frame = (now: number) => {
      if (started === 0) started = now;
      else intervals.push(now - last);
      last = now;
      if (now - started < seconds * 1000) {
        requestAnimationFrame(frame);
        return;
      }
      const draws = frameTimes.slice(startDraw);
      const result: BenchResult = {
        seconds,
        frames: intervals.length,
        fps: round(intervals.length / ((now - started) / 1000)),
        frameP50: round(percentile(intervals, 0.5)),
        frameP95: round(percentile(intervals, 0.95)),
        slowFrames: intervals.filter((interval) => interval > 25).length,
        drawP50: round(percentile(draws, 0.5)),
        drawP95: round(percentile(draws, 0.95)),
        drawMax: round(Math.max(0, ...draws)),
        commits: import.meta.env.DEV ? commits - startCommits : null,
        trains: trains(),
        renderer: geojsonRenderer ? "geojson" : "deck.gl",
        dataUpdatesPerSecond: geojsonRenderer ? round((geojsonUpdates.count - startUpdates) / seconds) : null,
      };
      console.info("bench", JSON.stringify(result));
      (window as unknown as { __bench: BenchResult }).__bench = result;
      resolve(result);
    };
    requestAnimationFrame(frame);
  });
}
