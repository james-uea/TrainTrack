-- 0.9.0 keeps a track route that turns back on itself when it's barely longer than the straight line, marked
-- fallback_reason 'reverses', but the check from 007 didn't allow that value, so storing one failed.
ALTER TABLE segment_paths DROP CONSTRAINT segment_paths_fallback_reason_check;
ALTER TABLE segment_paths ADD CONSTRAINT segment_paths_fallback_reason_check
    CHECK (fallback_reason IN ('off_network', 'no_path', 'detour', 'reverses'));
