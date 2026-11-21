"""
Work out the path along the track between every pair of consecutive placed stops in a day's timetable,
for pairs not already in `segment_paths`.

    uv run src/segment_paths.py [--date YYYY-MM-DD]
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

# Other tracks within this distance of a stop's nearest one are also tried as route ends (metres)
PARALLEL_METRES = 30.0

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
    fallback_reason: str | None
    length: float
    straight: float
    line: LineString  # British National Grid


def segment_path(graph: TrackGraph, start: PlacedTiploc, end: PlacedTiploc) -> SegmentPath:
    straight_line = LineString([start.point, end.point])

    def fallback(reason):
        return SegmentPath(start.tiploc, end.tiploc, "straight", reason, straight_line.length, straight_line.length, straight_line)

    if not start.snaps or not end.snaps:
        return fallback("off_network")
    path = graph.route(start.snaps, end.snaps)
    if path is None:
        return fallback("no_path")
    straight = math.dist(graph.point(start.snaps[0]), graph.point(end.snaps[0]))
    if path.length > MAX_DETOUR * max(straight, 1.0):
        return fallback("detour")
    return SegmentPath(start.tiploc, end.tiploc, "track", None, path.length, straight, path.line)


def update(db: Database, day: date, graph: TrackGraph | None = None) -> Counter:
    """Add paths for the day's new stop pairs. Returns counts by method/fallback reason."""
    if not db.has_track_links():
        logger.info("No track model loaded (src/track_model.py), so no segment paths")
        return Counter()
    pairs = db.fetch_new_segment_pairs(day)
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
    args = parser.parse_args()

    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(config.database_url)
    try:
        update(db, args.date)
    finally:
        db.close()


if __name__ == "__main__":
    main()
