"""Small durable budget for password-verification work, shared by app processes."""

from datetime import timedelta
from hashlib import sha256
from math import ceil

IDENTIFIER_LIMIT = 20
GLOBAL_LIMIT = 40
WINDOW_SECONDS = 60


def reserve_login(conn, normalized_identifier):
    """Commit one admission before hashing a password, or return a wait in seconds.

    All counter writers take the singleton lock first. Do not hold that lock
    during password verification, and do not refund it for success or failure.
    """
    identifier_hash = sha256(normalized_identifier.encode("utf-8")).hexdigest()
    retry_after = 0
    with conn.transaction():
        global_budget = conn.execute("SELECT attempts,reset_at FROM login_global WHERE singleton=true FOR UPDATE").fetchone()
        if not global_budget:
            raise RuntimeError("Login admission state is unavailable")
        # Transaction-start time can be stale after waiting for the lock.
        now = conn.execute("SELECT clock_timestamp() AS value").fetchone()["value"]
        conn.execute("DELETE FROM login_identifiers WHERE reset_at <= %s", (now,))
        identifier = conn.execute("SELECT attempts,reset_at FROM login_identifiers WHERE identifier_hash=%s", (identifier_hash,)).fetchone()
        global_live = global_budget["reset_at"] > now
        blocked_until = []
        if global_live and global_budget["attempts"] >= GLOBAL_LIMIT:
            blocked_until.append(global_budget["reset_at"])
        if identifier and identifier["attempts"] >= IDENTIFIER_LIMIT:
            blocked_until.append(identifier["reset_at"])
        if blocked_until:
            retry_after = max(1, ceil((max(blocked_until) - now).total_seconds()))
        else:
            reset_at = now + timedelta(seconds=WINDOW_SECONDS)
            conn.execute("UPDATE login_global SET attempts=%s,reset_at=%s WHERE singleton=true",
                         (global_budget["attempts"] + 1 if global_live else 1,
                          global_budget["reset_at"] if global_live else reset_at))
            conn.execute("""INSERT INTO login_identifiers(identifier_hash,attempts,reset_at) VALUES (%s,1,%s)
                ON CONFLICT (identifier_hash) DO UPDATE SET attempts=login_identifiers.attempts+1""",
                         (identifier_hash, identifier["reset_at"] if identifier else reset_at))
    # Returning after the transaction commits also persists expiry cleanup on
    # denied requests. A storage failure must propagate before any hashing.
    return retry_after
