"""Small explicit PostgreSQL boundary. Each request owns its connection."""

from importlib.resources import files
from uuid import UUID

import psycopg
from argon2 import PasswordHasher
from psycopg.rows import dict_row

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
SCHEMA_VERSION = 2


def connect(database_url):
    return psycopg.connect(database_url, autocommit=True, row_factory=dict_row,
                           connect_timeout=5, options="-c statement_timeout=10000 -c lock_timeout=5000")


def initialize(database_url):
    with connect(database_url) as conn, conn.transaction():
        exists = conn.execute("SELECT to_regclass('public.schema_version') AS name").fetchone()["name"]
        if exists:
            version = conn.execute("SELECT version FROM schema_version").fetchall()
            if version != [{"version": SCHEMA_VERSION}]:
                raise RuntimeError("Database schema is not version 2. Stop the app and run shipment-workspace migrate for version 1.")
        elif conn.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                             WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f') LIMIT 1""").fetchone():
            raise RuntimeError("Schema metadata is missing from a nonempty database. Restore its metadata or use an empty dedicated database.")
        conn.execute(files("shipment_workspace").joinpath("schema.sql").read_text(encoding="utf-8"))


def require_current_schema(database_url):
    with connect(database_url) as conn:
        exists = conn.execute("SELECT to_regclass('public.schema_version') AS name").fetchone()["name"]
        if not exists or conn.execute("SELECT version FROM schema_version").fetchall() != [{"version": SCHEMA_VERSION}]:
            raise RuntimeError("Database requires schema version 2. Run init for an empty database or stop the app and migrate version 1.")


def migrate(database_url):
    """Upgrade the known v1 schema atomically. Never backfill fictional history."""
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
        if versions != [{"version": 1}]:
            raise RuntimeError("Unsupported database schema. Only version 1 can be migrated to version 2.")
        conn.execute(files("shipment_workspace").joinpath("migrate_v1_v2.sql").read_text(encoding="utf-8"))


def seed(database_url, password):
    """Insert synthetic records once. Repeated seeding never resets workflow state."""
    if len(password) < 12:
        raise ValueError("Demo password must contain at least 12 characters")
    require_current_schema(database_url)
    hashed = PASSWORDS.hash(password)
    north, harbor = UUID(int=1), UUID(int=2)
    with connect(database_url) as conn, conn.transaction():
        for org_id, name in [(north, "Northline Logistics"), (harbor, "Harbor Supply")]:
            conn.execute("INSERT INTO organizations(id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING", (org_id, name))
        for ident, org_id, email, name in [
            (11, north, "alex@northline.example", "Alex Morgan"),
            (12, north, "sam@northline.example", "Sam Rivera"),
            (21, harbor, "jules@harbor.example", "Jules Chen"),
            (22, harbor, "robin@harbor.example", "Robin Ellis"),
        ]:
            conn.execute("INSERT INTO users(id,organization_id,email,name,password_hash) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                         (UUID(int=ident), org_id, email, name, hashed))
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


EXCEPTION_SELECT = """SELECT e.id, e.reference, e.summary, e.details, e.status, e.priority,
    e.assignee_id, u.name AS assignee_name, e.resolution, e.version, e.updated_at
    FROM shipment_exceptions e LEFT JOIN users u ON u.id=e.assignee_id"""


def exception_record(conn, organization_id, exception_id):
    return conn.execute(EXCEPTION_SELECT + " WHERE e.organization_id=%s AND e.id=%s",
                        (organization_id, exception_id)).fetchone()
