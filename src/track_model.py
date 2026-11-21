"""
Load Network Rail's Track Model track centrelines into `track_links`, replacing what's there.

    uv run src/track_model.py    # newest data/trackmodel/NWR_TrackModel*.zip
"""

import logging
import math
import os
import re
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import shapefile

from config import load_config
from db import Database

logger = logging.getLogger("track_model")

TRACK_MODEL_FILE = re.compile(r"NWR_TrackModel(\d{8})\.zip")

# Link endpoints closer than this are the same node
NODE_TOLERANCE_METRES = 1.0


@dataclass
class TrackLink:
    asset_id: str
    elr: str
    track_id: str | None
    start_miles: float | None
    end_miles: float | None
    points: list[tuple[float, float]]  # British National Grid
    from_node: int = -1
    to_node: int = -1

    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:]))

    def ewkt(self) -> str:
        return "SRID=27700;LINESTRING(" + ",".join(f"{x:.3f} {y:.3f}" for x, y in self.points) + ")"


def latest_track_model(track_dir: str) -> str | None:
    matches = sorted(name for name in os.listdir(track_dir) if TRACK_MODEL_FILE.fullmatch(name))
    return os.path.join(track_dir, matches[-1]) if matches else None


def read_track_links(path: str) -> Iterator[TrackLink]:
    """Centrelines from a Track Model zip (shapefile NWR_TrackCentreLines inside it)."""
    with shapefile.Reader(f"{path}/NWR_TrackCentreLines") as reader:
        for shape, record in zip(reader.iterShapes(), reader.iterRecords(), strict=True):
            if len(shape.points) < 2:
                continue
            yield TrackLink(
                asset_id=str(record["ASSET_ID"]), elr=record["ELR"], track_id=record["TRACK_ID"] or None,
                start_miles=record["START"], end_miles=record["END"],
                points=[(float(x), float(y)) for x, y in shape.points],
            )


class NodeIndex:
    """Numbers points, giving points within `tolerance` of an earlier one that one's number."""

    def __init__(self, tolerance: float = NODE_TOLERANCE_METRES):
        self.tolerance = tolerance
        self.cells: dict[tuple[int, int], list[tuple[int, tuple[float, float]]]] = {}
        self.points: list[tuple[float, float]] = []

    def node(self, point: tuple[float, float]) -> int:
        cx, cy = math.floor(point[0] / self.tolerance), math.floor(point[1] / self.tolerance)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for number, other in self.cells.get((cx + dx, cy + dy), ()):
                    if math.dist(point, other) <= self.tolerance:
                        return number
        number = len(self.points)
        self.points.append(point)
        self.cells.setdefault((cx, cy), []).append((number, point))
        return number


def assign_nodes(links: Iterable[TrackLink], tolerance: float = NODE_TOLERANCE_METRES) -> list[TrackLink]:
    index = NodeIndex(tolerance)
    result = []
    for link in links:
        link.from_node = index.node(link.points[0])
        link.to_node = index.node(link.points[-1])
        result.append(link)
    return result


def load(db: Database, data_dir: str) -> int:
    path = latest_track_model(os.path.join(data_dir, "trackmodel"))
    if path is None:
        raise FileNotFoundError(f"No NWR_TrackModel*.zip in {data_dir}/trackmodel")

    start = time.time()
    links = assign_nodes(read_track_links(path))
    logger.info("Read %d track links from %s (%.1fs)", len(links), path, time.time() - start)
    db.replace_track_links(links)
    logger.info("Loaded track links (%.1fs)", time.time() - start)
    return len(links)


def main():
    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(config.database_url)
    try:
        load(db, config.data_dir)
    finally:
        db.close()


if __name__ == "__main__":
    main()
