"""Exercise authorization and transactional writes against actual PostgreSQL."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import json
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from conftest import ORIGIN, TEST_PASSWORD, authenticated_client


def mutation(client, headers, exception_id, action, payload, key=None):
    return client.post(
        f"/api/exceptions/{exception_id}/{action}",
        json=payload,
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
    )


def detail(client, exception_id):
    response = client.get(f"/api/exceptions/{exception_id}")
    assert response.status_code == 200, response.text
    return response.json()


def db_state(database, exception_id):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        item = conn.execute(
            "SELECT * FROM shipment_exceptions WHERE id = %s", (exception_id,)
        ).fetchone()
        events = conn.execute(
            "SELECT * FROM exception_events WHERE exception_id = %s ORDER BY id",
            (exception_id,),
        ).fetchall()
        receipts = conn.execute("SELECT * FROM mutation_requests ORDER BY key, actor_id").fetchall()
    return item, events, receipts


def assert_error(response, status, code=None):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert isinstance(error["message"], str) and error["message"]
    if code is not None:
        assert error["code"] == code


def test_unauthenticated_endpoints_require_a_session(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        for path in ("/api/exceptions", "/api/members", f"/api/exceptions/{uuid4()}"):
            assert_error(client.get(path), 401)
        assert_error(
            client.post(
                f"/api/exceptions/{uuid4()}/resolve",
                json={"expected_version": 1, "resolution": "Synthetic resolution"},
                headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid4())},
            ),
            401,
        )


def test_list_members_detail_and_mutations_are_organization_scoped(
    northline, harbor, identities, database
):
    north, north_headers = northline
    other, other_headers = harbor
    north_items = north.get("/api/exceptions").json()["items"]
    other_items = other.get("/api/exceptions").json()["items"]
    assert north_items and other_items
    assert {row["id"] for row in north_items}.isdisjoint(row["id"] for row in other_items)
    north_members = north.get("/api/members").json()["items"]
    other_members = other.get("/api/members").json()["items"]
    assert {row["email"] for row in north_members} == {
        "alex@northline.example", "sam@northline.example"
    }
    assert {row["email"] for row in other_members} == {
        "jules@harbor.example", "robin@harbor.example"
    }
    for outsider, outsider_headers, item in (
        (north, north_headers, other_items[0]),
        (other, other_headers, north_items[0]),
    ):
        before = db_state(database, item["id"])
        assert_error(outsider.get(f"/api/exceptions/{item['id']}"), 404)
        response = mutation(
            outsider, outsider_headers, item["id"], "resolve",
            {"expected_version": item["version"], "resolution": "Not authorized"},
        )
        assert_error(response, 404)
        after = db_state(database, item["id"])
        assert after[:2] == before[:2]
    assert identities["alex@northline.example"]["organization_id"] != identities[
        "jules@harbor.example"
    ]["organization_id"]
    spoofed = north.get("/api/exceptions", headers={
        "X-Organization-ID": str(identities["jules@harbor.example"]["organization_id"])
    })
    assert spoofed.status_code == 200, spoofed.text
    assert spoofed.json()["items"] == north_items


def test_cross_organization_assignment_is_rejected_by_api_and_database(
    northline, identities, open_exception, database
):
    client, headers = northline
    outsider_id = str(identities["jules@harbor.example"]["id"])
    before = db_state(database, open_exception["id"])
    response = mutation(
        client, headers, open_exception["id"], "assign",
        {"expected_version": open_exception["version"], "assignee_id": outsider_id},
    )
    assert_error(response, 400)
    assert db_state(database, open_exception["id"])[:2] == before[:2]
    with psycopg.connect(database) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "UPDATE shipment_exceptions SET assignee_id = %s WHERE id = %s",
                (outsider_id, open_exception["id"]),
            )


def test_assignment_and_resolution_commit_versions_and_audit_events(
    northline, identities, open_exception, database
):
    client, headers = northline
    exception_id = open_exception["id"]
    before = detail(client, exception_id)
    original_version = before["exception"]["version"]
    sam_id = str(identities["sam@northline.example"]["id"])
    assigned = mutation(
        client, headers, exception_id, "assign",
        {"expected_version": original_version, "assignee_id": sam_id},
    )
    assert assigned.status_code == 200, assigned.text
    assigned_item = assigned.json()["exception"]
    assert assigned_item["assignee_id"] == sam_id
    assert assigned_item["version"] == original_version + 1
    assert assigned_item["status"] == "open"
    resolved = mutation(
        client, headers, exception_id, "resolve",
        {"expected_version": assigned_item["version"], "resolution": "Carrier confirmed delivery."},
    )
    assert resolved.status_code == 200, resolved.text
    item, events, receipts = db_state(database, exception_id)
    assert item["version"] == original_version + 2
    assert item["status"] == "resolved"
    assert item["resolution"] == "Carrier confirmed delivery."
    assert len(events) == len(before["events"]) + 2
    assert len(receipts) == 2
    assert all(row["actor_id"] == identities["alex@northline.example"]["id"] for row in events)
    assert len(detail(client, exception_id)["events"]) == len(events)


def test_stale_version_cannot_overwrite_a_committed_change(northline, identities, open_exception, database):
    client, headers = northline
    sam_id = str(identities["sam@northline.example"]["id"])
    first = mutation(
        client, headers, open_exception["id"], "assign",
        {"expected_version": open_exception["version"], "assignee_id": sam_id},
    )
    assert first.status_code == 200, first.text
    before = db_state(database, open_exception["id"])
    stale = mutation(
        client, headers, open_exception["id"], "resolve",
        {"expected_version": open_exception["version"], "resolution": "Stale operator view"},
    )
    assert_error(stale, 409)
    assert stale.json()["error"]["current_version"] == open_exception["version"] + 1
    assert db_state(database, open_exception["id"])[:2] == before[:2]


def test_retry_returns_committed_response_and_key_mismatches_do_not_write(
    northline, identities, open_exception, database
):
    client, headers = northline
    exception_id = open_exception["id"]
    payload = {
        "expected_version": open_exception["version"],
        "assignee_id": str(identities["sam@northline.example"]["id"]),
    }
    key = str(uuid4())
    first = mutation(client, headers, exception_id, "assign", payload, key)
    assert first.status_code == 200, first.text
    committed = db_state(database, exception_id)
    # A response lost after commit is retried with the same semantic request.
    retry = mutation(client, headers, exception_id, "assign", deepcopy(payload), key)
    assert retry.status_code == first.status_code
    assert retry.json() == first.json()
    assert db_state(database, exception_id) == committed
    changed = mutation(
        client, headers, exception_id, "assign", {**payload, "assignee_id": None}, key
    )
    assert_error(changed, 409)
    changed_action = mutation(
        client, headers, exception_id, "resolve",
        {"expected_version": open_exception["version"], "resolution": "Different action"}, key,
    )
    assert_error(changed_action, 409)
    another = next(item for item in client.get("/api/exceptions").json()["items"] if item["id"] != exception_id)
    changed_object = mutation(client, headers, another["id"], "assign", payload, key)
    assert_error(changed_object, 409)
    assert db_state(database, exception_id) == committed
    later = mutation(
        client, headers, exception_id, "resolve",
        {"expected_version": first.json()["exception"]["version"], "resolution": "Later committed change"},
    )
    assert later.status_code == 200, later.text
    current = db_state(database, exception_id)
    historical = mutation(client, headers, exception_id, "assign", payload, key)
    assert historical.status_code == 200, historical.text
    assert historical.json() == first.json()
    assert historical.json()["exception"]["version"] < current[0]["version"]
    assert db_state(database, exception_id) == current


def test_idempotency_uses_validated_content_instead_of_json_serialization(
    northline, identities, open_exception, database
):
    client, headers = northline
    payload = {
        "expected_version": open_exception["version"],
        "assignee_id": str(identities["sam@northline.example"]["id"]),
    }
    key = str(uuid4())
    first = mutation(client, headers, open_exception["id"], "assign", payload, key)
    assert first.status_code == 200, first.text
    before = db_state(database, open_exception["id"])
    reordered = dict(reversed(list(payload.items())))
    replay = client.post(
        f"/api/exceptions/{open_exception['id']}/assign",
        content=json.dumps(reordered, indent=4),
        headers={
            **headers, "Idempotency-Key": key, "Content-Type": "application/json",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert db_state(database, open_exception["id"]) == before


def test_same_key_is_independent_for_two_authenticated_actors(
    app, northline, identities, open_exception, database
):
    alex, alex_headers = northline
    key = str(uuid4())
    first = mutation(
        alex, alex_headers, open_exception["id"], "assign",
        {
            "expected_version": open_exception["version"],
            "assignee_id": str(identities["sam@northline.example"]["id"]),
        }, key,
    )
    assert first.status_code == 200, first.text
    with authenticated_client(app, "sam@northline.example") as (sam, sam_headers):
        second = mutation(
            sam, sam_headers, open_exception["id"], "resolve",
            {
                "expected_version": first.json()["exception"]["version"],
                "resolution": "A second authorized operator completed the task.",
            }, key,
        )
    assert second.status_code == 200, second.text
    item, events, receipts = db_state(database, open_exception["id"])
    assert item["version"] == open_exception["version"] + 2
    assert len(receipts) == 2
    assert {str(row["key"]) for row in receipts} == {key}
    assert {row["actor_id"] for row in receipts} == {
        identities["alex@northline.example"]["id"], identities["sam@northline.example"]["id"],
    }
    assert len(events) == 2


@pytest.mark.parametrize("same_key", [False, True], ids=["competing-versions", "duplicate-request"])
def test_two_independent_clients_race_without_duplicate_effects(
    app, open_exception, identities, database, same_key
):
    exception_id = open_exception["id"]
    before = db_state(database, exception_id)
    payload = {
        "expected_version": open_exception["version"],
        "assignee_id": str(identities["sam@northline.example"]["id"]),
    }
    shared_key = str(uuid4())
    barrier = Barrier(2, timeout=15)

    def worker():
        with authenticated_client(app) as (client, headers):
            key = shared_key if same_key else str(uuid4())
            barrier.wait()
            response = mutation(client, headers, exception_id, "assign", payload, key)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(status for status, _ in results) == ([200, 200] if same_key else [200, 409]), results
    if same_key:
        assert results[0][1] == results[1][1]
    item, events, receipts = db_state(database, exception_id)
    assert item["version"] == before[0]["version"] + 1
    assert len(events) == len(before[1]) + 1
    assert len(receipts) == (1 if same_key else 2)


def test_database_failure_rolls_back_exception_event_and_retry_receipt(
    northline, identities, open_exception, database
):
    client, headers = northline
    exception_id = open_exception["id"]
    payload = {
        "expected_version": open_exception["version"],
        "assignee_id": str(identities["sam@northline.example"]["id"]),
    }
    key = str(uuid4())
    before = db_state(database, exception_id)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION test_reject_exception_event() RETURNS trigger LANGUAGE plpgsql "
            "AS $$ BEGIN RAISE EXCEPTION 'synthetic audit failure'; END; $$"
        )
        conn.execute(
            "CREATE TRIGGER test_event_failure BEFORE INSERT ON exception_events "
            "FOR EACH ROW EXECUTE FUNCTION test_reject_exception_event()"
        )
    try:
        failed = mutation(client, headers, exception_id, "assign", payload, key)
        assert_error(failed, 500)
        assert "synthetic audit failure" not in failed.text
        assert db_state(database, exception_id) == before
    finally:
        with psycopg.connect(database, autocommit=True) as conn:
            conn.execute("DROP TRIGGER IF EXISTS test_event_failure ON exception_events")
            conn.execute("DROP FUNCTION IF EXISTS test_reject_exception_event()")
    retry = mutation(client, headers, exception_id, "assign", payload, key)
    assert retry.status_code == 200, retry.text
    item, events, receipts = db_state(database, exception_id)
    assert item["version"] == before[0]["version"] + 1
    assert len(events) == len(before[1]) + 1
    assert len(receipts) == 1


@pytest.mark.parametrize("invalid_headers", [
    {"Origin": ORIGIN},
    {"Origin": ORIGIN, "X-CSRF-Token": "wrong"},
    {"X-CSRF-Token": "VALID"},
    {"Origin": "https://outside.example", "X-CSRF-Token": "VALID"},
])
def test_login_logout_and_writes_require_exact_origin_and_csrf(
    app, northline, open_exception, invalid_headers, database
):
    with TestClient(app, raise_server_exceptions=False) as anonymous:
        token = anonymous.get("/api/session").json()["csrf_token"]
        login_headers = {key: token if value == "VALID" else value for key, value in invalid_headers.items()}
        assert_error(anonymous.post(
            "/api/login", json={"email": "alex@northline.example", "password": TEST_PASSWORD},
            headers=login_headers,
        ), 403)
    client, valid = northline
    headers = {
        key: valid["X-CSRF-Token"] if value == "VALID" else value
        for key, value in invalid_headers.items()
    }
    before = db_state(database, open_exception["id"])
    assert_error(mutation(
        client, headers, open_exception["id"], "resolve",
        {"expected_version": open_exception["version"], "resolution": "Denied"},
    ), 403)
    assert db_state(database, open_exception["id"]) == before
    assert_error(client.post("/api/logout", headers=headers), 403)
    assert client.get("/api/exceptions").status_code == 200


def test_login_rotates_session_cookie_and_csrf_and_logout_invalidates_it(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        anonymous = client.get("/api/session")
        anonymous_cookies = dict(client.cookies)
        anonymous_csrf = anonymous.json()["csrf_token"]
        set_cookie = anonymous.headers["set-cookie"].lower()
        assert "httponly" in set_cookie and "samesite=strict" in set_cookie and "path=/" in set_cookie
        login = client.post(
            "/api/login", json={"email": "alex@northline.example", "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN, "X-CSRF-Token": anonymous_csrf},
        )
        assert login.status_code == 200, login.text
        authenticated_cookies = dict(client.cookies)
        authenticated_csrf = login.json()["csrf_token"]
        assert authenticated_cookies != anonymous_cookies
        assert authenticated_csrf != anonymous_csrf
        assert_error(client.post("/api/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": anonymous_csrf
        }), 403)
        logout = client.post("/api/logout", headers={
            "Origin": ORIGIN, "X-CSRF-Token": authenticated_csrf,
            "Content-Type": "application/json",
        })
        assert logout.status_code == 204, logout.text
        client.cookies.clear()
        client.cookies.update(authenticated_cookies)
        assert_error(client.get("/api/exceptions"), 401)
        client.cookies.clear()
        client.cookies.update(anonymous_cookies)
        assert_error(client.get("/api/exceptions"), 401)


def test_database_stores_a_digest_instead_of_the_bearer_cookie(northline, database):
    client, _ = northline
    cookie_values = list(dict(client.cookies).values())
    assert len(cookie_values) == 1
    cookie = cookie_values[0]
    with psycopg.connect(database, row_factory=dict_row) as conn:
        rows = conn.execute("SELECT token_hash FROM sessions WHERE user_id IS NOT NULL").fetchall()
    assert len(rows) == 1
    assert rows[0]["token_hash"] != cookie
    assert rows[0]["token_hash"] == sha256(cookie.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("invalidate", ["logout", "expire"])
def test_invalidated_session_cannot_replay_a_committed_mutation(
    northline, open_exception, database, invalidate
):
    client, headers = northline
    key = str(uuid4())
    payload = {"expected_version": open_exception["version"], "assignee_id": None}
    first = mutation(client, headers, open_exception["id"], "assign", payload, key)
    assert first.status_code == 200, first.text
    cookies = dict(client.cookies)
    before = db_state(database, open_exception["id"])
    if invalidate == "logout":
        assert client.post("/api/logout", headers=headers).status_code == 204
    else:
        with psycopg.connect(database) as conn:
            conn.execute("UPDATE sessions SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second'")
    client.cookies.clear()
    client.cookies.update(cookies)
    assert_error(mutation(client, headers, open_exception["id"], "assign", payload, key), 401)
    assert db_state(database, open_exception["id"]) == before


@pytest.mark.parametrize("payload", [
    {"expected_version": 0, "resolution": "Done"},
    {"expected_version": 1, "resolution": ""},
    {"expected_version": 1, "resolution": "x" * 2001},
    {"expected_version": 1, "resolution": "Done", "organization_id": str(uuid4())},
    {"expected_version": "1", "resolution": "Done"},
])
def test_invalid_mutation_bodies_do_not_change_database(northline, open_exception, database, payload):
    client, headers = northline
    before = db_state(database, open_exception["id"])
    response = mutation(client, headers, open_exception["id"], "resolve", payload)
    assert response.status_code in (400, 422), response.text
    assert db_state(database, open_exception["id"]) == before


def test_oversized_request_is_rejected_before_writing(northline, open_exception, database):
    client, headers = northline
    before = db_state(database, open_exception["id"])
    response = client.post(
        f"/api/exceptions/{open_exception['id']}/resolve",
        content=b'{"expected_version":1,"resolution":"' + b"x" * 20000 + b'"}',
        headers={**headers, "Idempotency-Key": str(uuid4()), "Content-Type": "application/json"},
    )
    assert response.status_code == 413, response.text
    assert db_state(database, open_exception["id"]) == before


def test_sql_and_html_resolution_strings_are_stored_as_data(northline, open_exception, database):
    client, headers = northline
    literal = "<script>window.synthetic = true</script>'; DROP TABLE users; --"
    response = mutation(
        client, headers, open_exception["id"], "resolve",
        {"expected_version": open_exception["version"], "resolution": literal},
    )
    assert response.status_code == 200, response.text
    assert response.json()["exception"]["resolution"] == literal
    assert detail(client, open_exception["id"])["exception"]["resolution"] == literal
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 4


@pytest.mark.parametrize("statement", [
    "UPDATE shipment_exceptions SET version = 0 WHERE id = %s",
    "UPDATE shipment_exceptions SET status = 'unknown' WHERE id = %s",
    "UPDATE shipment_exceptions SET status = 'resolved', resolution = NULL WHERE id = %s",
])
def test_database_rejects_invalid_state_even_without_api(
    open_exception, database, statement
):
    before = db_state(database, open_exception["id"])
    with psycopg.connect(database) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(statement, (open_exception["id"],))
    assert db_state(database, open_exception["id"]) == before


@pytest.mark.parametrize("status_code,response_json", [
    (None, '{"exception":{}}'),
    (200, None),
], ids=["response-without-status", "status-without-response"])
def test_database_rejects_partial_retry_receipts(
    database, identities, open_exception, status_code, response_json
):
    actor = identities["alex@northline.example"]
    before = db_state(database, open_exception["id"])
    with psycopg.connect(database) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO mutation_requests(organization_id,actor_id,key,fingerprint,status_code,response) "
                "VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
                (actor["organization_id"], actor["id"], uuid4(), "synthetic-fingerprint", status_code, response_json),
            )
    assert db_state(database, open_exception["id"]) == before


def test_non_ascii_csrf_header_is_rejected_without_mutation_or_logout(
    northline, open_exception, database
):
    client, _ = northline
    before = db_state(database, open_exception["id"])
    headers = [
        (b"origin", ORIGIN.encode("ascii")),
        (b"x-csrf-token", b"\xff"),
        (b"content-type", b"application/json"),
        (b"idempotency-key", str(uuid4()).encode("ascii")),
    ]
    denied = client.post(
        f"/api/exceptions/{open_exception['id']}/resolve",
        json={"expected_version": open_exception["version"], "resolution": "Must not be written"},
        headers=headers,
    )
    assert_error(denied, 403, "csrf_failed")
    assert db_state(database, open_exception["id"]) == before
    assert_error(client.post("/api/logout", headers=headers), 403, "csrf_failed")
    assert client.get("/api/exceptions").status_code == 200


def test_login_failures_are_generic_and_do_not_echo_credentials(app):
    responses = []
    for email in ("missing@northline.example", "alex@northline.example"):
        with TestClient(app, raise_server_exceptions=False) as client:
            token = client.get("/api/session").json()["csrf_token"]
            response = client.post(
                "/api/login", json={"email": email, "password": "Wrong-private-input-777"},
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )
            assert_error(response, 401)
            assert "Wrong-private-input-777" not in response.text
            assert email not in response.text
            responses.append(response.json())
    assert responses[0] == responses[1]
