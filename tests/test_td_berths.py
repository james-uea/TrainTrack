"""Learning where berth steps happen, on made-up trains (no database)."""

from datetime import UTC, datetime

import pytest
from shapely.geometry import LineString

from accuracy import build_route
from positions import Journey, Stop
from td_berths import Samples, learn, step_points

X, Y = 600000, 300000
# AAA -> BBB runs 6 km east; FAR -> FAB is the same 50 km north
POINTS = {"AAA": (X, Y), "BBB": (X + 6000, Y), "FAR": (X, Y + 50000), "FAB": (X + 6000, Y + 50000)}


def paths(a, b):
    return LineString([POINTS[a], POINTS[b]]), "track"


def t(minute, second=0):
    return datetime(2026, 11, 25, 10, minute, second, tzinfo=UTC).timestamp()


def run(rid, headcode, leaves, a="AAA", b="BBB"):
    """A train leaving `a` at 10:`leaves` and reaching `b` 6 minutes later, both reported."""
    def at(minute):
        return datetime.fromtimestamp(t(minute), UTC)
    stops = [Stop(a, "OR", POINTS[a], working_departure=at(leaves), actual_departure=at(leaves)),
             Stop(b, "DT", POINTS[b], working_arrival=at(leaves + 6), actual_arrival=at(leaves + 6))]
    return rid, build_route(Journey(rid, stops, headcode, "LE"), paths, 0)


def steps_for(headcode, leaves):
    """Its steps half way (3 km, after 3 minutes) and at 4 km a minute later."""
    return [(t(leaves + 3), "R1", "0101", "0103", headcode), (t(leaves + 4), "R1", "0103", "0105", headcode)]


def test_a_step_is_placed_where_the_actual_times_put_its_trains():
    routes = dict(run(f"R{n}", "1A01", 10 * n) for n in range(3))
    samples = Samples()
    learn(sorted(s for n in range(3) for s in steps_for("1A01", 10 * n)), routes, paths, samples)

    rows = {row[:3]: row[3:] for row in step_points(samples)}
    x, y, count, spread, next_metres, next_seconds = rows[("R1", "0101", "0103")]
    assert (x, y, count, spread) == (pytest.approx(X + 3000), pytest.approx(Y), 3, pytest.approx(0))
    assert (next_metres, next_seconds) == (pytest.approx(1000), 60)
    x, y, count, _, next_metres, _ = rows[("R1", "0103", "0105")]
    assert (x, y, count, next_metres) == (pytest.approx(X + 4000), pytest.approx(Y), 3, None)  # no step after it


def test_a_shared_headcode_goes_to_the_train_among_the_areas_steps():
    # 1A01 runs AAA -> BBB three times; at 10:00 another 1A01 runs 50 km away
    routes = dict(run(f"R{n}", "1A01", 10 * n) for n in range(3))
    routes.update([run("S", "1A01", 0, "FAR", "FAB")])
    samples = Samples()
    learn(sorted(s for n in range(3) for s in steps_for("1A01", 10 * n)), routes, paths, samples)

    assert samples.counts["placed, shared headcode"] == 2
    assert len(samples.points[("R1", "0101", "0103")]) == 3
    assert all(y == pytest.approx(Y) for _, y in samples.points[("R1", "0101", "0103")])


def test_a_step_too_few_trains_made_isnt_kept():
    routes = dict([run("R0", "1A01", 0)])
    samples = Samples()
    learn(steps_for("1A01", 0), routes, paths, samples)
    assert step_points(samples) == []
