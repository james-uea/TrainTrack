// Delay bands for colouring trains, as on the map's legend
export type DelayBand = "on_time" | "minor" | "late" | "major" | "unknown";

export const DELAY_BANDS: { band: DelayBand; label: string; colour: [number, number, number] }[] = [
  { band: "on_time", label: "On time", colour: [26, 152, 80] },
  { band: "minor", label: "1–5 min late", colour: [253, 174, 97] },
  { band: "late", label: "5–15 min late", colour: [244, 109, 67] },
  { band: "major", label: "Over 15 min late", colour: [215, 48, 39] },
  { band: "unknown", label: "No report yet", colour: [140, 140, 150] },
];

/** The band for a delay in minutes (negative is early); null means the train hasn't reported yet. */
export function delayBand(delay: number | null | undefined): DelayBand {
  if (delay === null || delay === undefined) return "unknown";
  if (delay < 1) return "on_time";
  if (delay <= 5) return "minor";
  if (delay <= 15) return "late";
  return "major";
}
