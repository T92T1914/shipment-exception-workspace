"""The stock seed stores each password only as an Argon2id hash.

The threat model in SECURITY.md lists a password hash from the stock seed
stored as plain text. A sign in test cannot see that on its own, because a seed
and a password check that changed together would still let the user in. So
this test reads what the seed stored. Each stock account must hold an encoded
Argon2id hash made with the parameters the application hashes with, that hash
must verify the seed password, and the password text must appear in no row of
any table in the public schema.

The removed run replaces the application's hasher, in the seed and in sign in,
with one that stores and compares plain text, so sign in still succeeds. The
test must then report every stock account and the users table.
"""

from argon2 import Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerifyMismatchError
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from conftest import ORIGIN, TEST_PASSWORD, authenticated_client, reset_database
from shipment_workspace import app as app_module, db
from shipment_workspace.app import create_app
from shipment_workspace.config import Settings
from shipment_workspace.db import PASSWORDS


STOCK_ACCOUNTS = [
    "alex@northline.example", "casey@northline.example", "jules@harbor.example",
    "robin@harbor.example", "sam@northline.example", "taylor@harbor.example",
]

GUARD = pytest.mark.parametrize("guard", ["kept", "removed"], ids=["guard-kept", "guard-removed"])


class PlainText:
    """The hasher with its hash taken out. Verification compares the stored text."""

    def hash(self, password):
        return password

    def verify(self, stored, password):
        if stored != password:
            raise VerifyMismatchError()
        return True


def account_finding(stored, password):
    """The first problem with one stored credential, or None when it is a proper hash."""
    if password in stored:
        return "holds the password text"
    try:
        parameters = extract_parameters(stored)
    except InvalidHashError:
        return "is not an encoded Argon2 hash"
    if parameters.type is not Type.ID or PASSWORDS.check_needs_rehash(stored):
        return "uses other Argon2 parameters than the application"
    try:
        PASSWORDS.verify(stored, password)
    except VerifyMismatchError:
        return "does not verify the seed password"
    return None


def credential_findings(database, password):
    """Name each account and each table where the seed password is not only a hash."""
    findings = []
    with psycopg.connect(database, row_factory=dict_row) as conn:
        for user in conn.execute("SELECT email, password_hash FROM users ORDER BY email").fetchall():
            finding = account_finding(user["password_hash"], password)
            if finding:
                findings.append((user["email"], finding))
        tables = [row["name"] for row in conn.execute(
            "SELECT tablename AS name FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
        for table in tables:
            found = conn.execute(sql.SQL("SELECT EXISTS(SELECT 1 FROM {} t WHERE strpos(t::text, %s) > 0) AS found")
                                 .format(sql.Identifier(table)), (password,)).fetchone()["found"]
            if found:
                findings.append((table, "holds the password text"))
    return findings


@GUARD
def test_stock_seed_stores_only_argon2id_hashes_and_the_password_nowhere(database_url, monkeypatch, guard):
    try:
        with monkeypatch.context() as patch:
            if guard == "removed":
                patch.setattr(db, "PASSWORDS", PlainText())
                patch.setattr(app_module, "PASSWORDS", PlainText())
            reset_database(database_url)
            app = create_app(Settings(database_url=database_url, origin=ORIGIN, secure_cookie=False))
            # Sign in succeeds either way, which is why the stored value is read directly.
            with authenticated_client(app) as (client, _):
                assert client.get("/api/session").json()["user"]["email"] == "alex@northline.example"
            findings = credential_findings(database_url, TEST_PASSWORD)
    finally:
        reset_database(database_url)

    if guard == "kept":
        assert findings == []
    else:
        assert findings == [(email, "holds the password text") for email in STOCK_ACCOUNTS] + [
            ("users", "holds the password text")]


def test_each_finding_names_the_credential_it_rejects():
    """The checker tells a weak, foreign or wrong hash apart from a proper one."""
    proper = PASSWORDS.hash(TEST_PASSWORD)
    assert account_finding(proper, TEST_PASSWORD) is None
    assert account_finding(TEST_PASSWORD, TEST_PASSWORD) == "holds the password text"
    assert account_finding("5f4dcc3b5aa765d61d8327deb882cf99", TEST_PASSWORD) == "is not an encoded Argon2 hash"
    weaker = type(PASSWORDS)(time_cost=1, memory_cost=8192, parallelism=1).hash(TEST_PASSWORD)
    assert account_finding(weaker, TEST_PASSWORD) == "uses other Argon2 parameters than the application"
    argon2i = type(PASSWORDS)(time_cost=3, memory_cost=65536, parallelism=1, type=Type.I).hash(TEST_PASSWORD)
    assert account_finding(argon2i, TEST_PASSWORD) == "uses other Argon2 parameters than the application"
    other = PASSWORDS.hash("Another-synthetic-password-7")
    assert account_finding(other, TEST_PASSWORD) == "does not verify the seed password"
