"""Narrow request-time database availability classification for Psycopg 3.3.6."""

from contextlib import contextmanager
import errno
from ipaddress import ip_address
import os
import socket

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import ConnStatus


class DependencyUnavailable(Exception):
    """The request cannot rely on its database; its write outcome is not implied."""


# Do not classify the whole connection/operational error hierarchy. For example,
# protocol errors, cancellation, authentication and transaction conflicts differ.
UNAVAILABLE_STATES = frozenset({"08006", "57P01", "57P02", "57P03"})


def numeric_endpoint(hostaddr, port):
    try:
        if isinstance(hostaddr, bytes):
            hostaddr = hostaddr.decode("ascii")
        if not hostaddr or "%" in hostaddr:
            return None
        address = ip_address(hostaddr)
        port = int(port)
        if address.is_unspecified or address.is_multicast or not 1 <= port <= 65535:
            return None
        return str(address), port
    except (ValueError, TypeError, UnicodeError):
        return None


def literal_endpoint(database_url, environment):
    """Admit a timeout witness only for an explicit, unambiguous numeric route."""
    routing = {"PGHOST", "PGHOSTADDR", "PGPORT", "PGSERVICE", "PGSERVICEFILE"}
    if any(key.upper() in routing and value for key, value in environment.items()):
        return None
    try:
        params = conninfo_to_dict(database_url)
    except (psycopg.Error, TypeError):
        return None
    if "hostaddr" in params or "service" in params:
        return None
    return numeric_endpoint(params.get("host"), params.get("port"))


def refused_endpoint(endpoint):
    """One bounded TCP diagnostic to the verified dependency, without a DB login.

    Psycopg/libpq connection failures do not reliably carry SQLSTATE or errno.
    BAD alone also includes bad credentials, TLS and configuration. Only a
    current numeric-endpoint refusal corroborates this supported outage route.
    A successful handshake is not a successful database connection or authority.
    """
    host, port = endpoint
    family = socket.AF_INET6 if ip_address(host).version == 6 else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            # Windows can delay a refused loopback connect for about two seconds.
            probe.settimeout(2.5)
            result = probe.connect_ex((host, port))
        return result in {errno.ECONNREFUSED, 10061}  # WSAECONNREFUSED
    except OSError:
        return False


def unavailable_connect(exc, verified_endpoint, database_url=None):
    if exc.sqlstate in UNAVAILABLE_STATES:
        return True
    if type(exc) is psycopg.errors.ConnectionTimeout and exc.sqlstate is None:
        # This exception carries no failed PGconn in Psycopg 3.3.6. Do not
        # guess its destination from startup state, DNS or libpq defaults.
        endpoint = literal_endpoint(database_url, os.environ) if database_url else None
        return endpoint is not None and endpoint == verified_endpoint and refused_endpoint(endpoint)
    if type(exc) is not psycopg.OperationalError or exc.sqlstate is not None:
        return False
    failed = exc.pgconn
    if verified_endpoint is None or failed is None or failed.status != ConnStatus.BAD:
        return False
    endpoint = numeric_endpoint(failed.hostaddr, failed.port)
    return endpoint == verified_endpoint and refused_endpoint(endpoint)


@contextmanager
def request_connection(connect_factory, verified_endpoint, database_url=None):
    connection = None
    try:
        with connect_factory() as connection:
            try:
                yield connection
            except psycopg.Error as exc:
                # Inspect broken before our own context closes the connection.
                # Explicit application close is not a transport-break witness.
                if (exc.sqlstate in UNAVAILABLE_STATES or
                        (type(exc) is psycopg.OperationalError and exc.sqlstate is None
                         and connection.broken)):
                    raise DependencyUnavailable() from exc
                raise
    except psycopg.Error as exc:
        if connection is None and unavailable_connect(exc, verified_endpoint, database_url):
            raise DependencyUnavailable() from exc
        raise
