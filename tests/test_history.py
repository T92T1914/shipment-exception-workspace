"""Bounded per-record history against the disposable PostgreSQL database.

The initial histories are labeled SQL fixtures. The append-fence case adds its
later change through the real mutation route rather than modifying a cursor's
expected answer or fabricating an HTTP response.
"""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from copy import deepcopy
import json
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from conftest import authenticated_client
import shipment_workspace.app as app_module


def token_bytes(raw):
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def encode_cursor(payload):
    return token_bytes(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def decode_cursor(token):
    return json.loads(urlsafe_b64decode(token + "=" * (-len(token) % 4)))


def fixture_history(database, organization, actor, ident, count, label, *, creation=True):
    """Insert one bounded synthetic history with deliberately equal timestamps."""
    item_id = UUID(int=ident)
    versions = list(range(1 if creation else 2, count + (1 if creation else 2)))
    through = versions[-1] if versions else 1
    with psycopg.connect(database) as conn:
        conn.execute(
            "INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority,version) "
            "VALUES (%s,%s,%s,%s,%s,'normal',%s)",
            (item_id, organization, f"HISTORY-{label}", f"Synthetic history {label}",
             "Disposable bounded history fixture.", through),
        )
        for version in versions:
            conn.execute(
                "INSERT INTO exception_events(organization_id,exception_id,actor_id,action,note,version,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,'2026-01-01T00:00:00Z')",
                (organization, item_id, actor, "created" if version == 1 else "assigned",
                 None if version == 1 else f"Synthetic {label} event {version}", version),
            )
    return {"id": str(item_id), "versions": versions, "through": through, "label": label}


@pytest.fixture()
def histories(database, identities):
    north = identities["alex@northline.example"]
    harbor = identities["jules@harbor.example"]
    return {
        "north": fixture_history(database, north["organization_id"], north["id"], 40001, 65, "NORTH-A"),
        "other_north": fixture_history(database, north["organization_id"], north["id"], 40002, 7, "NORTH-B"),
        "harbor": fixture_history(database, harbor["organization_id"], harbor["id"], 40003, 65, "HARBOR"),
        "north_org": north["organization_id"],
        "harbor_org": harbor["organization_id"],
    }


def business_rows(database):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return {
            "exceptions": conn.execute("SELECT * FROM shipment_exceptions ORDER BY id").fetchall(),
            "events": conn.execute("SELECT * FROM exception_events ORDER BY id").fetchall(),
            "receipts": conn.execute(
                "SELECT * FROM mutation_requests ORDER BY organization_id,actor_id,key"
            ).fetchall(),
        }


def read_page(client, item, params=None, headers=None):
    response = client.get(f"/api/exceptions/{item['id']}/history", params=params or {}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"events", "next_cursor", "page_size", "through_version"}
    assert isinstance(payload["events"], list)
    assert type(payload["page_size"]) is int and 1 <= payload["page_size"] <= 50
    assert type(payload["through_version"]) is int and payload["through_version"] >= 1
    assert len(payload["events"]) <= payload["page_size"]
    versions = [event["version"] for event in payload["events"]]
    assert versions == sorted(versions) and len(versions) == len(set(versions))
    assert all(version <= payload["through_version"] for version in versions)
    assert payload["next_cursor"] is None or isinstance(payload["next_cursor"], str)
    if payload["next_cursor"] is not None:
        assert len(payload["events"]) == payload["page_size"]
        assert 0 < len(payload["next_cursor"]) <= 1024
        assert "=" not in payload["next_cursor"]
    return payload


def walk_history(client, item, limit=20, first=None):
    pages = [first] if first is not None else [read_page(client, item, {"limit": limit})]
    cursors = set()
    for _ in range(100):
        cursor = pages[-1]["next_cursor"]
        if cursor is None:
            return pages
        assert cursor not in cursors, "Older-history continuation must make progress"
        cursors.add(cursor)
        pages.append(read_page(client, item, {"limit": limit, "cursor": cursor}))
    pytest.fail("The finite history fixture did not terminate within its row bound")


def assert_invalid(response):
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_history_query"
    assert isinstance(error["message"], str) and error["message"]
    return response.json()


def test_detail_and_default_history_show_only_latest_twenty_in_ascending_page_order(
    northline, histories, database
):
    client, _ = northline
    item = histories["north"]
    before = business_rows(database)
    detail = client.get(f"/api/exceptions/{item['id']}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["exception"]["version"] == 65
    assert [event["version"] for event in payload["events"]] == list(range(46, 66))
    assert set(payload["history"]) == {"next_cursor", "page_size", "through_version"}
    assert payload["history"]["page_size"] == 20
    assert payload["history"]["through_version"] == 65
    first = read_page(client, item)
    assert payload["events"] == first["events"]
    assert payload["history"] == {key: first[key] for key in ("next_cursor", "page_size", "through_version")}
    position = decode_cursor(first["next_cursor"])
    assert position == {
        "v": 1, "organization_id": str(histories["north_org"]), "exception_id": item["id"],
        "limit": 20, "through_version": 65, "before_version": 46,
    }
    assert business_rows(database) == before


@pytest.mark.parametrize("limit", [1, 7, 20, 50])
def test_complete_static_traversal_has_no_duplicate_or_missing_versions(
    northline, histories, limit
):
    client, _ = northline
    item = histories["north"]
    pages = walk_history(client, item, limit)
    versions = [event["version"] for page in reversed(pages) for event in page["events"]]
    assert versions == item["versions"]
    assert len(set(versions)) == len(versions) == 65
    assert all(page["through_version"] == 65 and page["page_size"] == limit for page in pages)
    assert all("NORTH-A" in event["note"] for page in pages for event in page["events"] if event["version"] > 1)
    # Every fixture timestamp is equal. Version, rather than timestamp or event
    # insertion identity, must keep the result complete and uniquely ordered.
    assert len({event["created_at"] for page in pages for event in page["events"]}) == 1


@pytest.mark.parametrize("count,expected_lengths", [
    (0, [0]), (1, [1]), (20, [20]), (21, [20, 1]), (40, [20, 20]), (41, [20, 20, 1]),
])
def test_empty_short_full_and_exact_multiple_boundaries(
    northline, database, identities, count, expected_lengths
):
    client, _ = northline
    actor = identities["alex@northline.example"]
    item = fixture_history(database, actor["organization_id"], actor["id"], 41001, count, "BOUNDARY")
    pages = walk_history(client, item)
    assert [len(page["events"]) for page in pages] == expected_lengths
    assert [event["version"] for page in reversed(pages) for event in page["events"]] == item["versions"]
    assert pages[-1]["next_cursor"] is None


def test_legacy_gap_and_seeded_empty_history_do_not_fabricate_creation_events(
    northline, database, identities
):
    client, _ = northline
    empty = read_page(client, {"id": str(UUID(int=101))})
    assert empty == {"events": [], "next_cursor": None, "page_size": 20, "through_version": 1}
    actor = identities["alex@northline.example"]
    item = fixture_history(database, actor["organization_id"], actor["id"], 41002, 24, "LEGACY", creation=False)
    pages = walk_history(client, item)
    versions = [event["version"] for page in reversed(pages) for event in page["events"]]
    assert versions == list(range(2, 26))
    assert all(event["action"] == "assigned" for page in pages for event in page["events"])


def test_new_mutation_does_not_shift_existing_fenced_history_and_refresh_sees_it(
    northline, histories, database
):
    client, headers = northline
    item = histories["north"]
    first = read_page(client, item)
    changed = client.post(f"/api/exceptions/{item['id']}/assign", json={
        "expected_version": 65, "assignee_id": str(UUID(int=12)),
    }, headers={**headers, "Idempotency-Key": str(uuid4())})
    assert changed.status_code == 200, changed.text
    assert changed.json()["exception"]["version"] == 66
    after_mutation = business_rows(database)
    pages = walk_history(client, item, first=first)
    assert [event["version"] for page in reversed(pages) for event in page["events"]] == list(range(1, 66))
    assert all(page["through_version"] == 65 for page in pages)
    refreshed = read_page(client, item)
    assert refreshed["through_version"] == 66
    assert [event["version"] for event in refreshed["events"]] == list(range(47, 67))
    detail = client.get(f"/api/exceptions/{item['id']}").json()
    assert detail["exception"]["version"] == detail["history"]["through_version"] == 66
    assert detail["events"] == refreshed["events"]
    assert business_rows(database) == after_mutation


def test_detail_fence_excludes_an_append_committed_after_its_record_read(
    northline, histories, database, identities, monkeypatch
):
    client, _ = northline
    item = histories["north"]
    original = app_module.exception_record
    appended = False

    def append_after_read(conn, organization_id, exception_id):
        nonlocal appended
        record = original(conn, organization_id, exception_id)
        if record and str(exception_id) == item["id"] and not appended:
            appended = True
            # This separate committed SQL fixture is inserted at the precise
            # record-read/history-read boundary. No timer or thread establishes
            # the ordering, and the original record result remains version 65.
            with psycopg.connect(database) as writer:
                changed = writer.execute(
                    "UPDATE shipment_exceptions SET version=version+1 WHERE id=%s AND version=65 RETURNING version",
                    (UUID(item["id"]),),
                ).fetchone()
                assert changed == (66,)
                writer.execute(
                    "INSERT INTO exception_events(organization_id,exception_id,actor_id,action,note,version) "
                    "VALUES (%s,%s,%s,'assigned','Synthetic append between detail reads',66)",
                    (organization_id, UUID(item["id"]), identities["alex@northline.example"]["id"]),
                )
        return record

    monkeypatch.setattr(app_module, "exception_record", append_after_read)
    response = client.get(f"/api/exceptions/{item['id']}")
    assert response.status_code == 200, response.text
    result = response.json()
    assert appended
    assert result["exception"]["version"] == result["history"]["through_version"] == 65
    assert [event["version"] for event in result["events"]] == list(range(46, 66))
    after_append = business_rows(database)
    refreshed = client.get(f"/api/exceptions/{item['id']}").json()
    assert refreshed["exception"]["version"] == refreshed["history"]["through_version"] == 66
    assert [event["version"] for event in refreshed["events"]] == list(range(47, 67))
    assert business_rows(database) == after_append


def test_authentication_and_record_scope_precede_cursor_validation(app, histories):
    own, foreign = histories["north"], histories["harbor"]
    with TestClient(app, raise_server_exceptions=False) as anonymous:
        assert anonymous.get(f"/api/exceptions/{own['id']}/history", params={"cursor": "bad"}).status_code == 401
    with authenticated_client(app) as (client, headers):
        foreign_response = client.get(f"/api/exceptions/{foreign['id']}/history", params={"cursor": "bad"})
        absent_response = client.get(f"/api/exceptions/{uuid4()}/history", params={"limit": "100000", "cursor": "bad"})
        assert foreign_response.status_code == absent_response.status_code == 404
        assert foreign_response.json() == absent_response.json()
        assert client.post("/api/logout", headers=headers).status_code == 204
        assert client.get(f"/api/exceptions/{own['id']}/history").status_code == 401


@pytest.mark.parametrize("email,own_name,foreign_name", [
    ("casey@northline.example", "north", "harbor"),
    ("taylor@harbor.example", "harbor", "north"),
])
def test_both_reviewers_can_page_only_their_organization_without_business_changes(
    app, database, histories, email, own_name, foreign_name
):
    with authenticated_client(app, email) as (client, _):
        before = business_rows(database)
        pages = walk_history(client, histories[own_name], limit=7)
        assert [event["version"] for page in reversed(pages) for event in page["events"]] == list(range(1, 66))
        assert client.get(f"/api/exceptions/{histories[foreign_name]['id']}/history").status_code == 404
        assert business_rows(database) == before


def test_current_database_identity_and_role_control_history_reads(app, database, histories, identities):
    with authenticated_client(app) as (operator, headers):
        actor = identities["alex@northline.example"]
        with psycopg.connect(database) as conn:
            conn.execute("UPDATE users SET role='reviewer' WHERE id=%s", (actor["id"],))
        before = business_rows(database)
        assert len(read_page(operator, histories["north"])["events"]) == 20
        denied = operator.post(f"/api/exceptions/{histories['north']['id']}/assign", json={
            "expected_version": 65, "assignee_id": None,
        }, headers={**headers, "Idempotency-Key": str(uuid4())})
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "read_only"
        assert business_rows(database) == before
    with authenticated_client(app, "casey@northline.example") as (reader, _):
        saved_cursor = read_page(reader, histories["north"])["next_cursor"]
        # This unassigned synthetic reviewer has no business FK references, so
        # the fixture can move its current organization without rewriting data.
        with psycopg.connect(database) as conn:
            conn.execute("UPDATE users SET organization_id=%s WHERE id=%s",
                         (histories["harbor_org"], identities["casey@northline.example"]["id"]))
        before = business_rows(database)
        assert reader.get(f"/api/exceptions/{histories['north']['id']}/history", params={"cursor": saved_cursor}).status_code == 404
        assert len(read_page(reader, histories["harbor"])["events"]) == 20
        assert business_rows(database) == before


def test_cursor_context_never_supplies_authority_or_cross_record_history(
    northline, harbor, histories, database
):
    client, _ = northline
    other, _ = harbor
    before = business_rows(database)
    first = read_page(client, histories["north"])
    foreign = read_page(other, histories["harbor"])
    for item, token, size in [
        (histories["other_north"], first["next_cursor"], 20),
        (histories["north"], foreign["next_cursor"], 20),
        (histories["north"], first["next_cursor"], 7),
    ]:
        assert_invalid(client.get(f"/api/exceptions/{item['id']}/history", params={"limit": size, "cursor": token}))
    # An unsigned own-context position may skip own rows; it still cannot make
    # the organization predicate select the foreign cursor's actual records.
    forged = decode_cursor(foreign["next_cursor"])
    forged.update(organization_id=str(histories["north_org"]), exception_id=histories["north"]["id"])
    page = read_page(client, histories["north"], {"cursor": encode_cursor(forged)}, headers={
        "X-Organization-ID": str(histories["harbor_org"]), "X-User-ID": str(UUID(int=21)), "X-Role": "operator",
    })
    assert [event["version"] for event in page["events"]] == list(range(26, 46))
    assert all("NORTH-A" in event["note"] for event in page["events"])
    assert business_rows(database) == before


def test_invalid_or_ambiguous_queries_are_generic_and_do_not_mutate_business_rows(
    northline, histories, database
):
    client, _ = northline
    item = histories["north"]
    before = business_rows(database)
    failures = []
    for params in [
        {"limit": "0"}, {"limit": "51"}, {"limit": "-1"}, {"limit": "1.5"},
        {"limit": "1e1"}, {"limit": "01"}, {"limit": "+1"}, {"limit": " 1"},
        {"limit": "1 "}, {"limit": ""}, {"limit": "true"}, {"limit": "2147483648"},
        {"limit": "1' OR 1=1 --"}, {"organization_id": str(histories["harbor_org"])},
        {"before_version": "2"}, {"through_version": "65"}, {"unexpected": "private-value"},
        [("limit", "2"), ("limit", "2")], [("cursor", "a"), ("cursor", "b")],
    ]:
        failures.append(assert_invalid(client.get(f"/api/exceptions/{item['id']}/history", params=params)))
    assert all(failure == failures[0] for failure in failures)
    assert "private-value" not in json.dumps(failures)
    assert business_rows(database) == before


def test_cursor_envelope_is_strict_bounded_canonical_and_non_echoing(northline, histories):
    client, _ = northline
    item = histories["north"]
    for token in ["", "*", "a", "a=", "x" * 1025,
                  token_bytes(b"not json"), token_bytes(b"\xff"), token_bytes(b"[]"),
                  token_bytes(b"null"), token_bytes(b"[" * 300 + b"0" + b"]" * 300)]:
        assert_invalid(client.get(f"/api/exceptions/{item['id']}/history", params={"cursor": token}))
    first = read_page(client, item)
    payload = decode_cursor(first["next_cursor"])
    for name in payload:
        missing = deepcopy(payload)
        missing.pop(name)
        assert_invalid(client.get(f"/api/exceptions/{item['id']}/history", params={"cursor": encode_cursor(missing)}))
    pairs = list(payload.items()) + [("v", 1)]
    raw = "{" + ",".join(json.dumps(key) + ":" + json.dumps(value) for key, value in pairs) + "}"
    assert_invalid(client.get(f"/api/exceptions/{item['id']}/history", params={"cursor": token_bytes(raw.encode())}))
    assert_invalid(client.get(f"/api/exceptions/{item['id']}/history", params={"cursor": first["next_cursor"] + "="}))
    # A different final base64url character can decode to identical bytes while
    # carrying nonzero unused bits. It must not become a second accepted token.
    raw = json.dumps(payload, separators=(",", ":")).encode()
    while len(raw) % 3 != 2:
        raw += b" "
    canonical = token_bytes(raw)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final_index = alphabet.index(canonical[-1])
    assert final_index % 4 == 0
    alias = canonical[:-1] + alphabet[final_index + 1]
    assert urlsafe_b64decode(alias + "=") == raw
    assert_invalid(client.get(f"/api/exceptions/{item['id']}/history", params={"cursor": alias}))


def test_cursor_field_types_bounds_and_relationships_are_validated(northline, histories, database):
    client, _ = northline
    item = histories["north"]
    payload = decode_cursor(read_page(client, item)["next_cursor"])
    before = business_rows(database)
    changes = [
        {"v": 0}, {"v": 2}, {"v": True}, {"v": "1"}, {"v": 1.0},
        {"organization_id": "not-a-uuid"}, {"organization_id": 1},
        {"exception_id": "not-a-uuid"}, {"exception_id": None},
        {"limit": 0}, {"limit": 51}, {"limit": True}, {"limit": "20"}, {"limit": 20.0},
        {"through_version": 0}, {"through_version": -1}, {"through_version": True},
        {"through_version": "65"}, {"through_version": 65.0}, {"through_version": 2147483648},
        {"through_version": 66}, {"before_version": 0}, {"before_version": -1},
        {"before_version": True}, {"before_version": "46"}, {"before_version": 46.0},
        {"before_version": 2147483648}, {"before_version": 66},
        {"organization_id": str(histories["harbor_org"])},
        {"exception_id": histories["other_north"]["id"]}, {"unknown": "sensitive-cursor-value"},
    ]
    errors = []
    for changed in changes:
        errors.append(assert_invalid(client.get(f"/api/exceptions/{item['id']}/history", params={
            "cursor": encode_cursor({**payload, **changed}),
        })))
    assert all(error == errors[0] for error in errors)
    assert "sensitive-cursor-value" not in json.dumps(errors)
    assert business_rows(database) == before


def test_valid_untrusted_positions_can_skip_rows_or_end_without_requiring_an_anchor(
    northline, histories
):
    client, _ = northline
    item = histories["north"]
    position = decode_cursor(read_page(client, item)["next_cursor"])
    position.update(through_version=40, before_version=31)
    page = read_page(client, item, {"cursor": encode_cursor(position)})
    assert page["through_version"] == 40
    assert [event["version"] for event in page["events"]] == list(range(11, 31))
    position.update(before_version=1)
    end = read_page(client, item, {"cursor": encode_cursor(position)})
    assert end == {"events": [], "next_cursor": None, "page_size": 20, "through_version": 40}


def test_maximum_postgresql_integer_position_is_supported(northline, histories, database):
    client, _ = northline
    item = histories["north"]
    position = decode_cursor(read_page(client, item)["next_cursor"])
    with psycopg.connect(database) as conn:
        conn.execute("UPDATE shipment_exceptions SET version=2147483647 WHERE id=%s", (UUID(item["id"]),))
    position.update(through_version=2147483647, before_version=2147483647)
    page = read_page(client, item, {"cursor": encode_cursor(position)})
    assert page["through_version"] == 2147483647
    assert [event["version"] for event in page["events"]] == list(range(46, 66))
    # This deliberately sparse SQL fixture checks an admitted boundary value,
    # not a claim that billions of events were generated or scanned.
