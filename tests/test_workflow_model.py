"""Check the installed application against the sequential reference model.

A Hypothesis state machine sends one call at a time through the real routes to
a real PostgreSQL database and applies the same call to the model in
tests/workflow_model.py. After every call the answer must match the model's
answer, and the rows the application stored must match what the model says
they hold: the exceptions, their audit events and the retry receipts.

The calls cover creation, assignment, resolution, a retry on the same key, a
stale or wrong version, a reviewer write, a key reused for a different body,
and a replay after logout. Only the one-call-at-a-time case lives here.
Concurrent clients are a separate check.

Hypothesis runs with a fixed derandomized search, so the examples are the same
on every run and a failure replays from the printed steps. Three of the tests
here make one rule of the model wrong on purpose and require the check to
fail, which shows that the check depends on the rules it names.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from hypothesis import HealthCheck, Phase, settings, strategies as st
from hypothesis.stateful import (Bundle, RuleBasedStateMachine, invariant, rule,
                                 run_state_machine_as_test)
import psycopg
from psycopg.rows import dict_row
import pytest

from conftest import ORIGIN, authenticated_client, reset_database
from shipment_workspace.app import create_app
from shipment_workspace.config import Settings
from workflow_model import ACTORS, OPERATORS, REVIEWER, VIEW_FIELDS, Model, Reply, Request

NORTHLINE = UUID(int=1)
USERS = {"alex": UUID(int=11), "sam": UUID(int=12), "casey": UUID(int=13)}
EMAILS = {"alex": "alex@northline.example", "sam": "sam@northline.example",
          "casey": "casey@northline.example"}
OTHER_ORGANIZATION_USER = str(UUID(int=21))
UNKNOWN_USER = str(UUID(int=999))
MISSING = "NO-SUCH-REFERENCE"
MISSING_ID = UUID(int=998)
NEW_REFERENCES = ("MODEL-1", "MODEL-2", "MODEL-3")

ASSIGNEES = st.sampled_from([None, *(str(USERS[name]) for name in ACTORS),
                             OTHER_ORGANIZATION_USER, UNKNOWN_USER])
TEXTS = st.sampled_from(["first text", "second text", "third text"])
PRIORITIES = st.sampled_from(["normal", "high"])


def as_view(item):
    return tuple(str(item[name]) if name == "assignee_id" and item[name] else item[name]
                 for name in VIEW_FIELDS)


class WorkflowMachine(RuleBasedStateMachine):
    """The application and the model, driven by the same calls."""

    model_class = Model
    requests = Bundle("requests")

    def __init__(self, database_url):
        super().__init__()
        self.database_url = database_url
        self.stack = ExitStack()
        reset_database(database_url)
        app = create_app(Settings(database_url=database_url, origin=ORIGIN, secure_cookie=False))
        self.app = app
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            seeded = conn.execute(
                "SELECT id, reference, summary, details, status, priority, assignee_id, resolution, version "
                "FROM shipment_exceptions WHERE organization_id=%s", (NORTHLINE,)).fetchall()
        self.ids = {row["reference"]: row["id"] for row in seeded}
        rows = [{**row, "assignee_id": row["assignee_id"] and str(row["assignee_id"])} for row in seeded]
        self.model = self.model_class({name: str(user) for name, user in USERS.items()}, rows)
        self.sessions = {}
        for name in ACTORS:
            self.login(name)

    def teardown(self):
        self.stack.close()

    def login(self, name):
        self.sessions[name] = self.stack.enter_context(authenticated_client(self.app, EMAILS[name]))

    # Sending a request and comparing the answer.

    def send(self, request: Request, session=None):
        client, headers = session or self.sessions[request.actor]
        headers = {**headers, "Idempotency-Key": request.key}
        if request.kind == "create":
            response = client.post("/api/exceptions", headers=headers, json={
                "reference": request.reference, "summary": request.summary,
                "details": request.details, "priority": request.priority})
        else:
            target = self.ids.get(request.target, MISSING_ID)
            if request.kind == "assign":
                body = {"expected_version": request.expected_version, "assignee_id": request.assignee_id}
            else:
                body = {"expected_version": request.expected_version, "resolution": request.resolution}
            response = client.post(f"/api/exceptions/{target}/{request.kind}", headers=headers, json=body)
        return response

    def check_answer(self, request, response, expected: Reply):
        where = f"{request}"
        assert response.status_code == expected.status, f"{where}: {response.status_code} {response.text}"
        body = response.json()
        if expected.code:
            assert body["error"]["code"] == expected.code, where
            assert body["error"].get("current_version") == expected.current_version, where
        else:
            exception = body["exception"]
            assert as_view(exception) == expected.view, where
            if request.kind == "create":
                self.ids.setdefault(request.reference, UUID(exception["id"]))
        header = response.headers.get("Idempotency-Replayed")
        promised = None if expected.replayed is None else str(expected.replayed).lower()
        assert header == promised, f"{where}: replay header {header!r}, expected {promised!r}"

    def submit(self, request: Request):
        expected = self.model.apply(request)
        self.check_answer(request, self.send(request), expected)
        return request

    # Drawing the next request from what the model currently holds.

    def draw(self, data, actor=None):
        actor = actor or data.draw(st.sampled_from(OPERATORS))
        key = str(uuid4())
        kind = data.draw(st.sampled_from(["create", "assign", "resolve"]))
        if kind == "create":
            return Request("create", actor, key,
                           reference=data.draw(st.sampled_from([*NEW_REFERENCES, *self.model.references()])),
                           summary=data.draw(TEXTS), details=data.draw(TEXTS),
                           priority=data.draw(PRIORITIES))
        target = data.draw(st.sampled_from([*self.model.references(), MISSING]))
        current = self.model.version_of(target) if target != MISSING else 1
        version = max(1, current + data.draw(st.sampled_from([0, 0, 0, -1, 1])))
        if kind == "assign":
            return Request("assign", actor, key, target=target, expected_version=version,
                           assignee_id=data.draw(ASSIGNEES))
        return Request("resolve", actor, key, target=target, expected_version=version,
                       resolution=data.draw(TEXTS))

    # The rules.

    @rule(target=requests, data=st.data())
    def new_write(self, data):
        return self.submit(self.draw(data))

    @rule(target=requests, data=st.data())
    def reviewer_write(self, data):
        return self.submit(self.draw(data, actor=REVIEWER))

    @rule(request=requests)
    def retry_same_key(self, request):
        self.submit(request)

    @rule(target=requests, request=requests, data=st.data())
    def reuse_key_for_another_body(self, request, data):
        other = self.draw(data, actor=request.actor)
        return self.submit(other.with_identity(request.actor, request.key))

    @rule(request=requests)
    def replay_after_logout(self, request):
        name = request.actor
        client, headers = self.sessions[name]
        assert client.post("/api/logout", headers=headers).status_code == 204
        refused = self.send(request, session=(client, headers))
        assert refused.status_code == 401, refused.text
        assert refused.json()["error"]["code"] == "not_authenticated"
        self.login(name)
        self.submit(request)

    # What the database holds after every call.

    @invariant()
    def stored_state_matches_the_model(self):
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            exceptions = conn.execute(
                "SELECT reference, summary, details, status, priority, assignee_id, resolution, version "
                "FROM shipment_exceptions WHERE organization_id=%s", (NORTHLINE,)).fetchall()
            events = conn.execute(
                "SELECT e.reference, v.action, v.version, v.actor_id, v.assignee_id, v.note "
                "FROM exception_events v JOIN shipment_exceptions e ON e.id=v.exception_id "
                "WHERE v.organization_id=%s ORDER BY e.reference, v.version", (NORTHLINE,)).fetchall()
            receipts = conn.execute(
                "SELECT actor_id, key, status_code FROM mutation_requests "
                "WHERE organization_id=%s", (NORTHLINE,)).fetchall()
        names = {str(user): name for name, user in USERS.items()}
        assert {row["reference"]: as_view(row) for row in exceptions} == self.model.stored_exceptions()
        stored_events = {reference: [] for reference in self.model.stored_events()}
        for row in events:
            stored_events[row["reference"]].append((
                row["action"], row["version"], str(row["actor_id"]),
                row["assignee_id"] and str(row["assignee_id"]), row["note"]))
        assert stored_events == self.model.stored_events()
        assert sorted((names[str(row["actor_id"])], str(row["key"]), row["status_code"])
                      for row in receipts) == self.model.stored_receipts()


SEARCH = settings(max_examples=40, stateful_step_count=12, derandomize=True, deadline=None,
                  database=None, suppress_health_check=list(HealthCheck))


def run(database_url, model_class, search=SEARCH):
    class Machine(WorkflowMachine):
        pass

    Machine.model_class = model_class
    run_state_machine_as_test(lambda: Machine(database_url), settings=search)


def test_the_application_agrees_with_the_model(database_url):
    run(database_url, Model)


# One rule of the model made wrong at a time. Each run must fail, which shows
# the check notices that rule. The search stops at the first failure and does
# not shrink it, so a wrong rule costs only the calls up to its first miss.

class IgnoresTheVersion(Model):
    def _edit(self, request):
        item = self.items.get(request.target)
        if item is not None:
            request = replace(request, expected_version=item["version"])
        return super()._edit(request)


class RerunsAReplay(Model):
    def apply(self, request):
        reply = super().apply(request)
        if reply.replayed and request.kind != "create" and reply.status == 200:
            self.items[request.target]["version"] += 1
        return reply


class LetsReviewersWrite(Model):
    def apply(self, request):
        return super().apply(replace(request, actor="alex")) if request.actor == REVIEWER else super().apply(request)


QUICK = settings(SEARCH, phases=[Phase.generate], max_examples=60)


@pytest.mark.parametrize("wrong_model", [IgnoresTheVersion, RerunsAReplay, LetsReviewersWrite],
                         ids=lambda cls: cls.__name__)
def test_the_check_fails_when_a_model_rule_is_wrong(database_url, wrong_model):
    with pytest.raises(AssertionError):
        run(database_url, wrong_model, QUICK)


# The model alone, with no database, so its rules read as plain statements.

def fresh_model():
    row = {"reference": "R-1", "summary": "s", "details": "d", "status": "open",
           "priority": "normal", "assignee_id": None, "resolution": None, "version": 1}
    return Model({name: str(user) for name, user in USERS.items()}, [row])


def assign(key, version=1, assignee=None, actor="alex"):
    return Request("assign", actor, key, target="R-1", expected_version=version, assignee_id=assignee)


def test_model_replays_the_saved_answer_and_changes_nothing():
    model = fresh_model()
    first = model.apply(assign("k1", assignee=str(USERS["sam"])))
    again = model.apply(assign("k1", assignee=str(USERS["sam"])))
    assert (first.status, first.replayed, again.status, again.replayed) == (200, False, 200, True)
    assert again.view == first.view and model.version_of("R-1") == 2
    assert len(model.stored_events()["R-1"]) == 1


def test_model_refuses_a_reused_key_with_another_body_and_keeps_the_receipt():
    model = fresh_model()
    model.apply(assign("k1"))
    assert model.apply(assign("k1", assignee=str(USERS["sam"]))).code == "idempotency_conflict"
    assert model.apply(assign("k1")).replayed is True and model.version_of("R-1") == 2


def test_model_saves_refusals_but_not_reviewer_refusals():
    model = fresh_model()
    assert model.apply(assign("k1", version=5)).code == "version_conflict"
    assert model.apply(assign("k2", actor="casey")).code == "read_only"
    assert model.stored_receipts() == [("alex", "k1", 409)]
    assert model.apply(assign("k1", version=5)).replayed is True


def test_model_checks_version_then_resolved_then_assignee():
    model = fresh_model()
    resolve = Request("resolve", "alex", "k1", target="R-1", expected_version=1, resolution="done")
    assert model.apply(resolve).status == 200
    assert model.apply(assign("k2", version=1)).code == "version_conflict"
    assert model.apply(assign("k3", version=2, assignee=OTHER_ORGANIZATION_USER)).code == "already_resolved"
    other = fresh_model()
    assert other.apply(assign("k4", assignee=OTHER_ORGANIZATION_USER)).code == "invalid_assignee"
