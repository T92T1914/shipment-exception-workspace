"""Upgrade accepted schemas without resetting access or retained business state."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1, sha256
from pathlib import Path
from threading import Barrier
from uuid import UUID

from fastapi.testclient import TestClient
import psycopg
import pytest

from conftest import ORIGIN
from shipment_workspace.app import create_app
from shipment_workspace.config import Settings
from shipment_workspace.db import initialize, migrate, require_current_schema
from test_login_migration import (
    CREATION_BODY, LEGACY_CSRF, LEGACY_KEY, LEGACY_SESSION, database_snapshot,
    insert_v2_rows, replace_test_schema,
)
from test_migration import insert_legacy_rows

FIXTURES = Path(__file__).with_name("fixtures")


@pytest.fixture()
def v3_database(database_url):
    replace_test_schema(database_url, (FIXTURES / "schema_v3.sql").read_text())
    try:
        response = insert_v2_rows(database_url)
        with psycopg.connect(database_url) as conn:
            conn.execute("UPDATE login_global SET attempts=17,reset_at='2035-01-01T00:00:00Z'")
            conn.execute("INSERT INTO login_identifiers(identifier_hash,attempts,reset_at) VALUES (%s,7,'2035-01-01T00:00:00Z')",
                         (sha256(b"retained-v3@synthetic.example").hexdigest(),))
        yield database_url, response
    finally:
        replace_test_schema(database_url)
        initialize(database_url)


def assert_v3_preserved(before, after):
    assert before["rows"]["schema_version"] == [{"singleton": True, "version": 3}]
    assert after["rows"]["schema_version"] == [{"singleton": True, "version": 4}]
    for table, rows in before["rows"].items():
        if table == "users":
            assert after["rows"][table] == [{**row, "role": "operator"} for row in rows]
        elif table != "schema_version":
            assert after["rows"][table] == rows, table


def test_v3_fixture_is_exact_accepted_source():
    raw = (FIXTURES / "schema_v3.sql").read_bytes()
    assert sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == "1cd24211bec132199e87a7f1ad4175be381fbf9d"


def test_v3_upgrade_keeps_sessions_receipts_history_and_live_admission(v3_database):
    database, original = v3_database
    before = database_snapshot(database)
    migrate(database)
    require_current_schema(database)
    after = database_snapshot(database)
    assert_v3_preserved(before, after)
    app = create_app(Settings(database_url=database, origin=ORIGIN, secure_cookie=False))
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("shipment_session", LEGACY_SESSION)
        session = client.get("/api/session")
        assert session.status_code == 200 and session.json()["user"]["role"] == "operator"
        replay = client.post("/api/exceptions", json=CREATION_BODY,
                             headers={"Origin": ORIGIN, "X-CSRF-Token": LEGACY_CSRF,
                                      "Idempotency-Key": str(LEGACY_KEY)})
        assert replay.status_code == 201 and replay.json() == original
        assert replay.headers["idempotency-replayed"] == "true"
    assert database_snapshot(database) == after


def test_v3_needs_explicit_upgrade_before_init_or_app(v3_database):
    database, _ = v3_database
    before = database_snapshot(database)
    for operation in (initialize, require_current_schema):
        with pytest.raises(RuntimeError, match="version 4"):
            operation(database)
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url=database, origin=ORIGIN, secure_cookie=False))
    assert database_snapshot(database) == before


def test_v4_default_denies_new_user_writes_and_repeat_upgrade_preserves_roles(v3_database):
    database, _ = v3_database
    migrate(database)
    with psycopg.connect(database) as conn:
        actor, org = conn.execute("SELECT id,organization_id FROM users").fetchone()
        conn.execute("UPDATE users SET role='reviewer' WHERE id=%s", (actor,))
        role = conn.execute("INSERT INTO users(id,organization_id,email,name,password_hash) VALUES (%s,%s,%s,%s,%s) RETURNING role",
                            (UUID(int=20012), org, "new-reviewer@synthetic.example", "New reviewer", "unused-synthetic-hash")).fetchone()[0]
        assert role == "reviewer"
    before = database_snapshot(database)
    initialize(database)
    migrate(database)
    assert database_snapshot(database) == before
    with psycopg.connect(database) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE users SET role='administrator'")
    assert database_snapshot(database) == before


def test_two_v3_migrators_preserve_all_rows_once(v3_database):
    database, _ = v3_database
    before = database_snapshot(database)
    barrier = Barrier(2, timeout=10)
    def worker():
        barrier.wait()
        migrate(database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(worker) for _ in range(2)]
        for task in tasks:
            task.result(timeout=20)
    assert_v3_preserved(before, database_snapshot(database))


@pytest.mark.parametrize("source_version", [1, 2, 3])
def test_late_v4_failure_rolls_back_entire_required_chain(database_url, source_version):
    replace_test_schema(database_url, (FIXTURES / f"schema_v{source_version}.sql").read_text())
    try:
        (insert_legacy_rows if source_version == 1 else insert_v2_rows)(database_url)
        before = database_snapshot(database_url)
        with psycopg.connect(database_url) as conn:
            conn.execute("""CREATE FUNCTION test_reject_v4() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.version=4 THEN RAISE EXCEPTION 'synthetic final access upgrade failure';
                END IF; RETURN NEW; END; $$""")
            conn.execute("CREATE TRIGGER test_v4_failure BEFORE UPDATE ON schema_version FOR EACH ROW EXECUTE FUNCTION test_reject_v4()")
        with pytest.raises(psycopg.Error):
            migrate(database_url)
        assert database_snapshot(database_url) == before
        with psycopg.connect(database_url) as conn:
            assert conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='users' AND column_name='role'").fetchone()[0] == 0
            conn.execute("DROP TRIGGER test_v4_failure ON schema_version")
            conn.execute("DROP FUNCTION test_reject_v4()")
        migrate(database_url)
        require_current_schema(database_url)
    finally:
        replace_test_schema(database_url)
        initialize(database_url)
