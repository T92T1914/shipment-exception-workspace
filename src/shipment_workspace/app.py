"""Same-origin sessions and an atomic, versioned exception workflow."""

import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import anyio
from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg.types.json import Jsonb

from .config import Settings
from .db import PASSWORDS, connect, exception_record, require_current_schema
from .login_admission import reserve_login
from .queue_browsing import InvalidQueueQuery, page_for
from .history_browsing import InvalidHistoryQuery, page_for as history_page_for

COOKIE = "shipment_session"
MAX_BODY = 16384


class Problem(Exception):
    def __init__(self, status, code, message, headers=None, **extra):
        self.status = status
        self.headers = headers
        self.body = {"error": {"code": code, "message": message, **extra}}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class Assign(Input):
    expected_version: int = Field(ge=1, le=2147483646, strict=True)
    assignee_id: UUID | None


class Create(Input):
    reference: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=200)
    details: str = Field(min_length=1, max_length=4000)
    priority: Literal["normal", "high"]

    @field_validator("priority", mode="before")
    @classmethod
    def trim_priority(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("reference", "summary", "details")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter text for each field")
        return value.strip()


class Resolve(Input):
    expected_version: int = Field(ge=1, le=2147483646, strict=True)
    resolution: str = Field(min_length=1, max_length=2000)

    @field_validator("resolution")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Resolution must contain text")
        return value.strip()


class BodyLimit:
    """Bound buffered request bodies even when Content-Length is absent or false."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > MAX_BODY:
                return await JSONResponse({"error": {"code": "body_too_large", "message": "Request body is too large."}}, 413)(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break
        index = 0

        async def replay():
            nonlocal index
            if index < len(chunks):
                message = chunks[index]
                index += 1
                return message
            return await receive()

        async def headers(message):
            if message["type"] == "http.response.start":
                message["headers"] += [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
                    (b"x-frame-options", b"DENY"),
                ]
            await send(message)

        await self.app(scope, replay, headers)


def create_app(settings: Settings):
    require_current_schema(settings.database_url)
    @asynccontextmanager
    async def lifespan(app):
        anyio.to_thread.current_default_thread_limiter().total_tokens = 2
        yield

    app = FastAPI(title="Shipment Exception Workspace", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.add_middleware(BodyLimit)
    # One dummy hash prevents the unknown-email path from skipping password work.
    dummy_hash = PASSWORDS.hash(secrets.token_urlsafe(32))

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse(exc.body, exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_handler(request, exc):
        # Do not echo submitted passwords, payloads or internal validation context.
        return JSONResponse({"error": {"code": "invalid_input", "message": "Check the submitted fields."}}, 422)

    @app.exception_handler(Exception)
    async def unexpected_handler(request, exc):
        return JSONResponse({"error": {"code": "internal_error", "message": "The change could not be completed. Retry the same request."}}, 500)

    def connection():
        with connect(settings.database_url) as conn:
            yield conn

    def session(request: Request, conn=Depends(connection)):
        token = request.cookies.get(COOKIE, "")
        if not token or len(token) > 128:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        return conn.execute("""SELECT s.*, u.organization_id, u.name, u.email, u.role, o.name AS organization_name
            FROM sessions s LEFT JOIN users u ON u.id=s.user_id
            LEFT JOIN organizations o ON o.id=u.organization_id
            WHERE token_hash=%s AND expires_at > now()""", (digest,)).fetchone()

    def principal(current=Depends(session)):
        if not current or not current["user_id"]:
            raise Problem(401, "not_authenticated", "Sign in to continue.")
        return current

    def csrf(request, current):
        if request.headers.get("origin") != settings.origin:
            raise Problem(403, "csrf_failed", "Refresh the page before submitting this change.")
        supplied = request.headers.get("x-csrf-token", "")
        if not current or len(supplied) > 128 or not supplied.isascii() or not secrets.compare_digest(supplied, current["csrf_token"]):
            raise Problem(403, "csrf_failed", "Refresh the page before submitting this change.")
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            raise Problem(415, "json_required", "Submit JSON for this action.")

    def payload(current):
        result = {"authenticated": bool(current["user_id"]), "csrf_token": current["csrf_token"]}
        if current["user_id"]:
            result["user"] = {"id": current["user_id"], **{key: current[key] for key in ("name", "email", "organization_id", "organization_name", "role")}}
        return jsonable_encoder(result)

    def new_session(conn, user_id=None):
        token = secrets.token_urlsafe(32)
        row = {"token_hash": hashlib.sha256(token.encode()).hexdigest(), "user_id": user_id,
               "csrf_token": secrets.token_urlsafe(32),
               "expires_at": datetime.now(timezone.utc) + timedelta(hours=8) if user_id else datetime.now(timezone.utc) + timedelta(minutes=15)}
        conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES (%s,%s,%s,%s)", tuple(row.values()))
        return token, row

    def session_response(current, token=None):
        response = JSONResponse(payload(current))
        if token:
            response.set_cookie(COOKIE, token, httponly=True, secure=settings.secure_cookie,
                                samesite="strict", path="/", max_age=28800 if current["user_id"] else 900)
        return response

    @app.get("/api/session")
    def get_session(current=Depends(session), conn=Depends(connection)):
        if current:
            return session_response(current)
        with conn.transaction():
            conn.execute("DELETE FROM sessions WHERE expires_at <= now()")
            token, created = new_session(conn)
        return session_response(created, token)

    @app.post("/api/login")
    def login(body: Login, request: Request, current=Depends(session), conn=Depends(connection)):
        csrf(request, current)
        identifier = body.email.strip().lower()
        retry_after = reserve_login(conn, identifier)
        if retry_after:
            raise Problem(429, "login_throttled", "Too many sign-in attempts. Wait before trying again.",
                          headers={"Retry-After": str(retry_after)})
        user = conn.execute("SELECT u.*,o.name AS organization_name FROM users u JOIN organizations o ON o.id=u.organization_id WHERE email=%s",
                            (identifier,)).fetchone()
        try:
            PASSWORDS.verify(user["password_hash"] if user else dummy_hash, body.password)
        except VerificationError:
            raise Problem(401, "invalid_credentials", "Email or password is incorrect.")
        if not user:
            raise Problem(401, "invalid_credentials", "Email or password is incorrect.")
        with conn.transaction():
            conn.execute("DELETE FROM sessions WHERE token_hash=%s", (current["token_hash"],))
            token, created = new_session(conn, user["id"])
        created.update({key: user[key] for key in ("name", "email", "organization_id", "organization_name", "role")})
        return session_response(created, token)

    @app.post("/api/logout", status_code=204)
    def logout(request: Request, current=Depends(principal), conn=Depends(connection)):
        csrf(request, current)
        conn.execute("DELETE FROM sessions WHERE token_hash=%s", (current["token_hash"],))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookie, httponly=True, samesite="strict")
        return response

    @app.get("/api/members")
    def members(current=Depends(principal), conn=Depends(connection)):
        return {"items": conn.execute("SELECT id,name,email FROM users WHERE organization_id=%s ORDER BY name", (current["organization_id"],)).fetchall()}

    @app.get("/api/exceptions")
    def exceptions(request: Request, current=Depends(principal), conn=Depends(connection)):
        try:
            return page_for(conn, current["organization_id"], request.query_params)
        except InvalidQueueQuery:
            raise Problem(422, "invalid_queue_query", "Check the queue search, status and page parameters.")

    @app.get("/api/exceptions/{exception_id}")
    def detail(exception_id: UUID, current=Depends(principal), conn=Depends(connection)):
        record = exception_record(conn, current["organization_id"], exception_id)
        if not record:
            raise Problem(404, "not_found", "Exception not found.")
        page = history_page_for(conn, current["organization_id"], exception_id, record["version"])
        return {"exception": record, "events": page["events"],
                "history": {key: page[key] for key in ("next_cursor", "page_size", "through_version")}}

    @app.get("/api/exceptions/{exception_id}/history")
    def history(exception_id: UUID, request: Request, current=Depends(principal), conn=Depends(connection)):
        record = exception_record(conn, current["organization_id"], exception_id)
        if not record:
            raise Problem(404, "not_found", "Exception not found.")
        try:
            return history_page_for(conn, current["organization_id"], exception_id, record["version"], request.query_params)
        except InvalidHistoryQuery:
            raise Problem(422, "invalid_history_query", "Check the history page parameters.")

    def prepare_intent(canonical, request, current, key):
        csrf(request, current)
        try:
            request_key = UUID(key or "")
        except ValueError:
            raise Problem(422, "invalid_idempotency_key", "Supply a UUID Idempotency-Key for this change.")
        fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return request_key, fingerprint

    def reserve(conn, org, actor, request_key, fingerprint):
        inserted = conn.execute("""INSERT INTO mutation_requests(organization_id,actor_id,key,fingerprint)
            VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING key""", (org, actor, request_key, fingerprint)).fetchone()
        if inserted:
            return None
        # A new READ COMMITTED statement sees the concurrent insert after it
        # commits. A single INSERT/SELECT CTE could keep the older snapshot.
        receipt = conn.execute("SELECT * FROM mutation_requests WHERE organization_id=%s AND actor_id=%s AND key=%s", (org, actor, request_key)).fetchone()
        if receipt["fingerprint"] != fingerprint:
            raise Problem(409, "idempotency_conflict", "This retry key belongs to a different change.")
        return receipt

    def require_operator(conn, org, actor):
        # SHARE conflicts with an ordinary non-key role UPDATE. Keep this lock
        # until the business transaction commits, before receipt/record locks.
        user = conn.execute("SELECT organization_id,role FROM users WHERE id=%s FOR SHARE", (actor,)).fetchone()
        if not user or user["organization_id"] != org or user["role"] != "operator":
            raise Problem(403, "read_only", "Your account has read-only access. Refresh the workspace to review saved records.")

    def save_receipt(conn, org, actor, request_key, status, result):
        conn.execute("UPDATE mutation_requests SET status_code=%s,response=%s WHERE organization_id=%s AND actor_id=%s AND key=%s",
                     (status, Jsonb(result), org, actor, request_key))

    @app.post("/api/exceptions")
    def create(body: Create, request: Request, current=Depends(principal),
               conn=Depends(connection), idempotency_key: str | None = Header(default=None)):
        canonical = {"action": "created", **body.model_dump(mode="json")}
        request_key, fingerprint = prepare_intent(canonical, request, current, idempotency_key)
        org, actor = current["organization_id"], current["user_id"]
        replay = False
        with conn.transaction():
            require_operator(conn, org, actor)
            receipt = reserve(conn, org, actor, request_key, fingerprint)
            if receipt:
                status, result, replay = receipt["status_code"], receipt["response"], True
            else:
                exception_id = uuid4()
                inserted = conn.execute("""INSERT INTO shipment_exceptions(id,organization_id,reference,summary,details,priority)
                    VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (organization_id,reference) DO NOTHING RETURNING id""",
                    (exception_id, org, body.reference, body.summary, body.details, body.priority)).fetchone()
                if inserted:
                    conn.execute("""INSERT INTO exception_events(organization_id,exception_id,actor_id,action,version)
                        VALUES (%s,%s,%s,'created',1)""", (org, exception_id, actor))
                    status, result = 201, {"exception": jsonable_encoder(exception_record(conn, org, exception_id))}
                else:
                    status, result = 409, {"error": {"code": "reference_conflict", "message": "This reference already exists in your organization."}}
                save_receipt(conn, org, actor, request_key, status, result)
        return JSONResponse(result, status, headers={"Idempotency-Replayed": str(replay).lower()})

    def mutate(action, exception_id, body, request, current, conn, key):
        # Keep this canonical shape unchanged so v1 receipts survive migration.
        canonical = {"action": action, "exception_id": str(exception_id), **body.model_dump(mode="json")}
        request_key, fingerprint = prepare_intent(canonical, request, current, key)
        org, actor = current["organization_id"], current["user_id"]
        replay = False
        with conn.transaction():
            require_operator(conn, org, actor)
            receipt = reserve(conn, org, actor, request_key, fingerprint)
            if receipt:
                status, result, replay = receipt["status_code"], receipt["response"], True
            else:
                record = conn.execute("SELECT * FROM shipment_exceptions WHERE organization_id=%s AND id=%s FOR UPDATE", (org, exception_id)).fetchone()
                try:
                    if not record:
                        raise Problem(404, "not_found", "Exception not found.")
                    if record["version"] != body.expected_version:
                        raise Problem(409, "version_conflict", "This exception changed. Refresh before editing.", current_version=record["version"])
                    if record["status"] == "resolved":
                        raise Problem(409, "already_resolved", "This exception is already resolved.")
                    if action == "assigned":
                        if body.assignee_id and not conn.execute("SELECT id FROM users WHERE organization_id=%s AND id=%s", (org, body.assignee_id)).fetchone():
                            raise Problem(400, "invalid_assignee", "Choose a member of your organization.")
                        conn.execute("UPDATE shipment_exceptions SET assignee_id=%s,version=version+1,updated_at=now() WHERE organization_id=%s AND id=%s", (body.assignee_id, org, exception_id))
                        assignee, note = body.assignee_id, None
                    else:
                        conn.execute("UPDATE shipment_exceptions SET status='resolved',resolution=%s,version=version+1,updated_at=now() WHERE organization_id=%s AND id=%s", (body.resolution, org, exception_id))
                        assignee, note = record["assignee_id"], body.resolution
                    conn.execute("""INSERT INTO exception_events(organization_id,exception_id,actor_id,action,assignee_id,note,version)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)""", (org, exception_id, actor, action, assignee, note, record["version"] + 1))
                    status, result = 200, {"exception": jsonable_encoder(exception_record(conn, org, exception_id))}
                except Problem as exc:
                    status, result = exc.status, exc.body
                save_receipt(conn, org, actor, request_key, status, result)
        # The response is not exposed until the transaction has committed.
        return JSONResponse(result, status, headers={"Idempotency-Replayed": str(replay).lower()})

    @app.post("/api/exceptions/{exception_id}/assign")
    def assign(exception_id: UUID, body: Assign, request: Request, current=Depends(principal),
               conn=Depends(connection), idempotency_key: str | None = Header(default=None)):
        return mutate("assigned", exception_id, body, request, current, conn, idempotency_key)

    @app.post("/api/exceptions/{exception_id}/resolve")
    def resolve(exception_id: UUID, body: Resolve, request: Request, current=Depends(principal),
                conn=Depends(connection), idempotency_key: str | None = Header(default=None)):
        return mutate("resolved", exception_id, body, request, current, conn, idempotency_key)

    static = Path(__file__).with_name("static")
    @app.get("/third-party-notices")
    def notices():
        return FileResponse(Path(__file__).with_name("THIRD_PARTY_NOTICES.txt"), media_type="text/plain")

    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app
