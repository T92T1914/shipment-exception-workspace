"""Bounded event pages inside one organization-scoped exception's version fence."""

import base64
import binascii
import json
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class InvalidHistoryQuery(ValueError):
    pass


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    v: int = Field(strict=True, ge=1, le=1)
    organization_id: UUID
    exception_id: UUID
    limit: int = Field(strict=True, ge=1, le=50)
    through_version: int = Field(strict=True, ge=1, le=2147483647)
    before_version: int = Field(strict=True, ge=1, le=2147483647)

    @model_validator(mode="after")
    def ordered_versions(self):
        if self.before_version > self.through_version:
            raise ValueError("Position exceeds its version fence")
        return self


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate cursor field")
        result[key] = value
    return result


def decode_position(token):
    try:
        if len(token) > 1024 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError("Invalid cursor encoding")
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != token:
            raise ValueError("Noncanonical cursor encoding")
        return Position.model_validate(json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object))
    except (ValueError, UnicodeError, binascii.Error, ValidationError, RecursionError) as exc:
        raise InvalidHistoryQuery("Invalid cursor") from exc


def encode_position(organization_id, exception_id, limit, through_version, before_version):
    position = Position(v=1, organization_id=organization_id, exception_id=exception_id,
                        limit=limit, through_version=through_version, before_version=before_version)
    raw = json.dumps(position.model_dump(mode="json"), sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def page_for(conn, organization_id, exception_id, current_version, params=None):
    # The caller must first resolve this record using its authenticated org.
    fields = list(params.multi_items()) if params is not None else []
    if any(key not in {"limit", "cursor"} for key, _ in fields) or len(fields) != len({key for key, _ in fields}):
        raise InvalidHistoryQuery("Unsupported or duplicate parameter")
    size = params.get("limit", "20") if params is not None else "20"
    if not re.fullmatch(r"(?:[1-9]|[1-4][0-9]|50)", size):
        raise InvalidHistoryQuery("Invalid page size")
    limit = int(size)
    position = decode_position(params["cursor"]) if params is not None and "cursor" in params else None
    if position and (position.organization_id != organization_id or position.exception_id != exception_id or
                     position.limit != limit or position.through_version > current_version):
        raise InvalidHistoryQuery("Cursor does not match this history")
    through_version = position.through_version if position else current_version
    where = "e.organization_id=%s AND e.exception_id=%s AND e.version<=%s"
    arguments = [organization_id, exception_id, through_version]
    if position:
        where += " AND e.version<%s"
        arguments.append(position.before_version)
    # Fetch one lookahead row, not the whole history. The unique per-record
    # version gives a deterministic order without an offset or total count.
    rows = conn.execute("""SELECT e.id,e.action,a.name AS actor_name,u.name AS assignee_name,e.note,e.version,e.created_at
        FROM exception_events e JOIN users a ON a.id=e.actor_id LEFT JOIN users u ON u.id=e.assignee_id
        WHERE """ + where + " ORDER BY e.version DESC LIMIT %s", (*arguments, limit + 1)).fetchall()
    selected = rows[:limit]
    next_cursor = encode_position(organization_id, exception_id, limit, through_version,
                                  selected[-1]["version"]) if len(rows) > limit else None
    return {"events": list(reversed(selected)), "next_cursor": next_cursor,
            "page_size": limit, "through_version": through_version}
