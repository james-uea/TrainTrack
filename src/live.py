"""
Live train positions for the map: every train's journey held in memory, kept up to date from the database, and
estimated for the current moment on every tick.

A clock decides what "now" is, so the same service runs live, frozen at a past moment, or replaying the past:

    now                         real time
    fixed:2026-11-21T14:30Z     always that moment
    replay:2026-11-21T14:30Z    starts at that moment and runs forward at 1x

    uv run src/live.py --clock replay:2026-11-21T14:30Z --bench 240   # time 240 ticks, 5 s of clock apart
"""

import argparse
import logging
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from config import load_config
from db import Database
from positions import (
    Journey,
    PathCache,
    Position,
    SectionTimes,
    Stop,
    estimate_position,
    segment_line,
    service_status,
)

logger = logging.getLogger(__name__)

TICK = timedelta(seconds=5)
# How often (in clock time) to look for trains entering or leaving the time window positions cover
WINDOW_REFRESH = timedelta(seconds=60)
# How often (in clock time) to work out other trains' recent run times between stops again
SECTIONS_REFRESH = timedelta(seconds=60)
# How often (in real time) to reload segment paths, which the daily timetable load adds to
PATHS_REFRESH = 15 * 60.0
# The consumer stamps updated_at when its transaction starts, which can be a moment before it commits, so each
# poll looks back a little further than the last one to avoid missing a change
POLL_OVERLAP = timedelta(seconds=10)


class Clock:
    """What time it is for the map: real time, a fixed moment, or a replay of the past running at 1x."""

    def __init__(self, start: datetime | None = None, running: bool = True,
                 monotonic: Callable[[], float] = time.monotonic):
        self.start, self.running, self._monotonic = start, running, monotonic
        self._started = monotonic()

    @classmethod
    def parse(cls, spec: str | None) -> "Clock":
        if not spec or spec == "now":
            return cls()
        mode, _, value = spec.partition(":")
        if mode not in ("fixed", "replay") or not value:
            raise ValueError(f"Clock must be 'now', 'fixed:<ISO time>' or 'replay:<ISO time>', not {spec!r}")
        start = datetime.fromisoformat(value)
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        return cls(start, running=mode == "replay")

    @property
    def mode(self) -> str:
        return "now" if self.start is None else "replay" if self.running else "fixed"

    @property
    def is_live(self) -> bool:
        return self.start is None

    def now(self) -> datetime:
        if self.start is None:
            return datetime.now(UTC)
        if not self.running:
            return self.start
        return self.start + timedelta(seconds=self._monotonic() - self._started)

    def __str__(self) -> str:
        return self.mode if self.start is None else f"{self.mode}:{self.start.isoformat()}"


@dataclass
class Snapshot:
    at: datetime
    positions: list[tuple[Journey, Position]]
    active: int  # trains running at `at`, placed or not
    timings: dict[str, float] = field(default_factory=dict)  # seconds spent in each part of the tick


class LivePositions:
    """
    Journeys in the time window around the clock, kept current: trains whose `updated_at` moved are reloaded on
    each tick, and the window itself is refreshed every minute of clock time.
    """

    def __init__(self, db: Database, clock: Clock):
        self.db, self.clock = db, clock
        self.journeys: dict[str, Journey] = {}
        self.points: dict[str, tuple[float, float]] = {}  # every placed TIPLOC seen, British National Grid
        self.paths: PathCache | None = None
        self._paths_loaded = 0.0
        self._window_at: datetime | None = None
        self.sections: SectionTimes | None = None
        self._sections_at: datetime | None = None
        self._polled_at: datetime | None = None

    def tick(self) -> Snapshot:
        at = self.clock.now()
        timings: dict[str, float] = {}
        started = time.perf_counter()
        try:
            if self.paths is None or time.monotonic() - self._paths_loaded > PATHS_REFRESH:
                self.paths = PathCache(self.db.fetch_segment_paths())
                self._paths_loaded = time.monotonic()
                timings["paths"] = time.perf_counter() - started

            mark = time.perf_counter()
            changed = self._poll()
            timings["poll"] = time.perf_counter() - mark

            mark = time.perf_counter()
            if self._window_at is None or abs(at - self._window_at) >= WINDOW_REFRESH:
                self._refresh_window(at)
                timings["window"] = time.perf_counter() - mark
            elif changed:
                self._reload(at, changed)
                timings["reload"] = time.perf_counter() - mark
        finally:
            # Reads open a transaction; end it so the next tick sees new commits (and now() moves on)
            self.db.conn.rollback()

        mark = time.perf_counter()
        if self.sections is None or not timedelta(0) <= at - self._sections_at < SECTIONS_REFRESH:
            self.sections, self._sections_at = SectionTimes(self.journeys.values(), at), at
            timings["sections"] = time.perf_counter() - mark

        mark = time.perf_counter()
        active = 0
        positions = []
        for journey in self.journeys.values():
            if service_status(journey, at) != "active":
                continue
            active += 1
            if (position := estimate_position(journey, at, self.paths, self.sections)) is not None:
                positions.append((journey, position))
        timings["estimate"] = time.perf_counter() - mark
        timings["total"] = time.perf_counter() - started
        return Snapshot(at, positions, active, timings)

    def journey(self, rid: str) -> Journey | None:
        return self.journeys.get(rid)

    def _poll(self) -> list[str]:
        """Trains changed since the last poll. The first poll only sets the starting point."""
        since = self._polled_at - POLL_OVERLAP if self._polled_at else None
        self._polled_at, changed = self.db.fetch_changed_journeys(since)
        if changed:
            logger.debug("%d trains changed", len(changed))
        return changed

    def _refresh_window(self, at: datetime):
        """Reload the set of trains around `at`: new ones are loaded, finished ones dropped."""
        rows = self.db.fetch_journeys_around(at)
        wanted = {row[0] for row in rows}
        known = set(self.journeys)
        for rid in known - wanted:
            del self.journeys[rid]
        self._load(rows, only=wanted - known)
        self._window_at = at
        logger.debug("Window at %s: %d trains (%d new)", at.isoformat(), len(wanted), len(wanted - known))

    def _reload(self, at: datetime, rids: list[str]):
        """Reload changed trains that are in the window (or have just joined it, e.g. a new schedule)."""
        rows = self.db.fetch_journeys_around(at, rids)
        in_window = {row[0] for row in rows}
        for rid in set(rids) - in_window:
            self.journeys.pop(rid, None)
        self._load(rows, only=in_window)

    def _load(self, rows: list[tuple], only: set[str]):
        """Build journeys for the rids in `only` from `fetch_journeys_around` rows; others keep their stops."""
        fresh: dict[str, Journey] = {}
        for rid, train_id, toc, cancelled, deactivated in rows:
            if rid in only:
                fresh[rid] = Journey(rid, [], train_id, toc, bool(cancelled), bool(deactivated))
            elif (journey := self.journeys.get(rid)) is not None:
                journey.cancelled, journey.deactivated = bool(cancelled), bool(deactivated)
        if fresh:
            for row in self.db.fetch_position_stops(list(fresh)):
                rid, tiploc, location_type, x, y, *times, cancelled = row
                fresh[rid].stops.append(
                    Stop(tiploc, location_type, (x, y) if x is not None else None, *times, cancelled=cancelled))
                if x is not None:
                    self.points[tiploc] = (x, y)
        self.journeys.update(fresh)

    def segment(self, from_tiploc: str, to_tiploc: str) -> list[tuple[float, float]] | None:
        """The (lon, lat) path between two placed TIPLOCs, as trains are drawn along it, or None if either is unknown."""
        start, end = self.points.get(from_tiploc), self.points.get(to_tiploc)
        if start is None or end is None or self.paths is None:
            return None
        return segment_line(Stop(from_tiploc, "", start), Stop(to_tiploc, "", end), self.paths)


class SteppedClock(Clock):
    """A replay clock moved on by hand, for benchmarks."""

    def __init__(self, start: datetime):
        super().__init__(start, running=False)

    def step(self, by: timedelta):
        self.start += by


def bench(db: Database, start: datetime, ticks: int):
    """Time `ticks` ticks, each 5 s of clock after the last, and print percentiles."""
    clock = SteppedClock(start)
    live = LivePositions(db, clock)
    first = live.tick()
    print(f"First tick at {first.at.isoformat()}: {first.timings['total']:.2f}s "
          f"({', '.join(f'{k} {v:.2f}s' for k, v in first.timings.items())}), "
          f"{len(first.positions):,} of {first.active:,} active trains placed")

    totals, estimates, polls, windows, placed = [], [], [], [], []
    for _ in range(ticks):
        clock.step(TICK)
        snapshot = live.tick()
        totals.append(snapshot.timings["total"])
        estimates.append(snapshot.timings["estimate"])
        polls.append(snapshot.timings["poll"])
        if "window" in snapshot.timings:
            windows.append(snapshot.timings["window"])
        placed.append(len(snapshot.positions) / snapshot.active if snapshot.active else 1.0)

    def summary(name: str, values: list[float]) -> str:
        if not values:
            return f"{name}: none"
        ordered = sorted(values)
        p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
        return f"{name}: median {1000 * statistics.median(ordered):.0f} ms, p95 {1000 * p95:.0f} ms, max {1000 * ordered[-1]:.0f} ms"

    print(f"{ticks} ticks to {clock.now().isoformat()}:")
    for name, values in (("tick", totals), ("estimate", estimates), ("poll", polls), ("window refresh", windows)):
        print("  " + summary(name, values))
    print(f"  placed: {100 * min(placed):.1f}% to {100 * max(placed):.1f}% of active trains")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clock", default="now", help="now, fixed:<ISO time> or replay:<ISO time> (default: now)")
    parser.add_argument("--bench", type=int, metavar="TICKS", help="time this many ticks, 5 s of clock apart")
    args = parser.parse_args()
    logging.basicConfig(level=load_config().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    clock = Clock.parse(args.clock)
    db = Database(load_config().database_url)
    try:
        if args.bench:
            bench(db, clock.start or clock.now(), args.bench)
            return
        live = LivePositions(db, clock)
        while True:
            snapshot = live.tick()
            logger.info("%s: %d of %d trains placed in %.0f ms", snapshot.at.isoformat(timespec="seconds"),
                        len(snapshot.positions), snapshot.active, 1000 * snapshot.timings["total"])
            time.sleep(TICK.total_seconds())
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__ == "__main__":
    main()
