"""Recompute a capacity report from its finite sanitized request records."""

import argparse
import gzip
import json
from pathlib import Path

from capacity_model import digest, plan, trial_summary, verify_reconciliation, verify_fixture


def check(run):
    protocol = json.loads((run / "protocol.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    assert digest(protocol) == manifest["protocol_sha256"]
    summaries = []
    active_total = 0
    for size in protocol["exceptions_per_org"]:
        for rate in protocol["rates"]:
            for rep in range(protocol["replicates"]):
                directory = run / f"n{size}-r{rate}-rep{rep}"
                rows = [json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines()]
                expected = plan(protocol, rate)
                assert len(rows) == len(expected)
                rows.sort(key=lambda r: r["slot"])
                assert [{k: row[k] for k in item} for row, item in zip(rows, expected)] == expected
                for row in rows:
                    assert row["category"] in {"successful", "failed", "refused", "dropped"}
                    assert row.get("error") not in {"AssertionError", "KeyError", "JSONDecodeError", "ValueError", "TypeError", "UnicodeDecodeError"}, "Incorrect response requires investigation, regardless of completion target"
                    if row["category"] == "successful":
                        assert row["status"] == 200 and row["validated"] is True
                    if row["category"] != "dropped":
                        assert row["scheduled"] <= row["dispatched"] <= row["completed"]
                summary = trial_summary(rows, protocol)
                recorded = json.loads((directory / "result.json").read_text())
                timing = json.loads((directory / "timing.json").read_text())
                assert 90 <= recorded["active_seconds"] <= 103
                assert abs(timing["active_seconds"] - recorded["active_seconds"]) < .1
                assert timing["finished_monotonic"] >= timing["started_monotonic"] + 90
                active_total += timing["active_seconds"]
                assert summary == recorded["summary"]
                with gzip.open(directory / "initial-business.json.gz", "rt", encoding="utf-8") as stream:
                    initial = json.load(stream)
                with gzip.open(directory / "final-business.json.gz", "rt", encoding="utf-8") as stream:
                    after = json.load(stream)
                intents = json.loads((directory / "intent-ledger.json").read_text())
                assert verify_fixture(initial, protocol["seed"], size)
                integrity = verify_reconciliation(initial, after, intents, protocol["seed"])
                assert integrity == recorded["integrity"]
                assert recorded["initial_counts"] == {"exceptions": size * 2, "events": size * 20}
                summaries.append({"size": size, "rate": rate, "replicate": rep, **summary})
    active = json.loads((run / "active-budget.json").read_text())
    assert active["used_seconds"] <= protocol["active_budget_seconds"]
    fault = json.loads((run / "fault" / "result.json").read_text())
    assert fault["integrity"]["passed"] and fault["owned_database_interruptions"] == 1
    assert fault["readiness_during_outage"] == 503
    assert fault["reviewer_after_recovery"] == 403
    assert fault["reviewer_during_outage"] >= 400
    assert fault["same_intent_replayed"] is True
    assert fault["active_seconds"] <= protocol["fault_budget_seconds"]
    active_total += fault["active_seconds"]
    assert abs(active_total - active["used_seconds"]) < .01
    assert fault["recovery_target_met"] == (fault["recovery_seconds_after_restart_completed"] <= 60)
    with gzip.open(run / "fault/initial-business.json.gz", "rt", encoding="utf-8") as stream:
        initial = json.load(stream)
    with gzip.open(run / "fault/final-business.json.gz", "rt", encoding="utf-8") as stream:
        after = json.load(stream)
    intents = json.loads((run / "fault/intent-ledger.json").read_text())
    assert verify_fixture(initial, protocol["seed"], 200)
    assert verify_reconciliation(initial, after, intents, protocol["seed"]) == fault["integrity"]
    cleanup = json.loads((run / "cleanup.json").read_text())
    assert cleanup["owned_postgres_stopped"] and cleanup["app_process_returned"]
    return summaries


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps({"passed": True, "trials": len(check(args.run))}))


if __name__ == "__main__":
    main()
