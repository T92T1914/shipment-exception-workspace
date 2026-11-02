"""Workload accounting rejects the errors that can make a load report flattering."""

import importlib.util
import copy
import json
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from capacity_model import digest, identity, plan, summarize, trial_summary, verify_reconciliation
from qualify_capacity import local_url


@pytest.fixture
def protocol():
    return json.loads((TOOLS / "capacity-protocol.json").read_text())


@pytest.mark.parametrize("rate", [1, 2, 4, 8])
def test_open_schedule_and_exact_mix(protocol, rate):
    rows = plan(protocol, rate)
    measured = [r for r in rows if r["phase"] == "measurement"]
    assert len(rows) == 90 * rate and len(measured) == 60 * rate
    assert sum(r["route"].startswith("queue") for r in measured) == 36 * rate
    assert sum(r["route"].startswith("history") for r in measured) == 18 * rate
    assert sum(r["route"] == "assign" for r in measured) == 6 * rate
    mutations = [(r["org"], r["object_index"]) for r in rows if r["route"] == "assign"]
    assert len(set(mutations)) == len(mutations)
    assert all(index < 200 for _, index in mutations)
    assert measured[-1]["scheduled"] == 90 - 1 / rate


def test_refusals_transport_errors_and_drops_remain_in_denominator():
    rows = [
        {"category": "successful", "status": 200, "scheduled": 0, "dispatched": .2, "completed": .5},
        {"category": "refused", "status": 503, "scheduled": 1, "dispatched": 1, "completed": 1.1},
        {"category": "failed", "scheduled": 2, "dispatched": 2, "completed": 3},
        {"category": "dropped", "scheduled": 3},
    ]
    result = summarize(rows, 4)
    assert result["scheduled"] == 4 and result["completion_fraction"] == .25
    assert result["dispatched"] == 3 and result["completed"] == 2
    assert result["clocks_seconds"]["schedule_to_complete"]["p95"] == .5
    assert result["clocks_seconds"]["dispatch_to_complete"]["p95"] == .3
    assert result["p95_exploratory"] is True


def test_warmup_does_not_improve_measurement(protocol):
    warmup = {"route": "assign", "phase": "warmup", "category": "successful", "status": 200,
              "scheduled": 0, "dispatched": 0, "completed": .1}
    measurement = {"route": "assign", "phase": "measurement", "category": "dropped", "scheduled": 31}
    assert trial_summary([warmup, measurement], protocol)["aggregate"]["completion_fraction"] == 0


@pytest.mark.parametrize("url", [
    "postgresql://user:password@example.com:5432/capacity", "postgresql://user:password@localhost:5432/capacity",
    "postgresql://user:password@127.0.0.1:5432/capacity?host=example.com",
    "postgresql://user:password@127.0.0.1:5432/capacity#fragment", "postgresql://127.0.0.1/capacity",
])
def test_remote_or_ambiguous_database_targets_rejected(url):
    with pytest.raises(ValueError):
        local_url(url)


@pytest.fixture
def reconciled_intent():
    seed = 20261101
    ident = identity(seed, "exception", 1, 20)
    org, actor, other = (identity(seed, kind, 1) for kind in ("org", "operator", "other"))
    initial_record = {"id": ident, "organization_id": org, "reference": "SYN-00020_!%",
        "summary": "Synthetic queue record 00020", "details": "Disposable capacity fixture.",
        "priority": "normal", "status": "open", "assignee_id": other,
        "resolution": None, "version": 10, "updated_at": "2026-01-01 00:00:00+00:00"}
    initial = {"shipment_exceptions": [initial_record], "exception_events": [], "mutation_requests": []}
    final_record = {**initial_record, "assignee_id": actor, "version": 11, "updated_at": "2026-11-01 00:00:00+00:00"}
    body = {"expected_version": 10, "assignee_id": actor}
    response = {"exception": {k: v for k, v in final_record.items() if k != "organization_id"}}
    response["exception"]["assignee_name"] = "Capacity operator 1"
    key = identity(seed, "test-intent", 1, 20)
    fingerprint = digest({"action": "assigned", "exception_id": ident, **body})
    intent = {"org": 1, "id": ident, "key": key, "body": body, "fingerprint": fingerprint,
              "dispatched": True, "observed_status": 200, "response": response}
    after = {"shipment_exceptions": [final_record],
        "exception_events": [{"exception_id": ident, "organization_id": org, "actor_id": actor,
                              "assignee_id": actor, "action": "assigned", "note": None, "version": 11}],
        "mutation_requests": [{"key": key, "organization_id": org, "actor_id": actor,
                               "fingerprint": fingerprint, "status_code": 200, "response": response}]}
    return initial, after, [intent], seed


def test_complete_business_reconciliation(reconciled_intent):
    assert verify_reconciliation(*reconciled_intent)["committed_mutations"] == 1


@pytest.mark.parametrize("fault", ["lost_record", "lost_audit", "duplicate_receipt", "foreign_receipt", "undispatched_commit", "bad_response"])
def test_reconciliation_rejects_false_integrity(reconciled_intent, fault):
    initial, after, intents, seed = copy.deepcopy(reconciled_intent)
    if fault == "lost_record":
        after["shipment_exceptions"] = []
    elif fault == "lost_audit":
        after["exception_events"] = []
    elif fault == "duplicate_receipt":
        after["mutation_requests"].append(copy.deepcopy(after["mutation_requests"][0]))
    elif fault == "foreign_receipt":
        after["mutation_requests"][0]["organization_id"] = identity(seed, "org", 2)
    elif fault == "undispatched_commit":
        intents[0]["dispatched"] = False
    else:
        after["mutation_requests"][0]["response"]["exception"]["summary"] = "Incorrect response"
    with pytest.raises(AssertionError):
        verify_reconciliation(initial, after, intents, seed)
