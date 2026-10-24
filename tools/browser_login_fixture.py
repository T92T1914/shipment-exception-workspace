"""Control only admission time/budget in a disposable synthetic browser database.

This is test setup, never an application endpoint. An explicit fixture URL and
the exact seeded account set are required. Credentials are not command arguments.
"""

import argparse
from hashlib import sha256
import json
import os

from shipment_workspace.db import connect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("exhaust", "expire"))
    args = parser.parse_args()
    database_url = os.environ.get("WORKSPACE_LOGIN_FIXTURE_URL")
    if not database_url:
        parser.error("Set WORKSPACE_LOGIN_FIXTURE_URL to the disposable browser database")
    expected = {"alex@northline.example", "sam@northline.example", "casey@northline.example", "jules@harbor.example", "robin@harbor.example", "taylor@harbor.example"}
    identifier = sha256(b"alex@northline.example").hexdigest()
    with connect(database_url) as conn, conn.transaction():
        version = conn.execute("SELECT version FROM schema_version").fetchall()
        accounts = {row["email"] for row in conn.execute("SELECT email FROM users").fetchall()}
        if version != [{"version": 4}] or accounts != expected:
            raise RuntimeError("Browser admission fixture requires the exact synthetic schema/account set")
        if not conn.execute("SELECT singleton FROM login_global WHERE singleton=true FOR UPDATE").fetchone():
            raise RuntimeError("Browser admission fixture requires initialized global state")
        if args.command == "exhaust":
            conn.execute("UPDATE login_global SET attempts=0,reset_at=clock_timestamp()+interval '60 seconds' WHERE singleton=true")
            conn.execute("""INSERT INTO login_identifiers(identifier_hash,attempts,reset_at)
                VALUES (%s,20,clock_timestamp()+interval '60 seconds')
                ON CONFLICT (identifier_hash) DO UPDATE SET attempts=20,reset_at=EXCLUDED.reset_at""", (identifier,))
        else:
            conn.execute("UPDATE login_global SET reset_at=clock_timestamp()-interval '1 second' WHERE singleton=true")
            conn.execute("UPDATE login_identifiers SET reset_at=clock_timestamp()-interval '1 second' WHERE identifier_hash=%s", (identifier,))
    print(json.dumps({"command": args.command, "ok": True}))


if __name__ == "__main__":
    main()
