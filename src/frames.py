"""
The map's wire format, shared by the live API and the recorder: a snapshot of every placed train, and the changes
between two snapshots. Recorded frames store exactly these, gzipped.
"""

import gzip
import itertools
import json
import math
from collections.abc import Callable
from datetime import datetime

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


def rebuild(frames: list[dict]) -> dict:
    """
    The snapshot a run of frames adds up to: the first must be a keyframe, each later one either a keyframe (which
    replaces everything) or the changes since the frame before it.
    """
    trains: dict[str, dict] = {}
    current: dict = {}
    for frame in frames:
        if "removed" not in frame:  # a keyframe
            trains = {train["rid"]: train for train in frame["trains"]}
        else:
            for rid in frame["removed"]:
                trains.pop(rid, None)
            for train in frame["trains"]:
                trains[train["rid"]] = train
        current = frame
    return {**{k: v for k, v in current.items() if k != "removed"}, "trains": list(trains.values())}


def fraction_at(train: dict, at: datetime) -> float:
    """How far along its segment a train is at `at`: the formula the map uses between updates (motion.ts)."""
    if train["state"] == "held":
        return 1.0
    if not train["left"] or not train["due"]:
        return train["fraction"]
    left, due = datetime.fromisoformat(train["left"]), datetime.fromisoformat(train["due"])
    if due <= left:
        return 1.0
    return min(max((at - left) / (due - left), 0.0), 1.0)


def point_along(line: list[tuple[float, float]], fraction: float) -> tuple[float, float, float]:
    """(lon, lat, bearing) `fraction` of the way along a (lon, lat) line, measuring with a local flat projection."""
    scale = math.cos(math.radians(sum(lat for _, lat in line) / len(line)))
    steps = [math.hypot((b[0] - a[0]) * scale, b[1] - a[1]) for a, b in itertools.pairwise(line)]
    distance = fraction * sum(steps)
    last = len(steps) - 1
    for index, ((a, b), step) in enumerate(zip(itertools.pairwise(line), steps, strict=True)):
        if distance <= step or index == last:
            t = min(distance / step, 1.0) if step else 0.0
            bearing = math.degrees(math.atan2((b[0] - a[0]) * scale, b[1] - a[1])) % 360
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, bearing
        distance -= step
    return line[-1][0], line[-1][1], 0.0


def advance(snapshot: dict, at: datetime, segment: Callable[[str, str], list | None]) -> dict:
    """
    A rebuilt snapshot moved on to `at`: frames only resend a running train when its segment or times change, so
    its stored point is from its last change. Moving trains are placed along their segment as the map does.
    """
    trains = []
    for train in snapshot["trains"]:
        moving = train["state"] in ("running", "held") and train["from_tiploc"] != train["to_tiploc"]
        line = segment(train["from_tiploc"], train["to_tiploc"]) if moving else None
        if line and len(line) > 1:
            fraction = fraction_at(train, at)
            lon, lat, bearing = point_along(line, fraction)
            train = {**train, "lon": round(lon, 5), "lat": round(lat, 5), "bearing": round(bearing) % 360,
                     "fraction": round(fraction, 4)}
        trains.append(train)
    return {**snapshot, "at": at.isoformat(), "trains": trains}
