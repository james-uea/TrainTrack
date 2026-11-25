"""
Network Rail Train Describer messages. Signalling splits the track into berths, roughly from one signal to the next,
and reports each train's headcode as it steps from one berth to the next.

Each Kafka message is a JSON list of items such as `{"CA_MSG": {"area_id": "R2", "time": "1795639841000",
"from": "3279", "to": "3281", "descr": "1B54", ...}}`. Only the berth (C-class) items are kept: CA steps, CB cancels
and CC interposes. Heartbeats (CT) and signalling state (S-class) are counted and dropped.
"""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

KEPT = {"CA_MSG": "CA", "CB_MSG": "CB", "CC_MSG": "CC"}


@dataclass(frozen=True)
class Step:
    at: datetime
    area_id: str
    from_berth: str | None  # None for an interpose
    to_berth: str | None  # None for a cancel
    descr: str  # the train's headcode
    msg_type: str  # CA, CB or CC


def parse_td(data: bytes, counts: Counter | None = None) -> list[Step]:
    """The berth items in one Kafka message. `counts`, if given, gets one count per item kind, kept or not."""
    try:
        items = json.loads(data)
    except ValueError:
        if counts is not None:
            counts["unparsed"] += 1
        return []
    steps = []
    for item in items if isinstance(items, list) else [items]:
        if not isinstance(item, dict):
            continue
        for kind, body in item.items():
            if counts is not None:
                counts[kind.removesuffix("_MSG")] += 1
            msg_type = KEPT.get(kind)
            if msg_type is None or not isinstance(body, dict) or not body.get("descr") or not body.get("time"):
                continue
            steps.append(Step(
                datetime.fromtimestamp(int(body["time"]) / 1000, UTC),
                body.get("area_id", ""),
                body.get("from") or None,
                body.get("to") or None,
                body["descr"],
                msg_type,
            ))
    return steps
