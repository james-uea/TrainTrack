import { DELAY_BANDS } from "../trains/delay";
import styles from "./Legend.module.css";

export function Legend() {
  return (
    <ul className={styles.legend} aria-label="Delay colours">
      {DELAY_BANDS.map(({ band, label, colour }) => (
        <li key={band}>
          <span className={styles.swatch} style={{ background: `rgb(${colour.join(",")})` }} />
          {label}
        </li>
      ))}
    </ul>
  );
}
