# Milestone 2 data spike (21 Nov 2026)

Measured against the Darwin timetable of 21 Nov 2026 (52,390 journeys, 4,794 TIPLOCs).

| Check | Result |
| --- | --- |
| TIPLOCs with BPLAN coordinates (PIF20261120571120089) | 3,790 / 4,794 (79%), 86% of train-stops |
| Calls covered / passes covered | 88.6% / 82.2% of occurrences |
| BPLAN point to nearest Track Model track | median 32 m, p90 438 m, p95 1.6 km |
| BPLAN points used today > 2 km from track (wrong) | 172 (e.g. STPANCI 236 km, GLGCBSJ 218 km) |
| Call-to-call segments with both ends within 500 m of track | 80.8% (82.4% passenger) |
| Journeys with every call placed | 52.7% |
| TPNM coordinates | none usable (station easting/northing all 0; node netx/nety schematic) |
| Track Model 2026-10-26 | 49,731 centreline links, 38,689 nodes, EPSG:27700, NR track only |

BPLAN LOC fields: [6] easting, [7] northing; 0 or 999999 means missing.

Biggest gaps: Elizabeth line core (PADTLL, BONDST, TOTCTRD, FRNDXR, LIVSTLL, WCHAPXR), East London line
(DALS, HAGGERS, HOXTON, SHRDHST, WCHAPEL, SHADWEL, WAPPING, RTHERHI, CNDAW, SURREYQ), London junctions
(WATRLWC, PRTOBJP, ROYAOJN, KNGXBEL, CMDNSTH, LNDNASJ), LEEDSWJ.

Decision: BPLAN for non-station points, NaPTAN (DfT, OGL) for stations, Track Model for geometry.
Points > 500 m from track are suspect; non-NR lines get straight-line segments.
Scripts: spike.py, spike2.py (inputs: BPLAN PIF, Darwin v8 + ref_v4 timetable, Track Model shapefile).

## With NaPTAN (data/naptan/Stops.csv, rail stops = StopType RLY, ATCOCode 9100+TIPLOC)

| Check | Result |
| --- | --- |
| NaPTAN rail stops | 2,716 (2,671 active); 2,636 TIPLOCs used today |
| NaPTAN point to track | median 8.4 m, p90 28 m, p99 102 m |
| NaPTAN vs BPLAN for same TIPLOC | median 65 m, p90 336 m |
| Calls placed (NaPTAN first, then BPLAN within 500 m of track) | 95.3% |
| Call-to-call segments placed | 93.9% all, 96.0% passenger |
| Journeys with every call placed | 77.7% |

Remaining misses: Tyne & Wear Metro (STDI, SGOS, FELL...), airport buses (HTRBUS*, EDINAIR), HIGHBYE, CNNBELL, WBRNPKS.
Script: spike_naptan.py.

## Matching TS locations to stops (passing points)

Positions come from TS location updates, so every one that fails to match a stop is a lost position.
In the PR #2 live test 92.1% matched; 99.4% of the misses were passes, either TIPLOCs Darwin reports
that aren't in the train's schedule, or TIPLOCs the train passes more than once where Darwin's working
pass time differs from every planned one.

Changes (branch `milestone-2-positions`):

- At a TIPLOC the train visits more than once with no exact time match, take the visit whose working
  time is nearest, within 5 minutes (`MATCH_TOLERANCE`). A tie, or nothing within 5 minutes, stays unmatched.
- A pass at a TIPLOC that isn't in the schedule at all is stored as a new `PP` stop, placed by its
  working pass time, with `train_stops.added_from_status = TRUE` (migration 003). Later stops shift
  along one sequence number. Passes before the origin or after the destination aren't stored.
- The consumer's stats line gains `added_locations`; `unmatched_locations` still counts the rest.

Replay of `data/recorded-2026-11-21*.jsonl` against the 21 Nov timetable (throwaway DB):

| | Locations matched | Unmatched | Added as new stops |
| --- | --- | --- | --- |
| Before (3a1e5f4) | 92.00% | 28,040 | n/a |
| After | **99.96%** | 147 | 4,832 |

100,963 messages; 350,512 TS locations for known trains; 131 statuses for unknown trains in both runs.
Each replay took ~135 s. After the replay, 3,315 added stops remained on 731 trains (later schedule
messages replace some: when a schedule lists the point, its live data carries over and the flag clears).
1,739 of them have an actual pass time. All added stops sit in working-time order: across the 29,067 stops
of those trains, no working time goes backwards.

The misses at TIPLOCs already stored come from real loops. 11,973 (rid, TIPLOC) pairs occur twice in a
day, e.g. Merseyrail's Wirral loop passes HAMTSQ and JAMESST twice per trip.

Known gap: re-running `initialise.py` mid-day upserts on `(rid, sequence)`, so a train whose stops were
shifted by an added pass (or by a schedule message) gets misaligned rows. The bug was already there with
schedule messages; added passes make it more frequent.
