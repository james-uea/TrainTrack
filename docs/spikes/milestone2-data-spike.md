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

## TIPLOC coordinates loaded (stage 3)

`src/tiploc_locations.py` into `tiploc_locations` (PostGIS), 21 Nov 2026: 6,330 TIPLOCs, made up of
2,632 NaPTAN good, 84 NaPTAN suspect, 3,612 BPLAN and 2 overrides. Precedence is override > NaPTAN > BPLAN.
"Suspect" means BPLAN puts the TIPLOC more than 2 km from NaPTAN. Spot checks found BPLAN wrong
(AYLSPWY, BGLAN digit typos; Aviemore and Brora 3–4 km out). BPLAN placeholders 0/999999/666666 etc. count as missing.

Coverage of the 30,064 journeys scheduled on 21 Nov:

| Stops | Count | With a point |
| --- | --- | --- |
| Passenger calls (OR/IP/DT) | 274,304 | 97.5% |
| All calls incl. operational | 291,254 | 96.5% |
| Passing points | 203,865 | 83.2% |
| All stops | 495,119 | 91.0% |
| Distinct TIPLOCs | 4,671 | 82.2% |

Uncovered calls are mostly buses (EDINAIR, HTRBUS2/3/5, LUTOBUS, DUNT, SANWBUS, EMPKAIR), the Tyne & Wear
Metro and WBRNPKS. Uncovered passes are London and Leeds junctions with BPLAN placeholders (WATRLWC,
LEEDSWJ, PRTOBJP, SURRQSJ, KNGXBEL, ROYAOJN). BPLAN-only points aren't checked: GLGCBSJ lands in the
North Sea (lon 2.03), and the Track Model distance check in stage 5 should catch points like it.

## Track geometry and segment paths (stages 4–5)

Loaded in `nationalrail` on 21 Nov:

- **Track Model:** 49,731 centrelines in `track_links` (57 MB), loaded in ~3 s. Link ends coincide exactly with
  the 38,689 Track Model nodes; merging ends within 1 m gives 38,655. 129 connected components, the largest
  holding 98.4% of nodes.
- **Snapping** (`tiploc_locations`): within 500 m of track is good. A NaPTAN station further out is off_network
  (17, placed and joined by straight lines). A BPLAN point further out is suspect (1,011, mostly sidings
  and signals tens to hundreds of km out; GLGCBSJ is 218 km). Five more BPLAN points sit near the wrong
  track (HOLME and PBLJWM on Scottish lines) and are caught by a speed check: over 360 km/h both into and
  out of the point, more than 5 km each way.
- **Segment paths:** 9,781 distinct consecutive placed-stop pairs for 21 Nov. 98.7% routed on track,
  118 detours (track route > 3× straight; often genuine, e.g. the Carmarthen–Aberystwyth bus or the Looe
  branch reversal), 8 with no connecting track, 4 off_network. Track/straight ratio: median 1.03, p90 1.17,
  p99 2.08. ~11 s for every pair (graph build ~1 s); only new pairs on later runs. 8.8 MB.
- **Routing ends:** each end may snap to any track within 30 m of its nearest one. Without this, ends on
  opposite Up/Down lines went out to the next crossover and back; detours fell from 695 to 115.
- **Sanity checks:** Norwich–Diss 32.1 km on track (30.8 km straight), Euston–Watford Junction 28.0 km,
  Liverpool Street–Stratford 6.4 km, Waterloo–Clapham Junction 6.2 km.
- `segment_paths_sample.geojson` (20 paths, blue = track, red = straight fallback) can be opened in
  geojson.io.

Coverage now (usable = good or off_network): passenger calls 97.2%, all calls 95.9%, passes 77.2%, all stops
88.2%, call-to-call segments 94.6%. Passes dropped from 83% because suspect BPLAN points no longer count.

## Position estimator (stage 6)

`uv run src/positions.py --at 2026-11-21T14:45:00Z` against `nationalrail`. No consumer was running, so this
uses the live data recorded 13:48–14:51 UTC on 21 Nov.

- 2,284 active trains, **2,252 positioned (98.6%)**. The other 32 have no placeable stop (buses, Tyne & Wear Metro).
  Similar at 14:30 (98.7%) and 14:50 (98.6%).
- States: running 1,335, not_started 425 (no reports yet, due out within 15 min), dwelling 225, held 134,
  terminated 133.
- Confidence: high 1,288, medium 221, low 743. Of the low ones, 425 are not-started trains, ~270 have no
  reports yet, and ~40 have reports over 15 minutes old.
- Runtime: estimating 0.15 s for all trains. Loading takes 0.16 s for the 9,781 paths and 0.76 s for journeys
  and stops (two queries).
- At first, holding a train short of the next placed stop until it reported there held 236 trains, many of them a minute after
  a report, at passing points Darwin never reports (e.g. Heald Green South Jn). Only calls hold now.

`positions_sample.geojson` holds all 2,252 positions at 14:45 (green high, orange medium, red low).
