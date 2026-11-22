from datetime import UTC, datetime

import pytest

from frames import advance, changes_dict, point_along, rebuild

AT = datetime(2026, 11, 21, 14, 45, tzinfo=UTC)


def train(rid, **fields):
    return {"rid": rid, "headcode": "1A48", "toc": "VT", "lat": 52.0, "lon": -1.0, "bearing": 0, "state": "running",
            "confidence": "high", "delay": 0, "from_tiploc": "AAA", "to_tiploc": "BBB", "fraction": 0.0,
            "left": "2026-11-21T14:44:00+00:00", "due": "2026-11-21T14:46:00+00:00", **fields}


def snap(*trains, at=AT):
    return {"version": 0, "at": at.isoformat(), "clock": "now", "active": len(trains), "trains": list(trains)}


def test_rebuilding_from_a_keyframe_and_changes_gives_the_last_snapshot():
    first = snap(train("A"), train("B"), train("C"))
    second = snap(train("A"), train("B", to_tiploc="CCC"), train("D"))
    third = snap(train("A", state="dwelling"), train("B", to_tiploc="CCC"), train("D"))
    rebuilt = rebuild([first, changes_dict(first, second), changes_dict(second, third)])
    assert sorted(t["rid"] for t in rebuilt["trains"]) == ["A", "B", "D"]
    assert {t["rid"]: t for t in rebuilt["trains"]} == {t["rid"]: t for t in third["trains"]}
    assert "removed" not in rebuilt


def test_a_keyframe_part_way_replaces_everything_before_it():
    first = snap(train("A"))
    assert [t["rid"] for t in rebuild([first, snap(train("Z"))])["trains"]] == ["Z"]


def test_point_along_measures_distance_not_points():
    line = [(0.0, 52.0), (0.0, 52.001), (0.0, 52.01)]
    lon, lat, bearing = point_along(line, 0.5)
    assert lat == pytest.approx(52.005) and lon == 0.0 and bearing == pytest.approx(0.0)
    assert point_along(line, 1.0)[:2] == (0.0, 52.01)


def test_advance_moves_running_trains_along_their_segment_and_leaves_the_rest():
    line = [(-1.0, 52.0), (-1.0, 52.02)]
    moved = advance(snap(train("A"), train("B", state="dwelling", lat=51.0)), AT,
                    lambda a, b: line if (a, b) == ("AAA", "BBB") else None)
    a, b = moved["trains"]
    assert a["fraction"] == 0.5 and a["lat"] == pytest.approx(52.01) and a["bearing"] == 0
    assert b["lat"] == 51.0
    assert moved["at"] == AT.isoformat()
