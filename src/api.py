"""
The live map's API: every train's position, one train's details, and the service's health.

A background task ticks the live positions every 5 seconds; requests are served from the latest snapshot.

    uv run src/api.py [--clock now|fixed:<ISO time>|replay:<ISO time>] [--host 127.0.0.1] [--port 8000]
"""

import argparse
import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Literal

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from config import load_config
from db import Database
from live import TICK, Clock, LivePositions, Snapshot
from positions import Journey, Position, route

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
    is_call: bool
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


class PositionChanges(BaseModel):
    """What changed in one tick. Trains not listed are unchanged: a client moves them on with `left` and `due`."""
    version: int
    at: datetime
    clock: str
    active: int
    trains: list[TrainPosition]  # new or changed
    removed: list[str]  # rids no longer shown


class Health(BaseModel):
    clock: str
    at: datetime | None
    tick_ms: float | None
    trains_loaded: int
    active: int
    placed: int
    last_write: datetime | None  # when the consumer last changed any train


CALL_TYPES = {"OR", "IP", "DT", "OPOR", "OPIP", "OPDT"}


def position_dict(journey: Journey, position: Position) -> dict:
    return {
        "rid": journey.rid, "headcode": journey.train_id, "toc": journey.toc,
        "lat": round(position.lat, 5), "lon": round(position.lon, 5),
        "bearing": round(position.bearing) % 360 if position.bearing is not None else None,
        "state": position.state, "confidence": position.confidence, "delay": position.delay_minutes,
        "from_tiploc": position.from_tiploc, "to_tiploc": position.to_tiploc,
        "fraction": round(position.fraction, 4),
        "left": position.left.isoformat() if position.left else None,
        "due": position.due.isoformat() if position.due else None,
    }


# A train's position is resent only when one of these changes; in between, a client works out where it is
CHANGE_FIELDS = ("headcode", "toc", "state", "confidence", "delay", "from_tiploc", "to_tiploc", "left", "due")


def change_key(train: dict) -> tuple:
    key = tuple(train[name] for name in CHANGE_FIELDS)
    # A train standing still or moving with no times has nothing for a client to work from: send its point
    return key if train["state"] == "running" and train["due"] else (*key, train["lat"], train["lon"])


def to_json(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def snapshot_dict(snapshot: Snapshot, clock: Clock, version: int) -> dict:
    return {
        "version": version, "at": snapshot.at.isoformat(), "clock": str(clock), "active": snapshot.active,
        "trains": [position_dict(journey, position) for journey, position in snapshot.positions],
    }


def snapshot_json(snapshot: Snapshot, clock: Clock, version: int = 0) -> bytes:
    return to_json(snapshot_dict(snapshot, clock, version))


def changes_dict(before: dict | None, after: dict) -> dict:
    """The trains in snapshot `after` that are new or changed since `before`, and those that have gone."""
    old = {train["rid"]: change_key(train) for train in before["trains"]} if before else {}
    current = {train["rid"] for train in after["trains"]}
    return {
        "version": after["version"], "at": after["at"], "clock": after["clock"], "active": after["active"],
        "trains": [train for train in after["trains"] if old.get(train["rid"]) != change_key(train)],
        "removed": sorted(set(old) - current),
    }


def train_stop(row: tuple) -> TrainStop:
    (tiploc, name, crs, location_type, public_arrival, public_departure, working_arrival, working_departure,
     working_pass, est_arrival, est_departure, est_pass, act_arrival, act_departure, act_pass,
     platform, platform_confirmed, platform_suppressed, cancelled) = row
    is_call = location_type in CALL_TYPES
    return TrainStop(
        tiploc=tiploc, name=name, crs=crs, is_call=is_call,
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
        self.live = LivePositions(Database(database_url), clock)
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

    def train(self, rid: str) -> TrainDetail | None:
        row = self.query("fetch_train", rid)
        if row is None:
            return None
        rid, headcode, toc, operator, cancelled, _, cancel_reason, late_reason, delay = row
        stops = [train_stop(stop) for stop in self.query("fetch_panel_stops", rid)]
        calls = [stop for stop in stops if stop.is_call]

        journey = self.live.journey(rid)
        position = self.positions.get(rid)
        return TrainDetail(
            rid=rid, headcode=headcode, toc=toc, operator=operator, cancelled=cancelled,
            cancel_reason=cancel_reason, late_reason=late_reason, delay=delay,
            origin=calls[0].name if calls else None, destination=calls[-1].name if calls else None,
            stops=stops,
            route=route(journey, self.live.paths) if journey is not None and self.live.paths else [],
            position=TrainPosition(**position_dict(journey, position)) if journey and position else None,
        )

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

    app = FastAPI(title="TrainTrack", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    def current(app_: FastAPI) -> MapService:
        return app_.state.service

    @app.get("/api/positions", response_model=PositionsResponse)
    def positions() -> Response:
        """Every placed train at the latest tick."""
        return Response(current(app).snapshot_bytes, media_type="application/json")

    @app.get("/api/trains/{rid}", response_model=TrainDetail)
    def train(rid: str) -> TrainDetail:
        """One train's stops, times, route and position."""
        detail = current(app).train(rid)
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

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return current(app).health()

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
