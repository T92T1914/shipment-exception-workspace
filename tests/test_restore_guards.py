"""Connection/empty-state admission uses actual PostgreSQL for database guards."""
import pytest
import psycopg
from psycopg.conninfo import make_conninfo

from tools.local_restore import Refused, empty_database, guard_restore, parameters


@pytest.mark.parametrize("url", [
    "dbname=shipment", "host=127.0.0.1 dbname=shipment user=owner password=test",
    "host=localhost port=5432 dbname=shipment user=owner password=test",
    "host=192.0.2.1 port=5432 dbname=shipment user=owner password=test",
    "host=127.0.0.1 port=5433 dbname=shipment user=owner password=test",
    "host=127.0.0.1 port=5432 dbname=shipment user=owner password=test service=other",
])
def test_restore_requires_explicit_bounded_endpoint(url):
    with pytest.raises(Refused):
        parameters(url, 5432)


def test_connection_alias_is_refused_at_actual_identity_preflight(database):
    from psycopg.conninfo import conninfo_to_dict
    port = int(conninfo_to_dict(database)["port"])
    source = parameters(database, port)
    alias = parameters(make_conninfo(**source), port)
    assert alias == source
    # Hosted CI reaches its service through Docker port forwarding. The direct
    # loopback route must reject that different server endpoint first, while a
    # directly hosted database reaches the later same-database refusal.
    with psycopg.connect(database) as conn:
        effective = conn.execute("SELECT host(inet_server_addr()), inet_server_port()").fetchone()
    reason = ("Source and target resolve to the same database" if effective == (source["host"], port)
              else "Effective endpoint differs from the explicit record")
    with pytest.raises(Refused) as refusal:
        guard_restore(source, alias)
    assert str(refusal.value) == reason


def test_application_tables_make_a_nonempty_restore_target(database):
    from psycopg.conninfo import conninfo_to_dict
    params = parameters(database, int(conninfo_to_dict(database)["port"]))
    with pytest.raises(Refused, match="pristine empty"):
        empty_database(params)
