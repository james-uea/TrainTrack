-- Milestone 1 groundwork:
--   * an append-only log of every Push Port message (the source for replay and history)
--   * date-aware times on train stops (TIME -> TIMESTAMPTZ), so trains running past midnight work
--   * forecast times, platform confirmation and current position/delay fields

CREATE TABLE darwin_events (
    id BIGSERIAL PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    message_ts TIMESTAMPTZ, -- the Push Port `ts`
    push_port_sequence BIGINT,
    kinds TEXT[] NOT NULL DEFAULT '{}', -- update types in the message, e.g. {TS} or {schedule}
    rids TEXT[] NOT NULL DEFAULT '{}', -- trains the message refers to
    payload JSONB NOT NULL
);

CREATE INDEX darwin_events_received_at_idx ON darwin_events (received_at);
CREATE INDEX darwin_events_rids_idx ON darwin_events USING GIN (rids);

-- Convert a stop time into a timestamp. `day` is the scheduled start date plus any midnight rollovers
-- before this stop, `ref` is the stop's own working time. A time more than 12 hours away from `ref`
-- belongs to the neighbouring day.
CREATE FUNCTION pg_temp.stop_ts(day DATE, t TIME, ref TIME) RETURNS TIMESTAMPTZ AS $$
    SELECT CASE WHEN t IS NULL THEN NULL ELSE (
        (day + t + CASE
            WHEN ref IS NULL THEN INTERVAL '0'
            WHEN t - ref < INTERVAL '-12 hours' THEN INTERVAL '1 day'
            WHEN t - ref > INTERVAL '12 hours' THEN INTERVAL '-1 day'
            ELSE INTERVAL '0'
        END) AT TIME ZONE 'Europe/London'
    ) END
$$ LANGUAGE SQL IMMUTABLE;

ALTER TABLE train_stops ADD COLUMN migration_day DATE;

-- Count how many times the working time goes backwards by more than 6 hours (i.e. crosses midnight)
WITH ordered AS (
    SELECT s.rid, s.sequence, j.scheduled_start,
        COALESCE(s.working_departure, s.working_arrival, s.working_pass) AS wt,
        LAG(COALESCE(s.working_departure, s.working_arrival, s.working_pass))
            OVER (PARTITION BY s.rid ORDER BY s.sequence) AS prev_wt
    FROM train_stops s JOIN train_journeys j ON j.rid = s.rid
), offsets AS (
    SELECT rid, sequence, scheduled_start,
        SUM(CASE WHEN prev_wt IS NOT NULL AND wt - prev_wt < INTERVAL '-6 hours' THEN 1 ELSE 0 END)
            OVER (PARTITION BY rid ORDER BY sequence) AS day_offset
    FROM ordered
)
UPDATE train_stops s SET migration_day = o.scheduled_start + o.day_offset::INTEGER
FROM offsets o WHERE o.rid = s.rid AND o.sequence = s.sequence;

ALTER TABLE train_stops
    ALTER COLUMN public_arrival TYPE TIMESTAMPTZ
        USING pg_temp.stop_ts(migration_day, public_arrival, COALESCE(working_arrival, working_departure, working_pass)),
    ALTER COLUMN public_departure TYPE TIMESTAMPTZ
        USING pg_temp.stop_ts(migration_day, public_departure, COALESCE(working_departure, working_arrival, working_pass)),
    ALTER COLUMN working_arrival TYPE TIMESTAMPTZ
        USING pg_temp.stop_ts(migration_day, working_arrival, COALESCE(working_departure, working_arrival, working_pass)),
    ALTER COLUMN working_departure TYPE TIMESTAMPTZ
        USING pg_temp.stop_ts(migration_day, working_departure, COALESCE(working_departure, working_arrival, working_pass)),
    ALTER COLUMN working_pass TYPE TIMESTAMPTZ
        USING pg_temp.stop_ts(migration_day, working_pass, COALESCE(working_departure, working_arrival, working_pass)),
    ALTER COLUMN actual_arrival TYPE TIMESTAMPTZ
        USING pg_temp.stop_ts(migration_day, actual_arrival, COALESCE(working_arrival, working_departure, working_pass)),
    ALTER COLUMN actual_departure TYPE TIMESTAMPTZ
        USING pg_temp.stop_ts(migration_day, actual_departure, COALESCE(working_departure, working_arrival, working_pass)),
    ALTER COLUMN actual_pass TYPE TIMESTAMPTZ
        USING pg_temp.stop_ts(migration_day, actual_pass, COALESCE(working_pass, working_departure, working_arrival));

ALTER TABLE train_stops
    DROP COLUMN migration_day,
    ADD COLUMN estimated_arrival TIMESTAMPTZ,
    ADD COLUMN estimated_departure TIMESTAMPTZ,
    ADD COLUMN estimated_pass TIMESTAMPTZ,
    ADD COLUMN platform_confirmed BOOLEAN,
    ADD COLUMN platform_suppressed BOOLEAN;

ALTER TABLE train_journeys
    ADD COLUMN category VARCHAR(2),
    ADD COLUMN deactivated BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN late_reason SMALLINT, -- no FK: Darwin can send codes missing from the reference data
    ADD COLUMN delay_minutes INTEGER, -- at the last reported location; negative = early
    ADD COLUMN updated_at TIMESTAMPTZ;

COMMENT ON COLUMN train_journeys.last_reported_at IS 'Time of the latest actual arrival/departure/pass';
COMMENT ON COLUMN train_journeys.updated_at IS 'When TrainTrack last changed this train';

UPDATE train_journeys SET updated_at = last_reported_at WHERE last_reported_at IS NOT NULL;

CREATE INDEX train_journeys_updated_at_idx ON train_journeys (updated_at DESC NULLS LAST);
CREATE INDEX train_journeys_scheduled_start_idx ON train_journeys (scheduled_start);
