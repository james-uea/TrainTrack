"""Track model, graph routing, snapping and segment paths, on a tiny made-up network near Norwich."""

from datetime import date

import pytest
from shapely.geometry import LineString

from darwin import parse_schedule
from segment_paths import PlacedTiploc, segment_path, update
from tiploc_locations import TiplocLocation, to_wgs84
from track_graph import Link, Snap, TrackGraph
from track_model import TrackLink, assign_nodes

X, Y = 600000, 300000  # British National Grid origin for the test network


def link(asset_id, *points, from_node, to_node):
    return Link(asset_id, from_node, to_node, LineString([(X + x, Y + y) for x, y in points]))


def network():
    """
    Two parallel tracks 4 m apart from x=0 to x=2000, joined by a crossover only at x=2000, plus a
    branch that leaves at x=2000 and loops back to finish 10 m from the main line's start, and an
    isolated siding.
    """
    return TrackGraph([
        link("up1", (0, 0), (1000, 0), from_node=1, to_node=2),
        link("up2", (1000, 0), (2000, 0), from_node=2, to_node=3),
        link("down", (0, 4), (2000, 4), from_node=4, to_node=5),
        link("xover", (2000, 0), (2000, 4), from_node=3, to_node=5),
        link("loop", (2000, 0), (2000, 3000), (-10, 3000), (-10, 10), from_node=3, to_node=6),
        link("siding", (5000, 5000), (5100, 5000), from_node=7, to_node=8),
    ])


def test_endpoints_within_a_metre_share_a_node():
    links = assign_nodes([
        TrackLink("a", "ELR", "1100", 0, 1, [(0, 0), (100, 0)]),
        TrackLink("b", "ELR", "1100", 1, 2, [(100.4, 0.3), (200, 0)]),  # 0.5 m from a's end
        TrackLink("c", "ELR", "1100", 2, 3, [(201.5, 0), (300, 0)]),  # 1.5 m from b's end
    ])
    assert [(t.from_node, t.to_node) for t in links] == [(0, 1), (1, 2), (3, 4)]
    assert links[0].length() == 100
    assert links[0].ewkt() == "SRID=27700;LINESTRING(0.000 0.000,100.000 0.000)"


def test_route_between_points_part_way_along_links():
    graph = network()

    same_link = graph.route(Snap("up1", 100), Snap("up1", 900))
    assert same_link.length == pytest.approx(800)
    assert same_link.line.coords[0] == (X + 100, Y)

    across_a_node = graph.route(Snap("up1", 900), Snap("up2", 300))
    assert across_a_node.length == pytest.approx(400)
    assert list(across_a_node.line.coords) == [(X + 900, Y), (X + 1000, Y), (X + 1300, Y)]

    backwards = graph.route(Snap("up2", 300), Snap("up1", 900))
    assert list(backwards.line.coords) == [(X + 1300, Y), (X + 1000, Y), (X + 900, Y)]

    assert graph.route(Snap("up1", 100), Snap("siding", 50)) is None
    assert graph.components() == [6, 2]
    # The virtual nodes are taken out again
    assert graph.graph.number_of_nodes() == 8


def test_route_stays_on_one_track_when_ends_can_snap_to_either():
    graph = network()
    # Snapped to different tracks, the only way is out to the crossover at x=2000 and back
    assert graph.route(Snap("up1", 100), Snap("down", 900)).length == pytest.approx(900 + 1000 + 4 + 1100)
    # Given both tracks at each end, it stays on one
    both = graph.route([Snap("up1", 100), Snap("down", 100)], [Snap("down", 900), Snap("up1", 900)])
    assert both.length == pytest.approx(800)


def test_segment_path_falls_back_to_a_straight_line():
    graph = network()
    start = PlacedTiploc("AAA", (X + 100, Y), [Snap("up1", 100)])

    on_track = segment_path(graph, start, PlacedTiploc("BBB", (X + 1300, Y), [Snap("up2", 300)]))
    assert (on_track.method, on_track.fallback_reason, on_track.length) == ("track", None, pytest.approx(1200))

    off_network = segment_path(graph, start, PlacedTiploc("CCC", (X + 500, Y + 800), []))
    assert (off_network.method, off_network.fallback_reason) == ("straight", "off_network")
    assert off_network.length == pytest.approx(off_network.straight) == pytest.approx(894.4, abs=0.1)

    # 110 m apart in a straight line, but ~9 km round the loop
    detour = segment_path(graph, start, PlacedTiploc("DDD", (X - 10, Y + 10), [Snap("loop", 7990)]))
    assert (detour.method, detour.fallback_reason) == ("straight", "detour")

    no_path = segment_path(graph, start, PlacedTiploc("EEE", (X + 5050, Y + 5000), [Snap("siding", 50)]))
    assert no_path.fallback_reason == "no_path"


def located(tiploc, x, y, source):
    lon, lat = to_wgs84(X + x, Y + y)
    return TiplocLocation(tiploc, tiploc, lon, lat, X + x, Y + y, source, "good")


def track_link(asset_id, *points):
    return TrackLink(asset_id, "TST", "1100", 0, 1, [(X + x, Y + y) for x, y in points])


def test_snapping_grades_locations_by_distance_from_track(db):
    db.add_tiploc_locations([
        located("AAA", 100, 20, "naptan"),
        located("BBB", 1300, -30, "bplan"),
        located("FAR", 900, 900, "naptan"),  # a station off Network Rail track
        located("BAD", 1100, -900, "bplan"),  # a BPLAN point in the wrong place
    ])
    assert db.snap_tiploc_locations() is False  # no track model yet

    db.replace_track_links(assign_nodes([track_link("up1", (0, 0), (1000, 0)), track_link("up2", (1000, 0), (2000, 0))]))
    assert db.snap_tiploc_locations() is True

    db.cur.execute("SELECT tiploc, quality, snap_link, round(snap_along), round(snap_distance_m) FROM tiploc_locations ORDER BY tiploc")
    assert db.cur.fetchall() == [
        ("AAA", "good", "up1", 100, 20),
        ("BAD", "suspect", "up2", 100, 900),
        ("BBB", "good", "up2", 300, 30),
        ("FAR", "off_network", "up1", 900, 900),
    ]


def test_segment_paths_for_a_days_timetable(db):
    db.replace_track_links(assign_nodes([
        track_link("up1", (0, 0), (1000, 0)), track_link("up2", (1000, 0), (2000, 0)),
        track_link("down", (0, 4), (2000, 4)),
    ]))
    db.add_tiploc_locations([
        located("AAA", 100, 6, "naptan"), located("BBB", 1300, -2, "naptan"), located("FAR", 1500, 900, "naptan"),
    ])
    db.snap_tiploc_locations()
    db.add_schedules([parse_schedule({
        "rid": "202611218000004", "uid": "W00004", "trainId": "2T01", "ssd": "2026-11-21", "toc": "LE",
        "OR": {"tpl": "AAA", "wtd": "10:00"},
        "PP": {"tpl": "NOWHERE", "wtp": "10:02"},  # no location: AAA joins straight to BBB
        "IP": {"tpl": "BBB", "wta": "10:05", "wtd": "10:06"},
        "DT": {"tpl": "FAR", "wta": "10:10"},
    })])

    assert update(db, date(2026, 11, 21)) == {"track": 1, "off_network": 1}
    assert update(db, date(2026, 11, 21)) == {}  # only new pairs are routed

    db.cur.execute("""
        SELECT from_tiploc, to_tiploc, method, fallback_reason, round(length_m), ST_SRID(geom)
        FROM segment_paths ORDER BY from_tiploc
    """)
    # AAA is nearest the down line and BBB the up line; the route stays on one of them
    assert db.cur.fetchall() == [
        ("AAA", "BBB", "track", None, 1200, 4326),
        ("BBB", "FAR", "straight", "off_network", 924, 4326),
    ]
