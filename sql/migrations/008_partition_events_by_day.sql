-- Milestone 4: the event log split into one partition per UK day, so expiring a day is a table drop.
-- Rows for a day with no partition yet land in darwin_events_default; ensure_day_partition moves them out.

-- Creates `<parent>_YYYYMMDD` for one UK day (midnight to midnight, Europe/London) if it doesn't exist, moving any
-- rows for that day out of `<parent>_default` first. Returns whether it made the partition.
CREATE FUNCTION ensure_day_partition(parent TEXT, key_column TEXT, day DATE) RETURNS BOOLEAN AS $$
DECLARE
    name TEXT := parent || '_' || to_char(day, 'YYYYMMDD');
    lo TIMESTAMPTZ := day::TIMESTAMP AT TIME ZONE 'Europe/London';
    hi TIMESTAMPTZ := (day + 1)::TIMESTAMP AT TIME ZONE 'Europe/London';
BEGIN
    IF to_regclass(name) IS NOT NULL THEN
        RETURN FALSE;
    END IF;
    EXECUTE format('CREATE TABLE %I (LIKE %I INCLUDING DEFAULTS INCLUDING CONSTRAINTS)', name, parent);
    IF to_regclass(parent || '_default') IS NOT NULL THEN
        EXECUTE format(
            'WITH moved AS (DELETE FROM %I WHERE %I >= $1 AND %I < $2 RETURNING *) INSERT INTO %I SELECT * FROM moved',
            parent || '_default', key_column, key_column, name
        ) USING lo, hi;
    END IF;
    EXECUTE format('ALTER TABLE %I ATTACH PARTITION %I FOR VALUES FROM (%L) TO (%L)', parent, name, lo, hi);
    RETURN TRUE;
END
$$ LANGUAGE plpgsql;

ALTER TABLE darwin_events RENAME TO darwin_events_unpartitioned;
ALTER INDEX darwin_events_received_at_idx RENAME TO darwin_events_unpartitioned_received_at_idx;
ALTER INDEX darwin_events_rids_idx RENAME TO darwin_events_unpartitioned_rids_idx;
ALTER SEQUENCE darwin_events_id_seq OWNED BY NONE;

CREATE TABLE darwin_events (
    id BIGINT NOT NULL DEFAULT nextval('darwin_events_id_seq'),
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    message_ts TIMESTAMPTZ, -- the Push Port `ts`
    push_port_sequence BIGINT,
    kinds TEXT[] NOT NULL DEFAULT '{}', -- update types in the message, e.g. {TS} or {schedule}
    rids TEXT[] NOT NULL DEFAULT '{}', -- trains the message refers to
    payload JSONB NOT NULL,
    PRIMARY KEY (id, received_at)
) PARTITION BY RANGE (received_at);

ALTER SEQUENCE darwin_events_id_seq OWNED BY darwin_events.id;
CREATE TABLE darwin_events_default PARTITION OF darwin_events DEFAULT;
CREATE INDEX darwin_events_received_at_idx ON darwin_events (received_at);
CREATE INDEX darwin_events_rids_idx ON darwin_events USING GIN (rids);

SELECT ensure_day_partition('darwin_events', 'received_at', day)
FROM (SELECT DISTINCT (received_at AT TIME ZONE 'Europe/London')::DATE AS day FROM darwin_events_unpartitioned) days;

INSERT INTO darwin_events SELECT * FROM darwin_events_unpartitioned;
DROP TABLE darwin_events_unpartitioned;
