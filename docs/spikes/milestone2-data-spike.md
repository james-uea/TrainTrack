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
