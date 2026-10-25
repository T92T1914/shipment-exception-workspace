"""Exercise an installed wheel from outside its checkout, including API restart.

This runner starts only its own loopback server, uses a dedicated synthetic
database and saves private state for the subsequent browser journey. It never
starts a visible app. Pass the fresh environment's Python executable.
"""

import argparse
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
import psycopg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keep-server", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    database_url = os.environ["SHIPMENT_DATABASE_URL"]
    password_file = args.output / "demo-password.txt"
    if not password_file.exists():
        password_file.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    password = password_file.read_text(encoding="utf-8")
    env = {**os.environ, "SHIPMENT_DEMO_PASSWORD": password, "PYTHONPATH": ""}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    # POSIX venv executables are often symlinks. Resolving the link selects the
    # base interpreter and loses the installed environment we need to exercise.
    python = str(args.python.absolute())
    cwd = args.output.resolve()
    for command in ("init", "seed"):
        subprocess.run([python, "-m", "shipment_workspace.cli", command], cwd=cwd, env=env, check=True, creationflags=flags)
    probe = subprocess.run([python, "-c", "import shipment_workspace; print(shipment_workspace.__file__)"],
                           cwd=cwd, env=env, check=True, capture_output=True, text=True, creationflags=flags).stdout.strip()
    if "site-packages" not in probe:
        raise AssertionError("Consumer did not import the installed wheel")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = (cwd / "server.log").open("ab")
    server = None

    def start():
        process = subprocess.Popen([python, "-m", "shipment_workspace.cli", "serve", "--port", str(port)],
                                   cwd=cwd, env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Installed server exited. Inspect private server.log")
                try:
                    with httpx.Client(base_url=base, timeout=1, trust_env=False) as client:
                        if client.get("/api/session").status_code == 200:
                            return process
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass
                time.sleep(0.1)
            raise RuntimeError("Installed server did not become ready")
        except BaseException:
            stop(process)
            raise

    def stop(process):
        if os.name == "nt" and process.poll() is None:
            # A venv Python launcher can own a Python child on Windows. Stop
            # this exact process tree, not every Python process on the PC.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=flags)
        elif process.poll() is None:
            process.terminate()
        process.wait(timeout=15)

    try:
        server = start()
        with httpx.Client(base_url=base, trust_env=False) as client, httpx.Client(base_url=base, trust_env=False) as login_client, httpx.Client(base_url=base, trust_env=False) as reviewer:
            html = client.get("/")
            assert html.status_code == 200 and '/assets/' in html.text
            assert "script-src 'self'" in html.headers["content-security-policy"]
            notices = client.get("/third-party-notices")
            assert notices.status_code == 200 and "Meta Platforms" in notices.text
            anonymous = client.get("/api/session").json()
            csrf = anonymous["csrf_token"]
            session = client.post("/api/login", json={"email": "jules@harbor.example", "password": password},
                                  headers={"Origin": base, "X-CSRF-Token": csrf,
                                           "X-Workspace-Context": anonymous["session_context"]})
            assert session.status_code == 200, session.text
            assert session.json()["user"]["role"] == "operator"
            retired_context = session.json()["session_context"]
            original_actor = session.json()["user"]["id"]
            session = client.post("/api/login", json={"email": "jules@harbor.example", "password": password},
                                  headers={"Origin": base, "X-CSRF-Token": session.json()["csrf_token"],
                                           "X-Workspace-Context": retired_context})
            assert session.status_code == 200 and session.json()["user"]["id"] == original_actor
            context = session.json()["session_context"]
            assert len(context) == 64 and context != retired_context
            client.headers["X-Workspace-Context"] = context
            mismatch = client.get("/api/members", headers={"X-Workspace-Context": retired_context})
            assert mismatch.status_code == 409 and mismatch.json()["error"]["code"] == "session_changed"
            assert context not in mismatch.text and retired_context not in mismatch.text
            assert client.get("/api/session", headers={"X-Workspace-Context": retired_context}).json()["session_context"] == context
            with httpx.Client(base_url=base, cookies=client.cookies, trust_env=False) as legacy:
                assert legacy.get("/api/members").status_code == 200
            headers = {"Origin": base, "X-CSRF-Token": session.json()["csrf_token"],
                       "X-Workspace-Context": context, "Idempotency-Key": str(uuid4())}
            queue_params = {"q": "HS-", "status": "all", "limit": 1}
            first_page = client.get("/api/exceptions", params=queue_params).json()
            assert len(first_page["items"]) == 1 and first_page["page_size"] == 1
            assert first_page["items"][0]["reference"] == "HS-2057" and first_page["next_cursor"]
            item = next(x for x in client.get("/api/exceptions").json()["items"] if x["reference"] == "HS-2073")
            body = {"expected_version": item["version"], "assignee_id": session.json()["user"]["id"]}
            path = f"/api/exceptions/{item['id']}/assign"
            first = client.post(path, json=body, headers=headers)
            assert first.status_code == 200, first.text
            create_headers = {**headers, "Idempotency-Key": str(uuid4())}
            create_body = {"reference": "HS-RESTART", "summary": "Restart acceptance",
                           "details": "Synthetic intake persisted across an API restart.", "priority": "normal"}
            created = client.post("/api/exceptions", json=create_body, headers=create_headers)
            assert created.status_code == 201, created.text
            created_id = created.json()["exception"]["id"]
            history_path = f"/api/exceptions/{created_id}/history"
            # These are real accepted mutations, not fabricated legacy events.
            # They exercise the original detail cap and more than two pages.
            for version in range(1, 45):
                saved = client.post(f"/api/exceptions/{created_id}/assign",
                                    json={"expected_version": version,
                                          "assignee_id": session.json()["user"]["id"] if version % 2 else None},
                                    headers={**headers, "Idempotency-Key": str(uuid4())})
                assert saved.status_code == 200 and saved.json()["exception"]["version"] == version + 1
            history_detail = client.get(f"/api/exceptions/{created_id}").json()
            assert history_detail["exception"]["version"] == 45
            assert [event["version"] for event in history_detail["events"]] == list(range(26, 46))
            assert history_detail["history"]["page_size"] == 20
            assert history_detail["history"]["through_version"] == 45
            history_cursor = history_detail["history"]["next_cursor"]
            assert history_cursor
            reviewer_csrf = reviewer.get("/api/session").json()["csrf_token"]
            review_session = reviewer.post("/api/login", json={"email": "taylor@harbor.example", "password": password},
                                           headers={"Origin": base, "X-CSRF-Token": reviewer_csrf})
            assert review_session.status_code == 200 and review_session.json()["user"]["role"] == "reviewer"
            reviewer_context = review_session.json()["session_context"]
            reviewer.headers["X-Workspace-Context"] = reviewer_context
            reviewer_headers = {"Origin": base, "X-CSRF-Token": review_session.json()["csrf_token"],
                                "X-Workspace-Context": reviewer_context}

            def business_rows():
                with psycopg.connect(database_url) as conn:
                    return tuple(conn.execute(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY 1").fetchall()
                                 for table in ("shipment_exceptions", "exception_events", "mutation_requests"))

            def review_without_writes():
                assert reviewer.get("/api/session").json()["user"]["role"] == "reviewer"
                own = reviewer.get(f"/api/exceptions/{created_id}")
                assert own.status_code == 200 and len(own.json()["events"]) == 20
                assert own.json()["history"]["through_version"] == 45
                older = reviewer.get(history_path, params={"cursor": history_cursor})
                assert older.status_code == 200 and older.json()["through_version"] == 45
                assert [event["version"] for event in older.json()["events"]] == list(range(6, 26))
                assert reviewer.get("/api/exceptions", params=queue_params).status_code == 200
                assert reviewer.get("/api/members").status_code == 200
                before = business_rows()
                for target, payload in (("/api/exceptions", {**create_body, "reference": "HS-REVIEWER-DENIED"}),
                                        (path, {"expected_version": item["version"] + 1, "assignee_id": None}),
                                        (f"/api/exceptions/{item['id']}/resolve", {"expected_version": item["version"] + 1, "resolution": "Reviewer denied"})):
                    response = reviewer.post(target, json=payload, headers={**reviewer_headers, "Idempotency-Key": str(uuid4())})
                    assert response.status_code == 403 and response.json()["error"]["code"] == "read_only"
                assert business_rows() == before

            review_without_writes()
            login_csrf = login_client.get("/api/session").json()["csrf_token"]
            login_headers = {"Origin": base, "X-CSRF-Token": login_csrf}
            # Three successful sign-ins charged three admissions. Charge37
            # further verifications without authenticating this separate client.
            for index in range(37):
                subject = "unknown-one@synthetic.example" if index < 20 else "unknown-two@synthetic.example"
                denied = login_client.post("/api/login", json={"email": subject, "password": "Synthetic wrong password"}, headers=login_headers)
                assert denied.status_code == 401, denied.text
            limited = login_client.post("/api/login", json={"email": "unknown-one@synthetic.example", "password": password}, headers=login_headers)
            assert limited.status_code == 429 and 1 <= int(limited.headers["Retry-After"]) <= 60
            with psycopg.connect(database_url) as conn:
                before_admission = conn.execute("SELECT attempts,reset_at FROM login_global").fetchall(), conn.execute("SELECT * FROM login_identifiers ORDER BY identifier_hash").fetchall()
            # Treat the committed response as lost, then start a fresh app process.
            stop(server)
            server = None
            server = start()
            assert client.get("/api/session").json()["session_context"] == context
            assert reviewer.get("/api/session").json()["session_context"] == reviewer_context
            assert client.get("/api/members", headers={"X-Workspace-Context": retired_context}).status_code == 409
            still_limited = login_client.post("/api/login", json={"email": "jules@harbor.example", "password": password}, headers=login_headers)
            assert still_limited.status_code == 429
            assert login_client.get("/api/session").json()["authenticated"] is False
            with psycopg.connect(database_url) as conn:
                after_admission = conn.execute("SELECT attempts,reset_at FROM login_global").fetchall(), conn.execute("SELECT * FROM login_identifiers ORDER BY identifier_hash").fetchall()
            assert after_admission == before_admission
            review_without_writes()
            older_history = client.get(history_path, params={"cursor": history_cursor}).json()
            assert [event["version"] for event in older_history["events"]] == list(range(6, 26))
            assert older_history["page_size"] == 20 and older_history["through_version"] == 45
            oldest_history = client.get(history_path, params={"cursor": older_history["next_cursor"]}).json()
            assert [event["version"] for event in oldest_history["events"]] == list(range(1, 6))
            assert oldest_history["next_cursor"] is None and oldest_history["through_version"] == 45
            history_events = [*oldest_history["events"], *older_history["events"], *history_detail["events"]]
            assert [event["version"] for event in history_events] == list(range(1, 46))
            assert len({event["id"] for event in history_events}) == 45
            assert sum(event["action"] == "created" for event in history_events) == 1
            appended = client.post(f"/api/exceptions/{created_id}/assign",
                                   json={"expected_version": 45, "assignee_id": None},
                                   headers={**headers, "Idempotency-Key": str(uuid4())})
            assert appended.status_code == 200 and appended.json()["exception"]["version"] == 46
            fenced = client.get(history_path, params={"cursor": history_cursor}).json()
            assert fenced == older_history
            refreshed = client.get(f"/api/exceptions/{created_id}").json()
            assert refreshed["history"]["through_version"] == 46
            assert [event["version"] for event in refreshed["events"]] == list(range(27, 47))
            second_page = client.get("/api/exceptions", params={**queue_params, "cursor": first_page["next_cursor"]}).json()
            assert len(second_page["items"]) == 1 and second_page["items"][0]["reference"] == "HS-2073"
            assert second_page["next_cursor"]
            third_page = client.get("/api/exceptions", params={**queue_params, "cursor": second_page["next_cursor"]}).json()
            assert [row["reference"] for row in third_page["items"]] == ["HS-RESTART"]
            assert third_page["next_cursor"] is None
            replay = client.post(path, json=body, headers=headers)
            assert replay.status_code == 200 and replay.json() == first.json()
            assert replay.headers["idempotency-replayed"] == "true"
            detail = client.get(f"/api/exceptions/{item['id']}").json()
            assert detail["exception"]["version"] == item["version"] + 1
            assert len(detail["events"]) == 1
            creation_replay = client.post("/api/exceptions", json=create_body, headers=create_headers)
            assert creation_replay.status_code == 201 and creation_replay.json() == created.json()
            assert creation_replay.headers["idempotency-replayed"] == "true"
            creation_detail = client.get(f"/api/exceptions/{created_id}").json()
            assert creation_detail["exception"]["version"] == 46
            assert creation_detail["history"]["through_version"] == 46
            assert len(creation_detail["events"]) == 20
            # The old creation receipt still describes version1. It is never
            # presented as this record's current version or complete history.
            assert creation_replay.json()["exception"]["version"] == 1
        # Browser journeys are a separate synthetic campaign. Expire only this
        # disposable consumer's admission fixtures, preserving sessions/history.
        with psycopg.connect(database_url) as conn:
            conn.execute("UPDATE login_global SET reset_at=clock_timestamp()-interval '1 second'")
            conn.execute("UPDATE login_identifiers SET reset_at=clock_timestamp()-interval '1 second'")
        state = {"base_url": base, "port": port, "pid": server.pid, "demo_password": password,
                 "installed_module": probe, "python": python}
        (cwd / "consumer-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        (cwd / "result.json").write_text(json.dumps({"passed": True, "installed_module": probe,
             "built_ui_served": True, "dependency_notices_served": True,
             "app_process_restart": True, "persistent_session_and_receipt": True,
             "one_committed_effect_after_retry": True, "creation_receipt_after_restart": True,
             "one_creation_event_after_restart_retry": True, "login_budget_survived_restart": True,
             "correct_password_throttled_at_global_limit": True,
             "admission_fixture_expired_before_browser_campaign": True,
             "queue_cursor_survived_restart": True, "bounded_queue_traversal": True,
             "reviewer_read_and_business_write_denial_survived_restart": True,
             "bounded_detail_and_history_cursor_survived_restart": True,
             "complete_three_page_history_without_duplicates": True,
             "history_append_fenced_until_refresh": True,
             "same_actor_login_rotates_context": True,
             "retired_context_denied_and_legacy_cookie_client_accepted": True,
             "operator_and_reviewer_context_survived_process_restart": True}, indent=2), encoding="utf-8")
        print("Installed wheel, UI, API restart, durable retry, admission, queue pages, reviewer access, bounded history and session context accepted.")
        if args.keep_server:
            server = None
    finally:
        if server:
            stop(server)
        log.close()


if __name__ == "__main__":
    main()
