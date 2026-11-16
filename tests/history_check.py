"""Check a recorded history of concurrent calls against the sequential model.

A history is every call several clients made, with the time each call was sent
and the time its answer came back, and what a read of the database showed once
every call had finished. The history passes when, for every exception, some
order of its calls does all of these at once:

1. A call that came back before another call was sent comes first.
2. The model in tests/workflow_model.py gives every answered call the answer
   the client saw, replay header included.
3. A call whose answer never reached the client counts as may have happened.
   The order can place it anywhere after it was sent, or leave it out.
4. After the order, the model holds exactly the stored exception, its audit
   events and the retry receipts for its keys.

Two more rules hold over the whole history. No retry key may get two answers
that each report a new change, and no answer may be a server error such as 500.
The model never gives an unconfirmed answer, and a healthy database gives the
application no reason to.

The search is split by exception. Every call names one exception, every retry
key stays with one exception, and nothing one exception does changes what the
model answers for another, so the history passes when each part passes on its
own. That keeps each search to a few dozen calls. Within a part the search
tries each call that may go next, drops a branch as soon as the model holds an
audit event or a receipt the database lacks, remembers every set of placed
calls and model state it has already ruled out, and stops at the first order
that works. When none works, a second search over the answers alone says
whether the answers or the stored state could not be explained. Every part
that fails is reported.

Run this file with a saved history to check it again:

    python tests/history_check.py history.json
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import sys

from workflow_model import Model, Reply, Request, VIEW_FIELDS


@dataclass(frozen=True)
class Answer:
    """What one client saw come back for one call."""

    status: int
    code: str | None = None
    current_version: int | None = None
    view: tuple | None = None
    replayed: bool | None = None   # None when the answer carried no replay header


@dataclass(frozen=True)
class Call:
    id: int
    request: Request               # kind "read" for a read of request.target
    invoked: int                   # when the client sent it
    returned: int | None = None    # None when the answer never reached the client
    answer: Answer | None = None   # None for the same reason

    @property
    def exception(self):
        return self.request.reference if self.request.kind == "create" else self.request.target


@dataclass(frozen=True)
class Stored:
    """A read of the database for one exception once every call has finished."""

    view: tuple | None
    events: tuple                  # (action, version, actor id, assignee id, note)
    receipts: tuple                # (actor, key, status, error code or exception view)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    kind: str | None = None        # unconfirmed_answer, duplicate_effect, no_order or stored_state
    detail: str = ""
    orders: dict = field(default_factory=dict)
    kinds: tuple = ()              # every kind found, when more than one exception fails

    def __post_init__(self):
        if self.kind and not self.kinds:
            object.__setattr__(self, "kinds", (self.kind,))


def agrees(answer: Answer, reply: Reply):
    if answer.status != reply.status or answer.replayed != reply.replayed:
        return False
    if reply.code:
        return answer.code == reply.code and answer.current_version == reply.current_version
    return answer.code is None and answer.view == reply.view


def perform(model, call):
    request = call.request
    return model.read(request.target) if request.kind == "read" else model.apply(request)


def model_state(model):
    """A hashable copy of everything the model holds, for the search memo."""
    return (tuple(sorted((reference, Model._view(item)) for reference, item in model.items.items())),
            tuple(sorted((reference, tuple(events)) for reference, events in model.events.items())),
            tuple(sorted(model.receipts.items())))


def model_record(model, exception):
    item = model.items.get(exception)
    receipts = sorted((actor, key, reply.status, reply.code or reply.view)
                      for (actor, key), (_, reply) in model.receipts.items())
    return Stored(Model._view(item) if item else None,
                  tuple(model.events.get(exception, ())), tuple(receipts))


def describe(call, reply=None):
    request = call.request
    if request.kind == "read":
        what = f"call {call.id} read {request.target}"
    elif request.kind == "create":
        what = f"call {call.id} {request.actor} create {request.reference}"
    else:
        what = (f"call {call.id} {request.actor} {request.kind} {request.target} "
                f"from version {request.expected_version}")
    if call.answer is None:
        return what + " (answer never arrived)"
    answer = call.answer
    seen = f"{answer.status} {answer.code or ''}".strip()
    if reply is None:
        return f"{what} answered {seen}"
    expected = f"{reply.status} {reply.code or ''}".strip()
    if seen == expected:
        seen, expected = f"{seen} {answer.view} replayed={answer.replayed}", f"{expected} {reply.view} replayed={reply.replayed}"
    return f"{what} answered {seen} where the model answers {expected}"


def could_still_become(model, exception, stored):
    """Whether the stored state can still be reached from this model state.

    Audit events and receipts are only ever added, never changed or removed, so
    once the model holds an event the database lacks, or a receipt it does not
    hold, no later call can mend it and the branch is dropped.
    """
    record = model_record(model, exception)
    return (record.events == stored.events[:len(record.events)]
            and set(record.receipts) <= set(stored.receipts))


def search(start, exception, calls, stored=None):
    """Return an order of the calls that fits, or None with the deepest dead end.

    With stored given, the order must also leave the model holding it. Without
    it, only the answers count, which tells the two kinds of failure apart.
    """
    answered = frozenset(call.id for call in calls if call.answer is not None)
    ruled_out = set()
    deepest = {"order": None, "misfits": []}

    def step(model, placed, order):
        memo = (placed, model_state(model))
        if memo in ruled_out:
            return None
        ruled_out.add(memo)
        if answered <= placed and (stored is None or model_record(model, exception) == stored):
            return order
        waiting = [call for call in calls if call.id not in placed]
        # A call may go next only if no waiting call came back before it was sent.
        deadline = min((call.returned for call in waiting if call.returned is not None), default=None)
        misfits = []
        for call in waiting:
            if deadline is not None and call.invoked > deadline:
                continue
            after = copy.deepcopy(model)
            reply = perform(after, call)
            if call.answer is not None and not agrees(call.answer, reply):
                misfits.append(describe(call, reply))
                continue
            if stored is not None and not could_still_become(after, exception, stored):
                continue
            found = step(after, placed | {call.id}, [*order, call.id])
            if found is not None:
                return found
        if deepest["order"] is None or len(order) > len(deepest["order"]):
            deepest["order"], deepest["misfits"] = order, misfits
        return None

    return step(start, frozenset(), []), deepest


def order_one(users, initial, exception, calls, stored):
    """Find an order for the calls on one exception, or say why there is none."""
    start = Model(users, [row for row in initial if row["reference"] == exception])
    found, _ = search(start, exception, calls, stored)
    if found is not None:
        return found, None
    answers_only, deepest = search(start, exception, calls)
    if answers_only is not None:
        return None, Verdict(False, "stored_state", (
            f"{exception}: every answer fits some order, but no such order leaves the model "
            f"holding what the database stored: {stored}"))
    misfits = ". ".join(deepest["misfits"]) or "no waiting call may go next"
    return None, Verdict(False, "no_order", (
        f"{exception}: the longest order that fits is calls {deepest['order']}, "
        f"and then no call fits. {misfits}"))


def check(users, initial, calls, stored) -> Verdict:
    """Return whether the history has an order the model accepts.

    users maps each actor to a user id, initial holds the exception rows before
    the first call, calls is the history and stored maps each exception the
    database holds afterwards, or a key no call used, to its Stored read.
    """
    unconfirmed = [call for call in calls if call.answer is not None and call.answer.status >= 500]
    if unconfirmed:
        return Verdict(False, "unconfirmed_answer", ". ".join(describe(call) for call in unconfirmed))
    effects = {}
    for call in calls:
        answer = call.answer
        if answer is not None and answer.status in (200, 201) and answer.replayed is False:
            effects.setdefault((call.request.actor, call.request.key), []).append(call)
    doubled = [found for found in effects.values() if len(found) > 1]
    if doubled:
        return Verdict(False, "duplicate_effect", ". ".join(
            describe(call) for found in doubled for call in found))
    groups, owners = {}, {}
    for call in calls:
        groups.setdefault(call.exception, []).append(call)
        if call.request.kind != "read":
            owner = owners.setdefault((call.request.actor, call.request.key), call.exception)
            if owner != call.exception:
                raise ValueError(f"call {call.id} uses a retry key from {owner} on {call.exception}, "
                                 "so the history cannot be split by exception")
    # An exception no call touched must still read back as it started, and a
    # stored receipt for a key no call used fails the same way.
    exceptions = set(groups) | set(stored) | {row["reference"] for row in initial}
    orders, failures = {}, []
    for exception in sorted(exceptions):
        expected = stored.get(exception, Stored(None, (), ()))
        order, failure = order_one(users, initial, exception, groups.get(exception, []), expected)
        if failure:
            failures.append(failure)
        else:
            orders[exception] = order
    if failures:
        return Verdict(False, failures[0].kind, " | ".join(failure.detail for failure in failures),
                       orders, tuple(sorted({failure.kind for failure in failures})))
    return Verdict(True, orders=orders)


# Reading and writing the saved form. JSON has no tuples, so views, events and
# receipts come back as lists and are turned back into tuples here.

def freeze(value):
    return tuple(freeze(item) for item in value) if isinstance(value, list) else value


def answer_from(data):
    if data is None:
        return None
    return Answer(data["status"], data.get("code"), data.get("current_version"),
                  freeze(data.get("view")), data.get("replayed"))


def load(path):
    with open(path, encoding="utf-8") as source:
        history = json.load(source)
    calls = [Call(item["id"], Request(**item["request"]), item["invoked_ns"],
                  item["returned_ns"], answer_from(item["answer"])) for item in history["calls"]]
    stored = {exception: Stored(freeze(record["view"]), freeze(record["events"]), freeze(record["receipts"]))
              for exception, record in history["stored"].items()}
    return history["users"], history["initial"], calls, stored


def main(argv):
    if len(argv) != 2:
        print("Usage: python tests/history_check.py history.json")
        return 2
    verdict = check(*load(argv[1]))
    if verdict.ok:
        print(f"The history has an order the model accepts: {verdict.orders}")
        return 0
    print(f"Violation, {verdict.kind}: {verdict.detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
