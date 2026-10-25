"""Connection/empty-state admission uses actual PostgreSQL for database guards."""
import pytest
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


def test_same_effective_database_with_uri_and_keyword_forms_is_refused(database):
    from psycopg.conninfo import conninfo_to_dict
    port = int(conninfo_to_dict(database)["port"])
    source = parameters(database, port)
    alias = parameters(make_conninfo(**source), port)
    with pytest.raises(Refused, match="same database"):
        guard_restore(source, alias)


def test_application_tables_make_a_nonempty_restore_target(database):
    from psycopg.conninfo import conninfo_to_dict
    params = parameters(database, int(conninfo_to_dict(database)["port"]))
    with pytest.raises(Refused, match="pristine empty"):
        empty_database(params)
