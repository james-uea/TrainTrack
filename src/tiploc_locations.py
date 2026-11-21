"""
Load coordinates for TIPLOCs into `tiploc_locations`, for placing trains on the map.

Sources, highest precedence first:
  * reference/tiploc_overrides.csv: hand fixes (tiploc,lat,lon,note), kept in git
  * NaPTAN (data/naptan/Stops.csv): rail stations, ATCOCode 9100 + TIPLOC
  * Network Rail BPLAN (data/bplan/PIF*.txt.gz): every TIPLOC, including junctions and sidings,
    but some points are placeholders or far out

    uv run src/tiploc_locations.py
"""

import argparse
import csv
import gzip
import logging
import math
import os
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime

from pyproj import Transformer

from config import load_config
from db import Database
from util import LONDON

logger = logging.getLogger("tiploc_locations")

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERRIDES_FILE = os.path.join(REPO_DIR, "reference", "tiploc_overrides.csv")

# NaPTAN and BPLAN disagreeing by more than this means one of them is wrong
SUSPECT_DISTANCE_METRES = 2000

# BPLAN fills unknown coordinates with these instead of leaving them blank
BPLAN_PLACEHOLDERS = {(666666, 666666), (111111, 222222), (99999, 99999), (1, 1)}

# British National Grid (OSGB36) to WGS84 lon/lat
TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


@dataclass
class GridPoint:
    tiploc: str
    name: str | None
    easting: int
    northing: int


@dataclass
class TiplocLocation:
    tiploc: str
    name: str | None
    lon: float
    lat: float
    easting: int | None
    northing: int | None
    source: str  # naptan, bplan, override
    quality: str  # good, suspect


def valid_grid(easting: int, northing: int) -> bool:
    """Inside Great Britain's grid, and not one of BPLAN's placeholder values."""
    return 0 < easting < 700000 and 0 < northing < 1300000 and (easting, northing) not in BPLAN_PLACEHOLDERS


def to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """(lon, lat) for a British National Grid reference."""
    lon, lat = TO_WGS84.transform(easting, northing)
    return lon, lat


def distance(a: GridPoint, b: GridPoint) -> float:
    return math.hypot(a.easting - b.easting, a.northing - b.northing)


# NaPTAN

def read_naptan(lines: Iterable[str]) -> dict[str, GridPoint]:
    """Rail stations from NaPTAN's Stops.csv, by TIPLOC. Active stops win over inactive ones."""
    found: dict[str, tuple[bool, GridPoint]] = {}
    for row in csv.DictReader(lines):
        code = row.get("ATCOCode") or ""
        if row.get("StopType") != "RLY" or not code.startswith("9100") or len(code) <= 4:
            continue
        try:
            easting, northing = int(float(row["Easting"])), int(float(row["Northing"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not valid_grid(easting, northing):
            continue

        active = row.get("Status") == "active"
        tiploc = code[4:]
        if tiploc in found and found[tiploc][0] and not active:
            continue
        found[tiploc] = (active, GridPoint(tiploc, row.get("CommonName") or None, easting, northing))
    return {tiploc: point for tiploc, (_, point) in found.items()}


# BPLAN

BPLAN_FILE = re.compile(r"PIF\d+\.txt\.gz")


def bplan_validity(header: str) -> tuple[date, date] | None:
    """The period a BPLAN file covers, from its PIF header record (fields 4 and 5, dd-mm-YYYY)."""
    fields = header.rstrip("\r\n").split("\t")
    if len(fields) < 6 or fields[0] != "PIF":
        return None
    try:
        return parse_dmy(fields[4]), parse_dmy(fields[5])
    except ValueError:
        return None


def parse_dmy(value: str) -> date:
    """`dd-mm-YYYY` (anything after the date, like a time, is ignored)."""
    day, month, year = value[:10].split("-")
    return date(int(year), int(month), int(day))


def pick_bplan(bplan_dir: str, today: date) -> str | None:
    """The BPLAN file valid today. If several are, the one that started most recently."""
    best: tuple[date, str] | None = None
    for name in sorted(os.listdir(bplan_dir)):
        if not BPLAN_FILE.fullmatch(name):
            continue
        path = os.path.join(bplan_dir, name)
        with gzip.open(path, "rt", encoding="latin-1") as f:
            validity = bplan_validity(f.readline())
        if validity and validity[0] <= today <= validity[1] and (best is None or validity[0] >= best[0]):
            best = (validity[0], path)
    return best[1] if best else None


def read_bplan(lines: Iterable[str]) -> dict[str, GridPoint]:
    """BPLAN LOC records with usable coordinates, by TIPLOC: [2] TIPLOC, [3] name, [6] easting, [7] northing."""
    points = {}
    for line in lines:
        if not line.startswith("LOC\t"):
            continue
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) < 8:
            continue
        try:
            easting, northing = int(fields[6] or 0), int(fields[7] or 0)
        except ValueError:
            continue
        if valid_grid(easting, northing):
            points[fields[2]] = GridPoint(fields[2], fields[3] or None, easting, northing)
    return points


# Overrides

def read_overrides(lines: Iterable[str]) -> dict[str, tuple[float, float]]:
    """Hand-kept fixes, tiploc -> (lon, lat)."""
    overrides = {}
    for row in csv.DictReader(lines):
        try:
            overrides[row["tiploc"].strip()] = (float(row["lon"]), float(row["lat"]))
        except (KeyError, TypeError, ValueError):
            logger.warning("Skipping bad override row %s", row)
    return overrides


# Combining

def combine(
    naptan: dict[str, GridPoint],
    bplan: dict[str, GridPoint],
    overrides: dict[str, tuple[float, float]],
) -> Iterator[TiplocLocation]:
    """One location per TIPLOC: override, then NaPTAN, then BPLAN."""
    for tiploc in sorted(set(naptan) | set(bplan) | set(overrides)):
        station, network = naptan.get(tiploc), bplan.get(tiploc)
        # BPLAN names are shorter ("Norwich", not "Norwich Rail Station")
        name = next((point.name for point in (network, station) if point and point.name), None)

        if tiploc in overrides:
            lon, lat = overrides[tiploc]
            yield TiplocLocation(tiploc, name, lon, lat, None, None, "override", "good")
            continue

        point = station or network
        assert point is not None
        disagree = station is not None and network is not None and distance(station, network) > SUSPECT_DISTANCE_METRES
        lon, lat = to_wgs84(point.easting, point.northing)
        yield TiplocLocation(
            tiploc, name, lon, lat, point.easting, point.northing,
            "naptan" if station else "bplan", "suspect" if disagree else "good",
        )


def load(db: Database, data_dir: str, overrides_file: str = OVERRIDES_FILE, today: date | None = None) -> Counter:
    """Read every source and upsert into tiploc_locations. Returns counts by (source, quality)."""
    today = today or datetime.now(LONDON).date()

    naptan_file = os.path.join(data_dir, "naptan", "Stops.csv")
    with open(naptan_file, encoding="utf-8", errors="replace", newline="") as f:
        naptan = read_naptan(f)
    logger.info("NaPTAN: %d rail stations from %s", len(naptan), naptan_file)

    bplan_file = pick_bplan(os.path.join(data_dir, "bplan"), today)
    if bplan_file is None:
        raise FileNotFoundError(f"No BPLAN file in {data_dir}/bplan valid on {today}")
    with gzip.open(bplan_file, "rt", encoding="latin-1") as f:
        bplan = read_bplan(f)
    logger.info("BPLAN: %d locations with coordinates from %s", len(bplan), bplan_file)

    overrides: dict[str, tuple[float, float]] = {}
    if os.path.exists(overrides_file):
        with open(overrides_file, encoding="utf-8", newline="") as f:
            overrides = read_overrides(f)
    logger.info("Overrides: %d", len(overrides))

    locations = list(combine(naptan, bplan, overrides))
    db.add_tiploc_locations(locations)
    if db.snap_tiploc_locations():
        logger.info("Snapped locations to the track model")
    return Counter(db.count_tiploc_locations())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--overrides", default=OVERRIDES_FILE, help="overrides CSV (default: %(default)s)")
    args = parser.parse_args()

    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(config.database_url)
    try:
        counts = load(db, config.data_dir, args.overrides)
        for (source, quality), count in sorted(counts.items()):
            print(f"{source:9} {quality:8} {count:6}")
        print(f"{'total':18} {sum(counts.values()):6}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
