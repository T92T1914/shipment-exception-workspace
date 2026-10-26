"""Explicit local configuration. No credentials are embedded in source."""

from dataclasses import dataclass, field
from ipaddress import ip_address
import re
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str
    origin: str = "http://127.0.0.1:8765"
    secure_cookie: bool = False
    public_demo: bool = False
    demo_password: str | None = field(default=None, repr=False)
    deployment_revision: str | None = None

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
        if self.public_demo:
            if (parsed.scheme != "https" or not self.secure_cookie or parsed.username is not None
                    or parsed.password is not None or not self.origin.isascii()
                    or any(char.isspace() for char in self.origin) or "\\" in self.origin):
                raise ValueError("Public demo requires a canonical HTTPS origin and secure cookies")
            try:
                port = parsed.port
            except ValueError:
                raise ValueError("Public demo origin has an invalid port") from None
            host = parsed.hostname
            try:
                address = ip_address(host)
                authority = f"[{address}]" if address.version == 6 else str(address)
            except ValueError:
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or any(
                        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                        for label in host.split(".")):
                    raise ValueError("Public demo origin has an invalid hostname") from None
                authority = host
            if port is not None and port != 443:
                authority += f":{port}"
            if self.origin != "https://" + authority:
                raise ValueError("Public demo origin must use its canonical HTTPS spelling")
            if not self.demo_password or not 12 <= len(self.demo_password) <= 256:
                raise ValueError("Public demo requires its separate published reviewer password")
            try:
                database = urlsplit(self.database_url)
                hostname = database.hostname
                if database.scheme not in ("postgres", "postgresql") or not hostname or database.fragment:
                    raise ValueError
                if not hostname.isascii() or any(char in hostname for char in ",%/\\") or any(char.isspace() for char in hostname):
                    raise ValueError
                if database.port is not None and not 1 <= database.port <= 65535:
                    raise ValueError
                query = parse_qs(database.query, keep_blank_values=True, strict_parsing=True)
                if set(query) - {"sslmode", "sslrootcert", "sslcert", "sslkey", "channel_binding"}:
                    raise ValueError
                loopback = hostname == "localhost"
                try:
                    loopback = loopback or ip_address(hostname).is_loopback
                except ValueError:
                    pass
                modes = query.get("sslmode", [])
                if not loopback and modes not in (["require"], ["verify-ca"], ["verify-full"]):
                    raise ValueError
            except ValueError:
                raise ValueError("Public demo requires a PostgreSQL URL with explicit TLS for nonloopback connections") from None
        elif self.demo_password is not None:
            raise ValueError("A published reviewer password requires public demo mode")
        if self.deployment_revision is not None and not re.fullmatch(r"[0-9a-f]{40}", self.deployment_revision):
            raise ValueError("Deployment revision must be one complete lowercase Git commit ID")
