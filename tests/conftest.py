import json
import os

import pytest


def envelope(document: dict, sequence: int | None = None) -> bytes:
    """Wrap a Push Port document the way RailData's Kafka topic does."""
    properties = {}
    if sequence is not None:
        properties["PushPortSequence"] = {"propertyType": "string", "string": str(sequence)}
    return json.dumps({
        "destination": {"name": "Consumer.rdmportal.VirtualTopic.PushPort-v18", "destinationType": "queue"},
        "messageType": "bytes",
        "bytes": json.dumps(document),
        "properties": properties,
    }).encode()


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture_lines(name: str) -> list[bytes]:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return [line.rstrip(b"\n") for line in f if line.strip()]


@pytest.fixture
def db():
    """
    A clean, migrated database. Needs TEST_DATABASE_URL pointing at a database that can be wiped,
    e.g. `postgresql://postgres:secret@localhost:5432/traintrack_test`.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")

    from db import Database
    from migrate import apply_migrations

    database = Database(url)
    database.cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    database.commit()
    apply_migrations(database)
    yield database
    database.close()
