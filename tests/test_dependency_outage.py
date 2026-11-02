"""Documented faults at real request boundaries, separate from native stop/restart."""

from contextlib import contextmanager
import errno
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
from psycopg.pq import ConnStatus
from psycopg.rows import dict_row
import pytest

from conftest import authenticated_client
import shipment_workspace.app as app_module
from shipment_workspace import availability as av


def business_state(url):
    with psycopg.connect(url, row_factory=dict_row) as conn:
        return {name: conn.execute(f"SELECT * FROM {name} ORDER BY {order}").fetchall()
                for name, order in (("shipment_exceptions", "id"), ("exception_events", "id"),
                                    ("mutation_requests", "organization_id,actor_id,key"))}


def assert_unavailable(response):
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert "private diagnostic" not in response.text
    assert "Retry-After" not in response.headers
    assert "Idempotency-Replayed" not in response.headers
    assert "no-store" in response.headers["cache-control"]
    assert set(response.json()) == {"error"}


def inject_query(monkeypatch, fragment, failure):
    original = psycopg.Connection.execute

    def execute(conn, query, *args, **kwargs):
        if fragment in str(query):
            raise failure("private diagnostic: password=hidden SQL /internal/path")
        return original(conn, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", execute)


@pytest.mark.parametrize("failure", [psycopg.errors.AdminShutdown, psycopg.errors.CrashShutdown,
                                    psycopg.errors.CannotConnectNow, psycopg.errors.ConnectionFailure])
def test_session_failure_is_unavailable_without_protected_data(northline, database, monkeypatch, failure):
    client, _ = northline
    before = business_state(database)
    with monkeypatch.context() as m:
        inject_query(m, "FROM sessions s", failure)
        for path in ("/api/session", "/api/exceptions", "/api/members"):
            result = client.get(path)
            assert_unavailable(result)
            assert "change" not in result.json()["error"]["message"].lower()
            assert "Northline" not in result.text
    assert business_state(database) == before


@pytest.mark.parametrize("failure", [RuntimeError, psycopg.OperationalError, psycopg.InterfaceError,
                                    psycopg.DatabaseError, psycopg.errors.UndefinedTable,
                                    psycopg.errors.UniqueViolation, psycopg.errors.InvalidPassword,
                                    psycopg.errors.QueryCanceled, psycopg.errors.DeadlockDetected,
                                    psycopg.errors.SerializationFailure, psycopg.errors.ProtocolViolation])
def test_unexpected_read_failure_is_still_sanitized_500(northline, monkeypatch, failure):
    client, _ = northline
    inject_query(monkeypatch, "FROM sessions s", failure)
    result = client.get("/api/exceptions")
    assert result.status_code == 500
    assert result.json()["error"]["code"] == "internal_error"
    assert "change" not in result.json()["error"]["message"].lower()
    assert "private diagnostic" not in result.text
    assert "Retry-After" not in result.headers
    assert "no-store" in result.headers["cache-control"]


@pytest.mark.parametrize("fragment", ["UPDATE shipment_exceptions", "INSERT INTO exception_events"])
def test_failure_before_write_or_after_write_rolls_back_all_business(northline, database, monkeypatch, fragment):
    client, headers = northline
    before = business_state(database)
    body = {"expected_version": 1, "assignee_id": str(UUID(int=12))}
    key = str(uuid4())
    with monkeypatch.context() as m:
        inject_query(m, fragment, psycopg.errors.AdminShutdown)
        result = client.post(f"/api/exceptions/{UUID(int=101)}/assign", json=body,
                             headers={**headers, "Idempotency-Key": key})
        assert_unavailable(result)
        assert "may already be saved" in result.json()["error"]["message"]
    assert business_state(database) == before
    retry = client.post(f"/api/exceptions/{UUID(int=101)}/assign", json=body,
                        headers={**headers, "Idempotency-Key": key})
    assert retry.status_code == 200 and retry.headers["Idempotency-Replayed"] == "false"


def test_reviewer_outage_cannot_be_role_denial_then_recovers(app, database, monkeypatch):
    with authenticated_client(app, "casey@northline.example") as (client, headers):
        before = business_state(database)
        body = {"expected_version": 1, "assignee_id": None}
        headers = {**headers, "Idempotency-Key": str(uuid4())}
        with monkeypatch.context() as m:
            inject_query(m, "FROM sessions s", psycopg.errors.AdminShutdown)
            assert_unavailable(client.post(f"/api/exceptions/{UUID(int=101)}/assign", json=body, headers=headers))
        denied = client.post(f"/api/exceptions/{UUID(int=101)}/assign", json=body, headers=headers)
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "read_only"
        assert business_state(database) == before


def test_committed_acknowledgement_failure_preserves_receipt_and_current_authority(
        app, northline, harbor, database, monkeypatch):
    client, headers = northline
    item, actor = UUID(int=101), UUID(int=11)
    route = f"/api/exceptions/{item}/assign"
    body = {"expected_version": 1, "assignee_id": str(UUID(int=12))}
    headers = {**headers, "Idempotency-Key": str(uuid4())}
    before = business_state(database)
    real_connect = app_module.connect

    class CommitFault:
        def __init__(self, connection):
            self.connection, self.saved = connection, False

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, query, *args, **kwargs):
            value = self.connection.execute(query, *args, **kwargs)
            if "UPDATE mutation_requests SET status_code" in str(query):
                self.saved = True
            return value

        @contextmanager
        def transaction(self):
            with self.connection.transaction():
                yield
            if self.saved:
                # The actual commit succeeded. Withhold its acknowledgement by
                # injecting the documented error at the transaction boundary.
                raise psycopg.errors.ConnectionFailure("private diagnostic at commit acknowledgement")

    @contextmanager
    def fault_connection(url):
        with real_connect(url) as conn:
            yield CommitFault(conn)

    with monkeypatch.context() as m:
        m.setattr(app_module, "connect", fault_connection)
        result = client.post(route, json=body, headers=headers)
        assert_unavailable(result)
    committed = business_state(database)
    assert committed != before
    assert len(committed["exception_events"]) == len(before["exception_events"]) + 1
    assert len(committed["mutation_requests"]) == 1
    receipt = committed["mutation_requests"][0]
    replay = client.post(route, json=body, headers=headers)
    assert replay.status_code == 200 and replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == receipt["response"]
    assert business_state(database) == committed
    conflict = client.post(route, json={**body, "assignee_id": None}, headers=headers)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
    assert business_state(database) == committed
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE users SET role='reviewer' WHERE id=%s", (actor,))
    denied = client.post(route, json=body, headers=headers)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "read_only"
    assert business_state(database) == committed
    other, other_headers = harbor
    assert other.get(f"/api/exceptions/{item}").status_code == 404
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE users SET role='operator' WHERE id=%s", (actor,))
    stale = client.post(route, json=body, headers={**headers,"Idempotency-Key": str(uuid4())})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"
    prior = business_state(database)
    assert prior["shipment_exceptions"] == committed["shipment_exceptions"]
    assert prior["exception_events"] == committed["exception_events"]
    assert next(r for r in prior["mutation_requests"] if r["key"] == receipt["key"]) == receipt
    valid = client.post(route, json={**body,"expected_version":2,"assignee_id":None},
                        headers={**headers,"Idempotency-Key":str(uuid4())})
    assert valid.status_code == 200 and valid.json()["exception"]["version"] == 3
    history = client.get(f"/api/exceptions/{item}").json()
    assert [e["version"] for e in history["events"]] == [2, 3]
    # Saved receipt access still requires a current, unexpired session.
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE sessions SET expires_at=now()-interval '1 second' WHERE user_id=%s", (actor,))
    expired = client.post(route, json=body, headers=headers)
    assert expired.status_code == 401


@pytest.mark.parametrize("change", [{"password":"deliberately-invalid-password"},
                                   {"dbname":"nonexistent_outage_test_database"},
                                   {"sslmode":"require"}])
def test_actual_reachable_auth_and_configuration_failures_stay_500(northline, database, monkeypatch, change):
    client, _ = northline
    real_connect = app_module.connect
    from psycopg.conninfo import make_conninfo
    monkeypatch.setattr(app_module, "connect", lambda _: real_connect(make_conninfo(database, **change)))
    result = client.get("/api/session")
    assert result.status_code == 500
    assert result.json()["error"]["code"] == "internal_error"
    assert "deliberately-invalid" not in result.text and "nonexistent_outage" not in result.text


@pytest.mark.parametrize("broken", [True,False])
def test_sqlstateless_session_connection_loss_requires_broken_witness(northline, monkeypatch, broken):
    client, _ = northline
    real_connect = app_module.connect
    class Fault:
        def __init__(self, conn): self.conn=conn
        def __getattr__(self,name): return getattr(self.conn,name)
        @property
        def broken(self): return broken
        def execute(self,query,*args,**kwargs):
            if 'FROM sessions s' in str(query):
                raise psycopg.OperationalError('private diagnostic at simulated transport boundary')
            return self.conn.execute(query,*args,**kwargs)
    @contextmanager
    def connection(url):
        with real_connect(url) as conn: yield Fault(conn)
    monkeypatch.setattr(app_module,'connect',connection)
    response=client.get('/api/exceptions')
    if broken: assert_unavailable(response)
    else:
        assert response.status_code==500 and response.json()['error']['code']=='internal_error'


def failed_connection_error(host=b"127.0.0.1", port=b"5432", status=ConnStatus.BAD):
    return psycopg.OperationalError("private diagnostic", pgconn=SimpleNamespace(hostaddr=host,port=port,status=status))


@pytest.mark.parametrize("error,endpoint", [
    (psycopg.OperationalError("generic"), ("127.0.0.1",5432)),
    (psycopg.errors.ConnectionTimeout("timeout"), ("127.0.0.1",5432)),
    (psycopg.InterfaceError("closed"), ("127.0.0.1",5432)),
    (failed_connection_error(), None),
    (failed_connection_error(), ("127.0.0.1",5433)),
    (failed_connection_error(host=b"localhost"), ("127.0.0.1",5432)),
    (failed_connection_error(status=ConnStatus.OK), ("127.0.0.1",5432)),
])
def test_ambiguous_connect_errors_never_probe(monkeypatch, error, endpoint):
    monkeypatch.setattr(av, "refused_endpoint", lambda _: pytest.fail("Unexpected transport diagnostic"))
    assert not av.unavailable_connect(error, endpoint)


@pytest.mark.parametrize("result,expected", [(errno.ECONNREFUSED,True),(10061,True),(0,False),(errno.ETIMEDOUT,False)])
def test_connect_refusal_diagnostic_is_numeric_once_and_bounded(monkeypatch, result, expected):
    calls=[]
    class Probe:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def settimeout(self,value): calls.append(("timeout",value))
        def connect_ex(self,address): calls.append(("connect",address)); return result
    monkeypatch.setattr(av.socket, "socket", lambda *args: Probe())
    assert av.unavailable_connect(failed_connection_error(), ("127.0.0.1",5432)) is expected
    assert calls == [("timeout",2.5),("connect",("127.0.0.1",5432))]


@pytest.mark.parametrize("url,environment", [
    ("postgresql://localhost:5432/workspace", {}),
    ("postgresql://127.0.0.1/workspace", {}),
    ("host=127.0.0.1,127.0.0.2 port=5432 dbname=workspace", {}),
    ("host=127.0.0.1 hostaddr=127.0.0.1 port=5432", {}),
    ("service=workspace host=127.0.0.1 port=5432", {}),
    ("postgresql://127.0.0.1:5432/workspace?host=localhost", {}),
    ("host=127.0.0.1 port=5432", {"PGHOSTADDR":"127.0.0.2"}),
    ("host=127.0.0.1 port=5432", {"PGSERVICE":"workspace"}),
    ("host=127.0.0.1 port=5432", {"PGSERVICEFILE":"private-service-file"}),
])
def test_timeout_route_does_not_guess_endpoint(url, environment):
    assert av.literal_endpoint(url, environment) is None


@pytest.mark.parametrize("refused", [True, False])
def test_timeout_caller_requires_current_refusal(northline, database, monkeypatch, refused):
    client, _ = northline
    calls=[]
    def fail_connect(url):
        assert url == database
        raise psycopg.errors.ConnectionTimeout("private diagnostic")
    def probe(endpoint):
        calls.append(endpoint)
        return refused
    monkeypatch.setattr(app_module, "connect", fail_connect)
    monkeypatch.setattr(av, "refused_endpoint", probe)
    response=client.get("/api/session")
    if refused: assert_unavailable(response)
    else:
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
    assert calls == [av.literal_endpoint(database, {})]


def test_timeout_does_not_probe_a_changed_endpoint(monkeypatch):
    monkeypatch.setattr(av, "refused_endpoint", lambda _: pytest.fail("Unexpected transport diagnostic"))
    assert not av.unavailable_connect(psycopg.errors.ConnectionTimeout("timeout"),
                                      ("127.0.0.1",5433), "host=127.0.0.1 port=5432")
    assert not av.unavailable_connect(psycopg.errors.ConnectionTimeout("timeout"),
                                      ("127.0.0.1",5432), "postgresql://127.0.0.1:5432/workspace?port=5433")


@pytest.mark.parametrize("broken", [True,False])
def test_broken_established_connection_differs_from_application_close(broken):
    @contextmanager
    def connection():
        yield SimpleNamespace(broken=broken)
    with pytest.raises(av.DependencyUnavailable if broken else psycopg.OperationalError):
        with av.request_connection(connection, ("127.0.0.1",5432)):
            raise psycopg.OperationalError("private diagnostic")
