"""Bounded live queue queries against the disposable PostgreSQL database."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from copy import deepcopy
import json
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest


def insert_item(database, organization_id, ident, reference, summary="Synthetic queue review",
                details="Synthetic queue fixture.", status="open"):
    item_id = UUID(int=ident)
    with psycopg.connect(database) as conn:
        conn.execute(
            "INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority,status,resolution) "
            "VALUES (%s,%s,%s,%s,%s,'normal',%s,%s)",
            (item_id, organization_id, reference, summary, details, status,
             "Synthetic resolved fixture." if status == "resolved" else None),
        )
    return str(item_id)


def organization_rows(database, organization_id):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT id,reference,summary,details,status FROM shipment_exceptions WHERE organization_id=%s",
            (organization_id,),
        ).fetchall()
    return [{**row, "id": str(row["id"])} for row in rows]


def order_key(item):
    # Expected C order is independent of the operation's SQL or cursor helper.
    return item["reference"].encode("utf-8"), UUID(item["id"]).int


@pytest.fixture()
def queue_records(database, identities):
    north = identities["alex@northline.example"]["organization_id"]
    harbor = identities["jules@harbor.example"]["organization_id"]
    with psycopg.connect(database) as conn:
        for index in range(70):
            status = "resolved" if index % 3 == 0 else "open"
            conn.execute(
                "INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority,status,resolution) "
                "VALUES (%s,%s,%s,%s,%s,'normal',%s,%s)",
                (UUID(int=10000 + index), north, f"NL-Q-{index:03}",
                 f"Synthetic queue review {index:03}", "Synthetic queue fixture.", status,
                 "Synthetic resolved fixture." if status == "resolved" else None),
            )
        for index in range(9):
            # Overlapping references deliberately prevent prefix assumptions
            # from standing in for organization-scoped authorization.
            conn.execute(
                "INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority) "
                "VALUES (%s,%s,%s,%s,%s,'normal')",
                (UUID(int=20000 + index), harbor, f"NL-Q-{index:03}",
                 f"Other organization queue review {index:03}", "Synthetic other-organization fixture."),
            )
    return {"north": north, "harbor": harbor}


def read_page(client, params=None, headers=None):
    response = client.get("/api/exceptions", params=params or {}, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) == {"items", "next_cursor", "page_size"}
    assert isinstance(result["items"], list)
    assert isinstance(result["page_size"], int) and 1 <= result["page_size"] <= 50
    assert len(result["items"]) <= result["page_size"]
    assert result["next_cursor"] is None or isinstance(result["next_cursor"], str)
    if result["next_cursor"] is not None:
        assert len(result["items"]) == result["page_size"]
        assert 0 < len(result["next_cursor"]) <= 2048
        assert "=" not in result["next_cursor"]
    return result


def walk_queue(client, params=None):
    params = dict(params or {})
    items, pages, seen_cursors = [], [], set()
    for _ in range(100):
        page = read_page(client, params)
        pages.append(page)
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items, pages
        assert cursor not in seen_cursors, "Continuation must make progress"
        seen_cursors.add(cursor)
        params["cursor"] = cursor
    pytest.fail("Static fixture traversal did not terminate within its finite row bound")


def decode_cursor(token):
    return json.loads(urlsafe_b64decode(token + "=" * (-len(token) % 4)))


def token_bytes(raw):
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def encode_cursor(payload):
    # ASCII JSON escapes also allow deliberate malformed Unicode payloads.
    return token_bytes(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def assert_invalid(response):
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_queue_query"
    assert isinstance(response.json()["error"]["message"], str)


def test_default_and_maximum_pages_bound_results_and_continue_from_last_returned_row(
    northline, queue_records, database
):
    client, _ = northline
    expected = sorted(organization_rows(database, queue_records["north"]), key=order_key)
    first = read_page(client)
    assert first["page_size"] == 20 and len(first["items"]) == 20
    assert [item["id"] for item in first["items"]] == [item["id"] for item in expected[:20]]
    position = decode_cursor(first["next_cursor"])
    assert position["reference"] == first["items"][-1]["reference"]
    assert position["id"] == first["items"][-1]["id"]
    second = read_page(client, {"cursor": first["next_cursor"]})
    assert second["items"][0]["id"] == expected[20]["id"]

    maximum = read_page(client, {"limit": 50})
    assert maximum["page_size"] == 50 and len(maximum["items"]) == 50
    rest = read_page(client, {"limit": 50, "cursor": maximum["next_cursor"]})
    assert len(rest["items"]) == len(expected) - 50
    assert rest["next_cursor"] is None
    assert [item["id"] for item in maximum["items"] + rest["items"]] == [item["id"] for item in expected]


@pytest.mark.parametrize("status", ["all", "open", "resolved"])
def test_unchanged_queue_traversal_is_complete_ordered_and_organization_scoped(
    northline, queue_records, database, status
):
    client, _ = northline
    expected = organization_rows(database, queue_records["north"])
    if status != "all":
        expected = [item for item in expected if item["status"] == status]
    expected.sort(key=order_key)
    items, pages = walk_queue(client, {"status": status, "limit": 7})
    assert [item["id"] for item in items] == [item["id"] for item in expected]
    assert len({item["id"] for item in items}) == len(items)
    assert all(page["page_size"] == 7 for page in pages)
    assert pages[-1]["next_cursor"] is None
    other_ids = {item["id"] for item in organization_rows(database, queue_records["harbor"])}
    assert other_ids.isdisjoint(item["id"] for item in items)


def test_search_and_status_are_applied_together_before_page_selection(
    northline, queue_records, database
):
    client, _ = northline
    expected = [item for item in organization_rows(database, queue_records["north"])
                if item["status"] == "open" and "queue review" in item["summary"].lower()]
    expected.sort(key=order_key)
    items, _ = walk_queue(client, {"q": "  QUEUE review  ", "status": "open", "limit": 4})
    assert [item["id"] for item in items] == [item["id"] for item in expected]
    reference_only = read_page(client, {"q": "nl-q-019"})
    assert [item["reference"] for item in reference_only["items"]] == ["NL-Q-019"]
    empty = read_page(client, {"q": "not present in this synthetic queue", "status": "resolved"})
    assert empty["items"] == [] and empty["next_cursor"] is None


@pytest.mark.parametrize("needle,reference,summary", [
    ("%", "NL-LITERAL-PERCENT%", "A literal percent value"),
    ("_", "NL-LITERAL_UNDERSCORE", "A literal underscore value"),
    ("!", "NL-LITERAL!ESCAPE", "A literal escape character"),
    ("\\", "NL-LITERAL\\BACKSLASH", "A literal backslash value"),
    ("' OR 1=1 --", "NL-LITERAL-SQL", "Literal text ' OR 1=1 -- remains data"),
    ("<script>", "NL-LITERAL-HTML", "Literal <script> text remains data"),
    ("café", "NL-LITERAL-UNICODE", "A café handoff needs review"),
])
def test_search_metacharacters_sql_html_and_unicode_are_literal_data(
    northline, identities, database, needle, reference, summary
):
    client, _ = northline
    org = identities["alex@northline.example"]["organization_id"]
    intended = insert_item(database, org, 30001, reference, summary)
    insert_item(database, org, 30002, "NL-LITERAL-DECOY", "A different ordinary summary")
    page = read_page(client, {"q": needle})
    assert [item["id"] for item in page["items"]] == [intended]
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 4


def test_c_search_folds_ascii_without_claiming_unicode_case_folding(northline, identities, database):
    client, _ = northline
    org = identities["alex@northline.example"]["organization_id"]
    exact = insert_item(database, org, 30001, "NL-ACCENT-LOWER", "café")
    upper = insert_item(database, org, 30002, "NL-ACCENT-UPPER", "CAFÉ")
    page = read_page(client, {"q": "café"})
    assert [item["id"] for item in page["items"]] == [exact]
    assert upper not in {item["id"] for item in page["items"]}


def test_c_order_and_unicode_cursor_roundtrip_follow_utf8_bytes(northline, identities, database):
    client, _ = northline
    org = identities["alex@northline.example"]["organization_id"]
    for index, reference in enumerate(["NL-Z", "NL-a", "NL-é", "NL-Ω", "NL-中", "NL-🙂", "NL-e\u0301"]):
        insert_item(database, org, 30000 + index, reference)
    expected = sorted(organization_rows(database, org), key=order_key)
    items, pages = walk_queue(client, {"limit": 2})
    assert [item["id"] for item in items] == [item["id"] for item in expected]
    assert len(items) == len({item["id"] for item in items})
    assert len(pages) > 1


def test_search_excludes_details_and_whitespace_query_is_empty(northline, identities, database):
    client, _ = northline
    org = identities["alex@northline.example"]["organization_id"]
    insert_item(database, org, 30001, "NL-DETAILS-ONLY", "Ordinary summary", "details-only-needle")
    assert read_page(client, {"q": "details-only-needle"})["items"] == []
    assert read_page(client, {"q": " \t "}) == read_page(client)
    bounded = read_page(client, {"q": "x" * 80})
    assert bounded["items"] == [] and bounded["next_cursor"] is None


@pytest.mark.parametrize("params", [
    {"limit": "0"}, {"limit": "51"}, {"limit": "-1"}, {"limit": "1.5"},
    {"limit": "not-a-number"}, {"limit": ""}, {"status": "closed"}, {"status": "OPEN"},
    {"q": "x" * 81}, {"q": "bad\x00query"}, {"organization_id": str(UUID(int=2))},
    {"unexpected": "value"}, [("q", "same"), ("q", "same")],
    [("status", "all"), ("status", "open")], [("limit", "2"), ("limit", "2")],
])
def test_invalid_or_ambiguous_query_parameters_are_rejected(northline, params):
    client, _ = northline
    assert_invalid(client.get("/api/exceptions", params=params))


@pytest.mark.parametrize("raw", [b"not json", b"\xff", b"[]", b"null", b"[" * 700 + b"0" + b"]" * 700])
def test_cursor_encoding_must_contain_a_valid_flat_object(northline, raw):
    client, _ = northline
    assert_invalid(client.get("/api/exceptions", params={"cursor": token_bytes(raw)}))


@pytest.mark.parametrize("token", ["*", "a", "a=", "x" * 2049])
def test_invalid_base64_or_oversized_cursor_is_rejected(northline, token):
    client, _ = northline
    assert_invalid(client.get("/api/exceptions", params={"cursor": token}))


@pytest.mark.parametrize("changes", [
    {"v": 0}, {"v": 2}, {"v": True}, {"v": "1"},
    {"organization_id": "not-a-uuid"}, {"status": "unknown"},
    {"q": "x" * 81}, {"q": "bad\x00query"}, {"q": "\ud800"},
    {"limit": 0}, {"limit": 51}, {"limit": True}, {"limit": "2"}, {"limit": 2.0},
    {"reference": ""}, {"reference": "x" * 81}, {"reference": "bad\x00reference"},
    {"reference": "\ud800"}, {"id": "not-a-uuid"}, {"unknown": "value"},
])
def test_cursor_fields_are_strict_and_bounded(northline, queue_records, changes):
    client, _ = northline
    first = read_page(client, {"limit": 2})
    payload = decode_cursor(first["next_cursor"])
    payload.update(changes)
    assert_invalid(client.get("/api/exceptions", params={"limit": 2, "cursor": encode_cursor(payload)}))


def test_cursor_rejects_missing_duplicate_and_noncanonical_fields(northline, queue_records):
    client, _ = northline
    first = read_page(client, {"limit": 2})
    payload = decode_cursor(first["next_cursor"])
    missing = deepcopy(payload)
    missing.pop("id")
    assert_invalid(client.get("/api/exceptions", params={"limit": 2, "cursor": encode_cursor(missing)}))

    pairs = list(payload.items()) + [("v", 1)]
    raw = "{" + ",".join(json.dumps(key) + ":" + json.dumps(value) for key, value in pairs) + "}"
    assert_invalid(client.get("/api/exceptions", params={"limit": 2, "cursor": token_bytes(raw.encode())}))
    assert_invalid(client.get("/api/exceptions", params=[("limit", "2"),
        ("cursor", first["next_cursor"]), ("cursor", first["next_cursor"])]))
    assert_invalid(client.get("/api/exceptions", params={"limit": 2, "cursor": first["next_cursor"] + "="}))

    raw = json.dumps(payload, separators=(",", ":")).encode()
    while len(raw) % 3 != 2:
        raw += b" "
    canonical = token_bytes(raw)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final_index = alphabet.index(canonical[-1])
    assert final_index % 4 == 0
    alias = canonical[:-1] + alphabet[final_index + 1]
    assert urlsafe_b64decode(alias + "=") == raw
    assert_invalid(client.get("/api/exceptions", params={"limit": 2, "cursor": alias}))


@pytest.mark.parametrize("changes", [{"status": "all"}, {"q": "other"}, {"limit": 4}])
def test_cursor_cannot_be_reused_with_changed_query_context(northline, queue_records, changes):
    client, _ = northline
    original = {"status": "open", "q": "queue", "limit": 3}
    first = read_page(client, original)
    assert first["next_cursor"]
    assert_invalid(client.get("/api/exceptions", params={
        **original, **changes, "cursor": first["next_cursor"],
    }))
    canonical = read_page(client, {**original, "cursor": first["next_cursor"]})
    normalized = read_page(client, {**original, "q": "  queue \t", "cursor": first["next_cursor"]})
    assert normalized == canonical


def test_foreign_cursor_is_rejected_and_forged_own_position_grants_no_foreign_access(
    northline, harbor, queue_records, database
):
    north, _ = northline
    other, _ = harbor
    foreign = read_page(other, {"limit": 2})
    assert foreign["next_cursor"]
    assert_invalid(north.get("/api/exceptions", params={"limit": 2, "cursor": foreign["next_cursor"]}))
    position = decode_cursor(foreign["next_cursor"])
    position.update({"organization_id": str(queue_records["north"]),
                     "reference": "NL-Q-020x", "id": str(UUID(int=0))})
    page = read_page(north, {"limit": 2, "cursor": encode_cursor(position)})
    expected = sorted(organization_rows(database, queue_records["north"]), key=order_key)
    expected = [item for item in expected if order_key(item) > (b"NL-Q-020x", 0)]
    assert [item["id"] for item in page["items"]] == [item["id"] for item in expected[:2]]
    assert {item["id"] for item in page["items"]}.isdisjoint(
        item["id"] for item in organization_rows(database, queue_records["harbor"]))
    spoofed = read_page(north, {"q": "queue", "limit": 3}, headers={
        "X-Organization-ID": str(queue_records["harbor"]), "X-User-ID": str(UUID(int=21)),
    })
    assert spoofed == read_page(north, {"q": "queue", "limit": 3})


def test_cursor_anchor_can_leave_the_status_filter_without_breaking_continuation(
    northline, queue_records, database
):
    client, headers = northline
    first = read_page(client, {"status": "open", "limit": 3})
    anchor = first["items"][-1]
    response = client.post(f"/api/exceptions/{anchor['id']}/resolve",
        json={"expected_version": anchor["version"], "resolution": "Synthetic resolution between pages."},
        headers={**headers, "Idempotency-Key": str(uuid4())})
    assert response.status_code == 200, response.text
    page = read_page(client, {"status": "open", "limit": 3, "cursor": first["next_cursor"]})
    expected = [item for item in organization_rows(database, queue_records["north"])
                if item["status"] == "open" and order_key(item) > order_key(anchor)]
    expected.sort(key=order_key)
    assert [item["id"] for item in page["items"]] == [item["id"] for item in expected[:3]]
    detail = client.get(f"/api/exceptions/{anchor['id']}")
    assert detail.status_code == 200 and detail.json()["exception"]["status"] == "resolved"


def test_insertions_between_requests_follow_live_positions_and_refresh_starts_again(
    northline, queue_records, database
):
    client, _ = northline
    first = read_page(client, {"limit": 5})
    anchor = first["items"][-1]
    earlier = insert_item(database, queue_records["north"], 30001, "NL-0000")
    later = insert_item(database, queue_records["north"], 30002, anchor["reference"] + "a")
    continuation = read_page(client, {"limit": 5, "cursor": first["next_cursor"]})
    assert earlier not in {item["id"] for item in continuation["items"]}
    assert later in {item["id"] for item in continuation["items"]}
    expected = sorted((item for item in organization_rows(database, queue_records["north"])
                       if order_key(item) > order_key(anchor)), key=order_key)
    assert [item["id"] for item in continuation["items"]] == [item["id"] for item in expected[:5]]
    refreshed = read_page(client, {"limit": 5})
    assert refreshed["items"][0]["id"] == earlier


def test_off_page_detail_is_independent_and_other_organization_detail_stays_hidden(
    northline, queue_records
):
    client, _ = northline
    first = read_page(client)
    off_page_id = str(UUID(int=10069))
    assert off_page_id not in {item["id"] for item in first["items"]}
    detail = client.get(f"/api/exceptions/{off_page_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["exception"]["reference"] == "NL-Q-069"
    assert client.get(f"/api/exceptions/{UUID(int=20000)}").status_code == 404


def test_valid_queue_queries_still_require_authentication(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/exceptions", params={"q": "queue", "status": "open", "limit": 5})
        assert response.status_code == 401, response.text
