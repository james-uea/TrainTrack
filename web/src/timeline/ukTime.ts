// UK days and times for the timeline, whatever the browser's own time zone: a UK day runs midnight to midnight
// Europe/London, so it's 23 or 25 hours long when the clocks change
const PARTS = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function londonParts(ms: number): Record<string, number> {
  const parts: Record<string, number> = {};
  for (const { type, value } of PARTS.formatToParts(new Date(ms)))
    if (type !== "literal") parts[type] = Number(value);
  return parts;
}

/** How far London's clock is ahead of UTC at `ms` (0 or an hour). */
function londonOffset(ms: number): number {
  const p = londonParts(ms);
  const asUtc = Date.UTC(
    p.year ?? 0,
    (p.month ?? 1) - 1,
    p.day ?? 1,
    p.hour ?? 0,
    p.minute ?? 0,
    p.second ?? 0,
  );
  return asUtc - Math.floor(ms / 1000) * 1000;
}

/** The UK date at `ms`, as YYYY-MM-DD. */
export function ukDay(ms: number): string {
  const p = londonParts(ms);
  return `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
}

/** When a UK day (YYYY-MM-DD) starts, in ms since the epoch. */
export function ukDayStart(day: string): number {
  const [year, month, date] = day.split("-").map(Number);
  const midnightUtc = Date.UTC(year ?? 1970, (month ?? 1) - 1, date ?? 1);
  // Midnight is never inside a clock change in the UK (they happen at 01:00 UTC), so one correction is enough
  return midnightUtc - londonOffset(midnightUtc - 3_600_000);
}

/** The day after a UK day. */
export function nextUkDay(day: string): string {
  return ukDay(ukDayStart(day) + 36 * 3_600_000);
}
