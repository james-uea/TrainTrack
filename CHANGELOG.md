# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased
### Changed
- Passing points Darwin reports that aren't in a train's schedule are stored as extra stops (`train_stops.added_from_status`, migration `003`), and counted as `added_locations` in the consumer's stats
- At a TIPLOC a train visits more than once, a location whose working time doesn't match any visit exactly matches the nearest one within 5 minutes

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
