"""No HTTP route edits or deletes an audit event, checked route by route.

The threat model in SECURITY.md lists an audit event edited or deleted through
an HTTP route. No route does that today. There is also no guard in the code to
remove, because the events stay as written only since no route sends a
statement that changes them. The database does not seal the rows, which
docs/LIMITATIONS.md states. So this test holds every route to that rule itself.

The walk sends well formed requests to every route the application registers,
as an operator, a reviewer, an operator of the other organization and a caller
with no session. Before and after each request it reads every audit event. A
request passes only when each event that existed before it is still there with
every column unchanged, and when it sent no statement that updates, deletes,
truncates, merges into or upserts the events table. Each request must also get
the status its step expects, and every route must answer at least one request
with success, so a route that only ever refused would not count as walked. The
route a request reached is read from the router, and a registered route that
no request reached is reported, so a new route cannot skip the check.

The other runs stand in for a removed guard. Two plant a route that edits or
deletes an earlier event. One rewrites the shipped write path, the way
tests/test_concurrent_history.py removes its guards, so that assignment and
resolution also delete the first event of their record. In each run the walk
must report the faulty routes and no other.
"""

from contextlib import contextmanager
import inspect
import re
import sys
import types
from uuid import UUID, uuid4

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from conftest import ORIGIN, TEST_PASSWORD
from shipment_workspace import app as installed_app
from shipment_workspace.config import Settings


ITEM = UUID(int=101)
STATIC = ("GET", "/")
PLANTED_PATH = "/api/exceptions/{exception_id}/events/rewrite"
ASSIGN, RESOLVE = ("POST", "/api/exceptions/{exception_id}/assign"), ("POST", "/api/exceptions/{exception_id}/resolve")

# The end of the statement that appends an assignment or resolution event, and
# the same text followed by a delete of the first event of that record.
EVENT_APPEND = '(org, exception_id, actor, action, assignee, note, record["version"] + 1))'
EVENT_APPEND_AND_DELETE = (EVENT_APPEND + "\n                    conn.execute(\"DELETE FROM exception_events WHERE id="
                           "(SELECT min(id) FROM exception_events WHERE exception_id=%s)\", (exception_id,))")

# Each caller walks with its own client, in this order. The operator goes
# first, so the shared record is still open when it assigns and resolves it.
CALLERS = {
    "operator": "alex@northline.example",
    "reviewer": "casey@northline.example",
    "other organization": "jules@harbor.example",
    "no session": None,
}

# A statement that rewrites or removes rows of the events table. A plain
# INSERT only appends, so it is the one write a route may send to that table.
# The table name may be schema qualified and quoted, as psycopg.sql writes it.
EVENTS = r'(?:"?public"?\s*\.\s*)?"?exception_events\b"?'
EVENT_EDIT = re.compile(
    rf"\bupdate\s+(?:only\s+)?{EVENTS}"
    rf"|\bdelete\s+from\s+(?:only\s+)?{EVENTS}"
    rf"|\bmerge\s+into\s+{EVENTS}"
    r'|\btruncate\b[^;]*(?:exception_events\b|\bcascade\b)'
    r'|\b(?:alter|drop)\s+table\b[^;]*exception_events\b'
    rf"|\binsert\s+into\s+{EVENTS}.*\bon\s+conflict\b.*\bdo\s+update\b",
    re.IGNORECASE | re.DOTALL,
)


def audit_events(database):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return {row["id"]: row for row in conn.execute("SELECT * FROM exception_events ORDER BY id")}


def current_version(database, exception_id):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return conn.execute("SELECT version FROM shipment_exceptions WHERE id=%s", (exception_id,)).fetchone()["version"]


def registered_routes(app):
    """Every method and path the application answers, as the router holds them."""
    routes = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes |= {(method, route.path) for method in route.methods}
        elif isinstance(route, Mount) and isinstance(route.app, StaticFiles) and route.path == "":
            routes.add(STATIC)
        else:
            routes.add((type(route).__name__, getattr(route, "path", repr(route))))
    return routes


class RouteRecorder:
    """Wrap the application and read which route the router chose for a request."""

    def __init__(self, app):
        self.app = app
        self.reached = None

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        finally:
            if scope["type"] == "http":
                route = scope.get("route")
                if isinstance(route, APIRoute):
                    self.reached = (scope["method"], route.path)
                elif isinstance(scope.get("endpoint"), StaticFiles):
                    self.reached = STATIC
                else:
                    self.reached = None


class Walk:
    """Send requests and check the audit events around each one."""

    def __init__(self, database, monkeypatch):
        self.database = database
        self.reached = set()
        self.succeeded = set()
        self.violations = []
        self.requests = 0
        self.sent = []
        sent = self.sent

        # Connection.execute sends its statement through Cursor.execute, so
        # watching the cursor sees both, and executemany as well.
        def watch(original):
            def send(cursor, query, *args, **kwargs):
                sent.append(query if isinstance(query, (str, bytes)) else query.as_string(cursor.connection))
                return original(cursor, query, *args, **kwargs)
            return send

        monkeypatch.setattr(psycopg.Cursor, "execute", watch(psycopg.Cursor.execute))
        monkeypatch.setattr(psycopg.Cursor, "executemany", watch(psycopg.Cursor.executemany))

    def send(self, client, recorder, method, url, expect, **kwargs):
        before = audit_events(self.database)
        self.sent.clear()
        recorder.reached = None
        response = client.request(method, url, **kwargs)
        statements = list(self.sent)
        after = audit_events(self.database)
        route = recorder.reached
        assert response.status_code == expect, (method, url, response.status_code, response.text)
        assert route is not None, (method, url)
        self.reached.add(route)
        if response.status_code < 300:
            self.succeeded.add(route)
        self.requests += 1
        for event_id, row in before.items():
            if event_id not in after:
                self.violations.append((route, "removed", event_id))
            elif after[event_id] != row:
                self.violations.append((route, "changed", event_id))
        for text in statements:
            text = text.decode() if isinstance(text, bytes) else text
            if EVENT_EDIT.search(text):
                self.violations.append((route, "edit statement", " ".join(text.split())))
        return response


@contextmanager
def caller(app, walk, email):
    """A client for one caller, signed in through the walk when it has an account."""
    recorder = RouteRecorder(app)
    with TestClient(recorder, raise_server_exceptions=False) as client:
        token = walk.send(client, recorder, "GET", "/api/session", 200).json()["csrf_token"]
        if email:
            token = walk.send(client, recorder, "POST", "/api/login", 200,
                              json={"email": email, "password": TEST_PASSWORD},
                              headers={"Origin": ORIGIN, "X-CSRF-Token": token}).json()["csrf_token"]
        yield client, recorder, token


def write_headers(token, key=None):
    return {"Origin": ORIGIN, "X-CSRF-Token": token, "Content-Type": "application/json",
            "Idempotency-Key": key or str(uuid4())}


def prelude(app, walk):
    """Give every walked request earlier events in both organizations to protect."""
    for email, reference in [("sam@northline.example", "AW-0"), ("robin@harbor.example", "AW-0")]:
        with caller(app, walk, email) as (client, recorder, token):
            body = {"reference": reference, "summary": "Audit walk prelude",
                    "details": "A synthetic record whose history the walk protects.", "priority": "normal"}
            created = walk.send(client, recorder, "POST", "/api/exceptions", 201,
                                json=body, headers=write_headers(token)).json()["exception"]
            path = f"/api/exceptions/{created['id']}"
            walk.send(client, recorder, "POST", f"{path}/assign", 200, headers=write_headers(token),
                      json={"expected_version": 1, "assignee_id": None})
            walk.send(client, recorder, "POST", f"{path}/resolve", 200, headers=write_headers(token),
                      json={"expected_version": 2, "resolution": "Closed before the walk began."})


def walk_caller(app, walk, name, email, extra_steps=()):
    """Send every route one or more well formed requests as this caller."""
    signed_in = email is not None
    reads = 200 if signed_in else 401
    foreign = name == "other organization"
    with caller(app, walk, email) as (client, recorder, token):
        walk.send(client, recorder, "GET", "/api/version", 200)
        walk.send(client, recorder, "GET", "/api/ready", 200)
        walk.send(client, recorder, "GET", "/api/session", 200)
        walk.send(client, recorder, "GET", "/third-party-notices", 200)
        if STATIC in registered_routes(app):
            walk.send(client, recorder, "GET", "/", 200)
        walk.send(client, recorder, "GET", "/api/members", reads)
        page = walk.send(client, recorder, "GET", "/api/exceptions", reads, params={"status": "all", "limit": "2"})
        if signed_in and page.json()["next_cursor"]:
            walk.send(client, recorder, "GET", "/api/exceptions", 200,
                      params={"status": "all", "limit": "2", "cursor": page.json()["next_cursor"]})
        detail = 404 if foreign else reads
        walk.send(client, recorder, "GET", f"/api/exceptions/{ITEM}", detail)
        walk.send(client, recorder, "GET", f"/api/exceptions/{ITEM}/history", detail, params={"limit": "1"})

        # Writes. The operator succeeds, then replays and conflicts. The
        # reviewer is refused, the other organization finds no such record
        # and the caller with no session is asked to sign in.
        creates = {"operator": 201, "reviewer": 403, "other organization": 201}.get(name, 401)
        body = {"reference": "AW-1", "summary": "Audit walk record",
                "details": "A synthetic record created during the route walk.", "priority": "high"}
        key = str(uuid4())
        walk.send(client, recorder, "POST", "/api/exceptions", creates, json=body, headers=write_headers(token, key))
        walk.send(client, recorder, "POST", "/api/exceptions", creates, json=body, headers=write_headers(token, key))
        conflict = 409 if creates == 201 else creates
        walk.send(client, recorder, "POST", "/api/exceptions", conflict, json=body, headers=write_headers(token))

        changes = {"operator": 200, "reviewer": 403, "other organization": 404}.get(name, 401)
        stale = 409 if changes == 200 else changes
        version = current_version(walk.database, ITEM)
        assign = {"expected_version": version, "assignee_id": str(UUID(int=12))}
        key = str(uuid4())
        walk.send(client, recorder, "POST", f"/api/exceptions/{ITEM}/assign", changes, json=assign, headers=write_headers(token, key))
        walk.send(client, recorder, "POST", f"/api/exceptions/{ITEM}/assign", changes, json=assign, headers=write_headers(token, key))
        walk.send(client, recorder, "POST", f"/api/exceptions/{ITEM}/assign", stale, json=assign, headers=write_headers(token))
        resolve = {"expected_version": current_version(walk.database, ITEM), "resolution": "Closed during the route walk."}
        key = str(uuid4())
        walk.send(client, recorder, "POST", f"/api/exceptions/{ITEM}/resolve", changes, json=resolve, headers=write_headers(token, key))
        walk.send(client, recorder, "POST", f"/api/exceptions/{ITEM}/resolve", changes, json=resolve, headers=write_headers(token, key))
        walk.send(client, recorder, "POST", f"/api/exceptions/{ITEM}/resolve", stale, json=resolve, headers=write_headers(token))

        for step in extra_steps:
            step(walk, client, recorder, token)

        # Sign in again, which rotates the session, and then sign out. A caller
        # with no account sends a wrong password and is refused.
        login = {"email": email or "nobody@northline.example", "password": TEST_PASSWORD if signed_in else "Not-the-password-0"}
        signed = walk.send(client, recorder, "POST", "/api/login", 200 if signed_in else 401, json=login,
                           headers={"Origin": ORIGIN, "X-CSRF-Token": token})
        if signed_in:
            token = signed.json()["csrf_token"]
        walk.send(client, recorder, "POST", "/api/logout", 204 if signed_in else 401,
                  headers={"Origin": ORIGIN, "X-CSRF-Token": token, "Content-Type": "application/json"})


def plant(app, database, kind):
    """Add one route that edits or deletes an earlier event, ahead of the static files."""
    statement = {
        "edit": "UPDATE exception_events SET created_at=created_at - interval '1 day' "
                "WHERE id=(SELECT min(id) FROM exception_events)",
        "delete": "DELETE FROM exception_events WHERE id=(SELECT max(id) FROM exception_events)",
    }[kind]

    def rewrite(exception_id: UUID):
        with psycopg.connect(database) as conn:
            conn.execute(statement)
        return {"rewritten": kind}

    app.add_api_route(PLANTED_PATH, rewrite, methods=["POST"])
    app.router.routes.insert(0, app.router.routes.pop())


def call_planted(walk, client, recorder, token):
    walk.send(client, recorder, "POST", PLANTED_PATH.format(exception_id=ITEM), 200,
              headers={"Origin": ORIGIN, "X-CSRF-Token": token})


def rewritten_app(database):
    """The installed application with its write path deleting the first event of each record it changes."""
    source = inspect.getsource(installed_app)
    assert source.count(EVENT_APPEND) == 1, "The event append of the write path must appear exactly once"
    name = f"{installed_app.__name__}_deleting_first_events"
    module = types.ModuleType(name)
    module.__file__, module.__package__ = installed_app.__file__, installed_app.__package__
    sys.modules[name] = module
    exec(compile(source.replace(EVENT_APPEND, EVENT_APPEND_AND_DELETE), installed_app.__file__, "exec"), module.__dict__)
    return module.create_app(Settings(database_url=database, origin=ORIGIN, secure_cookie=False))


def run_walk(app, database, monkeypatch, extra_steps=()):
    walk = Walk(database, monkeypatch)
    prelude(app, walk)
    for name, email in CALLERS.items():
        walk_caller(app, walk, name, email, extra_steps)
    return walk


@pytest.mark.parametrize("fault", [None, "edit-route-planted", "delete-route-planted", "write-path-rewritten"],
                         ids=["routes-shipped", "edit-route-planted", "delete-route-planted", "write-path-rewritten"])
def test_no_route_edits_or_deletes_an_earlier_audit_event(app, database, monkeypatch, fault):
    if fault == "write-path-rewritten":
        app = rewritten_app(database)
    elif fault:
        plant(app, database, fault.split("-")[0])
    walk = run_walk(app, database, monkeypatch, [call_planted] if fault and "planted" in fault else ())

    assert walk.reached == walk.succeeded == registered_routes(app)
    events = audit_events(database)
    found = {(route, kind) for route, kind, _ in walk.violations}
    if fault is None:
        assert walk.violations == []
        # The prelude wrote 3 events in each organization. The operator then
        # created, assigned and resolved, and the other organization created.
        assert len(events) == 6 + 3 + 1
        assert sorted(events) == list(range(1, len(events) + 1))
    elif fault == "write-path-rewritten":
        # The prelude records had earlier events to lose. The shared record had
        # none before the operator, so there the walk sees only the statement.
        assert found == {(ASSIGN, "removed"), (ASSIGN, "edit statement"),
                         (RESOLVE, "removed"), (RESOLVE, "edit statement")}
    else:
        state = "changed" if fault.startswith("edit") else "removed"
        assert found == {(("POST", PLANTED_PATH), state), (("POST", PLANTED_PATH), "edit statement")}
        kinds = sorted(kind for _, kind, _ in walk.violations)
        assert kinds == sorted([state] * len(CALLERS) + ["edit statement"] * len(CALLERS))


@pytest.mark.parametrize("statement, flagged", [
    ("UPDATE exception_events SET note=%s WHERE id=%s", True),
    ('DELETE FROM "public"."exception_events" WHERE id=%s', True),
    ('delete from only "exception_events"', True),
    ("MERGE INTO exception_events e USING x ON true WHEN MATCHED THEN DELETE", True),
    ("TRUNCATE shipment_exceptions CASCADE", True),
    ("TRUNCATE exception_events", True),
    ("ALTER TABLE exception_events DROP CONSTRAINT exception_events_action_version", True),
    ("INSERT INTO exception_events(organization_id,version) VALUES (%s,%s) "
     "ON CONFLICT (exception_id, version) DO UPDATE SET note=EXCLUDED.note", True),
    ("INSERT INTO exception_events(organization_id,exception_id,actor_id,action,version)\n"
     "    VALUES (%s,%s,%s,'created',1)", False),
    ("SELECT e.id FROM exception_events e WHERE e.exception_id=%s", False),
    ("DELETE FROM sessions WHERE token_hash=%s", False),
    ("UPDATE shipment_exceptions SET version=version+1 WHERE id=%s", False),
], ids=["update", "quoted-delete", "delete-only", "merge", "truncate-cascade", "truncate", "alter",
        "upsert", "append", "select", "other-table-delete", "other-table-update"])
def test_the_statement_pattern_flags_only_writes_that_rewrite_or_remove_events(statement, flagged):
    assert bool(EVENT_EDIT.search(statement)) is flagged


def test_a_registered_route_the_walk_never_reaches_is_reported(app, database, monkeypatch):
    plant(app, database, "edit")
    walk = run_walk(app, database, monkeypatch)

    assert registered_routes(app) - walk.reached == {("POST", PLANTED_PATH)}
    assert registered_routes(app) - walk.succeeded == {("POST", PLANTED_PATH)}
    assert walk.violations == []
