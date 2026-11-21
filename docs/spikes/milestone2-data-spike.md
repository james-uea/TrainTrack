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

## Accuracy check (stage 7)

`accuracy_check.py` takes every actual arrival or pass reported at a placed stop B between 14:05 and 14:51 UTC
on 21 Nov. For each one it estimates the train's position one second before the report, so the estimator
can't see it, and measures the distance along the journey's track paths from the estimate to B. Negative
means the estimate is behind the train. Time error is the estimator's predicted arrival at B minus the
report. This checks the estimator against our own data. It isn't ground truth: Darwin's actuals are to the
minute and come from TD berth steps.

```
PYTHONPATH=src uv run docs/spikes/accuracy_check.py --start 2026-11-21T14:05:00+00:00 --end 2026-11-21T14:51:00+00:00
```

Run on `traintrack_test` after a clean replay of the day's recordings with the two fixes below, and with
TIPLOC locations, the track model and segment paths reloaded. 17,234 reports were measured. Skipped: 1,729
because B has no location, and 81 because the train had no position.

| | n | median | p90 | p95 | signed median | time error median / \|p90\| |
|---|---:|---:|---:|---:|---:|---:|
| all | 17,234 | 34 m | 1,386 m | 1,922 m | −24 m | 0 s / 60 s |
| high confidence | 15,418 | 34 m | 1,347 m | 1,837 m | −24 m | 0 s / 60 s |
| medium | 1,508 | 31 m | 1,798 m | 2,569 m | −23 m | 0 s / 120 s |
| low | 308 | 448 m | 3,061 m | 11,948 m | −143 m | 0 s / 180 s |
| calls | 9,791 | 24 m | 1,233 m | 1,671 m | −24 m | 0 s / 120 s |
| passes | 7,443 | 42 m | 1,617 m | 2,233 m | −24 m | 0 s / 60 s |

By state: running 16,077 (median 38 m, p95 1,888 m); held 998 (median 0, p95 3,948 m); dwelling 122
(median 980 m, mostly behind: no departure report yet when the train was already arriving at B).

- The p90 of about 1.4 km matches the time error. Reports are to the minute, so a train doing 25 m/s can be a minute,
  or 1.5 km, from where the timetable-plus-delay says. Confidence separates the tails as intended: low has a
  p95 six times high's.
- **Worst offenders now:** trains held short of a call that never reports. There were 75 held estimates more
  than 1 km out, and 72 of those were held at a call with no report anywhere in the recording. Examples:
  - Far North line request stops: 2H62 held at Kinbrace for 46 min while it was really reaching Brora, 44.6 km on.
  - The Kyle line, the Cumbrian Coast, Gretna Green to Annan, Sleaford to Boston.
  
  Holding is the safe choice when a train might really be stopped, but where a call has no TD coverage it pins
  the train until the next report.
- 2O06 (Upminster to Richmond via Turnham Green): the BPLAN point for TRNHMGN is at Barking (lon 0.111).
  The speed check misses it because the Upminster leg is 75 min long, so only one side looks
  impossible. An override in `reference/tiploc_overrides.csv` would fix it. The check could also flag
  one-sided jumps, at some risk of flagging good neighbours of a bad point.

**Two data bugs found and fixed.** The first run, on `nationalrail` with the data as the consumer had stored
it, gave the same median (34 m) and p90 (1,407 m) but a long tail of 25–70 km errors:
- **Stale stops after the destination.** The timetable reload at 14:44 upserted on (rid, sequence) after
  schedule messages and added passes had renumbered stops. 9J29 kept Gatwick, Three Bridges and Faygate after
  its destination Horsham, and 1P24 had duplicate rows. Reloading now replaces a journey's stops and carries
  live data over by TIPLOC and working times, as schedule messages do (fddb98d). Darwin-added passes are
  dropped on reload and come back with the next TS for them.
- **The only visit matched any report.** match_location returned a TIPLOC's single visit whatever the time.
  On loops (2K35/2K37 round Kingston), the outbound pass at Queens Road Battersea (14:33) set the actual on the
  15:39 return call, and the estimator put the train on the return leg. Of single-visit matches in the replay:
  - 367 within 5 min
  - 31 within 15 min
  - 0 between 30 and 60 min
  - 19 over an hour, all wrong-leg matches at QTRDBAT

  The only visit now matches within 15 min. A pass further from every visit is stored as a Darwin-added pass
  (f0b235a). The replay stays at 99.96% matched (147 unmatched), with 4,840 added passes (+8).

**Test gaps found and filled:**
- A reload after renumbering.
- A report far from a TIPLOC's only visit (pass added, close call matched, far call unmatched).
- The estimator on a journey that reverses and runs back through the same TIPLOC.

The script's own reversal handling was wrong at first. It took the visit nearest B, which put 1R70 on the
far side of Sheffield. It now takes the visit heading for the estimate's to_tiploc.

### Loose ends fixed: unreported calls and Turnham Green

**Holding a train at an unreported call.** A train due at a call that hasn't reported is now held there for
at most 3 minutes after it was due. After that it runs on through the call on forecast or planned times
(`HOLD_LIMIT` in `positions.py`). I considered a list of calls that never report, learned from the data, but
it would need new state and would go stale. The time limit handles request stops and lines without train
describer coverage without knowing which ones they are, and a train that is really stopped still shows as
held for the first few minutes. Choosing the limit (same check, same window, `--hold-minutes`):

| hold limit | median | p90 | p95 | low-confidence p95 | reports > 1 km out (trains) | held > 1 km out |
|---|---:|---:|---:|---:|---:|---:|
| none (before) | 34 m | 1,384 m | 1,919 m | 11,006 m | 2,843 (1,284) | 75 |
| 10 min | 34 m | 1,378 m | 1,898 m | 2,954 m | 2,828 (1,274) | 58 |
| 5 min | 34 m | 1,366 m | 1,867 m | 1,848 m | 2,804 (1,265) | 27 |
| **3 min** | 34 m | 1,361 m | 1,855 m | 1,848 m | 2,791 (1,256) | 11 |

A shorter limit would show a train running past a call before it really got there, which the check
counts as a positive error at that call. 3 minutes still came out best on every measure. At 14:45, 2,247 of
2,279 active trains (98.6%) are positioned, the same as before. Held trains fell from 134 to 96.

**Turnham Green.** I added an override from NaPTAN's point for the Underground station (9400ZZLUTNG).
The speed check missed the Barking point because trains reach Turnham Green from Upminster on a 75-minute
leg, so only the Richmond side looked impossible. Reloading locations also left the old paths in place, so
`add_tiploc_locations` now drops paths that touch a TIPLOC that moved, for `segment_paths.py` to route
again. On `nationalrail`, the 4 TRNHMGN paths were rerouted. TRNHMGN to GNRSBRY is now 659 m of track,
where it was 33 km.

**Worst offenders now** (worst is 11 km, down from 44.6 km):
- **Severn Tunnel:** 2U18 and 1F16 at Severn Tunnel Junction are estimated at Pilning, 11 km short.
- **Twyford:** five trains at TWYFORD are 7.2 km ahead, predicted 2 minutes before the report, which looks like
  late pass reports at that TIPLOC.
- **Beccles to Oulton Broad South:** 2D80 is still "dwelling" at Beccles with no departure report.
