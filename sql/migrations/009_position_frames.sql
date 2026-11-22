-- Milestone 4: what the map showed, recorded every tick so any moment can be replayed.
-- A keyframe holds every placed train (the shape of /api/positions); a changes frame holds only the trains that
-- changed since the frame before it and the rids removed (the shape of a /api/stream `changes` event). Each run of
-- the recorder starts with a keyframe and writes one every 5 minutes, so a moment is rebuilt from the latest
-- keyframe at or before it plus the changes frames after that.

CREATE TABLE position_frames (
    at TIMESTAMPTZ NOT NULL, -- the moment the positions are for
    keyframe BOOLEAN NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('recorded', 'computed')), -- computed: backfilled after the fact
    trains INTEGER NOT NULL, -- trains in `data`
    active INTEGER NOT NULL, -- trains running at `at`, placed or not
    data BYTEA NOT NULL, -- gzipped JSON
    PRIMARY KEY (at)
) PARTITION BY RANGE (at);

COMMENT ON COLUMN position_frames.source IS
    'recorded: written live by recorder.py; computed: backfilled later from the database as it was then';

CREATE TABLE position_frames_default PARTITION OF position_frames DEFAULT;
CREATE INDEX position_frames_keyframes_idx ON position_frames (at) WHERE keyframe;
