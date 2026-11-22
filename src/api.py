"""
The live map's API: every train's position, one train's details, and the service's health.

A background task ticks the live positions every 5 seconds; requests are served from the latest snapshot.

    uv run src/api.py [--clock now|fixed:<ISO time>|replay:<ISO time>] [--host 127.0.0.1] [--port 8000]
"""

import argparse
import asyncio
import logging
import threading
import time
import tomllib
from collections import OrderedDict
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import load_config
from db import Database
from frames import (
    advance,
    changes_dict,
    position_dict,
    rebuild,
    snapshot_dict,
    to_json,
    unpack,
)
from live import TICK, Clock, LivePositions, Snapshot, SteppedClock
from positions import Position, route
from util import LONDON

logger = logging.getLogger(__name__)

State = Literal["not_started", "dwelling", "running", "held", "terminated"]
Confidence = Literal["high", "medium", "low"]


class TrainPosition(BaseModel):
    rid: str
    headcode: str | None
    toc: str | None
    lat: float
    lon: float
    bearing: int | None  # degrees clockwise from north
    state: State
    confidence: Confidence
    delay: int | None  # minutes late at the last report; negative is early
    from_tiploc: str
    to_tiploc: str
    fraction: float  # how far from from_tiploc to to_tiploc
    left: datetime | None  # when it left from_tiploc: with `due`, fraction = (now - left) / (due - left) while running
    due: datetime | None  # when it's expected at to_tiploc


class PositionsResponse(BaseModel):
    version: int  # counts ticks; pass it to /api/stream as `since` to get only what changes after this
    at: datetime  # the moment the positions are for
    clock: str
    active: int  # trains running, placed or not
    trains: list[TrainPosition]


class TrainStop(BaseModel):
    tiploc: str
    name: str | None
    crs: str | None
    is_call: bool  # the train stops here, including operational stops (crew changes, reversals)
    public: bool  # passengers can get on or off: an origin, calling point or destination in the public timetable
    planned_arrival: datetime | None  # public times for calls, working times otherwise
    planned_departure: datetime | None
    planned_pass: datetime | None
    forecast_arrival: datetime | None
    forecast_departure: datetime | None
    forecast_pass: datetime | None
    actual_arrival: datetime | None
    actual_departure: datetime | None
    actual_pass: datetime | None
    platform: str | None  # None when Darwin says not to show it
    platform_confirmed: bool
    cancelled: bool


class TrainDetail(BaseModel):
    rid: str
    headcode: str | None
    toc: str | None
    operator: str | None
    cancelled: bool
    cancel_reason: str | None
    late_reason: str | None
    delay: int | None
    origin: str | None
    destination: str | None
    stops: list[TrainStop]
    route: list[tuple[float, float]]  # (lon, lat) along the track, stop to stop
    position: TrainPosition | None


class Station(BaseModel):
    crs: str
    name: str
    lon: float
    lat: float


class Operator(BaseModel):
    code: str  # as in each train's `toc`
    name: str


class PositionChanges(BaseModel):
    """What changed in one tick. Trains not listed are unchanged: a client moves them on with `left` and `due`."""
    version: int
    at: datetime
    clock: str
    active: int
    trains: list[TrainPosition]  # new or changed
    removed: list[str]  # rids no longer shown


Source = Literal["recorded", "computed"]


class ReplayFrame(BaseModel):
    """One stored tick. A keyframe lists every placed train; otherwise only those that changed since the frame
    before, and the rids removed."""
    at: datetime
    keyframe: bool
    source: Source  # recorded live, or computed afterwards from the database (later forecasts may show through)
    active: int
    trains: list[TrainPosition]
    removed: list[str]


class ReplayResponse(BaseModel):
    start: datetime
    end: datetime
    frames: list[ReplayFrame]  # oldest first; the first is a keyframe. Empty when nothing was stored


class ReplayRun(BaseModel):
    start: datetime
    end: datetime
    source: Source


class ReplayDay(BaseModel):
    day: str  # UK date, YYYY-MM-DD
    recorded_minutes: float
    computed_minutes: float


class Health(BaseModel):
    clock: str
    at: datetime | None
    tick_ms: float | None
    trains_loaded: int
    active: int
    placed: int
    last_write: datetime | None  # when the consumer last changed any train


VERSION = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())["project"]["version"]
MAX_SEGMENTS = 500  # per request
MAX_REPLAY = timedelta(minutes=15)  # longest window /api/replay returns at once
# Frames further apart than this leave a gap: the moments between aren't covered
FRAME_GAP = timedelta(seconds=30)
REPLAY_DAYS_REFRESH = 60.0  # seconds
# Track tiles exist from the zoom the whole network first reads as lines down to the zoom MapLibre overzooms from
TRACK_ZOOMS = range(5, 15)
STATIONS_REFRESH = 3600.0  # seconds; stations change only with the timetable
TRACK_TILES_CACHED = 2048  # most recently used tiles kept in memory; the Track Model changes only when reloaded
WEB_DIST = Path(__file__).parent.parent / "web" / "dist"
CALL_TYPES = {"OR", "IP", "DT", "OPOR", "OPIP", "OPDT"}
PUBLIC_TYPES = {"OR", "IP", "DT"}


def train_stop(row: tuple) -> TrainStop:
    (tiploc, name, crs, location_type, public_arrival, public_departure, working_arrival, working_departure,
     working_pass, est_arrival, est_departure, est_pass, act_arrival, act_departure, act_pass,
     platform, platform_confirmed, platform_suppressed, cancelled) = row
    is_call = location_type in CALL_TYPES
    return TrainStop(
        tiploc=tiploc, name=name, crs=crs, is_call=is_call, public=location_type in PUBLIC_TYPES,
        planned_arrival=(public_arrival or working_arrival) if is_call else working_arrival,
        planned_departure=(public_departure or working_departure) if is_call else working_departure,
        planned_pass=working_pass,
        forecast_arrival=est_arrival, forecast_departure=est_departure, forecast_pass=est_pass,
        actual_arrival=act_arrival, actual_departure=act_departure, actual_pass=act_pass,
        platform=None if platform_suppressed else platform, platform_confirmed=platform_confirmed,
        cancelled=cancelled,
    )


class MapService:
    """The live positions and the latest snapshot, ticked in a background thread."""

    def __init__(self, database_url: str, clock: Clock):
        self.clock = clock
        self.database_url = database_url
        self.live = LivePositions(Database(database_url), clock)
        # Positions at a moment a page asks for (?at=), separate from the service's own clock. Created on first use;
        # a page replaying forward asks for moments a few seconds apart, which is a cheap tick
        self._replay: tuple[SteppedClock, LivePositions] | None = None
        self._replay_lock = threading.Lock()
        self.snapshot: Snapshot | None = None
        self.version = 0
        self.snapshot_bytes: bytes | None = None
        self.changes_bytes: bytes | None = None  # from the previous version to this one
        self._snapshot_dict: dict | None = None
        self.positions: dict[str, Position] = {}
        # Request queries get their own connection: psycopg connections aren't shared between threads
        self._db = Database(database_url)
        self._db_lock = threading.Lock()
        self.ticked = asyncio.Event()
        self._segments: dict[str, list[tuple[float, float]]] = {}
        self._track_tiles: OrderedDict[tuple[int, int, int], bytes] = OrderedDict()
        self._stations: tuple[float, list[Station]] | None = None  # (loaded at, stations)
        self._replay_days: tuple[float, list[ReplayDay]] | None = None

    def tick(self):
        snapshot = self.live.tick()
        current = snapshot_dict(snapshot, self.clock, self.version + 1)
        changes = changes_dict(self._snapshot_dict, current)
        # Publish everything for the new version together, so readers never mix versions
        self.snapshot_bytes, self.changes_bytes = to_json(current), to_json(changes)
        self.positions = {journey.rid: position for journey, position in snapshot.positions}
        self.snapshot, self._snapshot_dict = snapshot, current
        self.version += 1

    async def run(self):
        while True:
            try:
                await asyncio.to_thread(self.tick)
                self.ticked.set()
                self.ticked = asyncio.Event()
            except Exception:
                logger.exception("Tick failed")
            await asyncio.sleep(TICK.total_seconds())

    async def events(self, since: int | None):
        """Server-sent events: the whole snapshot unless the client is up to date, then each tick's changes."""
        version = self.version
        if since != version:
            if since is not None and since == version - 1:
                yield ServerSentEvent(event="changes", id=str(version), raw_data=self.changes_bytes.decode())
            else:
                yield ServerSentEvent(event="snapshot", id=str(version), raw_data=self.snapshot_bytes.decode())
        while True:
            await self.ticked.wait()
            if self.version == version + 1:
                yield ServerSentEvent(event="changes", id=str(self.version), raw_data=self.changes_bytes.decode())
            else:
                yield ServerSentEvent(event="snapshot", id=str(self.version), raw_data=self.snapshot_bytes.decode())
            version = self.version

    def query(self, method: str, *args):
        with self._db_lock:
            try:
                return getattr(self._db, method)(*args)
            finally:
                self._db.conn.rollback()

    def train(self, rid: str, at: datetime | None = None) -> TrainDetail | None:
        """One train's details. With `at`, as they stood then: later actual times are left out, and the position
        is the one the map showed."""
        row = self.query("fetch_train", rid)
        if row is None:
            return None
        rid, headcode, toc, operator, cancelled, _, cancel_reason, late_reason, delay = row
        stops = [train_stop(stop) for stop in self.query("fetch_panel_stops", rid)]
        calls = [stop for stop in stops if stop.is_call]

        journey = self.live.journey(rid)
        position = self.positions.get(rid)
        if at is not None:
            for stop in stops:
                for name in ("actual_arrival", "actual_departure", "actual_pass"):
                    if (value := getattr(stop, name)) is not None and value > at:
                        setattr(stop, name, None)
            snapshot = self.stored_positions(at) or self.computed_positions(at)
            stored = next((train for train in snapshot["trains"] if train["rid"] == rid), None)
            with self._replay_lock:
                replay_live = self._replay_live()
                journey = journey or replay_live.journey(rid)
                paths = replay_live.paths
            return TrainDetail(
                rid=rid, headcode=headcode, toc=toc, operator=operator, cancelled=cancelled,
                cancel_reason=cancel_reason, late_reason=late_reason, delay=stored["delay"] if stored else None,
                origin=calls[0].name if calls else None, destination=calls[-1].name if calls else None,
                stops=stops, route=route(journey, paths) if journey is not None and paths else [],
                position=TrainPosition(**stored) if stored else None,
            )
        return TrainDetail(
            rid=rid, headcode=headcode, toc=toc, operator=operator, cancelled=cancelled,
            cancel_reason=cancel_reason, late_reason=late_reason, delay=delay,
            origin=calls[0].name if calls else None, destination=calls[-1].name if calls else None,
            stops=stops,
            route=route(journey, self.live.paths) if journey is not None and self.live.paths else [],
            position=TrainPosition(**position_dict(journey, position)) if journey and position else None,
        )

    def segments(self, pairs: list[str]) -> dict[str, list[tuple[float, float]]]:
        found = {}
        for pair in pairs[:MAX_SEGMENTS]:
            if pair not in self._segments:
                from_tiploc, _, to_tiploc = pair.partition(">")
                if (line := self.live.segment(from_tiploc, to_tiploc)) is None:
                    continue
                self._segments[pair] = line
            found[pair] = self._segments[pair]
        return found

    def positions_at(self, at: datetime) -> bytes:
        """
        Every placed train at `at`, shaped like /api/positions, for a page looking at the past: rebuilt from stored
        frames where they cover the moment, otherwise computed from the database as it is now.
        """
        if (snapshot := self.stored_positions(at)) is not None:
            return to_json(snapshot)
        return to_json(self.computed_positions(at))

    def stored_positions(self, at: datetime) -> dict | None:
        rows = self.query("fetch_frames", at, at)
        if not rows or at - rows[-1][0] > FRAME_GAP:
            return None
        rebuilt = rebuild([unpack(data) for _, _, _, data in rows])
        rebuilt.update(version=0, clock=f"replay:{at.isoformat()}")
        with self._replay_lock:
            segment = self._replay_live().segment
            return advance(rebuilt, at, segment)

    def computed_positions(self, at: datetime) -> dict:
        with self._replay_lock:
            live = self._replay_live()
            live.clock.start = at
            snapshot = live.tick()
        return snapshot_dict(snapshot, Clock(at), 0)

    def _replay_live(self) -> LivePositions:
        """Positions for moments pages ask for (?at=), separate from the service's own clock. Hold _replay_lock."""
        if self._replay is None:
            clock = SteppedClock(datetime.now(UTC))
            self._replay = (clock, LivePositions(Database(self.database_url), clock))
        live = self._replay[1]
        if live.paths is None:
            live.tick()  # loads the track paths segments are cut from
        return live

    def replay(self, start: datetime, end: datetime) -> bytes:
        """The stored frames that rebuild every moment from `start` to `end` (see /api/replay)."""
        frames = []
        for at, keyframe, source, data in self.query("fetch_frames", start, end):
            frame = unpack(data)
            frames.append({"at": at.isoformat(), "keyframe": keyframe, "source": source, "active": frame["active"],
                           "trains": frame["trains"], "removed": frame.get("removed", [])})
        return to_json({"start": start.isoformat(), "end": end.isoformat(), "frames": frames})

    def replay_runs(self, day: date) -> list[ReplayRun]:
        start = datetime.combine(day, datetime.min.time(), LONDON)
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), LONDON)
        return [ReplayRun(start=first, end=last, source=source)
                for first, last, source, _ in self.query("fetch_frame_runs", start, end, FRAME_GAP)]

    def replay_days(self) -> list[ReplayDay]:
        if self._replay_days is None or time.monotonic() - self._replay_days[0] > REPLAY_DAYS_REFRESH:
            days = [ReplayDay(day=day.isoformat(), recorded_minutes=round(recorded / 12, 1),
                              computed_minutes=round(computed / 12, 1))
                    for day, recorded, computed in self.query("fetch_frame_days")]
            self._replay_days = (time.monotonic(), days)
        return self._replay_days[1]

    def stations(self) -> list[Station]:
        if self._stations is None or time.monotonic() - self._stations[0] > STATIONS_REFRESH:
            stations = [Station(crs=crs, name=name, lon=round(lon, 5), lat=round(lat, 5))
                        for crs, name, lon, lat in self.query("fetch_stations")]
            self._stations = (time.monotonic(), stations)
        return self._stations[1]

    def track_tile(self, z: int, x: int, y: int) -> bytes:
        key = (z, x, y)
        if (tile := self._track_tiles.get(key)) is None:
            tile = self.query("fetch_track_tile", z, x, y)
            self._track_tiles[key] = tile
            if len(self._track_tiles) > TRACK_TILES_CACHED:
                self._track_tiles.popitem(last=False)
        else:
            self._track_tiles.move_to_end(key)
        return tile

    def health(self) -> Health:
        snapshot = self.snapshot
        return Health(
            clock=str(self.clock), at=snapshot.at if snapshot else None,
            tick_ms=round(1000 * snapshot.timings["total"], 1) if snapshot else None,
            trains_loaded=len(self.live.journeys), active=snapshot.active if snapshot else 0,
            placed=len(snapshot.positions) if snapshot else 0, last_write=self.query("fetch_last_write"),
        )

    def close(self):
        self.live.db.close()
        self._db.close()


def utc(at: datetime) -> datetime:
    """A time from a query string; one without a zone is read as UTC."""
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def create_app(service: MapService | None = None, clock: Clock | None = None) -> FastAPI:
    """The app. Pass a `service` to use one already made (tests); otherwise one is made at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        made = service or MapService(load_config().database_url, clock or Clock())
        app.state.service = made
        await asyncio.to_thread(made.tick)  # serve real positions from the first request
        runner = asyncio.create_task(made.run())
        try:
            yield
        finally:
            runner.cancel()
            with suppress(asyncio.CancelledError):
                await runner
            if service is None:
                made.close()

    app = FastAPI(title="TrainTrack", version=VERSION, lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    def current(app_: FastAPI) -> MapService:
        return app_.state.service

    @app.get("/api/positions", response_model=PositionsResponse)
    def positions(at: datetime | None = None) -> Response:
        """
        Every placed train at the latest tick, or at `at` (an ISO time) to look at another moment. A page replaying
        the past asks again every few seconds with a later `at`; `clock` in the reply is then `replay:<at>`.
        """
        if at is None:
            return Response(current(app).snapshot_bytes, media_type="application/json")
        return Response(current(app).positions_at(utc(at)), media_type="application/json")

    @app.get("/api/replay", response_model=ReplayResponse)
    def replay(start: datetime, end: datetime) -> Response:
        """
        Stored frames for playing back the past: the keyframe at or before `start`, then every frame up to `end`
        (at most 15 minutes after `start`). Apply them in order: a keyframe replaces every train, other frames
        add or update `trains` and drop `removed`. Between frames, trains move along their segments by `left` and
        `due`, as with the stream.
        """
        start, end = utc(start), utc(end)
        if end < start or end - start > MAX_REPLAY:
            raise HTTPException(422, "end must be after start, and at most 15 minutes after it")
        return Response(current(app).replay(start, end), media_type="application/json")

    @app.get("/api/replay/days", response_model=list[ReplayDay])
    def replay_days() -> list[ReplayDay]:
        """UK days with stored frames, oldest first, and how much of each was recorded live or computed later."""
        return current(app).replay_days()

    @app.get("/api/replay/runs", response_model=list[ReplayRun])
    def replay_runs(day: date) -> list[ReplayRun]:
        """Unbroken stretches of stored frames on one UK day: the moments that can be replayed."""
        return current(app).replay_runs(day)

    @app.get("/api/trains/{rid}", response_model=TrainDetail)
    def train(rid: str, at: datetime | None = None) -> TrainDetail:
        """One train's stops, times, route and position; with `at`, as the map showed them at that moment."""
        detail = current(app).train(rid, utc(at) if at else None)
        if detail is None:
            raise HTTPException(404, f"No train {rid}")
        return detail

    @app.get("/api/stream", response_class=EventSourceResponse)
    async def stream(since: int | None = None, last_event_id: str | None = Header(None)) -> AsyncIterable[ServerSentEvent]:
        """
        Positions as server-sent events, one per tick. A `snapshot` event holds every train (as /api/positions);
        a `changes` event holds only new and changed trains and the rids removed. Pass the version you already have
        as `since` (or let the browser send Last-Event-ID on reconnect) to start with changes instead of a snapshot.
        """
        if since is None and last_event_id and last_event_id.isdigit():
            since = int(last_event_id)
        async for event in current(app).events(since):
            yield event

    @app.get("/api/segments", response_model=dict[str, list[tuple[float, float]]])
    def segments(pairs: Annotated[list[str], Query()]) -> dict[str, list[tuple[float, float]]]:
        """
        Track paths between pairs of TIPLOCs, written `FROM>TO`, as (lon, lat) points: the lines trains move along
        between their `from_tiploc` and `to_tiploc`. Pairs that can't be placed are left out.
        """
        return current(app).segments(pairs)

    @app.get("/api/stations", response_model=list[Station])
    def stations() -> list[Station]:
        """Every station trains call at, by CRS code, for search."""
        return current(app).stations()

    @app.get("/api/operators", response_model=list[Operator])
    def operators() -> list[Operator]:
        """Train operators by code, for search."""
        return [Operator(code=code, name=name) for code, name in current(app).query("fetch_operators")]

    @app.get("/tiles/track/{z}/{x}/{y}.pbf", include_in_schema=False)
    def track_tile(z: int, x: int, y: int) -> Response:
        """The Track Model's lines as a vector tile (layer `track`), drawn under the trains."""
        if z not in TRACK_ZOOMS or not (0 <= x < 2**z and 0 <= y < 2**z):
            raise HTTPException(404, "No track tile there")
        return Response(current(app).track_tile(z, x, y), media_type="application/vnd.mapbox-vector-tile",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return current(app).health()

    def openapi() -> dict:
        """The schema, plus the stream's event payloads, which no route returns as JSON."""
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            extra = PositionChanges.model_json_schema(ref_template="#/components/schemas/{model}")
            components = schema.setdefault("components", {}).setdefault("schemas", {})
            components.update(extra.pop("$defs", {}))
            components["PositionChanges"] = extra
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi

    # The built web front end (web/dist), if there is one; API routes above take precedence
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clock", default=None, help="now, fixed:<ISO time> or replay:<ISO time> (default: $MAP_CLOCK or now)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    clock = Clock.parse(args.clock or config.map_clock)
    logger.info("Clock: %s", clock)
    uvicorn.run(create_app(clock=clock), host=args.host, port=args.port, log_level=config.log_level.lower())


if __name__ == "__main__":
    main()
