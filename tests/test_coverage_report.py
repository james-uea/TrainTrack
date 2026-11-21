from datetime import date

from coverage_report import report, summary_line
from darwin import parse_schedule

SCHEDULE = {
    "rid": "202611218000003", "uid": "W00003", "trainId": "2C01", "ssd": "2026-11-21", "toc": "LE",
    "OR": {"tpl": "AAA", "wtd": "10:00"},
    "PP": [{"tpl": "JJJ", "wtp": "10:05"}, {"tpl": "KKK", "wtp": "10:15"}],
    "IP": [{"tpl": "BBB", "wta": "10:10", "wtd": "10:11"}, {"tpl": "CCC", "wta": "10:20", "wtd": "10:21"}],
    "DT": {"tpl": "DDD", "wta": "10:30"},
}


def place(db, tiploc, quality):
    db.cur.execute("""
        INSERT INTO tiploc_locations (tiploc, geom, source, quality)
        VALUES (%s, ST_SetSRID(ST_MakePoint(1, 52), 4326), 'naptan', %s)
    """, (tiploc, quality))


def test_coverage_counts_and_unplaced_tiplocs(db):
    db.add_schedules([parse_schedule(SCHEDULE)])
    place(db, "AAA", "good")
    place(db, "BBB", "good")
    place(db, "JJJ", "good")
    place(db, "DDD", "good")
    place(db, "KKK", "suspect")  # not usable
    # CCC has no row at all

    coverage = db.fetch_coverage(date(2026, 11, 21))
    assert coverage == {
        "passenger calls": (3, 4),
        "all calls": (3, 4),
        "passing points": (1, 2),
        "all stops": (4, 6),
        "call-to-call segments": (1, 3),  # AAA-BBB placed; BBB-CCC and CCC-DDD not
    }
    assert summary_line(coverage).startswith("passenger calls 75.0%, all calls 75.0%")

    assert db.fetch_unplaced_tiplocs(date(2026, 11, 21), 10) == [
        ("CCC", "CCC", "missing", 1, 0),
        ("KKK", "KKK", "suspect", 0, 1),
    ]
    assert "CCC" in report(db, date(2026, 11, 21), 10)
