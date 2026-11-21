import { useUi } from "../state";
import { DELAY_BANDS, type DelayBand } from "../trains/delay";
import styles from "./Legend.module.css";

const NOT_LATE: DelayBand[] = ["on_time", "unknown"];

/** The delay colours, each a switch for showing or hiding trains in that band, and a shortcut to late trains only. */
export function Legend() {
  const hidden = useUi((state) => state.hiddenBands);
  const toggleBand = useUi((state) => state.toggleBand);
  const setHiddenBands = useUi((state) => state.setHiddenBands);
  const operator = useUi((state) => state.operator);
  const showOperator = useUi((state) => state.showOperator);
  const lateOnly = hidden.size === NOT_LATE.length && NOT_LATE.every((band) => hidden.has(band));

  return (
    <div className={styles.legend}>
      {operator && (
        <button
          type="button"
          className={styles.operator}
          onClick={() => showOperator(null)}
          title="Show all operators"
        >
          {operator.name} only <span aria-hidden="true">×</span>
        </button>
      )}
      <ul aria-label="Delay colours: click to show or hide">
        {DELAY_BANDS.map(({ band, label, colour }) => (
          <li key={band}>
            <button
              type="button"
              className={styles.band}
              aria-pressed={!hidden.has(band)}
              onClick={() => toggleBand(band)}
            >
              <span className={styles.swatch} style={{ background: `rgb(${colour.join(",")})` }} />
              {label}
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className={styles.shortcut}
        aria-pressed={lateOnly}
        onClick={() => setHiddenBands(lateOnly ? [] : NOT_LATE)}
      >
        {lateOnly ? "Show all trains" : "Late trains only"}
      </button>
    </div>
  );
}
