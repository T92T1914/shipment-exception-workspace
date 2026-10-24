"""Change only Alex's role in the explicit disposable six-account browser DB.

This fixture is not an application endpoint or role administration tool. It
never resets domain records, sessions, audit history or mutation receipts.
"""

import argparse
import json
import os
from uuid import UUID

from shipment_workspace.db import connect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("demote-alex", "promote-alex"))
    args = parser.parse_args()
    database_url = os.environ.get("WORKSPACE_ROLE_FIXTURE_URL")
    if not database_url:
        parser.error("Set WORKSPACE_ROLE_FIXTURE_URL to the disposable browser database")
    expected = {
        "alex@northline.example": (UUID(int=11), UUID(int=1)),
        "sam@northline.example": (UUID(int=12), UUID(int=1)),
        "casey@northline.example": (UUID(int=13), UUID(int=1)),
        "jules@harbor.example": (UUID(int=21), UUID(int=2)),
        "robin@harbor.example": (UUID(int=22), UUID(int=2)),
        "taylor@harbor.example": (UUID(int=23), UUID(int=2)),
    }
    role = "reviewer" if args.command == "demote-alex" else "operator"
    with connect(database_url) as conn, conn.transaction():
        accounts = {
            row["email"]: (row["id"], row["organization_id"])
            for row in conn.execute("SELECT id,organization_id,email FROM users").fetchall()
        }
        version = conn.execute("SELECT version FROM schema_version").fetchall()
        if accounts != expected or version != [{"version": 4}]:
            raise RuntimeError("Role fixture requires the exact synthetic schema/account set")
        changed = conn.execute(
            "UPDATE users SET role=%s WHERE id=%s AND organization_id=%s AND email=%s RETURNING id",
            (role, UUID(int=11), UUID(int=1), "alex@northline.example"),
        ).fetchall()
        if len(changed) != 1:
            raise RuntimeError("Role fixture did not update the one expected synthetic actor")
    print(json.dumps({"command": args.command, "ok": True, "role": role}))


if __name__ == "__main__":
    main()
