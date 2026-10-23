"""Retain the full licenses of the frontend code embedded in the wheel."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]
header = """Shipment Exception Workspace source is licensed under MIT.

Dependency licenses remain their own. The Python wheel imports, rather than
vendors, FastAPI (MIT), Uvicorn (BSD-3-Clause), psycopg and psycopg-binary
(LGPL-3.0-only), and argon2-cffi (MIT). Their installed distributions retain
their own notices. PostgreSQL is an external database, not bundled here.

The built frontend embeds the following unmodified dependencies. Their MIT
licenses are reproduced below. Other build/test dependencies are installed
separately and retain their own notices.
"""
parts = [header]
for name in ("react", "react-dom", "scheduler"):
    package = root / "frontend" / "node_modules" / name
    parts.append(f"\n{name}\n" + (package / "LICENSE").read_text(encoding="utf-8"))
notice = "\n".join(parts)
(root / "THIRD_PARTY_NOTICES.txt").write_text(notice, encoding="utf-8")
(root / "src" / "shipment_workspace" / "THIRD_PARTY_NOTICES.txt").write_text(notice, encoding="utf-8")
print("Frontend licenses retained in source and wheel notice files.")
