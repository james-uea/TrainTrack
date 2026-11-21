"""The API's routes and wire format, with a stand-in service (no Postgres needed)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from api import (
    PositionsResponse,
    TrainDetail,
    changes_dict,
    create_app,
    snapshot_dict,
    to_json,
    train_stop,
)
from api_schema import schema
from live import Clock, Snapshot
from positions import Journey, Position

AT = datetime(2026, 11, 21, 14, 45, tzinfo=UTC)
JOURNEY = Journey("202611218733688", [], "1A48", "VT")
POSITION = Position(51.93831, -0.691812, 109.6, "running", "high", "BLTCHLY", "LEDBRNJ", 0.60004, 10, 30.0,
                    datetime(2026, 11, 21, 14, 44, tzinfo=UTC), datetime(2026, 11, 21, 14, 47, tzinfo=UTC))
CLOCK = Clock.parse("fixed:2026-11-21T14:45Z")


class StubService:
    def __init__(self):
        self.snapshot = Snapshot(AT, [(JOURNEY, POSITION)], active=2)
        self.version = 1
        current = snapshot_dict(self.snapshot, CLOCK, 1)
        self.snapshot_bytes, self.changes_bytes = to_json(current), to_json(changes_dict(None, current))

    async def events(self, since):
        from api import MapService
        async for event in MapService.events(self, since):
            yield event
            return  # one event is enough here

    def tick(self):
        pass

    async def run(self):
        pass

    def train(self, rid):
        if rid != JOURNEY.rid:
            return None
        return TrainDetail(rid=rid, headcode="1A48", toc="VT", operator="Avanti West Coast", cancelled=False,
                           cancel_reason=None, late_reason=None, delay=10, origin="Liverpool Lime Street",
                           destination="London Euston", stops=[], route=[(-0.7, 51.9)], position=None)


def client() -> TestClient:
    return TestClient(create_app(StubService()))


def test_positions_match_their_published_schema():
    with client() as api:
        response = api.get("/api/positions", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    body = TypeAdapter(PositionsResponse).validate_json(response.content)
    assert body.active == 2
    train = body.trains[0]
    assert (train.headcode, train.lat, train.lon, train.bearing, train.fraction) == ("1A48", 51.93831, -0.69181, 110, 0.6)
    assert train.due == datetime(2026, 11, 21, 14, 47, tzinfo=UTC)


def test_train_details_and_a_missing_train():
    with client() as api:
        assert api.get("/api/trains/202611218733688").json()["destination"] == "London Euston"
        assert api.get("/api/trains/nope").status_code == 404


def test_platform_hidden_when_darwin_suppresses_it_and_public_times_used_for_calls():
    public, working = datetime(2026, 11, 21, 14, 0, tzinfo=UTC), datetime(2026, 11, 21, 13, 59, 30, tzinfo=UTC)
    row = ("NRCH", "Norwich", "NRW", "OR", None, public, None, working, None, None, None, None, None, None, None,
           "3", True, True, False)
    stop = train_stop(row)
    assert (stop.is_call, stop.planned_departure, stop.platform) == (True, public, None)


def train_dict(rid, **changes):
    train = {"rid": rid, "headcode": "1A48", "toc": "VT", "lat": 51.9, "lon": -0.7, "bearing": 110,
             "state": "running", "confidence": "high", "delay": 10, "from_tiploc": "BLTCHLY", "to_tiploc": "LEDBRNJ",
             "fraction": 0.5, "left": "2026-11-21T14:44:00+00:00", "due": "2026-11-21T14:47:00+00:00"}
    return {**train, **changes}


def snap(version, *trains):
    return {"version": version, "at": AT.isoformat(), "clock": "now", "active": len(trains), "trains": list(trains)}


def test_changes_leave_out_trains_a_client_can_move_on_itself():
    before = snap(1, train_dict("A"), train_dict("B"), train_dict("C", state="dwelling", fraction=0.0),
                  train_dict("GONE"))
    after = snap(2,
                 train_dict("A", lat=51.95, fraction=0.6),  # moved along the same segment: client works it out
                 train_dict("B", to_tiploc="WOLVRTN", fraction=0.0),  # next segment
                 train_dict("C", state="dwelling", fraction=0.0),  # still standing
                 train_dict("NEW"))
    changes = changes_dict(before, after)
    assert [train["rid"] for train in changes["trains"]] == ["B", "NEW"]
    assert changes["removed"] == ["GONE"]


def test_the_stream_starts_with_a_snapshot_unless_the_client_is_up_to_date():
    with client() as api:
        with api.stream("GET", "/api/stream") as response:
            text = "".join(response.iter_text())
        assert "event: snapshot" in text and "id: 1" in text
        with api.stream("GET", "/api/stream?since=0") as response:
            assert "event: changes" in "".join(response.iter_text())


def test_the_web_front_ends_copy_of_the_schema_is_current():
    """web/openapi.json generates the front end's types; regenerate both with `pnpm gen:api` in web/."""
    with open(Path(__file__).parent.parent / "web" / "openapi.json") as f:
        assert json.load(f) == schema()
