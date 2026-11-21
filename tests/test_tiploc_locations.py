import gzip
import os
from datetime import date

import pytest

from tiploc_locations import (
    GridPoint,
    bplan_validity,
    combine,
    load,
    pick_bplan,
    read_bplan,
    read_naptan,
    read_overrides,
    to_wgs84,
)

NAPTAN_HEADER = "ATCOCode,CommonName,Easting,Northing,StopType,Status\n"

# Real rows (trimmed to the columns used), from NaPTAN's Stops.csv and BPLAN PIF20261120571120089
NAPTAN_ROWS = [
    "9100NRCH,Norwich Rail Station,623866,308367,RLY,active\n",
    "9100STPANCI,St Pancras International Rail Station,530020,183176,RLY,inactive\n",
    "2900NRCH0,Norwich Rail Station,623866,308367,RSE,active\n",  # an entrance, not the station
    "9100AVIEMRE,Aviemore Rail Station,289566,812339,RLY,active\n",
]
BPLAN_LINES = [
    "PIF\t1\tCENTRE\tNR\t17-05-2026 00:00:00\t12-12-2026 23:59:59\tI\tD\t20-11-2026 19:00:00\t1\r\n",
    "LOC\tA\tNRCH\tNorwich\t01-01-1995 00:00:00\t\t623900\t308400\tT\t3\t48231\tN\tB\r\n",
    "LOC\tA\tSTPANCI\tSt. Pancras International\t01-01-1995 00:00:00\t\t666666\t666666\tM\t3\t63631\tN\t \r\n",
    "LOC\tA\tAACHEN\tAachen\t01-01-1995 00:00:00\t\t848093\t121300\tO\t3\t00005\tN\t \r\n",
    "LOC\tA\tABARASQ\tAberaeron Alban Square\t11-12-2022 00:00:00\t\t0\t0\tO\t4\t\tN\t \r\n",
    "LOC\tA\tAVIEMRE\tAviemore\t01-01-1995 00:00:00\t\t285600\t812400\tT\t3\t\tN\t \r\n",
    "LOC\tA\tWVCTJN\tWolvercot Junction\t01-01-1995 00:00:00\t\t449100\t210100\tJ\t3\t\tN\t \r\n",
    "NWK\tA\tNRCH\tTHRPJN\t...\r\n",
]


def test_converts_the_british_grid_to_lat_lon():
    lon, lat = to_wgs84(623900, 308400)  # Norwich in BPLAN
    assert lat == pytest.approx(52.627, abs=0.001)
    assert lon == pytest.approx(1.307, abs=0.001)


def test_reads_naptan_rail_stations():
    stations = read_naptan([NAPTAN_HEADER, *NAPTAN_ROWS])
    assert set(stations) == {"NRCH", "STPANCI", "AVIEMRE"}
    assert stations["NRCH"] == GridPoint("NRCH", "Norwich Rail Station", 623866, 308367)


def test_naptan_prefers_an_active_stop():
    stations = read_naptan([
        NAPTAN_HEADER,
        "9100XYZ,Old,600000,300000,RLY,active\n",
        "9100XYZ,Closed,600500,300500,RLY,inactive\n",
    ])
    assert stations["XYZ"].name == "Old"


def test_reads_bplan_and_drops_missing_coordinates():
    points = read_bplan(BPLAN_LINES)
    # STPANCI (666666 placeholder), AACHEN (off the grid) and ABARASQ (0) have no usable point
    assert set(points) == {"NRCH", "AVIEMRE", "WVCTJN"}
    assert points["NRCH"] == GridPoint("NRCH", "Norwich", 623900, 308400)
    assert bplan_validity(BPLAN_LINES[0]) == (date(2026, 5, 17), date(2026, 12, 12))


def test_picks_the_bplan_file_valid_today(tmp_path):
    for name, start, end in [
        ("PIF20261120571120089.txt.gz", "17-05-2026", "12-12-2026"),
        ("PIF20261120581120051.txt.gz", "13-12-2026", "15-05-2027"),
    ]:
        with gzip.open(tmp_path / name, "wt", encoding="latin-1") as f:
            f.write(f"PIF\t1\tCENTRE\tNR\t{start} 00:00:00\t{end} 23:59:59\tI\tD\t20-11-2026 19:00:00\t1\r\n")

    assert os.path.basename(pick_bplan(str(tmp_path), date(2026, 11, 21))) == "PIF20261120571120089.txt.gz"
    assert os.path.basename(pick_bplan(str(tmp_path), date(2026, 12, 13))) == "PIF20261120581120051.txt.gz"
    assert pick_bplan(str(tmp_path), date(2028, 1, 1)) is None


def test_precedence_and_suspect_points():
    naptan = read_naptan([NAPTAN_HEADER, *NAPTAN_ROWS])
    bplan = read_bplan(BPLAN_LINES)
    overrides = read_overrides(["tiploc,lat,lon,note\n", "WVCTJN,51.78,-1.28,moved by hand\n"])

    rows = {row.tiploc: row for row in combine(naptan, bplan, overrides)}

    assert (rows["NRCH"].source, rows["NRCH"].quality, rows["NRCH"].easting) == ("naptan", "good", 623866)
    assert rows["NRCH"].name == "Norwich"  # BPLAN's name, without "Rail Station"
    assert (rows["STPANCI"].source, rows["STPANCI"].quality) == ("naptan", "good")
    # BPLAN puts Aviemore ~4 km from NaPTAN
    assert (rows["AVIEMRE"].source, rows["AVIEMRE"].quality) == ("naptan", "suspect")
    wolvercot = rows["WVCTJN"]
    assert (wolvercot.source, wolvercot.lat, wolvercot.lon, wolvercot.easting) == ("override", 51.78, -1.28, None)


def test_load_upserts(db, tmp_path):
    (tmp_path / "naptan").mkdir()
    (tmp_path / "naptan" / "Stops.csv").write_text(NAPTAN_HEADER + "".join(NAPTAN_ROWS))
    (tmp_path / "bplan").mkdir()
    with gzip.open(tmp_path / "bplan" / "PIF20261120571120089.txt.gz", "wt", encoding="latin-1") as f:
        f.writelines(BPLAN_LINES)
    overrides = tmp_path / "overrides.csv"
    overrides.write_text("tiploc,lat,lon,note\n")

    counts = load(db, str(tmp_path), str(overrides), today=date(2026, 11, 21))
    assert counts == {("naptan", "good"): 2, ("naptan", "suspect"): 1, ("bplan", "good"): 1}

    db.cur.execute("SELECT ST_Y(geom), ST_X(geom) FROM tiploc_locations WHERE tiploc = 'NRCH'")
    assert db.cur.fetchone() == (pytest.approx(52.627, abs=0.001), pytest.approx(1.307, abs=0.001))

    # Reloading with an override replaces the point; a TIPLOC no source has any more is removed
    overrides.write_text("tiploc,lat,lon,note\nNRCH,52.6,1.3,test\n")
    (tmp_path / "naptan" / "Stops.csv").write_text(NAPTAN_HEADER + NAPTAN_ROWS[0])
    load(db, str(tmp_path), str(overrides), today=date(2026, 11, 21))

    db.cur.execute("SELECT tiploc, source, ST_Y(geom), easting FROM tiploc_locations ORDER BY tiploc")
    assert db.cur.fetchall() == [("AVIEMRE", "bplan", pytest.approx(57.19, abs=0.01), 285600),
                                 ("NRCH", "override", 52.6, None), ("WVCTJN", "bplan", pytest.approx(51.79, abs=0.01), 449100)]
