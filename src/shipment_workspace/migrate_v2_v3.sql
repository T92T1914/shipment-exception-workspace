-- The caller locks schema_version and runs all required upgrades atomically.
CREATE TABLE login_global (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    attempts integer NOT NULL CHECK (attempts BETWEEN 0 AND 40),
    reset_at timestamptz NOT NULL
);
CREATE TABLE login_identifiers (
    identifier_hash text PRIMARY KEY CHECK (identifier_hash ~ '^[0-9a-f]{64}$'),
    attempts integer NOT NULL CHECK (attempts BETWEEN 1 AND 20),
    reset_at timestamptz NOT NULL
);
CREATE INDEX login_identifiers_expiry ON login_identifiers(reset_at);
INSERT INTO login_global(singleton,attempts,reset_at) VALUES (true,0,clock_timestamp());
ALTER TABLE schema_version DROP CONSTRAINT schema_version_supported;
UPDATE schema_version SET version=3;
ALTER TABLE schema_version ADD CONSTRAINT schema_version_supported CHECK (version=3);
