"""
Record what the map shows, so any moment can be replayed: ticks the live positions every 5 seconds and stores a
frame in `position_frames` each time. A keyframe (every placed train) starts each run and every 5 minutes of
clock time; in between, each frame holds only what changed since the one before.

    uv run src/recorder.py                                                       # record live, forever
    uv run src/recorder.py --backfill 2026-11-21T13:50Z 2026-11-21T14:51Z        # compute frames for the past
    uv run src/recorder.py --backfill ... --replace                              # recompute computed frames there

A backfill works from the database as it is now, as `?at=` does: actual times after each moment are hidden, but
later forecasts, schedule changes and cancellations can show through. Its frames are marked `computed`, and it
never touches recorded ones.
"""

import argparse
import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import retention
from config import load_config
from db import Database
from frames import changes_dict, pack, snapshot_dict
from live import TICK, Clock, LivePositions, Snapshot, SteppedClock
from util import LONDON

logger = logging.getLogger("recorder")

KEYFRAME_EVERY = timedelta(minutes=5)


def keyframe_slot(at: datetime) -> int:
    """Which 5-minute slot of the epoch `at` is in: a keyframe is written in the first frame of each slot."""
    return int(at.timestamp() // KEYFRAME_EVERY.total_seconds())


@dataclass
class Frame:
    at: datetime
    keyframe: bool
    trains: int
    active: int
    data: bytes


@dataclass
class Recorder:
    """Turns successive snapshots into frames: a keyframe when one is due, otherwise the changes since the last."""
    clock: Clock
    _last: dict | None = None
    _slot: int | None = None
    sizes: list[int] = field(default_factory=list)  # bytes stored per frame
    keyframes: int = 0

    def frame(self, snapshot: Snapshot) -> Frame:
        current = snapshot_dict(snapshot, self.clock, 0)
        slot = keyframe_slot(snapshot.at)
        if self._last is None or slot != self._slot:
            frame = Frame(snapshot.at, True, len(current["trains"]), snapshot.active, pack(current))
            self.keyframes += 1
        else:
            changes = changes_dict(self._last, current)
            frame = Frame(snapshot.at, False, len(changes["trains"]), snapshot.active, pack(changes))
        self._last, self._slot = current, slot
        self.sizes.append(len(frame.data))
        return frame

    def lost(self):
        """The last frame wasn't stored, so the next must be a keyframe: changes would have nothing to follow."""
        self._last = None


def wait_for_next_tick():
    """Sleep to the next multiple of 5 seconds of real time, so frames land on :00, :05, :10..."""
    period = TICK.total_seconds()
    time.sleep(period - time.time() % period)


def record(db: Database):
    clock = Clock()
    live = LivePositions(Database(db.database_url), clock)
    recorder = Recorder(clock)
    retention.ensure_partitions(db, datetime.now(LONDON).date(), ahead=1)
    day = datetime.now(LONDON).date()
    written, write_times, started = 0, [], time.monotonic()
    while True:
        wait_for_next_tick()
        try:
            snapshot = live.tick()
            frame = recorder.frame(snapshot)
            mark = time.perf_counter()
            if (today := datetime.now(LONDON).date()) != day:
                retention.ensure_partitions(db, today, ahead=1)
                day = today
            db.add_frame(frame.at, frame.keyframe, "recorded", frame.trains, frame.active, frame.data)
            db.commit()
            write_times.append(time.perf_counter() - mark)
            written += 1
        except Exception:
            logger.exception("Tick failed; the next frame will be a keyframe")
            db.conn.rollback()
            recorder.lost()
            continue
        if time.monotonic() - started >= 60:
            logger.info("Last minute: %d frames, %d bytes, write median %.0f ms, tick %.0f ms, %d of %d placed",
                        written, sum(recorder.sizes), 1000 * statistics.median(write_times),
                        1000 * snapshot.timings["total"], len(snapshot.positions), snapshot.active)
            written, write_times, started = 0, [], time.monotonic()
            recorder.sizes.clear()


def backfill(db: Database, start: datetime, end: datetime, replace: bool = False) -> int:
    """Compute and store frames every 5 s from `start` to `end`, marked `computed`. Returns how many."""
    recorded, computed = db.count_frames(start, end)
    if recorded:
        raise SystemExit(f"{recorded} recorded frames already lie between {start} and {end}; backfill around them")
    if computed:
        if not replace:
            raise SystemExit(f"{computed} computed frames already lie between {start} and {end}; pass --replace")
        db.delete_computed_frames(start, end)
    day = start.astimezone(LONDON).date()
    while day <= end.astimezone(LONDON).date():
        db.ensure_day_partition("position_frames", "at", day)
        day += timedelta(days=1)
    db.commit()

    clock = SteppedClock(start)
    live = LivePositions(Database(db.database_url), clock)
    recorder = Recorder(clock)
    count, began = 0, time.perf_counter()
    while clock.now() <= end:
        snapshot = live.tick()
        frame = recorder.frame(snapshot)
        db.add_frame(frame.at, frame.keyframe, "computed", frame.trains, frame.active, frame.data)
        count += 1
        if count % 120 == 0:  # every 10 minutes of clock
            db.commit()
            logger.info("%s: %d frames, %.1f MB", frame.at.isoformat(), count, sum(recorder.sizes) / 1e6)
        clock.step(TICK)
    db.commit()
    elapsed = time.perf_counter() - began
    logger.info("Backfilled %d frames (%.1f MB, %d keyframes) in %.0fs", count, sum(recorder.sizes) / 1e6,
                recorder.keyframes, elapsed)
    live.db.close()
    return count


def parse_moment(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backfill", nargs=2, metavar=("FROM", "TO"), help="compute frames for a past window")
    parser.add_argument("--replace", action="store_true", help="with --backfill, recompute computed frames there")
    args = parser.parse_args()

    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(config.database_url)
    try:
        if args.backfill:
            backfill(db, parse_moment(args.backfill[0]), parse_moment(args.backfill[1]), args.replace)
        else:
            record(db)
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__ == "__main__":
    main()
