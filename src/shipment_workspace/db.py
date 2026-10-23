"""Small explicit PostgreSQL boundary. Each request owns its connection."""

from importlib.resources import files
from uuid import UUID

import psycopg
from argon2 import PasswordHasher
from psycopg.rows import dict_row

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)


def connect(database_url):
    return psycopg.connect(database_url, autocommit=True, row_factory=dict_row,
                           connect_timeout=5, options="-c statement_timeout=10000 -c lock_timeout=5000")


def initialize(database_url):
    with connect(database_url) as conn, conn.transaction():
        exists = conn.execute("SELECT to_regclass('public.schema_version') AS name").fetchone()["name"]
        if exists:
            version = conn.execute("SELECT version FROM schema_version").fetchall()
            if version != [{"version": 1}]:
                raise RuntimeError("Unsupported database schema")
        conn.execute(files("shipment_workspace").joinpath("schema.sql").read_text(encoding="utf-8"))


def seed(database_url, password):
    """Insert synthetic records once. Repeated seeding never resets workflow state."""
    if len(password) < 12:
        raise ValueError("Demo password must contain at least 12 characters")
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
