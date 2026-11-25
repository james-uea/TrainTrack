"""Train Describer messages: parsing (no database) and storing berth steps (needs TEST_DATABASE_URL)."""

import json
from collections import Counter
from datetime import UTC, datetime

from td import Step, parse_td

AT = 1795639841000  # 2026-11-25 20:50:41 UTC


def message(*items) -> bytes:
    return json.dumps(list(items)).encode()


def test_berth_items_are_kept_and_the_rest_counted():
    counts = Counter()
    steps = parse_td(message(
        {"CA_MSG": {"msg_type": "CA", "area_id": "R2", "time": str(AT), "from": "3279", "to": "3281", "descr": "1B54"}},
        {"CB_MSG": {"msg_type": "CB", "area_id": "R2", "time": str(AT), "from": "3281", "descr": "1B54"}},
        {"CC_MSG": {"msg_type": "CC", "area_id": "D1", "time": str(AT + 1500), "to": "1635", "descr": "2N10"}},
        {"CT_MSG": {"msg_type": "CT", "area_id": "ZR", "time": str(AT), "report_time": "1907"}},
        {"SF_MSG": {"msg_type": "SF", "area_id": "T2", "time": str(AT), "address": "38", "data": "2B"}},
    ), counts)

    at = datetime(2026, 11, 25, 20, 50, 41, tzinfo=UTC)
    assert steps == [
        Step(at, "R2", "3279", "3281", "1B54", "CA"),
        Step(at, "R2", "3281", None, "1B54", "CB"),
        Step(datetime(2026, 11, 25, 20, 50, 42, 500000, tzinfo=UTC), "D1", None, "1635", "2N10", "CC"),
    ]
    assert counts == {"CA": 1, "CB": 1, "CC": 1, "CT": 1, "SF": 1}


def test_a_message_that_isnt_json_is_counted_not_raised():
    counts = Counter()
    assert parse_td(b"not json", counts) == []
    assert counts["unparsed"] == 1


def test_steps_are_stored_and_read_back_in_time_order(db):
    later = datetime(2026, 11, 25, 20, 52, tzinfo=UTC)
    earlier = datetime(2026, 11, 25, 20, 51, tzinfo=UTC)
    db.add_td_steps([
        Step(later, "R2", "3281", "3283", "1B54", "CA"),
        Step(earlier, "R2", "3279", "3281", "1B54", "CA"),
        Step(earlier, "R2", "3281", None, "1B54", "CB"),
    ])
    db.commit()

    rows = db.fetch_td_steps(datetime(2026, 11, 25, 20, tzinfo=UTC), datetime(2026, 11, 25, 21, tzinfo=UTC))
    assert rows == [(earlier.timestamp(), "R2", "3279", "3281", "1B54"), (later.timestamp(), "R2", "3281", "3283", "1B54")]
