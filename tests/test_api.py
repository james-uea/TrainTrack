"""The API's routes and wire format, with a stand-in service (no Postgres needed)."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from api import PositionsResponse, TrainDetail, create_app, snapshot_json, train_stop
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
        self.snapshot_bytes = snapshot_json(self.snapshot, CLOCK)

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
