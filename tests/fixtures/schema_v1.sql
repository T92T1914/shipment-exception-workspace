CREATE TABLE IF NOT EXISTS schema_version (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version integer NOT NULL CHECK (version = 1)
);
CREATE TABLE IF NOT EXISTS organizations (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120)
);
CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES organizations(id),
    email text NOT NULL UNIQUE CHECK (email = lower(email)),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    password_hash text NOT NULL,
    UNIQUE (organization_id, id)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash text PRIMARY KEY,
    user_id uuid REFERENCES users(id) ON DELETE CASCADE,
    csrf_token text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS shipment_exceptions (
    id uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES organizations(id),
    reference text NOT NULL CHECK (length(reference) BETWEEN 1 AND 80),
    summary text NOT NULL CHECK (length(summary) BETWEEN 1 AND 200),
    details text NOT NULL CHECK (length(details) BETWEEN 1 AND 4000),
    priority text NOT NULL CHECK (priority IN ('high', 'normal')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    assignee_id uuid,
    resolution text,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, reference),
    FOREIGN KEY (organization_id, assignee_id) REFERENCES users(organization_id, id),
    CHECK ((status = 'open' AND resolution IS NULL) OR
           (status = 'resolved' AND resolution IS NOT NULL AND length(trim(resolution)) BETWEEN 1 AND 2000))
);
CREATE TABLE IF NOT EXISTS exception_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id uuid NOT NULL,
    exception_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    action text NOT NULL CHECK (action IN ('assigned', 'resolved')),
    assignee_id uuid,
    note text,
    version integer NOT NULL CHECK (version > 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, exception_id) REFERENCES shipment_exceptions(organization_id, id),
    FOREIGN KEY (organization_id, actor_id) REFERENCES users(organization_id, id),
    FOREIGN KEY (organization_id, assignee_id) REFERENCES users(organization_id, id),
    UNIQUE (exception_id, version)
);
CREATE TABLE IF NOT EXISTS mutation_requests (
    organization_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    key uuid NOT NULL,
    fingerprint text NOT NULL,
    status_code integer,
    response jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, actor_id, key),
    FOREIGN KEY (organization_id, actor_id) REFERENCES users(organization_id, id),
    CHECK ((status_code IS NULL AND response IS NULL) OR
           (status_code IS NOT NULL AND status_code BETWEEN 200 AND 499 AND response IS NOT NULL))
);
INSERT INTO schema_version(singleton, version) VALUES (true, 1)
ON CONFLICT (singleton) DO NOTHING;
