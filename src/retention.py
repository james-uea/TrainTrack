"""
Keep the day-partitioned tables in shape: make partitions for the days ahead, and expire old days.

Raw events older than EVENTS_KEEP_DAYS (default 14) are written to ARCHIVE_DIR (default data/archive) as
`darwin_events-YYYY-MM-DD.jsonl.gz`, one JSON object per message, then their partition is dropped. Recorded map
frames are dropped after FRAMES_KEEP_DAYS (default 0, which keeps them forever); they aren't archived.

    uv run src/retention.py [--dry-run]

The timetable service runs this after each daily load.
"""

import argparse
import gzip
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from config import Config, load_config
from db import Database
from util import LONDON

logger = logging.getLogger("retention")

# Partitions are made this many days ahead, so rows rarely land in a default partition
DAYS_AHEAD = 7


@dataclass(frozen=True)
class Partitioned:
    table: str
    key_column: str
    archive: bool  # write a day's rows to a file before dropping it


EVENTS = Partitioned("darwin_events", "received_at", archive=True)
FRAMES = Partitioned("position_frames", "at", archive=False)
TABLES = (EVENTS, FRAMES)


def partition_day(name: str) -> date:
    return date.fromisoformat(name.rsplit("_", 1)[1])


def ensure_partitions(db: Database, today: date, ahead: int = DAYS_AHEAD) -> list[str]:
    """Make partitions from yesterday to `ahead` days on, for every partitioned table. Returns the ones made."""
    made = []
    for table in TABLES:
        for offset in range(-1, ahead + 1):
            day = today + timedelta(days=offset)
            if db.ensure_day_partition(table.table, table.key_column, day):
                made.append(f"{table.table}_{day:%Y%m%d}")
    db.commit()
    return made


def archive_path(archive_dir: str, table: str, day: date) -> str:
    return os.path.join(archive_dir, f"{table}-{day.isoformat()}.jsonl.gz")


def archive_events(db: Database, partition: str, path: str) -> int:
    """Write every event in `partition` to a gzipped JSON-lines file, in id order. Returns how many."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    partial = path + ".partial"
    count = 0
    # A named cursor streams rows from the server instead of loading the day into memory
    with db.conn.cursor(name="archive") as cur, gzip.open(partial, "wt", encoding="utf-8", compresslevel=6) as out:
        cur.itersize = 5000
        cur.execute(f"""
            SELECT json_build_object(
                'id', id, 'received_at', received_at, 'message_ts', message_ts,
                'push_port_sequence', push_port_sequence, 'kinds', kinds, 'rids', rids, 'payload', payload
            )::TEXT
            FROM {partition} ORDER BY id
        """)  # partition names come from pg_class
        for (line,) in cur:
            out.write(line)
            out.write("\n")
            count += 1
    os.replace(partial, path)
    return count


def expire(db: Database, table: Partitioned, keep_days: int, today: date, archive_dir: str,
           dry_run: bool = False) -> list[str]:
    """
    Drop `table`'s partitions for days more than `keep_days` before `today`, archiving them first if the table is
    archived. `keep_days` of 0 keeps everything. Returns the partitions expired.
    """
    if keep_days <= 0:
        return []
    cutoff = today - timedelta(days=keep_days)
    expired = []
    for name, _ in db.fetch_day_partitions(table.table):
        day = partition_day(name)
        if day >= cutoff:
            continue
        if dry_run:
            logger.info("Would expire %s", name)
            expired.append(name)
            continue
        started = time.perf_counter()
        if table.archive:
            path = archive_path(archive_dir, table.table, day)
            count = archive_events(db, name, path)
            logger.info("Archived %s: %d rows to %s (%.1f MB)", name, count, path, os.path.getsize(path) / 1e6)
        db.drop_partition(name)
        db.commit()
        logger.info("Dropped %s (%.1fs)", name, time.perf_counter() - started)
        expired.append(name)
    return expired


def run(db: Database, config: Config, today: date | None = None, dry_run: bool = False) -> dict[str, list[str]]:
    today = today or datetime.now(LONDON).date()
    keep = {EVENTS.table: config.events_keep_days, FRAMES.table: config.frames_keep_days}
    result = {"made": [] if dry_run else ensure_partitions(db, today), "expired": []}
    for table in TABLES:
        result["expired"] += expire(db, table, keep[table.table], today, config.archive_dir, dry_run)
    # Listing partitions opens a transaction even when nothing is dropped. Left open, it stops vacuum clearing dead
    # rows from every table until the caller's next statement: a day, for the timetable service
    db.commit()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="say what would be expired, change nothing")
    args = parser.parse_args()

    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(config.database_url)
    try:
        result = run(db, config, dry_run=args.dry_run)
        logger.info("Partitions made: %d, expired: %d", len(result["made"]), len(result["expired"]))
    finally:
        db.close()


if __name__ == "__main__":
    main()
