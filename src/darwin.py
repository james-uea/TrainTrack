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
    sequence: str | None = None

@dataclass
class TrainStatus:
    update_origin: str | None
    rid: str
    uid: str | None
    scheduled_start: str | None
    locations: list[Location]

    def starts(self) -> str | None:
        # Return the working_departure from the first sequence
        if len(self.locations) > 0 and self.scheduled_start:
            return f"{self.scheduled_start} {self.locations[0].working_departure}"

    def ends(self) -> str | None:
        # Return the working_arrival from the last sequence
        if len(self.locations) > 0:
            return self.locations[len(self.locations) - 1].working_arrival

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
