"""The day accuracy report, on made-up journeys and frames (no database)."""

from datetime import datetime, timedelta

import pytest
from shapely.geometry import LineString

from accuracy import build_route, frame_moments, measure, report, sample_times
from frames import pack
from positions import Journey, Stop
from util import LONDON

X, Y = 600000, 300000
# A 6 km line east, then 4 km north: AAA -> BBB -> CCC
POINTS = {"AAA": (X, Y), "BBB": (X + 6000, Y), "CCC": (X + 6000, Y + 4000), "OFF": (X, Y + 9000)}


def paths(a, b):
    return (LineString([POINTS[a], POINTS[b]]), "track")


def t(hhmm, seconds=0):
    hours, minutes = hhmm.split(":")
    return datetime(2026, 11, 24, int(hours), int(minutes), seconds, tzinfo=LONDON)


def train(rid="R1", **actuals):
    """AAA 10:00 -> BBB 10:06/10:07 -> CCC 10:11, with any actual times given as AAA_dep="10:01" and so on."""
    times = {
        "AAA": {"working_departure": t("10:00")},
        "BBB": {"working_arrival": t("10:06"), "working_departure": t("10:07")},
        "CCC": {"working_arrival": t("10:11")},
    }
    names = {"dep": "actual_departure", "arr": "actual_arrival", "pass": "actual_pass"}
    for key, value in actuals.items():
        tiploc, kind = key.split("_")
        times[tiploc][names[kind]] = t(value)
    kinds = {"AAA": "OR", "BBB": "IP", "CCC": "DT"}
    return Journey(rid, [Stop(tiploc, kinds[tiploc], POINTS[tiploc], **times[tiploc]) for tiploc in kinds], "1A01", "LE")


def test_truth_runs_at_an_even_pace_between_reports_and_stands_at_stops():
    route = build_route(train(AAA_dep="10:00", BBB_arr="10:06", BBB_dep="10:08", CCC_arr="10:12"), paths, 0)
    assert route.metres == {0: 0, 1: 6000, 2: 10000}
    assert route.truth(t("10:03").timestamp()) == pytest.approx(3000)
    assert route.truth(t("10:07").timestamp()) == 6000  # dwelling at BBB
    assert route.truth(t("10:10").timestamp()) == pytest.approx(8000)
    # Before leaving its origin it's there, and after reaching its destination it's there
    assert route.truth(t("09:55").timestamp()) == 0
    assert route.truth(t("10:20").timestamp()) == 10000


def test_truth_is_unknown_outside_the_reports_and_across_a_long_gap():
    partial = build_route(train(BBB_arr="10:06", BBB_dep="10:07"), paths, 0)
    assert partial.truth(t("10:03").timestamp()) is None  # not reported leaving its origin
    assert partial.truth(t("10:09").timestamp()) is None  # nothing after BBB

    gap = build_route(train(AAA_dep="10:00", CCC_arr="10:40"), paths, 0)
    assert gap.truth(t("10:20").timestamp()) is None


def test_truth_offset_moves_every_report():
    route = build_route(train(AAA_dep="10:00", BBB_arr="10:06"), paths, 30)
    assert route.truth(t("10:03", 30).timestamp()) == pytest.approx(3000)


def test_a_report_out_of_order_is_left_out():
    route = build_route(train(AAA_dep="10:05", BBB_arr="10:03", CCC_arr="10:12"), paths, 0)
    assert [m for _, m in route.anchors] == [0, 10000]


def test_drawn_picks_the_visit_of_a_tiploc_nearest_the_truth():
    # AAA -> BBB -> AAA -> BBB: a train that runs the same stretch twice
    stops = [Stop(tiploc, "IP", POINTS[tiploc]) for tiploc in ("AAA", "BBB", "AAA", "BBB")]
    route = build_route(Journey("R2", stops), paths, 0)
    assert route.drawn("AAA", "BBB", 0.5, near=0) == 3000
    assert route.drawn("AAA", "BBB", 0.5, near=14000) == 15000
    assert route.drawn("BBB", "BBB", 0.0, near=17000) == 18000
    assert route.drawn("CCC", "AAA", 0.5, near=0) is None


def frame(at, trains, keyframe=True, removed=()):
    body = {"at": at.isoformat(), "trains": trains}
    if not keyframe:
        body["removed"] = list(removed)
    return (at, keyframe, "recorded", pack(body))


def running(rid, left, due, a="AAA", b="BBB"):
    return {"rid": rid, "state": "running", "from_tiploc": a, "to_tiploc": b, "fraction": 0.0,
            "left": left.isoformat(), "due": due.isoformat()}


def test_frames_place_trains_along_their_segment_at_each_moment():
    rows = [
        frame(t("10:00"), [running("R1", t("10:00"), t("10:06"))]),
        frame(t("10:04", 30), [], keyframe=False, removed=["R1"]),
    ]
    moments = list(frame_moments(rows, sample_times(t("10:00"), t("10:06"), timedelta(minutes=1))))
    assert [at for at, _ in moments] == [t("10:00"), t("10:01"), t("10:02"), t("10:03"), t("10:04")]
    assert moments[3][1]["R1"]["fraction"] == pytest.approx(0.5)
    assert moments[-1][1]["R1"]["fraction"] == pytest.approx(4 / 6)


def test_measure_reports_how_far_ahead_and_what_the_map_missed():
    # The map has R1 due at BBB at 10:04, but it got there at 10:06: at 10:02 the map is 1 km ahead
    routes = {rid: build_route(train(rid, AAA_dep="10:00", BBB_arr="10:06"), paths, 0) for rid in ("R1", "R2")}
    routes["R3"] = build_route(train("R3"), paths, 0)  # never reported
    shown = {"R1": {**running("R1", t("10:00"), t("10:04")), "fraction": 0.5},
             "R3": {**running("R3", t("10:00"), t("10:06")), "fraction": 0.5}}
    tally = measure([(t("10:02"), shown)], routes)
    assert [(s.rid, round(s.error)) for s in tally.samples] == [("R1", 1000)]
    assert (tally.in_service, tally.missing) == (2, 1)  # R2 was running but not on the map
    assert tally.unknown == {"never reported": 1}
    result = report(tally)
    assert result["overall"]["far_pct"] == 0
    assert result["coverage"]["missing_pct"] == 50
