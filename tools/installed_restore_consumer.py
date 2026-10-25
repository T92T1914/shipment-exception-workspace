"""Qualify one trusted local schema-4 round trip, without initializing the target.

Only fresh disposable source/target databases on an explicitly declared owned
PostgreSQL 18.1 cluster are admitted. This script deliberately retains archives,
logs, credentials and failed targets privately. It is not an operational backup
service or a restore command for arbitrary archives.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from psycopg import sql
from psycopg.conninfo import make_conninfo

from local_restore import (FLAGS, Refused, connect, empty_database, fingerprint,
                           guard_restore, identity, native, parameters, restore)


class App:
    def __init__(self, python, params, output):
        self.python, self.params, self.output = str(python), params, output
        self.process = None
        self.log = None
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def start(self):
        self.log = (self.output / "server.log").open("ab")
        env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        env.update(SHIPMENT_DATABASE_URL=make_conninfo(**self.params), PYTHONPATH="",
                   OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2")
        self.process = subprocess.Popen([self.python, "-m", "shipment_workspace.cli", "serve", "--port", str(self.port)],
            cwd=self.output, env=env, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, creationflags=FLAGS)
        for _ in range(100):
            if self.process.poll() is not None:
                raise RuntimeError("Owned installed app exited; inspect its private server.log")
            try:
                with httpx.Client(base_url=self.base, trust_env=False, timeout=1) as client:
                    # A session readiness GET would alter the state under test.
                    if client.get("/").status_code == 200:
                        return self
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.1)
        raise RuntimeError("Owned installed app readiness timed out")

    def stop(self):
        if self.process and self.process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=FLAGS)
            else:
                self.process.terminate()
            self.process.wait(timeout=15)
        if self.log:
            self.log.close()


def signed_in(base, password, email):
    client = httpx.Client(base_url=base, trust_env=False, timeout=10)
    anonymous = client.get("/api/session").json()
    response = client.post("/api/login", json={"email": email, "password": password}, headers={
        "Origin": base, "X-CSRF-Token": anonymous["csrf_token"], "X-Workspace-Context": anonymous["session_context"]})
    assert response.status_code == 200
    current = response.json()
    client.headers.update({"Origin": base, "X-CSRF-Token": current["csrf_token"],
                           "X-Workspace-Context": current["session_context"]})
    return client, current


def business(params):
    state = fingerprint(params)
    return {name: state["tables"][name] for name in ("shipment_exceptions", "exception_events", "mutation_requests")}


def source_fixture(app, password):
    clients = []
    try:
        operator, session = signed_in(app.base, password, "alex@northline.example")
        reviewer, _ = signed_in(app.base, password, "casey@northline.example")
        harbor, _ = signed_in(app.base, password, "jules@harbor.example")
        expired, _ = signed_in(app.base, password, "sam@northline.example")
        clients = [operator, reviewer, harbor, expired]
        key = str(uuid4())
        body = {"reference": "NL-RESTORE-001", "summary": "Preserved synthetic handoff",
                "details": "Created, assigned and resolved before this trusted local backup.", "priority": "high"}
        created = operator.post("/api/exceptions", json=body, headers={"Idempotency-Key": key})
        assert created.status_code == 201
        record = created.json()["exception"]
        assigned = operator.post(f"/api/exceptions/{record['id']}/assign", json={"expected_version": 1, "assignee_id": session["user"]["id"]},
                                 headers={"Idempotency-Key": str(uuid4())})
        assert assigned.status_code == 200
        resolved = operator.post(f"/api/exceptions/{record['id']}/resolve", json={"expected_version": 2, "resolution": "Synthetic receiving handoff confirmed."},
                                 headers={"Idempotency-Key": str(uuid4())})
        assert resolved.status_code == 200
        open_body = {**body, "reference": "NL-RESTORE-OPEN", "summary": "Next valid restored change"}
        opened = operator.post("/api/exceptions", json=open_body, headers={"Idempotency-Key": str(uuid4())})
        assert opened.status_code == 201
        before = operator.get(f"/api/exceptions/{record['id']}").json()
        assert [event["action"] for event in before["events"]] == ["created", "assigned", "resolved"]
        # A declared expired synthetic session tests current expiry after restore.
        expired_cookie = expired.cookies.get("shipment_session")
        with connect(app.params) as conn:
            conn.execute("UPDATE sessions SET expires_at=clock_timestamp()-interval '1 minute' WHERE token_hash=%s",
                         (sha256(expired_cookie.encode()).hexdigest(),))
            # Preserve a real sequence gap, rather than reconstructing from MAX(id).
            gap = conn.execute("SELECT nextval(pg_get_serial_sequence('exception_events','id'))").fetchone()[0]
        return {"record_id": record["id"], "open_id": opened.json()["exception"]["id"],
                "key": key, "body": body, "original_response": created.json(), "detail": before,
                "session": session, "cookie": operator.cookies.get("shipment_session"),
                "expired_cookie": expired_cookie, "sequence_gap": gap}
    finally:
        for client in clients:
            client.close()


def control_state(params):
    with connect(params) as conn:
        result = {
            "relations": conn.execute("SELECT relname,relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY 1,2").fetchall(),
            "functions": conn.execute("SELECT proname,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' ORDER BY 1").fetchall(),
            "types": conn.execute("SELECT typname,typtype FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public' ORDER BY 1").fetchall(),
            "extra_schema": conn.execute("SELECT nspname FROM pg_namespace WHERE nspname='restore_extra'").fetchall(),
            "collations": conn.execute("SELECT collname,collprovider FROM pg_collation c JOIN pg_namespace n ON n.oid=c.collnamespace WHERE n.nspname='public' ORDER BY 1").fetchall(),
            "large_objects": conn.execute("SELECT oid,lomowner,lomacl::text,lo_get(oid) FROM pg_largeobject_metadata ORDER BY oid").fetchall(),
        }
        if ("sentinel", "r") in result["relations"]:
            result["sentinel_rows"] = conn.execute("SELECT id FROM sentinel ORDER BY id").fetchall()
        return result


def negative_controls(pg_bin, source, target, archive, output):
    results = {}
    alias = parameters(make_conninfo(**source), int(source["port"]))
    same_log = output / "refused-same.log"
    try:
        restore(pg_bin, source, alias, archive, same_log)
    except Refused:
        assert not same_log.exists()
        results["same_actual_database_refused_before_tool"] = True
    else:
        raise AssertionError("Same actual database was not refused")
    try:
        parameters(make_conninfo(**{**target, "port": str(int(target["port"]) + 1)}), int(target["port"]))
    except Refused:
        results["unexpected_endpoint_refused_before_connect"] = True
    else:
        raise AssertionError("Unexpected endpoint was not refused")

    def new_control(label):
        name = target["dbname"] + "_" + label
        assert len(name) <= 63
        with connect(source) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} WITH TEMPLATE template0 OWNER {}").format(sql.Identifier(name), sql.Identifier(source["user"])))
        return {**target, "dbname": name}

    for label, statement in (
        ("table", "CREATE TABLE sentinel(id integer PRIMARY KEY)"),
        ("function", "CREATE FUNCTION public.sentinel() RETURNS integer LANGUAGE sql AS 'SELECT 7'"),
        ("type", "CREATE TYPE public.sentinel AS ENUM ('kept')"),
        ("schema", "CREATE SCHEMA restore_extra"),
        ("collation", 'CREATE COLLATION public.sentinel FROM pg_catalog."C"'),
        ("largeobject", "SELECT lo_from_bytea(0,decode('6b657074','hex'))"),
    ):
        params = new_control(label)
        with connect(params) as conn:
            conn.execute(statement)
            if label == "table":
                conn.execute("INSERT INTO sentinel VALUES (7)")
        before = control_state(params)
        log = output / f"refused-nonempty-{label}.log"
        try:
            restore(pg_bin, source, params, archive, log)
        except Refused:
            assert not log.exists() and control_state(params) == before
            results[f"nonempty_{label}_refused_unchanged"] = True
        else:
            raise AssertionError("Nonempty target was not refused")

    truncated = output / "truncated.dump"
    truncated.write_bytes(archive.read_bytes()[:64])
    for label, file in (("missing", output / "missing.dump"), ("truncated", truncated)):
        params = new_control(label)
        before = fingerprint(params, allow_empty=True)
        code, _ = restore(pg_bin, source, params, file, output / f"{label}-restore.log")
        assert code != 0 and fingerprint(params, allow_empty=True) == before
        results[f"{label}_archive"] = {"native_exit": code, "target_unchanged": True}

    toc = output / "archive-toc.list"
    executable = Path(pg_bin) / ("pg_restore.exe" if os.name == "nt" else "pg_restore")
    listing = subprocess.run([str(executable), "--list", str(archive)], check=True,
                             capture_output=True, text=True, creationflags=FLAGS, timeout=30).stdout
    toc.write_text(listing)
    lines = listing.splitlines()
    omitted = [line for line in lines if " TABLE public users " in line and not line.startswith(";")]
    assert len(omitted) == 1 and any("TABLE DATA public users " in line for line in lines)
    broken = output / "deliberately-incomplete-toc.list"
    broken.write_text("\n".join(";" + line if line in omitted else line for line in lines) + "\n")
    params = new_control("atomic")
    before = fingerprint(params, allow_empty=True)
    code, _ = restore(pg_bin, source, params, archive, output / "atomic-restore.log", broken_list=broken)
    assert code != 0 and fingerprint(params, allow_empty=True) == before
    evidence = (output / "atomic-restore.log").read_text(errors="replace")
    assert 'creating TABLE "public.organizations"' in evidence and 'processing data for table "public.' in evidence
    results["deliberate_sql_failure"] = {"native_exit": code, "earlier_ddl_and_data_observed": True,
                                          "transaction_rollback_read_back": True}
    return results


def restored_acceptance(app, password, fixture):
    with connect(app.params) as conn:
        still_valid = conn.execute("SELECT expires_at>clock_timestamp() FROM sessions WHERE token_hash=%s",
                                  (sha256(fixture["cookie"].encode()).hexdigest(),)).fetchone()[0]
    with httpx.Client(base_url=app.base, trust_env=False, cookies={"shipment_session": fixture["cookie"]}) as saved:
        read = saved.get(f"/api/exceptions/{fixture['record_id']}")
        assert read.status_code == (200 if still_valid else 401)
        if still_valid:
            assert read.json() == fixture["detail"]
    with httpx.Client(base_url=app.base, trust_env=False, cookies={"shipment_session": fixture["expired_cookie"]}) as expired:
        assert expired.get("/api/exceptions").status_code == 401

    clients = []
    try:
        operator, current = signed_in(app.base, password, "alex@northline.example")
        reviewer, _ = signed_in(app.base, password, "casey@northline.example")
        harbor, _ = signed_in(app.base, password, "jules@harbor.example")
        clients = [operator, reviewer, harbor]
        path = f"/api/exceptions/{fixture['record_id']}"
        assert operator.get(path).json() == fixture["detail"]
        assert reviewer.get(path).json() == fixture["detail"]
        assert harbor.get(path).status_code == 404
        assert operator.get(path + "/history").json()["events"] == fixture["detail"]["events"]
        before = business(app.params)
        denied = reviewer.post("/api/exceptions", json=fixture["body"], headers={"Idempotency-Key": fixture["key"]})
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "read_only"
        csrf = operator.post("/api/exceptions", json=fixture["body"], headers={"X-CSRF-Token": "wrong", "Idempotency-Key": fixture["key"]})
        assert csrf.status_code == 403 and csrf.json()["error"]["code"] == "csrf_failed"
        replay = operator.post("/api/exceptions", json=fixture["body"], headers={"Idempotency-Key": fixture["key"]})
        assert replay.status_code == 201 and replay.json() == fixture["original_response"]
        assert replay.headers["idempotency-replayed"] == "true" and business(app.params) == before
        saved = operator.post(f"/api/exceptions/{fixture['open_id']}/assign", json={"expected_version": 1, "assignee_id": current["user"]["id"]},
                              headers={"Idempotency-Key": str(uuid4())})
        assert saved.status_code == 200 and saved.json()["exception"]["version"] == 2
        detail = operator.get(f"/api/exceptions/{fixture['open_id']}").json()
        assert detail["events"][-1]["id"] == fixture["sequence_gap"] + 1
        return {"saved_session": "accepted-unexpired" if still_valid else "expired-and-refused",
                "declared_expired_session_refused": True, "current_operator_reviewer_org_and_csrf_checked": True,
                "retained_receipt_replayed_without_business_changes": True,
                "subsequent_write_preserved_sequence_gap_without_collision": True,
                "init_migrate_seed_on_target": False}
    finally:
        for client in clients:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--expected-port", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--keep-server", action="store_true")
    args = parser.parse_args()
    source = parameters(os.environ["SHIPMENT_RESTORE_SOURCE_URL"], args.expected_port)
    target = parameters(os.environ["SHIPMENT_RESTORE_TARGET_URL"], args.expected_port)
    identities = guard_restore(source, target)
    empty_database(source)
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.absolute()
    python = args.python.absolute()
    probe = subprocess.run([str(python), "-c", "import shipment_workspace,sys,json; print(json.dumps({'module':shipment_workspace.__file__,'version':shipment_workspace.__version__,'python':list(sys.version_info[:3])}))"],
                           cwd=output, env={**os.environ, "PYTHONPATH": ""}, check=True, capture_output=True, text=True, creationflags=FLAGS)
    installed = json.loads(probe.stdout)
    assert "site-packages" in installed["module"] and installed["version"] == "0.8.0" and installed["python"] == [3, 13, 3]
    versions = {}
    for name in ("pg_dump", "pg_restore"):
        file = args.pg_bin / (name + (".exe" if os.name == "nt" else ""))
        version = subprocess.run([str(file), "--version"], check=True, capture_output=True, text=True, creationflags=FLAGS).stdout.strip()
        assert version == f"{name} (PostgreSQL) 18.1"
        versions[name] = version
    password = secrets.token_urlsafe(24)
    (output / "demo-password.txt").write_text(password)
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(SHIPMENT_DATABASE_URL=make_conninfo(**source), SHIPMENT_DEMO_PASSWORD=password, PYTHONPATH="")
    for command in ("init", "seed"):
        subprocess.run([str(python), "-m", "shipment_workspace.cli", command], cwd=output, env=env, check=True, creationflags=FLAGS)
    source_dir = output / "source-app"
    target_dir = output / "target-app"
    source_dir.mkdir(); target_dir.mkdir()
    source_app, target_app = App(python, source, source_dir), App(python, target, target_dir)
    try:
        source_app.start()
        fixture = source_fixture(source_app, password)
        (output / "synthetic-acceptance-inputs.json").write_text(json.dumps(fixture, indent=2))
        source_app.stop()
        before = fingerprint(source)
        archive = output / "trusted-workspace.dump"
        assert native(args.pg_bin, "pg_dump", source, ["--format=custom", "--file", archive], output / "dump.log") == 0
        assert fingerprint(source) == before
        controls = negative_controls(args.pg_bin, source, target, archive, output)
        assert fingerprint(source) == before
        code, actual = restore(args.pg_bin, source, target, archive, output / "restore.log")
        assert code == 0
        restored = fingerprint(target)
        assert restored == before  # Before starting an app or creating a session.
        (output / "logical-readback.json").write_text(json.dumps({"source_before": before, "target_before_app": restored}, indent=2, default=str))
        target_app.start()
        accepted = restored_acceptance(target_app, password, fixture)
        assert fingerprint(source) == before
        result = {"passed": True, "installed": installed, "native_versions": versions,
                  "identities": identities, "effective_restore_identities": actual,
                  "source_quiet_before_through_dump_and_target_acceptance": True,
                  "complete_logical_readback_before_target_app": True, "source_fingerprint": before["sha256"],
                  "table_counts": {name: value["count"] for name, value in before["tables"].items()},
                  "archive_sha256": sha256(archive.read_bytes()).hexdigest(), "controls": controls, "restored_consumer": accepted}
        (output / "result.json").write_text(json.dumps(result, indent=2))
        state = {"base_url": target_app.base, "port": target_app.port, "pid": target_app.process.pid,
                 "python": str(python), "demo_password": password, "database_url": make_conninfo(**target),
                 "record_id": fixture["record_id"], "source_database_url": make_conninfo(**source),
                 "source_fingerprint": before["sha256"]}
        (output / "consumer-state.json").write_text(json.dumps(state, indent=2))
        print("Trusted local restore, full logical readback, native failures and installed current-authorization consumer accepted.")
        if args.keep_server:
            target_app = None
    finally:
        source_app.stop()
        if target_app:
            target_app.stop()


if __name__ == "__main__":
    main()
