"""Organization-scoped live queue pages with literal search and untrusted cursors."""

import base64
import binascii
import json
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .db import EXCEPTION_SELECT


class InvalidQueueQuery(ValueError):
    pass


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: int = Field(ge=1, le=1, strict=True)
    organization_id: UUID
    status: Literal["all", "open", "resolved"]
    q: str = Field(max_length=80)
    limit: int = Field(ge=1, le=50, strict=True)
    reference: str = Field(min_length=1, max_length=80)
    id: UUID

    @field_validator("q", "reference")
    @classmethod
    def valid_text(cls, value):
        if "\0" in value:
            raise ValueError("NUL is not supported")
        value.encode("utf-8")
        return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate cursor field")
        result[key] = value
    return result


def decode_position(token):
    try:
        if len(token) > 2048 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError("Invalid cursor encoding")
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != token:
            raise ValueError("Noncanonical cursor encoding")
        return Position.model_validate(json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object))
    except (ValueError, UnicodeError, binascii.Error, ValidationError, RecursionError) as exc:
        raise InvalidQueueQuery("Invalid cursor") from exc


def encode_position(organization_id, status, q, limit, record):
    position = Position(v=1, organization_id=organization_id, status=status, q=q,
                        limit=limit, reference=record["reference"], id=record["id"])
    raw = json.dumps(position.model_dump(mode="json"), ensure_ascii=False,
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def page_for(conn, organization_id, params):
    fields = list(params.multi_items())
    if any(key not in {"q", "status", "limit", "cursor"} for key, _ in fields) or len(fields) != len({key for key, _ in fields}):
        raise InvalidQueueQuery("Unsupported or duplicate parameter")
    q = params.get("q", "")
    status = params.get("status", "all")
    size = params.get("limit", "20")
    if len(q) > 80 or "\0" in q or status not in {"all", "open", "resolved"} or not re.fullmatch(r"(?:[1-9]|[1-4][0-9]|50)", size):
        raise InvalidQueueQuery("Invalid queue fields")
    try:
        q.encode("utf-8")
    except UnicodeError as exc:
        raise InvalidQueueQuery("Invalid search text") from exc
    q, limit = q.strip(), int(size)
    position = decode_position(params["cursor"]) if "cursor" in params else None
    if position and (position.organization_id != organization_id or position.status != status or position.q != q or position.limit != limit):
        raise InvalidQueueQuery("Cursor does not match this queue")

    # The cursor is a position hint, never an authorization credential. Do not
    # require its anchor to remain in a status filter between live requests.
    where, arguments = ["e.organization_id=%s"], [organization_id]
    if status != "all":
        where.append("e.status=%s")
        arguments.append(status)
    if q:
        pattern = "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        where.append("(e.reference COLLATE \"C\" ILIKE %s ESCAPE '!' OR e.summary COLLATE \"C\" ILIKE %s ESCAPE '!')")
        arguments.extend((pattern, pattern))
    if position:
        where.append('(e.reference COLLATE "C",e.id) > (%s::text COLLATE "C",%s::uuid)')
        arguments.extend((position.reference, position.id))
    query = EXCEPTION_SELECT + " WHERE " + " AND ".join(where) + ' ORDER BY e.reference COLLATE "C",e.id LIMIT %s'
    rows = conn.execute(query, (*arguments, limit + 1)).fetchall()
    items = rows[:limit]
    next_cursor = encode_position(organization_id, status, q, limit, items[-1]) if len(rows) > limit else None
    return {"items": items, "next_cursor": next_cursor, "page_size": limit}
