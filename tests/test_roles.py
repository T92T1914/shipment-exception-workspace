"""Reviewer authorization and role-change ordering on disposable PostgreSQL.

The race checks observe actual blocked database backends. A short polling wait
is only a diagnostic interval, never the evidence that a writer was blocked.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from conftest import TEST_PASSWORD, authenticated_client
import shipment_workspace.app as app_module
from shipment_workspace.db import seed


REVIEWERS = [
    ("casey@northline.example", "alex@northline.example", UUID(int=13), UUID(int=101), UUID(int=201)),
    ("taylor@harbor.example", "jules@harbor.example", UUID(int=23), UUID(int=201), UUID(int=101)),
]


def workflow_state(database):
    """Compare complete persisted business rows, not just response counts."""
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return {
            "exceptions": conn.execute("SELECT * FROM shipment_exceptions ORDER BY id").fetchall(),
            "events": conn.execute("SELECT * FROM exception_events ORDER BY id").fetchall(),
            "receipts": conn.execute(
                "SELECT * FROM mutation_requests ORDER BY organization_id,actor_id,key"
            ).fetchall(),
        }


def post_change(client, headers, path, body, key=None, extra_headers=None):
    return client.post(path, json=body, headers={
        **headers, "Idempotency-Key": key or str(uuid4()), **(extra_headers or {}),
    })


def create_body(reference="ROLE-CHECK"):
    return {
        "reference": reference,
        "summary": "Synthetic reviewer access check",
        "details": "A reviewer can inspect this workflow without changing it.",
        "priority": "normal",
    }


def assert_read_only(response):
    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "read_only"
    assert isinstance(error["message"], str) and error["message"]
    assert "Idempotency-Replayed" not in response.headers
    return response.json()


def set_role(database, user_id, role):
    with psycopg.connect(database) as conn:
        conn.execute("UPDATE users SET role=%s WHERE id=%s", (role, user_id))


def wait_for_block(observer, blocker_pid, future, target_pid=None):
    """Require a live lock wait whose blocker is the known held transaction."""
    deadline = monotonic() + 3
    interval = Event()
    while monotonic() < deadline:
        row = observer.execute(
            "SELECT pid,query,wait_event_type FROM pg_stat_activity "
            "WHERE datname=current_database() AND pid<>pg_backend_pid() "
            "AND %s=ANY(pg_blocking_pids(pid)) AND wait_event_type='Lock' "
            "AND (%s::integer IS NULL OR pid=%s) ORDER BY pid LIMIT 1",
            (blocker_pid, target_pid, target_pid),
        ).fetchone()
        if row:
            return row
        if future.done():
            pytest.fail("The competing operation completed without the required database lock wait")
        interval.wait(0.01)
    pytest.fail("PostgreSQL did not report the required lock wait before the bounded deadline")


def test_seed_roles_and_new_user_default_are_explicit(database):
    with psycopg.connect(database, autocommit=True, row_factory=dict_row) as conn:
        roles = {row["email"]: row["role"] for row in conn.execute(
            "SELECT email,role FROM users ORDER BY email"
        ).fetchall()}
        assert roles == {
            "alex@northline.example": "operator", "sam@northline.example": "operator",
            "jules@harbor.example": "operator", "robin@harbor.example": "operator",
            "casey@northline.example": "reviewer", "taylor@harbor.example": "reviewer",
        }
        for email, _, expected_id, _, _ in REVIEWERS:
            assert conn.execute("SELECT id FROM users WHERE email=%s", (email,)).fetchone()["id"] == expected_id
        new_id = uuid4()
        inserted = conn.execute(
            "INSERT INTO users(id,organization_id,email,name,password_hash) "
            "SELECT %s,organization_id,%s,'Default role fixture',password_hash "
            "FROM users WHERE email='alex@northline.example' RETURNING role",
            (new_id, f"future-{new_id.hex}@synthetic.example"),
        ).fetchone()
        assert inserted["role"] == "reviewer"
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE users SET role='administrator' WHERE id=%s", (new_id,))
        assert conn.execute("SELECT role FROM users WHERE id=%s", (new_id,)).fetchone()["role"] == "reviewer"


@pytest.mark.parametrize("email,operator,reviewer_id,own_id,foreign_id", REVIEWERS)
def test_reviewers_can_read_only_their_organization_and_sign_out(
    app, database, email, operator, reviewer_id, own_id, foreign_id
):
    with authenticated_client(app, operator) as (writer, writer_headers):
        changed = post_change(writer, writer_headers, f"/api/exceptions/{own_id}/assign", {
            "expected_version": 1, "assignee_id": str(reviewer_id),
        })
        assert changed.status_code == 200, changed.text
    with authenticated_client(app, email) as (client, headers):
        session = client.get("/api/session")
        assert session.status_code == 200
        assert session.json()["user"]["role"] == "reviewer"
        assert session.json()["user"]["id"] == str(reviewer_id)
        queue = client.get("/api/exceptions", params={"limit": 1, "status": "open"})
        assert queue.status_code == 200, queue.text
        assert len(queue.json()["items"]) == 1
        assert queue.json()["next_cursor"]
        continued = client.get("/api/exceptions", params={
            "limit": 1, "status": "open", "cursor": queue.json()["next_cursor"],
        })
        assert continued.status_code == 200, continued.text
        assert queue.json()["items"][0]["id"] != continued.json()["items"][0]["id"]
        detail = client.get(f"/api/exceptions/{own_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["exception"]["assignee_id"] == str(reviewer_id)
        assert detail.json()["events"][0]["action"] == "assigned"
        members = client.get("/api/members")
        assert members.status_code == 200, members.text
        assert len(members.json()["items"]) == 3
        assert email in {item["email"] for item in members.json()["items"]}
        foreign = client.get(f"/api/exceptions/{foreign_id}")
        missing = client.get(f"/api/exceptions/{uuid4()}")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        before = workflow_state(database)
        logged_out = client.post("/api/logout", headers=headers)
        assert logged_out.status_code == 204, logged_out.text
        assert client.get("/api/exceptions").status_code == 401
        assert workflow_state(database) == before


@pytest.mark.parametrize("email,operator,reviewer_id,own_id,foreign_id", REVIEWERS)
def test_every_reviewer_write_denies_without_business_or_receipt_changes(
    app, database, email, operator, reviewer_id, own_id, foreign_id
):
    with authenticated_client(app, email) as (client, headers):
        before = workflow_state(database)
        denied = [post_change(client, headers, "/api/exceptions", create_body())]
        for item_id in (own_id, foreign_id, uuid4()):
            denied.append(post_change(client, headers, f"/api/exceptions/{item_id}/assign", {
                "expected_version": 1, "assignee_id": str(reviewer_id),
            }))
            denied.append(post_change(client, headers, f"/api/exceptions/{item_id}/resolve", {
                "expected_version": 1, "resolution": "Not permitted for this actor.",
            }))
        errors = [assert_read_only(response) for response in denied]
        assert all(error == errors[0] for error in errors)
        assert workflow_state(database) == before


def test_forged_role_identity_and_organization_headers_do_not_grant_access(app, database, identities):
    with authenticated_client(app, "casey@northline.example") as (client, headers):
        ordinary = client.get("/api/exceptions")
        assert ordinary.status_code == 200
        spoofed = {
            "X-Role": "operator", "X-User-ID": str(identities["alex@northline.example"]["id"]),
            "X-Organization-ID": str(identities["jules@harbor.example"]["organization_id"]),
        }
        queue = client.get("/api/exceptions", headers=spoofed)
        assert queue.status_code == 200
        assert queue.json() == ordinary.json()
        before = workflow_state(database)
        assert_read_only(post_change(client, headers, "/api/exceptions", create_body(), extra_headers=spoofed))
        for name, value in (("role", "operator"), ("user_id", spoofed["X-User-ID"]),
                            ("organization_id", spoofed["X-Organization-ID"])):
            rejected = post_change(client, headers, "/api/exceptions", {**create_body(), name: value})
            assert rejected.status_code == 422, rejected.text
            assert rejected.json()["error"]["code"] == "invalid_input"
        assert workflow_state(database) == before


def test_reviewer_denial_does_not_wait_for_an_uncommitted_receipt_reservation(app, database, identities):
    with authenticated_client(app, "casey@northline.example") as (client, headers):
        reviewer = identities["casey@northline.example"]
        key = str(uuid4())
        before = workflow_state(database)
        with psycopg.connect(database) as holder:
            try:
                # This conflicting unique key is uncommitted throughout the
                # HTTP request. Reserving it before authorization would wait,
                # then fail on the application's finite database lock timeout.
                holder.execute(
                    "INSERT INTO mutation_requests(organization_id,actor_id,key,fingerprint) VALUES (%s,%s,%s,%s)",
                    (reviewer["organization_id"], reviewer["id"], key, "uncommitted fixture reservation"),
                )
                assert holder.execute("SELECT count(*) FROM mutation_requests WHERE actor_id=%s AND key=%s",
                                      (reviewer["id"], key)).fetchone()[0] == 1
                assert_read_only(post_change(client, headers, "/api/exceptions", create_body("ROLE-NO-RESERVE"), key))
                assert workflow_state(database) == before
            finally:
                holder.rollback()
        assert workflow_state(database) == before


def test_current_database_role_changes_existing_session_without_another_login(
    northline, database, identities
):
    client, headers = northline
    actor = identities["alex@northline.example"]["id"]
    cookies = dict(client.cookies)
    assert client.get("/api/session").json()["user"]["role"] == "operator"
    set_role(database, actor, "reviewer")
    assert client.get("/api/session").json()["user"]["role"] == "reviewer"
    assert dict(client.cookies) == cookies
    assert client.get("/api/exceptions").status_code == 200
    before = workflow_state(database)
    key = str(uuid4())
    body = create_body("ROLE-DENIED-KEY")
    assert_read_only(post_change(client, headers, "/api/exceptions", body, key))
    assert workflow_state(database) == before
    set_role(database, actor, "operator")
    assert client.get("/api/session").json()["user"]["role"] == "operator"
    accepted = post_change(client, headers, "/api/exceptions", body, key)
    assert accepted.status_code == 201, accepted.text
    assert accepted.headers["Idempotency-Replayed"] == "false"
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM mutation_requests WHERE actor_id=%s AND key=%s",
                            (actor, key)).fetchone()[0] == 1


@pytest.mark.parametrize("action", ["create", "assign", "resolve"])
def test_role_denial_precedes_saved_receipt_replay_and_preserves_that_receipt(
    northline, database, identities, action
):
    client, headers = northline
    actor = identities["alex@northline.example"]["id"]
    key = str(uuid4())
    item_id = str(UUID(int=101))
    if action == "create":
        path, body, expected_status = "/api/exceptions", create_body("ROLE-RECEIPT"), 201
    elif action == "assign":
        path, body, expected_status = f"/api/exceptions/{item_id}/assign", {
            "expected_version": 1, "assignee_id": str(UUID(int=13)),
        }, 200
    else:
        path, body, expected_status = f"/api/exceptions/{item_id}/resolve", {
            "expected_version": 1, "resolution": "Original authorized resolution.",
        }, 200
    original = post_change(client, headers, path, body, key)
    assert original.status_code == expected_status, original.text
    if action == "create":
        item_id = original.json()["exception"]["id"]
        later = post_change(client, headers, f"/api/exceptions/{item_id}/assign", {
            "expected_version": 1, "assignee_id": str(UUID(int=13)),
        })
        assert later.status_code == 200, later.text
    elif action == "assign":
        later = post_change(client, headers, f"/api/exceptions/{item_id}/resolve", {
            "expected_version": 2, "resolution": "A later authorized workflow change.",
        })
        assert later.status_code == 200, later.text
    before = workflow_state(database)
    set_role(database, actor, "reviewer")
    assert_read_only(post_change(client, headers, path, body, key))
    assert workflow_state(database) == before
    set_role(database, actor, "operator")
    replay = post_change(client, headers, path, body, key)
    assert replay.status_code == expected_status, replay.text
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == original.json()
    assert workflow_state(database) == before
    if action != "resolve":
        current = client.get(f"/api/exceptions/{item_id}").json()["exception"]
        assert current["version"] > replay.json()["exception"]["version"]


def test_repeated_seed_preserves_persisted_roles_and_workflow(database, identities):
    operator = identities["alex@northline.example"]["id"]
    reviewer = identities["casey@northline.example"]["id"]
    set_role(database, operator, "reviewer")
    set_role(database, reviewer, "operator")
    before = workflow_state(database)
    seed(database, TEST_PASSWORD)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT role FROM users WHERE id=%s", (operator,)).fetchone()[0] == "reviewer"
        assert conn.execute("SELECT role FROM users WHERE id=%s", (reviewer,)).fetchone()[0] == "operator"
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 6
    assert workflow_state(database) == before


def test_a_stale_operator_principal_waits_for_role_update_then_denies(
    app, northline, database, identities, monkeypatch
):
    client, headers = northline
    actor = identities["alex@northline.example"]["id"]
    session_read, release_session = Event(), Event()
    captured = {}
    real_connect = app_module.connect

    class SessionCursor:
        def __init__(self, cursor, connection):
            self.cursor, self.connection = cursor, connection

        def fetchone(self):
            row = self.cursor.fetchone()
            if row and row["user_id"] == actor and not session_read.is_set():
                captured.update(role=row["role"], pid=self.connection.info.backend_pid)
                session_read.set()
                if not release_session.wait(10):
                    raise AssertionError("The stale-principal fixture was not released")
            return row

        def __getattr__(self, name):
            return getattr(self.cursor, name)

    class ConnectionProbe:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, *args, **kwargs):
            cursor = self.connection.execute(query, *args, **kwargs)
            return SessionCursor(cursor, self.connection) if "FROM sessions s" in str(query) else cursor

        def __getattr__(self, name):
            return getattr(self.connection, name)

    @contextmanager
    def capture_session(database_url):
        with real_connect(database_url) as connection:
            yield ConnectionProbe(connection)

    monkeypatch.setattr(app_module, "connect", capture_session)
    before = workflow_state(database)
    with psycopg.connect(database) as holder, psycopg.connect(
        database, autocommit=True, row_factory=dict_row
    ) as observer, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(post_change, client, headers, "/api/exceptions", create_body("ROLE-RACE-DENIED"))
        try:
            assert session_read.wait(5), "The authenticated request must first read its operator principal"
            assert captured["role"] == "operator"
            holder.execute("UPDATE users SET role='reviewer' WHERE id=%s", (actor,))
            holder_pid = holder.info.backend_pid
            release_session.set()
            blocked = wait_for_block(observer, holder_pid, future, captured["pid"])
            assert "users" in blocked["query"].lower()
            assert workflow_state(database) == before
            holder.commit()
            assert_read_only(future.result(timeout=10))
        finally:
            release_session.set()
            holder.rollback()
    assert workflow_state(database) == before
    assert client.get("/api/session").json()["user"]["role"] == "reviewer"


def test_authorized_mutation_holds_role_lock_until_business_transaction_commits(
    northline, database, identities
):
    client, headers = northline
    actor = identities["alex@northline.example"]["id"]
    item_id = UUID(int=101)
    key = str(uuid4())
    before = workflow_state(database)
    demotion_started = Event()
    demotion = {}

    def demote():
        with psycopg.connect(database, options="-c lock_timeout=5000 -c statement_timeout=8000") as connection:
            demotion["pid"] = connection.info.backend_pid
            demotion_started.set()
            connection.execute("UPDATE users SET role='reviewer' WHERE id=%s", (actor,))
        return True

    with psycopg.connect(database) as holder, psycopg.connect(
        database, autocommit=True, row_factory=dict_row
    ) as observer, ThreadPoolExecutor(max_workers=2) as executor:
        holder.execute("SELECT id FROM shipment_exceptions WHERE id=%s FOR UPDATE", (item_id,))
        mutation = executor.submit(post_change, client, headers, f"/api/exceptions/{item_id}/assign", {
            "expected_version": 1, "assignee_id": str(UUID(int=13)),
        }, key)
        try:
            blocked_mutation = wait_for_block(observer, holder.info.backend_pid, mutation)
            assert "shipment_exceptions" in blocked_mutation["query"].lower()
            role_change = executor.submit(demote)
            assert demotion_started.wait(5), "The independent role updater must reach its SQL boundary"
            blocked_update = wait_for_block(observer, blocked_mutation["pid"], role_change, demotion["pid"])
            assert "update users" in blocked_update["query"].lower()
            assert workflow_state(database) == before
            holder.commit()
            accepted = mutation.result(timeout=10)
            assert accepted.status_code == 200, accepted.text
            assert role_change.result(timeout=10) is True
        finally:
            holder.rollback()
    after = workflow_state(database)
    item = next(row for row in after["exceptions"] if row["id"] == item_id)
    assert item["version"] == 2 and item["assignee_id"] == UUID(int=13)
    assert len(after["events"]) == len(before["events"]) + 1
    assert len(after["receipts"]) == len(before["receipts"]) + 1
    assert str(after["receipts"][0]["key"]) == key
    assert client.get("/api/session").json()["user"]["role"] == "reviewer"
    saved = workflow_state(database)
    assert_read_only(post_change(client, headers, f"/api/exceptions/{item_id}/assign", {
        "expected_version": 1, "assignee_id": str(UUID(int=13)),
    }, key))
    assert workflow_state(database) == saved
