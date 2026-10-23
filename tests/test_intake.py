"""Manual intake contract and real PostgreSQL transaction boundaries."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from conftest import ORIGIN, authenticated_client


def intake(client, headers, body=None, key=None):
    return client.post(
        "/api/exceptions",
        json=body if body is not None else intake_body(),
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
    )


def intake_body(**changes):
    return {
        "reference": "MANUAL-1042",
        "summary": "Synthetic receiving appointment missed",
        "details": "Confirm the next receiving window with the synthetic carrier.",
        "priority": "high",
        **changes,
    }


def workflow_rows(database):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return {
            "exceptions": conn.execute("SELECT * FROM shipment_exceptions ORDER BY id").fetchall(),
            "events": conn.execute("SELECT * FROM exception_events ORDER BY id").fetchall(),
            "receipts": conn.execute(
                "SELECT * FROM mutation_requests ORDER BY organization_id, actor_id, key"
            ).fetchall(),
        }


def assert_error(response, status, code=None):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert isinstance(error["message"], str) and error["message"]
    if code is not None:
        assert error["code"] == code


def test_intake_creates_server_owned_state_and_a_single_audit_event(
    northline, identities, database
):
    client, headers = northline
    before = workflow_rows(database)
    response = intake(client, headers, intake_body(
        reference="  MANUAL-1042 \t", summary=" Synthetic exception ",
        details="\nSynthetic carrier notes. \t", priority=" high ",
    ))
    assert response.status_code == 201, response.text
    item = response.json()["exception"]
    UUID(item["id"])
    assert item["reference"] == "MANUAL-1042"
    assert item["summary"] == "Synthetic exception"
    assert item["details"] == "Synthetic carrier notes."
    assert item["priority"] == "high"
    assert item["status"] == "open"
    assert item["assignee_id"] is None and item["assignee_name"] is None
    assert item["resolution"] is None
    assert item["version"] == 1
    detail = client.get(f"/api/exceptions/{item['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["exception"] == item
    events = detail.json()["events"]
    assert len(events) == 1
    assert events[0]["action"] == "created" and events[0]["version"] == 1
    after = workflow_rows(database)
    assert len(after["exceptions"]) == len(before["exceptions"]) + 1
    assert len(after["events"]) == len(before["events"]) + 1
    assert len(after["receipts"]) == len(before["receipts"]) + 1
    saved = next(row for row in after["exceptions"] if str(row["id"]) == item["id"])
    event = next(row for row in after["events"] if str(row["exception_id"]) == item["id"])
    actor = identities["alex@northline.example"]
    assert saved["organization_id"] == actor["organization_id"]
    assert event["organization_id"] == actor["organization_id"]
    assert event["actor_id"] == actor["id"]
    assert event["assignee_id"] is None


def test_intake_does_not_accept_client_owned_identity_or_workflow_state(
    northline, identities, database
):
    client, headers = northline
    before = workflow_rows(database)
    spoofed_fields = {
        "id": str(uuid4()),
        "organization_id": str(identities["jules@harbor.example"]["organization_id"]),
        "actor_id": str(identities["jules@harbor.example"]["id"]),
        "status": "resolved",
        "assignee_id": str(identities["sam@northline.example"]["id"]),
        "resolution": "Client supplied resolution",
        "version": 700,
        "updated_at": "2030-01-01T00:00:00Z",
        "events": [],
    }
    for field, value in spoofed_fields.items():
        response = intake(client, headers, intake_body(**{field: value}))
        assert response.status_code in (400, 422), (field, response.text)
        assert workflow_rows(database) == before


def test_intake_uses_authenticated_organization_even_with_a_spoofed_header(
    northline, harbor, identities, database
):
    north, headers = northline
    other, _ = harbor
    other_organization = identities["jules@harbor.example"]["organization_id"]
    response = intake(north, {
        **headers, "X-Organization-ID": str(other_organization),
        "X-User-ID": str(identities["jules@harbor.example"]["id"]),
    })
    assert response.status_code == 201, response.text
    item = response.json()["exception"]
    assert_error(other.get(f"/api/exceptions/{item['id']}"), 404)
    assert item["id"] not in {row["id"] for row in other.get("/api/exceptions").json()["items"]}
    with psycopg.connect(database) as conn:
        saved_org = conn.execute(
            "SELECT organization_id FROM shipment_exceptions WHERE id=%s", (item["id"],)
        ).fetchone()[0]
    assert saved_org == identities["alex@northline.example"]["organization_id"]


def test_intake_requires_authentication_origin_and_csrf(app, northline, database):
    before = workflow_rows(database)
    with TestClient(app, raise_server_exceptions=False) as anonymous:
        anonymous.get("/api/session")
        response = intake(anonymous, {"Origin": ORIGIN})
        assert_error(response, 401)
    client, valid = northline
    for invalid in (
        {"Origin": ORIGIN},
        {"Origin": ORIGIN, "X-CSRF-Token": "incorrect"},
        {"X-CSRF-Token": valid["X-CSRF-Token"]},
        {"Origin": "https://outside.example", "X-CSRF-Token": valid["X-CSRF-Token"]},
    ):
        assert_error(intake(client, {"Content-Type": "application/json", **invalid}), 403)
    assert workflow_rows(database) == before


@pytest.mark.parametrize("key", [None, "not-a-uuid"])
def test_intake_requires_a_uuid_idempotency_key(northline, database, key):
    client, headers = northline
    before = workflow_rows(database)
    supplied = {**headers}
    if key is not None:
        supplied["Idempotency-Key"] = key
    response = client.post("/api/exceptions", json=intake_body(), headers=supplied)
    assert_error(response, 422, "invalid_idempotency_key")
    assert workflow_rows(database) == before


@pytest.mark.parametrize("changes", [
    {"reference": " \t\n"}, {"summary": " \t\n"}, {"details": " \t\n"},
    {"reference": "x" * 81}, {"summary": "x" * 201}, {"details": "x" * 4001},
    {"priority": "urgent"}, {"priority": "HIGH"},
    {"reference": None}, {"reference": 123}, {"summary": False},
])
def test_invalid_intake_fields_cannot_write_rows(northline, database, changes):
    client, headers = northline
    before = workflow_rows(database)
    response = intake(client, headers, intake_body(**changes))
    assert response.status_code in (400, 422), response.text
    assert workflow_rows(database) == before


def test_intake_accepts_the_declared_text_boundaries(northline):
    client, headers = northline
    payload = intake_body(reference="r" * 80, summary="s" * 200, details="d" * 4000,
                          priority="normal")
    response = intake(client, headers, payload)
    assert response.status_code == 201, response.text
    item = response.json()["exception"]
    assert {field: item[field] for field in payload} == payload


def test_references_are_trimmed_case_sensitive_and_unique_only_within_an_organization(
    northline, harbor, database
):
    north, headers = northline
    other, other_headers = harbor
    first = intake(north, headers, intake_body(reference="  Shared-42  "))
    assert first.status_code == 201, first.text
    before = workflow_rows(database)
    duplicate = intake(north, headers, intake_body(reference="Shared-42"))
    assert_error(duplicate, 409, "reference_conflict")
    after_duplicate = workflow_rows(database)
    assert after_duplicate["exceptions"] == before["exceptions"]
    assert after_duplicate["events"] == before["events"]
    case_distinct = intake(north, headers, intake_body(reference="shared-42"))
    assert case_distinct.status_code == 201, case_distinct.text
    other_org = intake(other, other_headers, intake_body(reference="Shared-42"))
    assert other_org.status_code == 201, other_org.text
    assert first.json()["exception"]["id"] != other_org.json()["exception"]["id"]
    assert_error(north.get(f"/api/exceptions/{other_org.json()['exception']['id']}"), 404)
    assert_error(other.get(f"/api/exceptions/{first.json()['exception']['id']}"), 404)


def test_intake_retry_uses_validated_content_and_rejects_reused_keys(northline, database):
    client, headers = northline
    key = str(uuid4())
    first = intake(client, headers, intake_body(reference=" MANUAL-1042 "), key)
    assert first.status_code == 201, first.text
    committed = workflow_rows(database)
    replay_body = dict(reversed(list(intake_body().items())))
    replay = intake(client, headers, replay_body, key)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert workflow_rows(database) == committed
    for field, value in (("reference", "OTHER-REF"), ("summary", "Changed summary"),
                         ("details", "Changed details"), ("priority", "normal")):
        rejected = intake(client, headers, intake_body(**{field: value}), key)
        assert_error(rejected, 409, "idempotency_conflict")
        assert workflow_rows(database) == committed


def test_reference_conflict_is_a_saved_retry_result_not_a_second_creation(northline, database):
    client, headers = northline
    created = intake(client, headers)
    assert created.status_code == 201, created.text
    before_conflict = workflow_rows(database)
    key = str(uuid4())
    conflict = intake(client, headers, key=key)
    assert_error(conflict, 409, "reference_conflict")
    assert conflict.headers["Idempotency-Replayed"] == "false"
    committed = workflow_rows(database)
    assert committed["exceptions"] == before_conflict["exceptions"]
    assert committed["events"] == before_conflict["events"]
    assert len(committed["receipts"]) == len(before_conflict["receipts"]) + 1
    saved_receipt = next(row for row in committed["receipts"] if str(row["key"]) == key)
    assert saved_receipt["status_code"] == 409
    assert saved_receipt["response"] == conflict.json()
    replay = intake(client, headers, key=key)
    assert replay.status_code == 409 and replay.json() == conflict.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert workflow_rows(database) == committed
    changed = intake(client, headers, intake_body(reference="A-DIFFERENT-REFERENCE"), key)
    assert_error(changed, 409, "idempotency_conflict")
    assert workflow_rows(database) == committed


def test_one_retry_key_is_independent_for_two_actors_creating_distinct_references(app, northline):
    alex, alex_headers = northline
    key = str(uuid4())
    first = intake(alex, alex_headers, intake_body(reference="ALEX-INTAKE"), key)
    assert first.status_code == 201, first.text
    with authenticated_client(app, "sam@northline.example") as (sam, sam_headers):
        second = intake(sam, sam_headers, intake_body(reference="SAM-INTAKE"), key)
    assert second.status_code == 201, second.text
    assert first.json()["exception"]["id"] != second.json()["exception"]["id"]


def test_create_and_existing_assignment_share_the_actor_retry_key_namespace(
    northline, open_exception, database
):
    client, headers = northline
    key = str(uuid4())
    assigned = client.post(
        f"/api/exceptions/{open_exception['id']}/assign",
        json={"expected_version": open_exception["version"], "assignee_id": None},
        headers={**headers, "Idempotency-Key": key},
    )
    assert assigned.status_code == 200, assigned.text
    before = workflow_rows(database)
    denied = intake(client, headers, key=key)
    assert_error(denied, 409, "idempotency_conflict")
    assert workflow_rows(database) == before
    create_key = str(uuid4())
    created = intake(client, headers, key=create_key)
    assert created.status_code == 201, created.text
    before_assign = workflow_rows(database)
    denied_assign = client.post(
        f"/api/exceptions/{created.json()['exception']['id']}/assign",
        json={"expected_version": 1, "assignee_id": None},
        headers={**headers, "Idempotency-Key": create_key},
    )
    assert_error(denied_assign, 409, "idempotency_conflict")
    assert workflow_rows(database) == before_assign


def test_creation_replay_returns_historical_response_without_rewinding_later_edits(
    northline, identities, database
):
    client, headers = northline
    key = str(uuid4())
    first = intake(client, headers, key=key)
    assert first.status_code == 201, first.text
    item_id = first.json()["exception"]["id"]
    assigned = client.post(
        f"/api/exceptions/{item_id}/assign",
        json={"expected_version": 1, "assignee_id": str(identities["sam@northline.example"]["id"])},
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert assigned.status_code == 200, assigned.text
    resolved = client.post(
        f"/api/exceptions/{item_id}/resolve",
        json={"expected_version": 2, "resolution": "Synthetic handoff completed."},
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert resolved.status_code == 200, resolved.text
    before = workflow_rows(database)
    replay = intake(client, headers, deepcopy(intake_body()), key)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert replay.json()["exception"]["version"] == 1
    current = client.get(f"/api/exceptions/{item_id}").json()
    assert current["exception"]["status"] == "resolved"
    assert current["exception"]["version"] == 3
    assert [event["action"] for event in current["events"]] == ["created", "assigned", "resolved"]
    assert workflow_rows(database) == before


@pytest.mark.parametrize("invalidate", ["logout", "expire"])
def test_invalidated_session_cannot_replay_intake(northline, database, invalidate):
    client, headers = northline
    key = str(uuid4())
    first = intake(client, headers, key=key)
    assert first.status_code == 201, first.text
    saved_cookies = dict(client.cookies)
    before = workflow_rows(database)
    if invalidate == "logout":
        assert client.post("/api/logout", headers=headers).status_code == 204
    else:
        with psycopg.connect(database) as conn:
            conn.execute("UPDATE sessions SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second'")
    client.cookies.clear()
    client.cookies.update(saved_cookies)
    assert_error(intake(client, headers, key=key), 401)
    assert workflow_rows(database) == before


def test_two_independent_clients_retrying_one_creation_have_one_committed_effect(app, database):
    key = str(uuid4())
    before = workflow_rows(database)
    barrier = Barrier(2, timeout=15)

    def worker():
        with authenticated_client(app) as (client, headers):
            barrier.wait()
            response = intake(client, headers, key=key)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert [status for status, _ in results] == [201, 201], results
    assert results[0][1] == results[1][1]
    after = workflow_rows(database)
    assert len(after["exceptions"]) == len(before["exceptions"]) + 1
    assert len(after["events"]) == len(before["events"]) + 1
    assert len(after["receipts"]) == len(before["receipts"]) + 1


def test_two_actors_racing_one_reference_have_one_creation_and_one_conflict(app, database):
    before = workflow_rows(database)
    barrier = Barrier(2, timeout=15)

    def worker(email):
        with authenticated_client(app, email) as (client, headers):
            barrier.wait()
            response = intake(client, headers)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, email) for email in
                   ("alex@northline.example", "sam@northline.example")]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(status for status, _ in results) == [201, 409], results
    conflict = next(body for status, body in results if status == 409)
    assert conflict["error"]["code"] == "reference_conflict"
    after = workflow_rows(database)
    assert len(after["exceptions"]) == len(before["exceptions"]) + 1
    assert len(after["events"]) == len(before["events"]) + 1


def test_failed_creation_audit_insert_rolls_back_object_and_retry_receipt(northline, database):
    client, headers = northline
    key = str(uuid4())
    before = workflow_rows(database)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION test_reject_created_event() RETURNS trigger LANGUAGE plpgsql "
            "AS $$ BEGIN IF NEW.action='created' THEN RAISE EXCEPTION 'synthetic intake audit failure'; "
            "END IF; RETURN NEW; END; $$"
        )
        conn.execute(
            "CREATE TRIGGER test_intake_event_failure BEFORE INSERT ON exception_events "
            "FOR EACH ROW EXECUTE FUNCTION test_reject_created_event()"
        )
    try:
        failed = intake(client, headers, key=key)
        assert_error(failed, 500)
        assert "synthetic intake audit failure" not in failed.text
        assert workflow_rows(database) == before
    finally:
        with psycopg.connect(database, autocommit=True) as conn:
            conn.execute("DROP TRIGGER IF EXISTS test_intake_event_failure ON exception_events")
            conn.execute("DROP FUNCTION IF EXISTS test_reject_created_event()")
    retry = intake(client, headers, key=key)
    assert retry.status_code == 201, retry.text
    after = workflow_rows(database)
    assert len(after["exceptions"]) == len(before["exceptions"]) + 1
    assert len(after["events"]) == len(before["events"]) + 1
    assert len(after["receipts"]) == len(before["receipts"]) + 1


def test_intake_treats_sql_and_html_text_as_literal_data(northline, database):
    client, headers = northline
    body = intake_body(
        reference="REF'; DROP TABLE users; --",
        summary="<script>window.syntheticIntake=true</script>",
        details="<img src=x onerror=alert(1)> Synthetic café handoff. ' OR 1=1; --",
    )
    response = intake(client, headers, body)
    assert response.status_code == 201, response.text
    saved = client.get(f"/api/exceptions/{response.json()['exception']['id']}")
    assert saved.status_code == 200, saved.text
    assert {field: saved.json()["exception"][field] for field in body} == body
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 4
