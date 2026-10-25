"""Session-context consistency without treating a marker as authentication.

These checks exercise the real cookie session, current principal, CSRF policy
and durable receipt tables in the dedicated disposable PostgreSQL database.
"""

from hashlib import sha256
import json
import re
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from conftest import ORIGIN, TEST_PASSWORD, authenticated_client
from shipment_workspace.app import COOKIE, create_app
from shipment_workspace.config import Settings


HEADER = "X-Workspace-Context"
OWN_ID = str(UUID(int=101))
FOREIGN_ID = str(UUID(int=201))


def state(database, *, security=False):
    tables = ["shipment_exceptions", "exception_events", "mutation_requests"]
    if security:
        tables += ["sessions", "login_global", "login_identifiers"]
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return {table: conn.execute(f"SELECT row_to_json(t)::text AS row FROM {table} t ORDER BY 1").fetchall()
                for table in tables}


def current_session(client):
    response = client.get("/api/session")
    assert response.status_code == 200, response.text
    payload = response.json()
    marker = payload["session_context"]
    assert isinstance(marker, str) and re.fullmatch(r"[0-9a-f]{64}", marker)
    return payload


def context_headers(payload, **extra):
    return {"Origin": ORIGIN, "Content-Type": "application/json",
            "X-CSRF-Token": payload["csrf_token"], HEADER: payload["session_context"], **extra}


def create_body(reference="SESSION-CONTEXT"):
    return {"reference": reference, "summary": "Synthetic session context check",
            "details": "An account transition must not reuse this tab's previous context.", "priority": "normal"}


def assert_session_changed(response, *not_echoed):
    assert response.status_code == 409, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "session_changed"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert "Idempotency-Replayed" not in response.headers
    serialized = json.dumps(body)
    for value in not_echoed:
        if value:
            assert value not in serialized
    return body


def test_marker_is_non_authorizing_session_metadata_and_stable_on_reads(app, database):
    with TestClient(app, raise_server_exceptions=False) as client:
        anonymous = current_session(client)
        assert not anonymous["authenticated"]
        token = client.cookies.get(COOKIE)
        token_hash = sha256(token.encode()).hexdigest()
        with psycopg.connect(database, row_factory=dict_row) as conn:
            row = conn.execute("SELECT * FROM sessions WHERE token_hash=%s", (token_hash,)).fetchone()
        expected = sha256(("shipment-ui-context-v1:" + row["token_hash"]).encode()).hexdigest()
        assert anonymous["session_context"] == expected
        assert anonymous["session_context"] not in (token, row["token_hash"], row["csrf_token"])
        assert "token_hash" not in anonymous
        before = state(database, security=True)
        assert current_session(client) == anonymous
        # The recovery route ignores even a stale supplied context.
        recovered = client.get("/api/session", headers={HEADER: "f" * 64})
        assert recovered.status_code == 200 and recovered.json() == anonymous
        assert state(database, security=True) == before
        signed_in = client.post("/api/login", json={"email": "alex@northline.example", "password": TEST_PASSWORD},
                                headers=context_headers(anonymous))
        assert signed_in.status_code == 200, signed_in.text
        authenticated = signed_in.json()
        assert authenticated["authenticated"]
        assert re.fullmatch(r"[0-9a-f]{64}", authenticated["session_context"])
        assert authenticated["session_context"] != anonymous["session_context"]
        assert current_session(client) == authenticated


def test_context_survives_a_new_application_instance_with_the_same_cookie(northline, database):
    client, _ = northline
    payload = current_session(client)
    token = client.cookies.get(COOKIE)
    replacement = create_app(Settings(database_url=database, origin=ORIGIN, secure_cookie=False))
    with TestClient(replacement, raise_server_exceptions=False) as restarted:
        restarted.cookies.set(COOKIE, token)
        assert current_session(restarted) == payload
        response = restarted.get("/api/exceptions", headers={HEADER: payload["session_context"]})
        assert response.status_code == 200 and response.json()["items"]
    # This checks new app construction, separately from root's real process restart consumer.


@pytest.mark.parametrize("path", ["/api/members", "/api/exceptions", f"/api/exceptions/{OWN_ID}",
                                  f"/api/exceptions/{OWN_ID}/history"])
def test_stale_context_denies_each_private_read_without_business_effects(northline, database, path):
    client, _ = northline
    payload = current_session(client)
    wrong = "0" * 64 if payload["session_context"] != "0" * 64 else "1" * 64
    before = state(database, security=True)
    assert_session_changed(client.get(path, headers={HEADER: wrong}), wrong, payload["session_context"], payload["csrf_token"])
    assert state(database, security=True) == before
    assert client.get(path, headers={HEADER: payload["session_context"]}).status_code == 200


def test_missing_context_preserves_legacy_reads_mutations_and_logout(northline):
    client, legacy_headers = northline
    payload = current_session(client)
    for path in ("/api/members", "/api/exceptions", f"/api/exceptions/{OWN_ID}", f"/api/exceptions/{OWN_ID}/history"):
        legacy = client.get(path)
        current = client.get(path, headers={HEADER: payload["session_context"]})
        assert legacy.status_code == current.status_code == 200
        assert legacy.json() == current.json()
    created = client.post("/api/exceptions", json=create_body("LEGACY-CONTEXT-OPTIONAL"),
                          headers={**legacy_headers, "Idempotency-Key": str(uuid4())})
    assert created.status_code == 201, created.text
    assert client.post("/api/logout", headers=legacy_headers).status_code == 204
    assert client.get("/api/members").status_code == 401


def test_empty_duplicate_noncanonical_and_oversized_headers_deny_generically(northline, database):
    client, _ = northline
    payload = current_session(client)
    marker = payload["session_context"]
    invalid = ["", "A" * 64, "g" * 64, "0" * 63, "0" * 65, " " + marker,
               marker + " ", marker + "," + marker, "x" * 1025, "private-context-input"]
    before = state(database, security=True)
    errors = [assert_session_changed(client.get("/api/members", headers={HEADER: value}), marker, value)
              for value in invalid]
    for values in ([(HEADER, marker), (HEADER, marker)],
                   [(HEADER, marker), (HEADER.lower(), "f" * 64)]):
        errors.append(assert_session_changed(client.get("/api/members", headers=values), marker))
    assert all(error == errors[0] for error in errors)
    assert state(database, security=True) == before


@pytest.mark.parametrize("next_email", ["alex@northline.example", "sam@northline.example", "jules@harbor.example"])
def test_login_rotates_context_for_same_and_different_actors(northline, database, next_email):
    client, _ = northline
    old = current_session(client)
    response = client.post("/api/login", json={"email": next_email, "password": TEST_PASSWORD},
                           headers=context_headers(old))
    assert response.status_code == 200, response.text
    new = response.json()
    assert new["user"]["email"] == next_email
    assert new["session_context"] != old["session_context"]
    before = state(database, security=True)
    assert_session_changed(client.get("/api/exceptions", headers={HEADER: old["session_context"]}),
                           old["session_context"], new["session_context"])
    assert state(database, security=True) == before
    current = client.get("/api/exceptions", headers={HEADER: new["session_context"]})
    assert current.status_code == 200
    prefix = "HS-" if next_email.endswith("@harbor.example") else "NL-"
    assert all(row["reference"].startswith(prefix) for row in current.json()["items"])


def test_login_context_is_checked_before_csrf_password_work_and_admission(app, northline, database):
    client, _ = northline
    payload = current_session(client)
    before = state(database, security=True)
    invalid_headers = {"Origin": "https://untrusted.invalid", HEADER: "x" * 64,
                       "Content-Type": "application/json", "X-CSRF-Token": "wrong-csrf"}
    response = client.post("/api/login", json={"email": "jules@harbor.example", "password": "wrong-password"},
                           headers=invalid_headers)
    assert_session_changed(response, payload["session_context"], payload["csrf_token"])
    assert state(database, security=True) == before
    assert current_session(client) == payload
    # The same generic context error applies before login's CSRF check when no cookie exists.
    with TestClient(app, raise_server_exceptions=False) as anonymous:
        missing = anonymous.post("/api/login", json={"email": "alex@northline.example", "password": TEST_PASSWORD},
                                 headers={HEADER: payload["session_context"]})
        assert_session_changed(missing, payload["session_context"])


def test_stale_context_blocks_all_business_mutations_and_does_not_reserve_keys(northline, database):
    client, _ = northline
    payload = current_session(client)
    wrong = "0" * 64 if payload["session_context"] != "0" * 64 else "1" * 64
    requests = [
        ("/api/exceptions", create_body("DENIED-KEY-LATER-ACCEPTED")),
        (f"/api/exceptions/{OWN_ID}/assign", {"expected_version": 1, "assignee_id": None}),
        (f"/api/exceptions/{OWN_ID}/resolve", {"expected_version": 1, "resolution": "Synthetic resolution"}),
    ]
    before = state(database, security=True)
    keys = []
    for path, body in requests:
        key = str(uuid4())
        keys.append(key)
        response = client.post(path, json=body, headers={**context_headers(payload), HEADER: wrong, "Idempotency-Key": key})
        assert_session_changed(response, wrong, payload["session_context"])
    assert state(database, security=True) == before
    accepted = client.post(requests[0][0], json=requests[0][1],
                           headers=context_headers(payload, **{"Idempotency-Key": keys[0]}))
    assert accepted.status_code == 201 and accepted.headers["Idempotency-Replayed"] == "false"
    after = state(database)
    assert len(after["mutation_requests"]) == len(before["mutation_requests"]) + 1
    assert len(after["exception_events"]) == len(before["exception_events"]) + 1


def test_stale_context_denies_old_receipt_without_changing_it_and_current_context_replays(northline, database):
    client, _ = northline
    old = current_session(client)
    key = str(uuid4())
    body = create_body("SAVED-BEFORE-SESSION-ROTATION")
    original = client.post("/api/exceptions", json=body, headers=context_headers(old, **{"Idempotency-Key": key}))
    assert original.status_code == 201, original.text
    relogin = client.post("/api/login", json={"email": old["user"]["email"], "password": TEST_PASSWORD},
                         headers=context_headers(old))
    assert relogin.status_code == 200
    new = relogin.json()
    before = state(database)
    denied = client.post("/api/exceptions", json=body,
                         headers={**context_headers(new), HEADER: old["session_context"], "Idempotency-Key": key})
    assert_session_changed(denied, old["session_context"], new["session_context"])
    assert state(database) == before
    replay = client.post("/api/exceptions", json=body, headers=context_headers(new, **{"Idempotency-Key": key}))
    assert replay.status_code == original.status_code and replay.json() == original.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert state(database) == before


def test_wrong_context_logout_preserves_actual_session_and_correct_logout_ends_it(northline, database):
    client, _ = northline
    payload = current_session(client)
    token = client.cookies.get(COOKIE)
    before = state(database, security=True)
    response = client.post("/api/logout", headers={**context_headers(payload), HEADER: "x" * 64})
    assert_session_changed(response, payload["session_context"])
    assert "set-cookie" not in response.headers
    assert client.cookies.get(COOKIE) == token
    assert state(database, security=True) == before
    assert current_session(client) == payload
    assert client.post("/api/logout", headers=context_headers(payload)).status_code == 204
    assert client.get("/api/members", headers={HEADER: payload["session_context"]}).status_code == 401


def test_marker_alone_does_not_authenticate_and_protected_routes_authenticate_first(app, northline):
    authenticated, _ = northline
    payload = current_session(authenticated)
    with TestClient(app, raise_server_exceptions=False) as anonymous:
        for path in ("/api/members", "/api/exceptions", f"/api/exceptions/{OWN_ID}", f"/api/exceptions/{OWN_ID}/history"):
            response = anonymous.get(path, headers={HEADER: payload["session_context"]})
            assert response.status_code == 401 and response.json()["error"]["code"] == "not_authenticated"
            assert anonymous.get(path, headers={"Cookie": f"{COOKIE}={payload['session_context']}"}).status_code == 401
        response = anonymous.post("/api/exceptions", json=create_body(), headers=context_headers(payload, **{"Idempotency-Key": str(uuid4())}))
        assert response.status_code == 401 and response.json()["error"]["code"] == "not_authenticated"
        assert anonymous.post("/api/logout", headers=context_headers(payload)).status_code == 401


def test_correct_context_cannot_override_csrf_organization_or_current_role(northline, database):
    client, _ = northline
    payload = current_session(client)
    before = state(database)
    for path in (f"/api/exceptions/{FOREIGN_ID}", f"/api/exceptions/{FOREIGN_ID}/history"):
        response = client.get(path, headers={HEADER: payload["session_context"], "X-Organization-ID": str(UUID(int=2))})
        assert response.status_code == 404
    missing_csrf = client.post("/api/exceptions", json=create_body("CONTEXT-NOT-CSRF"),
                               headers={"Origin": ORIGIN, HEADER: payload["session_context"], "Idempotency-Key": str(uuid4())})
    assert missing_csrf.status_code == 403 and missing_csrf.json()["error"]["code"] == "csrf_failed"
    wrong_origin = client.post("/api/exceptions", json=create_body("CONTEXT-NOT-ORIGIN"),
                               headers={**context_headers(payload), "Origin": "https://untrusted.invalid", "Idempotency-Key": str(uuid4())})
    assert wrong_origin.status_code == 403 and wrong_origin.json()["error"]["code"] == "csrf_failed"
    assert state(database) == before
    with psycopg.connect(database) as conn:
        conn.execute("UPDATE users SET role='reviewer' WHERE id=%s", (UUID(payload["user"]["id"]),))
    refreshed = current_session(client)
    assert refreshed["session_context"] == payload["session_context"] and refreshed["user"]["role"] == "reviewer"
    before = state(database)
    denied = client.post("/api/exceptions", json=create_body("ROLE-STILL-REQUIRED"),
                         headers=context_headers(refreshed, **{"Idempotency-Key": str(uuid4())}))
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "read_only"
    assert state(database) == before
    assert client.get("/api/exceptions", headers={HEADER: refreshed["session_context"]}).status_code == 200


def test_expired_cookie_context_cannot_revive_session_and_recovery_issues_anonymous_context(northline, database):
    client, _ = northline
    payload = current_session(client)
    token_hash = sha256(client.cookies.get(COOKIE).encode()).hexdigest()
    with psycopg.connect(database) as conn:
        conn.execute("UPDATE sessions SET expires_at=now()-interval '1 second' WHERE token_hash=%s", (token_hash,))
    response = client.get("/api/members", headers={HEADER: payload["session_context"]})
    assert response.status_code == 401
    recovered = client.get("/api/session", headers={HEADER: payload["session_context"]})
    assert recovered.status_code == 200 and not recovered.json()["authenticated"]
    assert recovered.json()["session_context"] != payload["session_context"]
