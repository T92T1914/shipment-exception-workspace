"""Several clients at once against the installed application, checked as a history.

Four clients share the Northline records: two sessions of Alex, one of Sam and
one of Casey, who may only read. Each history is ten rounds. In a round every
call starts at the same barrier, so the calls of one round really are in flight
together, and the next round starts only after every call of this one is done.
The test records when each call was sent, when its answer came back and what
the answer was, then reads back every exception, its audit events and the
retry receipts. tests/history_check.py then looks for an order of the calls
that respects real time and that the model accepts, with the stored state at
the end.

Every history carries the same faults in rounds its seed chooses:

1. A dropped acknowledgement. The server does the work and the client never
   sees the answer.
2. A dropped request. The call never reaches the server and the client cannot
   tell the difference.
3. A retry on the same key of each call whose answer was lost.
4. A double delivery. One request reaches the server twice at once.
5. A contest. Two or three operators assign the same open exception from the
   same version they all just read, while every transaction pauses after it
   reads the exception. The pause is the seeded stall. It widens the window
   for a race and changes no answer.
6. A stale version. A client sends a version lower than one it already saw.

Rounds without a forced fault draw reads, edits, creations, retries, a key
reused for another body and a few more of the same faults at random. The seed
fixes the fault plan and every random draw. It does not fix how the threads
interleave, and the clients act on the versions their answers show, so each
history is saved with what actually happened and can be checked again with
`python tests/history_check.py <file>`. Between rounds the clients learn which
exceptions exist from a direct read of the table, the list the queue would show
them. That read is not part of the history.

The guard removed runs build the application from the installed module with
exactly one line changed: the version check, the conflict clause on the receipt
insert, or the row lock on the exception read. Each must make the checker
report a violation of the kind predicted below. Without the version check the
stored state goes wrong. Without the other two it stays right, held by the
receipt primary key and the unique audit version, and the checker sees only
the 500 the loser gets, which the test shows. Set SHIPMENT_HISTORY_DIR to keep
the histories, and SHIPMENT_HISTORY_SEEDS to a comma separated list of seeds to
run only those. A seed repeats the plan, not the interleaving, so a failure
replays from its saved history.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, dataclass, replace
import inspect
import json
import os
from pathlib import Path
import random
import sys
from threading import Barrier
import time
import types
from uuid import UUID

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from conftest import ORIGIN, TEST_PASSWORD, authenticated_client
from history_check import Answer, Call, Stored, check, load
import shipment_workspace.app as installed_app
from shipment_workspace.config import Settings
from shipment_workspace.db import seed as seed_records
from test_workflow_model import EMAILS, NORTHLINE, OTHER_ORGANIZATION_USER, USERS, as_view
from workflow_model import VIEW_FIELDS, Request

CLIENTS = {"a1": "alex", "a2": "alex", "s1": "sam", "c1": "casey"}
OPERATOR_CLIENTS = ("a1", "a2", "s1")
NEW_REFERENCES = ("HIST-1", "HIST-2")
ROUNDS = 10
WORKERS = 12
KEPT_SEEDS = tuple(range(1, 17))
REMOVED_SEEDS = (1, 2, 3)
MEMBERS = [None, *(str(USERS[name]) for name in ("alex", "sam", "casey"))]
ASSIGNEES = [*MEMBERS, OTHER_ORGANIZATION_USER]
TEXTS = ("first note", "second note", "third note")
ANY = object()
FORCED = ("drop_ack", "drop_request", "retry_after_drop", "duplicate", "contend", "stale")

# The statement the stall follows. Both the locked read and the read with its
# lock removed start with this text, and no other statement does.
RECORD_READ = "SELECT * FROM shipment_exceptions WHERE organization_id=%s AND id=%s"
STALL = {"seconds": 0.0}
CONTEND_STALL = 0.2

# Each guard is the exact text of one line or clause in the installed module
# and what the removed run puts in its place.
GUARDS = {
    "version-check": ('if record["version"] != body.expected_version:', "if False:"),
    "receipt-conflict": (" ON CONFLICT DO NOTHING RETURNING key", " RETURNING key"),
    "row-lock": ('AND id=%s FOR UPDATE"', 'AND id=%s"'),
}
PREDICTED = {"version-check": "no_order", "receipt-conflict": "unconfirmed_answer",
             "row-lock": "unconfirmed_answer"}


def chosen_seeds(default):
    value = os.environ.get("SHIPMENT_HISTORY_SEEDS")
    return tuple(int(item) for item in value.split(",")) if value else default


@pytest.fixture()
def history_dir(tmp_path_factory):
    value = os.environ.get("SHIPMENT_HISTORY_DIR")
    folder = Path(value) if value else tmp_path_factory.mktemp("histories")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@pytest.fixture()
def stall(monkeypatch):
    """Pause each assignment or resolution for the round's stall right after it reads its exception."""
    original = psycopg.Connection.execute

    def execute(conn, query, *args, **kwargs):
        cursor = original(conn, query, *args, **kwargs)
        if STALL["seconds"] and isinstance(query, str) and query.startswith(RECORD_READ):
            time.sleep(STALL["seconds"])
        return cursor

    monkeypatch.setattr(psycopg.Connection, "execute", execute)
    yield
    STALL["seconds"] = 0.0


def build_app(database_url, guard=None):
    settings = Settings(database_url=database_url, origin=ORIGIN, secure_cookie=False)
    if guard is None:
        return installed_app.create_app(settings)
    source = inspect.getsource(installed_app)
    old, new = GUARDS[guard]
    assert source.count(old) == 1, f"The text of the {guard} guard must appear exactly once"
    name = f"{installed_app.__name__}_without_{guard.replace('-', '_')}"
    module = types.ModuleType(name)
    module.__file__, module.__package__ = installed_app.__file__, installed_app.__package__
    sys.modules[name] = module
    exec(compile(source.replace(old, new), installed_app.__file__, "exec"), module.__dict__)
    return module.create_app(settings)


def reset_workflow(database_url):
    """Put the exceptions back as seeded. Users and sessions stay."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE mutation_requests, exception_events, shipment_exceptions RESTART IDENTITY")
    seed_records(database_url, TEST_PASSWORD)


def northline_records(database_url):
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT id, reference, summary, details, status, priority, assignee_id, resolution, version "
            "FROM shipment_exceptions WHERE organization_id=%s ORDER BY reference", (NORTHLINE,)).fetchall()
    initial = [{**{name: row[name] for name in VIEW_FIELDS},
                "assignee_id": row["assignee_id"] and str(row["assignee_id"])} for row in rows]
    return {row["reference"]: row["id"] for row in rows}, initial


def read_back(database_url, key_owner):
    """Every Northline exception, its events and the receipts, grouped by exception."""
    names = {str(user): name for name, user in USERS.items()}
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        exceptions = conn.execute(
            "SELECT reference, summary, details, status, priority, assignee_id, resolution, version "
            "FROM shipment_exceptions WHERE organization_id=%s", (NORTHLINE,)).fetchall()
        events = conn.execute(
            "SELECT e.reference, v.action, v.version, v.actor_id, v.assignee_id, v.note "
            "FROM exception_events v JOIN shipment_exceptions e ON e.id=v.exception_id "
            "WHERE v.organization_id=%s ORDER BY e.reference, v.version", (NORTHLINE,)).fetchall()
        receipts = conn.execute(
            "SELECT actor_id, key, status_code, response FROM mutation_requests WHERE organization_id=%s",
            (NORTHLINE,)).fetchall()
    stored = {row["reference"]: {"view": as_view(row), "events": [], "receipts": []} for row in exceptions}
    for row in events:
        stored[row["reference"]]["events"].append((
            row["action"], row["version"], str(row["actor_id"]),
            row["assignee_id"] and str(row["assignee_id"]), row["note"]))
    for row in receipts:
        owner = key_owner.get(str(row["key"]), "unknown key")
        response = row["response"] or {}
        outcome = response["error"]["code"] if "error" in response else (
            as_view(response["exception"]) if "exception" in response else None)
        record = stored.setdefault(owner, {"view": None, "events": [], "receipts": []})
        record["receipts"].append((names[str(row["actor_id"])], str(row["key"]), row["status_code"], outcome))
    return {reference: Stored(record["view"], tuple(record["events"]), tuple(sorted(record["receipts"])))
            for reference, record in stored.items()}


def send(client, headers, request, ids):
    if request.kind == "read":
        return client.get(f"/api/exceptions/{ids[request.target]}")
    headers = {**headers, "Idempotency-Key": request.key}
    if request.kind == "create":
        return client.post("/api/exceptions", headers=headers, json={
            "reference": request.reference, "summary": request.summary,
            "details": request.details, "priority": request.priority})
    if request.kind == "assign":
        body = {"expected_version": request.expected_version, "assignee_id": request.assignee_id}
    else:
        body = {"expected_version": request.expected_version, "resolution": request.resolution}
    return client.post(f"/api/exceptions/{ids[request.target]}/{request.kind}", headers=headers, json=body)


def answer_of(response):
    header = response.headers.get("Idempotency-Replayed")
    replayed = None if header is None else header == "true"
    try:
        body = response.json()
    except ValueError:
        return Answer(response.status_code, "unreadable", replayed=replayed)
    if "error" in body:
        error = body["error"]
        return Answer(response.status_code, error["code"], error.get("current_version"), None, replayed)
    return Answer(response.status_code, None, None, as_view(body["exception"]), replayed)


@dataclass(frozen=True)
class Planned:
    client: str
    request: Request
    fault: str | None = None     # drop_ack, drop_request or duplicate for the second delivery
    lane: str = "primary"
    note: str | None = None      # retry, retry_after_drop, reuse, contend or stale


class History:
    """One seeded run: the clients' choices, what they know and what happened."""

    def __init__(self, seed, ids, initial):
        self.seed, self.ids, self.initial = seed, dict(ids), initial
        self.rng = random.Random(seed)
        self.focus = self.rng.choice(sorted(ids))
        self.plan = self.schedule()
        self.contended = False
        self.known = {client: {reference: 1 for reference in ids} for client in CLIENTS}
        self.writes = {client: [] for client in CLIENTS}
        self.unanswered = {client: [] for client in CLIENTS}
        self.lost_in_drop = []
        self.records = []
        self.stalls = []
        self.notes = set()

    def schedule(self):
        rng = self.rng
        drop = rng.randint(1, 2)
        plan = {drop: "drop", drop + 1: "retry"}
        read = rng.randint(drop + 2, drop + 3)
        plan.update({read: "read", read + 1: "contend"})
        plan[rng.choice([number for number in range(ROUNDS) if number not in plan])] = "duplicate"
        plan[rng.choice([number for number in range(read + 2, ROUNDS) if number not in plan])] = "stale"
        return plan

    # Building requests.

    def key(self):
        return str(UUID(int=self.rng.getrandbits(128), version=4))

    def edit(self, client, target=None, kind=None, assignee=ANY, version=None):
        rng, actor = self.rng, CLIENTS[client]
        if target is None:
            target = self.focus if rng.random() < 0.4 else rng.choice(sorted(self.ids))
        if kind is None:
            # Nobody resolves the contested exception before the contest.
            resolvable = self.contended or target != self.focus
            kind = "resolve" if resolvable and rng.random() < 0.2 else "assign"
        if version is None:
            version = self.known[client].get(target, 1)
        if kind == "assign":
            return Request("assign", actor, self.key(), target=target, expected_version=version,
                           assignee_id=rng.choice(ASSIGNEES) if assignee is ANY else assignee)
        return Request("resolve", actor, self.key(), target=target, expected_version=version,
                       resolution=rng.choice(TEXTS))

    def create(self, client):
        rng = self.rng
        return Request("create", CLIENTS[client], self.key(),
                       reference=rng.choice([*NEW_REFERENCES, *NEW_REFERENCES, self.focus]),
                       summary=rng.choice(TEXTS), details=rng.choice(TEXTS),
                       priority=rng.choice(["normal", "high"]))

    def write(self, client):
        return self.create(client) if self.rng.random() < 0.2 else self.edit(client)

    def other_body(self, request):
        rng = self.rng
        if request.kind == "create":
            return replace(request, summary=rng.choice([text for text in TEXTS if text != request.summary]))
        if request.kind == "resolve":
            return replace(request, resolution=rng.choice([text for text in TEXTS if text != request.resolution]))
        return replace(request, assignee_id=rng.choice([item for item in ASSIGNEES if item != request.assignee_id]))

    def random_call(self, client):
        rng = self.rng
        choice = rng.choices(["edit", "read", "create", "retry", "reuse"], weights=[6, 2, 1.5, 1, 1])[0]
        stale = False
        if choice == "read":
            return [Planned(client, Request("read", CLIENTS[client], "", target=rng.choice(sorted(self.ids))))]
        if choice in ("retry", "reuse") and self.writes[client]:
            earlier = rng.choice(self.writes[client])
            request = earlier if choice == "retry" else self.other_body(earlier)
            return [Planned(client, request, note=choice)]
        if choice == "create":
            request = self.create(client)
        else:
            stale = rng.random() < 0.1 and self.known[client].get(self.focus, 1) >= 2
            if stale:
                request = self.edit(client, target=self.focus, version=self.known[client][self.focus] - 1)
            else:
                request = self.edit(client)
        fault = rng.choices([None, "drop_ack", "drop_request", "duplicate"], weights=[16, 2, 1, 1.5])[0]
        if fault == "duplicate":
            return [Planned(client, request, note="stale" if stale else None),
                    Planned(client, request, "duplicate", "duplicate")]
        return [Planned(client, request, fault, note="stale" if stale else None)]

    # Rounds.

    def forced_calls(self, kind, busy):
        rng, calls = self.rng, []
        if kind == "drop":
            ack, lost = rng.sample(OPERATOR_CLIENTS, 2)
            calls += [Planned(ack, self.write(ack), "drop_ack"), Planned(lost, self.write(lost), "drop_request")]
            self.lost_in_drop = [(call.client, call.request) for call in calls]
        elif kind == "retry":
            # Exactly the two calls the drop round lost, each on its own key.
            calls += [Planned(client, request, note="retry_after_drop") for client, request in self.lost_in_drop]
        elif kind == "read":
            calls += [Planned(client, Request("read", CLIENTS[client], "", target=self.focus))
                      for client in OPERATOR_CLIENTS]
        elif kind == "contend":
            contenders = rng.sample(OPERATOR_CLIENTS, rng.choice([2, 3]))
            assignees = rng.sample(MEMBERS, len(contenders))
            calls += [Planned(client, self.edit(client, self.focus, "assign", assignee), note="contend")
                      for client, assignee in zip(contenders, assignees)]
        elif kind == "duplicate":
            client = rng.choice(OPERATOR_CLIENTS)
            request = self.write(client)
            calls += [Planned(client, request), Planned(client, request, "duplicate", "duplicate")]
        elif kind == "stale":
            ahead = [client for client in OPERATOR_CLIENTS if self.known[client][self.focus] >= 2]
            if ahead:
                client = rng.choice(ahead)
                calls.append(Planned(client, self.edit(client, self.focus, "assign",
                                                       version=self.known[client][self.focus] - 1), note="stale"))
        busy.update(call.client for call in calls)
        return calls

    def plan_round(self, number):
        busy = set()
        kind = self.plan.get(number)
        calls = self.forced_calls(kind, busy) if kind else []
        for client in CLIENTS:
            if client not in busy and self.rng.random() < 0.6:
                calls += self.random_call(client)
        stall = CONTEND_STALL if kind == "contend" else self.rng.choice([0, 0, 0.02, 0.05])
        return calls, stall

    # Running a round.

    def perform(self, planned, barrier, lanes, ids):
        client, headers = lanes[planned.lane][planned.client]
        barrier.wait(timeout=30)
        invoked = time.monotonic_ns()
        if planned.fault == "drop_request":
            return invoked, None, None, None
        answer = answer_of(send(client, headers, planned.request, ids))
        returned = time.monotonic_ns()
        if planned.fault == "drop_ack":
            return invoked, None, None, answer
        return invoked, returned, answer, None

    def run_round(self, number, pool, lanes, started):
        calls, stall = self.plan_round(number)
        self.stalls.append(stall)
        if not calls:
            return
        # Every call of a round must hold a worker at once, or the barrier waits forever.
        assert len(calls) <= WORKERS, f"round {number} planned {len(calls)} calls for {WORKERS} workers"
        STALL["seconds"] = stall
        try:
            barrier = Barrier(len(calls))
            ids = dict(self.ids)
            futures = [pool.submit(self.perform, planned, barrier, lanes, ids) for planned in calls]
            results = [future.result(timeout=60) for future in futures]
        finally:
            STALL["seconds"] = 0.0
        for planned, (invoked, returned, answer, server_answer) in zip(calls, results):
            self.records.append({
                "id": len(self.records), "round": number, "client": planned.client, "lane": planned.lane,
                "fault": planned.fault, "note": planned.note, "request": asdict(planned.request),
                "invoked_ns": invoked - started, "returned_ns": returned and returned - started,
                "answer": answer and asdict(answer),
                "server_answer_not_seen_by_client": server_answer and asdict(server_answer)})
            self.learn(planned, answer)
        if any(planned.note == "contend" for planned in calls):
            self.contended = True

    def learn(self, planned, answer):
        client, request = planned.client, planned.request
        for name in (planned.fault, planned.note):
            if name:
                self.notes.add(name)
        if request.kind != "read" and planned.lane == "primary" and request not in self.writes[client]:
            self.writes[client].append(request)
        if answer is None:
            if request.kind != "read" and request not in self.unanswered[client]:
                self.unanswered[client].append(request)
            return
        if request in self.unanswered[client]:
            self.unanswered[client].remove(request)
        exception = request.reference if request.kind == "create" else request.target
        if answer.view:
            self.known[client][exception] = answer.view[-1]
        elif answer.current_version:
            self.known[client][exception] = answer.current_version

    def checker_calls(self):
        calls = []
        for record in self.records:
            answer = record["answer"]
            calls.append(Call(record["id"], Request(**record["request"]), record["invoked_ns"],
                              record["returned_ns"], answer and Answer(**answer)))
        return calls

    def key_owner(self):
        return {record["request"]["key"]: record["request"]["reference"] if record["request"]["kind"] == "create"
                else record["request"]["target"] for record in self.records if record["request"]["kind"] != "read"}


def overlapping_pairs(calls):
    """Pairs of answered calls on one exception that were in flight at the same time."""
    count = 0
    answered = [call for call in calls if call.returned is not None]
    for index, first in enumerate(answered):
        for second in answered[index + 1:]:
            if (first.exception == second.exception and first.invoked < second.returned
                    and second.invoked < first.returned):
                count += 1
    return count


def run_one(database_url, seed, lanes, pool, path, guard):
    reset_workflow(database_url)
    ids, initial = northline_records(database_url)
    history = History(seed, ids, initial)
    started = time.monotonic_ns()
    for number in range(ROUNDS):
        history.run_round(number, pool, lanes, started)
        history.ids = northline_records(database_url)[0]
    calls = history.checker_calls()
    stored = read_back(database_url, history.key_owner())
    users = {name: str(user) for name, user in USERS.items()}
    verdict = check(users, initial, calls, stored)
    summary = {
        "seed": seed, "guard_removed": guard, "file": path.name, "calls": len(calls),
        "exceptions": len({call.exception for call in calls}),
        "unanswered": sum(call.answer is None for call in calls),
        "overlapping_pairs": overlapping_pairs(calls), "faults": sorted(history.notes),
        "ok": verdict.ok, "kind": verdict.kind, "kinds": list(verdict.kinds), "detail": verdict.detail}
    path.write_text(json.dumps({
        "format": "shipment-concurrent-history-1", **summary, "focus": history.focus,
        "plan": {str(number): kind for number, kind in sorted(history.plan.items())},
        "stall_seconds_by_round": history.stalls, "users": users, "initial": initial,
        "calls": history.records,
        "stored": {reference: asdict(record) for reference, record in sorted(stored.items())},
        "orders": verdict.orders}, indent=1, default=str), encoding="utf-8")
    return summary


def run_histories(database_url, guard, seeds, folder):
    app = build_app(database_url, guard)
    variant = "kept" if guard is None else f"without-{guard}"
    summaries = []
    with ExitStack() as stack:
        lanes = {"primary": {}, "duplicate": {}}
        for client, actor in CLIENTS.items():
            session, headers = stack.enter_context(authenticated_client(app, EMAILS[actor]))
            second = stack.enter_context(TestClient(app, raise_server_exceptions=False, cookies=session.cookies))
            lanes["primary"][client], lanes["duplicate"][client] = (session, headers), (second, headers)
        pool = stack.enter_context(ThreadPoolExecutor(max_workers=WORKERS))
        for seed in seeds:
            summaries.append(run_one(database_url, seed, lanes, pool,
                                     folder / f"{variant}-seed{seed:02d}.json", guard))
    (folder / f"summary-{variant}.json").write_text(json.dumps(summaries, indent=1), encoding="utf-8")
    return summaries


def test_concurrent_histories_agree_with_the_model(database, history_dir, stall):
    summaries = run_histories(database, None, chosen_seeds(KEPT_SEEDS), history_dir)
    failures = [summary for summary in summaries if not summary["ok"]]
    assert not failures, json.dumps(failures, indent=1)
    for summary in summaries:
        missing = set(FORCED) - set(summary["faults"])
        assert not missing, f"seed {summary['seed']} did not carry {sorted(missing)}"
        assert summary["overlapping_pairs"] > 0, f"seed {summary['seed']} had no overlapping calls"
        # The saved file alone gives the same verdict, so a history can be checked again later.
        assert check(*load(history_dir / summary["file"])).ok


def as_lost(calls):
    """The same calls with every 500 read as an answer that never arrived."""
    return [replace(call, answer=None, returned=None) if call.answer and call.answer.status >= 500 else call
            for call in calls]


@pytest.mark.parametrize("guard", sorted(GUARDS))
def test_the_checker_reports_each_removed_guard(database, history_dir, stall, guard):
    summaries = run_histories(database, guard, chosen_seeds(REMOVED_SEEDS), history_dir)
    caught = {summary["seed"]: PREDICTED[guard] in summary["kinds"] for summary in summaries}
    assert all(caught.values()), json.dumps(summaries, indent=1)
    # Without the receipt clause or the row lock, the receipt primary key and the
    # unique audit version still keep the stored state right. Read each 500 as a
    # lost answer and those histories pass, so the check catches these two
    # removals only through the rule that no answer is a 500. A missing version
    # check changes what is stored, and no reading of the answers hides that.
    for summary in summaries:
        users, initial, calls, stored = load(history_dir / summary["file"])
        assert check(users, initial, as_lost(calls), stored).ok == (PREDICTED[guard] == "unconfirmed_answer")
