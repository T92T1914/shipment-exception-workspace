"""Upgrade the exact accepted v2 schema without changing its retained workflow.

These checks replace public only in the explicit disposable integration database
and restore the current schema afterward. They never use a retained consumer URL.
"""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1, sha256
import json
from pathlib import Path
from threading import Barrier
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from conftest import ORIGIN
from shipment_workspace.app import create_app
from shipment_workspace.config import Settings
from shipment_workspace.db import initialize, migrate, require_current_schema


V2_SQL = Path(__file__).with_name("fixtures").joinpath("schema_v2.sql")
LEGACY_ORG = UUID(int=20001)
LEGACY_ACTOR = UUID(int=20011)
LEGACY_EXCEPTION = UUID(int=20101)
LEGACY_SESSION = "synthetic-v2-session-preserved-by-login-upgrade"
LEGACY_CSRF = "synthetic-v2-csrf-preserved-by-login-upgrade"
LEGACY_KEY = UUID("684cb67e-4c6d-47f0-9af8-20c65188a1f2")
CREATION_BODY = {
    "reference": "LEGACY-V2-CREATED", "summary": "Accepted manual exception",
    "details": "Retained v2 text with literal <b>markup</b> and a quote ' kept.",
    "priority": "normal",
}


def replace_test_schema(database, legacy_sql=None):
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        if legacy_sql is not None:
            conn.execute(legacy_sql)


def database_snapshot(database):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        names = [row["tablename"] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).fetchall()]
        rows = {
            name: conn.execute(sql.SQL("SELECT * FROM {} ORDER BY 1,2").format(
                sql.Identifier(name)
            )).fetchall()
            for name in names
        }
        constraints = conn.execute(
            "SELECT t.relname AS table_name,c.conname,pg_get_constraintdef(c.oid) AS definition "
            "FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
            "JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' "
            "ORDER BY t.relname,c.conname"
        ).fetchall()
        indexes = conn.execute(
            "SELECT tablename,indexname,indexdef FROM pg_indexes "
            "WHERE schemaname='public' ORDER BY tablename,indexname"
        ).fetchall()
    return {"rows": rows, "constraints": constraints, "indexes": indexes}


def insert_v2_rows(database):
    canonical = {"action": "created", **CREATION_BODY}
    fingerprint = sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with psycopg.connect(database, row_factory=dict_row) as conn:
        conn.execute("INSERT INTO organizations(id,name) VALUES (%s,%s)",
                     (LEGACY_ORG, "Synthetic V2 Organization"))
        conn.execute(
            "INSERT INTO users(id,organization_id,email,name,password_hash) VALUES (%s,%s,%s,%s,%s)",
            (LEGACY_ACTOR, LEGACY_ORG, "legacy-v2@synthetic.example", "V2 Operator",
             "synthetic-password-hash-not-used-for-login"),
        )
        conn.execute(
            "INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,'2026-10-02T10:00:00Z')",
            (LEGACY_EXCEPTION, LEGACY_ORG, *CREATION_BODY.values()),
        )
        conn.execute(
            "INSERT INTO exception_events(organization_id,exception_id,actor_id,action,version,created_at) "
            "VALUES (%s,%s,%s,'created',1,'2026-10-02T10:00:00Z')",
            (LEGACY_ORG, LEGACY_EXCEPTION, LEGACY_ACTOR),
        )
        original = conn.execute(
            "SELECT e.id,e.reference,e.summary,e.details,e.status,e.priority,e.assignee_id," 
            "u.name AS assignee_name,e.resolution,e.version,e.updated_at "
            "FROM shipment_exceptions e LEFT JOIN users u ON u.id=e.assignee_id WHERE e.id=%s",
            (LEGACY_EXCEPTION,),
        ).fetchone()
        response = {"exception": jsonable_encoder(original)}
        conn.execute(
            "INSERT INTO mutation_requests(organization_id,actor_id,key,fingerprint,status_code,response,created_at) "
            "VALUES (%s,%s,%s,%s,201,%s,'2026-10-02T10:00:00Z')",
            (LEGACY_ORG, LEGACY_ACTOR, LEGACY_KEY, fingerprint, Jsonb(response)),
        )
        conn.execute(
            "UPDATE shipment_exceptions SET assignee_id=%s,version=2,updated_at='2026-10-02T10:05:00Z' "
            "WHERE id=%s", (LEGACY_ACTOR, LEGACY_EXCEPTION),
        )
        conn.execute(
            "INSERT INTO exception_events(organization_id,exception_id,actor_id,action,assignee_id,version,created_at) "
            "VALUES (%s,%s,%s,'assigned',%s,2,'2026-10-02T10:05:00Z')",
            (LEGACY_ORG, LEGACY_EXCEPTION, LEGACY_ACTOR, LEGACY_ACTOR),
        )
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) "
            "VALUES (%s,%s,%s,'2035-01-01T00:00:00Z')",
            (sha256(LEGACY_SESSION.encode()).hexdigest(), LEGACY_ACTOR, LEGACY_CSRF),
        )
    return response


@pytest.fixture()
def v2_database(database_url):
    replace_test_schema(database_url, V2_SQL.read_text(encoding="utf-8"))
    try:
        response = insert_v2_rows(database_url)
        yield database_url, response
    finally:
        replace_test_schema(database_url)
        initialize(database_url)


def assert_retained_v2_rows(before, after):
    assert before["rows"]["schema_version"] == [{"singleton": True, "version": 2}]
    assert after["rows"]["schema_version"] == [{"singleton": True, "version": 4}]
    for name, rows in before["rows"].items():
        if name == "users":
            assert after["rows"][name] == [{**row, "role": "operator"} for row in rows]
        elif name != "schema_version":
            assert after["rows"][name] == rows, name
    assert after["rows"]["login_identifiers"] == []
    assert len(after["rows"]["login_global"]) == 1
    assert after["rows"]["login_global"][0]["singleton"] is True
    assert after["rows"]["login_global"][0]["attempts"] == 0


def test_v2_fixture_is_the_exact_accepted_source_blob():
    raw = V2_SQL.read_bytes()
    git_blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    # Accepted v0.2.0 schema at 3a3f971, retained byte-for-byte across platforms.
    assert sha1(git_blob).hexdigest() == "c8f6bf47db94ae6b0dffeffd136606df1e2029be"


def test_explicit_v2_upgrade_preserves_created_history_historical_201_receipt_and_session(v2_database):
    database, original_response = v2_database
    before = database_snapshot(database)
    migrate(database)
    require_current_schema(database)
    after = database_snapshot(database)
    assert_retained_v2_rows(before, after)
    app = create_app(Settings(database_url=database, origin=ORIGIN, secure_cookie=False))
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("shipment_session", LEGACY_SESSION)
        session = client.get("/api/session")
        assert session.status_code == 200, session.text
        assert session.json()["authenticated"] is True
        assert session.json()["csrf_token"] == LEGACY_CSRF
        replay = client.post(
            "/api/exceptions", json=CREATION_BODY,
            headers={"Origin": ORIGIN, "X-CSRF-Token": LEGACY_CSRF,
                     "Content-Type": "application/json", "Idempotency-Key": str(LEGACY_KEY)},
        )
        assert replay.status_code == 201, replay.text
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert replay.json() == original_response
        assert replay.json()["exception"]["version"] == 1
        assert replay.json()["exception"]["assignee_id"] is None
        current = client.get(f"/api/exceptions/{LEGACY_EXCEPTION}")
        assert current.status_code == 200, current.text
        assert current.json()["exception"]["version"] == 2
        assert current.json()["exception"]["assignee_id"] == str(LEGACY_ACTOR)
        assert [event["action"] for event in current.json()["events"]] == ["created", "assigned"]
    assert database_snapshot(database) == after


def test_v2_requires_explicit_upgrade_before_initialization_or_app_start(v2_database):
    database, _ = v2_database
    before = database_snapshot(database)
    for operation in (initialize, require_current_schema):
        with pytest.raises(RuntimeError, match="[Mm]igrat|version 4"):
            operation(database)
        assert database_snapshot(database) == before
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url=database, origin=ORIGIN, secure_cookie=False))
    assert database_snapshot(database) == before


def test_two_v2_migrators_upgrade_once_and_keep_every_accepted_row(v2_database):
    database, _ = v2_database
    before = database_snapshot(database)
    start = Barrier(2, timeout=10)

    def worker():
        start.wait()
        migrate(database)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)
    require_current_schema(database)
    assert_retained_v2_rows(before, database_snapshot(database))


def test_a_late_v2_upgrade_failure_rolls_back_new_tables_indexes_and_schema_bump(v2_database):
    database, _ = v2_database
    before = database_snapshot(database)
    with psycopg.connect(database) as conn:
        conn.execute(
            "CREATE FUNCTION test_reject_v3_schema_bump() RETURNS trigger LANGUAGE plpgsql "
            "AS $$ BEGIN RAISE EXCEPTION 'synthetic v3 schema bump failure'; END; $$"
        )
        conn.execute(
            "CREATE TRIGGER test_v3_schema_failure BEFORE UPDATE ON schema_version "
            "FOR EACH ROW EXECUTE FUNCTION test_reject_v3_schema_bump()"
        )
    try:
        with pytest.raises((psycopg.Error, RuntimeError)):
            migrate(database)
        assert database_snapshot(database) == before
        with psycopg.connect(database) as conn:
            assert conn.execute("SELECT to_regclass('public.login_global')").fetchone()[0] is None
            assert conn.execute("SELECT to_regclass('public.login_identifiers')").fetchone()[0] is None
            assert conn.execute("SELECT to_regclass('public.login_identifiers_expiry')").fetchone()[0] is None
    finally:
        with psycopg.connect(database) as conn:
            conn.execute("DROP TRIGGER IF EXISTS test_v3_schema_failure ON schema_version")
            conn.execute("DROP FUNCTION IF EXISTS test_reject_v3_schema_bump()")
    migrate(database)
    require_current_schema(database)
    assert_retained_v2_rows(before, database_snapshot(database))


def test_repeating_current_initialization_and_migration_does_not_reset_live_budgets(v2_database):
    database, _ = v2_database
    migrate(database)
    with psycopg.connect(database) as conn:
        conn.execute(
            "UPDATE login_global SET attempts=17,reset_at=clock_timestamp()+interval '60 seconds'"
        )
        conn.execute(
            "INSERT INTO login_identifiers(identifier_hash,attempts,reset_at) "
            "VALUES (%s,17,clock_timestamp()+interval '60 seconds')",
            (sha256(b"retained@synthetic.example").hexdigest(),),
        )
    before = database_snapshot(database)
    initialize(database)
    migrate(database)
    require_current_schema(database)
    assert database_snapshot(database) == before


@pytest.mark.parametrize("table,column,value", [
    ("login_global", "attempts", -1),
    ("login_global", "attempts", 41),
    ("login_identifiers", "attempts", 0),
    ("login_identifiers", "attempts", 21),
    ("login_identifiers", "identifier_hash", "plaintext@synthetic.example"),
])
def test_upgraded_database_enforces_bounded_counter_and_digest_constraints(
    v2_database, table, column, value
):
    database, _ = v2_database
    migrate(database)
    digest = sha256(b"bounded@synthetic.example").hexdigest()
    with psycopg.connect(database) as conn:
        conn.execute(
            "INSERT INTO login_identifiers(identifier_hash,attempts,reset_at) "
            "VALUES (%s,1,clock_timestamp()+interval '60 seconds')", (digest,),
        )
    before = database_snapshot(database)
    with psycopg.connect(database) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(sql.SQL("UPDATE {} SET {}=%s").format(
                sql.Identifier(table), sql.Identifier(column)
            ), (value,))
    assert database_snapshot(database) == before
