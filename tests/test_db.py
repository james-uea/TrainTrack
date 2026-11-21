"""Database tests. Run with TEST_DATABASE_URL set (the database is wiped)."""

from datetime import datetime

from conftest import envelope
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


def status(*locations, late_reason=None):
    ts = {"rid": RID, "uid": "W00001", "ssd": "2026-09-05", "Location": list(locations)}
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
        {"tpl": "ZZZ", "wtp": "00:06"},
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


def test_reading_for_the_terminal_app(db):
    db.add_schedules([parse_schedule(SCHEDULE)])
    db.handle_message(status({"tpl": "AAA", "wtd": "23:40", "dep": {"at": "23:41"}}))

    [train] = db.fetch_train_journeys()
    assert (train.origin, train.destination, train.last_location, train.delay_minutes) == ("AAA", "FFF", "AAA", 1)
    assert [s.tiploc for s in db.fetch_train_stops(RID)] == ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
