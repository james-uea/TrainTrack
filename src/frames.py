"""
The map's wire format, shared by the live API and the recorder: a snapshot of every placed train, and the changes
between two snapshots. Recorded frames store exactly these, gzipped.
"""

import gzip
import json

from live import Clock, Snapshot
from positions import Journey, Position


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




def pack(value: dict) -> bytes:
    """A frame as stored in position_frames: compact JSON, gzipped."""
    return gzip.compress(to_json(value), compresslevel=6)


def unpack(data: bytes) -> dict:
    return json.loads(gzip.decompress(data))

