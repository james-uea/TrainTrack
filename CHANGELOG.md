# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.8.0
Milestone 4: replay any day.

### Added
- Migration `008_partition_events_by_day.sql`: `darwin_events` is split into one partition per UK day (`darwin_events_YYYYMMDD`), with `darwin_events_default` catching rows for a day with no partition yet. The SQL function `ensure_day_partition(parent, key_column, day)` makes a day's partition, moving its rows out of the default one
- `retention.py`: makes partitions a week ahead, writes raw events older than `EVENTS_KEEP_DAYS` (default 14) to `ARCHIVE_DIR` (default `data/archive`) as `darwin_events-YYYY-MM-DD.jsonl.gz`, then drops their partition; drops recorded frames older than `FRAMES_KEEP_DAYS` (default 0, kept forever). `--dry-run` says what it would do. The timetable service runs it after each daily load, and the consumer makes today's partition on start
- Migration `009_position_frames.sql`: the `position_frames` table, partitioned by UK day, holds what the map showed at each tick: a keyframe of every placed train every 5 minutes and at the start of each run, and only what changed in between, gzipped
- `recorder.py`: ticks the live positions every 5 s and stores a frame each time. Runs as the `recorder` service in Compose. `--backfill FROM TO` computes frames for a past window from the database as it is now, marked `computed`; it won't touch recorded frames, and `--replace` recomputes computed ones
- `frames.py`: the snapshot and changes wire format, shared by the API and the recorder (moved from `api.py`), and rebuilding any moment from stored frames
- `GET /api/replay?start=&end=`: stored frames for up to 15 minutes, starting from the keyframe at or before `start`. `GET /api/replay/days` lists the UK days with frames and how many minutes were recorded or computed; `GET /api/replay/runs?day=` gives the unbroken stretches on one day
- `GET /api/trains/{rid}?at=`: a train as it stood at a moment, without actual times after it and with the position the map showed
- The map's timeline: Live, play and pause, 1×, 10× and 60×, a day picker, and a slider across the UK day shaded where frames are stored (darker for recorded, lighter for computed). Replay fetches frames in chunks ahead of the playhead and moves trains between them as live does; where nothing is stored, it shows positions computed by the server, marked "not recorded"
- Shareable links: the address keeps the moment (`?at=`), speed (`speed=`), pause (`paused=1`), selected train and map view (`#map=zoom/lat/lon`), and "Copy link" copies it
- `pnpm test:e2e` also opens a replay link, pauses, changes speed and goes back to live. It needs frames for 21 Nov (`recorder.py --backfill 2026-11-21T13:50Z 2026-11-21T14:51Z`)

### Changed
- `GET /api/positions?at=` rebuilds the moment from stored frames when they cover it, and only otherwise computes it from the database as it is now
- `?at=` on the map plays stored frames instead of asking for computed positions every 5 seconds

## 0.7.0
Milestone 3: the live map.

### Added
- `live.py`: keeps every train around the current moment in memory and estimates all positions on each tick, reloading only trains whose `updated_at` changed. Its clock runs live, frozen at a past moment (`fixed:`) or replaying the past (`replay:`); `--bench N` times N ticks
- `api.py`: a FastAPI service with `GET /api/positions` (every placed train), `GET /api/trains/{rid}` (stops, times, platforms, reasons, route and position) and `GET /api/health`. Responses over 1 KB are gzipped. Runs as the `api` service in Compose on port 8000; `MAP_CLOCK` in `.env` sets its clock
- `GET /api/stream`: positions as server-sent events, one per tick. The first is a `snapshot` of every train; after that each `changes` event lists only new or changed trains and those removed. `?since=<version>` (from `/api/positions`) or the browser's `Last-Event-ID` skips the snapshot
- `web/`: the map's front end in TypeScript (Vite, React), built with pnpm. Its API types are generated from FastAPI's OpenAPI schema (`pnpm gen:api`, via `api_schema.py`); a test fails if `web/openapi.json` is out of date. The API serves the built page from `web/dist`, and the Docker image builds it in a Node stage
- `GET /api/segments?pairs=FROM>TO`: the track path between pairs of stops, simplified, for drawing trains along it
- The map page: every placed train on an OpenFreeMap basemap, coloured by delay, moving smoothly along the track between server ticks and shown as arrows pointing the way it's going from zoom 9. Hovering a train shows its headcode, operator and delay; a status bar shows the clock and how many trains are placed
- `GET /tiles/track/{z}/{x}/{y}.pbf`: the Track Model's lines as vector tiles (zoom 5–14), built on request with PostGIS (`Database.fetch_track_tile`) and kept in memory. The map draws them under the trains
- The train panel: click a train for its headcode, operator, origin and destination, how late it is and why, and its stations with planned, expected and actual times and platforms, marking where the train is now. Passing points and operational stops are behind a toggle. The train's route is drawn on the map, the selected train is ringed, and `?train=<rid>` in the address opens it directly
- Each stop in `GET /api/trains/{rid}` says whether it's `public`: an origin, calling point or destination passengers can use, as opposed to an operational stop or a passing point
- Search (press `/` or Ctrl/Cmd+K): stations by name or CRS code fly the map there; operators show only their trains (cleared from the legend); trains by headcode open in the panel
- `GET /api/operators`: operators that run trains in the timetable, by code, for search
- `?at=<ISO time>` on the map replays the past from that moment at 1x, whatever the API's own clock is. `GET /api/positions?at=` gives positions at any moment, from a second in-memory set of journeys kept for it
- `GET /api/stations`: every station trains call at publicly, one per CRS code, with its location (`Database.fetch_stations`)
- The legend's delay bands are switches that hide or show those trains, and "Late trains only" hides trains that are on time or haven't reported
- `?bench=1` on the map measures 60 s of frames and React renders; `pnpm bench` runs it in headless Chrome, with `--throttle 4` to slow the CPU and `?renderer=geojson` to compare deck.gl with a MapLibre GeoJSON source
- Dependencies: `fastapi`, `uvicorn[standard]`; `httpx2` for tests. Front end: React, MapLibre GL (`react-map-gl`), deck.gl (with `@deck.gl/extensions`), TanStack Query, Zustand, `openapi-fetch`, `cmdk`, `cheap-ruler`; Vite, TypeScript 6, Vitest, Biome, `openapi-typescript`, Playwright
- `pnpm test:e2e`: a Playwright smoke test that starts its own API on a replay clock and Vite, waits for trains to be placed and the clock to move, finds a train with search and opens its panel, and fails on any console error
- The map page has a favicon

### Changed
- A train is held short of a call that hasn't reported only if it's at least 3 minutes late (`positions.HOLD_MIN_DELAY`); an on-time train runs on through, since it has most likely called and the report is late. Held trains more than 1 km from where they turned out to be fell from 13 to 2 on 21 Nov 14:05–14:51
- `accuracy_check.py --hold-min-delay` compares settings
- The README covers PostGIS, the Track Model and locations, the API and the map
- Positions carry `left` and `due`: when the train left the stop it's coming from and is expected at the next, so a client can work out its progress itself
- Every applied train status update now sets `train_journeys.updated_at`, not only one with a new actual time, so forecast changes can be picked up

### Fixed
- Seven junctions and tunnel ends now have overrides in `reference/tiploc_overrides.csv`: Leeds West Jn, Portobello Jn (Paddington), Glasgow Central Bridge St Jn, Surrey Quays Jn and Waterloo West Crossings had no usable BPLAN point, and BPLAN put both Severn Tunnel portals near Severn Tunnel Junction, so trains between Pilning and the tunnel zigzagged and were drawn up to 11 km short

## 0.6.0
Milestone 2: train positions on the real track.

### Added
- PostGIS. The database image is built from `postgres:18` with PostGIS (`docker/db/Dockerfile`), because `postgis/postgis` has no arm64 build
- `tiploc_locations` (migration `004`): a point for each TIPLOC from NaPTAN, then BPLAN, then hand fixes in `reference/tiploc_overrides.csv`, loaded by `tiploc_locations.py`
- `coverage_report.py`: how many of a day's stops can be placed on the map, and the biggest gaps
- `track_links` (migration `005`): Network Rail Track Model centrelines, loaded by `track_model.py`, with a routable graph of the track (`track_graph.py`)
- TIPLOC locations are snapped to the track and graded `good`, `off_network` or `suspect` (migration `006`). BPLAN points that trains would have to reach impossibly fast are marked `suspect`
- `segment_paths` (migration `007`): a path along the track for each pair of consecutive stops in the day's timetable, or a straight line when there isn't a sensible one. `initialise.py` routes new pairs after each timetable load
- `positions.py`: where each running train is at a given moment (now or a replayed time), along its track path. Gives a state (`running`, `dwelling`, `held`, `not_started`, `terminated`), bearing, delay and confidence, with optional GeoJSON output. A train due at a call that hasn't reported is held there for up to 3 minutes
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
- BPLAN has no usable point for the East London line platforms at Highbury & Islington and Canonbury; they now have overrides

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
