"""Check the wheel's actual UI, schema and license contents before acceptance."""

import hashlib
from pathlib import Path
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]
wheel = root / "dist" / "shipment_exception_workspace-0.4.0-py3-none-any.whl"
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    required = ("shipment_workspace/static/index.html", "shipment_workspace/schema.sql", "shipment_workspace/migrate_v1_v2.sql",
                "shipment_workspace/migrate_v2_v3.sql", "shipment_workspace/login_admission.py", "shipment_workspace/queue_browsing.py",
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
sdist = root / "dist" / "shipment_exception_workspace-0.4.0.tar.gz"
with tarfile.open(sdist) as archive:
    for version in (1, 2):
        fixture = f"shipment_exception_workspace-0.4.0/tests/fixtures/schema_v{version}.sql"
        assert archive.extractfile(fixture).read() == (root / f"tests/fixtures/schema_v{version}.sql").read_bytes()
print(f"Wheel contents and sdist migration fixture accepted. SHA256 {hashlib.sha256(wheel.read_bytes()).hexdigest()}")
