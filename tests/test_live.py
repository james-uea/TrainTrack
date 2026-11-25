"""The live position service, with a stand-in database (no Postgres needed)."""

from datetime import UTC, datetime, timedelta

import pytest
from shapely import to_wkb
from shapely.geometry import LineString
from test_positions import POINTS, TRACK

from live import Clock, LivePositions, SteppedClock
from tiploc_locations import to_wgs84

START = datetime(2026, 11, 21, 14, 0, tzinfo=UTC)


def stop_row(rid, tiploc, location_type, departure=None, arrival=None, actual_departure=None):
    x, y = POINTS[tiploc]
    return (rid, tiploc, location_type, x, y, arrival, departure, None, None, None, None, None, actual_departure,
            None, False)


def run(rid, start):
    """A train from AAA to BBB, 10 minutes, leaving at `start`."""
    return [stop_row(rid, "AAA", "OR", departure=start), stop_row(rid, "BBB", "DT", arrival=start + timedelta(minutes=10))]


class FakeDatabase:
    def __init__(self):
        self.trains = {"A": run("A", START), "B": run("B", START + timedelta(minutes=30))}
        self.meta = {"A": ("A", "1A01", "LE", False, False), "B": ("B", "1B01", "LE", False, False)}
        self.changed: list[str] = []
        self.stop_loads: list[list[str]] = []
        self.step_points: list[tuple] = []
        self.steps: list[tuple] = []
        self.conn = self

    def rollback(self):
        pass

    def fetch_segment_paths(self):
        return [(a, b, "track", to_wkb(LineString([to_wgs84(x, y) for x, y in line.coords])))
                for (a, b), line in TRACK.items()]

    def fetch_changed_journeys(self, since):
        changed, self.changed = self.changed, []
        return START, changed if since is not None else []

    def fetch_journeys_around(self, at, rids=None):
        rows = []
        for rid, stops in self.trains.items():
            first, last = stops[0][6], stops[-1][5]
            in_window = first <= at + timedelta(minutes=15) and last >= at - timedelta(hours=3)
            if in_window and (rids is None or rid in rids):
                rows.append(self.meta[rid])
        return rows

    def fetch_td_step_points(self):
        return self.step_points

    def fetch_td_steps(self, start, end):
        return [step for step in self.steps if start.timestamp() <= step[0] < end.timestamp()]

    def fetch_position_stops(self, rids):
        self.stop_loads.append(sorted(rids))
        return [row for rid in sorted(rids) for row in self.trains[rid]]


def test_clock_modes():
    assert Clock.parse("now").is_live
    fixed = Clock.parse("fixed:2026-11-21T14:30Z")
    assert fixed.now() == datetime(2026, 11, 21, 14, 30, tzinfo=UTC)
    assert str(fixed) == "fixed:2026-11-21T14:30:00+00:00"

    ticks = iter([100.0, 107.5])
    replay = Clock(datetime(2026, 11, 21, 14, 30, tzinfo=UTC), monotonic=lambda: next(ticks))
    assert replay.mode == "replay"
    assert replay.now() == datetime(2026, 11, 21, 14, 30, 7, 500000, tzinfo=UTC)

    with pytest.raises(ValueError):
        Clock.parse("yesterday")


def test_only_trains_in_the_window_are_loaded_and_placed():
    db = FakeDatabase()
    live = LivePositions(db, SteppedClock(START + timedelta(minutes=5)))
    snapshot = live.tick()
    assert set(live.journeys) == {"A"}  # B leaves in 30 minutes, outside the 15-minute lead
    assert [(j.rid, p.state) for j, p in snapshot.positions] == [("A", "running")]
    assert snapshot.positions[0][1].fraction == pytest.approx(0.5)


def test_a_changed_train_is_reloaded_without_reloading_the_rest():
    db = FakeDatabase()
    clock = SteppedClock(START + timedelta(minutes=5))
    live = LivePositions(db, clock)
    live.tick()
    db.stop_loads.clear()

    # Departed 2 minutes late: the new actual time moves the train back along the segment
    db.trains["A"][0] = stop_row("A", "AAA", "OR", departure=START, actual_departure=START + timedelta(minutes=2))
    db.changed = ["A"]
    clock.step(timedelta(seconds=5))
    snapshot = live.tick()
    assert db.stop_loads == [["A"]]
    assert snapshot.positions[0][1].fraction < 0.5


def test_the_window_moves_with_the_clock():
    db = FakeDatabase()
    clock = SteppedClock(START + timedelta(minutes=5))
    live = LivePositions(db, clock)
    live.tick()

    clock.step(timedelta(minutes=20))  # B is now due within 15 minutes
    live.tick()
    assert set(live.journeys) == {"A", "B"}

    clock.step(timedelta(hours=4))  # both long finished
    live.tick()
    assert live.journeys == {}


def test_berth_steps_place_trains_and_follow_the_clock():
    db = FakeDatabase()
    x, y = POINTS["AAA"]
    db.step_points = [("R1", "0101", "0103", x + 1000, y, 3, 10.0, 800.0, 40.0)]
    db.steps = [((START + timedelta(minutes=3)).timestamp(), "R1", "0101", "0103", "1A01")]
    clock = SteppedClock(START + timedelta(minutes=3, seconds=20))
    live = LivePositions(db, clock)
    snapshot = live.tick()
    assert snapshot.positions[0][1].fraction == pytest.approx(1400 / 6000)  # 1 km out, then 20 s at 20 m/s

    clock.step(timedelta(hours=1))  # a jump: steps from before it are dropped
    live.tick()
    assert live.berths.recent == {}
