"""Finite installed-package queue/history study in a new owned local cluster.

Run through capacity_windows.py. No URL argument, remote target, retained state,
cloud action or desktop activity is supported. Raw output contains private
fixture credentials and must remain outside Git. Publish reviewed derivatives.
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import gzip
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import zipfile
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx
import psycopg
from psycopg.rows import dict_row

from capacity_model import digest, identity, plan, trial_summary, verify_reconciliation


FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
ROOT = Path(__file__).resolve().parents[1]


def save(path, data):
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def run(argv, **kwargs):
    if not kwargs.get("capture_output"):
        kwargs.setdefault("stdout", sys.stdout)
        kwargs.setdefault("stderr", sys.stderr)
    return subprocess.run([str(x) for x in argv], stdin=subprocess.DEVNULL,
                          creationflags=FLAGS, check=True, **kwargs)


def local_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "postgresql" or parsed.hostname != "127.0.0.1" or parsed.query or parsed.fragment:
        raise ValueError("Only an owned direct IPv4 loopback database is admitted")
    if not parsed.port or not parsed.username or not parsed.password:
        raise ValueError("Missing dedicated connection identity")
    return parsed


class Study:
    def __init__(self, args):
        self.args = args
        self.root = args.output.resolve()
        control_root = Path(os.environ.get("SHIPMENT_CAPACITY_RESOURCE_ROOT", "")).resolve()
        if not os.environ.get("SHIPMENT_CAPACITY_RESOURCE_ROOT") or not (control_root / "resource-control.json").is_file():
            raise ValueError("Start through the resource supervisor")
        if not self.root.is_relative_to(control_root):
            raise ValueError("Study output must be inside the monitored resource root")
        control = json.loads((control_root / "resource-control.json").read_text())
        if control["status"] != "running" or control["logical_cores"] > 2 or control["memory_limit_bytes"] > 3 * 1024**3:
            raise ValueError("Absent or incompatible resource controls")
        if os.name != "nt":
            raise ValueError("Only the qualified Windows job route is supported")
        from capacity_windows import job_api, require, Limits
        import ctypes as C
        from ctypes import wintypes as W
        k = job_api()
        k.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)]
        k.IsProcessInJob.restype = W.BOOL
        k.OpenJobObjectW.argtypes, k.OpenJobObjectW.restype = [W.DWORD, W.BOOL, W.LPCWSTR], W.HANDLE
        job_name = os.environ.get("SHIPMENT_CAPACITY_JOB_NAME")
        if not job_name or control.get("job_name") != job_name:
            raise ValueError("Missing exact supervisor job identity")
        job = k.OpenJobObjectW(4, False, job_name)
        require(job)
        in_job = W.BOOL()
        require(k.IsProcessInJob(k.GetCurrentProcess(), job, C.byref(in_job)))
        actual = Limits()
        require(k.QueryInformationJobObject(job, 9, C.byref(actual), C.sizeof(actual), None))
        k.CloseHandle.argtypes = [W.HANDLE]
        k.CloseHandle(job)
        if not in_job.value or actual.job_memory != 3 * 1024**3 or actual.basic.affinity.bit_count() > 2 or actual.basic.flags & 0x2000 == 0:
            raise ValueError("The actual process job does not have the declared safeguards")
        self.root.mkdir(exist_ok=False)
        self.protocol = json.loads(args.protocol.read_text())
        frozen = json.loads((ROOT / "tools/capacity-protocol.json").read_text())
        if self.protocol != frozen:
            raise ValueError("This route admits only the reviewed frozen protocol")
        save(self.root / "protocol.json", self.protocol)
        self.seed = self.protocol["seed"]
        self.marker = secrets.token_hex(24)
        self.used = 0.0
        self.state = control_root / "postgres-state"
        self.pg_started = False
        self.server = None
        self.listener_handle = None
        self.app_cleanup = []
        self.password = secrets.token_urlsafe(24)
        self.urls = {}
        self.environment = {**os.environ, "PYTHONPATH": "", "PGOPTIONS": "-c max_parallel_workers_per_gather=0"}
        self.python = str(args.python.absolute())
        self.intents = []
        self.initial = None
        self.trial = None
        self.base = None
        self.run_manifest = {"protocol_sha256": digest(self.protocol),
            "source_head": run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
            "source_diff_sha256": hashlib.sha256(run(["git", "-C", ROOT, "diff", "--binary"], capture_output=True).stdout).hexdigest(),
            "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
            "seed": self.seed, "started_utc": datetime.now(timezone.utc).isoformat(),
            "packages": {x: importlib.metadata.version(x) for x in ("httpx", "psycopg")},
            "python": sys.version, "platform": sys.platform, "server_admission_count": "unknown; no instrumentation added",
            "optional_public_trial": "not executed; no qualified separate HTTPS fixture"}
        self.run_manifest["tool_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "tools").glob("*capacity*.py"))}
        package = importlib.util.find_spec("shipment_workspace")
        if package is None or "site-packages" not in package.origin:
            raise ValueError("The driver must consume the installed wheel, outside source imports")
        if Path(self.python).resolve() != Path(sys.executable).resolve():
            raise ValueError("Application and workload must use the same qualified installed interpreter")
        installation = Path(package.origin).parent.parent
        payload = {}
        with zipfile.ZipFile(args.wheel) as wheel:
            for name in wheel.namelist():
                if name.startswith("shipment_workspace/") and not name.endswith("/"):
                    if ".." in Path(name).parts or (installation / name).read_bytes() != wheel.read(name):
                        raise ValueError("Installed application payload differs from the selected wheel")
                    payload[name] = hashlib.sha256(wheel.read(name)).hexdigest()
        self.run_manifest["installed_payload_sha256"] = payload
        self.run_manifest["installed_import"] = package.origin
        save(self.root / "manifest.json", self.run_manifest)

    def helper(self, action):
        run([self.python, ROOT / "tools/local_postgres.py", action, "--bin", self.args.pg_bin, "--state", self.state],
            env=self.environment)

    def guard(self):
        if not self.pg_started:
            raise RuntimeError("Owned cluster is not active")
        connection = json.loads((self.state / "connection.json").read_text())
        if connection != self.connection:
            raise RuntimeError("Cluster connection identity changed")
        with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=2) as conn:
            endpoint = conn.execute("SELECT current_database() AS db,host(inet_server_addr()) AS host,inet_server_port() AS port,current_setting('data_directory') AS data").fetchone()
            if (endpoint["db"] != self.dbname or endpoint["host"] != "127.0.0.1" or
                endpoint["port"] != connection["port"] or Path(endpoint["data"]).resolve() != (self.state / "data").resolve()):
                raise RuntimeError("Effective cluster/database endpoint mismatch")
            if conn.execute("SELECT marker FROM capacity_run_marker").fetchall() != [{"marker": self.marker}]:
                raise RuntimeError("Missing synthetic run marker")

    def listener_guard(self):
        """Read only this loopback listener's Windows PID and its app ancestry."""
        import ctypes as C
        from ctypes import wintypes as W
        ip = C.WinDLL("iphlpapi", use_last_error=True)
        ip.GetExtendedTcpTable.argtypes = [C.c_void_p, C.POINTER(W.DWORD), W.BOOL, W.ULONG, C.c_int, W.ULONG]
        size = W.DWORD()
        # Ask the API for listeners only, rather than interpreting a separate
        # state field from the all-endpoints table. Keep exact PID/port binding.
        ip.GetExtendedTcpTable(None, C.byref(size), False, 2, 3, 0)
        buffer = C.create_string_buffer(size.value)
        if ip.GetExtendedTcpTable(buffer, C.byref(size), False, 2, 3, 0) != 0:
            raise RuntimeError("Cannot read owned TCP listener")
        class Row(C.Structure):
            _fields_ = [(name, W.DWORD) for name in ("state", "address", "port", "remote", "remote_port", "pid")]
        count = W.DWORD.from_buffer(buffer).value
        matches = []
        observations = []
        target_port = urlsplit(self.base).port
        for n in range(count):
            row = Row.from_buffer(buffer, 4 + C.sizeof(Row) * n)
            if socket.ntohs(row.port & 0xffff) == target_port:
                observations.append({"state": row.state, "address": row.address, "pid": row.pid})
            if socket.ntohs(row.port & 0xffff) == target_port:
                if socket.inet_ntoa(row.address.to_bytes(4, "little")) != "127.0.0.1":
                    raise RuntimeError("Owned application is not loopback-only")
                matches.append(row.pid)
        if len(matches) != 1 or self.server.poll() is not None:
            save(self.trial / "listener-guard-observation.json", {"port": target_port, "observations": observations})
            raise RuntimeError(f"Missing or ambiguous owned listener: {observations}")
        # Windows venv launchers may introduce a Python child. Snapshot only
        # process IDs/parents; no command lines, environment or user windows.
        k = C.WinDLL("kernel32", use_last_error=True)
        class Entry(C.Structure):
            _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("pid", W.DWORD),
                ("heap", C.c_size_t), ("module", W.DWORD), ("threads", W.DWORD),
                ("parent", W.DWORD), ("priority", W.LONG), ("flags", W.DWORD), ("exe", W.WCHAR * 260)]
        k.CreateToolhelp32Snapshot.argtypes, k.CreateToolhelp32Snapshot.restype = [W.DWORD, W.DWORD], W.HANDLE
        k.Process32FirstW.argtypes, k.Process32FirstW.restype = [W.HANDLE, C.POINTER(Entry)], W.BOOL
        k.Process32NextW.argtypes, k.Process32NextW.restype = [W.HANDLE, C.POINTER(Entry)], W.BOOL
        k.CloseHandle.argtypes = [W.HANDLE]
        snapshot = k.CreateToolhelp32Snapshot(2, 0)
        if snapshot == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        parents = {}
        try:
            entry = Entry()
            entry.size = C.sizeof(entry)
            more = k.Process32FirstW(snapshot, C.byref(entry))
            while more:
                parents[entry.pid] = entry.parent
                more = k.Process32NextW(snapshot, C.byref(entry))
        finally:
            k.CloseHandle(snapshot)
        cursor = matches[0]
        for _ in range(10):
            if cursor == self.server.pid:
                if self.listener_handle is None:
                    k.OpenProcess.argtypes, k.OpenProcess.restype = [W.DWORD, W.BOOL, W.DWORD], W.HANDLE
                    self.listener_handle = k.OpenProcess(0x00100001 | 0x1000, False, matches[0])
                    if not self.listener_handle:
                        raise C.WinError(C.get_last_error())
                return matches[0]
            cursor = parents.get(cursor)
        raise RuntimeError(f"TCP listener {matches[0]} is not a descendant of owned launcher {self.server.pid}")

    def start_cluster(self):
        self.helper("start")
        self.pg_started = True
        self.connection = json.loads((self.state / "connection.json").read_text())
        for key in ("test_url", "consumer_url"):
            local_url(self.connection[key])
        parsed = local_url(self.connection["test_url"])
        self.admin_url = urlunsplit(parsed._replace(path="/postgres"))
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute("ALTER SYSTEM SET max_wal_size='128MB'")
            conn.execute("ALTER SYSTEM SET min_wal_size='32MB'")
            conn.execute("SELECT pg_reload_conf()")
        self.run_manifest["postgres"] = run([self.args.pg_bin / "postgres.exe", "--version"], capture_output=True, text=True).stdout.strip()
        self.run_manifest["cluster_system_identifier"] = self.scalar("SELECT system_identifier FROM pg_control_system()", self.admin_url)
        save(self.root / "manifest.json", self.run_manifest)

    def scalar(self, sql, url=None):
        with psycopg.connect(url or self.url) as conn:
            return conn.execute(sql).fetchone()[0]

    def snapshot(self):
        with psycopg.connect(self.url, row_factory=dict_row) as conn:
            return {table: conn.execute(f"SELECT * FROM {table} ORDER BY " +
                    ("organization_id,actor_id,key" if table == "mutation_requests" else "id")).fetchall()
                    for table in ("shipment_exceptions", "exception_events", "mutation_requests")}

    def fresh(self, name, size):
        self.dbname = name
        self.url = urlunsplit(local_url(self.connection["test_url"])._replace(path="/" + name))
        # Name is generated locally, never accepted from a target URL or SQL input.
        from psycopg import sql
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        env = {**self.environment, "SHIPMENT_DATABASE_URL": self.url}
        run([self.python, "-I", "-m", "shipment_workspace.cli", "init"], cwd=self.root, env=env)
        from shipment_workspace.db import PASSWORDS
        hashed = PASSWORDS.hash(self.password)
        exceptions, events = [], []
        for org in (1, 2):
            org_id, operator, other = (identity(self.seed, kind, org) for kind in ("org", "operator", "other"))
            for index in range(size):
                ident = identity(self.seed, "exception", org, index)
                base = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index)
                exceptions.append((ident, org_id, f"SYN-{index:05d}_!%", f"Synthetic queue record {index:05d}",
                    "Disposable capacity fixture.", "high" if index % 3 == 0 else "normal", "open", other, 10,
                    base + timedelta(milliseconds=10)))
                for version in range(1, 11):
                    events.append((org_id, ident, operator, "created" if version == 1 else "assigned",
                                   None if version % 2 else other, version, base + timedelta(milliseconds=version)))
        with psycopg.connect(self.url) as conn:
            conn.execute("CREATE TABLE capacity_run_marker(marker text PRIMARY KEY)")
            conn.execute("INSERT INTO capacity_run_marker VALUES (%s)", (self.marker,))
            for org in (1, 2):
                oid = identity(self.seed, "org", org)
                conn.execute("INSERT INTO organizations VALUES (%s,%s)", (oid, f"Capacity organization {org}"))
                for kind, role in (("operator", "operator"), ("other", "operator"), ("reviewer", "reviewer")):
                    conn.execute("INSERT INTO users(id,organization_id,email,name,password_hash,role) VALUES (%s,%s,%s,%s,%s,%s)",
                        (identity(self.seed, kind, org), oid, f"{kind}{org}@capacity.example", f"Capacity {kind} {org}", hashed, role))
            with conn.cursor().copy("COPY shipment_exceptions(id,organization_id,reference,summary,details,priority,status,assignee_id,version,updated_at) FROM STDIN") as copy:
                for row in exceptions:
                    copy.write_row(row)
            with conn.cursor().copy("COPY exception_events(organization_id,exception_id,actor_id,action,assignee_id,version,created_at) FROM STDIN") as copy:
                for row in events:
                    copy.write_row(row)
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute("ANALYZE")
        self.guard()
        self.initial = self.snapshot()
        with gzip.open(self.trial / "initial-business.json.gz", "wt", encoding="utf-8") as stream:
            json.dump(self.initial, stream, default=str, sort_keys=True)
        assert len(self.initial["shipment_exceptions"]) == size * 2
        assert len(self.initial["exception_events"]) == size * 20
        self.intents = []
        save(self.trial / "fixture.json", {"seed": self.seed, "exceptions_per_org": size,
            "exceptions": size * 2, "events": size * 20, "initial_business_sha256": digest(self.initial),
            "database_bytes": self.scalar("SELECT pg_database_size(current_database())")})

    def start_app(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        self.log = (self.trial / "server.log").open("wb")
        self.server = subprocess.Popen([self.python, "-I", "-m", "shipment_workspace.cli", "serve", "--port", str(port)],
            cwd=self.root, env={**self.environment, "SHIPMENT_DATABASE_URL": self.url},
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, creationflags=FLAGS)
        save(self.trial / "server-identity.json", {"launcher_pid": self.server.pid, "port": port,
                                                  "base": self.base})
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=1) as client:
            last_error = None
            for _ in range(200):
                if self.server.poll() is not None:
                    raise RuntimeError("Owned server exited; inspect its private log")
                try:
                    self.listener_guard()
                    if client.get(self.base + "/api/ready").status_code == 200:
                        return
                except (httpx.TransportError, RuntimeError) as exc:
                    last_error = str(exc)
                time.sleep(.1)
        raise RuntimeError(f"Owned server did not become ready: {last_error}")

    def stop_app(self):
        if self.server is not None:
            if self.listener_handle is not None:
                import ctypes as C
                from ctypes import wintypes as W
                k = C.WinDLL("kernel32", use_last_error=True)
                k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [W.HANDLE, W.DWORD], W.DWORD
                k.TerminateProcess.argtypes, k.TerminateProcess.restype = [W.HANDLE, W.UINT], W.BOOL
                k.CloseHandle.argtypes = [W.HANDLE]
                if k.WaitForSingleObject(self.listener_handle, 0) == 258:
                    if not k.TerminateProcess(self.listener_handle, 0):
                        raise C.WinError(C.get_last_error())
                if k.WaitForSingleObject(self.listener_handle, 15000) != 0:
                    raise RuntimeError("Owned application process did not terminate")
                k.CloseHandle(self.listener_handle)
                self.listener_handle = None
            if self.server.poll() is None:
                self.server.terminate()
            self.server.wait(timeout=15)
            self.app_cleanup.append({"launcher_pid": self.server.pid, "return_code": self.server.returncode,
                                     "owned_tree_stop_completed": True})
            self.server = None
            self.log.close()

    def plans(self):
        """Capture real query shapes outside timed HTTP traffic."""
        from shipment_workspace.queue_browsing import page_for as queue_page
        from shipment_workspace.history_browsing import page_for as history_page
        from starlette.datastructures import QueryParams
        captured = []
        with psycopg.connect(self.url, row_factory=dict_row) as conn:
            class Recorder:
                def execute(self, query, parameters):
                    observed = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, parameters).fetchone()
                    captured.append({"query": query, "synthetic_parameters": parameters, "plan": observed["QUERY PLAN"]})
                    return conn.execute(query, parameters)
            recorder = Recorder()
            org = UUID(identity(self.seed, "org", 1))
            page = queue_page(recorder, org, QueryParams({"limit": "20"}))
            queue_page(recorder, org, QueryParams({"limit": "20", "cursor": page["next_cursor"]}))
            for query in ("_!%", "000"):
                queue_page(recorder, org, QueryParams({"limit": "20", "status": "open", "q": query}))
            ident = UUID(identity(self.seed, "exception", 1, 0))
            page = history_page(recorder, org, ident, 10, QueryParams({"limit": "5"}))
            history_page(recorder, org, ident, 10, QueryParams({"limit": "5", "cursor": page["next_cursor"]}))
        save(self.trial / "diagnostic-plans.json", {"instrumented_outside_http_trials": True, "queries": captured})

    def login(self, org, kind="operator"):
        self.listener_guard()
        client = httpx.Client(base_url=self.base, trust_env=False, follow_redirects=False, timeout=12)
        anonymous = client.get("/api/session").json()
        response = client.post("/api/login", json={"email": f"{kind}{org}@capacity.example", "password": self.password},
            headers={"Origin": self.base, "X-CSRF-Token": anonymous["csrf_token"], "X-Workspace-Context": anonymous["session_context"]})
        assert response.status_code == 200
        session = response.json()
        assert session["user"]["id"] == identity(self.seed, kind, org)
        client.headers.update({"Origin": self.base, "X-CSRF-Token": session["csrf_token"],
                               "X-Workspace-Context": session["session_context"]})
        return client

    def intent(self, org, index, tag, version=10, assignee=None):
        item = {"org": org, "index": index, "key": identity(self.seed, tag, org, index),
            "id": identity(self.seed, "exception", org, index),
            "body": {"expected_version": version,
                     "assignee_id": assignee or identity(self.seed, "operator", org)}}
        item["fingerprint"] = digest({"action": "assigned", "exception_id": item["id"], **item["body"]})
        self.intents.append(item)
        return item

    @staticmethod
    def mutate(client, intent):
        return client.post(f"/api/exceptions/{intent['id']}/assign", json=intent["body"],
                           headers={"Idempotency-Key": intent["key"]})

    def reconcile(self):
        self.guard()
        after = self.snapshot()
        with gzip.open(self.trial / "final-business.json.gz", "wt", encoding="utf-8") as stream:
            json.dump(after, stream, default=str, sort_keys=True)
        save(self.trial / "intent-ledger.json", self.intents)
        return verify_reconciliation(self.initial, after, self.intents, self.seed)

    def boundaries(self, clients):
        for org, client in clients.items():
            foreign = identity(self.seed, "exception", 3 - org, 0)
            assert client.get(f"/api/exceptions/{foreign}").status_code == 404
            assert client.get(f"/api/exceptions/{foreign}/history", params={"limit": 5}).status_code == 404
            ids, cursor = [], None
            while True:
                params = {"limit": 50}
                if cursor:
                    params["cursor"] = cursor
                response = client.get("/api/exceptions", params=params)
                assert response.status_code == 200
                page = response.json()
                ids.extend(row["id"] for row in page["items"])
                cursor = page["next_cursor"]
                if not cursor:
                    break
            expected = [str(row["id"]) for row in sorted(self.initial["shipment_exceptions"], key=lambda r: (r["reference"].encode(), str(r["id"])))
                        if str(row["organization_id"]) == identity(self.seed, "org", org)]
            assert ids == expected and len(set(ids)) == len(ids)

    async def arrivals(self, rate, clients):
        protocol = self.protocol
        schedule = plan(protocol, rate)
        intents = {row["slot"]: self.intent(row["org"], row["object_index"], self.trial.name)
                   for row in schedule if row["route"] == "assign"}
        save(self.trial / "intent-ledger.json", self.intents)
        save(self.trial / "schedule.json", schedule)
        async_clients = {org: httpx.AsyncClient(base_url=self.base, cookies=client.cookies, headers=client.headers,
            timeout=protocol["request_timeout_seconds"], follow_redirects=False, trust_env=False,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8)) for org, client in clients.items()}
        deep = {}
        for org, client in clients.items():
            response = client.get(f"/api/exceptions/{identity(self.seed, 'exception', org, 0)}/history", params={"limit": 5})
            assert response.status_code == 200
            assert [event["version"] for event in response.json()["events"]] == [6, 7, 8, 9, 10]
            deep[org] = response.json()["next_cursor"]
        rows, pending = [], set()
        expected_queue = {}
        expected_records = {str(record["id"]): record for record in self.initial["shipment_exceptions"]}
        expected_history = {(org, event["version"]): event for org in (1, 2)
            for event in self.initial["exception_events"]
            if str(event["exception_id"]) == identity(self.seed, "exception", org, 0)}
        for org in (1, 2):
            for query in (None, "_!%", "000"):
                expected_queue[org, query] = [str(record["id"]) for record in sorted(self.initial["shipment_exceptions"], key=lambda r: (r["reference"].encode(), str(r["id"])))
                    if str(record["organization_id"]) == identity(self.seed, "org", org) and
                    (query is None or query.lower() in record["reference"].lower() or query.lower() in record["summary"].lower())][:20]
        start = time.perf_counter()
        timing = {"started_monotonic": start, "started_utc": datetime.now(timezone.utc).isoformat(),
                  "warmup_ends_relative": 30, "measurement_ends_relative": 90}
        save(self.trial / "timing.json", timing)
        self.active_begin(103)
        log = (self.trial / "requests.jsonl").open("w", encoding="utf-8")

        async def request(item):
            row = {**item, "dispatched": time.perf_counter() - start}
            route, org = item["route"], item["org"]
            client = async_clients[org]
            try:
                if route.startswith("queue"):
                    params = {"limit": protocol["queue_limit"]}
                    if route == "queue_filtered":
                        params.update(q=item["filter"], status="open")
                    response = await client.get("/api/exceptions", params=params)
                elif route.startswith("history"):
                    params = {"limit": 5}
                    if route == "history_deep":
                        params["cursor"] = deep[org]
                    response = await client.get(f"/api/exceptions/{identity(self.seed, 'exception', org, 0)}/history", params=params)
                else:
                    intent = intents[item["slot"]]
                    intent["dispatched"] = True
                    response = await client.post(f"/api/exceptions/{intent['id']}/assign", json=intent["body"],
                                                 headers={"Idempotency-Key": intent["key"]})
                row.update(status=response.status_code, completed=time.perf_counter() - start)
                row["category"] = "refused" if response.status_code in (429, 503) else "failed"
                if route == "assign":
                    intent["observed_status"] = response.status_code
                if response.status_code == 200:
                    payload = response.json()
                    if route.startswith("queue"):
                        expected = expected_queue[org, None if route == "queue_all" else item["filter"]]
                        assert [r["id"] for r in payload["items"]] == expected
                        for record in payload["items"]:
                            initial = expected_records[record["id"]]
                            for key in ("id", "reference", "summary", "details", "status", "priority", "resolution"):
                                assert str(record[key]) == str(initial[key])
                            assert record["version"] in (10, 11)
                            kind = "other" if record["version"] == 10 else "operator"
                            assert record["assignee_id"] == identity(self.seed, kind, org)
                            assert record["assignee_name"] == f"Capacity {kind} {org}"
                            assert datetime.fromisoformat(record["updated_at"]) >= initial["updated_at"]
                    elif route.startswith("history"):
                        assert payload["through_version"] == 10
                        assert [e["version"] for e in payload["events"]] == ([1, 2, 3, 4, 5] if route == "history_deep" else [6, 7, 8, 9, 10])
                        for event in payload["events"]:
                            expected = expected_history[org, event["version"]]
                            for key in ("id", "action", "version", "note"):
                                assert event[key] == expected[key]
                            assert event["actor_name"] == f"Capacity operator {org}"
                            assert event["assignee_name"] == (f"Capacity other {org}" if event["version"] % 2 == 0 else None)
                            assert datetime.fromisoformat(event["created_at"]) == expected["created_at"]
                    else:
                        intent["response"] = payload
                        assert payload["exception"]["id"] == intent["id"] and payload["exception"]["version"] == 11
                        assert response.headers.get("Idempotency-Replayed") == "false"
                    row.update(category="successful", validated=True)
            except (Exception, asyncio.CancelledError) as exc:
                row.update(category="failed", completed=time.perf_counter() - start,
                           error=type(exc).__name__)
            rows.append(row)
            log.write(json.dumps(row) + "\n")
            log.flush()

        try:
            for item in schedule:
                await asyncio.sleep(max(0, start + item["scheduled"] - time.perf_counter()))
                pending = {task for task in pending if not task.done()}
                delay = time.perf_counter() - start - item["scheduled"]
                if len(pending) >= protocol["max_in_flight"] or delay > protocol["late_dispatch_drop_seconds"]:
                    row = {**item, "category": "dropped", "reason": "in_flight_cap" if len(pending) >= protocol["max_in_flight"] else "generator_late"}
                    rows.append(row)
                    log.write(json.dumps(row) + "\n")
                    log.flush()
                else:
                    async def bounded(item=item):
                        async with asyncio.timeout(protocol["request_timeout_seconds"]):
                            await request(item)
                    pending.add(asyncio.create_task(bounded()))
            await asyncio.sleep(max(0, start + 90 - time.perf_counter()))
            if pending:
                await asyncio.wait_for(asyncio.gather(*pending), timeout=12.1)
            return rows, time.perf_counter() - start
        finally:
            end = time.perf_counter()
            timing.update(finished_monotonic=end, finished_utc=datetime.now(timezone.utc).isoformat(),
                          active_seconds=end - start)
            save(self.trial / "timing.json", timing)
            self.charge(end - start, self.trial.name)
            for client in async_clients.values():
                await client.aclose()
            log.close()

    def charge(self, seconds, phase):
        self.used += seconds
        save(self.root / "active-budget.json", {"used_seconds": self.used, "last_phase": phase,
                                               "limit_seconds": self.protocol["active_budget_seconds"]})
        save(self.root / "active-phase.json", {"running": False})
        if self.used > self.protocol["active_budget_seconds"]:
            raise RuntimeError("Active study budget exceeded; no further work admitted")

    def active_begin(self, limit):
        save(self.root / "active-phase.json", {"running": True, "started_monotonic": time.perf_counter(),
             "previous_seconds": self.used, "phase_limit_seconds": limit})

    def baseline(self):
        for size in self.protocol["exceptions_per_org"]:
            for rate in self.protocol["rates"]:
                for rep in range(self.protocol["replicates"]):
                    if self.used + 102 + self.protocol["fault_budget_seconds"] > self.protocol["active_budget_seconds"]:
                        raise RuntimeError("Insufficient remaining active budget for another trial and fault reserve")
                    name = f"n{size}-r{rate}-rep{rep}"
                    self.trial = self.root / name
                    self.trial.mkdir()
                    self.fresh(f"capacity_{size}_{rate}_{rep}", size)
                    self.start_app()
                    clients = {org: self.login(org) for org in (1, 2)}
                    try:
                        self.boundaries(clients)
                        if rate == 1 and rep == 0:
                            self.plans()
                        self.guard()
                        self.listener_guard()
                        rows, elapsed = asyncio.run(self.arrivals(rate, clients))
                        integrity = self.reconcile()
                        result = {"name": name, "active_seconds": elapsed, "summary": trial_summary(rows, self.protocol),
                                  "initial_counts": {"exceptions": size * 2, "events": size * 20}, "integrity": integrity}
                        save(self.trial / "result.json", result)
                        print(json.dumps({"trial": name, "active_seconds": elapsed,
                                          "result": result["summary"]["aggregate"], "integrity": integrity["passed"]}), flush=True)
                    finally:
                        for client in clients.values():
                            client.close()
                        self.stop_app()

    def fault(self):
        self.trial = self.root / "fault"
        self.trial.mkdir()
        self.fresh("capacity_fault", 200)
        self.start_app()
        operator, reviewer = self.login(1), self.login(1, "reviewer")
        started = time.perf_counter()
        self.active_begin(self.protocol["fault_budget_seconds"])
        timeline = []
        result = {"owned_database_interruptions": 0}
        try:
            def mark(event):
                timeline.append({"event": event, "elapsed": time.perf_counter() - started,
                                 "utc": datetime.now(timezone.utc).isoformat()})

            intent = self.intent(1, 1, "fault-original")
            intent["dispatched"] = True
            save(self.trial / "intent-ledger.json", self.intents)
            # Synthetic lost-response boundary: the harness receives a committed
            # response and withholds it from its logical caller. Not a network failure.
            response = self.mutate(operator, intent)
            assert response.status_code == 200
            held = response.json()
            intent.update(observed_status=200, response=held)
            mark("committed_response_withheld_from_logical_caller")
            before = self.snapshot()
            self.guard()
            self.listener_guard()
            self.helper("stop")
            self.pg_started = False
            result["owned_database_interruptions"] += 1
            mark("owned_database_stop_completed")
            unavailable = operator.get("/api/ready")
            result["readiness_during_outage"] = unavailable.status_code
            assert unavailable.status_code == 503 and unavailable.json() == {"ready": False}
            denied = self.mutate(reviewer, intent)
            result["reviewer_during_outage"] = denied.status_code
            assert denied.status_code >= 400 and "Idempotency-Replayed" not in denied.headers
            mark("outage_probes_completed")
            self.helper("restart")
            self.pg_started = True
            restarted = time.perf_counter()
            mark("owned_database_restart_completed")
            recovered = False
            while time.perf_counter() - started < 240:
                try:
                    ready = operator.get("/api/ready")
                    queue = operator.get("/api/exceptions")
                    if ready.status_code == 200 and ready.json() == {"ready": True} and queue.status_code == 200:
                        recovered = True
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            result["recovery_seconds_after_restart_completed"] = time.perf_counter() - restarted
            result["recovery_target_met"] = recovered and result["recovery_seconds_after_restart_completed"] <= 60
            save(self.trial / "recovery-observation.json", {**result, "timeline": timeline})
            if not recovered:
                raise RuntimeError("Recovery unavailable within the bounded fault reconciliation window")
            mark("readiness_and_authenticated_queue_succeeded")
            replay = self.mutate(operator, intent)
            assert replay.status_code == 200 and replay.headers.get("Idempotency-Replayed") == "true" and replay.json() == held
            assert self.snapshot() == before
            result["same_intent_replayed"] = True
            denied = self.mutate(reviewer, intent)
            result["reviewer_after_recovery"] = denied.status_code
            assert denied.status_code == 403 and denied.json()["error"]["code"] == "read_only"
            assert "Idempotency-Replayed" not in denied.headers and self.snapshot() == before
            conflict = operator.post(f"/api/exceptions/{intent['id']}/assign",
                json={**intent["body"], "assignee_id": None}, headers={"Idempotency-Key": intent["key"]})
            assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
            assert self.snapshot() == before
            stale = self.intent(1, 1, "fault-stale")
            stale["dispatched"] = True
            refused = self.mutate(operator, stale)
            assert refused.status_code == 409 and refused.json()["error"]["code"] == "version_conflict"
            stale.update(observed_status=409, response=refused.json())
            # Append after capturing a version fence, then traverse the old fence.
            first = operator.get(f"/api/exceptions/{intent['id']}/history", params={"limit": 5}).json()
            later = self.intent(1, 1, "fault-later", version=11)
            later["dispatched"] = True
            changed = self.mutate(operator, later)
            assert changed.status_code == 200
            later.update(observed_status=200, response=changed.json())
            versions = [event["version"] for event in first["events"]]
            cursor = first["next_cursor"]
            while cursor:
                page = operator.get(f"/api/exceptions/{intent['id']}/history", params={"limit": 5, "cursor": cursor}).json()
                assert page["through_version"] == 11
                versions = [event["version"] for event in page["events"]] + versions
                cursor = page["next_cursor"]
            assert versions == list(range(1, 12))
            fresh = operator.get(f"/api/exceptions/{intent['id']}/history", params={"limit": 5}).json()
            assert fresh["through_version"] == 12
            result["history_fence_preserved"] = True
            result["integrity"] = self.reconcile()
            mark("receipt_audit_business_reconciliation_completed")
            result.update(passed=True, timeline=timeline, lost_response_boundary="synthetic committed response withheld by harness, not transport loss")
            save(self.trial / "intent-ledger.json", self.intents)
            save(self.trial / "result.json", result)
        finally:
            elapsed = time.perf_counter() - started
            self.charge(elapsed, "fault")
            if elapsed > self.protocol["fault_budget_seconds"]:
                save(self.trial / "fault-budget-exceeded.json", {"elapsed": elapsed})
            result.update(timeline=timeline, active_seconds=elapsed)
            save(self.trial / "result.json", result)
            operator.close()
            reviewer.close()
            self.stop_app()

    def execute(self):
        try:
            self.start_cluster()
            self.baseline()
            self.fault()
        finally:
            self.stop_app()
            status_code = None
            if (self.state / "connection.json").exists():
                status = subprocess.run([str(self.args.pg_bin / "pg_ctl.exe"), "-D", str(self.state / "data"), "status"],
                    stdin=subprocess.DEVNULL, capture_output=True, creationflags=FLAGS)
                if status.returncode == 0:
                    self.helper("stop")
                status = subprocess.run([str(self.args.pg_bin / "pg_ctl.exe"), "-D", str(self.state / "data"), "status"],
                    stdin=subprocess.DEVNULL, capture_output=True, creationflags=FLAGS)
                status_code = status.returncode
                if status_code != 3 or (self.state / "data/postmaster.pid").exists():
                    raise RuntimeError("Owned PostgreSQL stop is not verified")
                self.pg_started = False
            save(self.root / "cleanup.json", {"app_process_returned": self.server is None,
                "app_trees": self.app_cleanup, "owned_postgres_stopped": status_code == 3,
                "postgres_status_exit": status_code, "postmaster_pid_file_absent": not (self.state / "data/postmaster.pid").exists(),
                "retained_databases_used": False,
                "cloud_actions": 0, "finished_utc": datetime.now(timezone.utc).isoformat()})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--python", type=Path, required=True)
    p.add_argument("--wheel", type=Path, required=True)
    p.add_argument("--pg-bin", type=Path, required=True)
    args = p.parse_args()
    Study(args).execute()


if __name__ == "__main__":
    main()
