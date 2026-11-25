"""
How far the map was from where trains really were, over a stretch of a recorded day.

Every `--every` seconds, each train on the map is placed in metres along its route and compared with where its actual
times put it then: at a stop between its reported arrival and departure, or between the last stop it was reported
leaving and the next it was reported reaching, at an even pace. Darwin's actual times are whole minutes, and most
are rounded to the nearest one rather than cut down (`--truth-offset` moves them).

    uv run src/accuracy.py --day 2026-11-24                     # what the map showed, from the recorded frames
    uv run src/accuracy.py --day 2026-11-24 --source estimate   # today's estimator over the database as it is now
    uv run src/accuracy.py --day 2026-11-24 --start 07:00 --end 10:00 --json before.json

`--source estimate` sees Darwin's forecasts as they were last stored, which are later and better than the ones the
map had on the day, so its errors read lower than the frames'. Use it to compare two versions of the estimator on
the same data, and the frames to say how the map did.
"""

import argparse
import bisect
import json
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise

from config import load_config
from db import Database
from frames import fraction_at, unpack
from positions import (
    Journey,
    PathCache,
    SectionTimes,
    Stop,
    _path,
    estimate_position,
    service_status,
)
from util import LONDON

# Seconds added to each actual time to say when the train was really there. Darwin's actual times are whole minutes.
# Those from train describers (81% on 24 Nov) are rounded to the nearest minute, not cut down: 6% of them were
# published up to 29 s before their minute began, and none earlier
TRUTH_OFFSET = 0.0
# Between two reports further apart than this, an even pace says little about where the train was
MAX_GAP = timedelta(minutes=20)
# An error over this many metres counts as "far out"
FAR = 1000.0
# A journey is loaded for an estimate from this long before its first planned time to this long after its last
# (fetch_journeys_around's window)
BEFORE_FIRST = timedelta(minutes=15)
AFTER_LAST = timedelta(hours=3)


@dataclass
class Route:
    """A journey's placed stops in metres along its route, and where its actual times put it."""
    journey: Journey
    stops: list[Stop]
    metres: dict[int, float]  # placed stop index -> metres from the first placed stop
    following: dict[int, int]  # placed stop index -> the next placed stop's index
    by_tiploc: dict[str, list[int]]
    anchors: list[tuple[float, float]]  # (epoch seconds, metres), in time order
    starts_at_origin: bool  # its first anchor is leaving the first placed stop
    ends_at_destination: bool  # its last anchor is arriving at the last stop

    @property
    def times(self) -> list[float]:
        return [t for t, _ in self.anchors]

    def truth(self, t: float, times: list[float] | None = None) -> float | None:
        """Metres along the route at epoch `t` from the actual times, or None where they don't say."""
        anchors = self.anchors
        if not anchors:
            return None
        if t < anchors[0][0]:
            return anchors[0][1] if self.starts_at_origin else None
        if t > anchors[-1][0]:
            return anchors[-1][1] if self.ends_at_destination else None
        k = bisect.bisect_right(times if times is not None else self.times, t)
        if k >= len(anchors):
            return anchors[-1][1]
        (t0, m0), (t1, m1) = anchors[k - 1], anchors[k]
        if t1 - t0 > MAX_GAP.total_seconds():
            return None
        return m1 if t1 <= t0 else m0 + (m1 - m0) * (t - t0) / (t1 - t0)

    def in_service(self, t: float) -> bool:
        """Between the train's first and last report."""
        return bool(self.anchors) and self.anchors[0][0] <= t <= self.anchors[-1][0]

    def drawn(self, from_tiploc: str, to_tiploc: str, fraction: float, near: float | None) -> float | None:
        """Metres along the route of a position given as a fraction from one placed stop to the next."""
        starts = self.by_tiploc.get(from_tiploc, [])
        if from_tiploc != to_tiploc:
            heading = [i for i in starts if i in self.following and self.stops[self.following[i]].tiploc == to_tiploc]
            starts = heading or starts
        if not starts:
            return None
        start = min(starts, key=lambda i: abs(self.metres[i] - near)) if near is not None else starts[0]
        if from_tiploc == to_tiploc or start not in self.following:
            return self.metres[start]
        end = self.following[start]
        return self.metres[start] + fraction * (self.metres[end] - self.metres[start])


def build_route(journey: Journey, paths, truth_offset: float = TRUTH_OFFSET) -> Route:
    stops = [stop for stop in journey.stops if not stop.cancelled]
    placed = [index for index, stop in enumerate(stops) if stop.point is not None]
    metres: dict[int, float] = {}
    total = 0.0
    for a, b in pairwise(placed):
        metres.setdefault(a, total)
        total += _path(stops[a], stops[b], paths)[0].length
        metres[b] = total
    if placed:
        metres.setdefault(placed[0], 0.0)
    by_tiploc: dict[str, list[int]] = defaultdict(list)
    for index in placed:
        by_tiploc[stops[index].tiploc].append(index)

    anchors: list[tuple[float, float]] = []
    first_kind = last_kind = None
    for index in placed:
        stop = stops[index]
        arrived = stop.actual_arrival or stop.actual_pass
        left = stop.actual_departure or stop.actual_pass
        for kind, when in (("arrived", arrived), ("left", left)):
            if when is None:
                continue
            t = when.timestamp() + truth_offset
            if anchors and t < anchors[-1][0]:
                continue  # out of order: a report that can't be right
            if anchors and anchors[-1] == (t, metres[index]):
                continue
            anchors.append((t, metres[index]))
            if first_kind is None:
                first_kind = (index, kind)
            last_kind = (index, kind)
    return Route(
        journey, stops, metres, dict(pairwise(placed)), dict(by_tiploc), anchors,
        starts_at_origin=bool(placed) and first_kind == (placed[0], "left") and placed[0] == 0,
        ends_at_destination=bool(placed) and last_kind == (placed[-1], "arrived") and placed[-1] == len(stops) - 1,
    )


@dataclass
class Sample:
    t: float
    rid: str
    toc: str | None
    state: str
    from_tiploc: str
    to_tiploc: str
    error: float  # metres: the map's position minus the truth; positive = ahead of the train


@dataclass
class Tally:
    """Everything measured over a run."""
    samples: list[Sample] = field(default_factory=list)
    moments: int = 0
    shown: int = 0  # train-moments on the map
    in_service: int = 0  # train-moments between a train's first and last report
    missing: int = 0  # in service but not on the map
    unknown: Counter = field(default_factory=Counter)  # on the map, but the actual times can't say where


def sample_times(start: datetime, end: datetime, every: timedelta) -> list[datetime]:
    times, at = [], start
    while at < end:
        times.append(at)
        at += every
    return times


def frame_moments(rows: Iterable[tuple], times: list[datetime]) -> Iterator[tuple[datetime, dict[str, dict]]]:
    """
    The trains the map showed at each of `times`, from recorded frames (at, keyframe, source, data) oldest first:
    each train as last sent, placed along its segment for that moment as the map does.
    """
    trains: dict[str, dict] = {}
    rows = iter(rows)
    pending = next(rows, None)
    for at in times:
        while pending is not None and pending[0] <= at:
            frame = unpack(pending[3])
            if pending[1] or "removed" not in frame:
                trains = {train["rid"]: train for train in frame["trains"]}
            else:
                for rid in frame["removed"]:
                    trains.pop(rid, None)
                for train in frame["trains"]:
                    trains[train["rid"]] = train
            pending = next(rows, None)
        if trains:
            yield at, {rid: {**train, "fraction": fraction_at(train, at)} for rid, train in trains.items()}


def estimate_moments(journeys: list[Journey], paths, times: list[datetime]) -> Iterator[tuple[datetime, dict[str, dict]]]:
    """The trains today's estimator places at each of `times`, as the live map would, from the journeys given."""
    spans = []
    for journey in journeys:
        planned = [t for stop in journey.stops for t in (stop.planned_departure, stop.planned_arrival) if t]
        if planned:
            spans.append((min(planned) - BEFORE_FIRST, max(planned) + AFTER_LAST, journey))
    for at in times:
        around = [journey for first, last, journey in spans if first <= at <= last]
        sections = SectionTimes(around, at)
        trains = {}
        for journey in around:
            position = estimate_position(journey, at, paths, sections)
            if position is not None:
                trains[journey.rid] = {"state": position.state, "from_tiploc": position.from_tiploc,
                                       "to_tiploc": position.to_tiploc, "fraction": position.fraction}
        yield at, trains


def measure(moments: Iterable[tuple[datetime, dict[str, dict]]], routes: dict[str, Route]) -> Tally:
    tally = Tally()
    times = {rid: route.times for rid, route in routes.items()}
    for at, trains in moments:
        t = at.timestamp()
        tally.moments += 1
        tally.shown += len(trains)
        for rid, route in routes.items():
            if route.in_service(t):
                tally.in_service += 1
                if rid not in trains:
                    tally.missing += 1
        for rid, train in trains.items():
            route = routes.get(rid)
            truth = route.truth(t, times[rid]) if route else None
            if truth is None:
                tally.unknown[_why_unknown(route, t)] += 1
                continue
            drawn = route.drawn(train["from_tiploc"], train["to_tiploc"], train["fraction"], truth)
            if drawn is None:
                tally.unknown["not on its route"] += 1
                continue
            tally.samples.append(Sample(t, rid, route.journey.toc, train["state"], train["from_tiploc"],
                                        train["to_tiploc"], drawn - truth))
    return tally


def _why_unknown(route: Route | None, t: float) -> str:
    if route is None or not route.anchors:
        return "never reported"
    if t < route.anchors[0][0]:
        return "before its first report"
    if t > route.anchors[-1][0]:
        return "after its last report"
    return f"reports over {MAX_GAP.total_seconds() / 60:.0f} min apart"


def percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else float("nan")


def stats(samples: list[Sample]) -> dict:
    errors = [abs(s.error) for s in samples]
    return {
        "samples": len(samples),
        "trains": len({s.rid for s in samples}),
        "median_m": round(percentile(errors, .5)),
        "p90_m": round(percentile(errors, .9)),
        "p95_m": round(percentile(errors, .95)),
        "p99_m": round(percentile(errors, .99)),
        "far_pct": round(100 * sum(e > FAR for e in errors) / len(errors), 2) if errors else None,
        "signed_median_m": round(statistics.median(s.error for s in samples)) if samples else None,
    }


def report(tally: Tally, worst: int = 25) -> dict:
    samples = tally.samples
    by_hour: dict[int, list[Sample]] = defaultdict(list)
    by_state: dict[str, list[Sample]] = defaultdict(list)
    by_toc: dict[str, list[Sample]] = defaultdict(list)
    far: dict[tuple[str, str, str], list[Sample]] = defaultdict(list)
    for sample in samples:
        by_hour[datetime.fromtimestamp(sample.t, LONDON).hour].append(sample)
        by_state[sample.state].append(sample)
        by_toc[sample.toc or "?"].append(sample)
        if abs(sample.error) > FAR:
            far[(sample.state, sample.from_tiploc, sample.to_tiploc)].append(sample)
    return {
        "overall": stats(samples),
        "coverage": {
            "moments": tally.moments,
            "shown": tally.shown,
            "in_service": tally.in_service,
            "missing": tally.missing,
            "missing_pct": round(100 * tally.missing / tally.in_service, 2) if tally.in_service else None,
            "unknown": dict(tally.unknown.most_common()),
        },
        "by_hour": {hour: stats(rows) for hour, rows in sorted(by_hour.items())},
        "by_state": {state: stats(rows) for state, rows in sorted(by_state.items())},
        "by_toc": {toc: stats(rows) for toc, rows in sorted(by_toc.items(), key=lambda kv: -len(kv[1]))},
        "far_by_segment": [
            {"state": state, "from": a, "to": b, "samples": len(rows), "trains": len({s.rid for s in rows}),
             "signed_median_m": round(statistics.median(s.error for s in rows)), "example": rows[0].rid}
            for (state, a, b), rows in sorted(far.items(), key=lambda kv: -len(kv[1]))[:worst]
        ],
    }


def print_report(result: dict, label: str):
    def line(name, s):
        if not s["samples"]:
            return f"{name:22} none"
        return (f"{name:22} n={s['samples']:8,} trains={s['trains']:6,}  median {s['median_m']:6,} m  p90 {s['p90_m']:6,}"
                f"  p95 {s['p95_m']:6,}  p99 {s['p99_m']:7,}  >1 km {s['far_pct']:5.2f}%  signed {s['signed_median_m']:+6,}")
    print(label)
    print(line("all", result["overall"]))
    coverage = result["coverage"]
    print(f"coverage: {coverage['moments']} moments, {coverage['shown']:,} shown, {coverage['in_service']:,} in service, "
          f"missing {coverage['missing']:,} ({coverage['missing_pct']}%), no truth {coverage['unknown']}")
    print("\nBy state:")
    for state, s in result["by_state"].items():
        print(line(state, s))
    print("\nBy hour (UK):")
    for hour, s in result["by_hour"].items():
        print(line(f"{int(hour):02d}:00", s))
    print("\nBy operator (largest 15):")
    for toc, s in list(result["by_toc"].items())[:15]:
        print(line(toc, s))
    print("\nOver 1 km out, by segment:")
    for row in result["far_by_segment"]:
        print(f"  {row['state']:10} {row['from']:8} -> {row['to']:8} samples {row['samples']:5}  trains {row['trains']:4}"
              f"  signed median {row['signed_median_m']:+8,} m  e.g. {row['example']}")


def load_routes(db: Database, rids: list[str], paths, truth_offset: float) -> tuple[list[Journey], dict[str, Route]]:
    journeys: dict[str, Journey] = {}
    for rid, train_id, toc, cancelled, deactivated in db.fetch_journeys(rids):
        journeys[rid] = Journey(rid, [], train_id, toc, bool(cancelled), bool(deactivated))
    for row in db.fetch_position_stops(list(journeys)):
        rid, tiploc, location_type, x, y, *times, cancelled = row
        journeys[rid].stops.append(Stop(tiploc, location_type, (x, y) if x is not None else None, *times, cancelled=cancelled))
    return list(journeys.values()), {rid: build_route(j, paths, truth_offset) for rid, j in journeys.items()}


def window(day: date, start: str | None, end: str | None) -> tuple[datetime, datetime]:
    """A stretch of a UK day, from HH:MM to HH:MM (default: the whole day)."""
    midnight = datetime.combine(day, datetime.min.time(), LONDON)
    def at(text, default):
        if not text:
            return default
        hours, minutes = (int(part) for part in text.split(":"))
        return midnight + timedelta(hours=hours, minutes=minutes)
    return at(start, midnight), at(end, datetime.combine(day + timedelta(days=1), datetime.min.time(), LONDON))


def main(argv: list[str] | None = None, progress: Callable[[str], None] = print):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--day", type=date.fromisoformat, required=True, help="UK day, YYYY-MM-DD")
    parser.add_argument("--start", help="UK time HH:MM (default: midnight)")
    parser.add_argument("--end", help="UK time HH:MM (default: the next midnight)")
    parser.add_argument("--every", type=int, default=60, help="seconds between moments measured (default: %(default)s)")
    parser.add_argument("--source", choices=("frames", "estimate"), default="frames")
    parser.add_argument("--truth-offset", type=float, default=TRUTH_OFFSET,
                        help="seconds added to each actual time (default: %(default)s)")
    parser.add_argument("--json", metavar="FILE", help="write the report as JSON")
    args = parser.parse_args(argv)
    start, end = window(args.day, args.start, args.end)
    times = sample_times(start, end, timedelta(seconds=args.every))

    began = time.perf_counter()
    db = Database(load_config().database_url)
    try:
        paths = PathCache(db.fetch_segment_paths())
        frames = db.fetch_frames(start, end) if args.source == "frames" else []
        rids = set(db.fetch_reported_rids(start, end))
        for _, _, _, data in frames:
            rids.update(train["rid"] for train in unpack(data)["trains"])
        journeys, routes = load_routes(db, sorted(rids), paths, args.truth_offset)
    finally:
        db.close()
    progress(f"Loaded {len(frames):,} frames and {len(routes):,} journeys in {time.perf_counter() - began:.1f} s")

    if args.source == "frames":
        moments = frame_moments(frames, times)
    else:
        moments = estimate_moments([j for j in journeys if service_status(j, end) != "cancelled"], paths, times)
    tally = measure(moments, routes)
    result = report(tally)
    result["run"] = {"day": args.day.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
                     "every_s": args.every, "source": args.source, "truth_offset_s": args.truth_offset,
                     "seconds": round(time.perf_counter() - began, 1)}
    print_report(result, f"{args.source} {start:%Y-%m-%d %H:%M}-{end:%H:%M} UK, every {args.every} s, "
                         f"truth = actual minute + {args.truth_offset:g} s")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(result, f, indent=1)
    return result


if __name__ == "__main__":
    main()
