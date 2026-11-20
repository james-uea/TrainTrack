from datetime import datetime
from itertools import cycle

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Static

from db import Database, JourneySummary
from util import LONDON

cursors = cycle(["row", "column", "none"])


def hhmm(value: datetime | None) -> str:
    return value.astimezone(LONDON).strftime("%H:%M") if value else ""


def delay_text(minutes: int | None) -> str:
    if minutes is None:
        return ""
    if minutes == 0:
        return "on time"
    return f"{minutes} late" if minutes > 0 else f"{-minutes} early"


class StopsScreen(Screen):
    BINDINGS = [  # noqa: RUF012
        Binding(key="left", action="app.pop_screen", description="Go back"),
        Binding(key="escape", action="app.pop_screen", description="Go back"),
    ]

    def __init__(self, train: JourneySummary, db: Database):
        super().__init__()
        self.train = train
        self.db = db

    def compose(self) -> ComposeResult:
        yield Static(f"{self.train.uid} {self.train.origin} to {self.train.destination} ({self.train.scheduled_start}, rid {self.train.rid})")
        yield DataTable()
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = 'row'
        table.zebra_stripes = True
        table.add_columns('#', 'Location', 'Plat', 'Plan arr', 'Plan dep', 'Plan pass', 'Exp arr', 'Exp dep', 'Exp pass', 'Arrived', 'Departed', 'Passed')

        for stop in self.db.fetch_train_stops(self.train.rid):
            table.add_row(
                stop.sequence, stop.tiploc, stop.platform or '',
                hhmm(stop.working_arrival), hhmm(stop.working_departure), hhmm(stop.working_pass),
                hhmm(stop.estimated_arrival), hhmm(stop.estimated_departure), hhmm(stop.estimated_pass),
                hhmm(stop.actual_arrival), hhmm(stop.actual_departure), hhmm(stop.actual_pass),
            )

class JourneyTable(DataTable):
    BINDINGS = [Binding(key="right", action="select_cursor", description="Open Journey")]  # noqa: RUF012

class TrainSearchApp(App):
    BINDINGS = [  # noqa: RUF012
        Binding(key="q", action="quit", description="Quit the app")
    ]

    def compose(self) -> ComposeResult:
        yield JourneyTable()
        yield Footer()

    def load_trains(self):
        trains = self.db.fetch_train_journeys()
        self.trains = {train.rid: train for train in trains}

        self.table.clear()
        for train in self.trains.values():
            last_seen = f"{train.last_report_type or ''} {train.last_location or ''} {hhmm(train.last_reported_at)}".strip()
            self.table.add_row(
                train.uid, train.toc or '', train.origin or '', hhmm(train.departs), train.destination or '',
                hhmm(train.arrives), last_seen, 'cancelled' if train.cancelled else delay_text(train.delay_minutes),
                key=train.rid,
            )

    def on_mount(self) -> None:
        ROWS = [
            ("UID", "TOC", "From", "Departs", "To", "Arrives", "Last seen", "Delay")
        ]

        self.db = Database()

        self.table = self.query_one(DataTable)
        self.table.cursor_type = next(cursors)
        self.table.zebra_stripes = True
        self.table.add_columns(*ROWS[0])

        self.load_trains()
        self.set_interval(2, self.load_trains)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        rid = event.row_key.value
        self.push_screen(StopsScreen(self.trains[rid], self.db))

    def key_c(self):
        table = self.query_one(DataTable)
        table.cursor_type = next(cursors)

if __name__ == "__main__":
    app = TrainSearchApp()
    app.run()
