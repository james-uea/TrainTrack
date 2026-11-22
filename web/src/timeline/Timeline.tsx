import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type ReplayRun } from "../api/client";
import { useFeed } from "../feed/context";
import { SPEEDS } from "../feed/playback";
import { useUi } from "../state";
import styles from "./Timeline.module.css";
import { nextUkDay, ukDay, ukDayStart } from "./ukTime";

const MINUTE = 60_000;
const TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London",
  hour: "2-digit",
  minute: "2-digit",
});
// How long after the slider stops moving to jump there, so dragging doesn't fetch every minute it passes
const SEEK_AFTER_MS = 150;

function useRuns(day: string, live: boolean) {
  return useQuery({
    queryKey: ["replay-runs", day],
    refetchInterval: live ? MINUTE : false,
    queryFn: async (): Promise<ReplayRun[]> => {
      const { data } = await api.GET("/api/replay/runs", { params: { query: { day } } });
      return data ?? [];
    },
  });
}

/** Copies the address, which holds the moment, speed, view and selected train. */
function CopyLink() {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title="Copy a link to this moment and view"
      onClick={async () => {
        await navigator.clipboard.writeText(window.location.href);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}

/** Live, or any moment of any day: a day picker, a slider across it shaded where frames were stored, and controls. */
export function Timeline() {
  const feed = useFeed();
  const playback = useUi((state) => state.playback);
  const live = playback.mode === "live";
  const playing = live || playback.playing;

  const [now, setNow] = useState(() => feed.now());
  const [dragging, setDragging] = useState<number | null>(null);
  const seekTimer = useRef(0);
  useEffect(() => {
    const timer = setInterval(() => setNow(feed.now()), 250);
    return () => clearInterval(timer);
  }, [feed]);

  const shown = dragging ?? now;
  const day = ukDay(shown);
  const start = ukDayStart(day);
  const end = ukDayStart(nextUkDay(day));
  const latest = Math.min(end, Date.now());
  const { data: runs = [] } = useRuns(day, live);

  const seek = (at: number) => {
    setDragging(at);
    clearTimeout(seekTimer.current);
    seekTimer.current = window.setTimeout(() => {
      feed.seek(at);
      setDragging(null);
    }, SEEK_AFTER_MS);
  };

  const span = end - start;
  const percent = (ms: number) => `${(100 * Math.min(Math.max(ms - start, 0), span)) / span}%`;

  return (
    <fieldset className={styles.timeline} aria-label="Timeline">
      <button
        type="button"
        className={styles.live}
        aria-pressed={live}
        onClick={() => feed.live()}
        title={live ? "Showing trains now" : "Back to now"}
      >
        <span className={styles.dot} />
        Live
      </button>
      <button
        type="button"
        className={styles.play}
        aria-label={playing ? "Pause" : "Play"}
        onClick={() => feed.setPlaying(!playing)}
      >
        {playing ? "❚❚" : "▶"}
      </button>
      <fieldset className={styles.speeds} aria-label="Speed">
        {SPEEDS.map((speed) => (
          <button
            key={speed}
            type="button"
            aria-pressed={!live && playback.speed === speed}
            disabled={live}
            onClick={() => feed.setSpeed(speed)}
          >
            {speed}×
          </button>
        ))}
      </fieldset>
      <input
        type="date"
        className={styles.day}
        aria-label="Day"
        value={day}
        max={ukDay(Date.now())}
        onChange={(event) => {
          if (!event.target.value) return;
          // Same time of day on the chosen day, or as far as it's gone if that's today
          feed.seek(Math.min(ukDayStart(event.target.value) + (shown - start), Date.now()));
        }}
      />
      <div className={styles.track}>
        <div className={styles.runs} aria-hidden="true">
          {runs.map((run) => (
            <span
              key={run.start}
              data-source={run.source}
              style={{
                left: percent(Date.parse(run.start)),
                width: `calc(${percent(Date.parse(run.end))} - ${percent(Date.parse(run.start))})`,
              }}
            />
          ))}
        </div>
        <input
          type="range"
          aria-label="Time"
          aria-valuetext={TIME.format(shown)}
          min={start}
          max={end}
          step={MINUTE}
          value={Math.min(shown, end)}
          onChange={(event) => seek(Math.min(Number(event.target.value), latest))}
        />
      </div>
      <output className={styles.time}>{TIME.format(shown)}</output>
      <CopyLink />
    </fieldset>
  );
}
