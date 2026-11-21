from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Darwin times are UK local times relative to the train's scheduled start date (ssd)
LONDON = ZoneInfo("Europe/London")

# Darwin's rule for working out which day a time belongs to: compared with the previous time in the
# journey, a jump back of more than 6 hours means the next day, a jump forward of more than 18 hours
# means the previous day.
ROLLOVER_BACK = timedelta(hours=6)
ROLLOVER_FORWARD = timedelta(hours=18)


def convert_to_bool(value, default):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1")


def parse_time(value: str | None) -> time | None:
    """Parse a Darwin `HH:MM` or `HH:MM:SS` time."""
    if not value:
        return None
    parts = value.split(":")
    try:
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = int(parts[2]) if len(parts) > 2 else 0
        return time(hours, minutes, seconds)
    except (ValueError, IndexError):
        return None


def parse_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def local_datetime(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=LONDON)


def resolve_sequence(ssd: date, times: list[time | None]) -> list[datetime | None]:
    """
    Turn a journey's ordered times into full datetimes, rolling over midnight where needed.
    `None` entries are kept as `None` and don't affect the rollover of later times.
    """
    resolved: list[datetime | None] = []
    day = ssd
    previous: datetime | None = None

    for at in times:
        if at is None:
            resolved.append(None)
            continue

        current = local_datetime(day, at)
        if previous is not None:
            if current - previous < -ROLLOVER_BACK:
                day += timedelta(days=1)
            elif current - previous > ROLLOVER_FORWARD:
                day -= timedelta(days=1)
            current = local_datetime(day, at)

        resolved.append(current)
        previous = current

    return resolved


def nearest_datetime(at: time | None, anchor: datetime | None) -> datetime | None:
    """
    Pick the date for a time of day so that it lands closest to `anchor` (normally the planned time).
    Used for forecast and actual times, which Darwin sends without a date.
    """
    if at is None or anchor is None:
        return None
    anchor_local = anchor.astimezone(LONDON)
    candidates = [local_datetime(anchor_local.date() + timedelta(days=offset), at) for offset in (-1, 0, 1)]
    return min(candidates, key=lambda candidate: abs(candidate - anchor_local))
