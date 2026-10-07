from dataclasses import dataclass


@dataclass
class Location:
    tiploc: str
    working_arrival: str | None
    working_departure: str | None
    working_pass: str | None
    actual_arrival: str | None
    actual_departure: str | None
    actual_pass: str | None

@dataclass
class TrainStatus:
    update_origin: str | None
    rid: str
    uid: str | None
    ssd: str | None
    locations: list[Location]

def parse_location(loc: dict) -> Location:
    def actual_time(k):
        return (loc.get(k) or {}).get('at')

    return Location(
        tiploc=loc.get('tpl'),
        working_arrival=loc.get('wta'),
        working_departure=loc.get('wtd'),
        working_pass=loc.get('wtp'),
        actual_arrival=actual_time('arr'),
        actual_departure=actual_time('dep'),
        actual_pass=actual_time('pass')
    )
