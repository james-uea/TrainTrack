from datetime import date, datetime, time

from util import LONDON, convert_to_bool, nearest_datetime, parse_time, resolve_sequence


def london(*args) -> datetime:
    return datetime(*args, tzinfo=LONDON)


def test_parse_time_handles_seconds_and_junk():
    assert parse_time("23:19") == time(23, 19)
    assert parse_time("00:38:30") == time(0, 38, 30)
    assert parse_time("") is None
    assert parse_time("soon") is None


def test_convert_to_bool_accepts_darwin_lowercase():
    assert convert_to_bool("true", False) is True
    assert convert_to_bool("True", False) is True
    assert convert_to_bool("false", True) is False
    assert convert_to_bool(None, True) is True


def test_resolve_sequence_rolls_over_midnight():
    times = [time(23, 30), time(23, 55), None, time(0, 10), time(1, 0)]
    assert resolve_sequence(date(2026, 9, 4), times) == [
        london(2026, 9, 4, 23, 30),
        london(2026, 9, 4, 23, 55),
        None,
        london(2026, 9, 5, 0, 10),
        london(2026, 9, 5, 1, 0),
    ]


def test_resolve_sequence_keeps_small_backwards_steps_on_the_same_day():
    # Darwin can list a pass a minute before the previous departure; that isn't a new day
    times = [time(10, 0), time(9, 59)]
    assert resolve_sequence(date(2026, 9, 4), times) == [london(2026, 9, 4, 10, 0), london(2026, 9, 4, 9, 59)]


def test_nearest_datetime_picks_the_closest_day():
    planned = london(2026, 9, 4, 23, 50)
    assert nearest_datetime(time(0, 5), planned) == london(2026, 9, 5, 0, 5)  # late, after midnight
    assert nearest_datetime(time(23, 48), planned) == london(2026, 9, 4, 23, 48)  # early

    planned = london(2026, 9, 5, 0, 2)
    assert nearest_datetime(time(23, 59), planned) == london(2026, 9, 4, 23, 59)  # early, before midnight
