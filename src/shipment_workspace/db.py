"""Small explicit PostgreSQL boundary. Each request owns its connection."""

from importlib.resources import files
from datetime import timedelta
import secrets
from uuid import UUID

import psycopg
from argon2 import PasswordHasher
from psycopg.rows import dict_row

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
SCHEMA_VERSION = 4


def connect(database_url):
    return psycopg.connect(database_url, autocommit=True, row_factory=dict_row,
                           connect_timeout=5, options="-c statement_timeout=10000 -c lock_timeout=5000")


def initialize(database_url):
    with connect(database_url) as conn, conn.transaction():
        exists = conn.execute("SELECT to_regclass('public.schema_version') AS name").fetchone()["name"]
        if exists:
            version = conn.execute("SELECT version FROM schema_version").fetchall()
            if version != [{"version": SCHEMA_VERSION}]:
                raise RuntimeError("Database schema is not version 4. Stop the app and run shipment-workspace migrate for version 1, 2 or 3.")
        elif conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                             WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f') LIMIT 1""").fetchone():
            raise RuntimeError("Schema metadata is missing from a nonempty database. Restore its metadata or use an empty dedicated database.")
        conn.execute(files("shipment_workspace").joinpath("schema.sql").read_text(encoding="utf-8"))


def require_current_schema(database_url):
    with connect(database_url) as conn:
        exists = conn.execute("SELECT to_regclass('public.schema_version') AS name").fetchone()["name"]
        if not exists or conn.execute("SELECT version FROM schema_version").fetchall() != [{"version": SCHEMA_VERSION}]:
            raise RuntimeError("Database requires schema version 4. Run init for an empty database or stop the app and migrate version 1, 2 or 3.")


def migrate(database_url):
    """Upgrade known schemas atomically while preserving old users' access."""
    with connect(database_url) as conn, conn.transaction():
        exists = conn.execute("SELECT to_regclass('public.schema_version') AS name").fetchone()["name"]
        if not exists:
            raise RuntimeError("No database schema found. Run shipment-workspace init for an empty database.")
        # Acquire the DDL lock before any row lock. Two migrators otherwise
        # could each hold a table lock while one waits to upgrade it for ALTER.
        conn.execute("LOCK TABLE schema_version IN ACCESS EXCLUSIVE MODE")
        versions = conn.execute("SELECT version FROM schema_version FOR UPDATE").fetchall()
        if versions == [{"version": SCHEMA_VERSION}]:
            return
        if versions not in ([{"version": 1}], [{"version": 2}], [{"version": 3}]):
            raise RuntimeError("Unsupported database schema. Only version 1, 2 or 3 can be migrated to version 4.")
        if versions == [{"version": 1}]:
            conn.execute(files("shipment_workspace").joinpath("migrate_v1_v2.sql").read_text(encoding="utf-8"))
        if versions in ([{"version": 1}], [{"version": 2}]):
            conn.execute(files("shipment_workspace").joinpath("migrate_v2_v3.sql").read_text(encoding="utf-8"))
        conn.execute(files("shipment_workspace").joinpath("migrate_v3_v4.sql").read_text(encoding="utf-8"))


def seed(database_url, password):
    """Insert synthetic records once. Repeated seeding never resets workflow state."""
    if len(password) < 12:
        raise ValueError("Demo password must contain at least 12 characters")
    require_current_schema(database_url)
    hashed = PASSWORDS.hash(password)
    with connect(database_url) as conn, conn.transaction():
        _seed_rows(conn, hashed)


def _seed_rows(conn, hashed):
    """The caller owns the complete synthetic provisioning transaction."""
    north, harbor = UUID(int=1), UUID(int=2)
    for org_id, name in [(north, "Northline Logistics"), (harbor, "Harbor Supply")]:
        conn.execute("INSERT INTO organizations(id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING", (org_id, name))
    for ident, org_id, email, name, role in [
            (11, north, "alex@northline.example", "Alex Morgan", "operator"),
            (12, north, "sam@northline.example", "Sam Rivera", "operator"),
            (13, north, "casey@northline.example", "Casey Lane", "reviewer"),
            (21, harbor, "jules@harbor.example", "Jules Chen", "operator"),
            (22, harbor, "robin@harbor.example", "Robin Ellis", "operator"),
            (23, harbor, "taylor@harbor.example", "Taylor Brooks", "reviewer"),
    ]:
        conn.execute("INSERT INTO users(id,organization_id,email,name,password_hash,role) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (UUID(int=ident), org_id, email, name, hashed, role))
    for ident, org_id, reference, summary, details, priority in [
            (101, north, "NL-1042", "Delivery appointment missed", "Carrier arrived after the receiving window. Confirm the next available appointment and update the receiving team.", "high"),
            (102, north, "NL-1086", "Pallet count needs confirmation", "The receipt records 11 pallets against 12 on the synthetic manifest. Reconcile the count before closing the exception.", "normal"),
            (103, north, "NL-1091", "Missing handoff document", "The delivery packet is missing a signed handoff record. Assign an owner to obtain a replacement.", "normal"),
            (201, harbor, "HS-2057", "Receiving location changed", "The destination team has requested a different receiving bay. Confirm the updated handoff instructions.", "high"),
            (202, harbor, "HS-2073", "Seal reference mismatch", "The synthetic arrival record and manifest have different seal references. Verify the paperwork before release.", "normal"),
    ]:
        conn.execute("""INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority)
                        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                     (UUID(int=ident), org_id, reference, summary, details, priority))


def provision_demo(database_url, password):
    """Provision one empty schema atomically. This command never resets data."""
    from .public_demo import DEMO_EMAIL, DEMO_ORGANIZATION_ID, DEMO_USER_ID, SESSION_LOCK
    if not 12 <= len(password) <= 256:
        raise ValueError("Published reviewer password must contain 12 through 256 characters")
    require_current_schema(database_url)
    private_hash = PASSWORDS.hash(secrets.token_urlsafe(48))
    public_hash = PASSWORDS.hash(password)
    with connect(database_url) as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s,%s)", SESSION_LOCK)
        # The separate target must have only its initialized schema. Lock all
        # application writers before inspecting emptiness or inserting rows.
        conn.execute("LOCK TABLE organizations,users,shipment_exceptions,exception_events,mutation_requests,sessions,login_identifiers,login_global IN ACCESS EXCLUSIVE MODE")
        populated = conn.execute("""SELECT EXISTS(SELECT 1 FROM organizations) OR EXISTS(SELECT 1 FROM users)
            OR EXISTS(SELECT 1 FROM shipment_exceptions) OR EXISTS(SELECT 1 FROM exception_events)
            OR EXISTS(SELECT 1 FROM mutation_requests) OR EXISTS(SELECT 1 FROM sessions)
            OR EXISTS(SELECT 1 FROM login_identifiers) OR EXISTS(SELECT 1 FROM login_global WHERE attempts<>0) AS value""").fetchone()["value"]
        if populated:
            raise RuntimeError("Public demo provisioning requires empty application state. Existing state was preserved.")
        _seed_rows(conn, private_hash)
        conn.execute("INSERT INTO users(id,organization_id,email,name,password_hash,role) VALUES (%s,%s,%s,%s,%s,'reviewer')",
                     (DEMO_USER_ID, DEMO_ORGANIZATION_ID, DEMO_EMAIL, "Synthetic Visitor", public_hash))
        _demo_history(conn)


def _demo_history(conn):
    """Provisioned synthetic history, separate from an executed operator journey."""
    now = conn.execute("SELECT clock_timestamp() AS value").fetchone()["value"]
    org, actor, assignee = UUID(int=1), UUID(int=11), UUID(int=12)
    resolved, assigned = UUID(int=102), UUID(int=103)
    resolution = "Provisioned synthetic fixture: the receiving team confirmed the pallet count and recorded the reconciliation."
    conn.execute("""UPDATE shipment_exceptions SET status='resolved',assignee_id=%s,resolution=%s,
                    version=3,updated_at=%s WHERE id=%s AND organization_id=%s""",
                 (assignee, resolution, now - timedelta(minutes=1), resolved, org))
    conn.execute("UPDATE shipment_exceptions SET assignee_id=%s,version=2,updated_at=%s WHERE id=%s AND organization_id=%s",
                 (assignee, now, assigned, org))
    for item, action, version, recipient, note, ago in [
        (resolved, "created", 1, None, None, 3),
        (resolved, "assigned", 2, assignee, None, 2),
        (resolved, "resolved", 3, assignee, resolution, 1),
        (assigned, "created", 1, None, None, 1),
        (assigned, "assigned", 2, assignee, None, 0),
    ]:
        conn.execute("""INSERT INTO exception_events(organization_id,exception_id,actor_id,action,
                        assignee_id,note,version,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (org, item, actor, action, recipient, note, version, now - timedelta(minutes=ago)))


def require_demo_identity(database_url, password):
    """Refuse a mismatched deployment without altering identities or workflow."""
    from argon2.exceptions import VerificationError
    from .public_demo import DEMO_USER_ID, public_reviewer
    require_current_schema(database_url)
    with connect(database_url) as conn:
        user = conn.execute("SELECT * FROM users WHERE id=%s", (DEMO_USER_ID,)).fetchone()
    if not public_reviewer(user):
        raise RuntimeError("Provision the separate synthetic reviewer before starting the public demo")
    try:
        PASSWORDS.verify(user["password_hash"], password)
    except VerificationError:
        raise RuntimeError("Published reviewer credential does not match the provisioned demo") from None


EXCEPTION_SELECT = """SELECT e.id, e.reference, e.summary, e.details, e.status, e.priority,
    e.assignee_id, u.name AS assignee_name, e.resolution, e.version, e.updated_at
    FROM shipment_exceptions e LEFT JOIN users u ON u.id=e.assignee_id"""


def exception_record(conn, organization_id, exception_id):
    return conn.execute(EXCEPTION_SELECT + " WHERE e.organization_id=%s AND e.id=%s",
                        (organization_id, exception_id)).fetchone()
