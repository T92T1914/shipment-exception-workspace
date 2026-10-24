"""Login work admission against the disposable PostgreSQL integration database.

Threshold tests replace only password verification so forty admitted attempts do
not become a password-hashing load test. Existing API tests retain real Argon2
success and failure coverage. Counter state, locking and commits remain real.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from hashlib import sha256
from math import ceil
from threading import Barrier, Lock
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

from argon2.exceptions import VerificationError
from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from conftest import ORIGIN, TEST_PASSWORD
import shipment_workspace.app as app_module


KNOWN = "alex@northline.example"
UNKNOWN = "missing@synthetic.example"
WRONG_PASSWORD = "Synthetic-wrong-password-77!"


def identifier_digest(email):
    return sha256(email.strip().lower().encode("utf-8")).hexdigest()


def admission_state(database):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return {
            "global": conn.execute("SELECT * FROM login_global ORDER BY singleton").fetchall(),
            "identifiers": conn.execute(
                "SELECT * FROM login_identifiers ORDER BY identifier_hash"
            ).fetchall(),
        }


def set_budget(database, global_attempts=0, global_seconds=60, subjects=()):
    """Set a boundary directly, without waiting on real minute-long windows."""
    with psycopg.connect(database) as conn:
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        conn.execute("DELETE FROM login_identifiers")
        conn.execute(
            "UPDATE login_global SET attempts=%s,reset_at=%s WHERE singleton=true",
            (global_attempts, now + timedelta(seconds=global_seconds)),
        )
        for email, attempts, seconds in subjects:
            conn.execute(
                "INSERT INTO login_identifiers(identifier_hash,attempts,reset_at) VALUES (%s,%s,%s)",
                (identifier_digest(email), attempts, now + timedelta(seconds=seconds)),
            )


@contextmanager
def anonymous_client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/session")
        assert response.status_code == 200, response.text
        assert response.json()["authenticated"] is False
        yield client, {
            "Origin": ORIGIN,
            "X-CSRF-Token": response.json()["csrf_token"],
            "Content-Type": "application/json",
        }


def login(client, headers, email=UNKNOWN, password=WRONG_PASSWORD):
    return client.post("/api/login", json={"email": email, "password": password}, headers=headers)


def assert_throttled(response):
    assert response.status_code == 429, response.text
    assert response.json() == {
        "error": {
            "code": "login_throttled",
            "message": "Too many sign-in attempts. Wait before trying again.",
        }
    }
    assert response.headers["Retry-After"].isdigit()
    wait = int(response.headers["Retry-After"])
    assert 1 <= wait <= 60
    return wait


def install_verifier(monkeypatch, verify):
    # Replace the application's verification boundary, keeping its actual hash
    # method available if a later app instance creates its dummy credential.
    monkeypatch.setattr(app_module, "PASSWORDS", SimpleNamespace(
        hash=app_module.PASSWORDS.hash, verify=verify,
    ))


@pytest.fixture()
def verification_calls(app, monkeypatch):
    calls, guard = [], Lock()

    def fail(encoded, password):
        with guard:
            calls.append((encoded, password))
        raise VerificationError("Synthetic verification failure")

    install_verifier(monkeypatch, fail)
    return calls


@pytest.mark.parametrize("email", [KNOWN, UNKNOWN], ids=["known", "unknown"])
def test_identifier_admits_twenty_verifications_then_denies_without_extending_state(
    app, database, verification_calls, email
):
    with anonymous_client(app) as (client, headers):
        for _ in range(20):
            response = login(client, headers, email)
            assert response.status_code == 401, response.text
            assert response.json()["error"]["code"] == "invalid_credentials"
            assert "Retry-After" not in response.headers
        before = admission_state(database)
        assert before["global"][0]["attempts"] == 20
        assert len(before["identifiers"]) == 1
        assert before["identifiers"][0]["identifier_hash"] == identifier_digest(email)
        assert before["identifiers"][0]["attempts"] == 20
        for _ in range(3):
            denied = login(client, headers, email)
            assert_throttled(denied)
            assert email not in denied.text
            assert WRONG_PASSWORD not in denied.text
            assert admission_state(database) == before
    assert len(verification_calls) == 20


def test_success_and_failure_share_the_normalized_identifier_budget_without_refunds(
    app, database, monkeypatch
):
    calls = []

    def verify(encoded, password):
        calls.append((encoded, password))
        if password != TEST_PASSWORD:
            raise VerificationError("Synthetic verification failure")
        return True

    install_verifier(monkeypatch, verify)
    with anonymous_client(app) as (client, headers):
        for index in range(20):
            succeeds = index % 2 == 0
            response = login(
                client, headers, "  ALEX@Northline.Example \t",
                TEST_PASSWORD if succeeds else WRONG_PASSWORD,
            )
            assert response.status_code == (200 if succeeds else 401), response.text
            if succeeds:
                assert response.json()["user"]["email"] == KNOWN
                headers["X-CSRF-Token"] = response.json()["csrf_token"]
        before = admission_state(database)
        assert before["global"][0]["attempts"] == 20
        assert before["identifiers"] == [{
            "identifier_hash": identifier_digest(KNOWN), "attempts": 20,
            "reset_at": before["identifiers"][0]["reset_at"],
        }]
        assert_throttled(login(client, headers, KNOWN, TEST_PASSWORD))
        assert admission_state(database) == before
    assert len(calls) == 20


def test_global_budget_admits_forty_distinct_identifiers_then_allocates_no_denied_row(
    app, database, verification_calls
):
    with anonymous_client(app) as (client, headers):
        for index in range(40):
            response = login(client, headers, f"unknown-{index}@synthetic.example")
            assert response.status_code == 401, response.text
        before = admission_state(database)
        assert before["global"][0]["attempts"] == 40
        assert len(before["identifiers"]) == 40
        assert all(row["attempts"] == 1 for row in before["identifiers"])
        for index in range(3):
            assert_throttled(login(client, headers, f"denied-{index}@synthetic.example"))
            assert admission_state(database) == before
    assert len(verification_calls) == 40


@pytest.mark.parametrize("global_seconds,identifier_seconds", [(20, 45), (55, 15)])
def test_retry_after_uses_the_later_blocking_window(
    app, database, verification_calls, global_seconds, identifier_seconds
):
    set_budget(database, 40, global_seconds, [(KNOWN, 20, identifier_seconds)])
    before = admission_state(database)
    with psycopg.connect(database) as conn:
        request_started = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    latest = max(before["global"][0]["reset_at"], before["identifiers"][0]["reset_at"])
    expected = ceil((latest - request_started).total_seconds())
    with anonymous_client(app) as (client, headers):
        wait = assert_throttled(login(client, headers, KNOWN))
    assert expected - 2 <= wait <= expected
    assert admission_state(database) == before
    assert verification_calls == []


@pytest.mark.parametrize("email", [KNOWN, UNKNOWN], ids=["known", "unknown"])
@pytest.mark.parametrize("invalid", [
    "missing-origin", "foreign-origin", "missing-csrf", "wrong-csrf", "non-ascii-csrf",
    "non-json", "empty-password", "extra-field", "short-email", "long-email",
    "long-password", "malformed-json", "oversized-body",
])
def test_rejected_login_envelopes_do_not_charge_either_budget(
    app, database, verification_calls, email, invalid
):
    with anonymous_client(app) as (client, valid):
        before = admission_state(database)
        headers = valid.copy()
        body = {"email": email, "password": WRONG_PASSWORD}
        content = None
        expected = 422
        if invalid == "missing-origin":
            headers.pop("Origin")
            expected = 403
        elif invalid == "foreign-origin":
            headers["Origin"] = "https://untrusted.synthetic.example"
            expected = 403
        elif invalid == "missing-csrf":
            headers.pop("X-CSRF-Token")
            expected = 403
        elif invalid == "wrong-csrf":
            headers["X-CSRF-Token"] = "synthetic-wrong-csrf"
            expected = 403
        elif invalid == "non-ascii-csrf":
            headers = [(key.lower().encode("ascii"), value.encode("ascii"))
                       for key, value in headers.items() if key != "X-CSRF-Token"]
            headers.append((b"x-csrf-token", b"\xff"))
            expected = 403
        elif invalid == "non-json":
            headers["Content-Type"] = "text/plain"
            content = b'{"email":"' + email.encode() + b'","password":"synthetic"}'
            # FastAPI validates the typed body before invoking the route's CSRF
            # content-type check, so this envelope is rejected as invalid input.
            expected = 422
        elif invalid == "empty-password":
            body["password"] = ""
        elif invalid == "extra-field":
            body["organization_id"] = str(uuid4())
        elif invalid == "short-email":
            body["email"] = "x"
        elif invalid == "long-email":
            body["email"] = "x" * 255
        elif invalid == "long-password":
            body["password"] = "x" * 257
        elif invalid == "malformed-json":
            content = b'{"email":'
        elif invalid == "oversized-body":
            content = b'{"email":"' + email.encode() + b'","password":"' + b"x" * 20000 + b'"}'
            expected = 413
        if content is None:
            response = client.post("/api/login", json=body, headers=headers)
        else:
            response = client.post("/api/login", content=content, headers=headers)
        assert response.status_code == expected, response.text
        assert "Retry-After" not in response.headers
        assert WRONG_PASSWORD not in response.text
        assert admission_state(database) == before
    assert verification_calls == []


def test_missing_anonymous_session_is_rejected_before_admission(app, database, verification_calls):
    before = admission_state(database)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = login(client, {"Origin": ORIGIN, "X-CSRF-Token": "synthetic"})
    assert response.status_code == 403, response.text
    assert admission_state(database) == before
    assert verification_calls == []


def test_budget_is_committed_and_global_lock_released_before_password_verification(
    app, database, monkeypatch
):
    observations = []

    def verify(encoded, password):
        with psycopg.connect(database, row_factory=dict_row) as observer:
            budget = observer.execute(
                "SELECT * FROM login_global WHERE singleton=true FOR UPDATE NOWAIT"
            ).fetchone()
            subject = observer.execute(
                "SELECT * FROM login_identifiers WHERE identifier_hash=%s", (identifier_digest(UNKNOWN),)
            ).fetchone()
            assert budget["attempts"] == 1
            assert subject["attempts"] == 1
            observations.append((budget, subject))
        raise VerificationError("Synthetic verification failure")

    install_verifier(monkeypatch, verify)
    with anonymous_client(app) as (client, headers):
        response = login(client, headers)
        assert response.status_code == 401, response.text
    assert len(observations) == 1


def test_window_clock_is_sampled_after_waiting_for_the_global_lock(
    app, database, verification_calls
):
    set_budget(database, 40, 60)
    with anonymous_client(app) as (client, headers):
        with psycopg.connect(database) as holder, psycopg.connect(database, autocommit=True) as observer:
            holder_pid = holder.execute("SELECT pg_backend_pid()").fetchone()[0]
            holder.execute("SELECT singleton FROM login_global FOR UPDATE")
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(login, client, headers)
                try:
                    deadline = monotonic() + 3
                    while monotonic() < deadline:
                        waiting = observer.execute(
                            "SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                            "AND %s=ANY(pg_blocking_pids(pid)) AND wait_event_type='Lock'",
                            (holder_pid,),
                        ).fetchone()
                        if waiting:
                            break
                        # Only a bounded lock-order handshake, not an expiry wait.
                        sleep(0.01)
                    else:
                        pytest.fail("The login request did not wait for the held global row lock")
                    # This expiry is later than the waiting transaction's start,
                    # but earlier than its eventual post-lock wall-clock sample.
                    # A transaction-start now() would incorrectly deny it.
                    holder.execute("UPDATE login_global SET reset_at=clock_timestamp()")
                    holder.commit()
                    response = future.result(timeout=20)
                finally:
                    holder.rollback()
    assert response.status_code == 401, response.text
    assert len(verification_calls) == 1
    state = admission_state(database)
    assert state["global"][0]["attempts"] == 1
    assert state["identifiers"][0]["attempts"] == 1


def test_missing_global_state_fails_closed_without_password_verification(
    app, database, verification_calls
):
    with anonymous_client(app) as (client, headers):
        with psycopg.connect(database) as conn:
            removed = conn.execute("DELETE FROM login_global RETURNING attempts,reset_at").fetchone()
        try:
            before = admission_state(database)
            response = login(client, headers, KNOWN, TEST_PASSWORD)
            assert response.status_code == 500, response.text
            assert response.json()["error"]["code"] == "internal_error"
            assert admission_state(database) == before
        finally:
            with psycopg.connect(database) as conn:
                conn.execute(
                    "INSERT INTO login_global(singleton,attempts,reset_at) VALUES (true,%s,%s)", removed
                )
    assert verification_calls == []


def test_admission_sql_failure_rolls_back_both_counters_before_verification(
    app, database, verification_calls
):
    with anonymous_client(app) as (client, headers):
        before = admission_state(database)
        with psycopg.connect(database) as conn:
            conn.execute(
                "CREATE FUNCTION test_reject_login_admission() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE EXCEPTION 'synthetic admission failure'; END; $$"
            )
            conn.execute(
                "CREATE TRIGGER test_login_admission_failure BEFORE INSERT OR UPDATE ON login_identifiers "
                "FOR EACH ROW EXECUTE FUNCTION test_reject_login_admission()"
            )
        try:
            response = login(client, headers, KNOWN, TEST_PASSWORD)
            assert response.status_code == 500, response.text
            assert admission_state(database) == before
            assert verification_calls == []
        finally:
            with psycopg.connect(database) as conn:
                conn.execute("DROP TRIGGER IF EXISTS test_login_admission_failure ON login_identifiers")
                conn.execute("DROP FUNCTION IF EXISTS test_reject_login_admission()")


def test_later_session_write_failure_does_not_refund_committed_password_admission(
    app, database, monkeypatch
):
    calls = []

    def verify(encoded, password):
        calls.append((encoded, password))
        return True

    install_verifier(monkeypatch, verify)
    with anonymous_client(app) as (client, headers):
        with psycopg.connect(database) as conn:
            before_sessions = conn.execute("SELECT * FROM sessions ORDER BY token_hash").fetchall()
            conn.execute(
                "CREATE FUNCTION test_reject_authenticated_session() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE EXCEPTION 'synthetic session insert failure'; END; $$"
            )
            conn.execute(
                "CREATE TRIGGER test_authenticated_session_failure BEFORE INSERT ON sessions "
                "FOR EACH ROW WHEN (NEW.user_id IS NOT NULL) "
                "EXECUTE FUNCTION test_reject_authenticated_session()"
            )
        try:
            response = login(client, headers, KNOWN, TEST_PASSWORD)
            assert response.status_code == 500, response.text
            state = admission_state(database)
            assert state["global"][0]["attempts"] == 1
            assert state["identifiers"][0]["attempts"] == 1
            assert state["identifiers"][0]["identifier_hash"] == identifier_digest(KNOWN)
            with psycopg.connect(database) as conn:
                assert conn.execute("SELECT * FROM sessions ORDER BY token_hash").fetchall() == before_sessions
            current = client.get("/api/session")
            assert current.json()["authenticated"] is False
            assert current.json()["csrf_token"] == headers["X-CSRF-Token"]
        finally:
            with psycopg.connect(database) as conn:
                conn.execute("DROP TRIGGER IF EXISTS test_authenticated_session_failure ON sessions")
                conn.execute("DROP FUNCTION IF EXISTS test_reject_authenticated_session()")
    assert len(calls) == 1


@pytest.mark.parametrize("boundary", ["identifier", "global"])
def test_two_independent_clients_compete_for_only_one_remaining_admission(
    app, database, verification_calls, boundary
):
    if boundary == "identifier":
        set_budget(database, 19, 60, [(UNKNOWN, 19, 60)])
        emails = [UNKNOWN, UNKNOWN]
    else:
        set_budget(database, 39, 60, [
            ("previous-a@synthetic.example", 20, 60),
            ("previous-b@synthetic.example", 19, 60),
        ])
        emails = ["race-a@synthetic.example", "race-b@synthetic.example"]
    before = admission_state(database)
    start = Barrier(2, timeout=10)
    with ExitStack() as stack:
        clients = [stack.enter_context(anonymous_client(app)) for _ in range(2)]

        def worker(index):
            client, headers = clients[index]
            start.wait()
            return login(client, headers, emails[index])

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, index) for index in range(2)]
            responses = [future.result(timeout=20) for future in futures]
    assert sorted(response.status_code for response in responses) == [401, 429]
    for response in responses:
        if response.status_code == 429:
            assert_throttled(response)
    assert len(verification_calls) == 1
    after = admission_state(database)
    assert after["global"][0]["attempts"] == before["global"][0]["attempts"] + 1
    assert after["global"][0]["reset_at"] == before["global"][0]["reset_at"]
    if boundary == "identifier":
        assert len(after["identifiers"]) == 1
        assert after["identifiers"][0]["attempts"] == 20
        assert after["identifiers"][0]["reset_at"] == before["identifiers"][0]["reset_at"]
    else:
        admitted_index = next(index for index, response in enumerate(responses) if response.status_code == 401)
        added = [row for row in after["identifiers"] if row["identifier_hash"] not in {
            subject["identifier_hash"] for subject in before["identifiers"]
        }]
        assert len(added) == 1
        assert added[0]["identifier_hash"] == identifier_digest(emails[admitted_index])
        assert added[0]["attempts"] == 1


def test_expired_windows_are_reset_and_expired_identifier_rows_are_removed(
    app, database, verification_calls
):
    set_budget(database, 40, -1, [(UNKNOWN, 20, -1), ("stale@synthetic.example", 1, -1)])
    with anonymous_client(app) as (client, headers):
        response = login(client, headers)
        assert response.status_code == 401, response.text
    after = admission_state(database)
    assert after["global"][0]["attempts"] == 1
    assert len(after["identifiers"]) == 1
    assert after["identifiers"][0]["identifier_hash"] == identifier_digest(UNKNOWN)
    assert after["identifiers"][0]["attempts"] == 1
    with psycopg.connect(database) as conn:
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    for row in (after["global"][0], after["identifiers"][0]):
        assert 57 <= (row["reset_at"] - now).total_seconds() <= 60
    assert len(verification_calls) == 1


def test_denial_cleans_expired_identifiers_without_resetting_or_extending_global_window(
    app, database, verification_calls
):
    set_budget(database, 40, 60, [(UNKNOWN, 20, -1), ("stale@synthetic.example", 1, -1)])
    before = admission_state(database)
    with anonymous_client(app) as (client, headers):
        assert_throttled(login(client, headers))
    after = admission_state(database)
    assert after["global"] == before["global"]
    assert after["identifiers"] == []
    assert verification_calls == []


def test_expired_global_window_is_not_restarted_by_an_identifier_denial(
    app, database, verification_calls
):
    set_budget(database, 40, -1, [(UNKNOWN, 20, 60)])
    before = admission_state(database)
    with anonymous_client(app) as (client, headers):
        assert_throttled(login(client, headers))
        assert admission_state(database) == before
        admitted = login(client, headers, "fresh@synthetic.example")
        assert admitted.status_code == 401, admitted.text
    after = admission_state(database)
    assert after["global"][0]["attempts"] == 1
    old_subject = next(row for row in after["identifiers"]
                       if row["identifier_hash"] == identifier_digest(UNKNOWN))
    assert old_subject == before["identifiers"][0]
    assert len(verification_calls) == 1


def test_two_directly_advanced_global_windows_retain_at_most_eighty_unknown_identifiers(
    app, database, verification_calls
):
    # Direct SQL advances only the disposable counter clock. This checks row
    # allocation/retention at boundaries, not traffic rate or elapsed-time load.
    with anonymous_client(app) as (client, headers):
        for window in range(2):
            if window:
                with psycopg.connect(database) as conn:
                    conn.execute("UPDATE login_global SET reset_at=clock_timestamp()-interval '1 second'")
            for index in range(40):
                response = login(client, headers, f"window-{window}-{index}@synthetic.example")
                assert response.status_code == 401, response.text
            before_denial = admission_state(database)
            assert len(before_denial["identifiers"]) == (window + 1) * 40
            assert before_denial["global"][0]["attempts"] == 40
            assert_throttled(login(client, headers, f"not-allocated-{window}@synthetic.example"))
            assert admission_state(database) == before_denial
    assert len(verification_calls) == 80
    assert len(admission_state(database)["identifiers"]) == 80


def test_authenticated_workflow_remains_available_when_further_login_work_is_denied(
    northline, app, database, monkeypatch
):
    client, headers = northline
    calls = []

    def unexpected_verify(encoded, password):
        calls.append((encoded, password))
        raise AssertionError("Blocked requests must not verify a password")

    install_verifier(monkeypatch, unexpected_verify)
    set_budget(database, 40, 60, [(KNOWN, 20, 60)])
    before = admission_state(database)
    with anonymous_client(app) as (other, anonymous_headers):
        assert_throttled(login(other, anonymous_headers, KNOWN, TEST_PASSWORD))
    members = client.get("/api/members")
    assert members.status_code == 200, members.text
    created = client.post(
        "/api/exceptions",
        json={"reference": "LOGIN-BLOCKED-WORKFLOW", "summary": "Synthetic intake",
              "details": "Existing authenticated work remains available.", "priority": "normal"},
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert created.status_code == 201, created.text
    item = created.json()["exception"]
    assigned = client.post(
        f"/api/exceptions/{item['id']}/assign",
        json={"expected_version": 1, "assignee_id": members.json()["items"][0]["id"]},
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert assigned.status_code == 200, assigned.text
    resolved = client.post(
        f"/api/exceptions/{item['id']}/resolve",
        json={"expected_version": 2, "resolution": "Synthetic resolution after login admission filled."},
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["exception"]["version"] == 3
    assert resolved.json()["exception"]["status"] == "resolved"
    assert admission_state(database) == before
    assert calls == []
