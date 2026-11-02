"""Deterministic workload and independently recomputable result accounting."""

import hashlib
import json
import math
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5


def identity(seed, kind, org, index=0):
    return str(uuid5(NAMESPACE_URL, f"shipment-capacity:{seed}:{kind}:{org}:{index}"))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def plan(protocol, rate):
    warmup = protocol["warmup_seconds"]
    duration = warmup + protocol["measurement_seconds"]
    cycle = protocol["mix_cycle"]
    result = []
    for slot in range(rate * duration):
        route = cycle[slot % len(cycle)]
        org = (slot // 10) % 2 + 1
        result.append({"slot": slot, "scheduled": slot / rate, "org": org,
                       "route": route, "object_index": 20 + slot // 10 if route == "assign" else 0,
                       "phase": "warmup" if slot / rate < warmup else "measurement",
                       "filter": "_!%" if slot % 20 < 10 else "000"})
    return result


def percentile(values, fraction):
    if not values:
        return None
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def summarize(rows, seconds):
    counts = {name: 0 for name in ("scheduled", "dispatched", "completed", "successful",
                                  "refused", "failed", "dropped")}
    status = {}
    clocks = {name: [] for name in ("schedule_to_dispatch", "dispatch_to_complete", "schedule_to_complete")}
    for row in rows:
        counts["scheduled"] += 1
        if row["category"] == "dropped":
            counts["dropped"] += 1
            continue
        counts["dispatched"] += 1
        if row.get("status") is not None:
            counts["completed"] += 1
            key = str(row["status"])
            status[key] = status.get(key, 0) + 1
        counts[row["category"]] += 1
        if row["category"] == "successful":
            clocks["schedule_to_dispatch"].append(row["dispatched"] - row["scheduled"])
            clocks["dispatch_to_complete"].append(row["completed"] - row["dispatched"])
            clocks["schedule_to_complete"].append(row["completed"] - row["scheduled"])
    assert counts["scheduled"] == counts["successful"] + counts["refused"] + counts["failed"] + counts["dropped"]
    return {**counts, "statuses": status,
            "completion_fraction": counts["successful"] / counts["scheduled"] if counts["scheduled"] else None,
            "successful_per_second": counts["successful"] / seconds,
            "p95_exploratory": counts["successful"] < 200,
            "clocks_seconds": {name: {"n": len(v), "p50": percentile(v, .5),
                                     "p95": percentile(v, .95), "max": max(v) if v else None}
                               for name, v in clocks.items()}}


def trial_summary(rows, protocol):
    measured = [row for row in rows if row["phase"] == "measurement"]
    return {"aggregate": summarize(measured, protocol["measurement_seconds"]),
            "routes": {route: summarize([r for r in measured if r["route"] == route],
                                         protocol["measurement_seconds"])
                       for route in sorted(set(protocol["mix_cycle"]))}}


def verify_reconciliation(initial, after, intents, seed):
    """Check all ordered business rows and each intent without database access."""
    receipts = {str(row["key"]): row for row in after["mutation_requests"]}
    assert len(receipts) == len(after["mutation_requests"]), "Duplicate logical receipt key"
    assert initial["mutation_requests"] == []
    assert set(receipts).issubset({item["key"] for item in intents}), "Unexplained receipt"
    expected_exceptions = {str(row["id"]): dict(row) for row in initial["shipment_exceptions"]}
    initial_events = initial["exception_events"]
    assert after["exception_events"][:len(initial_events)] == initial_events, "Initial history changed"
    actual_new = after["exception_events"][len(initial_events):]
    expected_events = []
    applied = set()
    for item in intents:
        receipt = receipts.get(item["key"])
        if not item.get("dispatched"):
            assert receipt is None, "Undispatched intent has a receipt"
        if receipt is None:
            assert item.get("observed_status") != 200, "Successful intent has no receipt"
            continue
        assert receipt["fingerprint"] == item["fingerprint"]
        assert str(receipt["actor_id"]) == identity(seed, "operator", item["org"])
        assert str(receipt["organization_id"]) == identity(seed, "org", item["org"])
        assert receipt["status_code"] in (200, 409, 404) and receipt["response"] is not None
        if item.get("observed_status") in (200, 409, 404):
            assert receipt["status_code"] == item["observed_status"]
        if item.get("response") is not None:
            assert digest(receipt["response"]) == digest(item["response"])
        if receipt["status_code"] != 200:
            continue
        row = expected_exceptions[item["id"]]
        assert row["version"] == item["body"]["expected_version"]
        row["version"] += 1
        row["assignee_id"] = item["body"]["assignee_id"]
        applied.add(item["id"])
        response = receipt["response"]["exception"]
        assert response["id"] == item["id"] and response["version"] == row["version"]
        assert response["assignee_id"] == item["body"]["assignee_id"]
        assert set(response) == (set(row) - {"organization_id"}) | {"assignee_name"}
        for key in ("reference", "summary", "details", "status", "priority", "resolution"):
            assert response[key] == row[key]
        assert response["assignee_name"] == f"Capacity operator {item['org']}"
        assert datetime.fromisoformat(response["updated_at"]) >= datetime.fromisoformat(str(row["updated_at"]))
        expected_events.append((item["id"], row["version"], identity(seed, "operator", item["org"]),
                                item["body"]["assignee_id"], identity(seed, "org", item["org"])))
    assert set(str(row["id"]) for row in after["shipment_exceptions"]) == set(expected_exceptions)
    assert len(after["shipment_exceptions"]) == len(expected_exceptions)
    for row in after["shipment_exceptions"]:
        expected = expected_exceptions[str(row["id"])]
        for key, value in expected.items():
            if key == "updated_at" and str(row["id"]) in applied:
                assert str(row[key]) >= str(value)
            else:
                assert str(row[key]) == str(value), (key, row["id"])
    actual = []
    for event in actual_new:
        assert event["action"] == "assigned" and event["note"] is None
        actual.append(tuple(str(event[key]) if key != "version" else event[key]
                            for key in ("exception_id", "version", "actor_id", "assignee_id", "organization_id")))
    assert sorted(actual) == sorted(expected_events), "Unexplained or missing audit event"
    return {"passed": True, "initial_sha256": digest(initial), "final_sha256": digest(after),
            "complete_receipts": len(receipts), "committed_mutations": len(expected_events),
            "final_events": len(after["exception_events"]), "full_ordered_business_comparison": True}


def verify_fixture(initial, seed, size):
    expected = {identity(seed, "exception", org, index): (org, index)
                for org in (1, 2) for index in range(size)}
    records = initial["shipment_exceptions"]
    assert len(records) == 2 * size and {str(row["id"]) for row in records} == set(expected)
    for record in records:
        org, index = expected[str(record["id"])]
        assert str(record["organization_id"]) == identity(seed, "org", org)
        assert record["reference"] == f"SYN-{index:05d}_!%" and record["version"] == 10
        assert record["summary"] == f"Synthetic queue record {index:05d}"
        assert record["details"] == "Disposable capacity fixture."
        assert record["status"] == "open" and record["resolution"] is None
        assert str(record["assignee_id"]) == identity(seed, "other", org)
    histories = {ident: [] for ident in expected}
    for event in initial["exception_events"]:
        org, _ = expected[str(event["exception_id"])]
        assert str(event["organization_id"]) == identity(seed, "org", org)
        assert str(event["actor_id"]) == identity(seed, "operator", org)
        assert event["action"] == ("created" if event["version"] == 1 else "assigned")
        assert str(event["assignee_id"]) == (identity(seed, "other", org) if event["version"] % 2 == 0 else "None")
        assert event["note"] is None
        histories[str(event["exception_id"])].append(event["version"])
    assert all(sorted(versions) == list(range(1, 11)) for versions in histories.values())
    return True
