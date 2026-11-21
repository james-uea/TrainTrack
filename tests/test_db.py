"""Database tests. Run with TEST_DATABASE_URL set (the database is wiped)."""

from datetime import datetime

from conftest import envelope, load_fixture_lines
from test_darwin import SCHEDULE

from darwin import parse_message, parse_schedule
from util import LONDON

RID = SCHEDULE["rid"]


def london(*args) -> datetime:
    return datetime(*args, tzinfo=LONDON)


def journey(db, *columns):
    db.cur.execute(f"SELECT {', '.join(columns)} FROM train_journeys WHERE rid = %s", (RID,))
    return db.cur.fetchone()


def stop(db, tiploc, *columns):
    db.cur.execute(f"SELECT {', '.join(columns)} FROM train_stops WHERE rid = %s AND tiploc = %s", (RID, tiploc))
    return db.cur.fetchone()


def status(*locations, late_reason=None, rid=RID):
    ts = {"rid": rid, "uid": "W00001", "ssd": "2026-09-05", "Location": list(locations)}
    if late_reason:
        ts["LateReason"] = late_reason
    return parse_message(envelope({"ts": "2026-09-05T23:59:00+01:00", "uR": {"updateOrigin": "TD", "TS": ts}}, 1))


def test_timetable_times_cross_midnight(db):
    db.add_schedules([parse_schedule(SCHEDULE)])

    assert stop(db, "AAA", "working_departure", "public_departure") == (london(2026, 9, 5, 23, 40),) * 2
    assert stop(db, "DDD", "working_pass") == (london(2026, 9, 6, 0, 5, 30),)
    assert stop(db, "FFF", "working_arrival") == (london(2026, 9, 6, 0, 40),)
    db.cur.execute("SELECT location_name FROM locations WHERE tiploc = 'AAA'")
    assert db.cur.fetchone() == ("AAA",)  # placeholder for a TIPLOC missing from reference data


def test_status_sets_actuals_forecasts_and_position(db):
    db.add_schedules([parse_schedule(SCHEDULE)])

    counts = db.handle_message(status(
        {"tpl": "CCC", "wta": "23:58", "wtd": "23:59", "arr": {"at": "00:01"}, "dep": {"at": "00:03"},
         "plat": {"conf": "true", "": "2"}},
        {"tpl": "DDD", "wtp": "00:05:30", "pass": {"et": "00:09"}},
        {"tpl": "ZZZ", "wta": "00:06", "wtd": "00:07"},  # a call that isn't in the schedule
        late_reason="520",
    ))
    assert counts["statuses"] == 1
    assert counts["unmatched_locations"] == 1

    assert stop(db, "CCC", "actual_arrival", "actual_departure", "platform", "platform_confirmed") == (
        london(2026, 9, 6, 0, 1), london(2026, 9, 6, 0, 3), "2", True,
    )
    assert stop(db, "DDD", "estimated_pass") == (london(2026, 9, 6, 0, 9),)
    assert journey(db, "last_tiploc", "last_report_type", "last_reported_at", "delay_minutes", "late_reason") == (
        "CCC", "departure", london(2026, 9, 6, 0, 3), 4, 520,
    )

    db.cur.execute("SELECT kinds, rids, push_port_sequence FROM darwin_events")
    assert db.cur.fetchall() == [(["TS"], [RID], 1)]


def test_status_for_unknown_train_is_logged_but_not_applied(db):
    counts = db.handle_message(status({"tpl": "CCC", "wta": "23:58", "arr": {"at": "00:01"}}))
    assert counts["unknown_trains"] == 1
    db.cur.execute("SELECT count(*) FROM darwin_events")
    assert db.cur.fetchone() == (1,)


def test_schedule_message_adds_a_train_and_keeps_live_data(db):
    db.handle_message(parse_message(envelope({"uR": {"schedule": SCHEDULE}})))
    assert journey(db, "train_id", "toc_code", "category") == ("2X99", "LO", "OO")

    db.handle_message(status({"tpl": "AAA", "wtd": "23:40", "dep": {"at": "23:41"}}))

    # A revised schedule (extra stop at DDD) replaces the stops but keeps the departure from AAA
    revised = {**SCHEDULE, "IP": SCHEDULE["IP"] + [{"tpl": "DDD", "wta": "00:08", "wtd": "00:09"}], "PP": SCHEDULE["PP"][:1]}
    db.handle_message(parse_message(envelope({"uR": {"schedule": revised}})))

    db.cur.execute("SELECT tiploc, location_type FROM train_stops WHERE rid = %s ORDER BY sequence", (RID,))
    assert db.cur.fetchall() == [("AAA", "OR"), ("BBB", "PP"), ("CCC", "IP"), ("DDD", "IP"), ("EEE", "IP"), ("FFF", "DT")]
    assert stop(db, "AAA", "actual_departure") == (london(2026, 9, 5, 23, 41),)
    assert journey(db, "last_tiploc", "delay_minutes") == ("AAA", 1)


def test_deactivation(db):
    db.add_schedules([parse_schedule(SCHEDULE)])
    db.handle_message(parse_message(envelope({"uR": {"deactivated": {"rid": RID}}})))
    assert journey(db, "deactivated") == (True,)


def test_reloading_the_timetable_keeps_live_data(db):
    db.add_schedules([parse_schedule(SCHEDULE)])
    db.handle_message(status({"tpl": "AAA", "wtd": "23:40", "dep": {"at": "23:41"}}))
    db.add_schedules([parse_schedule(SCHEDULE)])
    assert stop(db, "AAA", "actual_departure") == (london(2026, 9, 5, 23, 41),)


def test_reloading_after_a_schedule_message_renumbered_stops(db):
    db.add_schedules([parse_schedule(SCHEDULE)])
    # A schedule message adds a passing point near the start, shifting every later stop along one
    revised = {**SCHEDULE, "PP": [{"tpl": "ABB", "wtp": "23:45"}, *SCHEDULE["PP"]]}
    db.handle_message(parse_message(envelope({"uR": {"schedule": revised}})))
    db.handle_message(status({"tpl": "CCC", "wta": "23:58", "wtd": "23:59", "arr": {"at": "00:01"}}))

    db.add_schedules([parse_schedule(SCHEDULE)])  # the timetable again, without ABB

    db.cur.execute("SELECT sequence, tiploc, actual_arrival FROM train_stops WHERE rid = %s ORDER BY sequence", (RID,))
    assert db.cur.fetchall() == [
        (0, "AAA", None), (1, "BBB", None), (2, "CCC", london(2026, 9, 6, 0, 1)), (3, "DDD", None), (4, "EEE", None),
        (5, "FFF", None),
    ]


def test_reading_for_the_terminal_app(db):
    db.add_schedules([parse_schedule(SCHEDULE)])
    db.handle_message(status({"tpl": "AAA", "wtd": "23:40", "dep": {"at": "23:41"}}))

    [train] = db.fetch_train_journeys()
    assert (train.origin, train.destination, train.last_location, train.delay_minutes) == ("AAA", "FFF", "AAA", 1)
    assert [s.tiploc for s in db.fetch_train_stops(RID)] == ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


# Passing points: Darwin's working pass times drift from the timetable and it reports passes the schedule lacks

LOOP = {
    "rid": "202611218000002", "uid": "W00002", "trainId": "2L01", "ssd": "2026-11-21", "toc": "ME",
    "OR": {"tpl": "AAA", "wtd": "10:00"},
    "PP": [{"tpl": "JJJ", "wtp": "10:10"}, {"tpl": "JJJ", "wtp": "10:30"}],
    "IP": {"tpl": "BBB", "wta": "10:20", "wtd": "10:21"},
    "DT": {"tpl": "ZZZ", "wta": "10:40"},
}
LOOP_RID = LOOP["rid"]


def loop_stops(db, *columns):
    db.cur.execute(f"SELECT {', '.join(columns)} FROM train_stops WHERE rid = %s ORDER BY sequence", (LOOP_RID,))
    return db.cur.fetchall()


def test_pass_time_a_few_minutes_out_matches_the_nearest_visit(db):
    db.add_schedules([parse_schedule(LOOP)])

    counts = db.handle_message(status(
        {"tpl": "JJJ", "wtp": "10:12", "pass": {"at": "10:13"}},
        {"tpl": "JJJ", "wtp": "10:28", "pass": {"et": "10:29"}},
        rid=LOOP_RID,
    ))

    assert (counts["unmatched_locations"], counts["added_locations"]) == (0, 0)
    assert loop_stops(db, "tiploc", "actual_pass", "estimated_pass") == [
        ("AAA", None, None),
        ("JJJ", london(2026, 11, 21, 10, 13), None),
        ("BBB", None, None),
        ("JJJ", None, london(2026, 11, 21, 10, 29)),
        ("ZZZ", None, None),
    ]


def test_pass_time_too_far_from_either_visit_is_unmatched(db):
    db.add_schedules([parse_schedule(LOOP)])
    counts = db.handle_message(status({"tpl": "JJJ", "wtp": "10:20", "pass": {"at": "10:20"}}, rid=LOOP_RID))
    assert counts["unmatched_locations"] == 1
    assert loop_stops(db, "actual_pass") == [(None,)] * 5


def test_pass_missing_from_the_schedule_is_stored_in_order(db):
    db.add_schedules([parse_schedule(LOOP)])
    db.handle_message(status({"tpl": "AAA", "wtd": "10:00", "dep": {"at": "10:01"}}, rid=LOOP_RID))

    counts = db.handle_message(status(
        {"tpl": "KKK", "wtp": "10:15", "pass": {"at": "10:16"}},
        {"tpl": "BBB", "wta": "10:20", "wtd": "10:21", "arr": {"at": "10:22"}},
        rid=LOOP_RID,
    ))

    assert (counts["unmatched_locations"], counts["added_locations"]) == (0, 1)
    assert loop_stops(db, "sequence", "tiploc", "location_type", "added_from_status", "actual_pass") == [
        (0, "AAA", "OR", False, None),
        (1, "JJJ", "PP", False, None),
        (2, "KKK", "PP", True, london(2026, 11, 21, 10, 16)),
        (3, "BBB", "IP", False, None),
        (4, "JJJ", "PP", False, None),
        (5, "ZZZ", "DT", False, None),
    ]
    assert loop_stops(db, "actual_arrival")[3] == (london(2026, 11, 21, 10, 22),)
    db.cur.execute("SELECT last_tiploc FROM train_journeys WHERE rid = %s", (LOOP_RID,))
    assert db.cur.fetchone() == ("BBB",)

    # The next report for it matches the stored row instead of adding another
    counts = db.handle_message(status({"tpl": "KKK", "wtp": "10:15", "pass": {"at": "10:16"}}, rid=LOOP_RID))
    assert (counts["unmatched_locations"], counts["added_locations"]) == (0, 0)
    assert len(loop_stops(db, "tiploc")) == 6


def test_locations_still_unmatched(db):
    db.add_schedules([parse_schedule(LOOP)])

    counts = db.handle_message(status(
        {"tpl": "KKK", "wtp": "09:50"},  # a pass before the train starts
        {"tpl": "KKK", "wtp": "10:50"},  # and after it ends
        {"tpl": "MMM", "wta": "10:15", "wtd": "10:16"},  # a call that isn't in the schedule
        rid=LOOP_RID,
    ))

    assert (counts["unmatched_locations"], counts["added_locations"]) == (3, 0)
    assert len(loop_stops(db, "tiploc")) == 5


# Recorded 2026-11-21: 2V35 Banbury → Didcot passes Tackley, which the day's timetable doesn't list
TIMETABLE_2V35 = {
    "rid": "202611216700781", "uid": "C00781", "trainId": "2V35", "ssd": "2026-11-21", "toc": "GW",
    "OR": {"tpl": "BNBR", "wtd": "13:34"},
    "IP": [{"tpl": "KINSSTN", "wta": "13:38:30", "wtd": "13:39:30"}, {"tpl": "HEYFORD", "wta": "13:47", "wtd": "13:48"},
           {"tpl": "OXFD", "wta": "14:03", "wtd": "14:05"}],
    "PP": [{"tpl": "AYNHOJ", "wtp": "13:42"}, {"tpl": "WVCTJN", "wtp": "13:58:30"}, {"tpl": "OXFDNNJ", "wtp": "14:00"}],
    "DT": {"tpl": "DIDCOTP", "wta": "14:23"},
}


def test_recorded_pass_missing_from_the_timetable(db):
    db.add_schedules([parse_schedule(TIMETABLE_2V35)])
    [line] = load_fixture_lines("added_passing_point.jsonl")

    counts = db.handle_message(parse_message(line))

    assert (counts["unmatched_locations"], counts["added_locations"]) == (0, 1)
    db.cur.execute("""
        SELECT tiploc, added_from_status, estimated_pass FROM train_stops
        WHERE rid = %s ORDER BY sequence
    """, (TIMETABLE_2V35["rid"],))
    rows = db.cur.fetchall()
    assert [row[0] for row in rows] == ["BNBR", "KINSSTN", "AYNHOJ", "HEYFORD", "TACKLEY", "WVCTJN", "OXFDNNJ", "OXFD", "DIDCOTP"]
    assert rows[4] == ("TACKLEY", True, datetime(2026, 11, 21, 13, 51, tzinfo=LONDON))
