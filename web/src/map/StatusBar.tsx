import { useEffect, useState } from "react";
import { useUi } from "../state";
import type { TrainStore } from "../trains/store";
import styles from "./StatusBar.module.css";

const TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});
const DAY = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", day: "numeric", month: "short" });

/** The moment the map shows (UK time), how many trains, and whether the feed is live. */
export function StatusBar({ store }: { store: TrainStore }) {
  const status = useUi((state) => state.status);
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((tick) => tick + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  if (!store.clock.ready) return <div className={styles.bar}>Connecting…</div>;
  const now = new Date(store.clock.now());
  const mode = store.clockName.split(":")[0];
  return (
    <div className={styles.bar}>
      <strong>{TIME.format(now)}</strong> {DAY.format(now)}
      {mode !== "now" && <span className={styles.mode}>{mode}</span>}
      <span>
        {store.trains.size.toLocaleString()} of {store.active.toLocaleString()} trains placed
      </span>
      {status !== "live" && <span className={styles.warning}>{status}</span>}
    </div>
  );
}
