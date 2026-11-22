"""The position estimator, on made-up journeys (no database)."""

from datetime import datetime

import pytest
from shapely import to_wkb
from shapely.geometry import LineString

from positions import Journey, PathCache, Stop, estimate_position, route, service_status
from tiploc_locations import to_wgs84
from util import LONDON

X, Y = 600000, 300000
POINTS = {"AAA": (X, Y), "PPP": (X + 3000, Y), "BBB": (X + 6000, Y), "CCC": (X + 6000, Y + 4000)}
# AAA -> PPP -> BBB runs east along a straight track, BBB -> CCC north
TRACK = {
    ("AAA", "PPP"): LineString([POINTS["AAA"], POINTS["PPP"]]),
    ("PPP", "BBB"): LineString([POINTS["PPP"], POINTS["BBB"]]),
    ("AAA", "BBB"): LineString([POINTS["AAA"], POINTS["BBB"]]),
    ("BBB", "CCC"): LineString([POINTS["BBB"], POINTS["CCC"]]),
}


def paths(from_tiploc, to_tiploc):
    line = TRACK.get((from_tiploc, to_tiploc))
    return (line, "track") if line is not None else None


def t(hhmm, day=21):
    hours, minutes = hhmm.split(":")
    return datetime(2026, 11, day, int(hours), int(minutes), tzinfo=LONDON)


def stop(tiploc, kind, placed=True, **times):
    return Stop(tiploc, kind, POINTS[tiploc] if placed else None, **times)


def journey(*stops, **kwargs):
    return Journey("202611218000009", list(stops), "1A01", "LE", **kwargs)


def simple(**extra):
    """AAA 10:00 -> BBB 10:10/10:11 -> CCC 10:20."""
    stops = {
        "AAA": {"working_departure": t("10:00")},
        "BBB": {"working_arrival": t("10:10"), "working_departure": t("10:11")},
        "CCC": {"working_arrival": t("10:20")},
    }
    for tiploc, times in extra.items():
        stops[tiploc].update(times)
    return journey(
        stop("AAA", "OR", **stops["AAA"]), stop("BBB", "IP", **stops["BBB"]), stop("CCC", "DT", **stops["CCC"]),
    )


def lat_lon(x, y):
    lon, lat = to_wgs84(x, y)
    return pytest.approx(lat, abs=1e-5), pytest.approx(lon, abs=1e-5)


def test_before_departure():
    assert estimate_position(simple(), t("09:40"), paths) is None
    assert service_status(simple(), t("09:40")) == "not_yet"

    position = estimate_position(simple(), t("09:50"), paths)
    assert (position.state, position.from_tiploc, position.confidence, position.delay_minutes) == ("not_started", "AAA", "low", None)
    assert (position.lat, position.lon) == lat_lon(*POINTS["AAA"])
    assert position.bearing == pytest.approx(92.4, abs=0.5)  # facing east, the way it'll leave


def test_replay_ignores_actual_times_after_the_moment():
    train = simple(AAA={"actual_departure": t("10:02")})
    before = estimate_position(train, t("10:01"), paths)  # the 10:02 departure hasn't happened yet
    assert (before.state, before.delay_minutes, before.confidence) == ("running", None, "low")
    after = estimate_position(train, t("10:03"), paths)
    assert (after.delay_minutes, after.confidence) == (2, "high")


def test_running_part_way_along_a_segment():
    train = simple(AAA={"actual_departure": t("10:02")})  # 2 late, so due at BBB 10:12
    position = estimate_position(train, t("10:07"), paths)

    assert (position.state, position.from_tiploc, position.to_tiploc) == ("running", "AAA", "BBB")
    assert position.fraction == pytest.approx(0.5)
    assert (position.lat, position.lon) == lat_lon(X + 3000, Y)
    assert position.bearing == pytest.approx(92.4, abs=0.5)
    assert (position.delay_minutes, position.last_report_age_s, position.confidence) == (2, 300, "high")


def test_a_forecast_beats_planned_plus_delay():
    train = simple(AAA={"actual_departure": t("10:00")}, BBB={"estimated_arrival": t("10:20")})
    assert estimate_position(train, t("10:05"), paths).fraction == pytest.approx(0.25)


def test_dwelling_at_a_call():
    train = simple(AAA={"actual_departure": t("10:00")}, BBB={"actual_arrival": t("10:10")})
    position = estimate_position(train, t("10:10").replace(second=30), paths)
    assert (position.state, position.from_tiploc, position.to_tiploc) == ("dwelling", "BBB", "BBB")
    assert position.bearing == pytest.approx(2.4, abs=0.5)  # facing north, towards CCC


def test_a_late_train_is_held_short_of_a_call_with_no_report_yet():
    train = simple(AAA={"actual_departure": t("10:04")})  # 4 late, so due at BBB 10:14
    position = estimate_position(train, t("10:16"), paths)
    assert (position.state, position.from_tiploc, position.to_tiploc, position.fraction) == ("held", "AAA", "BBB", 1.0)
    assert (position.lat, position.lon) == lat_lon(*POINTS["BBB"])
    assert position.confidence == "medium"  # 12 minutes since the last report


def test_an_on_time_train_runs_on_through_a_call_that_hasnt_reported():
    train = simple(AAA={"actual_departure": t("10:00")})
    position = estimate_position(train, t("10:12"), paths)  # due at BBB 10:10, most likely gone through
    assert (position.state, position.from_tiploc, position.to_tiploc) == ("running", "BBB", "CCC")


def test_a_call_that_never_reports_holds_a_late_train_only_briefly():
    # Like 2H62 at Kinbrace: a request stop with no report, so the train shouldn't be pinned there until Brora
    train = simple(AAA={"actual_departure": t("10:04")})  # 4 late: due at BBB 10:14, leaves 10:15, at CCC 10:24
    position = estimate_position(train, t("10:20"), paths)  # 6 minutes after it was due at BBB, past HOLD_LIMIT
    assert (position.state, position.from_tiploc, position.to_tiploc) == ("running", "BBB", "CCC")
    assert position.fraction == pytest.approx(5 / 9)
    assert position.confidence == "low"  # 16 minutes since the last report


def test_passing_points_without_reports_dont_hold_the_train():
    train = journey(
        stop("AAA", "OR", working_departure=t("10:00"), actual_departure=t("10:00")),
        stop("PPP", "PP", working_pass=t("10:04")),
        stop("BBB", "DT", working_arrival=t("10:08")),
    )
    position = estimate_position(train, t("10:06"), paths)
    assert (position.state, position.from_tiploc, position.to_tiploc, position.fraction) == ("running", "PPP", "BBB", 0.5)


def test_skips_a_stop_without_a_location():
    train = journey(
        stop("AAA", "OR", working_departure=t("10:00"), actual_departure=t("10:00")),
        stop("PPP", "PP", placed=False, working_pass=t("10:04"), actual_pass=t("10:05")),
        stop("BBB", "DT", working_arrival=t("10:08")),
    )
    # Reported at PPP a minute late, so due at BBB at 10:09: the segment AAA -> BBB runs 10:00 -> 10:09
    position = estimate_position(train, t("10:05"), paths)
    assert (position.from_tiploc, position.to_tiploc, position.fraction) == ("AAA", "BBB", pytest.approx(5 / 9))
    assert (position.delay_minutes, position.confidence) == (1, "medium")


def test_straight_line_when_there_is_no_track_path():
    train = simple(BBB={"actual_departure": t("10:11")})
    position = estimate_position(train, t("10:15"), lambda a, b: None)
    assert (position.from_tiploc, position.to_tiploc, position.confidence) == ("BBB", "CCC", "low")
    assert position.fraction == pytest.approx(4 / 9)  # 10:11 -> 10:20
    assert (position.lat, position.lon) == lat_lon(X + 6000, Y + 4000 * 4 / 9)
    assert position.bearing == pytest.approx(2.4, abs=0.5)


def test_past_midnight():
    train = journey(
        stop("AAA", "OR", working_departure=t("23:55"), actual_departure=t("23:57")),
        stop("BBB", "DT", working_arrival=t("00:05", day=22)),
    )
    position = estimate_position(train, t("00:02", day=22), paths)
    assert (position.state, position.fraction, position.delay_minutes) == ("running", 0.5, 2)


def test_terminated_then_dropped():
    train = simple(CCC={"actual_arrival": t("10:21")})
    assert estimate_position(train, t("10:23"), paths).state == "terminated"
    assert estimate_position(train, t("10:30"), paths) is None
    assert service_status(train, t("10:30")) == "finished"


def test_timetable_only_when_nothing_has_reported():
    position = estimate_position(simple(), t("10:05"), paths)
    assert (position.state, position.fraction, position.confidence, position.delay_minutes) == ("running", 0.5, "low", None)


def test_cancelled_trains_have_no_position():
    train = simple()
    train.cancelled = True
    assert estimate_position(train, t("10:05"), paths) is None
    assert service_status(train, t("10:05")) == "cancelled"


def test_path_cache_reverses_paths_stored_the_other_way():
    cache = PathCache([("AAA", "BBB", "track", to_wkb(LineString([(1.30, 52.60), (1.31, 52.61)])))])
    forward, method = cache("AAA", "BBB")
    backward, _ = cache("BBB", "AAA")
    assert method == "track"
    assert forward.coords[0] == pytest.approx(backward.coords[-1])
    assert forward.coords[0][0] == pytest.approx(623000, abs=2000)  # converted to the British grid
    assert cache("AAA", "ZZZ") is None


def test_back_the_way_it_came_after_reversing():
    train = journey(
        stop("AAA", "OR", working_departure=t("10:00"), actual_departure=t("10:00")),
        stop("BBB", "IP", working_arrival=t("10:10"), working_departure=t("10:12"),
             actual_arrival=t("10:10"), actual_departure=t("10:12")),
        stop("AAA", "DT", working_arrival=t("10:22")),
    )
    reverse = {("BBB", "AAA"): LineString([POINTS["BBB"], POINTS["AAA"]])}
    position = estimate_position(train, t("10:17"), lambda a, b: paths(a, b) or ((reverse[(a, b)], "track") if (a, b) in reverse else None))
    assert (position.state, position.from_tiploc, position.to_tiploc, position.fraction) == ("running", "BBB", "AAA", 0.5)
    assert (position.lat, position.lon) == lat_lon(X + 3000, Y)
    assert position.bearing == pytest.approx(272.4, abs=1)  # heading west, back towards AAA


def test_route_joins_the_paths_between_placed_stops():
    train = journey(stop("AAA", "OR"), stop("PPP", "PP", placed=False), stop("BBB", "IP"), stop("CCC", "DT"))
    points = route(train, paths)
    assert len(points) == 3  # AAA, BBB (shared by both paths, once), CCC
    assert (points[0][1], points[0][0]) == lat_lon(*POINTS["AAA"])
    assert (points[-1][1], points[-1][0]) == lat_lon(*POINTS["CCC"])


def test_a_running_train_says_when_it_left_and_is_due():
    train = simple(AAA={"actual_departure": t("10:00")})
    position = estimate_position(train, t("10:02"), paths)
    assert position.state == "running"
    assert (position.left, position.due) == (t("10:00"), t("10:10"))
    assert position.fraction == pytest.approx((t("10:02") - position.left) / (position.due - position.left))
