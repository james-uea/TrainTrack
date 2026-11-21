# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## 0.6.0
Milestone 2: train positions on the real track.

### Added
- PostGIS. The database image is built from `postgres:18` with PostGIS (`docker/db/Dockerfile`), because `postgis/postgis` has no arm64 build
- `tiploc_locations` (migration `004`): a point for each TIPLOC from NaPTAN, then BPLAN, then hand fixes in `reference/tiploc_overrides.csv`, loaded by `tiploc_locations.py`
- `coverage_report.py`: how many of a day's stops can be placed on the map, and the biggest gaps
- `track_links` (migration `005`): Network Rail Track Model centrelines, loaded by `track_model.py`, with a routable graph of the track (`track_graph.py`)
- TIPLOC locations are snapped to the track and graded `good`, `off_network` or `suspect` (migration `006`). BPLAN points that trains would have to reach impossibly fast are marked `suspect`
- `segment_paths` (migration `007`): a path along the track for each pair of consecutive stops in the day's timetable, or a straight line when there isn't a sensible one. `initialise.py` routes new pairs after each timetable load
- `positions.py`: where each running train is at a given moment (now or a replayed time), along its track path. Gives a state (`running`, `dwelling`, `held`, `not_started`, `terminated`), bearing, delay and confidence, with optional GeoJSON output
- `docs/spikes/accuracy_check.py`: measures the position estimator against the actual reports in the database
- Dependencies: `networkx`, `pyproj`, `pyshp`, `shapely`

### Changed
- Passing points Darwin reports that aren't in a train's schedule are stored as extra stops (`train_stops.added_from_status`, migration `003`), and counted as `added_locations` in the consumer's stats
- At a TIPLOC a train visits more than once, a location whose working time doesn't match any visit exactly matches the nearest one within 5 minutes. A TIPLOC visited once matches only within 15 minutes; a pass further out is stored as an extra stop
- Reloading the timetable replaces a journey's stops and carries live data over by TIPLOC and working times, as schedule messages do
- Reloading TIPLOC locations drops the segment paths of any TIPLOC that moved, so they are routed again

### Fixed
- Reloading the timetable after schedule messages had renumbered a journey's stops left stale stops after its destination
- A report at a TIPLOC visited once was matched to that visit whatever its time (e.g. the outbound pass on a loop landed on the return call)
- Turnham Green was placed at Barking (BPLAN); it now uses NaPTAN's point

## 0.5.0
### Added
- `darwin_events`: an append-only log of every Push Port message, the base for history and replay
- The consumer now handles `schedule` messages (trains added or changed during the day) and `deactivated` messages
- Forecast times, platform confirmation/suppression and late reasons from train status messages
- `train_journeys` now tracks the last reported location, report type, time and delay
- `consumer.py --record FILE` to save raw messages
- `initialise.py --daily HH:MM` to reload the timetable every day
- `initialise.py` reads gzipped timetable downloads (`.xml.gz`) directly
- Docker Compose services for the consumer and the daily timetable load
- Tests (pytest), including database tests against a throwaway Postgres

### Changed
- All stop times are now full timestamps (`TIMESTAMPTZ`), so trains running past midnight have the right dates. Migration `002` converts existing data
- Status updates are matched to stops in Python by TIPLOC and working times; unmatched locations are counted and logged
- The terminal app shows origin, destination, last seen location and delay, with station names
- Settings come from `.env` or environment variables, including `KAFKA_TOPIC` (previously hard-coded)
- Logging instead of `print`
- `initialise.py` streams journeys from the timetable and writes them in batches of 5,000, instead of loading the whole file (peak memory was ~2.5 GB)

### Fixed
- Darwin's lowercase `true` was read as false, so cancelled stops in the timetable were never marked cancelled

## 0.4.1
### Changed
- Updated the README with a more detailed setup and requirements list + a mermaid diagram of the project

### Fixed
- Bug and typo fixes

## 0.4.0
### Changed
- `initialise.py` now reads the latest timetable files

## 0.3.1
### Changed
- `db.py:fetch_train_stops` now orders by sequence to ensure stops are in the right order
- `last_reported_at` in the table `train_journeys` now only updates when something actually changed

## 0.3.0
### Added
- A CLI for viewing train journey data

## 0.2.1
### Changed
- `db.py` now rolls back on all psycopg errors instead of just data error

## 0.2.0
### Added
- Consumer now updates the train stops table with live train statuses (Arrival, Departure and Pass times)
- Train statuses are parsed into `darwin.py` dataclasses

### Changed
- `db.py` inserts now commit after each batch

## 0.1.1
### Changed
- `db.py` now uses executemany instead of execute for inserts

## 0.1.0
### Added
- Initial train status populator
- Docker compose for postgres and adminer
- Database migration script
