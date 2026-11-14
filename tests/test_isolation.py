"""Isolation audit of the write routes on disposable PostgreSQL.

Every race here is staged rather than hoped for. A holder transaction takes a
real lock, the competing requests start, and the test waits until PostgreSQL
reports each request blocked before the holder lets go. The requests reach
their locks in the same order on every run, and no sleep stands in for
evidence.

Each lock test also runs with that lock removed. The removal rewrites one
application statement as it reaches PostgreSQL and changes nothing else, and
that variant asserts the anomaly the lock prevents. A race test that still
passed with its lock gone would prove nothing, so the removed variant shows that
each test depends on the lock it names. The account per route is in
docs/DESIGN.md under Write route isolation.
"""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import sys
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from conftest import TEST_PASSWORD, authenticated_client
from shipment_workspace.app import COOKIE, create_app
from shipment_workspace.db import provision_demo
from shipment_workspace.public_demo import DEMO_EMAIL, SESSION_LOCK
from test_public_demo import ORIGIN as DEMO_ORIGIN, PUBLIC_PASSWORD, clear_application, settings


NORTHLINE = UUID(int=1)
ALEX, CASEY = UUID(int=11), UUID(int=13)
ITEM = UUID(int=101)

# Each entry is the exact application statement and the clause the removed
# variant takes out of it.
EXCEPTION_ROW_LOCK = ("SELECT * FROM shipment_exceptions WHERE organization_id=%s AND id=%s FOR UPDATE", " FOR UPDATE")
ACTOR_ROW_LOCK = ("SELECT organization_id,role FROM users WHERE id=%s FOR SHARE", " FOR SHARE")
LOGIN_BUDGET_LOCK = ("SELECT attempts,reset_at FROM login_global WHERE singleton=true FOR UPDATE", " FOR UPDATE")
SESSION_ORDER_LOCK = ("SELECT pg_advisory_xact_lock(%s,%s)", "pg_advisory_xact_lock(%s,%s)")

LOCK = pytest.mark.parametrize("lock", ["kept", "removed"], ids=["lock-kept", "lock-removed"])


def watch_statements(monkeypatch, lock, statement=None, replacement="", caller=None):
    """Record database errors and, for the removed variant, take one lock out.

    The statement must match exactly, so the holder and observer connections
    are never rewritten. A caller name narrows the rewrite further when two
    functions send the same text.
    """
    original = psycopg.Connection.execute
    record = {"removed": 0, "errors": []}

    def execute(conn, query, *args, **kwargs):
        if (lock == "removed" and statement and query == statement[0]
                and (caller is None or sys._getframe(1).f_code.co_name == caller)):
            query = query.replace(statement[1], replacement)
            record["removed"] += 1
        try:
            return original(conn, query, *args, **kwargs)
        except psycopg.Error as exc:
            record["errors"].append(type(exc).__name__)
            raise

    monkeypatch.setattr(psycopg.Connection, "execute", execute)
    return record


def wait_until_blocked(observer, future, blockers, exclude=(), target=None):
    """Return the backend PostgreSQL reports waiting behind one of the blockers.

    A blocker either holds the conflicting lock or waits ahead in its queue.
    The short pause only paces the polling. The evidence is the reported wait.
    """
    deadline = monotonic() + 3
    pause = Event()
    while monotonic() < deadline:
        row = observer.execute(
            "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
            "AND pid<>pg_backend_pid() AND wait_event_type='Lock' "
            "AND pg_blocking_pids(pid) && %s::integer[] AND NOT pid=ANY(%s::integer[]) "
            "AND (%s::integer IS NULL OR pid=%s) ORDER BY pid LIMIT 1",
            (list(blockers), [0, *exclude], target, target),
        ).fetchone()
        if row:
            return row["pid"]
        if future.done():
            pytest.fail(f"The request finished without the lock wait this race needs: "
                        f"{future.exception() or future.result()!r}")
        pause.wait(0.01)
    pytest.fail("PostgreSQL did not report the lock wait before the deadline")


def workflow(database):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return {
            "item": conn.execute("SELECT * FROM shipment_exceptions WHERE id=%s", (ITEM,)).fetchone(),
            "exceptions": conn.execute("SELECT count(*) AS n FROM shipment_exceptions").fetchone()["n"],
            "events": conn.execute("SELECT * FROM exception_events ORDER BY id").fetchall(),
            "receipts": conn.execute("SELECT * FROM mutation_requests ORDER BY created_at,key").fetchall(),
        }


def change(client, headers, action, body):
    return client.post(f"/api/exceptions/{ITEM}/{action}", json=body,
                       headers={**headers, "Idempotency-Key": str(uuid4())})


def assert_unconfirmed(response):
    """The sanitized answer for a write that failed after it reached the database."""
    assert response.status_code == 500, response.text
    assert response.json()["error"]["code"] == "internal_error"
    assert "Idempotency-Replayed" not in response.headers


def race_on_exception(database, first_request, second_request):
    """Queue two edits of one exception behind a held row lock, then release it."""
    with psycopg.connect(database) as holder, psycopg.connect(
        database, autocommit=True, row_factory=dict_row
    ) as observer, ThreadPoolExecutor(max_workers=2) as pool:
        holder.execute("SELECT id FROM shipment_exceptions WHERE id=%s FOR UPDATE", (ITEM,))
        holder_pid = holder.info.backend_pid
        try:
            first = pool.submit(*first_request)
            first_pid = wait_until_blocked(observer, first, [holder_pid])
            second = pool.submit(*second_request)
            wait_until_blocked(observer, second, [holder_pid, first_pid], exclude=[first_pid])
            holder.commit()
            return first.result(timeout=10), second.result(timeout=10)
        finally:
            holder.rollback()


@LOCK
def test_assign_row_lock_turns_a_competing_assignment_into_a_version_conflict(
    app, database, monkeypatch, lock
):
    """Two operators assign the same open exception from version 1.

    With the row lock, the second request waits, reads version 2 and saves a
    409 receipt. Without it, both read version 1 and both update. The unique
    audit version then rejects the second event, so the loser gets an
    unconfirmed 500 with no receipt instead of a clean conflict.
    """
    with authenticated_client(app) as (alex, alex_headers), authenticated_client(
        app, "sam@northline.example"
    ) as (sam, sam_headers):
        before = workflow(database)
        record = watch_statements(monkeypatch, lock, EXCEPTION_ROW_LOCK)
        first, second = race_on_exception(
            database,
            (change, alex, alex_headers, "assign", {"expected_version": 1, "assignee_id": str(CASEY)}),
            (change, sam, sam_headers, "assign", {"expected_version": 1, "assignee_id": str(ALEX)}),
        )
    after = workflow(database)
    assert first.status_code == 200, first.text
    assert first.json()["exception"]["assignee_id"] == str(CASEY)
    assert after["item"]["version"] == 2 and after["item"]["assignee_id"] == CASEY
    new_events = after["events"][len(before["events"]):]
    assert [(event["action"], event["version"], event["actor_id"]) for event in new_events] == [("assigned", 2, ALEX)]
    if lock == "kept":
        assert second.status_code == 409, second.text
        assert second.json()["error"]["code"] == "version_conflict"
        assert second.json()["error"]["current_version"] == 2
        assert len(after["receipts"]) == len(before["receipts"]) + 2
        assert record["errors"] == []
    else:
        assert record["removed"] == 2
        assert_unconfirmed(second)
        assert "UniqueViolation" in record["errors"]
        assert len(after["receipts"]) == len(before["receipts"]) + 1


@LOCK
def test_resolve_row_lock_lets_only_one_operator_close_an_exception(app, database, monkeypatch, lock):
    """Two operators resolve the same exception from version 1 with different notes.

    With the row lock, the first resolution stands and the second request gets
    a saved 409. Without it, the second update overwrites the first resolution
    until the duplicate audit version rolls it back with an unconfirmed 500.
    """
    with authenticated_client(app) as (alex, alex_headers), authenticated_client(
        app, "sam@northline.example"
    ) as (sam, sam_headers):
        before = workflow(database)
        record = watch_statements(monkeypatch, lock, EXCEPTION_ROW_LOCK)
        first, second = race_on_exception(
            database,
            (change, alex, alex_headers, "resolve", {"expected_version": 1, "resolution": "First operator closed it."}),
            (change, sam, sam_headers, "resolve", {"expected_version": 1, "resolution": "Second operator closed it."}),
        )
    after = workflow(database)
    assert first.status_code == 200, first.text
    assert after["item"]["status"] == "resolved" and after["item"]["version"] == 2
    assert after["item"]["resolution"] == "First operator closed it."
    new_events = after["events"][len(before["events"]):]
    assert [(event["action"], event["version"], event["note"]) for event in new_events] == [
        ("resolved", 2, "First operator closed it.")]
    if lock == "kept":
        assert second.status_code == 409, second.text
        assert second.json()["error"]["code"] == "version_conflict"
        assert second.json()["error"]["current_version"] == 2
        assert len(after["receipts"]) == len(before["receipts"]) + 2
        assert record["errors"] == []
    else:
        assert record["removed"] == 2
        assert_unconfirmed(second)
        assert "UniqueViolation" in record["errors"]
        assert len(after["receipts"]) == len(before["receipts"]) + 1


@LOCK
def test_create_actor_lock_holds_a_demotion_until_the_admitted_creation_commits(
    app, database, monkeypatch, lock
):
    """An operator's creation is admitted, then a demotion of that operator arrives.

    The holder keeps the same reference uncommitted, so the creation waits after
    its role check and before it commits. With `FOR SHARE`, the demotion waits
    for the creation, and the database order matches the documented rule. Without
    it, the demotion commits first and a write by the demoted operator commits
    after the change that should have stopped it.
    """
    reference = "ISO-CREATE"
    body = {"reference": reference, "summary": "Held reference race",
            "details": "A synthetic creation that waits behind a held reference.", "priority": "normal"}

    def demote():
        with psycopg.connect(database, options="-c lock_timeout=5000") as conn:
            conn.execute("UPDATE users SET role='reviewer' WHERE id=%s", (ALEX,))
        return True

    def create(client, headers):
        return client.post("/api/exceptions", json=body, headers={**headers, "Idempotency-Key": str(uuid4())})

    with authenticated_client(app) as (client, headers):
        record = watch_statements(monkeypatch, lock, ACTOR_ROW_LOCK)
        with psycopg.connect(database) as holder, psycopg.connect(
            database, autocommit=True, row_factory=dict_row
        ) as observer, ThreadPoolExecutor(max_workers=2) as pool:
            holder.execute("""INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority)
                VALUES (%s,%s,%s,'Held by the test','Uncommitted row that holds the reference.','normal')""",
                           (uuid4(), NORTHLINE, reference))
            try:
                creation = pool.submit(create, client, headers)
                creation_pid = wait_until_blocked(observer, creation, [holder.info.backend_pid])
                demotion = pool.submit(demote)
                if lock == "kept":
                    # The demotion waits on the creation's own backend, so it
                    # can commit only after the creation has committed.
                    wait_until_blocked(observer, demotion, [creation_pid])
                else:
                    # The demotion commits while the creation is still open.
                    assert demotion.result(timeout=5) is True
                    assert not creation.done()
                holder.rollback()
                created = creation.result(timeout=10)
                assert demotion.result(timeout=10) is True
            finally:
                holder.rollback()
    assert created.status_code == 201, created.text
    with psycopg.connect(database, row_factory=dict_row) as conn:
        assert conn.execute("SELECT role FROM users WHERE id=%s", (ALEX,)).fetchone()["role"] == "reviewer"
        row = conn.execute("SELECT id FROM shipment_exceptions WHERE organization_id=%s AND reference=%s",
                           (NORTHLINE, reference)).fetchone()
        event = conn.execute("SELECT actor_id,action FROM exception_events WHERE exception_id=%s", (row["id"],)).fetchone()
    assert event == {"actor_id": ALEX, "action": "created"}
    assert record["errors"] == []
    assert record["removed"] == (1 if lock == "removed" else 0)


@LOCK
def test_login_budget_lock_counts_every_admitted_password_verification(app, database, monkeypatch, lock):
    """Two visitors sign in at once from separate anonymous sessions.

    With the singleton row lock, the second admission reads the first one's
    count and the global budget records both. Without it, both read zero and
    the second write replaces the first, so two password verifications ran and
    the budget counted one.
    """
    with TestClient(app, raise_server_exceptions=False) as first_client, TestClient(
        app, raise_server_exceptions=False
    ) as second_client:
        tokens = [client.get("/api/session").json()["csrf_token"] for client in (first_client, second_client)]

        def sign_in(client, token, email):
            return client.post("/api/login", json={"email": email, "password": TEST_PASSWORD},
                               headers={"Origin": "http://testserver", "X-CSRF-Token": token})

        record = watch_statements(monkeypatch, lock, LOGIN_BUDGET_LOCK)
        with psycopg.connect(database) as holder, psycopg.connect(
            database, autocommit=True, row_factory=dict_row
        ) as observer, ThreadPoolExecutor(max_workers=2) as pool:
            assert observer.execute("SELECT attempts FROM login_global").fetchone()["attempts"] == 0
            holder.execute("SELECT singleton FROM login_global FOR UPDATE")
            holder_pid = holder.info.backend_pid
            try:
                first = pool.submit(sign_in, first_client, tokens[0], "alex@northline.example")
                first_pid = wait_until_blocked(observer, first, [holder_pid])
                second = pool.submit(sign_in, second_client, tokens[1], "sam@northline.example")
                wait_until_blocked(observer, second, [holder_pid, first_pid], exclude=[first_pid])
                holder.commit()
                responses = [first.result(timeout=15), second.result(timeout=15)]
            finally:
                holder.rollback()
            attempts = observer.execute("SELECT attempts FROM login_global").fetchone()["attempts"]
            identifiers = observer.execute("SELECT attempts FROM login_identifiers").fetchall()
    assert [response.status_code for response in responses] == [200, 200], [r.text for r in responses]
    assert identifiers == [{"attempts": 1}, {"attempts": 1}]
    assert record["errors"] == []
    if lock == "kept":
        assert attempts == 2
    else:
        assert record["removed"] == 2
        assert attempts == 1


@pytest.fixture()
def demo_app(database):
    clear_application(database)
    provision_demo(database, PUBLIC_PASSWORD)
    return create_app(settings(database))


@LOCK
def test_demo_login_takes_the_session_lock_before_deleting_its_old_row(demo_app, database, monkeypatch, lock):
    """A demo sign in replaces an anonymous session that expires while it waits.

    Admission for a new visitor holds the session lock and deletes expired
    rows. The sign in must take that lock before it deletes its own old row.
    In the reverse order it holds the old row while waiting for the lock, the
    admission holds the lock while waiting for that row, and PostgreSQL ends
    the cycle by aborting one of them.
    """
    with TestClient(demo_app, base_url=DEMO_ORIGIN, raise_server_exceptions=False) as returning, TestClient(
        demo_app, base_url=DEMO_ORIGIN, raise_server_exceptions=False
    ) as newcomer:
        token = returning.get("/api/session").json()["csrf_token"]
        old_row = sha256(returning.cookies.get(COOKIE).encode()).hexdigest()
        record = watch_statements(monkeypatch, lock, SESSION_ORDER_LOCK, replacement="%s,%s", caller="login")
        with psycopg.connect(database) as budget_holder, psycopg.connect(database) as session_holder, psycopg.connect(
            database, autocommit=True, row_factory=dict_row
        ) as observer, ThreadPoolExecutor(max_workers=2) as pool:
            budget_pid, session_pid = budget_holder.info.backend_pid, session_holder.info.backend_pid
            budget_holder.execute("SELECT singleton FROM login_global FOR UPDATE")
            try:
                # The sign in reads its anonymous session, then waits at admission.
                sign_in = pool.submit(returning.post, "/api/login",
                                      json={"email": DEMO_EMAIL, "password": PUBLIC_PASSWORD},
                                      headers={"Origin": DEMO_ORIGIN, "X-CSRF-Token": token})
                sign_in_pid = wait_until_blocked(observer, sign_in, [budget_pid])
                observer.execute("UPDATE sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE token_hash=%s",
                                 (old_row,))
                session_holder.execute("SELECT pg_advisory_xact_lock(%s,%s)", SESSION_LOCK)
                admission = pool.submit(newcomer.get, "/api/session")
                admission_pid = wait_until_blocked(observer, admission, [session_pid])
                budget_holder.commit()
                # After password verification the sign in queues for the session lock.
                wait_until_blocked(observer, sign_in, [session_pid, admission_pid], target=sign_in_pid)
                session_holder.commit()
                responses = [sign_in.result(timeout=15), admission.result(timeout=15)]
            finally:
                budget_holder.rollback()
                session_holder.rollback()
            remaining = observer.execute("SELECT count(*) AS n FROM sessions WHERE token_hash=%s", (old_row,)).fetchone()["n"]
    assert remaining == 0
    if lock == "kept":
        assert [response.status_code for response in responses] == [200, 200], [r.text for r in responses]
        assert responses[0].json()["authenticated"] is True
        assert record["errors"] == []
    else:
        assert record["removed"] == 1
        assert sorted(response.status_code for response in responses) == [200, 500], [r.text for r in responses]
        failed = next(response for response in responses if response.status_code == 500)
        assert failed.json()["error"]["code"] == "internal_error"
        assert record["errors"] == ["DeadlockDetected"]


def test_logout_takes_no_lock_and_does_not_cancel_a_write_already_admitted(app, database):
    """Logout is one delete keyed by the session digest, so it holds no lock to remove.

    This pins the limit the documents state instead. A write that passed its
    session check before logout can still commit after logout returns, because
    logout is not instantaneous revocation. The same token admits nothing new.
    """
    with authenticated_client(app) as (client, headers):
        token = client.cookies.get(COOKIE)
        with TestClient(app, raise_server_exceptions=False) as other_tab:
            other_tab.cookies.set(COOKIE, token)
            before = workflow(database)
            with psycopg.connect(database) as holder, psycopg.connect(
                database, autocommit=True, row_factory=dict_row
            ) as observer, ThreadPoolExecutor(max_workers=1) as pool:
                holder.execute("SELECT id FROM shipment_exceptions WHERE id=%s FOR UPDATE", (ITEM,))
                try:
                    write = pool.submit(change, other_tab, headers, "assign",
                                        {"expected_version": 1, "assignee_id": str(CASEY)})
                    wait_until_blocked(observer, write, [holder.info.backend_pid])
                    signed_out = client.post("/api/logout", headers=headers)
                    assert signed_out.status_code == 204, signed_out.text
                    assert not write.done()
                    digest = sha256(token.encode()).hexdigest()
                    assert observer.execute("SELECT count(*) AS n FROM sessions WHERE token_hash=%s",
                                            (digest,)).fetchone()["n"] == 0
                    holder.commit()
                    written = write.result(timeout=10)
                finally:
                    holder.rollback()
            assert written.status_code == 200, written.text
            after = workflow(database)
            assert after["item"]["version"] == 2 and after["item"]["assignee_id"] == CASEY
            assert len(after["events"]) == len(before["events"]) + 1
            refused = change(other_tab, headers, "assign", {"expected_version": 2, "assignee_id": None})
            assert refused.status_code == 401, refused.text
            assert workflow(database) == after
