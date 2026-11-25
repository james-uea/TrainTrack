"""
Learn where each Train Describer berth step happens, from where Darwin's actual times put the trains that made it.

A berth step is a train's headcode moving from one berth to the next, at the signal between them. When the headcode
belongs to one train running then, that train's position along its route at that second, from its actual times at
an even pace between them (as `accuracy.py` takes the truth), is one sample of where the step happens. A step's point
is the median of its samples. Where several running trains share the headcode, the one whose position is among the
area's steps already placed is taken, if only one is. Each step also gets the median distance and time to the same
train's next step, which says how far a train can have got before it steps again.

    uv run src/td_berths.py [--days 3]

The timetable service runs this after each daily load.
"""

import argparse
import bisect
import logging
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

from accuracy import TRUTH_OFFSET, Route, load_routes
from config import load_config
from db import Database
from positions import PathCache, _path
from util import LONDON

logger = logging.getLogger("td_berths")

# Days of berth steps learned from
LEARN_DAYS = 3
# Steps are matched to trains a few hours at a time, to keep memory down
CHUNK = timedelta(hours=6)
# A step is kept once this many trains placed it, and their positions sit within SPREAD_METRES of its point (median)
MIN_SAMPLES = 3
SPREAD_METRES = 500.0
# A train counts as running from this long before its first report to this long after its last (seconds)
REPORT_MARGIN = 120.0
# A shared headcode goes to the train whose position is within one grid cell of this size of the area's steps
AREA_CELL_METRES = 2000.0
# The next step by the same train counts only if it comes within this long (seconds)
NEXT_WITHIN = 900.0

Key = tuple[str, str, str]  # area, from berth, to berth


@dataclass
class Samples:
    points: dict[Key, list[tuple[float, float]]] = field(default_factory=lambda: defaultdict(list))
    moves: dict[Key, list[tuple[float, float]]] = field(default_factory=lambda: defaultdict(list))  # (metres, seconds)
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))


class RouteLine:
    """Points along a route, by metres from its first placed stop."""

    def __init__(self, route: Route, paths):
        pieces = []
        for a, b in route.following.items():
            pieces.append((route.metres[a], _path(route.stops[a], route.stops[b], paths)[0]))
        pieces.sort(key=lambda piece: piece[0])
        self.starts = [start for start, _ in pieces]
        self.lines = [line for _, line in pieces]

    def point(self, metres: float) -> tuple[float, float] | None:
        k = bisect.bisect_right(self.starts, metres) - 1
        if k < 0:
            return None
        line = self.lines[k]
        p = line.interpolate(min(max(metres - self.starts[k], 0.0), line.length))
        return p.x, p.y


def _cell(point: tuple[float, float]) -> tuple[int, int]:
    return int(point[0] // AREA_CELL_METRES), int(point[1] // AREA_CELL_METRES)


def learn(steps: list[tuple], routes: dict[str, Route], paths, samples: Samples):
    """
    Add samples from `steps` ((epoch seconds, area, from, to, headcode), in time order) and the routes of the trains
    running then.
    """
    by_headcode: dict[str, list[tuple[str, Route]]] = defaultdict(list)
    for rid, route in routes.items():
        if route.anchors and route.journey.train_id:
            by_headcode[route.journey.train_id].append((rid, route))
    lines: dict[str, RouteLine] = {}

    def place(rid: str, route: Route, t: float) -> tuple[float, tuple[float, float]] | None:
        metres = route.truth(t)
        if metres is None:
            return None
        if rid not in lines:
            lines[rid] = RouteLine(route, paths)
        point = lines[rid].point(metres)
        return (metres, point) if point is not None else None

    visits: dict[str, list[tuple[float, Key, float]]] = defaultdict(list)  # rid -> (t, step, metres)
    cells: dict[str, set[tuple[int, int]]] = defaultdict(set)
    shared = []
    for t, area, from_berth, to_berth, descr in steps:
        key = (area, from_berth, to_berth)
        running = [(rid, route) for rid, route in by_headcode.get(descr, ())
                   if route.anchors[0][0] - REPORT_MARGIN <= t <= route.anchors[-1][0] + REPORT_MARGIN]
        if not running:
            samples.counts["no train"] += 1
            continue
        if len(running) > 1:
            shared.append((t, key, running))
            continue
        placed = place(*running[0], t)
        if placed is None:
            samples.counts["no truth"] += 1
            continue
        metres, point = placed
        samples.points[key].append(point)
        visits[running[0][0]].append((t, key, metres))
        cells[area].add(_cell(point))
        samples.counts["placed"] += 1

    for t, key, running in shared:
        near = []
        for rid, route in running:
            placed = place(rid, route, t)
            if placed is None:
                continue
            cx, cy = _cell(placed[1])
            if any((cx + dx, cy + dy) in cells[key[0]] for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                near.append((rid, placed))
        if len(near) != 1:
            samples.counts["shared headcode"] += 1
            continue
        rid, (metres, point) = near[0]
        samples.points[key].append(point)
        visits[rid].append((t, key, metres))
        samples.counts["placed, shared headcode"] += 1

    for steps_made in visits.values():
        steps_made.sort()
        for (t1, key, m1), (t2, _, m2) in pairwise(steps_made):
            if 0 < t2 - t1 <= NEXT_WITHIN and m2 > m1:
                samples.moves[key].append((m2 - m1, t2 - t1))


def step_points(samples: Samples) -> list[tuple]:
    """(area, from, to, x, y, samples, spread_m, next_metres, next_seconds) for each step placed well enough."""
    rows = []
    for key, points in samples.points.items():
        if len(points) < MIN_SAMPLES:
            continue
        x = statistics.median(p[0] for p in points)
        y = statistics.median(p[1] for p in points)
        spread = statistics.median(math.dist((x, y), p) for p in points)
        if spread > SPREAD_METRES:
            continue
        moves = samples.moves.get(key)
        next_metres = statistics.median(m for m, _ in moves) if moves else None
        next_seconds = statistics.median(s for _, s in moves) if moves else None
        rows.append((*key, x, y, len(points), spread, next_metres, next_seconds))
    return rows


def update(db: Database, days: int = LEARN_DAYS, end: datetime | None = None) -> int:
    """Learn step points from the last `days` days of berth steps and replace the stored ones. Returns how many."""
    end = end or datetime.now(LONDON)
    began = time.perf_counter()
    paths = PathCache(db.fetch_segment_paths())
    samples = Samples()
    start = end - timedelta(days=days)
    while start < end:
        stop = min(start + CHUNK, end)
        steps = db.fetch_td_steps(start, stop)
        if steps:
            _, routes, _ = load_routes(db, db.fetch_reported_rids(start, stop), paths, TRUTH_OFFSET)
            learn(steps, routes, paths, samples)
        start = stop
    if not samples.points:
        logger.info("No berth steps to learn from")
        return 0
    rows = step_points(samples)
    db.in_transaction(lambda: db.replace_td_step_points(rows), "storing step points")
    logger.info("Placed %d berth steps from %d days (%.0fs): %s", len(rows), days, time.perf_counter() - began,
                dict(samples.counts))
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=float, default=LEARN_DAYS, help="days of steps to learn from (default: %(default)s)")
    args = parser.parse_args()

    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(config.database_url)
    try:
        update(db, args.days)
    finally:
        db.close()


if __name__ == "__main__":
    main()
