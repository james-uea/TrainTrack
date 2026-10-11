from itertools import cycle

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Static

from darwin import TrainStatus
from db import Database

cursors = cycle(["row", "column", "none"])


class StopsScreen(Screen):
    BINDINGS = [  # noqa: RUF012
        Binding(key="left", action="app.pop_screen", description="Go back"),
        Binding(key="escape", action="app.pop_screen", description="Go back"),
    ]

    def __init__(self, train: TrainStatus):
        super().__init__()
        self.train = train

    def compose(self) -> ComposeResult:
        yield Static(f"Train {self.train.rid} ({self.train.scheduled_start})")
        yield DataTable()
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = 'row'
        table.zebra_stripes = True
        table.add_columns('Sequence', 'Arrival', 'Departure', 'Ex At', 'Ex Dep', 'Ex Pass')

        for stop in self.train.locations:
            table.add_row(stop.sequence, stop.actual_arrival, stop.actual_departure, stop.working_arrival, stop.working_departure, stop.working_pass)

class JourneyTable(DataTable):
    BINDINGS = [Binding(key="right", action="select_cursor", description="Open Journey")]

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
            self.table.add_row(train.rid, train.uid, train.starts(), train.ends(), '', key=train.rid)

    def on_mount(self) -> None:
        ROWS = [  # noqa: RUF012
            ("RID", 'UID', "Starts", "Ends", "Last Tiploc")
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
        self.push_screen(StopsScreen(self.trains[rid]))

    def key_c(self):
        table = self.query_one(DataTable)
        table.cursor_type = next(cursors)

if __name__ == "__main__":
    app = TrainSearchApp()
    app.run()
