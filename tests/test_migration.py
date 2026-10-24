"""Upgrade the accepted v1 SQL fixture, using only the disposable test database.

These checks replace public in SHIPMENT_TEST_DATABASE_URL and always restore the
current schema. They must never point at a retained consumer or project database.
The legacy fixture is the accepted v0.1.0 schema, not a reconstruction from v2.
"""

from hashlib import sha1, sha256
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

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


V1_SQL = Path(__file__).with_name("fixtures").joinpath("schema_v1.sql")
LEGACY_ORG = UUID(int=10001)
LEGACY_ACTOR = UUID(int=10011)
LEGACY_EXCEPTION = UUID(int=10101)
LEGACY_SESSION = "synthetic-v1-session-kept-through-upgrade"
LEGACY_CSRF = "synthetic-v1-csrf-kept-through-upgrade"
LEGACY_KEY = UUID("56d2a064-a9c9-4a49-bf6c-e25b90b0f6d7")


def test_v1_upgrade_fixture_is_the_accepted_source_blob():
    raw = V1_SQL.read_bytes()
    git_blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    # Accepted v0.1.0 schema from e722a336f87462423769192d455a57560f8895ae.
    # Git's blob hash establishes fixture identity, not a security digest claim.
    assert sha1(git_blob).hexdigest() == "a5c75d707fa08e65fc6d539424d7be333c8040c4"


def replace_test_schema(database_url, legacy_sql=None):
    """Only called with the explicit disposable integration fixture URL."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        if legacy_sql is not None:
            conn.execute(legacy_sql)


def database_snapshot(database_url):
    """Retain row values and constraint/index definitions across DDL attempts."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        tables = [row["tablename"] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).fetchall()]
        data = {}
        for name in tables:
            data[name] = conn.execute(sql.SQL("SELECT * FROM {} ORDER BY 1,2").format(
                sql.Identifier(name)
            )).fetchall()
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
    return {"rows": data, "constraints": constraints, "indexes": indexes}


def insert_legacy_rows(database_url):
    """Retain an actual v1 assignment response and its original fingerprint route."""
    canonical = {
        "action": "assigned", "exception_id": str(LEGACY_EXCEPTION),
        "expected_version": 1, "assignee_id": str(LEGACY_ACTOR),
    }
    fingerprint = sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("INSERT INTO organizations(id,name) VALUES (%s,%s)",
                     (LEGACY_ORG, "Synthetic Legacy Organization"))
        conn.execute(
            "INSERT INTO users(id,organization_id,email,name,password_hash) VALUES (%s,%s,%s,%s,%s)",
            (LEGACY_ACTOR, LEGACY_ORG, "legacy@synthetic.example", "Legacy Operator",
             "synthetic-password-hash-not-used-for-login"),
        )
        conn.execute(
            "INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority,"
            "assignee_id,version,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,2,'2026-10-01T10:00:00Z')",
            (LEGACY_EXCEPTION, LEGACY_ORG, "LEGACY-1042", "Accepted old summary",
             "Accepted old details, with literal <b>markup</b> and quotes ' kept.", "normal", LEGACY_ACTOR),
        )
        conn.execute(
            "INSERT INTO exception_events(organization_id,exception_id,actor_id,action,assignee_id,note,version,created_at) "
            "VALUES (%s,%s,%s,'assigned',%s,NULL,2,'2026-10-01T10:00:00Z')",
            (LEGACY_ORG, LEGACY_EXCEPTION, LEGACY_ACTOR, LEGACY_ACTOR),
        )
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) "
            "VALUES (%s,%s,%s,'2035-01-01T00:00:00Z')",
            (sha256(LEGACY_SESSION.encode()).hexdigest(), LEGACY_ACTOR, LEGACY_CSRF),
        )
        item = conn.execute(
            "SELECT e.id,e.reference,e.summary,e.details,e.status,e.priority,e.assignee_id,"
            "u.name AS assignee_name,e.resolution,e.version,e.updated_at "
            "FROM shipment_exceptions e LEFT JOIN users u ON u.id=e.assignee_id WHERE e.id=%s",
            (LEGACY_EXCEPTION,),
        ).fetchone()
        response = {"exception": jsonable_encoder(item)}
        conn.execute(
            "INSERT INTO mutation_requests(organization_id,actor_id,key,fingerprint,status_code,response,created_at) "
            "VALUES (%s,%s,%s,%s,200,%s,'2026-10-01T10:00:00Z')",
            (LEGACY_ORG, LEGACY_ACTOR, LEGACY_KEY, fingerprint, Jsonb(response)),
        )
    return response


@pytest.fixture()
def legacy_database(database_url):
    # database_url is the existing explicit, disposable PostgreSQL test fixture.
    # No production/consumer URL fallback and no installed service are involved.
    replace_test_schema(database_url, V1_SQL.read_text(encoding="utf-8"))
    try:
        response = insert_legacy_rows(database_url)
        yield database_url, response
    finally:
        replace_test_schema(database_url)
        initialize(database_url)


def test_explicit_v1_migration_preserves_every_existing_row_and_old_retry_receipt(legacy_database):
    database_url, legacy_response = legacy_database
    before = database_snapshot(database_url)
    assert before["rows"]["schema_version"] == [{"singleton": True, "version": 1}]
    migrate(database_url)
    require_current_schema(database_url)
    after = database_snapshot(database_url)
    assert after["rows"]["schema_version"] == [{"singleton": True, "version": 4}]
    for table, rows in before["rows"].items():
        if table == "users":
            assert after["rows"][table] == [{**row, "role": "operator"} for row in rows]
        elif table != "schema_version":
            assert after["rows"][table] == rows, table
    app = create_app(Settings(database_url=database_url, origin=ORIGIN, secure_cookie=False))
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("shipment_session", LEGACY_SESSION)
        current = client.get("/api/session")
        assert current.status_code == 200 and current.json()["authenticated"] is True
        replay = client.post(
            f"/api/exceptions/{LEGACY_EXCEPTION}/assign",
            json={"expected_version": 1, "assignee_id": str(LEGACY_ACTOR)},
            headers={"Origin": ORIGIN, "X-CSRF-Token": LEGACY_CSRF,
                     "Content-Type": "application/json", "Idempotency-Key": str(LEGACY_KEY)},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json() == legacy_response
        detail = client.get(f"/api/exceptions/{LEGACY_EXCEPTION}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["exception"] == legacy_response["exception"]
        assert [event["action"] for event in detail.json()["events"]] == ["assigned"]
    assert database_snapshot(database_url) == after


def test_current_schema_allows_new_creation_after_upgrading_an_actual_v1_database(legacy_database):
    database_url, _ = legacy_database
    migrate(database_url)
    before = database_snapshot(database_url)
    app = create_app(Settings(database_url=database_url, origin=ORIGIN, secure_cookie=False))
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("shipment_session", LEGACY_SESSION)
        created = client.post(
            "/api/exceptions",
            json={"reference": "UPGRADED-NEW", "summary": "Created after upgrade",
                  "details": "Synthetic manual intake on the migrated database.", "priority": "normal"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": LEGACY_CSRF,
                     "Content-Type": "application/json", "Idempotency-Key": str(uuid4())},
        )
        assert created.status_code == 201, created.text
        item = created.json()["exception"]
        assert item["version"] == 1 and item["status"] == "open"
        detail = client.get(f"/api/exceptions/{item['id']}").json()
        assert len(detail["events"]) == 1
        assert detail["events"][0]["action"] == "created"
        assert detail["events"][0]["version"] == 1
    after = database_snapshot(database_url)
    assert len(after["rows"]["shipment_exceptions"]) == len(before["rows"]["shipment_exceptions"]) + 1
    assert len(after["rows"]["exception_events"]) == len(before["rows"]["exception_events"]) + 1


def test_v1_is_refused_by_initialization_and_app_startup_without_mutating_it(legacy_database):
    database_url, _ = legacy_database
    before = database_snapshot(database_url)
    with pytest.raises(RuntimeError, match="[Mm]igrat"):
        initialize(database_url)
    with pytest.raises(RuntimeError):
        require_current_schema(database_url)
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url=database_url, origin=ORIGIN, secure_cookie=False))
    assert database_snapshot(database_url) == before


def test_migration_and_initialization_are_noops_on_an_already_current_database(legacy_database):
    database_url, _ = legacy_database
    migrate(database_url)
    before = database_snapshot(database_url)
    migrate(database_url)
    initialize(database_url)
    require_current_schema(database_url)
    assert database_snapshot(database_url) == before


def test_two_concurrent_migrations_upgrade_once_and_preserve_existing_rows(legacy_database):
    database_url, _ = legacy_database
    before = database_snapshot(database_url)
    barrier = Barrier(2, timeout=10)

    def worker():
        barrier.wait()
        migrate(database_url)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)
    require_current_schema(database_url)
    after = database_snapshot(database_url)
    for table, rows in before["rows"].items():
        if table == "users":
            assert after["rows"][table] == [{**row, "role": "operator"} for row in rows]
        elif table != "schema_version":
            assert after["rows"][table] == rows, table


def test_a_late_database_failure_rolls_back_migration_ddl_and_data(legacy_database):
    database_url, _ = legacy_database
    before = database_snapshot(database_url)
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION test_reject_schema_bump() RETURNS trigger LANGUAGE plpgsql "
            "AS $$ BEGIN RAISE EXCEPTION 'synthetic schema bump failure'; END; $$"
        )
        conn.execute(
            "CREATE TRIGGER test_migration_failure BEFORE INSERT OR UPDATE OR DELETE ON schema_version "
            "FOR EACH ROW EXECUTE FUNCTION test_reject_schema_bump()"
        )
    try:
        with pytest.raises((psycopg.Error, RuntimeError)):
            migrate(database_url)
        assert database_snapshot(database_url) == before
    finally:
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute("DROP TRIGGER IF EXISTS test_migration_failure ON schema_version")
            conn.execute("DROP FUNCTION IF EXISTS test_reject_schema_bump()")
    migrate(database_url)
    require_current_schema(database_url)


@pytest.mark.parametrize("malformed", ["unknown-version", "missing-version-row"])
def test_unsupported_schema_metadata_is_refused_without_changes(legacy_database, malformed):
    database_url, _ = legacy_database
    with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as conn:
        if malformed == "missing-version-row":
            conn.execute("DELETE FROM schema_version")
        else:
            constraints = conn.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid='schema_version'::regclass "
                "AND contype='c' AND pg_get_constraintdef(oid) LIKE '%%version%%'"
            ).fetchall()
            assert len(constraints) == 1
            conn.execute(sql.SQL("ALTER TABLE schema_version DROP CONSTRAINT {}").format(
                sql.Identifier(constraints[0]["conname"])
            ))
            conn.execute("UPDATE schema_version SET version=99")
    before = database_snapshot(database_url)
    for operation in (migrate, initialize, require_current_schema):
        with pytest.raises(RuntimeError):
            operation(database_url)
        assert database_snapshot(database_url) == before


def test_missing_schema_requires_explicit_initialization_instead_of_implicit_migration(legacy_database):
    database_url, _ = legacy_database
    replace_test_schema(database_url)
    before = database_snapshot(database_url)
    for operation in (migrate, require_current_schema):
        with pytest.raises(RuntimeError):
            operation(database_url)
        assert database_snapshot(database_url) == before
    initialize(database_url)
    require_current_schema(database_url)
    assert database_snapshot(database_url)["rows"]["schema_version"] == [
        {"singleton": True, "version": 4}
    ]


def test_missing_metadata_does_not_relabel_remaining_legacy_tables_as_current(legacy_database):
    database_url, _ = legacy_database
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP TABLE schema_version")
    before = database_snapshot(database_url)
    for operation in (initialize, migrate, require_current_schema):
        with pytest.raises(RuntimeError):
            operation(database_url)
        assert database_snapshot(database_url) == before


def test_failure_in_second_upgrade_stage_rolls_back_the_entire_v1_chain(legacy_database):
    database_url, _ = legacy_database
    before = database_snapshot(database_url)
    with psycopg.connect(database_url) as conn:
        conn.execute("""CREATE FUNCTION test_reject_only_v3() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.version=3 THEN RAISE EXCEPTION 'synthetic second-stage upgrade failure';
            END IF; RETURN NEW; END; $$""")
        conn.execute("""CREATE TRIGGER test_second_upgrade_failure BEFORE UPDATE ON schema_version
            FOR EACH ROW EXECUTE FUNCTION test_reject_only_v3()""")
    try:
        with pytest.raises(psycopg.Error):
            migrate(database_url)
        assert database_snapshot(database_url) == before
    finally:
        with psycopg.connect(database_url) as conn:
            conn.execute("DROP TRIGGER IF EXISTS test_second_upgrade_failure ON schema_version")
            conn.execute("DROP FUNCTION IF EXISTS test_reject_only_v3()")
    migrate(database_url)
    require_current_schema(database_url)
