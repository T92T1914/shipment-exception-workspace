"""Check the wheel's actual UI, schema and license contents before acceptance."""

import hashlib
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
wheel = root / "dist" / "shipment_exception_workspace-0.1.0-py3-none-any.whl"
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    required = ("shipment_workspace/static/index.html", "shipment_workspace/schema.sql",
                "shipment_workspace/THIRD_PARTY_NOTICES.txt", "shipment_workspace/app.py")
    for name in required:
        assert name in names, f"Missing wheel member: {name}"
    assert any(name.startswith("shipment_workspace/static/assets/") and name.endswith(".js") for name in names)
    assert any(name.startswith("shipment_workspace/static/assets/") and name.endswith(".css") for name in names)
    notice = archive.read("shipment_workspace/THIRD_PARTY_NOTICES.txt")
    assert b"Meta Platforms" in notice and b"LGPL-3.0-only" in notice
    assert notice == (root / "THIRD_PARTY_NOTICES.txt").read_bytes()
    for name in names:
        assert "node_modules" not in name and not name.endswith((".env", ".log"))
        if name.startswith("shipment_workspace/") and name.endswith((".py", ".sql")):
            assert archive.read(name) == (root / "src" / name).read_bytes(), f"Stale wheel source: {name}"
print(f"Wheel contents accepted. SHA256 {hashlib.sha256(wheel.read_bytes()).hexdigest()}")
