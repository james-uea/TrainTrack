import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from config import load_config
from darwin import Location, PushPortMessage, Schedule, TrainStatus, normalise_time
from util import LONDON, nearest_datetime, parse_date, parse_time, resolve_sequence

logger = logging.getLogger(__name__)

# How far Darwin's working time for a location may be from the planned one when a train calls or passes
# somewhere more than once and the times don't match exactly
MATCH_TOLERANCE = timedelta(minutes=5)

STOP_COLUMNS = (
    "rid", "sequence", "tiploc", "location_type", "activities", "planned_activities", "cancelled", "platform",
    "public_arrival", "public_departure", "working_arrival", "working_departure", "working_pass",
)


@dataclass
class StopRow:
    sequence: int
    tiploc: str
    working_arrival: datetime | None
    working_departure: datetime | None
    working_pass: datetime | None

    def planned_key(self):
        return (
            normalise_time(self.working_arrival),
            normalise_time(self.working_departure),
            normalise_time(self.working_pass),
        )

    def any_working(self) -> datetime | None:
        return self.working_departure or self.working_arrival or self.working_pass


@dataclass
class JourneySummary:
    rid: str
    uid: str
    scheduled_start: object
    toc: str | None
    origin: str | None
    destination: str | None
    departs: datetime | None
    arrives: datetime | None
    last_location: str | None
    last_report_type: str | None
    last_reported_at: datetime | None
    delay_minutes: int | None
    cancelled: bool | None


def schedule_stop_rows(schedule: Schedule) -> list[tuple]:
    """Build `train_stops` rows for a schedule, resolving every time to a full timestamp."""
    ssd = parse_date(schedule.scheduled_start)
    if ssd is None:
        return []

    # Working times decide which day each stop falls on; public times are matched to the nearest working time
    working = resolve_sequence(ssd, [parse_time(stop.working_time()) for stop in schedule.stops])

    rows = []
    for sequence, (stop, anchor) in enumerate(zip(schedule.stops, working, strict=True)):
        def resolve(value, anchor=anchor):
            return nearest_datetime(parse_time(value), anchor)

        rows.append((
            schedule.rid, sequence, stop.tiploc, stop.location_type, stop.activities, stop.planned_activities,
            stop.cancelled, stop.platform,
            resolve(stop.public_arrival), resolve(stop.public_departure),
            resolve(stop.working_arrival), resolve(stop.working_departure), resolve(stop.working_pass),
        ))
    return rows


def match_location(location: Location, stops: list[StopRow]) -> StopRow | None:
    """Find the stop a Darwin location refers to: same TIPLOC and working times, or the only call at that TIPLOC."""
    at_tiploc = [stop for stop in stops if stop.tiploc == location.tiploc]
    if not at_tiploc:
        return None

    key = location.planned_key()
    for stop in at_tiploc:
        if stop.planned_key() == key:
            return stop

    # Darwin sometimes sends a subset of the working times; match on whichever were sent
    partial = [
        stop for stop in at_tiploc
        if all(sent is None or sent == have for sent, have in zip(key, stop.planned_key(), strict=True))
    ]
    if len(partial) == 1:
        return partial[0]

    if len(at_tiploc) == 1:
        return at_tiploc[0]

    # The train is here more than once and Darwin's working time differs a little from every call:
    # take the closest within tolerance
    return nearest_stop(location, at_tiploc)


def time_of_day_gap(at: time, planned: datetime) -> timedelta:
    """How far apart two times of day are, ignoring the date (so 23:59 and 00:01 are 2 minutes apart)."""
    planned_local = planned.astimezone(LONDON)
    seconds = abs(
        (at.hour * 3600 + at.minute * 60 + at.second)
        - (planned_local.hour * 3600 + planned_local.minute * 60 + planned_local.second)
    )
    return timedelta(seconds=min(seconds, 86400 - seconds))


def nearest_stop(location: Location, stops: list[StopRow]) -> StopRow | None:
    """The stop whose working time is nearest the location's, if within MATCH_TOLERANCE and not tied."""
    at = parse_time(location.working_time())
    if at is None:
        return None

    gaps = []
    for stop in stops:
        planned = (stop.working_pass if location.is_pass() else None) or stop.any_working()
        if planned is not None:
            gaps.append((time_of_day_gap(at, planned), stop))
    gaps = sorted((gap for gap in gaps if gap[0] <= MATCH_TOLERANCE), key=lambda gap: gap[0])

    if not gaps or (len(gaps) > 1 and gaps[0][0] == gaps[1][0]):
        return None
    return gaps[0][1]


def added_pass_position(location: Location, stops: list[StopRow]) -> tuple[int, datetime] | None:
    """
    Where a passing point that isn't in the schedule fits: the sequence to insert it at and its working
    pass time as a full timestamp. None if it falls outside the journey, or no stop has a working time.
    """
    at = parse_time(location.working_pass)
    timed = [stop for stop in stops if stop.any_working() is not None]
    if at is None or not timed:
        return None

    # Pick the day that puts the pass closest to some stop on the journey (handles trains past midnight)
    resolved = min(
        (nearest_datetime(at, stop.any_working()) for stop in timed),
        key=lambda candidate: min(abs(candidate - stop.any_working()) for stop in timed),
    )
    if not timed[0].any_working() < resolved < timed[-1].any_working():
        return None

    following = next(stop for stop in timed if stop.any_working() > resolved)
    return following.sequence, resolved


@dataclass
class StatusResult:
    unmatched: int = 0  # locations that couldn't be matched to a stop
    added: int = 0  # passing points stored as new stops because they weren't in the schedule


class Database:

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or load_config().database_url
        self.conn, self.cur = self.connect(self.database_url)

    def connect(self, database_url):
        conn = psycopg.connect(database_url)
        cur = conn.cursor()
        return conn, cur

    # Reference data

    def add_code_maps(self, table, key_col, value_col, code_map):
        query = sql.SQL("""
            INSERT INTO {table} ({key_col}, {value_col})
            VALUES (%s, %s)
            ON CONFLICT ({key_col})
                DO UPDATE SET {value_col} = EXCLUDED.{value_col}
            WHERE {table}.{value_col} IS DISTINCT FROM EXCLUDED.{value_col};
        """).format(
            table=sql.Identifier(table),
            key_col=sql.Identifier(key_col),
            value_col=sql.Identifier(value_col),
        )
        self.cur.executemany(query, [(key, value) for key, value in code_map.items()])
        self.conn.commit()

    def add_location_refs(self, locations):
        self.cur.executemany("""
            INSERT INTO locations (tiploc, location_name, reservation_code, train_operator_code)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(tiploc)
            DO UPDATE SET
                location_name = EXCLUDED.location_name,
                reservation_code = EXCLUDED.reservation_code,
                train_operator_code = EXCLUDED.train_operator_code
            WHERE locations.location_name IS DISTINCT FROM EXCLUDED.location_name
                OR locations.reservation_code IS DISTINCT FROM EXCLUDED.reservation_code
                OR locations.train_operator_code IS DISTINCT FROM EXCLUDED.train_operator_code
            """, [(
                tpl,
                location.get('locname') or tpl,
                location.get('crs'),
                location.get('toc')
            ) for tpl, location in locations])
        self.conn.commit()

    def ensure_tiplocs(self, tiplocs: Iterable[str]):
        """Add placeholder locations for TIPLOCs that aren't in the reference data yet, so FKs hold."""
        self.cur.executemany(
            "INSERT INTO locations (tiploc, location_name) VALUES (%s, %s) ON CONFLICT (tiploc) DO NOTHING",
            [(tiploc, tiploc) for tiploc in set(tiplocs) if tiploc],
        )

    # Timetable (bulk, from initialise.py)

    def add_schedules(self, schedules: list[Schedule]):
        """
        Load the day's timetable. Planned data is overwritten; live data (actuals, forecasts, positions)
        is left alone so re-running the import mid-day is safe.
        """
        self.ensure_tiplocs(stop.tiploc for schedule in schedules for stop in schedule.stops)
        self._upsert_journeys(schedules)
        self.cur.executemany(f"""
            INSERT INTO train_stops ({", ".join(STOP_COLUMNS)})
            VALUES ({", ".join(["%s"] * len(STOP_COLUMNS))})
            ON CONFLICT (rid, sequence) DO UPDATE SET
                {", ".join(f"{column} = EXCLUDED.{column}" for column in STOP_COLUMNS[2:])},
                added_from_status = FALSE
        """, [row for schedule in schedules for row in schedule_stop_rows(schedule)])
        self.conn.commit()

    def _upsert_journeys(self, schedules: list[Schedule]):
        self.cur.executemany("""
            INSERT INTO train_journeys (rid, train_id, uid, scheduled_start, toc_code, status, category, is_passenger, cancelled, deleted, cancel_reason, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (rid) DO UPDATE SET
                train_id = EXCLUDED.train_id,
                uid = EXCLUDED.uid,
                scheduled_start = EXCLUDED.scheduled_start,
                toc_code = EXCLUDED.toc_code,
                status = EXCLUDED.status,
                category = EXCLUDED.category,
                is_passenger = EXCLUDED.is_passenger,
                cancelled = EXCLUDED.cancelled,
                deleted = EXCLUDED.deleted,
                cancel_reason = EXCLUDED.cancel_reason
            """, [(
                s.rid, s.train_id or "", s.uid or "", s.scheduled_start, s.toc or "", s.status, s.category,
                s.is_passenger, s.cancelled, s.deleted, s.cancel_reason,
            ) for s in schedules])

    # Live updates (from consumer.py)

    def handle_message(self, message: PushPortMessage) -> dict[str, int]:
        """Log a Push Port message and apply everything in it, in one transaction."""
        counts = {
            "statuses": 0, "unmatched_locations": 0, "added_locations": 0, "unknown_trains": 0, "schedules": 0,
            "deactivated": 0,
        }
        try:
            self.record_event(message)
            for schedule in message.schedules:
                self.apply_schedule(schedule)
                counts["schedules"] += 1
            for status in message.statuses:
                result = self.apply_status(status)
                if result is None:
                    counts["unknown_trains"] += 1
                else:
                    counts["statuses"] += 1
                    counts["unmatched_locations"] += result.unmatched
                    counts["added_locations"] += result.added
            for deactivated in message.deactivated:
                self.cur.execute(
                    "UPDATE train_journeys SET deactivated = TRUE, updated_at = now() WHERE rid = %s",
                    (deactivated.rid,),
                )
                counts["deactivated"] += 1
            self.conn.commit()
        except psycopg.Error:
            logger.exception("Rolling back message %s", message.sequence)
            self.conn.rollback()
        return counts

    def record_event(self, message: PushPortMessage):
        self.cur.execute("""
            INSERT INTO darwin_events (message_ts, push_port_sequence, kinds, rids, payload)
            VALUES (%s, %s, %s, %s, %s)
        """, (message.timestamp, message.sequence, message.kinds(), message.rids(), Jsonb(message.raw)))

    def fetch_stop_rows(self, rid: str) -> list[StopRow]:
        self.cur.execute("""
            SELECT sequence, tiploc, working_arrival, working_departure, working_pass
            FROM train_stops WHERE rid = %s ORDER BY sequence
        """, (rid,))
        return [StopRow(*row) for row in self.cur.fetchall()]

    def apply_schedule(self, schedule: Schedule):
        """A new or changed schedule replaces the train's stops, keeping live data for calls that still exist."""
        self.cur.execute("""
            SELECT tiploc, working_arrival, working_departure, working_pass,
                actual_arrival, actual_departure, actual_pass,
                estimated_arrival, estimated_departure, estimated_pass, platform_confirmed, platform_suppressed
            FROM train_stops WHERE rid = %s
        """, (schedule.rid,))
        live = {
            (row[0], normalise_time(row[1]), normalise_time(row[2]), normalise_time(row[3])): row[4:]
            for row in self.cur.fetchall()
        }

        self.ensure_tiplocs(stop.tiploc for stop in schedule.stops)
        self._upsert_journeys([schedule])
        self.cur.execute("DELETE FROM train_stops WHERE rid = %s", (schedule.rid,))

        rows = schedule_stop_rows(schedule)
        self.cur.executemany(f"""
            INSERT INTO train_stops ({", ".join(STOP_COLUMNS)}, actual_arrival, actual_departure, actual_pass,
                estimated_arrival, estimated_departure, estimated_pass, platform_confirmed, platform_suppressed)
            VALUES ({", ".join(["%s"] * (len(STOP_COLUMNS) + 8))})
        """, [
            row + tuple(live.get((row[2], normalise_time(row[10]), normalise_time(row[11]), normalise_time(row[12])), (None,) * 8))
            for row in rows
        ])
        self.refresh_position(schedule.rid)

    def add_passing_point(self, rid: str, location: Location, stops: list[StopRow]) -> bool:
        """Store a passing point Darwin reports but the schedule doesn't have, in working-time order."""
        position = added_pass_position(location, stops)
        if position is None:
            return False
        sequence, working_pass = position

        self.ensure_tiplocs([location.tiploc])
        # Shift later stops along one place, in two steps so the (rid, sequence) key never collides
        self.cur.execute("UPDATE train_stops SET sequence = -sequence - 1 WHERE rid = %s AND sequence >= %s", (rid, sequence))
        self.cur.execute("UPDATE train_stops SET sequence = -sequence WHERE rid = %s AND sequence < 0", (rid,))
        self.cur.execute("""
            INSERT INTO train_stops (rid, sequence, tiploc, location_type, working_pass, added_from_status)
            VALUES (%s, %s, %s, 'PP', %s, TRUE)
        """, (rid, sequence, location.tiploc, working_pass))
        logger.debug("Added passing point %s at %s for %s", location.tiploc, location.working_pass, rid)
        return True

    def apply_status(self, status: TrainStatus) -> StatusResult | None:
        """
        Apply a TS (train status) update, or return None if the train isn't known at all (not in the
        timetable and no schedule message seen yet).
        """
        stops = self.fetch_stop_rows(status.rid)
        if not stops:
            logger.debug("Status for unknown train %s", status.rid)
            return None

        result = StatusResult()
        # Passing points missing from the schedule become stops first, so sequences are settled before matching
        for location in status.locations:
            if (location.is_pass() and not any(stop.tiploc == location.tiploc for stop in stops)
                    and self.add_passing_point(status.rid, location, stops)):
                result.added += 1
                stops = self.fetch_stop_rows(status.rid)

        rows = []
        for location in status.locations:
            stop = match_location(location, stops)
            if stop is None:
                result.unmatched += 1
                logger.debug("No stop for %s at %s %s", status.rid, location.tiploc, location.planned_key())
                continue

            fallback = stop.any_working()
            arrival_anchor = stop.working_arrival or fallback
            departure_anchor = stop.working_departure or fallback
            pass_anchor = stop.working_pass or fallback

            rows.append((
                nearest_datetime(parse_time(location.actual_arrival), arrival_anchor),
                nearest_datetime(parse_time(location.actual_departure), departure_anchor),
                nearest_datetime(parse_time(location.actual_pass), pass_anchor),
                nearest_datetime(parse_time(location.estimated_arrival), arrival_anchor),
                nearest_datetime(parse_time(location.estimated_departure), departure_anchor),
                nearest_datetime(parse_time(location.estimated_pass), pass_anchor),
                location.platform,
                location.platform_confirmed,
                location.platform_suppressed,
                status.rid,
                stop.sequence,
            ))

        if rows:
            self.cur.executemany("""
                UPDATE train_stops SET
                    actual_arrival      = COALESCE(%s, actual_arrival),
                    actual_departure    = COALESCE(%s, actual_departure),
                    actual_pass         = COALESCE(%s, actual_pass),
                    estimated_arrival   = COALESCE(%s, estimated_arrival),
                    estimated_departure = COALESCE(%s, estimated_departure),
                    estimated_pass      = COALESCE(%s, estimated_pass),
                    platform            = COALESCE(%s, platform),
                    platform_confirmed  = COALESCE(%s, platform_confirmed),
                    platform_suppressed = COALESCE(%s, platform_suppressed)
                WHERE rid = %s AND sequence = %s
            """, rows)

        if status.late_reason is not None:
            self.cur.execute("UPDATE train_journeys SET late_reason = %s WHERE rid = %s", (status.late_reason, status.rid))

        self.refresh_position(status.rid)
        return result

    def refresh_position(self, rid: str):
        """Set the train's last reported location, report type and delay from its latest actual time."""
        self.cur.execute("""
            WITH latest AS (
                SELECT tiploc,
                    CASE
                        WHEN actual_departure IS NOT NULL THEN 'departure'
                        WHEN actual_pass IS NOT NULL THEN 'pass'
                        ELSE 'arrival'
                    END AS report_type,
                    COALESCE(actual_departure, actual_pass, actual_arrival) AS reported_at,
                    CASE
                        WHEN actual_departure IS NOT NULL THEN actual_departure - working_departure
                        WHEN actual_pass IS NOT NULL THEN actual_pass - working_pass
                        ELSE actual_arrival - working_arrival
                    END AS delay
                FROM train_stops
                WHERE rid = %(rid)s
                    AND (actual_arrival IS NOT NULL OR actual_departure IS NOT NULL OR actual_pass IS NOT NULL)
                ORDER BY sequence DESC
                LIMIT 1
            )
            UPDATE train_journeys j SET
                last_tiploc = latest.tiploc,
                last_report_type = latest.report_type,
                last_reported_at = latest.reported_at,
                delay_minutes = ROUND(EXTRACT(EPOCH FROM latest.delay) / 60),
                updated_at = now()
            FROM latest
            WHERE j.rid = %(rid)s
                AND (j.last_tiploc, j.last_report_type, j.last_reported_at)
                    IS DISTINCT FROM (latest.tiploc, latest.report_type, latest.reported_at)
        """, {"rid": rid})

    # Reading (search.py)

    def fetch_train_stops(self, rid) -> list[Location]:
        self.cur.execute("""
            SELECT s.sequence, COALESCE(l.location_name, s.tiploc),
                s.working_arrival, s.working_departure, s.working_pass,
                s.actual_arrival, s.actual_departure, s.actual_pass,
                s.estimated_arrival, s.estimated_departure, s.estimated_pass, s.platform
            FROM train_stops s LEFT JOIN locations l ON l.tiploc = s.tiploc
            WHERE s.rid = %s ORDER BY s.sequence
        """, (rid,))
        return [
            Location(
                sequence=row[0], tiploc=row[1],
                working_arrival=row[2], working_departure=row[3], working_pass=row[4],
                actual_arrival=row[5], actual_departure=row[6], actual_pass=row[7],
                estimated_arrival=row[8], estimated_departure=row[9], estimated_pass=row[10],
                platform=row[11],
            )
            for row in self.cur.fetchall()
        ]

    def fetch_train_journeys(self, count: int = 50) -> list[JourneySummary]:
        """The most recently updated trains."""
        self.cur.execute("""
            SELECT j.rid, j.uid, j.scheduled_start, j.toc_code,
                COALESCE(lo.location_name, o.tiploc), COALESCE(ld.location_name, d.tiploc),
                COALESCE(o.working_departure, o.public_departure), COALESCE(d.working_arrival, d.public_arrival),
                COALESCE(ll.location_name, j.last_tiploc), j.last_report_type, j.last_reported_at,
                j.delay_minutes, j.cancelled
            FROM train_journeys j
            LEFT JOIN LATERAL (
                SELECT tiploc, working_departure, public_departure FROM train_stops
                WHERE rid = j.rid ORDER BY sequence LIMIT 1
            ) o ON TRUE
            LEFT JOIN LATERAL (
                SELECT tiploc, working_arrival, public_arrival FROM train_stops
                WHERE rid = j.rid ORDER BY sequence DESC LIMIT 1
            ) d ON TRUE
            LEFT JOIN locations lo ON lo.tiploc = o.tiploc
            LEFT JOIN locations ld ON ld.tiploc = d.tiploc
            LEFT JOIN locations ll ON ll.tiploc = j.last_tiploc
            ORDER BY j.updated_at DESC NULLS LAST
            LIMIT %s
        """, (count,))
        return [JourneySummary(*row) for row in self.cur.fetchall()]

    def close(self):
        self.cur.close()
        self.conn.close()

    def commit(self):
        self.conn.commit()


def main():
    db = Database()
    for train in db.fetch_train_journeys(5):
        print(train)


if __name__ == "__main__":
    main()
