"""
Work out the path along the track between every pair of consecutive placed stops in a day's timetable,
for pairs not already in `segment_paths` (or, with --all, every stored pair again).

    uv run src/segment_paths.py [--date YYYY-MM-DD] [--all]
"""

import argparse
import logging
import math
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from shapely.geometry import LineString

from config import load_config
from db import Database
from track_graph import Snap, TrackGraph
from util import LONDON

logger = logging.getLogger("segment_paths")

# A track route longer than this many times the straight distance is drawn straight instead
MAX_DETOUR = 3.0
# Where no route runs without turning back, one that does is kept only if it's at most this many times the straight
# distance: it turns back only a little, near an end. Longer ones were 2 to 3 times it, like Paddington low level to
# Bond Street (6.1 km for 2.1 km), and are drawn straight instead
MAX_REVERSING_DETOUR = 1.25

# Other tracks within this distance of a stop's nearest one are also tried as route ends (metres). A station's
# nearest track may join the line only behind it; with 100 m, 10,315 of 10,519 stored pairs on 25 Nov had a route
# that never turns back, against 9,931 with 30 m
PARALLEL_METRES = 100.0

# A BPLAN point the day's trains would reach and leave faster than this (m/s, so 360 km/h) over more than
# MIN_JUMP_METRES is in the wrong place
MAX_SPEED = 100.0
MIN_JUMP_METRES = 5000.0

# Vertices closer than this to the simplified line are dropped before storing (metres)
SIMPLIFY_METRES = 1.0


@dataclass
class PlacedTiploc:
    tiploc: str
    point: tuple[float, float]  # British National Grid
    snaps: list[Snap]  # nearest track first, then parallel ones; empty when not on Network Rail track


@dataclass
class SegmentPath:
    from_tiploc: str
    to_tiploc: str
    method: str  # track, straight
    fallback_reason: str | None  # why it's straight (off_network, no_path, detour), or "reverses" for a track route that does
    length: float
    straight: float
    line: LineString  # British National Grid


def segment_path(graph: TrackGraph, start: PlacedTiploc, end: PlacedTiploc) -> SegmentPath:
    straight_line = LineString([start.point, end.point])

    def fallback(reason):
        return SegmentPath(start.tiploc, end.tiploc, "straight", reason, straight_line.length, straight_line.length, straight_line)

    if not start.snaps or not end.snaps:
        return fallback("off_network")
    straight = max(math.dist(graph.point(start.snaps[0]), graph.point(end.snaps[0])), 1.0)
    path = graph.route(start.snaps, end.snaps)
    if path is not None and path.length <= MAX_DETOUR * straight:
        return SegmentPath(start.tiploc, end.tiploc, "track", None, path.length, straight, path.line)
    turning = graph.route(start.snaps, end.snaps, reversing=True)
    if turning is not None and turning.length <= MAX_REVERSING_DETOUR * straight:
        return SegmentPath(start.tiploc, end.tiploc, "track", "reverses", turning.length, straight, turning.line)
    return fallback("no_path" if path is None and turning is None else "detour")


def update(db: Database, day: date, graph: TrackGraph | None = None, everything: bool = False) -> Counter:
    """
    Add paths for the day's new stop pairs, or with `everything` route every stored pair again too. Returns counts
    by method/fallback reason.
    """
    if not db.has_track_links():
        logger.info("No track model loaded (src/track_model.py), so no segment paths")
        return Counter()
    flagged = db.flag_implausible_locations(day, MAX_SPEED, MIN_JUMP_METRES)
    if flagged:
        logger.info("%d BPLAN points are too far from their neighbours to be right, now suspect: %s",
                    len(flagged), ", ".join(sorted(flagged)))
    pairs = db.fetch_new_segment_pairs(day)
    if everything:
        pairs = sorted(set(pairs) | set(db.fetch_segment_pairs()))
    if not pairs:
        return Counter()

    start = time.time()
    graph = graph or TrackGraph.from_db(db)
    placed = {
        tiploc: PlacedTiploc(tiploc, (x, y), [Snap(link, along) for link, along in snaps])
        for tiploc, x, y, snaps in db.fetch_placed_tiplocs({tiploc for pair in pairs for tiploc in pair}, PARALLEL_METRES)
    }
    logger.info("Routing %d new stop pairs (graph ready in %.1fs)", len(pairs), time.time() - start)

    paths = [segment_path(graph, placed[a], placed[b]) for a, b in pairs]
    db.add_segment_paths(paths, SIMPLIFY_METRES)
    counts = Counter(path.fallback_reason or path.method for path in paths)
    logger.info("Routed %d stop pairs in %.1fs: %s", len(paths), time.time() - start, dict(counts))
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(LONDON).date(),
                        help="scheduled start date (default: today)")
    parser.add_argument("--all", action="store_true", help="route every stored pair again, as well as new ones")
    args = parser.parse_args()

    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(config.database_url)
    try:
        update(db, args.date, everything=args.all)
    finally:
        db.close()


if __name__ == "__main__":
    main()
