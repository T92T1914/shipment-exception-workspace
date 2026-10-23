-- Run by migrate() inside the same transaction that locks schema_version.
-- Existing records, events, sessions and mutation receipts remain unchanged.
ALTER TABLE exception_events DROP CONSTRAINT exception_events_action_check;
ALTER TABLE exception_events DROP CONSTRAINT exception_events_version_check;
ALTER TABLE exception_events ADD CONSTRAINT exception_events_action_version CHECK (
    (action = 'created' AND version = 1 AND assignee_id IS NULL AND note IS NULL) OR
    (action IN ('assigned', 'resolved') AND version > 1)
);
ALTER TABLE schema_version DROP CONSTRAINT schema_version_version_check;
UPDATE schema_version SET version = 2;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_supported CHECK (version = 2);
