"""
Parsing for Darwin Push Port messages (JSON flavour, as delivered over RailData's Kafka).

The JSON is a direct conversion of the Push Port XML, so any element may arrive as a single
object or as a list, and element text lives under the empty key `""`.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from json import JSONDecodeError
from typing import Any

from util import convert_to_bool, parse_time, resolve_sequence


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def element_text(value: Any) -> str | None:
    """Darwin elements with attributes put their text under `""`; plain elements are just strings."""
    if value is None:
        return None
    if isinstance(value, dict):
        text = value.get("")
        return str(text) if text is not None else None
    return str(value)


@dataclass
class TimeReport:
    """An arrival, departure or pass forecast/actual from a TS location."""
    actual: str | None = None  # at
    estimate: str | None = None  # et
    working_estimate: str | None = None  # wet
    actual_removed: bool = False  # atRemoved
    source: str | None = None  # src

    @classmethod
    def parse(cls, value: Any) -> "TimeReport | None":
        if not isinstance(value, dict):
            return None
        return cls(
            actual=value.get("at"),
            estimate=value.get("et"),
            working_estimate=value.get("wet"),
            actual_removed=convert_to_bool(value.get("atRemoved"), False),
            source=value.get("src"),
        )


@dataclass
class Location:
    tiploc: str
    working_arrival: str | None
    working_departure: str | None
    working_pass: str | None
    actual_arrival: str | None = None
    actual_departure: str | None = None
    actual_pass: str | None = None
    estimated_arrival: str | None = None
    estimated_departure: str | None = None
    estimated_pass: str | None = None
    platform: str | None = None
    platform_confirmed: bool | None = None
    platform_suppressed: bool | None = None
    sequence: int | None = None

    def planned_key(self) -> tuple[str | None, str | None, str | None]:
        """The working times identify which call this is when a train visits a TIPLOC more than once."""
        return (
            normalise_time(self.working_arrival),
            normalise_time(self.working_departure),
            normalise_time(self.working_pass),
        )

    def working_time(self) -> str | None:
        return self.working_departure or self.working_arrival or self.working_pass

    def is_pass(self) -> bool:
        return self.working_pass is not None and self.working_arrival is None and self.working_departure is None


def normalise_time(value: Any) -> str | None:
    """Normalise HH:MM / HH:MM:SS / datetime values to HH:MM:SS so they compare equal."""
    if value is None:
        return None
    if isinstance(value, datetime):
        from util import LONDON
        return value.astimezone(LONDON).strftime("%H:%M:%S")
    parsed = parse_time(str(value))
    return parsed.strftime("%H:%M:%S") if parsed else None


@dataclass
class TrainStatus:
    update_origin: str | None
    rid: str
    uid: str | None
    scheduled_start: str | None
    locations: list[Location]
    late_reason: int | None = None

    def starts(self) -> str | None:
        if len(self.locations) > 0 and self.scheduled_start:
            first = self.locations[0]
            return f"{self.scheduled_start} {first.working_departure or first.working_arrival or ''}".strip()

    def ends(self) -> str | None:
        if len(self.locations) > 0:
            last = self.locations[-1]
            return last.working_arrival or last.working_departure


@dataclass
class ScheduleStop:
    tiploc: str
    location_type: str  # OR, OPOR, IP, OPIP, PP, DT, OPDT
    activities: str | None = None
    planned_activities: str | None = None
    cancelled: bool = False
    platform: str | None = None
    public_arrival: str | None = None
    public_departure: str | None = None
    working_arrival: str | None = None
    working_departure: str | None = None
    working_pass: str | None = None

    def working_time(self) -> str | None:
        return self.working_departure or self.working_arrival or self.working_pass


@dataclass
class Schedule:
    rid: str
    uid: str | None
    train_id: str | None
    scheduled_start: str | None
    toc: str | None
    status: str | None = None
    category: str | None = None
    is_passenger: bool | None = None
    cancelled: bool | None = None
    deleted: bool | None = None
    cancel_reason: int | None = None
    stops: list[ScheduleStop] = field(default_factory=list)


@dataclass
class Deactivated:
    rid: str


@dataclass
class PushPortMessage:
    """One Kafka message, unwrapped. `raw` is the inner Push Port document, stored verbatim in the event log."""
    timestamp: str | None
    sequence: int | None
    raw: dict
    statuses: list[TrainStatus] = field(default_factory=list)
    schedules: list[Schedule] = field(default_factory=list)
    deactivated: list[Deactivated] = field(default_factory=list)

    def kinds(self) -> list[str]:
        """The update types in this message (TS, schedule, deactivated, OW, ...)."""
        update = self.raw.get("uR") or self.raw.get("sR") or {}
        return sorted(key for key in update if key[0].isalpha() and key not in ("updateOrigin", "requestSource", "requestID"))

    def rids(self) -> list[str]:
        rids = [s.rid for s in self.statuses] + [s.rid for s in self.schedules] + [d.rid for d in self.deactivated]
        return list(dict.fromkeys(rid for rid in rids if rid))


def to_int(value: Any) -> int | None:
    try:
        return int(element_text(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_platform(value: Any) -> tuple[str | None, bool | None, bool | None]:
    if value is None:
        return None, None, None
    if isinstance(value, dict):
        return (
            element_text(value),
            convert_to_bool(value.get("conf"), False),
            convert_to_bool(value.get("platsup"), False),
        )
    return str(value), None, None


def parse_location(loc: dict) -> Location:
    arrival = TimeReport.parse(loc.get("arr")) or TimeReport()
    departure = TimeReport.parse(loc.get("dep")) or TimeReport()
    passing = TimeReport.parse(loc.get("pass")) or TimeReport()
    platform, confirmed, suppressed = parse_platform(loc.get("plat"))

    return Location(
        tiploc=loc.get("tpl"),
        working_arrival=loc.get("wta"),
        working_departure=loc.get("wtd"),
        working_pass=loc.get("wtp"),
        actual_arrival=arrival.actual,
        actual_departure=departure.actual,
        actual_pass=passing.actual,
        estimated_arrival=arrival.estimate or arrival.working_estimate,
        estimated_departure=departure.estimate or departure.working_estimate,
        estimated_pass=passing.estimate or passing.working_estimate,
        platform=platform,
        platform_confirmed=confirmed,
        platform_suppressed=suppressed,
    )


def parse_train_status(status: dict, update_origin: str | None = None) -> TrainStatus | None:
    if not isinstance(status, dict) or not status.get("rid"):
        return None

    return TrainStatus(
        update_origin=update_origin,
        rid=status.get("rid"),
        uid=status.get("uid"),
        scheduled_start=status.get("ssd"),
        locations=[parse_location(loc) for loc in as_list(status.get("Location")) if isinstance(loc, dict)],
        late_reason=to_int(status.get("LateReason")),
    )


SCHEDULE_STOP_TYPES = ("OR", "OPOR", "IP", "OPIP", "PP", "DT", "OPDT")


def order_schedule_stops(ssd: str | None, stops: list[ScheduleStop]) -> list[ScheduleStop]:
    """
    The JSON conversion groups schedule locations by element type, losing the order between (say)
    IP and PP entries. Working times always increase along a journey, so sort by them, allowing for midnight.
    """
    from util import parse_date

    start = parse_date(ssd)
    if start is None:
        return stops

    origin_first = sorted(stops, key=lambda stop: stop.location_type not in ("OR", "OPOR"))
    # Resolve each stop independently against the origin's time, so a stop's day doesn't depend on list order
    origin_time = next((parse_time(stop.working_time()) for stop in origin_first if stop.working_time()), None)

    def sort_key(stop: ScheduleStop):
        at = parse_time(stop.working_time())
        if at is None or origin_time is None:
            return (1, 0.0)
        resolved = resolve_sequence(start, [origin_time, at])[1]
        return (0, resolved.timestamp())

    rank = {"OR": 0, "OPOR": 0, "DT": 2, "OPDT": 2}
    return sorted(stops, key=lambda stop: (sort_key(stop), rank.get(stop.location_type, 1)))


def parse_schedule(schedule: dict) -> Schedule | None:
    if not isinstance(schedule, dict) or not schedule.get("rid"):
        return None

    stops: list[ScheduleStop] = []
    for location_type in SCHEDULE_STOP_TYPES:
        for stop in as_list(schedule.get(location_type)):
            if not isinstance(stop, dict):
                continue
            stops.append(ScheduleStop(
                tiploc=stop.get("tpl"),
                location_type=location_type,
                activities=stop.get("act"),
                planned_activities=stop.get("planAct"),
                cancelled=convert_to_bool(stop.get("can"), False),
                platform=stop.get("plat"),
                public_arrival=stop.get("pta"),
                public_departure=stop.get("ptd"),
                working_arrival=stop.get("wta"),
                working_departure=stop.get("wtd"),
                working_pass=stop.get("wtp"),
            ))

    return Schedule(
        rid=schedule.get("rid"),
        uid=schedule.get("uid"),
        train_id=schedule.get("trainId"),
        scheduled_start=schedule.get("ssd"),
        toc=schedule.get("toc"),
        status=schedule.get("status"),
        category=schedule.get("trainCat"),
        is_passenger=convert_to_bool(schedule.get("isPassengerSvc"), True),
        cancelled=convert_to_bool(schedule.get("can"), False),
        deleted=convert_to_bool(schedule.get("deleted"), False),
        cancel_reason=to_int(schedule.get("cancelReason")),
        stops=order_schedule_stops(schedule.get("ssd"), stops),
    )


def unwrap_kafka_message(data: bytes | str) -> tuple[dict, int | None] | None:
    """Kafka messages wrap the Push Port JSON (as a string) in `bytes`, with the sequence in `properties`."""
    try:
        envelope = json.loads(data)
        if not isinstance(envelope, dict) or not (inner := envelope.get("bytes")):
            return None
        document = json.loads(inner)
    except (JSONDecodeError, TypeError, UnicodeDecodeError):
        return None

    if not isinstance(document, dict):
        return None

    sequence = None
    properties = envelope.get("properties") or {}
    sequence_property = properties.get("PushPortSequence") or {}
    if isinstance(sequence_property, dict):
        sequence = to_int(sequence_property.get("string") or sequence_property.get("long") or sequence_property.get("integer"))

    return document, sequence


def parse_message(data: bytes | str) -> PushPortMessage | None:
    unwrapped = unwrap_kafka_message(data)
    if unwrapped is None:
        return None
    document, sequence = unwrapped

    message = PushPortMessage(timestamp=document.get("ts"), sequence=sequence, raw=document)

    update = document.get("uR") or document.get("sR")
    if not isinstance(update, dict):
        return message

    origin = update.get("updateOrigin")
    message.statuses = [s for s in (parse_train_status(ts, origin) for ts in as_list(update.get("TS"))) if s]
    message.schedules = [s for s in (parse_schedule(sc) for sc in as_list(update.get("schedule"))) if s]
    message.deactivated = [
        Deactivated(rid=d.get("rid")) for d in as_list(update.get("deactivated")) if isinstance(d, dict) and d.get("rid")
    ]
    return message
