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
        with httpx.Client(base_url=base, trust_env=False) as client:
            html = client.get("/")
            assert html.status_code == 200 and '/assets/' in html.text
            assert "script-src 'self'" in html.headers["content-security-policy"]
            notices = client.get("/third-party-notices")
            assert notices.status_code == 200 and "Meta Platforms" in notices.text
            csrf = client.get("/api/session").json()["csrf_token"]
            session = client.post("/api/login", json={"email": "jules@harbor.example", "password": password},
                                  headers={"Origin": base, "X-CSRF-Token": csrf})
            assert session.status_code == 200, session.text
            headers = {"Origin": base, "X-CSRF-Token": session.json()["csrf_token"], "Idempotency-Key": str(uuid4())}
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
            # Treat the committed response as lost, then start a fresh app process.
            stop(server)
            server = None
            server = start()
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
            assert creation_detail["exception"]["version"] == 1
            assert [event["action"] for event in creation_detail["events"]] == ["created"]
        state = {"base_url": base, "port": port, "pid": server.pid, "demo_password": password,
                 "installed_module": probe, "python": python}
        (cwd / "consumer-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        (cwd / "result.json").write_text(json.dumps({"passed": True, "installed_module": probe,
             "built_ui_served": True, "dependency_notices_served": True,
             "app_process_restart": True, "persistent_session_and_receipt": True,
             "one_committed_effect_after_retry": True, "creation_receipt_after_restart": True,
             "one_creation_event_after_restart_retry": True}, indent=2), encoding="utf-8")
        print("Installed wheel, built UI, API process restart and durable retry accepted.")
        if args.keep_server:
            server = None
    finally:
        if server:
            stop(server)
        log.close()


if __name__ == "__main__":
    main()
