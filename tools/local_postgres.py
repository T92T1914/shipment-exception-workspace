"""Own a disposable loopback PostgreSQL cluster without touching installed services.

Supply an empty evidence directory and a PostgreSQL bin directory. State includes
a generated password and must stay outside the checkout. This is local test
support, not a database deployment tool.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile


def run(argv, **kwargs):
    # PostgreSQL children can inherit a capture pipe on Windows and keep it open
    # after pg_ctl exits. A file avoids waiting for an unrelated pipe EOF.
    with tempfile.TemporaryFile() as log:
        result = subprocess.run([str(item) for item in argv], stdout=log, stderr=log,
                                stdin=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                **kwargs)
        log.seek(0)
        output = log.read().decode("utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{Path(argv[0]).name} failed ({result.returncode}): {output}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart"))
    parser.add_argument("--bin", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    state = args.state.resolve()
    data, record = state / "data", state / "connection.json"
    if args.action in ("stop", "restart"):
        if not record.is_file() or not (data / "PG_VERSION").is_file():
            parser.error("No owned initialized cluster at this state path")
        command = [args.bin / "pg_ctl", "-D", data, "-m", "fast", "-w"]
        if args.action == "restart":
            command += ["-l", state / "postgres.log"]
        run([*command, args.action])
        print(f"Owned local PostgreSQL cluster {args.action} completed.")
        return
    if record.exists() or data.exists():
        parser.error("State already exists. Resume its cluster explicitly rather than overwriting credentials")
    state.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    password = secrets.token_urlsafe(32)
    password_file = state / "init-password.txt"
    password_file.write_text(password, encoding="utf-8")
    try:
        run([args.bin / "initdb", "-D", data, "-U", "shipment_owner", "--pwfile", password_file,
             "--auth-host=scram-sha-256", "--auth-local=scram-sha-256", "--encoding=UTF8", "--locale=C"])
    finally:
        password_file.unlink(missing_ok=True)
    with (data / "postgresql.conf").open("a", encoding="utf-8") as out:
        out.write(f"\nlisten_addresses='127.0.0.1'\nport={port}\nshared_buffers='32MB'\nmax_connections=16\nwork_mem='1MB'\nmax_parallel_workers=0\nmax_parallel_workers_per_gather=0\nmax_worker_processes=2\n")
    record.write_text(json.dumps({"port": port, "test_url": f"postgresql://shipment_owner:{password}@127.0.0.1:{port}/shipment_test",
                                 "consumer_url": f"postgresql://shipment_owner:{password}@127.0.0.1:{port}/shipment_consumer"}, indent=2), encoding="utf-8")
    run([args.bin / "pg_ctl", "-D", data, "-l", state / "postgres.log", "-w", "start"])
    env = {**os.environ, "PGPASSWORD": password}
    run([args.bin / "createdb", "-h", "127.0.0.1", "-p", port, "-U", "shipment_owner", "shipment_test"], env=env)
    run([args.bin / "createdb", "-h", "127.0.0.1", "-p", port, "-U", "shipment_owner", "shipment_consumer"], env=env)
    print(f"Owned PostgreSQL cluster ready on loopback port {port}. Private connection record: {record}")


if __name__ == "__main__":
    main()
