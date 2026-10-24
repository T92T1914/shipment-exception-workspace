"""Add one multi-page synthetic queue to an explicitly disposable browser DB.

No application endpoint exposes this helper. It refuses an existing queue
fixture instead of rewriting its state or inventing audit history on a rerun.
"""

import json
import os
from uuid import UUID

from shipment_workspace.db import connect


def main():
    database_url = os.environ.get("WORKSPACE_QUEUE_FIXTURE_URL")
    if not database_url:
        raise RuntimeError("Set WORKSPACE_QUEUE_FIXTURE_URL to the disposable browser database")
    expected = {"alex@northline.example", "sam@northline.example", "jules@harbor.example", "robin@harbor.example"}
    with connect(database_url) as conn, conn.transaction():
        accounts = {row["email"] for row in conn.execute("SELECT email FROM users").fetchall()}
        version = conn.execute("SELECT version FROM schema_version").fetchall()
        if accounts != expected or version != [{"version": 3}]:
            raise RuntimeError("Queue fixture requires the exact synthetic schema/account set")
        if conn.execute("SELECT 1 FROM shipment_exceptions WHERE reference LIKE 'NL-Q-%' OR reference LIKE 'HS-Q-%' LIMIT 1").fetchone():
            raise RuntimeError("Queue fixture exists. Use a fresh disposable consumer for another campaign")
        for index in range(54):
            resolved = index % 3 == 0
            summary = f"Queue browse synthetic case {index:03d}"
            if index == 52:
                summary = "Queue browse 100%_! literal marker"
            elif index == 53:
                summary = "Queue browse <script>literal markup</script>"
            conn.execute("""INSERT INTO shipment_exceptions
                (id,organization_id,reference,summary,details,priority,status,resolution)
                VALUES (%s,%s,%s,%s,%s,'normal',%s,%s)""",
                (UUID(int=5000 + index), UUID(int=1), f"NL-Q-{index:03d}", summary,
                 "Synthetic queue browsing fixture. No operational shipment data.",
                 "resolved" if resolved else "open", "Synthetic fixture resolution" if resolved else None))
        for index in range(4):
            conn.execute("""INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority)
                VALUES (%s,%s,%s,%s,%s,'normal')""",
                (UUID(int=6000 + index), UUID(int=2), f"HS-Q-{index:03d}",
                 f"Queue browse foreign case {index:03d}", "Synthetic other-organization fixture."))
    print(json.dumps({"command": "seed", "ok": True, "northline": 54, "harbor": 4}))


if __name__ == "__main__":
    main()
