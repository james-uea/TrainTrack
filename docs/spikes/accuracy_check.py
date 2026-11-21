"""
Self-consistency check of the position estimator (stage 7).

For every actual arrival or pass reported at a placed stop B in a window, estimate the train's position one
second before the report (so the estimator can't see it) and measure how far along the track the estimate is
from B. Negative = the estimate is behind the train, positive = ahead of it.

    PYTHONPATH=src uv run docs/spikes/accuracy_check.py --start 2026-11-21T14:05Z --end 2026-11-21T14:51Z
"""

import argparse
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import pairwise

import positions
from config import load_config
from db import Database
from positions import (
    CALL_TYPES,
    PathCache,
    _path,
    _Timeline,
    estimate_position,
    load_journeys,
)


def percentile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else float("nan")


def chain(journey, paths):
    """Cumulative distance along the journey's placed stops: {stop index: metres}, and segment lengths."""
    stops = [s for s in journey.stops if not s.cancelled]
    placed = [i for i, s in enumerate(stops) if s.point is not None]
    cumulative, lengths, total = {}, {}, 0.0
    for a, b in pairwise(placed):
        cumulative.setdefault(a, total)
        length = _path(stops[a], stops[b], paths)[0].length
        lengths[(stops[a].tiploc, stops[b].tiploc)] = length
        total += length
        cumulative[b] = total
    if placed:
        cumulative.setdefault(placed[0], 0.0)
    return stops, cumulative, lengths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=datetime.fromisoformat, required=True)
    parser.add_argument("--end", type=datetime.fromisoformat, required=True)
    parser.add_argument("--hold-minutes", type=float, help="override positions.HOLD_LIMIT, to compare settings")
    args = parser.parse_args()
    if args.hold_minutes is not None:
        positions.HOLD_LIMIT = timedelta(minutes=args.hold_minutes)

    db = Database(load_config().database_url)
    paths = PathCache(db.fetch_segment_paths())
    journeys = load_journeys(db, args.end)
    db.close()

    results = []  # (error_m, time_error_s, confidence, kind, journey, stop, position)
    held_at_silent = 0  # held >1 km out, at a call that never reports all day
    skipped = defaultdict(int)
    for journey in journeys:
        stops, cumulative, lengths = chain(journey, paths)
        placed = sorted(cumulative)
        next_placed = {a: stops[b].tiploc for a, b in pairwise(placed)}
        index_of = {}
        for index, stop in enumerate(stops):
            index_of.setdefault(stop.tiploc, []).append(index)
        for b, stop in enumerate(stops):
            reported = stop.actual_arrival or stop.actual_pass
            if reported is None or not (args.start <= reported < args.end) or b == 0:
                continue
            if b not in cumulative:
                skipped["stop not placed"] += 1
                continue
            at = reported - timedelta(seconds=1)
            position = estimate_position(journey, at, paths)
            if position is None:
                skipped["no position"] += 1
                continue
            # Where the estimate is, in metres along the journey. A TIPLOC visited twice (a reversal, a loop): take
            # the visit nearest B among those heading for the estimate's to_tiploc
            starts = [i for i in index_of[position.from_tiploc] if i in cumulative]
            heading = [i for i in starts if next_placed.get(i) == position.to_tiploc
                       or position.from_tiploc == position.to_tiploc]
            start = min(heading or starts, key=lambda i: abs(i - b))
            along = cumulative[start] + position.fraction * lengths.get((position.from_tiploc, position.to_tiploc), 0.0)
            predicted = _Timeline(stops, at).arrival(b)
            time_error = (predicted - reported).total_seconds() if predicted else None
            kind = "call" if stop.location_type in CALL_TYPES else "pass"
            held_at = stops[next(i for i in sorted(cumulative) if i > start)] if start != max(cumulative) else None
            if (position.state == "held" and abs(along - cumulative[b]) > 1000 and held_at is not None
                    and held_at.actual_arrival is None and held_at.actual_departure is None):
                held_at_silent += 1
            results.append((along - cumulative[b], time_error, position.confidence, kind, journey, stop, position))

    def summary(label, rows):
        errors = [abs(r[0]) for r in rows]
        signed = [r[0] for r in rows]
        times = [r[1] for r in rows if r[1] is not None]
        print(f"{label:24} n={len(rows):6,}  |error| median {percentile(errors, .5):6.0f} m  p90 {percentile(errors, .9):6.0f} m"
              f"  p95 {percentile(errors, .95):6.0f} m  signed median {statistics.median(signed) if signed else 0:6.0f} m"
              f"  time error median {statistics.median(times) if times else 0:5.0f} s  |p90| {percentile([abs(t) for t in times], .9):5.0f} s")

    print(f"{len(results):,} reports measured; skipped {dict(skipped)}")
    summary("all", results)
    for confidence in ("high", "medium", "low"):
        summary(f"confidence {confidence}", [r for r in results if r[2] == confidence])
    for kind in ("call", "pass"):
        summary(kind, [r for r in results if r[3] == kind])
    for state in sorted({r[6].state for r in results}):
        summary(f"state {state}", [r for r in results if r[6].state == state])

    held_far = sum(1 for r in results if r[6].state == "held" and abs(r[0]) > 1000)
    print(f"over 1 km out: {sum(1 for r in results if abs(r[0]) > 1000)}"
          f" ({len({r[4].rid for r in results if abs(r[0]) > 1000})} trains)")
    print(f"held over 1 km out: {held_far}, of which at a call with no report all day: {held_at_silent}")

    print("\nWorst 15:")
    for error, time_error, confidence, kind, journey, stop, position in sorted(results, key=lambda r: -abs(r[0]))[:15]:
        print(f"  {journey.train_id} {journey.rid} at {stop.tiploc} ({kind}) error {error/1000:7.1f} km, time {time_error}, "
              f"est {position.state} {position.from_tiploc}->{position.to_tiploc} {position.fraction:.2f} conf {confidence} "
              f"age {position.last_report_age_s} delay {position.delay_minutes}")


if __name__ == "__main__":
    main()
