-- Milestone 6: Network Rail's Train Describer. Signalling splits the track into berths, roughly from one signal to
-- the next, and reports each train's headcode stepping from berth to berth, to the second.

-- Berth steps (CA), cancels (CB, a headcode cleared from a berth) and interposes (CC, one put into a berth), as
-- td_consumer.py receives them. One partition per UK day, kept TD_KEEP_DAYS (default 14).
CREATE TABLE td_steps (
    at TIMESTAMPTZ NOT NULL,
    area_id TEXT NOT NULL, -- train describer area, e.g. R2
    from_berth TEXT, -- NULL for an interpose
    to_berth TEXT, -- NULL for a cancel
    descr TEXT NOT NULL, -- the train's headcode
    msg_type TEXT NOT NULL CHECK (msg_type IN ('CA', 'CB', 'CC'))
) PARTITION BY RANGE (at);

CREATE TABLE td_steps_default PARTITION OF td_steps DEFAULT;
CREATE INDEX td_steps_at_idx ON td_steps (at);

-- Where each berth step happens (the signal between its two berths), learned by td_berths.py from where Darwin's
-- actual times put the trains that made it, and how far and how long it is on average to a train's next step
CREATE TABLE td_step_points (
    area_id TEXT NOT NULL,
    from_berth TEXT NOT NULL,
    to_berth TEXT NOT NULL,
    x DOUBLE PRECISION NOT NULL, -- British National Grid
    y DOUBLE PRECISION NOT NULL,
    samples INTEGER NOT NULL, -- trains it was learned from
    spread_m REAL NOT NULL, -- median distance of those trains' positions from the point
    next_metres REAL, -- median distance along the track to the train's next step
    next_seconds REAL, -- median time to it
    learned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (area_id, from_berth, to_berth)
);
