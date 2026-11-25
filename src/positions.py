"""
Estimate where trains are at a moment in time, from their stops' planned, forecast and actual times and the
track paths between stops.

`estimate_position` is pure: it takes the journey, the time, a source of paths and other trains' recent run times,
so the live map and a replay of past data can both use it.

    uv run src/positions.py [--at ISO_TIME] [--limit N] [--geojson out.geojson]
"""

import argparse
import bisect
import json
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

import shapely
from pyproj import Geod, Transformer
from shapely.geometry import LineString, Point

from config import load_config
from db import Database
from util import LONDON

CALL_TYPES = {"OR", "IP", "DT", "OPOR", "OPIP", "OPDT"}

# A train is shown this long before it's due to leave its origin, and this long after it arrives at its destination
SHOW_BEFORE_DEPARTURE = timedelta(minutes=15)
SHOW_AFTER_ARRIVAL = timedelta(minutes=5)
# With no report for this long, a train has probably stopped running (Darwin doesn't always say)
STALE_REPORT = timedelta(minutes=60)
# Report ages for confidence
FRESH_REPORT = timedelta(minutes=10)
OLD_REPORT = timedelta(minutes=15)
# A train due at a call that hasn't reported is held there for this long, then assumed to have gone through it
# unreported: many calls (request stops, lines without train describer coverage) never report. A time limit
# needs no list of which calls report, which would go stale. On the 21 Nov replay 3 minutes gave fewer estimates
# over 1 km out than 5, 10 or no limit (docs/spikes/milestone2-data-spike.md)
HOLD_LIMIT = timedelta(minutes=3)
# ...and only if it was at least this late at its last report (minutes; None holds any train). An on-time train
# that doesn't report at a call has most likely gone through a call that never reports. On the 21 Nov 14:05-14:51
# check, 3 cut held estimates over 1 km out from 13 to 2 and p95 error from 1,964 to 1,962 m; 5 was no better
HOLD_MIN_DELAY: int | None = 3
# A train running between two stops isn't expected at the second sooner than other trains have recently taken
# over the same pair: the median of their runs in this window, if there are at least this many. On the 24 Nov
# 07:00-09:00 replay, this and never aiming sooner than planned + delay cut map pull-backs from 9.7 to 7.5 per
# train-hour, and those over 1 km from 2.9 to 1.5 (.memory/rubber-banding-bench.md)
SECTION_WINDOW = timedelta(minutes=30)
SECTION_MIN_RUNS = 2
# A call no train has reported at in this window, though at least SILENT_MIN_TRAINS went through it (they reported
# further on), doesn't report: a train isn't held short of it. Request stops on the Far North, Kyle and Cumbrian Coast
# lines held late trains up to 44 km from where they were on 21 Nov
SILENT_WINDOW = timedelta(hours=3)
SILENT_MIN_TRAINS = 2
# How far ahead along the path to look for the bearing (metres)
BEARING_LOOKAHEAD = 25.0
# Train Describer: a train's latest berth step, where td_berths.py has learned where it happens, places the train
# more closely than its Darwin reports: at the signal it last passed, then on at the usual pace from there, never
# past where trains usually step again. Steps before the train's latest Darwin report aren't used, nor steps older
# than BERTH_WINDOW, after which the train has more likely stepped somewhere not yet learned than stood still. On
# 25 Nov 20:15-21:00, with steps learned from 19:07-20:15, running trains' p95 error against their own later steps
# fell from 1,698 m to 1,056 m (median 337 m to 79 m); 90 s did better than 10, 3 or 1 minutes
BERTH_WINDOW = timedelta(seconds=90)
# A step counts for a train if its point is this close to the train's path (metres), within this many placed stops
# beyond its latest report; only its newest few steps are tried
BERTH_MATCH_METRES = 300.0
BERTH_LOOKAHEAD = 4
BERTH_TRIES = 3
# A train standing at a call counts as gone once a step puts it this far along the next segment (metres)
DEPARTED_METRES = 300.0
# Where a step's next step isn't known: how far a train may go past it, and at what pace (metres, m/s)
DEFAULT_BERTH_METRES = 1000.0
DEFAULT_BERTH_PACE = 20.0

TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
TO_GRID = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
GEOD = Geod(ellps="WGS84")


@dataclass
class Stop:
    tiploc: str
    location_type: str
    point: tuple[float, float] | None  # British National Grid; None when the location isn't usable
    working_arrival: datetime | None = None
    working_departure: datetime | None = None
    working_pass: datetime | None = None
    estimated_arrival: datetime | None = None
    estimated_departure: datetime | None = None
    estimated_pass: datetime | None = None
    actual_arrival: datetime | None = None
    actual_departure: datetime | None = None
    actual_pass: datetime | None = None
    cancelled: bool = False

    @property
    def is_call(self) -> bool:
        return self.location_type in CALL_TYPES

    @property
    def planned_arrival(self) -> datetime | None:
        return self.working_arrival or self.working_pass or self.working_departure

    @property
    def planned_departure(self) -> datetime | None:
        return self.working_departure or self.working_pass or self.working_arrival


@dataclass
class Journey:
    rid: str
    stops: list[Stop]
    train_id: str | None = None
    toc: str | None = None
    cancelled: bool = False
    deactivated: bool = False


@dataclass
class Position:
    lat: float
    lon: float
    bearing: float | None  # degrees clockwise from north
    state: str  # not_started, dwelling, running, held, terminated
    confidence: str  # high, medium, low
    from_tiploc: str
    to_tiploc: str
    fraction: float  # along from_tiploc -> to_tiploc
    delay_minutes: int | None  # at the last report; None with no reports yet
    last_report_age_s: float | None
    left: datetime | None = None  # when it left from_tiploc, while running or held
    due: datetime | None = None  # when it's expected at to_tiploc, while running or held


# A source of track paths: (from_tiploc, to_tiploc) -> (line in British National Grid, method), or None
PathSource = Callable[[str, str], tuple[LineString, str] | None]


class SectionTimes:
    """
    How long trains have recently taken between consecutive reported stops, from their actual times: the state of
    the line, which a single train's forecast doesn't know about. Also which calls trains have gone through lately
    without any reporting there.
    """

    def __init__(self, journeys: Iterable[Journey], at: datetime):
        self.runs: dict[tuple[str, str], list[tuple[datetime, float]]] = defaultdict(list)
        calls: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # TIPLOC -> [trains reported there, went through]
        since = at - SECTION_WINDOW
        for journey in journeys:
            self._count_calls(journey, at, calls)
            previous: tuple[str, datetime] | None = None  # the latest reported stop: (TIPLOC, when it left)
            for stop in journey.stops:
                if stop.cancelled or stop.point is None:
                    continue
                arrived = stop.actual_arrival or stop.actual_pass
                left = stop.actual_departure or stop.actual_pass
                if (arrived and arrived > at) or (not arrived and not left):
                    if arrived:
                        break  # a replay: this and later reports haven't happened yet
                    continue  # no report here: the run carries on to the next stop that has one
                if previous and arrived and arrived >= since:
                    self.runs[(previous[0], stop.tiploc)].append((arrived, (arrived - previous[1]).total_seconds()))
                previous = (stop.tiploc, left) if left and left <= at else None

        self.silent = {tiploc for tiploc, (reported, through) in calls.items()
                       if reported == 0 and through >= SILENT_MIN_TRAINS}

    @staticmethod
    def _count_calls(journey: Journey, at: datetime, calls: dict[str, list[int]]):
        """Count each recent call the train has reached (it reported there or further on) as reported there or not."""
        def reported(stop: Stop) -> bool:
            return any(t is not None and t <= at for t in (stop.actual_arrival, stop.actual_departure, stop.actual_pass))
        latest = next((index for index in range(len(journey.stops) - 1, -1, -1) if reported(journey.stops[index])), None)
        for stop in journey.stops[:latest + 1] if latest is not None else ():
            planned = stop.planned_arrival
            if stop.is_call and not stop.cancelled and planned is not None and planned >= at - SILENT_WINDOW:
                calls[stop.tiploc][0 if reported(stop) else 1] += 1

    def typical_run(self, from_tiploc: str, to_tiploc: str, at: datetime) -> timedelta | None:
        """The median run from one stop to the other among trains that finished it recently, if enough did."""
        recent = [run for arrived, run in self.runs.get((from_tiploc, to_tiploc), ()) if at - SECTION_WINDOW <= arrived <= at]
        if len(recent) < SECTION_MIN_RUNS:
            return None
        return timedelta(seconds=statistics.median(recent))



@dataclass(frozen=True)
class StepPoint:
    """Where a berth step happens (British National Grid), and the usual distance and time to a train's next step."""
    x: float
    y: float
    next_metres: float | None = None
    next_seconds: float | None = None

    @property
    def berth_metres(self) -> float:
        return self.next_metres or DEFAULT_BERTH_METRES

    @property
    def pace(self) -> float:
        if self.next_metres and self.next_seconds:
            return self.next_metres / self.next_seconds
        return DEFAULT_BERTH_PACE


class BerthSteps:
    """Trains' recent Train Describer berth steps by headcode, for the steps whose points are known."""

    def __init__(self, points: dict[tuple[str, str, str], StepPoint]):
        self.points = points
        self.recent: dict[str, list[tuple[float, StepPoint]]] = defaultdict(list)
        self._seen: set[tuple] = set()
        self._fixes: dict[tuple[str, float], tuple[int, int, float] | None] = {}  # (rid, step time) -> segment, metres

    def add(self, rows: Iterable[tuple]):
        """Add (epoch seconds, area, from berth, to berth, headcode) steps; ones already added are skipped."""
        for row in rows:
            if row in self._seen:
                continue
            self._seen.add(row)
            point = self.points.get(row[1:4])
            if point is not None:
                bisect.insort(self.recent[row[4]], (row[0], point), key=lambda step: step[0])

    def prune(self, before: datetime):
        """Forget steps made before `before`."""
        cutoff = before.timestamp()
        for headcode in list(self.recent):
            steps = self.recent[headcode]
            del steps[:bisect.bisect_left(steps, cutoff, key=lambda step: step[0])]
            if not steps:
                del self.recent[headcode]
        self._seen = {row for row in self._seen if row[0] >= cutoff}
        self._fixes = {key: fix for key, fix in self._fixes.items() if key[1] >= cutoff}

    def clear(self):
        self.recent.clear()
        self._seen.clear()
        self._fixes.clear()

    def latest(self, headcode: str | None, at: datetime) -> list[tuple[float, StepPoint]]:
        """The headcode's newest steps at or before `at` and within BERTH_WINDOW of it, newest first."""
        steps = self.recent.get(headcode) if headcode else None
        if not steps:
            return []
        end = bisect.bisect_right(steps, at.timestamp(), key=lambda step: step[0])
        oldest = (at - BERTH_WINDOW).timestamp()
        return [step for step in reversed(steps[max(0, end - BERTH_TRIES):end]) if step[0] >= oldest]


@dataclass
class _Timeline:
    """A journey's stops with the times to use at one moment: actuals so far, then forecasts or planned + delay."""
    stops: list[Stop]
    at: datetime
    sections: SectionTimes | None = None
    reported: int | None = None  # index of the latest stop with an actual time at or before `at`
    reported_at: datetime | None = None
    delay: timedelta = field(default_factory=timedelta)

    def __post_init__(self):
        for index, stop in enumerate(self.stops):
            times = [t for t in (stop.actual_arrival, stop.actual_pass, stop.actual_departure) if self._seen(t)]
            if times:
                self.reported, self.reported_at = index, max(times)
        if self.reported is not None:
            stop = self.stops[self.reported]
            left = self._seen(stop.actual_departure) or self._seen(stop.actual_pass)
            planned = stop.planned_departure if left else stop.planned_arrival
            if planned is not None:
                self.delay = self.reported_at - planned

    def _seen(self, value: datetime | None) -> datetime | None:
        """An actual time, if it had happened by `at` (so a replay doesn't see the future)."""
        return value if value is not None and value <= self.at else None

    def _bounded(self, index: int, value: datetime | None) -> datetime | None:
        """Stops before the latest report were passed by then; stops after it can't come sooner."""
        if value is None or self.reported_at is None:
            return value
        if index < self.reported:
            return min(value, self.reported_at)
        if index > self.reported:
            return max(value, self.reported_at)
        return value

    @staticmethod
    def _expected(forecast: datetime | None, planned: datetime | None) -> datetime | None:
        """
        Darwin's forecast, but never sooner than planned + the delay at the last report. Forecasts are revised later
        mid-run far more often than earlier, and each later revision pulls the map's train backwards.
        """
        return max(forecast, planned) if forecast and planned else forecast or planned

    def _section_floor(self, index: int, expected: datetime | None) -> datetime | None:
        """No sooner than other trains have recently taken from the latest reported stop to this one."""
        if self.sections is None or expected is None or self.reported is None or index <= self.reported:
            return expected
        start = self.stops[self.reported]
        left = self._seen(start.actual_departure) or self._seen(start.actual_pass)
        if left is None:
            return expected
        run = self.sections.typical_run(start.tiploc, self.stops[index].tiploc, self.at)
        return max(expected, left + run) if run is not None else expected

    def arrival(self, index: int) -> datetime | None:
        stop = self.stops[index]
        actual = self._seen(stop.actual_arrival) or self._seen(stop.actual_pass)
        if actual:
            return actual
        forecast = (stop.estimated_arrival or stop.estimated_pass) if self.reported is None or index >= self.reported else None
        planned = stop.planned_arrival + self.delay if stop.planned_arrival else None
        return self._bounded(index, self._section_floor(index, self._expected(forecast, planned)))

    def departure(self, index: int) -> datetime | None:
        stop = self.stops[index]
        actual = self._seen(stop.actual_departure) or self._seen(stop.actual_pass)
        if actual:
            return actual
        forecast = (stop.estimated_departure or stop.estimated_pass) if self.reported is None or index >= self.reported else None
        planned = stop.planned_departure + self.delay if stop.planned_departure else None
        departure = self._bounded(index, self._expected(forecast, planned))
        arrival = self.arrival(index)
        return max(departure, arrival) if departure and arrival else departure or arrival

    def report_age(self) -> timedelta | None:
        return self.at - self.reported_at if self.reported_at else None


def service_status(journey: Journey, at: datetime) -> str:
    """cancelled, not_yet (more than 15 minutes before departure), finished, or active."""
    stops = [stop for stop in journey.stops if not stop.cancelled]
    if journey.cancelled or len(stops) < 2:
        return "cancelled"
    timeline = _Timeline(stops, at)

    first_departure = timeline.departure(0)
    if timeline.reported is None and first_departure and at < first_departure - SHOW_BEFORE_DEPARTURE:
        return "not_yet"

    arrived = timeline._seen(stops[-1].actual_arrival)
    if arrived:
        return "finished" if at - arrived > SHOW_AFTER_ARRIVAL else "active"
    age = timeline.report_age()
    if age is not None and (age > STALE_REPORT or (journey.deactivated and age > SHOW_AFTER_ARRIVAL)):
        return "finished"
    if timeline.reported is None:
        due = stops[-1].planned_arrival
        if journey.deactivated or (due and at > due + SHOW_AFTER_ARRIVAL):
            return "finished"
    return "active"


def estimate_position(journey: Journey, at: datetime, paths: PathSource,
                      sections: SectionTimes | None = None, berths: BerthSteps | None = None) -> Position | None:
    """
    Where the train is at `at`, or None if it isn't running then (or none of its stops can be placed). `sections`,
    other trains' recent run times, keeps a train from being expected sooner than the line is running. `berths`,
    trains' recent Train Describer steps, places a train that has stepped since its latest Darwin report.
    """
    position = _from_reports(journey, at, paths, sections)
    if position is None or berths is None or position.state == "terminated":
        return position
    return _from_berths(journey, at, paths, berths, position) or position


def _from_berths(journey: Journey, at: datetime, paths: PathSource, berths: BerthSteps,
                 position: Position) -> Position | None:
    """The train placed from its latest berth step, if one made since its latest report lies on its path ahead."""
    recent = berths.latest(journey.train_id, at)
    if not recent:
        return None
    stops = [stop for stop in journey.stops if not stop.cancelled]
    timeline = _Timeline(stops, at)
    placed = [index for index, stop in enumerate(stops) if stop.point is not None]
    first = 0
    if timeline.reported is not None:
        first = max((k for k, index in enumerate(placed) if index <= timeline.reported), default=0)
    ahead = list(pairwise(placed[first:first + BERTH_LOOKAHEAD + 1]))
    after = timeline.reported_at.timestamp() if timeline.reported_at else None

    fix = None
    for t, point in recent:
        if after is not None and t < after:
            break
        key = (journey.rid, t)
        if key not in berths._fixes:
            berths._fixes[key] = _on_path(point, stops, ahead, paths)
        if (found := berths._fixes[key]) is not None:
            fix = (*found, t, point)
            break
    if fix is None:
        return None
    here, there, along, t, point = fix
    standing = position.state in ("dwelling", "not_started")
    if standing and not (stops[here].tiploc == position.from_tiploc and along >= DEPARTED_METRES):
        return None  # still standing there, as far as the steps say

    line, method = _path(stops[here], stops[there], paths)
    length = line.length
    advance = min(point.berth_metres, point.pace * max((at.timestamp() - t), 0.0))
    distance = min(along + advance, length)
    fraction = distance / length if length > 0 else 1.0
    left = due = None
    if advance < point.berth_metres and distance < length and length > 0:
        # The browser moves the train on at the same pace until the next update
        left = at - timedelta(seconds=distance / point.pace)
        due = left + timedelta(seconds=length / point.pace)
    (x, y), bearing = _point_on(line, fraction)
    lon, lat = TO_WGS84.transform(x, y)
    return Position(lat, lon, bearing, "running", "medium" if method == "straight" else "high", stops[here].tiploc,
                    stops[there].tiploc, fraction, position.delay_minutes, position.last_report_age_s, left, due)


def _on_path(point: StepPoint, stops: list[Stop], ahead: list[tuple[int, int]],
             paths: PathSource) -> tuple[int, int, float] | None:
    """The first segment ahead that passes within BERTH_MATCH_METRES of `point`, and how far along it the point is."""
    spot = Point(point.x, point.y)
    for here, there in ahead:
        line, _ = _path(stops[here], stops[there], paths)
        if line.distance(spot) <= BERTH_MATCH_METRES:
            return here, there, line.project(spot)
    return None


def _from_reports(journey: Journey, at: datetime, paths: PathSource,
                  sections: SectionTimes | None = None) -> Position | None:
    """Where the train is from its stops' actual, forecast and planned times."""
    if service_status(journey, at) != "active":
        return None
    stops = [stop for stop in journey.stops if not stop.cancelled]
    timeline = _Timeline(stops, at, sections)
    placed = [index for index, stop in enumerate(stops) if stop.point is not None]
    if not placed:
        return None

    age = timeline.report_age()
    delay = round(timeline.delay.total_seconds() / 60) if timeline.reported is not None else None
    # The train isn't shown past the next placed call after its latest report until it reports there, or until
    # HOLD_LIMIT after it was due. Passing points don't hold it: Darwin has no actual times for many of them
    limit = next((index for index in placed
                  if timeline.reported is not None and index > timeline.reported and stops[index].is_call), None)

    def confidence(method: str | None, skipped: int) -> str:
        if age is None or age > OLD_REPORT or method == "straight":
            return "low"
        if age > FRESH_REPORT or skipped:
            return "medium"
        return "high"

    def at_stop(index: int, state: str) -> Position:
        """Standing at a stop, facing along the next segment (or the last one, at the end)."""
        nxt = next((i for i in placed if i > index), None)
        prev = next((i for i in reversed(placed) if i < index), None)
        bearing = None
        if nxt is not None:
            _, bearing = _point_on(_path(stops[index], stops[nxt], paths)[0], 0.0)
        elif prev is not None:
            _, bearing = _point_on(_path(stops[prev], stops[index], paths)[0], 1.0)
        lon, lat = TO_WGS84.transform(*stops[index].point)
        return Position(lat, lon, bearing, state, confidence(None, 0), stops[index].tiploc, stops[index].tiploc,
                        0.0, delay, age.total_seconds() if age else None)

    first = placed[0]
    if at < (timeline.departure(first) or at):
        return at_stop(first, "not_started")

    for k, here in enumerate(placed):
        arrived, leaves = timeline.arrival(here), timeline.departure(here)
        if arrived and at < arrived:
            break  # shouldn't happen: an earlier segment would have caught it
        if leaves and at < leaves:
            return at_stop(here, "dwelling" if stops[here].is_call else "running")
        if k + 1 == len(placed):
            ended = here == len(stops) - 1 and timeline._seen(stops[here].actual_arrival)
            return at_stop(here, "terminated" if ended or here == len(stops) - 1 else "held")

        there = placed[k + 1]
        due = timeline.arrival(there)
        if due is not None and at >= due:
            late_enough = HOLD_MIN_DELAY is None or (delay is not None and delay >= HOLD_MIN_DELAY)
            reports = sections is None or stops[there].tiploc not in sections.silent
            if (there == limit and at < due + HOLD_LIMIT and late_enough and reports
                    and not timeline._seen(stops[there].actual_arrival or stops[there].actual_pass)):
                return _running(stops, here, there, 1.0, "held", paths, confidence, delay, age, leaves or arrived, due)
            continue

        left = leaves or arrived or at
        span = (due - left).total_seconds() if due else 0
        fraction = min(max((at - left).total_seconds() / span, 0.0), 1.0) if span > 0 else 1.0
        return _running(stops, here, there, fraction, "running", paths, confidence, delay, age, left, due)
    return None


def route(journey: Journey, paths: PathSource) -> list[tuple[float, float]]:
    """The train's whole route as (lon, lat) points: the paths between its placed stops, joined end to end."""
    placed = [stop for stop in journey.stops if stop.point is not None and not stop.cancelled]
    points: list[tuple[float, float]] = []
    for start, end in pairwise(placed):
        line, _ = _path(start, end, paths)
        coords = list(line.coords)
        points.extend(coords[1:] if points else coords)
    if len(placed) == 1:
        points = [placed[0].point]
    if not points:
        return []
    lons, lats = TO_WGS84.transform([x for x, _ in points], [y for _, y in points])
    return list(zip(lons, lats, strict=True))


def segment_line(start: Stop, end: Stop, paths: PathSource, tolerance: float = 5.0) -> list[tuple[float, float]]:
    """The path a train follows from `start` to `end` as (lon, lat) points, simplified to within `tolerance` metres."""
    line, _ = _path(start, end, paths)
    line = line.simplify(tolerance)
    lons, lats = TO_WGS84.transform(*zip(*line.coords, strict=True))
    return [(round(lon, 6), round(lat, 6)) for lon, lat in zip(lons, lats, strict=True)]


def _running(stops, here, there, fraction, state, paths, confidence, delay, age, left, due) -> Position:
    line, method = _path(stops[here], stops[there], paths)
    (x, y), bearing = _point_on(line, fraction)
    lon, lat = TO_WGS84.transform(x, y)
    return Position(lat, lon, bearing, state, confidence(method, there - here - 1), stops[here].tiploc,
                    stops[there].tiploc, fraction, delay, age.total_seconds() if age else None, left, due)


def _path(start: Stop, end: Stop, paths: PathSource) -> tuple[LineString, str]:
    found = paths(start.tiploc, end.tiploc)
    if found is not None:
        return found
    return LineString([start.point, end.point]), "straight"


def _point_on(line: LineString, fraction: float) -> tuple[tuple[float, float], float | None]:
    """The point `fraction` of the way along `line`, and the bearing of travel there."""
    length = line.length
    distance = fraction * length
    point = line.interpolate(distance)
    if length == 0:
        return (point.x, point.y), None
    ahead, behind = min(distance + BEARING_LOOKAHEAD, length), max(distance - BEARING_LOOKAHEAD, 0.0)
    a, b = line.interpolate(behind if ahead == distance else distance), line.interpolate(ahead)
    lon1, lat1 = TO_WGS84.transform(a.x, a.y)
    lon2, lat2 = TO_WGS84.transform(b.x, b.y)
    azimuth, _, _ = GEOD.inv(lon1, lat1, lon2, lat2)
    return (point.x, point.y), azimuth % 360


class PathCache:
    """Every segment path, in British National Grid, loaded once."""

    def __init__(self, rows: list[tuple[str, str, str, bytes]]):
        self.paths: dict[tuple[str, str], tuple[LineString, str]] = {}
        for from_tiploc, to_tiploc, method, wkb in rows:
            line = shapely.transform(shapely.from_wkb(wkb), lambda xy: _to_grid(xy))
            self.paths[(from_tiploc, to_tiploc)] = (line, method)

    def __call__(self, from_tiploc: str, to_tiploc: str) -> tuple[LineString, str] | None:
        if (found := self.paths.get((from_tiploc, to_tiploc))) is not None:
            return found
        if (found := self.paths.get((to_tiploc, from_tiploc))) is not None:
            return found[0].reverse(), found[1]
        return None


def _to_grid(coords):
    x, y = TO_GRID.transform(coords[:, 0], coords[:, 1])
    coords[:, 0], coords[:, 1] = x, y
    return coords


def load_journeys(db: Database, at: datetime) -> list[Journey]:
    journeys: dict[str, Journey] = {}
    for rid, train_id, toc, cancelled, deactivated in db.fetch_journeys_around(at):
        journeys[rid] = Journey(rid, [], train_id, toc, bool(cancelled), bool(deactivated))
    for row in db.fetch_position_stops(list(journeys)):
        rid, tiploc, location_type, x, y, *times, cancelled = row
        journeys[rid].stops.append(Stop(tiploc, location_type, (x, y) if x is not None else None, *times, cancelled=cancelled))
    return list(journeys.values())


def to_geojson(results: list[tuple[Journey, Position]]) -> dict:
    colours = {"high": "#2ca02c", "medium": "#ff7f0e", "low": "#d62728"}
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(p.lon, 6), round(p.lat, 6)]},
        "properties": {
            "rid": j.rid, "headcode": j.train_id, "toc": j.toc, "from": p.from_tiploc, "to": p.to_tiploc,
            "fraction": round(p.fraction, 3), "state": p.state, "confidence": p.confidence,
            "delay_minutes": p.delay_minutes, "bearing": round(p.bearing) if p.bearing is not None else None,
            "marker-color": colours[p.confidence], "marker-size": "small",
        },
    } for j, p in results]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--at", type=datetime.fromisoformat, help="ISO time (default: now)")
    parser.add_argument("--limit", type=int, default=15, help="sample rows to print (default: %(default)s)")
    parser.add_argument("--geojson", metavar="FILE", help="write positions as GeoJSON points")
    args = parser.parse_args()
    at = args.at or datetime.now(LONDON)
    if at.tzinfo is None:
        at = at.replace(tzinfo=LONDON)

    db = Database(load_config().database_url)
    try:
        start = time.perf_counter()
        paths = PathCache(db.fetch_segment_paths())
        loaded_paths = time.perf_counter()
        journeys = load_journeys(db, at)
        loaded_journeys = time.perf_counter()
    finally:
        db.close()

    statuses = Counter(service_status(journey, at) for journey in journeys)
    sections = SectionTimes(journeys, at)
    results = [(j, p) for j in journeys if (p := estimate_position(j, at, paths, sections)) is not None]
    estimated = time.perf_counter()

    active = statuses["active"]
    print(f"At {at.isoformat()}: {len(journeys):,} journeys loaded, {active:,} active, "
          f"{len(results):,} positioned ({100 * len(results) / active if active else 0:.1f}%)")
    print(f"Time: paths {loaded_paths - start:.2f}s ({len(paths.paths):,}), journeys {loaded_journeys - loaded_paths:.2f}s, "
          f"estimating {estimated - loaded_journeys:.3f}s")
    print("Not active:", dict(statuses - Counter(active=active)))
    print("States:", dict(Counter(p.state for _, p in results).most_common()))
    print("Confidence:", dict(Counter(p.confidence for _, p in results).most_common()))
    print()
    print(f"{'Headcode':8} {'TOC':3} {'From':8} {'To':8} {'Frac':>5} {'State':11} {'Conf':6} {'Delay':>5}  Lat, Lon")
    for journey, p in results[:args.limit]:
        print(f"{journey.train_id or '':8} {journey.toc or '':3} {p.from_tiploc:8} {p.to_tiploc:8} {p.fraction:5.2f} "
              f"{p.state:11} {p.confidence:6} {'' if p.delay_minutes is None else p.delay_minutes:>5}  {p.lat:.5f}, {p.lon:.5f}")

    if args.geojson:
        with open(args.geojson, "w") as f:
            json.dump(to_geojson(results), f)


if __name__ == "__main__":
    main()
