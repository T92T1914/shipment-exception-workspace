-- The caller holds the schema lock and runs the whole upgrade chain atomically.
-- Existing users retain accepted access. Future omitted roles default to review.
ALTER TABLE users ADD COLUMN role text NOT NULL DEFAULT 'operator'
    CONSTRAINT users_role_allowed CHECK (role IN ('operator', 'reviewer'));
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'reviewer';
ALTER TABLE schema_version DROP CONSTRAINT schema_version_supported;
UPDATE schema_version SET version=4;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_supported CHECK (version=4);
