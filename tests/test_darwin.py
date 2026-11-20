from conftest import envelope, load_fixture_lines

from darwin import order_schedule_stops, parse_message, parse_schedule


def test_parses_recorded_samples():
    messages = [parse_message(line) for line in load_fixture_lines("push_port_samples.jsonl")]
    assert all(message is not None for message in messages)
    assert [len(message.statuses) for message in messages] == [1, 1, 1, 1, 1]

    first = messages[0]
    assert first.sequence == 4367364
    assert first.kinds() == ["TS"]
    assert first.rids() == ["202609048087246"]

    status = first.statuses[0]
    assert status.update_origin == "TD"
    assert status.late_reason == 520
    location = status.locations[0]
    assert (location.tiploc, location.actual_arrival, location.actual_departure) == ("WDULWCH", "23:47", "23:48")
    assert (location.platform, location.platform_confirmed) == ("1", True)


def test_parses_forecasts_and_plain_platforms():
    messages = [parse_message(line) for line in load_fixture_lines("push_port_samples.jsonl")]
    status = messages[1].statuses[0]
    assert [loc.tiploc for loc in status.locations] == ["PRINRIS", "LTLKMBL", "MSHLLC", "AYLSBRY"]

    princes_risborough = status.locations[0]
    assert princes_risborough.actual_arrival == "00:37"
    assert princes_risborough.estimated_departure == "00:39"
    assert princes_risborough.working_arrival == "00:38:30"

    little_kimble = status.locations[1]
    assert little_kimble.estimated_pass == "00:44"
    assert (little_kimble.platform, little_kimble.platform_suppressed) == ("1", True)

    walthamstow = messages[3].statuses[0].locations[2]
    assert walthamstow.platform == "2"
    assert walthamstow.platform_confirmed is None


def test_ignores_junk():
    assert parse_message(b"not json") is None
    assert parse_message(b'{"bytes": null}') is None
    assert parse_message(envelope({"uR": {"TS": {"no": "rid"}}})).statuses == []


SCHEDULE = {
    "rid": "202609058000001", "uid": "W00001", "trainId": "2X99", "ssd": "2026-09-05", "toc": "LO",
    "trainCat": "OO", "isPassengerSvc": "true",
    # JSON groups locations by type, so IP and PP arrive out of order
    "OR": {"tpl": "AAA", "wtd": "23:40", "ptd": "23:40"},
    "IP": [{"tpl": "CCC", "wta": "23:58", "wtd": "23:59", "pta": "23:58", "ptd": "23:59"},
           {"tpl": "EEE", "wta": "00:20", "wtd": "00:21", "pta": "00:20", "ptd": "00:21", "can": "true"}],
    "PP": [{"tpl": "BBB", "wtp": "23:50"}, {"tpl": "DDD", "wtp": "00:05:30"}],
    "DT": {"tpl": "FFF", "wta": "00:40", "pta": "00:40"},
}


def test_schedule_stops_are_put_back_in_calling_order_across_midnight():
    schedule = parse_schedule(SCHEDULE)
    assert [stop.tiploc for stop in schedule.stops] == ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    assert [stop.location_type for stop in schedule.stops] == ["OR", "PP", "IP", "PP", "IP", "DT"]
    assert schedule.stops[4].cancelled is True
    assert schedule.is_passenger is True
    assert order_schedule_stops(None, schedule.stops) == schedule.stops


def test_schedule_and_deactivated_messages():
    message = parse_message(envelope({"uR": {"schedule": SCHEDULE, "deactivated": {"rid": "202609040000001"}}}, 7))
    assert message.kinds() == ["deactivated", "schedule"]
    assert message.rids() == ["202609058000001", "202609040000001"]
    assert len(message.schedules) == 1
    assert message.deactivated[0].rid == "202609040000001"
