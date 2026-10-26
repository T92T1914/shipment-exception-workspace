"""Bounded admission for the single-process synthetic reviewer deployment."""

from threading import Lock
from time import monotonic
from uuid import UUID

from fastapi.responses import JSONResponse


DEMO_EMAIL = "visitor@northline.example"
DEMO_USER_ID = UUID(int=14)
DEMO_ORGANIZATION_ID = UUID(int=1)
SESSION_LIMIT = 128
SESSION_LOCK = (1397246288, 1)
ANONYMOUS_SECONDS = 300
AUTHENTICATED_SECONDS = 1800
REQUEST_BURST = 30
REQUESTS_PER_SECOND = 5


def public_reviewer(row):
    return bool(row and row.get("id", row.get("user_id")) == DEMO_USER_ID
                and row.get("organization_id") == DEMO_ORGANIZATION_ID
                and row.get("email") == DEMO_EMAIL and row.get("role") == "reviewer")


def session_slot(conn):
    """Call inside the transaction that will insert the replacement session."""
    conn.execute("SELECT pg_advisory_xact_lock(%s,%s)", SESSION_LOCK)
    now = conn.execute("SELECT clock_timestamp() AS value").fetchone()["value"]
    conn.execute("DELETE FROM sessions WHERE expires_at <= %s", (now,))
    count = conn.execute("SELECT count(*) AS value FROM sessions").fetchone()["value"]
    return now if count < SESSION_LIMIT else None


class RequestBudget:
    """A process-local work budget, separate from the durable session cap."""

    def __init__(self, clock=monotonic):
        self.clock = clock
        self.updated = clock()
        self.tokens = float(REQUEST_BURST)
        self.lock = Lock()

    def admit(self):
        with self.lock:
            now = self.clock()
            self.tokens = min(REQUEST_BURST, self.tokens + max(0, now - self.updated) * REQUESTS_PER_SECOND)
            self.updated = now
            if self.tokens < 1:
                return False
            self.tokens -= 1
            return True


class PublicBoundary:
    """Use one configured authority. Forwarded headers carry no authority here."""

    def __init__(self, app, authority, budget):
        self.app, self.authority, self.budget = app, authority, budget

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        hosts = [value for key, value in scope["headers"] if key.lower() == b"host"]
        if len(hosts) != 1 or hosts[0].lower() != self.authority.encode("ascii"):
            return await JSONResponse({"error": {"code": "invalid_host", "message": "Use the configured demo address."}}, 400)(scope, receive, send)
        if scope["path"].startswith("/api/") and scope["path"] != "/api/ready" and not self.budget.admit():
            return await JSONResponse({"error": {"code": "demo_busy", "message": "The synthetic demo is busy. Wait before trying again."}}, 429,
                                      headers={"Retry-After": "1"})(scope, receive, send)
        return await self.app(scope, receive, send)
