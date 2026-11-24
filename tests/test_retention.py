import gzip
import json
from dataclasses import replace
from datetime import date, datetime

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

import retention
from config import load_config
from util import LONDON


def add_event(db, received_at: datetime, rid: str = "R1"):
    db.cur.execute(
        "INSERT INTO darwin_events (received_at, kinds, rids, payload) VALUES (%s, %s, %s, %s)",
        (received_at, ["TS"], [rid], Jsonb({"rid": rid})),
    )


def partitions(db) -> list[str]:
    return [name for name, _ in db.fetch_day_partitions("darwin_events")]


def rows_in(db, table: str) -> int:
    db.cur.execute(f"SELECT count(*) FROM {table}")
    return db.cur.fetchone()[0]


def test_partitions_follow_uk_days(db):
    retention.ensure_partitions(db, date(2026, 7, 1), ahead=1)
    # 22:30 UTC on 1 July is 23:30 in the UK (BST), and 23:30 UTC is 00:30 on 2 July
    add_event(db, datetime.fromisoformat("2026-07-01T22:30:00+00:00"))
    add_event(db, datetime.fromisoformat("2026-07-01T23:30:00+00:00"))
    db.commit()
    assert rows_in(db, "darwin_events_20260701") == 1
    assert rows_in(db, "darwin_events_20260702") == 1
    assert partitions(db) == ["darwin_events_20260630", "darwin_events_20260701", "darwin_events_20260702"]


def test_making_a_partition_moves_its_rows_out_of_the_default(db):
    add_event(db, datetime(2026, 3, 4, 12, tzinfo=LONDON))
    add_event(db, datetime(2026, 3, 5, 12, tzinfo=LONDON))
    db.commit()
    assert rows_in(db, "darwin_events_default") == 2

    assert db.ensure_day_partition("darwin_events", "received_at", date(2026, 3, 4))
    assert not db.ensure_day_partition("darwin_events", "received_at", date(2026, 3, 4))
    db.commit()
    assert rows_in(db, "darwin_events_20260304") == 1
    assert rows_in(db, "darwin_events_default") == 1
    assert rows_in(db, "darwin_events") == 2


def test_expire_archives_old_days_then_drops_them(db, tmp_path):
    today = date(2026, 11, 22)
    for day in (5, 7, 8, 21):
        db.ensure_day_partition("darwin_events", "received_at", date(2026, 11, day))
        add_event(db, datetime(2026, 11, day, 9, tzinfo=LONDON), rid=f"R{day}")
        add_event(db, datetime(2026, 11, day, 10, tzinfo=LONDON), rid=f"S{day}")
    db.commit()

    config = replace(load_config(), events_keep_days=14, archive_dir=str(tmp_path))
    assert retention.run(db, config, today, dry_run=True)["expired"] == [
        "darwin_events_20261105", "darwin_events_20261107",
    ]
    assert rows_in(db, "darwin_events") == 8

    result = retention.run(db, config, today)
    # 8 Nov is the oldest of the 14 days kept
    assert result["expired"] == ["darwin_events_20261105", "darwin_events_20261107"]
    assert "darwin_events_20261108" in partitions(db) and "darwin_events_20261129" in partitions(db)
    assert rows_in(db, "darwin_events") == 4

    with gzip.open(tmp_path / "darwin_events-2026-11-05.jsonl.gz", "rt") as f:
        lines = [json.loads(line) for line in f]
    assert [line["rids"] for line in lines] == [["R5"], ["S5"]]
    assert lines[0]["payload"] == {"rid": "R5"} and lines[0]["kinds"] == ["TS"]
    assert datetime.fromisoformat(lines[0]["received_at"]) == datetime(2026, 11, 5, 9, tzinfo=LONDON)
    assert not list(tmp_path.glob("*.partial"))


def test_keep_days_of_zero_keeps_everything(db, tmp_path):
    db.ensure_day_partition("darwin_events", "received_at", date(2020, 1, 1))
    db.commit()
    config = replace(load_config(), events_keep_days=0, archive_dir=str(tmp_path))
    assert retention.run(db, config, date(2026, 11, 22))["expired"] == []
    assert "darwin_events_20200101" in partitions(db)


def test_a_run_with_nothing_to_expire_leaves_no_transaction_open(db, tmp_path):
    # The timetable service sleeps a day after each run; an open transaction would stop vacuum for that long
    config = replace(load_config(), events_keep_days=14, archive_dir=str(tmp_path))
    assert retention.run(db, config, date(2026, 11, 22))["expired"] == []
    assert db.conn.info.transaction_status == TransactionStatus.IDLE
