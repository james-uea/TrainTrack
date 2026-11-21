"""
Report how much of a day's timetable can be placed on the map: headline percentages, and the TIPLOCs
without a usable location, busiest first.

    uv run src/coverage_report.py [--date YYYY-MM-DD] [--limit N]
"""

import argparse
from datetime import date, datetime

from config import load_config
from db import Database
from util import LONDON


def percent(placed: int, total: int) -> str:
    return f"{100 * placed / total:.1f}%" if total else "n/a"


def summary_line(coverage: dict[str, tuple[int, int]]) -> str:
    """One line for logs, e.g. `passenger calls 97.5%, all calls 96.5%, ...`."""
    return ", ".join(f"{kind} {percent(*counts)}" for kind, counts in coverage.items())


def report(db: Database, day: date, limit: int) -> str:
    coverage = db.fetch_coverage(day)
    lines = [f"Coverage for trains scheduled on {day}", ""]
    for kind, (placed, total) in coverage.items():
        lines.append(f"  {kind:22} {percent(placed, total):>6}  ({placed:,} of {total:,})")

    lines += ["", f"  {'TIPLOC':8} {'Name':32} {'Reason':11} {'Calling':>7} {'Passing':>7}"]
    for tiploc, name, reason, calling, passing in db.fetch_unplaced_tiplocs(day, limit):
        lines.append(f"  {tiploc:8} {(name or '')[:32]:32} {reason:11} {calling:7} {passing:7}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(LONDON).date(),
                        help="scheduled start date (default: today)")
    parser.add_argument("--limit", type=int, default=25, help="unplaced TIPLOCs to list (default: %(default)s)")
    args = parser.parse_args()

    db = Database(load_config().database_url)
    try:
        print(report(db, args.date, args.limit))
    finally:
        db.close()


if __name__ == "__main__":
    main()
