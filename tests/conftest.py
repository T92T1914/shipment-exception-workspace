"""Integration fixtures. These tests require their own disposable PostgreSQL database."""

from __future__ import annotations

from contextlib import contextmanager
import os

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from shipment_workspace.app import create_app
from shipment_workspace.config import Settings
from shipment_workspace.db import initialize, seed


TEST_PASSWORD = "Synthetic-only-password-42!"
ORIGIN = "http://testserver"


@pytest.fixture(scope="session")
def database_url():
    value = os.environ.get("SHIPMENT_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set SHIPMENT_TEST_DATABASE_URL to a disposable PostgreSQL database")
    initialize(value)
    return value


@pytest.fixture()
def database(database_url):
    with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute(
            "TRUNCATE login_identifiers, sessions, mutation_requests, exception_events, "
            "shipment_exceptions, users, organizations RESTART IDENTITY CASCADE"
        )
        conn.execute("UPDATE login_global SET attempts=0,reset_at=clock_timestamp() WHERE singleton=true")
    seed(database_url, TEST_PASSWORD)
    return database_url


@pytest.fixture()
def app(database):
    return create_app(Settings(database_url=database, origin=ORIGIN, secure_cookie=False))


@pytest.fixture()
def identities(database):
    with psycopg.connect(database, row_factory=dict_row) as conn:
        return {
            row["email"]: row
            for row in conn.execute(
                "SELECT id, organization_id, email FROM users ORDER BY email"
            ).fetchall()
        }


@contextmanager
def authenticated_client(app, email="alex@northline.example"):
    with TestClient(app, raise_server_exceptions=False) as client:
        anonymous = client.get("/api/session")
        assert anonymous.status_code == 200, anonymous.text
        assert anonymous.json()["authenticated"] is False
        response = client.post(
            "/api/login",
            json={"email": email, "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN, "X-CSRF-Token": anonymous.json()["csrf_token"]},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["authenticated"] is True
        yield client, {
            "Origin": ORIGIN,
            "X-CSRF-Token": payload["csrf_token"],
            "Content-Type": "application/json",
        }


@pytest.fixture()
def northline(app):
    with authenticated_client(app) as value:
        yield value


@pytest.fixture()
def harbor(app):
    with authenticated_client(app, "jules@harbor.example") as value:
        yield value


@pytest.fixture()
def open_exception(northline):
    client, _ = northline
    response = client.get("/api/exceptions")
    assert response.status_code == 200, response.text
    candidates = [item for item in response.json()["items"] if item["status"] == "open"]
    assert candidates, "Seed must contain an open synthetic Northline exception"
    return candidates[0]
