import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from time import sleep

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from config import load_config
from darwin import Location, PushPortMessage, Schedule, TrainStatus, normalise_time
from util import LONDON, nearest_datetime, parse_date, parse_time, resolve_sequence

logger = logging.getLogger(__name__)

# A TIPLOC further than this from Network Rail track isn't on it (see snap_tiploc_locations)
SNAP_DISTANCE_METRES = 500

# Stops where a train calls (the rest are passing points)
CALL_TYPES = "('OR', 'IP', 'DT', 'OPOR', 'OPIP', 'OPDT')"

# A tiploc_locations row `t` that can place a stop on the map. off_network points (stations away from
# Network Rail track) are placed but joined with straight lines; suspect points aren't used
USABLE_LOCATION = "COALESCE(t.quality IN ('good', 'off_network'), FALSE)"

# How far Darwin's working time for a location may be from the planned one when a train calls or passes
# somewhere more than once and the times don't match exactly
MATCH_TOLERANCE = timedelta(minutes=5)
# A TIPLOC the train visits once still matches a report this far from the planned time. Further out the
# report is of a visit the schedule doesn't have (on 21 Nov all 19 gaps over an hour were wrong-leg matches)
SINGLE_VISIT_TOLERANCE = timedelta(minutes=15)
# Keyframes are written every 5 minutes; looking back further than this for one means there's a gap in the frames
KEYFRAME_REACH = timedelta(minutes=10)

# The timetable reload and the consumer write the same journeys' rows, so they can deadlock; Postgres then
# aborts one of the two transactions. The aborted one is tried up to this many times in all, waiting a little
# longer before each retry (0.1 s, 0.2 s, ...). On 24 Nov two consumer messages were lost to this during one reload
TRANSACTION_ATTEMPTS = 5
RETRY_WAIT_SECONDS = 0.1

# Errors that mean Postgres aborted a transaction that would succeed if run again (40P01, 40001)
RETRYABLE_ERRORS = (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)

# What handle_message counts for the consumer's stats line, plus "failed" for a message it couldn't apply and
# "lost" for one it couldn't write to darwin_events either
MESSAGE_COUNTS = ("statuses", "unmatched_locations", "added_locations", "unknown_trains", "schedules", "deactivated")

# Live data a stop keeps when its journey's stops are replaced by a newer schedule
LIVE_COLUMNS = (
    "actual_arrival", "actual_departure", "actual_pass", "estimated_arrival", "estimated_departure", "estimated_pass",
    "platform_confirmed", "platform_suppressed",
)

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
        if parse_time(location.working_time()) is None:
            return at_tiploc[0]
        return nearest_stop(location, at_tiploc, SINGLE_VISIT_TOLERANCE)

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


def visit_gaps(location: Location, stops: list[StopRow]) -> list[tuple[timedelta, StopRow]]:
    """How far each stop's working time is from the location's, nearest first (empty if Darwin sent none)."""
    at = parse_time(location.working_time())
    if at is None:
        return []
    gaps = []
    for stop in stops:
        planned = (stop.working_pass if location.is_pass() else None) or stop.any_working()
        if planned is not None:
            gaps.append((time_of_day_gap(at, planned), stop))
    return sorted(gaps, key=lambda gap: gap[0])


def nearest_stop(location: Location, stops: list[StopRow], tolerance: timedelta = MATCH_TOLERANCE) -> StopRow | None:
    """The stop whose working time is nearest the location's, if within tolerance and not tied."""
    gaps = [gap for gap in visit_gaps(location, stops) if gap[0] <= tolerance]

    if not gaps or (len(gaps) > 1 and gaps[0][0] == gaps[1][0]):
        return None
    return gaps[0][1]


def is_unscheduled_visit(location: Location, stops: list[StopRow]) -> bool:
    """True if no stop at the location's TIPLOC is within SINGLE_VISIT_TOLERANCE of its working time."""
    at_tiploc = [stop for stop in stops if stop.tiploc == location.tiploc]
    if not at_tiploc:
        return True
    gaps = visit_gaps(location, at_tiploc)
    return bool(gaps) and gaps[0][0] > SINGLE_VISIT_TOLERANCE and match_location(location, at_tiploc) is None


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

    def in_transaction[T](self, work: Callable[[], T], what: str) -> T:
        """
        Run `work` and commit. If Postgres aborts the transaction to break a deadlock (or a serialization
        conflict), roll back and run it again from the start, up to TRANSACTION_ATTEMPTS times in all.
        """
        for attempt in range(1, TRANSACTION_ATTEMPTS + 1):
            try:
                result = work()
                self.conn.commit()
                return result
            except RETRYABLE_ERRORS as error:
                self.conn.rollback()
                if attempt == TRANSACTION_ATTEMPTS:
                    raise
                logger.warning("%s was aborted (%s), trying again (%d of %d)",
                               what, error.sqlstate, attempt + 1, TRANSACTION_ATTEMPTS)
                sleep(RETRY_WAIT_SECONDS * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

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

    def add_tiploc_locations(self, locations: list):
        """
        Replace TIPLOC coordinates (from tiploc_locations.py), leaving rows whose values haven't changed alone.
        Segment paths to or from a TIPLOC that moved or went are dropped, for segment_paths.py to route again.
        """
        self.cur.execute("CREATE TEMP TABLE old_points ON COMMIT DROP AS SELECT tiploc, geom FROM tiploc_locations")
        self.cur.executemany("""
            INSERT INTO tiploc_locations (tiploc, name, geom, easting, northing, source, quality)
            VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s)
            ON CONFLICT (tiploc) DO UPDATE SET
                name = EXCLUDED.name, geom = EXCLUDED.geom, easting = EXCLUDED.easting,
                northing = EXCLUDED.northing, source = EXCLUDED.source, quality = EXCLUDED.quality, updated_at = now()
            WHERE (tiploc_locations.name, tiploc_locations.geom, tiploc_locations.easting, tiploc_locations.northing,
                    tiploc_locations.source, tiploc_locations.quality)
                IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.geom, EXCLUDED.easting, EXCLUDED.northing,
                    EXCLUDED.source, EXCLUDED.quality)
        """, [(
            location.tiploc, location.name, location.lon, location.lat, location.easting, location.northing,
            location.source, location.quality,
        ) for location in locations])
        # A TIPLOC no source has any more (e.g. a removed override with no other point) loses its row
        tiplocs = [location.tiploc for location in locations]
        self.cur.execute("DELETE FROM tiploc_locations WHERE NOT (tiploc = ANY(%s))", (tiplocs,))
        self.cur.execute("""
            WITH moved AS (
                SELECT o.tiploc FROM old_points o LEFT JOIN tiploc_locations t USING (tiploc)
                WHERE t.geom IS NULL OR NOT ST_Equals(t.geom, o.geom)
            )
            DELETE FROM segment_paths
            WHERE from_tiploc IN (SELECT tiploc FROM moved) OR to_tiploc IN (SELECT tiploc FROM moved)
        """)
        self.conn.commit()

    # Timetable (bulk, from initialise.py)

    def add_schedules(self, schedules: list[Schedule]):
        """
        Load the day's timetable. A journey that already has stops gets them replaced, carrying live data
        (actuals, forecasts, platform confirmation) over to calls with the same TIPLOC and working times, as
        for a schedule message. So re-running the import mid-day is safe even after schedule messages or
        Darwin-added passing points have renumbered a journey's stops. A batch that deadlocks with the consumer
        is run again rather than failing the day's load.
        """
        self.in_transaction(lambda: self._add_schedules(schedules), f"Timetable batch of {len(schedules)} journeys")

    def _add_schedules(self, schedules: list[Schedule]):
        self.ensure_tiplocs(stop.tiploc for schedule in schedules for stop in schedule.stops)
        self._upsert_journeys(schedules)
        self.cur.execute("CREATE TEMP TABLE new_stops (LIKE train_stops INCLUDING DEFAULTS) ON COMMIT DROP")
        with self.cur.copy(f"COPY new_stops ({", ".join(STOP_COLUMNS)}) FROM STDIN") as copy:
            for schedule in schedules:
                for row in schedule_stop_rows(schedule):
                    copy.write_row(row)
        self.cur.execute(f"""
            UPDATE new_stops n SET {", ".join(f"{column} = o.{column}" for column in LIVE_COLUMNS)}
            FROM (
                SELECT DISTINCT ON (rid, tiploc, working_arrival, working_departure, working_pass) *
                FROM train_stops WHERE rid IN (SELECT DISTINCT rid FROM new_stops)
                ORDER BY rid, tiploc, working_arrival, working_departure, working_pass, sequence
            ) o
            WHERE o.rid = n.rid AND o.tiploc = n.tiploc
                AND o.working_arrival IS NOT DISTINCT FROM n.working_arrival
                AND o.working_departure IS NOT DISTINCT FROM n.working_departure
                AND o.working_pass IS NOT DISTINCT FROM n.working_pass
        """)
        self.cur.execute("DELETE FROM train_stops WHERE rid IN (SELECT DISTINCT rid FROM new_stops)")
        self.cur.execute("INSERT INTO train_stops SELECT * FROM new_stops")

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
        """
        Log a Push Port message and apply everything in it, in one transaction, tried again if it deadlocks.
        If it still can't be applied, for any reason, the raw message is written to darwin_events on its own so
        it isn't lost. Nothing in the table marks it unapplied; the consumer's log has the error.
        """
        def apply() -> dict[str, int]:
            counts = dict.fromkeys(MESSAGE_COUNTS, 0)
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
            return counts

        try:
            return self.in_transaction(apply, f"Message {message.sequence}")
        except Exception:
            # Not just database errors: a message the code can't handle mustn't stop the consumer, which would
            # then get the same message from Kafka again on restart
            logger.exception("Couldn't apply message %s, logging it unapplied", message.sequence)
            self.conn.rollback()
        counts = dict.fromkeys(MESSAGE_COUNTS, 0) | {"failed": 1}
        try:
            self.in_transaction(lambda: self.record_event(message), f"Logging message {message.sequence}")
        except psycopg.Error:
            logger.exception("Couldn't log message %s either, so it's lost", message.sequence)
            self.conn.rollback()
            counts["lost"] = 1
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
        # Lock the journey before its stops, the order the timetable load and schedule messages take them in,
        # so the two don't deadlock over one train
        self.cur.execute("SELECT 1 FROM train_journeys WHERE rid = %s FOR UPDATE", (status.rid,))
        stops = self.fetch_stop_rows(status.rid)
        if not stops:
            logger.debug("Status for unknown train %s", status.rid)
            return None

        result = StatusResult()
        # Passing points missing from the schedule become stops first, so sequences are settled before matching.
        # That includes a pass at a TIPLOC the schedule visits only at some quite different time (the other leg of
        # a loop); one between two nearby visits stays unmatched rather than becoming a third
        for location in status.locations:
            if (location.is_pass() and is_unscheduled_visit(location, stops)
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

        if rows or status.late_reason is not None:
            # Forecasts and platforms change positions and the train panel too, not only new actual times
            self.cur.execute(
                "UPDATE train_journeys SET late_reason = COALESCE(%s, late_reason), updated_at = now() WHERE rid = %s",
                (status.late_reason, status.rid),
            )

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

    # Track geometry (track_model.py, segment_paths.py)

    def replace_track_links(self, links: list):
        self.cur.execute("TRUNCATE track_links")
        with self.cur.copy("""
            COPY track_links (asset_id, elr, track_id, start_miles, end_miles, from_node, to_node, length_m, geom)
            FROM STDIN
        """) as copy:
            for link in links:
                copy.write_row((
                    link.asset_id, link.elr, link.track_id, link.start_miles, link.end_miles,
                    link.from_node, link.to_node, link.length(), link.ewkt(),
                ))
        self.conn.commit()

    def snap_tiploc_locations(self) -> bool:
        """
        Snap every TIPLOC to its nearest track link and set its quality from the distance.
        Does nothing (returns False) until track_links has been loaded.
        """
        if not self.has_track_links():
            return False
        self.cur.execute("""
            WITH points AS (
                SELECT tiploc, source, COALESCE(
                    ST_SetSRID(ST_MakePoint(easting, northing), 27700), ST_Transform(geom, 27700)
                ) AS point
                FROM tiploc_locations
            ), nearest AS (
                SELECT p.tiploc, p.source, p.point, link.asset_id, link.geom AS line
                FROM points p
                CROSS JOIN LATERAL (
                    SELECT asset_id, geom FROM track_links ORDER BY geom <-> p.point LIMIT 1
                ) link
            )
            UPDATE tiploc_locations t SET
                snap_link = n.asset_id,
                snap_along = ST_LineLocatePoint(n.line, n.point) * ST_Length(n.line),
                snap_distance_m = ST_Distance(n.line, n.point),
                snap_geom = ST_ClosestPoint(n.line, n.point),
                quality = CASE
                    WHEN n.source = 'override' OR ST_Distance(n.line, n.point) <= %(max_distance)s THEN 'good'
                    WHEN n.source = 'naptan' THEN 'off_network'
                    ELSE 'suspect'
                END
            FROM nearest n
            WHERE t.tiploc = n.tiploc
        """, {"max_distance": SNAP_DISTANCE_METRES})
        self.conn.commit()
        return True

    def count_tiploc_locations(self) -> dict[tuple[str, str], int]:
        """Rows in tiploc_locations by (source, quality)."""
        self.cur.execute("SELECT source, quality, count(*) FROM tiploc_locations GROUP BY 1, 2")
        return {(source, quality): count for source, quality, count in self.cur.fetchall()}

    def flag_implausible_locations(self, day, max_speed: float, min_distance: float) -> list[str]:
        """
        Mark BPLAN points suspect where the day's trains would have to cover more than `min_distance`
        metres at over `max_speed` m/s both to reach them and to leave them: a point in the wrong place
        that happens to be near some other track. Repeats until nothing changes, so that a wrong point
        next to another wrong one is found once the first is out. Drops their segment paths.
        """
        flagged: list[str] = []
        while True:
            self.cur.execute(f"""
                WITH placed AS (
                    SELECT s.rid, s.sequence, s.tiploc, t.source,
                        COALESCE(ST_SetSRID(ST_MakePoint(t.easting, t.northing), 27700), ST_Transform(t.geom, 27700)) AS point,
                        COALESCE(s.working_departure, s.working_arrival, s.working_pass) AS at
                    FROM train_stops s
                    JOIN train_journeys j ON j.rid = s.rid
                    JOIN tiploc_locations t ON t.tiploc = s.tiploc
                    WHERE j.scheduled_start = %(day)s AND {USABLE_LOCATION}
                ), legs AS (
                    SELECT tiploc, source,
                        ST_Distance(point, LAG(point) OVER w) AS from_distance,
                        EXTRACT(EPOCH FROM at - LAG(at) OVER w) AS from_seconds,
                        ST_Distance(point, LEAD(point) OVER w) AS to_distance,
                        EXTRACT(EPOCH FROM LEAD(at) OVER w - at) AS to_seconds
                    FROM placed
                    WINDOW w AS (PARTITION BY rid ORDER BY sequence)
                )
                SELECT tiploc FROM legs
                WHERE source = 'bplan' AND from_distance IS NOT NULL AND to_distance IS NOT NULL
                GROUP BY tiploc
                HAVING avg((
                    from_distance > %(min_distance)s AND from_distance / GREATEST(from_seconds, 30) > %(max_speed)s
                    AND to_distance > %(min_distance)s AND to_distance / GREATEST(to_seconds, 30) > %(max_speed)s
                )::INTEGER) > 0.5
            """, {"day": day, "max_speed": max_speed, "min_distance": min_distance})
            found = [row[0] for row in self.cur.fetchall()]
            if not found:
                break
            self.cur.execute("UPDATE tiploc_locations SET quality = 'suspect' WHERE tiploc = ANY(%s)", (found,))
            flagged += found
        if flagged:
            self.cur.execute(
                "DELETE FROM segment_paths WHERE from_tiploc = ANY(%(t)s) OR to_tiploc = ANY(%(t)s)", {"t": flagged},
            )
        self.conn.commit()
        return flagged

    def has_track_links(self) -> bool:
        self.cur.execute("SELECT EXISTS (SELECT FROM track_links)")
        return self.cur.fetchone()[0]

    def fetch_track_links(self) -> list[tuple]:
        self.cur.execute("SELECT asset_id, from_node, to_node, ST_AsBinary(geom) FROM track_links")
        return self.cur.fetchall()

    def fetch_new_segment_pairs(self, day) -> list[tuple[str, str]]:
        """Consecutive placed stops of trains scheduled on `day` that have no segment path yet."""
        self.cur.execute(f"""
            WITH placed AS (
                SELECT s.rid, s.sequence, s.tiploc
                FROM train_stops s
                JOIN train_journeys j ON j.rid = s.rid
                JOIN tiploc_locations t ON t.tiploc = s.tiploc
                WHERE j.scheduled_start = %s AND {USABLE_LOCATION}
            ), pairs AS (
                SELECT tiploc AS from_tiploc, LEAD(tiploc) OVER (PARTITION BY rid ORDER BY sequence) AS to_tiploc
                FROM placed
            )
            SELECT DISTINCT p.from_tiploc, p.to_tiploc FROM pairs p
            WHERE p.to_tiploc IS NOT NULL AND p.to_tiploc <> p.from_tiploc
                AND NOT EXISTS (
                    SELECT FROM segment_paths sp WHERE sp.from_tiploc = p.from_tiploc AND sp.to_tiploc = p.to_tiploc
                )
            ORDER BY 1, 2
        """, (day,))
        return self.cur.fetchall()

    def fetch_placed_tiplocs(self, tiplocs, parallel_metres: float) -> list[tuple]:
        """
        (tiploc, easting, northing, snaps) where snaps is a list of (asset_id, along): the nearest track
        link first, then any others within `parallel_metres` of it (parallel lines). Empty for points
        that aren't on Network Rail track.
        """
        self.cur.execute("""
            WITH t AS (
                SELECT tiploc, quality, snap_link, snap_geom,
                    COALESCE(ST_SetSRID(ST_MakePoint(easting, northing), 27700), ST_Transform(geom, 27700)) AS point
                FROM tiploc_locations WHERE tiploc = ANY(%s)
            )
            SELECT t.tiploc, ST_X(t.point), ST_Y(t.point), COALESCE(
                array_agg(ARRAY[l.asset_id, (ST_LineLocatePoint(l.geom, t.point) * ST_Length(l.geom))::TEXT]
                    ORDER BY l.asset_id <> t.snap_link, ST_Distance(l.geom, t.snap_geom))
                    FILTER (WHERE l.asset_id IS NOT NULL),
                '{}')
            FROM t
            LEFT JOIN track_links l ON t.quality = 'good' AND t.snap_link IS NOT NULL
                AND ST_DWithin(l.geom, t.snap_geom, %s)
            GROUP BY t.tiploc, t.point
        """, (list(tiplocs), parallel_metres))
        return [
            (tiploc, x, y, [(asset_id, float(along)) for asset_id, along in snaps])
            for tiploc, x, y, snaps in self.cur.fetchall()
        ]

    def add_segment_paths(self, paths: list, simplify_metres: float):
        self.cur.executemany("""
            INSERT INTO segment_paths (from_tiploc, to_tiploc, method, fallback_reason, length_m, straight_m, geom)
            VALUES (%s, %s, %s, %s, %s, %s, ST_Transform(ST_GeomFromText(%s, 27700), 4326))
            ON CONFLICT (from_tiploc, to_tiploc) DO UPDATE SET
                method = EXCLUDED.method, fallback_reason = EXCLUDED.fallback_reason, length_m = EXCLUDED.length_m,
                straight_m = EXCLUDED.straight_m, geom = EXCLUDED.geom, computed_at = now()
        """, [(
            path.from_tiploc, path.to_tiploc, path.method, path.fallback_reason, path.length, path.straight,
            path.line.simplify(simplify_metres).wkt,
        ) for path in paths])
        self.conn.commit()

    # Positions (positions.py)

    def fetch_segment_paths(self) -> list[tuple]:
        self.cur.execute("SELECT from_tiploc, to_tiploc, method, ST_AsBinary(geom) FROM segment_paths")
        return self.cur.fetchall()

    def fetch_journeys_around(self, at, rids: list[str] | None = None) -> list[tuple]:
        """
        Journeys whose planned times run from up to 15 minutes after `at` to up to 3 hours before it, optionally
        only among `rids`.
        """
        self.cur.execute("""
            SELECT j.rid, j.train_id, j.toc_code, j.cancelled, j.deactivated
            FROM train_journeys j
            JOIN LATERAL (
                SELECT min(COALESCE(working_departure, working_pass, working_arrival)) AS first_time,
                    max(COALESCE(working_arrival, working_pass, working_departure)) AS last_time
                FROM train_stops WHERE rid = j.rid
            ) span ON TRUE
            WHERE j.scheduled_start BETWEEN (%(at)s::timestamptz AT TIME ZONE 'Europe/London')::date - 1
                    AND (%(at)s::timestamptz AT TIME ZONE 'Europe/London')::date
                AND span.first_time <= %(at)s::timestamptz + INTERVAL '15 minutes'
                AND span.last_time >= %(at)s::timestamptz - INTERVAL '3 hours'
                AND (%(rids)s::text[] IS NULL OR j.rid = ANY(%(rids)s::text[]))
        """, {"at": at, "rids": rids})
        return self.cur.fetchall()

    def fetch_changed_journeys(self, since) -> tuple[datetime, list[str]]:
        """The database's time now, and the trains changed after `since` (all of them when `since` is None)."""
        self.cur.execute("SELECT clock_timestamp()")
        now = self.cur.fetchone()[0]
        if since is None:
            return now, []
        self.cur.execute("SELECT rid FROM train_journeys WHERE updated_at > %s", (since,))
        return now, [row[0] for row in self.cur.fetchall()]

    def fetch_position_stops(self, rids: list[str]) -> list[tuple]:
        """Stops in order with their usable point (British National Grid) and every time positions need."""
        self.cur.execute(f"""
            SELECT s.rid, s.tiploc, s.location_type,
                CASE WHEN {USABLE_LOCATION} THEN ST_X(p.point) END, CASE WHEN {USABLE_LOCATION} THEN ST_Y(p.point) END,
                s.working_arrival, s.working_departure, s.working_pass,
                s.estimated_arrival, s.estimated_departure, s.estimated_pass,
                s.actual_arrival, s.actual_departure, s.actual_pass, s.cancelled
            FROM train_stops s
            LEFT JOIN tiploc_locations t ON t.tiploc = s.tiploc
            LEFT JOIN LATERAL (
                SELECT COALESCE(ST_SetSRID(ST_MakePoint(t.easting, t.northing), 27700), ST_Transform(t.geom, 27700)) AS point
            ) p ON TRUE
            WHERE s.rid = ANY(%s)
            ORDER BY s.rid, s.sequence
        """, (rids,))
        return self.cur.fetchall()

    # The live map (api.py)

    def fetch_train(self, rid: str) -> tuple | None:
        """(rid, headcode, toc, operator, cancelled, deactivated, cancel reason, late reason, delay) for one train."""
        self.cur.execute("""
            SELECT j.rid, j.train_id, j.toc_code, toc.name, COALESCE(j.cancelled, FALSE), j.deactivated,
                cr.reason, lr.reason, j.delay_minutes
            FROM train_journeys j
            LEFT JOIN train_operator_codes toc ON toc.toc = j.toc_code
            LEFT JOIN cancellation_reasons cr ON cr.code = j.cancel_reason
            LEFT JOIN late_reasons lr ON lr.code = j.late_reason
            WHERE j.rid = %s
        """, (rid,))
        return self.cur.fetchone()

    def fetch_panel_stops(self, rid: str) -> list[tuple]:
        """A train's stops in order, with names and every time and platform field the train panel shows."""
        self.cur.execute("""
            SELECT s.tiploc, l.location_name, l.reservation_code, s.location_type,
                s.public_arrival, s.public_departure, s.working_arrival, s.working_departure, s.working_pass,
                s.estimated_arrival, s.estimated_departure, s.estimated_pass,
                s.actual_arrival, s.actual_departure, s.actual_pass,
                s.platform, COALESCE(s.platform_confirmed, FALSE), COALESCE(s.platform_suppressed, FALSE), s.cancelled
            FROM train_stops s
            LEFT JOIN locations l ON l.tiploc = s.tiploc
            WHERE s.rid = %s
            ORDER BY s.sequence
        """, (rid,))
        return self.cur.fetchall()

    def fetch_last_write(self) -> datetime | None:
        """When the consumer (or a timetable load) last changed any train."""
        self.cur.execute("SELECT max(updated_at) FROM train_journeys")
        return self.cur.fetchone()[0]

    def fetch_stations(self) -> list[tuple[str, str, float, float]]:
        """
        (crs, name, lon, lat) for every station trains call at publicly, one per CRS code. A station with several
        TIPLOCs (platform groups, low-level platforms) is placed at its NaPTAN point where there is one.
        """
        self.cur.execute("""
            WITH called AS (SELECT DISTINCT tiploc FROM train_stops WHERE location_type IN ('OR', 'IP', 'DT'))
            SELECT DISTINCT ON (l.reservation_code) l.reservation_code, l.location_name, ST_X(t.geom), ST_Y(t.geom)
            FROM locations l
            JOIN called c ON c.tiploc = l.tiploc
            JOIN tiploc_locations t ON t.tiploc = l.tiploc
            WHERE l.reservation_code IS NOT NULL AND l.reservation_code <> 'XXX' AND t.quality <> 'suspect'
            ORDER BY l.reservation_code, (t.source = 'naptan') DESC, l.tiploc
        """)
        return self.cur.fetchall()

    def fetch_operators(self) -> list[tuple[str, str]]:
        """(code, name) for every operator with a known name that runs trains in the timetable."""
        self.cur.execute("""
            SELECT o.toc, o.name FROM train_operator_codes o
            WHERE o.name IS NOT NULL AND EXISTS (SELECT 1 FROM train_journeys j WHERE j.toc_code = o.toc)
            ORDER BY o.name
        """)
        return self.cur.fetchall()

    def fetch_track_tile(self, z: int, x: int, y: int) -> bytes:
        """
        A Mapbox Vector Tile of the Track Model's centrelines in web mercator tile z/x/y, one layer named `track`.
        Lines are simplified to about a pixel in British National Grid before they're transformed, and links shorter
        than that are left out, which keeps a whole-country tile near 100 ms.
        """
        pixel = 40075016.686 / 2**z / 4096 * 0.6  # metres per tile pixel, allowing for BNG's scale at UK latitudes
        self.cur.execute("""
            WITH bounds AS (SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS env),
            tile AS (
                SELECT ST_AsMVTGeom(ST_Transform(ST_Simplify(t.geom, %(pixel)s), 3857), b.env, 4096, 64, true) AS geom
                FROM track_links t, bounds b
                WHERE t.geom && ST_Transform(ST_Expand(b.env, %(buffer)s), 27700) AND t.length_m >= %(pixel)s
            )
            SELECT ST_AsMVT(tile, 'track', 4096, 'geom') FROM tile WHERE geom IS NOT NULL
        """, {"z": z, "x": x, "y": y, "pixel": pixel, "buffer": 40075016.686 / 2**z * 64 / 4096})
        return bytes(self.cur.fetchone()[0])

    # Coverage (coverage_report.py): which stops can be placed on the map

    def fetch_coverage(self, day) -> dict[str, tuple[int, int]]:
        """(placed, total) for the stops of trains scheduled on `day`, by kind of stop."""
        self.cur.execute(f"""
            WITH stops AS (
                SELECT s.rid, s.sequence, s.location_type, ({USABLE_LOCATION}) AS placed,
                    s.location_type IN {CALL_TYPES} AS is_call
                FROM train_stops s
                JOIN train_journeys j ON j.rid = s.rid
                LEFT JOIN tiploc_locations t ON t.tiploc = s.tiploc
                WHERE j.scheduled_start = %(day)s
            ), segments AS (
                SELECT placed AND LEAD(placed) OVER (PARTITION BY rid ORDER BY sequence) AS placed,
                    LEAD(rid) OVER (PARTITION BY rid ORDER BY sequence) IS NOT NULL AS has_next
                FROM stops WHERE is_call
            )
            SELECT 'passenger calls', count(*) FILTER (WHERE placed), count(*) FROM stops WHERE location_type IN ('OR', 'IP', 'DT')
            UNION ALL SELECT 'all calls', count(*) FILTER (WHERE placed), count(*) FROM stops WHERE is_call
            UNION ALL SELECT 'passing points', count(*) FILTER (WHERE placed), count(*) FROM stops WHERE location_type = 'PP'
            UNION ALL SELECT 'all stops', count(*) FILTER (WHERE placed), count(*) FROM stops
            UNION ALL SELECT 'call-to-call segments', count(*) FILTER (WHERE placed), count(*) FROM segments WHERE has_next
        """, {"day": day})
        return {row[0]: (row[1], row[2]) for row in self.cur.fetchall()}

    def fetch_unplaced_tiplocs(self, day, limit: int) -> list[tuple]:
        """
        TIPLOCs that trains scheduled on `day` use but that can't be placed, busiest first:
        (tiploc, name, reason, trains calling, trains passing).
        """
        self.cur.execute(f"""
            SELECT s.tiploc, l.location_name,
                CASE WHEN t.tiploc IS NULL THEN 'missing' ELSE t.quality END,
                count(DISTINCT s.rid) FILTER (WHERE s.location_type IN {CALL_TYPES}),
                count(DISTINCT s.rid) FILTER (WHERE s.location_type NOT IN {CALL_TYPES})
            FROM train_stops s
            JOIN train_journeys j ON j.rid = s.rid
            LEFT JOIN tiploc_locations t ON t.tiploc = s.tiploc
            LEFT JOIN locations l ON l.tiploc = s.tiploc
            WHERE j.scheduled_start = %s AND NOT ({USABLE_LOCATION})
            GROUP BY 1, 2, 3
            ORDER BY count(DISTINCT s.rid) DESC, 1
            LIMIT %s
        """, (day, limit))
        return self.cur.fetchall()

    # Recorded frames (recorder.py) and replay

    def add_frame(self, at, keyframe: bool, source: str, trains: int, active: int, data: bytes):
        self.cur.execute("""
            INSERT INTO position_frames (at, keyframe, source, trains, active, data) VALUES (%s, %s, %s, %s, %s, %s)
        """, (at, keyframe, source, trains, active, data))

    def count_frames(self, start, end) -> tuple[int, int]:
        """Recorded and computed frames from `start` to `end`, inclusive."""
        self.cur.execute("""
            SELECT count(*) FILTER (WHERE source = 'recorded'), count(*) FILTER (WHERE source = 'computed')
            FROM position_frames WHERE at BETWEEN %s AND %s
        """, (start, end))
        return self.cur.fetchone()

    def delete_computed_frames(self, start, end):
        self.cur.execute("DELETE FROM position_frames WHERE source = 'computed' AND at BETWEEN %s AND %s", (start, end))

    def fetch_frames(self, start, end) -> list[tuple]:
        """
        The frames that rebuild every moment from `start` to `end`: the latest keyframe at or before `start` (or, in
        a gap, the first one after it), then every frame after that up to `end`. Rows are (at, keyframe, source,
        data), oldest first; empty when no keyframe is in reach.
        """
        self.cur.execute("""
            WITH key AS (
                SELECT at FROM (
                    (SELECT at, 0 AS pick FROM position_frames
                     WHERE keyframe AND at <= %(start)s AND at > %(start)s - %(reach)s ORDER BY at DESC LIMIT 1)
                    UNION ALL
                    (SELECT at, 1 FROM position_frames
                     WHERE keyframe AND at > %(start)s AND at <= %(end)s ORDER BY at LIMIT 1)
                ) candidates ORDER BY pick LIMIT 1
            )
            SELECT f.at, f.keyframe, f.source, f.data
            FROM position_frames f, key WHERE f.at >= key.at AND f.at <= %(end)s ORDER BY f.at
        """, {"start": start, "end": end, "reach": KEYFRAME_REACH})
        return self.cur.fetchall()

    def fetch_frame_runs(self, start, end, gap) -> list[tuple]:
        """
        Unbroken stretches of frames from `start` to `end`: (first, last, source, frames). Frames further apart than
        `gap`, or from a different source, start a new stretch.
        """
        self.cur.execute("""
            WITH ordered AS (
                SELECT at, source,
                    CASE WHEN at - LAG(at) OVER w > %(gap)s OR source IS DISTINCT FROM LAG(source) OVER w
                        OR LAG(at) OVER w IS NULL THEN 1 ELSE 0 END AS starts
                FROM position_frames WHERE at >= %(start)s AND at < %(end)s
                WINDOW w AS (ORDER BY at)
            ), runs AS (
                SELECT at, source, SUM(starts) OVER (ORDER BY at) AS run FROM ordered
            )
            SELECT min(at), max(at), min(source), count(*) FROM runs GROUP BY run ORDER BY 1
        """, {"start": start, "end": end, "gap": gap})
        return self.cur.fetchall()

    def fetch_frame_days(self) -> list[tuple]:
        """UK days with frames: (day, recorded frames, computed frames), oldest first."""
        self.cur.execute("""
            SELECT (at AT TIME ZONE 'Europe/London')::DATE AS day,
                count(*) FILTER (WHERE source = 'recorded'), count(*) FILTER (WHERE source = 'computed')
            FROM position_frames GROUP BY 1 ORDER BY 1
        """)
        return self.cur.fetchall()

    # Day partitions (retention.py)

    def ensure_day_partition(self, parent: str, key_column: str, day) -> bool:
        """Make `parent`'s partition for one UK day if it's missing. Returns whether it was made."""
        self.cur.execute("SELECT ensure_day_partition(%s, %s, %s)", (parent, key_column, day))
        return self.cur.fetchone()[0]

    def fetch_day_partitions(self, parent: str) -> list[tuple[str, int]]:
        """`parent`'s partitions and their (estimated) row counts, oldest first; the default partition is left out."""
        self.cur.execute("""
            SELECT c.relname, c.reltuples::BIGINT
            FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
            WHERE i.inhparent = to_regclass(%s) AND c.relname ~ '_[0-9]{8}$'
            ORDER BY c.relname
        """, (parent,))
        return self.cur.fetchall()

    def drop_partition(self, name: str):
        self.cur.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(name)))

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
