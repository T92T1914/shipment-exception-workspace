"""Explicit local configuration. No credentials are embedded in source."""

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str
    origin: str = "http://127.0.0.1:8765"
    secure_cookie: bool = False

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Origin must be an absolute HTTP origin")
        if parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("Origin must contain only scheme, host and optional port")
        if not self.secure_cookie and parsed.hostname not in ("127.0.0.1", "localhost", "testserver"):
            raise ValueError("HTTP cookies are restricted to loopback development")
        if parsed.scheme == "https" and not self.secure_cookie:
            raise ValueError("HTTPS requires secure cookies")
