"""Add synthetic history to one record in the explicit disposable browser DB.

The fixture creates its own labeled record and never rewrites existing workflow,
sessions or receipts. It is not an application endpoint or a recovery operation.
"""

import argparse
import json
import os
from uuid import UUID

from shipment_workspace.db import connect


RECORD_ID = UUID(int=8101)
REFERENCE = "NL-HISTORY-001"
DETAILS = "Synthetic history paging fixture. These events are test setup, not operational history."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "append"))
    args = parser.parse_args()
    database_url = os.environ.get("WORKSPACE_HISTORY_FIXTURE_URL")
    if not database_url:
        parser.error("Set WORKSPACE_HISTORY_FIXTURE_URL to the disposable browser database")
    expected = {
        "alex@northline.example": (UUID(int=11), UUID(int=1)),
        "sam@northline.example": (UUID(int=12), UUID(int=1)),
        "casey@northline.example": (UUID(int=13), UUID(int=1)),
        "jules@harbor.example": (UUID(int=21), UUID(int=2)),
        "robin@harbor.example": (UUID(int=22), UUID(int=2)),
        "taylor@harbor.example": (UUID(int=23), UUID(int=2)),
    }
    with connect(database_url) as conn, conn.transaction():
        accounts = {
            row["email"]: (row["id"], row["organization_id"])
            for row in conn.execute("SELECT id,organization_id,email FROM users").fetchall()
        }
        schema = conn.execute("SELECT version FROM schema_version").fetchall()
        if accounts != expected or schema != [{"version": 4}]:
            raise RuntimeError("History fixture requires the exact synthetic schema/account set")
        if args.command == "seed":
            if conn.execute("SELECT 1 FROM shipment_exceptions WHERE id=%s OR reference=%s", (RECORD_ID, REFERENCE)).fetchone():
                raise RuntimeError("History fixture exists. Use a fresh disposable consumer for another campaign")
            conn.execute("""INSERT INTO shipment_exceptions
                (id,organization_id,reference,summary,details,priority,version,assignee_id)
                VALUES (%s,%s,%s,'History paging synthetic review',%s,'normal',45,%s)""",
                (RECORD_ID, UUID(int=1), REFERENCE, DETAILS, UUID(int=11)))
            conn.execute("""INSERT INTO exception_events
                (organization_id,exception_id,actor_id,action,version)
                VALUES (%s,%s,%s,'created',1)""", (UUID(int=1), RECORD_ID, UUID(int=11)))
            for version in range(2, 46):
                conn.execute("""INSERT INTO exception_events
                    (organization_id,exception_id,actor_id,action,assignee_id,version)
                    VALUES (%s,%s,%s,'assigned',%s,%s)""",
                    (UUID(int=1), RECORD_ID, UUID(int=11), UUID(int=12 if version % 2 == 0 else 11), version))
            current_version = 45
        else:
            record = conn.execute("""SELECT * FROM shipment_exceptions
                WHERE id=%s AND organization_id=%s FOR UPDATE""", (RECORD_ID, UUID(int=1))).fetchone()
            if (not record or record["reference"] != REFERENCE or record["details"] != DETAILS or
                    record["version"] != 45 or record["status"] != "open"):
                raise RuntimeError("Append requires the exact untouched 45-event history fixture")
            versions = [row["version"] for row in conn.execute(
                "SELECT version FROM exception_events WHERE organization_id=%s AND exception_id=%s ORDER BY version",
                (UUID(int=1), RECORD_ID)).fetchall()]
            if versions != list(range(1, 46)):
                raise RuntimeError("Append requires the complete synthetic history fixture")
            current_version = 46
            conn.execute("""UPDATE shipment_exceptions SET version=%s,assignee_id=%s,updated_at=now()
                WHERE id=%s AND organization_id=%s""", (current_version, UUID(int=12), RECORD_ID, UUID(int=1)))
            conn.execute("""INSERT INTO exception_events
                (organization_id,exception_id,actor_id,action,assignee_id,version)
                VALUES (%s,%s,%s,'assigned',%s,%s)""",
                (UUID(int=1), RECORD_ID, UUID(int=11), UUID(int=12), current_version))
    print(json.dumps({"command": args.command, "ok": True, "id": str(RECORD_ID), "version": current_version}))


if __name__ == "__main__":
    main()
