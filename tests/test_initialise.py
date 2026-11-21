import gzip
import os
import subprocess
import sys
import textwrap

from initialise import batched, get_latest, iter_journeys

TIMETABLE = """<?xml version="1.0" encoding="utf-8"?>
<PportTimetable timetableID="20261121020530" xmlns="http://www.thalesgroup.com/rtti/XmlTimetable/v8">
<Journey rid="202611218000001" uid="W00001" trainId="2X99" ssd="2026-11-21" toc="LO" trainCat="OO">
<OR tpl="AAA" act="TB" ptd="23:40" wtd="23:40"/>
<PP tpl="BBB" wtp="23:50"/>
<IP tpl="CCC" act="T " pta="23:58" ptd="23:59" wta="23:58" wtd="23:59" can="true"/>
<DT tpl="FFF" act="TF" pta="00:40" wta="00:40"/>
</Journey>
<Association tiploc="CCC" category="JJ"><main rid="202611218000001"/><assoc rid="202611218000002"/></Association>
<Journey rid="202611218000002" uid="W00002" trainId="2X98" ssd="2026-11-21" toc="LO" can="true">
<OR tpl="AAA" ptd="10:00" wtd="10:00"/><DT tpl="CCC" pta="10:20" wta="10:20"/><cancelReason>100</cancelReason>
</Journey>
</PportTimetable>
"""


def test_get_latest_finds_gzipped_downloads(tmp_path):
    for name in ("PPTimetable_20261120020000_v8.xml", "PPTimetable_20261121020530_v8.xml.gz",
                 "PPTimetable_20261121020530_ref_v4.xml.gz", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    assert get_latest(str(tmp_path)) == str(tmp_path / "PPTimetable_20261121020530_v8.xml.gz")
    assert get_latest(str(tmp_path), ref=True) == str(tmp_path / "PPTimetable_20261121020530_ref_v4.xml.gz")


def test_iter_journeys_streams_plain_and_gzipped_files(tmp_path):
    plain = tmp_path / "PPTimetable_20261121020530_v8.xml"
    plain.write_text(TIMETABLE)
    zipped = tmp_path / "PPTimetable_20261121020530_v8.xml.gz"
    zipped.write_bytes(gzip.compress(TIMETABLE.encode()))

    for path in (plain, zipped):
        first, second = iter_journeys(str(path))
        assert [stop.tiploc for stop in first.stops] == ["AAA", "BBB", "CCC", "FFF"]
        assert first.stops[2].cancelled is True
        assert (second.rid, second.cancelled, second.cancel_reason) == ("202611218000002", True, 100)


def test_batched():
    assert list(batched(range(5), 2)) == [[0, 1], [2, 3], [4]]


def test_streaming_memory_stays_flat(tmp_path):
    """Parse a ~60 MB timetable in a child process and check peak memory is far below the file size."""
    path = tmp_path / "PPTimetable_20261121020530_v8.xml.gz"
    stop = '<IP tpl="CCC" act="T " pta="10:58" ptd="10:59" wta="10:58" wtd="10:59" plat="2"/>'
    with gzip.open(path, "wt") as f:
        f.write('<?xml version="1.0"?><PportTimetable xmlns="http://www.thalesgroup.com/rtti/XmlTimetable/v8">')
        for i in range(40000):
            f.write(f'<Journey rid="2026112180{i:05d}" uid="W{i:05d}" trainId="2X99" ssd="2026-11-21" toc="LO">'
                    f'<OR tpl="AAA" ptd="10:00" wtd="10:00"/>{stop * 12}<DT tpl="FFF" pta="11:40" wta="11:40"/></Journey>')
        f.write("</PportTimetable>")

    script = textwrap.dedent(f"""
        import resource, sys
        sys.path.insert(0, {os.path.join(os.path.dirname(__file__), "..", "src")!r})
        from initialise import iter_journeys
        count = sum(1 for _ in iter_journeys({str(path)!r}))
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print(count, peak if sys.platform == "darwin" else peak * 1024)
    """)
    count, peak_bytes = map(int, subprocess.check_output([sys.executable, "-c", script]).split())
    assert count == 40000
    # The uncompressed XML is ~60 MB and a full lxml tree of it is several times that
    assert peak_bytes < 120 * 1024 * 1024, f"peak RSS {peak_bytes / 1e6:.0f} MB"
