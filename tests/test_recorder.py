from datetime import UTC, datetime, timedelta

from frames import pack, unpack
from live import Clock, Snapshot
from positions import Journey, Position
from recorder import Recorder

AT = datetime(2026, 11, 21, 14, 44, 50, tzinfo=UTC)


def position(to_tiploc="LEDBRNJ", lat=51.9):
    return Position(lat, -0.69, 110.0, "running", "high", "BLTCHLY", to_tiploc, 0.5, 2, 30.0,
                    AT - timedelta(minutes=1), AT + timedelta(minutes=2))


def snapshot(at, *trains):
    return Snapshot(at, [(Journey(rid, [], "1A48", "VT"), pos) for rid, pos in trains], active=len(trains) + 1)


def test_a_run_starts_with_a_keyframe_then_stores_only_changes():
    recorder = Recorder(Clock())
    first = recorder.frame(snapshot(AT, ("A", position()), ("B", position())))
    assert first.keyframe and first.trains == 2 and first.active == 3
    assert [t["rid"] for t in unpack(first.data)["trains"]] == ["A", "B"]

    # A moved along its segment (nothing to send); B reached its next segment
    second = recorder.frame(snapshot(AT + timedelta(seconds=5), ("A", position(lat=51.91)), ("B", position("WOLVRTN"))))
    assert not second.keyframe
    changes = unpack(second.data)
    assert [t["rid"] for t in changes["trains"]] == ["B"] and changes["removed"] == []

    # The next 5-minute slot starts at 14:45:00, so that frame is a keyframe again
    third = recorder.frame(snapshot(AT + timedelta(seconds=10), ("B", position("WOLVRTN"))))
    assert third.keyframe and third.trains == 1


def test_a_frame_that_wasnt_stored_makes_the_next_one_a_keyframe():
    recorder = Recorder(Clock())
    recorder.frame(snapshot(AT, ("A", position())))
    recorder.lost()
    assert recorder.frame(snapshot(AT + timedelta(seconds=5), ("A", position()))).keyframe


def add(db, at, keyframe=False, source="recorded"):
    db.add_frame(at, keyframe, source, 0, 0, pack({"at": at.isoformat()}))


def test_frames_for_a_window_start_from_the_keyframe_before_it(db):
    start = datetime(2026, 11, 21, 14, 0, tzinfo=UTC)
    for tick in range(12 * 12):  # 14:00 to 14:11:55, a keyframe every 5 minutes
        add(db, start + timedelta(seconds=5 * tick), keyframe=tick % 60 == 0)
    db.commit()

    rows = db.fetch_frames(start + timedelta(minutes=7), start + timedelta(minutes=8))
    assert rows[0][0] == start + timedelta(minutes=5) and rows[0][1]
    assert rows[-1][0] == start + timedelta(minutes=8)
    assert len(rows) == 3 * 12 + 1
    assert unpack(rows[-1][3]) == {"at": (start + timedelta(minutes=8)).isoformat()}

    # Long after the last keyframe there's nothing to rebuild from
    assert db.fetch_frames(start + timedelta(hours=1), start + timedelta(hours=2)) == []


def test_in_a_gap_frames_start_from_the_next_keyframe(db):
    later = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
    add(db, later, keyframe=True)
    add(db, later + timedelta(seconds=5))
    db.commit()
    rows = db.fetch_frames(later - timedelta(minutes=30), later + timedelta(minutes=1))
    assert [row[0] for row in rows] == [later, later + timedelta(seconds=5)]


def test_runs_split_at_gaps_and_where_the_source_changes(db):
    start = datetime(2026, 11, 21, 14, 0, tzinfo=UTC)
    for tick in range(10):
        add(db, start + timedelta(seconds=5 * tick), keyframe=tick == 0, source="computed")
    for tick in range(10, 20):
        add(db, start + timedelta(seconds=5 * tick), keyframe=tick == 10)
    for tick in range(40, 45):  # after a 100 s gap
        add(db, start + timedelta(seconds=5 * tick), keyframe=tick == 40)
    db.commit()
    runs = db.fetch_frame_runs(start, start + timedelta(hours=1), timedelta(seconds=30))
    assert [(run[0] - start).seconds for run in runs] == [0, 50, 200]
    assert [(run[2], run[3]) for run in runs] == [("computed", 10), ("recorded", 10), ("recorded", 5)]
    assert db.count_frames(start, start + timedelta(hours=1)) == (15, 10)
    db.delete_computed_frames(start, start + timedelta(hours=1))
    assert db.count_frames(start, start + timedelta(hours=1)) == (15, 0)
