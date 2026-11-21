-- Passing points Darwin reports in a TS update but that aren't in the train's schedule are stored
-- as extra stops instead of being dropped.

ALTER TABLE train_stops ADD COLUMN added_from_status BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN train_stops.added_from_status IS
    'Passing point first seen in a TS location, not in the timetable or a schedule message';
