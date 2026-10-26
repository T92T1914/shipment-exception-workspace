"""Explicit one-time setup job for an otherwise empty dedicated demo database.

Run only through the reviewed installed runtime after the database identity and
cost decision. This is not a web start command or an automatic recovery step.
"""

import os
from pathlib import Path
import subprocess
import sys


def require_isolated_runtime(prefix, base_prefix):
    if Path(prefix).resolve() == Path(base_prefix).resolve():
        raise RuntimeError("Run setup through the isolated installed application runtime")


def setup_environment(environ):
    allowed = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "LD_LIBRARY_PATH",
               "SHIPMENT_DATABASE_URL", "SHIPMENT_PUBLIC_ORIGIN", "SHIPMENT_PUBLIC_DEMO_PASSWORD", "SHIPMENT_SOURCE_REVISION")
    env = {key: environ[key] for key in allowed if key in environ}
    env.update(PYTHONNOUSERSITE="1", PYTHONPATH="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", MAX_JOBS="2")
    return env


def setup(database_url, python, env, *, connect, execute):
    with connect(database_url) as conn:
        populated = conn.execute("""SELECT EXISTS(
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public') OR EXISTS(
            SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public') OR EXISTS(SELECT 1 FROM pg_largeobject_metadata) AS value""").fetchone()["value"]
        if populated:
            raise RuntimeError("Initial setup requires an empty dedicated public schema with no large objects. Existing state was preserved")
    for command in ("init", "provision-demo"):
        execute([str(python), "-I", "-m", "shipment_workspace.cli", command], check=True,
                timeout=120, stdin=subprocess.DEVNULL, env=env)


def main():
    require_isolated_runtime(sys.prefix, sys.base_prefix)
    # Imports here, rather than at module load, keep pure helper checks from
    # importing the application or making a database connection.
    from shipment_workspace import __version__
    from shipment_workspace.config import Settings
    from shipment_workspace.db import connect
    if __version__ != "0.9.0":
        raise RuntimeError("Initial setup requires the reviewed installed v0.9.0 package")
    Settings(os.environ["SHIPMENT_DATABASE_URL"], origin=os.environ["SHIPMENT_PUBLIC_ORIGIN"],
             secure_cookie=True, public_demo=True, demo_password=os.environ["SHIPMENT_PUBLIC_DEMO_PASSWORD"],
             deployment_revision=os.environ["SHIPMENT_SOURCE_REVISION"])
    setup(os.environ["SHIPMENT_DATABASE_URL"], sys.executable, setup_environment(os.environ),
          connect=connect, execute=subprocess.run)
    print("Explicit initial synthetic setup completed. Future starts must only use serve-demo.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            print(str(exc), file=sys.stderr)
        else:
            print("Initial setup failed. Preserve the target and job log, then inspect completed steps before any retry.", file=sys.stderr)
        raise SystemExit(1)
