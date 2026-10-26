"""Public-demo controls against a new disposable schema-4 database.

Fixtures deliberately replace only the test database's synthetic rows. They
must never be pointed at a retained consumer or deployment database.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sys
from threading import Barrier, Event
from time import monotonic
from uuid import UUID, uuid4

from argon2.exceptions import VerificationError
from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

import shipment_workspace.app as app_module
import shipment_workspace.cli as cli_module
from shipment_workspace import __version__
from shipment_workspace.app import COOKIE, create_app
from shipment_workspace.config import Settings
from shipment_workspace.db import PASSWORDS, provision_demo, require_demo_identity
from shipment_workspace.public_demo import (DEMO_EMAIL, DEMO_USER_ID, RequestBudget,
                                             SESSION_LIMIT, SESSION_LOCK, session_slot)


ORIGIN = "https://demo.synthetic.example"
PUBLIC_PASSWORD = "Published-synthetic-reviewer-2026"
REVISION = "1" * 40
TABLES = ("login_identifiers", "sessions", "mutation_requests", "exception_events",
          "shipment_exceptions", "users", "organizations")


def settings(database, **changes):
    return Settings(**{"database_url": database, "origin": ORIGIN, "secure_cookie": True,
                       "public_demo": True, "demo_password": PUBLIC_PASSWORD,
                       "deployment_revision": REVISION, **changes})


def state(database, security=False):
    tables = ("shipment_exceptions", "exception_events", "mutation_requests")
    if security:
        tables += ("organizations", "users", "sessions", "login_identifiers", "login_global")
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall() for table in tables}


def clear_application(database):
    with psycopg.connect(database) as conn:
        conn.execute("TRUNCATE " + ",".join(TABLES) + " RESTART IDENTITY CASCADE")
        conn.execute("UPDATE login_global SET attempts=0,reset_at=clock_timestamp() WHERE singleton=true")


@pytest.fixture()
def empty_demo_database(database):
    clear_application(database)
    return database


@pytest.fixture()
def demo_database(empty_demo_database):
    provision_demo(empty_demo_database, PUBLIC_PASSWORD)
    return empty_demo_database


@pytest.fixture()
def demo_app(demo_database):
    return create_app(settings(demo_database))


@contextmanager
def visitor(app):
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        anonymous = client.get("/api/session")
        assert anonymous.status_code == 200, anonymous.text
        response = client.post("/api/login", json={"email": DEMO_EMAIL, "password": PUBLIC_PASSWORD}, headers={
            "Origin": ORIGIN, "X-CSRF-Token": anonymous.json()["csrf_token"],
        })
        assert response.status_code == 200, response.text
        payload = response.json()
        yield client, {"Origin": ORIGIN, "X-CSRF-Token": payload["csrf_token"],
                       "X-Workspace-Context": payload["session_context"], "Content-Type": "application/json"}


@pytest.mark.parametrize("origin", [
    "http://demo.synthetic.example", "https://user:password@demo.synthetic.example",
    "https://:password@demo.synthetic.example", "https://demo.synthetic.example/",
    "https://demo.synthetic.example/path", "https://demo.synthetic.example?query=1",
    "https://demo.synthetic.example#fragment", "https://demo.synthetic.example:443",
    "https://demo.synthetic.example:invalid", "https://demo.synthetic.example:99999",
    "https://Demo.synthetic.example", "https://demo..synthetic.example",
    "https://demo.synthetic.example\\other", "https://demo.synthetic.example\n",
])
def test_public_origin_requires_canonical_https_without_credentials(origin):
    with pytest.raises(ValueError):
        settings("postgresql://synthetic@127.0.0.1/synthetic", origin=origin)


@pytest.mark.parametrize("database", [
    "postgresql://synthetic@database.synthetic.example/synthetic",
    "postgresql://synthetic@database.synthetic.example/synthetic?sslmode=prefer",
    "postgresql://synthetic@database.synthetic.example/synthetic?sslmode=require&sslmode=disable",
    "postgresql://synthetic@127.0.0.1/synthetic?host=database.synthetic.example",
    "postgresql://synthetic@127.0.0.1/synthetic?hostaddr=192.0.2.1",
    "postgresql://synthetic@127.0.0.1/synthetic?service=other",
    "postgresql://synthetic@127.0.0.1,other.synthetic.example/synthetic?sslmode=require",
    "postgresql://synthetic@127.0.0.1/synthetic?port=6543",
    "postgresql://synthetic@127.0.0.1/synthetic?dbname=other",
    "postgresql://synthetic@127.0.0.1/synthetic?user=other",
    "postgresql://synthetic@127.0.0.1:99999/synthetic", "dbname=synthetic host=127.0.0.1",
])
def test_public_database_configuration_cannot_silently_select_another_transport(database):
    with pytest.raises(ValueError, match="PostgreSQL URL"):
        settings(database)


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_explicit_remote_tls_mode_is_admitted_without_claiming_a_connection(mode):
    value = settings(f"postgresql://synthetic@database.synthetic.example/synthetic?sslmode={mode}")
    assert value.public_demo


def test_public_password_and_revision_are_explicit_and_local_defaults_stay_local():
    for changes in ({"demo_password": None}, {"demo_password": "short"}, {"secure_cookie": False},
                    {"deployment_revision": "short"}, {"deployment_revision": "A" * 40}):
        with pytest.raises(ValueError):
            settings("postgresql://synthetic@127.0.0.1/synthetic", **changes)
    value = Settings("postgresql://synthetic@127.0.0.1/synthetic")
    assert not value.public_demo and not value.secure_cookie and value.demo_password is None
    with pytest.raises(ValueError):
        Settings(value.database_url, demo_password=PUBLIC_PASSWORD)


def test_public_cli_requires_revision_and_disables_implicit_forwarded_header_trust(monkeypatch):
    monkeypatch.setenv("SHIPMENT_DATABASE_URL", "postgresql://synthetic@127.0.0.1/synthetic")
    monkeypatch.setenv("SHIPMENT_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("SHIPMENT_PUBLIC_DEMO_PASSWORD", PUBLIC_PASSWORD)
    monkeypatch.delenv("SHIPMENT_SOURCE_REVISION", raising=False)
    monkeypatch.setattr(sys, "argv", ["shipment-workspace", "serve-demo", "--port", "10000"])
    with pytest.raises(SystemExit) as missing:
        cli_module.main()
    assert missing.value.code == 2
    captured = {}
    monkeypatch.setenv("SHIPMENT_SOURCE_REVISION", REVISION)
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    monkeypatch.setattr(cli_module, "create_app", lambda value: captured.setdefault("settings", value))
    monkeypatch.setattr(cli_module.uvicorn, "run", lambda app, **options: captured.setdefault("server", options))
    cli_module.main()
    assert captured["settings"].deployment_revision == REVISION
    assert captured["server"] == {"host": "0.0.0.0", "port": 10000, "proxy_headers": False,
                                  "forwarded_allow_ips": "", "workers": 1, "limit_concurrency": 8,
                                  "timeout_keep_alive": 5, "access_log": False, "log_level": "warning"}


def test_empty_provisioning_separates_public_password_from_all_stock_accounts(demo_database):
    require_demo_identity(demo_database, PUBLIC_PASSWORD)
    with psycopg.connect(demo_database, row_factory=dict_row) as conn:
        users = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [{"version": 4}]
    assert len(users) == 7
    for user in users:
        if user["id"] == DEMO_USER_ID:
            assert user["email"] == DEMO_EMAIL and user["role"] == "reviewer"
            assert PASSWORDS.verify(user["password_hash"], PUBLIC_PASSWORD)
        else:
            with pytest.raises(VerificationError):
                PASSWORDS.verify(user["password_hash"], PUBLIC_PASSWORD)


def test_repeated_provisioning_refuses_without_changing_existing_state(demo_database):
    before = state(demo_database, security=True)
    with pytest.raises(RuntimeError, match="empty application state"):
        provision_demo(demo_database, "Another-public-password-2026")
    assert state(demo_database, security=True) == before


def test_stock_seed_state_is_not_repurposed_as_a_public_demo(database):
    before = state(database, security=True)
    with pytest.raises(RuntimeError, match="empty application state"):
        provision_demo(database, PUBLIC_PASSWORD)
    assert state(database, security=True) == before


def test_provisioning_failure_rolls_back_earlier_synthetic_inserts(empty_demo_database):
    database = empty_demo_database
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("CREATE FUNCTION demo_reject_visitor() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic provision failure'; END; $$")
        conn.execute(f"CREATE TRIGGER demo_provision_failure BEFORE INSERT ON users FOR EACH ROW WHEN (NEW.id='{DEMO_USER_ID}'::uuid) EXECUTE FUNCTION demo_reject_visitor()")
    before = state(database, security=True)
    try:
        with pytest.raises(psycopg.errors.RaiseException):
            provision_demo(database, PUBLIC_PASSWORD)
        assert state(database, security=True) == before
    finally:
        with psycopg.connect(database, autocommit=True) as conn:
            conn.execute("DROP TRIGGER demo_provision_failure ON users")
            conn.execute("DROP FUNCTION demo_reject_visitor()")


def test_startup_requires_matching_provisioned_identity_and_does_not_seed(demo_database):
    before = state(demo_database, security=True)
    with pytest.raises(RuntimeError, match="credential"):
        create_app(settings(demo_database, demo_password="Wrong-public-password-2026"))
    assert state(demo_database, security=True) == before
    with psycopg.connect(demo_database) as conn:
        conn.execute("UPDATE users SET role='operator' WHERE id=%s", (DEMO_USER_ID,))
    before = state(demo_database, security=True)
    with pytest.raises(RuntimeError, match="separate synthetic reviewer"):
        create_app(settings(demo_database))
    assert state(demo_database, security=True) == before


def test_public_cookie_descriptor_and_stock_account_denials_use_actual_credentials(demo_app, demo_database):
    with TestClient(demo_app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        anonymous = client.get("/api/session")
        assert anonymous.status_code == 200
        assert anonymous.json()["demo"] == {"read_only": True, "email": DEMO_EMAIL, "password": PUBLIC_PASSWORD}
        cookie = anonymous.headers["set-cookie"].lower()
        assert all(value in cookie for value in ("secure", "httponly", "samesite=strict", "path=/", "max-age=300"))
        with psycopg.connect(demo_database) as conn:
            emails = [row[0] for row in conn.execute("SELECT email FROM users WHERE id<>%s ORDER BY email", (DEMO_USER_ID,))]
        for email in emails:
            rejected = client.post("/api/login", json={"email": email, "password": PUBLIC_PASSWORD}, headers={
                "Origin": ORIGIN, "X-CSRF-Token": anonymous.json()["csrf_token"],
            })
            assert rejected.status_code == 401 and rejected.json()["error"]["code"] == "invalid_credentials"
        response = client.post("/api/login", json={"email": DEMO_EMAIL, "password": PUBLIC_PASSWORD}, headers={
            "Origin": ORIGIN, "X-CSRF-Token": anonymous.json()["csrf_token"],
        })
        assert response.status_code == 200 and response.json()["user"]["role"] == "reviewer"
        assert response.json()["demo"] == anonymous.json()["demo"]
        assert "max-age=1800" in response.headers["set-cookie"].lower()


def test_public_direct_reads_and_business_denials_preserve_organization_and_receipts(demo_app, demo_database):
    with visitor(demo_app) as (client, headers):
        queue = client.get("/api/exceptions").json()["items"]
        assert queue and all(item["reference"].startswith("NL-") for item in queue)
        own, foreign, absent = str(UUID(int=101)), str(UUID(int=201)), str(uuid4())
        assert client.get(f"/api/exceptions/{own}").status_code == 200
        for suffix in ("", "/history"):
            missing = client.get(f"/api/exceptions/{absent}{suffix}")
            outside = client.get(f"/api/exceptions/{foreign}{suffix}")
            assert outside.status_code == missing.status_code == 404 and outside.json() == missing.json()
        spoofed = client.get("/api/exceptions", headers={"X-Role": "operator", "X-Organization-ID": str(UUID(int=2))})
        assert spoofed.json()["items"] == queue
        before = state(demo_database)
        attempts = [("/api/exceptions", {"reference": "DEMO-DENIED", "summary": "Synthetic denied intake", "details": "Must not be saved", "priority": "normal"})]
        for item_id in (own, foreign, absent):
            attempts += [(f"/api/exceptions/{item_id}/assign", {"expected_version": 1, "assignee_id": None}),
                         (f"/api/exceptions/{item_id}/resolve", {"expected_version": 1, "resolution": "Must not be saved"})]
        for path, body in attempts:
            response = client.post(path, json=body, headers={**headers, "Idempotency-Key": str(uuid4())})
            assert response.status_code == 403 and response.json()["error"]["code"] == "read_only"
            assert "Idempotency-Replayed" not in response.headers
        assert state(demo_database) == before


def test_provisioned_synthetic_history_supplies_consistent_read_only_filter_examples(demo_app, demo_database):
    before = state(demo_database)
    assert len(before["shipment_exceptions"]) == 5 and len(before["exception_events"]) == 5
    assert before["mutation_requests"] == []
    with visitor(demo_app) as (client, _):
        opened = client.get("/api/exceptions", params={"status": "open"}).json()["items"]
        resolved = client.get("/api/exceptions", params={"status": "resolved"}).json()["items"]
        assert {item["reference"] for item in opened} == {"NL-1042", "NL-1091"}
        assert [item["reference"] for item in resolved] == ["NL-1086"]
        completed = client.get(f"/api/exceptions/{UUID(int=102)}").json()
        assert completed["exception"]["status"] == "resolved" and completed["exception"]["version"] == 3
        assert completed["exception"]["assignee_name"] == "Sam Rivera"
        assert "Provisioned synthetic fixture" in completed["exception"]["resolution"]
        assert [(event["action"], event["version"]) for event in completed["events"]] == [
            ("created", 1), ("assigned", 2), ("resolved", 3)]
        assert completed["events"][-1]["note"] == completed["exception"]["resolution"]
        assert completed["events"][-1]["created_at"] == completed["exception"]["updated_at"]
        pending = client.get(f"/api/exceptions/{UUID(int=103)}").json()
        assert pending["exception"]["status"] == "open" and pending["exception"]["version"] == 2
        assert pending["exception"]["assignee_name"] == "Sam Rivera"
        assert [(event["action"], event["version"]) for event in pending["events"]] == [("created", 1), ("assigned", 2)]
    assert state(demo_database) == before


@pytest.mark.parametrize("action", ["create", "assign", "resolve"])
def test_public_mode_denies_actual_matching_saved_receipt_before_reading_it(demo_app, demo_database, action):
    key = uuid4()
    # Establish the historical receipt through the ordinary API while this
    # disposable actor is an operator, then revoke that fixture-only access.
    with psycopg.connect(demo_database) as conn:
        conn.execute("UPDATE users SET role='operator' WHERE id=%s", (DEMO_USER_ID,))
    ordinary = create_app(Settings(demo_database, origin=ORIGIN, secure_cookie=True))
    if action == "create":
        path = "/api/exceptions"
        body = {"reference": "DEMO-REPLAY", "summary": "Synthetic historical intent", "details": "No replay permission", "priority": "normal"}
        expected_status = 201
    elif action == "assign":
        path = f"/api/exceptions/{UUID(int=101)}/assign"
        body = {"expected_version": 1, "assignee_id": str(UUID(int=13))}
        expected_status = 200
    else:
        path = f"/api/exceptions/{UUID(int=101)}/resolve"
        body = {"expected_version": 1, "resolution": "Earlier authorized synthetic resolution"}
        expected_status = 200
    with visitor(ordinary) as (writer, headers):
        committed = writer.post(path, json=body, headers={**headers, "Idempotency-Key": str(key)})
        assert committed.status_code == expected_status and committed.headers["Idempotency-Replayed"] == "false"
    with psycopg.connect(demo_database) as conn:
        conn.execute("UPDATE users SET role='reviewer' WHERE id=%s", (DEMO_USER_ID,))
    with visitor(demo_app) as (client, headers):
        before = state(demo_database)
        response = client.post(path, json=body, headers={**headers, "Idempotency-Key": str(key)})
        assert response.status_code == 403 and response.json()["error"]["code"] == "read_only"
        assert "Idempotency-Replayed" not in response.headers
        assert state(demo_database) == before


def test_public_session_refuses_promoted_reviewer_or_preexisting_operator_cookie(demo_app, demo_database):
    with visitor(demo_app) as (client, headers):
        with psycopg.connect(demo_database) as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=%s", (DEMO_USER_ID,))
        before = state(demo_database)
        assert client.get("/api/exceptions").status_code == 401
        response = client.post("/api/exceptions", json={"reference": "PROMOTED-DENIED", "summary": "Denied", "details": "Denied", "priority": "normal"}, headers={**headers, "Idempotency-Key": str(uuid4())})
        assert response.status_code == 401 and state(demo_database) == before
    token = "synthetic-old-operator-token"
    with psycopg.connect(demo_database) as conn:
        conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES (%s,%s,'synthetic',clock_timestamp()+interval '30 minutes')",
                     (sha256(token.encode()).hexdigest(), UUID(int=11)))
    with TestClient(demo_app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        client.cookies.set(COOKIE, token)
        assert client.get("/api/exceptions").status_code == 401


def fill_sessions(database, count=SESSION_LIMIT, *, expired=False):
    with psycopg.connect(database) as conn:
        conn.execute("INSERT INTO sessions(token_hash,csrf_token,expires_at) SELECT 'capacity-'||n,'synthetic-capacity-'||n,clock_timestamp()+(%s * interval '1 second') FROM generate_series(1,%s) AS n",
                     (-1 if expired else 300, count))


def test_session_cap_refuses_allocations_then_recovers_expired_slots(demo_app, demo_database):
    fill_sessions(demo_database)
    before = state(demo_database, security=True)
    with TestClient(demo_app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        response = client.get("/api/session")
        assert response.status_code == 429 and response.headers["Retry-After"] == "60"
        assert response.json()["error"]["code"] == "demo_sessions_full" and "set-cookie" not in response.headers
        assert state(demo_database, security=True) == before
        with psycopg.connect(demo_database) as conn:
            conn.execute("UPDATE sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE token_hash='capacity-1'")
        response = client.get("/api/session")
        assert response.status_code == 200
        after = state(demo_database, security=True)
        assert len(after["sessions"]) == SESSION_LIMIT
        assert all(row["token_hash"] != "capacity-1" for row in after["sessions"])


def test_two_independent_clients_compete_for_one_remaining_session_slot(demo_app, demo_database):
    fill_sessions(demo_database, SESSION_LIMIT - 1)
    start = Barrier(2, timeout=10)

    def worker():
        with TestClient(demo_app, base_url=ORIGIN, raise_server_exceptions=False) as client:
            start.wait()
            return client.get("/api/session")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        responses = [future.result(timeout=20) for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 429]
    assert len(state(demo_database, security=True)["sessions"]) == SESSION_LIMIT


def test_session_admission_samples_expiry_after_waiting_for_its_transaction_lock(demo_database):
    fill_sessions(demo_database)
    interval = Event()

    def admission():
        with psycopg.connect(demo_database, autocommit=True, row_factory=dict_row) as conn, conn.transaction():
            return session_slot(conn)

    with psycopg.connect(demo_database) as holder, psycopg.connect(demo_database, autocommit=True) as observer:
        holder_pid = holder.execute("SELECT pg_backend_pid()").fetchone()[0]
        holder.execute("SELECT pg_advisory_xact_lock(%s,%s)", SESSION_LOCK)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(admission)
            try:
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    waiting = observer.execute("SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND %s=ANY(pg_blocking_pids(pid)) AND wait_event_type='Lock'", (holder_pid,)).fetchone()
                    if waiting:
                        break
                    if future.done():
                        pytest.fail("Session admission completed without waiting for the held transaction lock")
                    interval.wait(0.01)
                else:
                    pytest.fail("PostgreSQL did not report the expected session-admission lock wait")
                # Expiry is later than the waiting transaction's start. The
                # post-lock wall clock must observe it as expired nonetheless.
                holder.execute("UPDATE sessions SET expires_at=clock_timestamp() WHERE token_hash='capacity-1'")
                holder.commit()
                assert future.result(timeout=20) is not None
            finally:
                holder.rollback()
    assert len(state(demo_database, security=True)["sessions"]) == SESSION_LIMIT - 1


def test_login_replaces_anonymous_session_at_capacity_and_failure_restores_it(demo_app, demo_database):
    with TestClient(demo_app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        anonymous = client.get("/api/session").json()
        fill_sessions(demo_database, SESSION_LIMIT - 1)
        headers = {"Origin": ORIGIN, "X-CSRF-Token": anonymous["csrf_token"]}
        before = state(demo_database, security=True)["sessions"]
        with psycopg.connect(demo_database, autocommit=True) as conn:
            conn.execute("CREATE FUNCTION demo_reject_session() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic session failure'; END; $$")
            conn.execute("CREATE TRIGGER demo_session_failure BEFORE INSERT ON sessions FOR EACH ROW WHEN (NEW.user_id IS NOT NULL) EXECUTE FUNCTION demo_reject_session()")
        try:
            failed = client.post("/api/login", json={"email": DEMO_EMAIL, "password": PUBLIC_PASSWORD}, headers=headers)
            assert failed.status_code == 500
            assert state(demo_database, security=True)["sessions"] == before
            assert client.get("/api/session").json()["csrf_token"] == anonymous["csrf_token"]
        finally:
            with psycopg.connect(demo_database, autocommit=True) as conn:
                conn.execute("DROP TRIGGER demo_session_failure ON sessions")
                conn.execute("DROP FUNCTION demo_reject_session()")
        response = client.post("/api/login", json={"email": DEMO_EMAIL, "password": PUBLIC_PASSWORD}, headers=headers)
        assert response.status_code == 200
        assert len(state(demo_database, security=True)["sessions"]) == SESSION_LIMIT


def test_restart_and_expiry_keep_public_session_context_authoritative(demo_app, demo_database):
    with visitor(demo_app) as (client, headers):
        before = state(demo_database, security=True)
        restarted = create_app(settings(demo_database))
        assert state(demo_database, security=True) == before
        with TestClient(restarted, base_url=ORIGIN, raise_server_exceptions=False) as replacement:
            replacement.cookies.update(dict(client.cookies))
            response = replacement.get("/api/session")
            assert response.json()["session_context"] == headers["X-Workspace-Context"]
            digest = sha256(replacement.cookies.get(COOKIE).encode()).hexdigest()
            with psycopg.connect(demo_database) as conn:
                conn.execute("UPDATE sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE token_hash=%s", (digest,))
            assert replacement.get("/api/exceptions", headers=headers).status_code == 401
            recovered = replacement.get("/api/session")
            assert recovered.status_code == 200 and not recovered.json()["authenticated"]
            assert recovered.json()["session_context"] != headers["X-Workspace-Context"]


def test_public_origin_csrf_host_and_forwarded_headers_cannot_grant_authority(demo_app, demo_database):
    with visitor(demo_app) as (client, headers):
        before = state(demo_database, security=True)
        for changed in ({"Origin": "https://foreign.synthetic.example"}, {"X-CSRF-Token": "wrong"}):
            response = client.post("/api/logout", headers={**headers, **changed})
            assert response.status_code == 403
        response = client.get("/api/session", headers={"Host": "foreign.synthetic.example", "X-Forwarded-Host": "demo.synthetic.example", "X-Forwarded-Proto": "https"})
        assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_host"
        assert "set-cookie" not in response.headers
        assert response.headers["Cache-Control"] == "no-store" and response.headers["X-Content-Type-Options"] == "nosniff"
        response = client.get("/api/session", headers={"X-Forwarded-Host": "foreign.synthetic.example", "X-Forwarded-Proto": "http", "X-Forwarded-For": "127.0.0.1"})
        assert response.status_code == 200 and response.json()["user"]["email"] == DEMO_EMAIL
        assert state(demo_database, security=True) == before
        logout = client.post("/api/logout", headers=headers)
        assert logout.status_code == 204
        assert "secure" in logout.headers["set-cookie"].lower()
        assert client.get("/api/exceptions").status_code == 401


def test_public_api_slash_and_missing_routes_never_redirect_to_backend_http(demo_app, demo_database):
    before = state(demo_database, security=True)
    # This scheme models the provider-to-container hop. Its Host remains the
    # configured public authority and forwarded headers are not trusted.
    with TestClient(demo_app, base_url="http://demo.synthetic.example", raise_server_exceptions=False) as client:
        for path in ("/api/session/", "/api/ready/", "/api/version/", "/api/not-a-route"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 404
            assert "Location" not in response.headers and "set-cookie" not in response.headers
    assert state(demo_database, security=True) == before


def test_readiness_version_and_budget_do_not_allocate_sessions_or_reset_business(demo_app, demo_database, monkeypatch):
    before = state(demo_database, security=True)
    with TestClient(demo_app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        assert client.get("/api/ready").json() == {"ready": True}
        assert client.get("/api/version").json() == {"version": __version__, "revision": REVISION, "public_demo": True}
        assert state(demo_database, security=True) == before
        monkeypatch.setattr(demo_app.state.demo_request_budget, "admit", lambda: False)
        denied = client.get("/api/session")
        assert denied.status_code == 429 and denied.headers["Retry-After"] == "1"
        assert "set-cookie" not in denied.headers
        assert denied.headers["Cache-Control"] == "no-store" and denied.headers["X-Content-Type-Options"] == "nosniff"
        assert client.get("/api/ready").status_code == 200
        assert state(demo_database, security=True) == before
        def unavailable(_):
            raise RuntimeError("private synthetic database failure")
        monkeypatch.setattr(app_module, "require_current_schema", unavailable)
        response = client.get("/api/ready")
        assert response.status_code == 503 and response.json() == {"ready": False}
        assert "private" not in response.text


def test_process_budget_has_a_bounded_burst_and_refills_without_sleeping():
    now = [0.0]
    budget = RequestBudget(clock=lambda: now[0])
    assert all(budget.admit() for _ in range(30))
    assert not budget.admit()
    now[0] = 0.2
    assert budget.admit() and not budget.admit()
    now[0] = 100
    assert all(budget.admit() for _ in range(30)) and not budget.admit()
