import { useEffect, useState } from "react";
import type { TrainDetail, TrainStop } from "../api/client";
import { useUi } from "../state";
import { delayBand } from "../trains/delay";
import { lastPassed, stopTime } from "../trains/stopTimes";
import { useTrain } from "../trains/useTrain";
import styles from "./TrainPanel.module.css";

const TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London",
  hour: "2-digit",
  minute: "2-digit",
});
const time = (iso: string | null) => (iso ? TIME.format(new Date(iso)) : "");

function lateness(delay: number | null, cancelled: boolean): string {
  if (cancelled) return "Cancelled";
  if (delay === null) return "No report yet";
  if (delay <= 0) return "On time";
  return `${delay} min late`;
}

function StopRow({
  stop,
  last,
  passed,
  here,
}: {
  stop: TrainStop;
  last: boolean;
  passed: boolean;
  here: boolean;
}) {
  const { planned, expected, actual, late } = stopTime(stop, last);
  const shown = actual ?? expected;
  const changed = shown !== null && late !== 0;
  return (
    <li
      className={[styles.stop, passed && styles.passed, !stop.public && styles.passing, here && styles.here]
        .filter(Boolean)
        .join(" ")}
    >
      <span className={styles.times}>
        <span className={changed ? styles.struck : undefined}>{time(planned)}</span>
        {changed && (
          <span className={styles.changed} data-band={delayBand(late)}>
            {time(shown)}
            {!actual && <span className={styles.estimate}>exp</span>}
          </span>
        )}
      </span>
      <span className={styles.name}>
        {stop.name ?? stop.tiploc}
        {stop.cancelled && <span className={styles.cancelled}>cancelled</span>}
      </span>
      {stop.platform && (
        <span
          className={stop.platform_confirmed ? styles.platform : `${styles.platform} ${styles.unconfirmed}`}
        >
          {stop.platform}
        </span>
      )}
    </li>
  );
}

function Stops({ train }: { train: TrainDetail }) {
  const [showPassing, setShowPassing] = useState(false);
  const passedUpTo = lastPassed(train.stops, train.position?.from_tiploc ?? null);
  // Stations passengers can use; passing points and operational stops are behind the toggle
  const shown = train.stops
    .map((stop, index) => ({ stop, index }))
    .filter(({ stop }) => showPassing || stop.public);
  const hiddenCount = train.stops.length - train.stops.filter((stop) => stop.public).length;
  // The train is drawn after the last shown stop it has left
  const here = shown.reduce((found, { index }, i) => (index <= passedUpTo ? i : found), -1);
  return (
    <>
      <ol className={styles.stops}>
        {shown.map(({ stop, index }, i) => (
          <StopRow
            key={`${stop.tiploc}-${index}`}
            stop={stop}
            last={index === train.stops.length - 1}
            passed={index <= passedUpTo}
            here={i === here && passedUpTo < train.stops.length - 1}
          />
        ))}
      </ol>
      {hiddenCount > 0 && (
        <button type="button" className={styles.toggle} onClick={() => setShowPassing(!showPassing)}>
          {showPassing ? "Hide" : "Show"} {hiddenCount} passing points and other stops
        </button>
      )}
    </>
  );
}

/** Details of the selected train: where it's going, how late, and every stop with its times and platform. */
export function TrainPanel() {
  const selected = useUi((state) => state.selected);
  const select = useUi((state) => state.select);
  const { data: train, isPending, isError } = useTrain(selected);

  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === "Escape" && select(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [select]);

  if (!selected) return null;
  return (
    <aside className={styles.panel} aria-label="Train details">
      <button type="button" className={styles.close} onClick={() => select(null)} aria-label="Close">
        ×
      </button>
      {isPending && <p className={styles.note}>Loading…</p>}
      {isError && <p className={styles.note}>Couldn't load this train.</p>}
      {train === null && <p className={styles.note}>This train is no longer running.</p>}
      {train && (
        <>
          <header className={styles.header}>
            <h2>
              {train.headcode ?? train.rid}{" "}
              <span className={styles.operator}>{train.operator ?? train.toc}</span>
            </h2>
            <p className={styles.journey}>
              {train.origin ?? "?"} to {train.destination ?? "?"}
            </p>
            <p className={styles.status} data-band={train.cancelled ? "cancelled" : delayBand(train.delay)}>
              {lateness(train.delay, train.cancelled)}
            </p>
            {(train.cancel_reason || train.late_reason) && (
              <p className={styles.reason}>{train.cancel_reason ?? train.late_reason}</p>
            )}
          </header>
          <Stops train={train} />
        </>
      )}
    </aside>
  );
}
