"""A sequential reference model of the write contract.

The model is plain Python with no database and no web framework. It states
what each write must answer and what it must leave behind when requests arrive
one at a time. tests/test_workflow_model.py drives the installed application
against it, so a disagreement between the two is a finding about one or the
other.

The contract it states, in the order the application applies it:

1. A reviewer cannot write. The refusal leaves no receipt, even when the retry
   key was already used by someone else.
2. A retry key belongs to one actor and one request body. Reusing it with the
   same body returns the saved answer and changes nothing. Reusing it with a
   different body is a conflict that changes nothing.
3. A new request is checked against the saved record in this order: the
   exception exists, the version the caller saw is the current one, the
   exception is still open, and an assignee belongs to the organization.
4. Every answer from step 3 is saved as the receipt for the key, including the
   refusals. A success changes the record, raises its version by one and adds
   one audit event with that version.
5. A creation succeeds only for a reference this organization has not used.
   A refused creation is saved as a receipt and creates nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


OPERATORS = ("alex", "sam")
REVIEWER = "casey"
ACTORS = (*OPERATORS, REVIEWER)
ROLES = {"alex": "operator", "sam": "operator", "casey": "reviewer"}

VIEW_FIELDS = ("reference", "summary", "details", "status", "priority",
               "assignee_id", "resolution", "version")


@dataclass(frozen=True)
class Request:
    """One write as a caller intends it, before it is sent."""

    kind: str                  # "create", "assign" or "resolve"
    actor: str
    key: str
    target: str | None = None  # reference of the exception an edit names
    reference: str | None = None
    summary: str | None = None
    details: str | None = None
    priority: str | None = None
    expected_version: int | None = None
    assignee_id: str | None = None
    resolution: str | None = None

    def fingerprint(self):
        """Two requests are the same change only when this tuple matches."""
        if self.kind == "create":
            return ("create", self.reference, self.summary, self.details, self.priority)
        if self.kind == "assign":
            return ("assign", self.target, self.expected_version, self.assignee_id)
        return ("resolve", self.target, self.expected_version, self.resolution)

    def with_identity(self, actor, key):
        return replace(self, actor=actor, key=key)


@dataclass(frozen=True)
class Reply:
    """What the application must answer for one request."""

    status: int
    code: str | None = None             # error code, when the answer is an error
    view: tuple | None = None           # the exception as the answer shows it
    current_version: int | None = None
    replayed: bool | None = None        # None when no replay header is promised


class Model:
    def __init__(self, organization_users, initial_exceptions):
        self.users = dict(organization_users)           # actor name -> user id
        self.members = set(self.users.values())
        self.items: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[tuple]] = {}
        self.receipts: dict[tuple[str, str], tuple[tuple, Reply]] = {}
        for row in initial_exceptions:
            self.items[row["reference"]] = {name: row[name] for name in VIEW_FIELDS}
            self.events[row["reference"]] = []

    # Questions the machine asks while it builds the next request.

    def references(self):
        return sorted(self.items)

    def version_of(self, reference):
        return self.items[reference]["version"]

    # The write contract.

    def apply(self, request: Request) -> Reply:
        if ROLES[request.actor] != "operator":
            return Reply(403, code="read_only")
        saved = self.receipts.get((request.actor, request.key))
        if saved:
            fingerprint, reply = saved
            if fingerprint != request.fingerprint():
                return Reply(409, code="idempotency_conflict")
            return replace(reply, replayed=True)
        reply = self._create(request) if request.kind == "create" else self._edit(request)
        self.receipts[(request.actor, request.key)] = (request.fingerprint(), reply)
        return reply

    def _create(self, request):
        if request.reference in self.items:
            return Reply(409, code="reference_conflict", replayed=False)
        item = {"reference": request.reference, "summary": request.summary,
                "details": request.details, "status": "open", "priority": request.priority,
                "assignee_id": None, "resolution": None, "version": 1}
        self.items[request.reference] = item
        self.events[request.reference] = [("created", 1, self.users[request.actor], None, None)]
        return Reply(201, view=self._view(item), replayed=False)

    def _edit(self, request):
        item = self.items.get(request.target)
        if item is None:
            return Reply(404, code="not_found", replayed=False)
        if item["version"] != request.expected_version:
            return Reply(409, code="version_conflict", current_version=item["version"], replayed=False)
        if item["status"] == "resolved":
            return Reply(409, code="already_resolved", replayed=False)
        if request.kind == "assign":
            if request.assignee_id is not None and request.assignee_id not in self.members:
                return Reply(400, code="invalid_assignee", replayed=False)
            item["assignee_id"] = request.assignee_id
            action, assignee, note = "assigned", request.assignee_id, None
        else:
            item["status"], item["resolution"] = "resolved", request.resolution
            action, assignee, note = "resolved", item["assignee_id"], request.resolution
        item["version"] += 1
        self.events[request.target].append(
            (action, item["version"], self.users[request.actor], assignee, note))
        return Reply(200, view=self._view(item), replayed=False)

    @staticmethod
    def _view(item):
        return tuple(item[name] for name in VIEW_FIELDS)

    # What a read of the stored state must show once the writes are done.

    def stored_exceptions(self):
        return {reference: self._view(item) for reference, item in self.items.items()}

    def stored_events(self):
        return {reference: list(events) for reference, events in self.events.items()}

    def stored_receipts(self):
        """Actor, key and saved status for every receipt, in a stable order."""
        return sorted((actor, key, reply.status) for (actor, key), (_, reply) in self.receipts.items())
