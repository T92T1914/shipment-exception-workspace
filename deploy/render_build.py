"""Install the reviewed Shipment v0.9.0 wheel for one native Render build.

Candidate only. Supply the published wheel digest after release acceptance.
This helper never connects to PostgreSQL or provisions application data.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit
import venv


VERSION = "0.9.0"
WHEEL = "shipment_exception_workspace-0.9.0-py3-none-any.whl"
WHEEL_URL = "https://github.com/T92T1914/shipment-exception-workspace/releases/download/v0.9.0/" + WHEEL
LOCK_LF_SHA256 = "f56bdd4266247a765c201073c2dd94f8356550429c4fac563b3c747dd6643434"
MAX_WHEEL_BYTES = 16 * 1024 * 1024


def validate_redirect(newurl):
    parsed = urlsplit(newurl)
    if parsed.scheme != "https" or parsed.hostname not in {
        "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
    } or parsed.username is not None or parsed.port not in (None, 443) or parsed.fragment:
        raise RuntimeError("Release download redirected outside the declared HTTPS asset route")


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        validate_redirect(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def run(argv, env, cwd, timeout=600):
    subprocess.run(argv, check=True, env=env, cwd=cwd, timeout=timeout, stdin=subprocess.DEVNULL)


def release_identity(environ):
    expected = environ.get("SHIPMENT_RELEASE_SHA256", "")
    revision = environ.get("SHIPMENT_SOURCE_REVISION", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or expected == "0" * 64:
        raise RuntimeError("Set SHIPMENT_RELEASE_SHA256 to the accepted public v0.9.0 wheel digest")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("Set SHIPMENT_SOURCE_REVISION to the accepted v0.9.0 application commit")
    return expected, revision


def verify_lock(raw):
    lock_bytes = raw.replace(b"\r\n", b"\n")
    if b"\r" in lock_bytes or hashlib.sha256(lock_bytes).hexdigest() != LOCK_LF_SHA256:
        raise RuntimeError("Dependency lock differs from the reviewed v0.9.0 pins")


def admit_outputs(root):
    runtime, inputs = root / ".shipment-runtime", root / ".shipment-release-inputs"
    if runtime.exists() or inputs.exists() or runtime.is_symlink() or inputs.is_symlink():
        raise RuntimeError("Build output already exists. Inspect the previous attempt before a clean provider build")
    return runtime, inputs


def child_environment(environ):
    env = {key: environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
                                       "SSL_CERT_FILE", "SSL_CERT_DIR", "LD_LIBRARY_PATH") if key in environ}
    env.update(PYTHONNOUSERSITE="1", PYTHONPATH="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               MAX_JOBS="2", PIP_DISABLE_PIP_VERSION_CHECK="1")
    return env


def download_wheel(wheel, expected, *, open_url=None, clock=None):
    clock = clock or time.monotonic
    if open_url is None:
        open_url = urllib.request.build_opener(ReleaseRedirect()).open
    deadline = clock() + 120
    digest, size = hashlib.sha256(), 0
    request = urllib.request.Request(WHEEL_URL, headers={"User-Agent": "shipment-v0.9.0-release-consumer"})
    with open_url(request, timeout=30) as response, wheel.open("xb") as destination:
        if response.status != 200:
            raise RuntimeError("Public release wheel download did not return HTTP 200")
        while chunk := response.read(65536):
            size += len(chunk)
            if size > MAX_WHEEL_BYTES or clock() > deadline:
                raise RuntimeError("Release wheel download exceeded its declared size or time bound")
            destination.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError("Downloaded wheel bytes do not match the accepted release digest")
    return digest.hexdigest(), size


def prepare_runtime(runtime, env, inputs, *, builder=None, execute=None):
    builder, execute = builder or venv.EnvBuilder, execute or run
    # EnvBuilder's automatic pip bootstrap would inherit the parent's database
    # credentials. Bootstrap explicitly under the filtered child environment.
    builder(with_pip=False).create(runtime)
    python = runtime / "bin" / "python"
    execute([str(python), "-I", "-m", "ensurepip", "--upgrade"], env, inputs, timeout=120)
    return python


def main():
    if os.name != "posix" or sys.version_info[:3] != (3, 13, 3):
        raise RuntimeError("This candidate requires Render's native CPython 3.13.3 Linux runtime")
    expected, revision = release_identity(os.environ)
    root = Path.cwd().resolve(strict=True)
    lock = root / "requirements-lock.txt"
    verify_lock(lock.read_bytes())
    runtime, inputs = admit_outputs(root)
    inputs.mkdir()
    wheel = inputs / WHEEL
    digest, size = download_wheel(wheel, expected)
    # The named environment belongs to this provider build. Existing outputs
    # are never recursively erased or repaired by this helper.
    env = child_environment(os.environ)
    python = prepare_runtime(runtime, env, inputs)
    run([str(python), "-I", "-m", "pip", "--isolated", "install", "--only-binary=:all:",
         "--index-url", "https://pypi.org/simple", "-r", str(lock)], env, inputs)
    run([str(python), "-I", "-m", "pip", "--isolated", "install", "--no-deps", str(wheel)], env, inputs)
    run([str(python), "-I", "-m", "pip", "check"], env, inputs, timeout=60)
    identity = r'''
import importlib.metadata, json, pathlib, sys
import shipment_workspace
root = pathlib.Path(sys.prefix).resolve()
module = pathlib.Path(shipment_workspace.__file__).resolve()
assert module.is_relative_to(root), "Source-tree package leaked into runtime"
assert shipment_workspace.__version__ == "0.9.0"
assert importlib.metadata.version("shipment-exception-workspace") == "0.9.0"
package = module.parent
assert (package / "static" / "index.html").is_file()
assert (package / "THIRD_PARTY_NOTICES.txt").is_file()
print(json.dumps({"installed_version": shipment_workspace.__version__, "installed_under_runtime": True,
                  "built_frontend_present": True, "notices_present": True}))
'''
    run([str(python), "-I", "-c", identity], env, inputs, timeout=60)
    deployment_source = os.environ.get("RENDER_GIT_COMMIT")
    if deployment_source is not None and not re.fullmatch(r"[0-9a-f]{40}", deployment_source):
        raise RuntimeError("Provider checkout identity is not a complete Git commit ID")
    receipt = {"application_version": VERSION, "application_source_revision": revision,
               "deployment_checkout_revision": deployment_source, "wheel_name": WHEEL,
               "wheel_sha256": digest, "wheel_bytes": size,
               "dependency_lock_lf_sha256": LOCK_LF_SHA256, "python": "3.13.3",
               "runtime": ".shipment-runtime", "database_actions": "none"}
    (inputs / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Redirect targets can contain signed query parameters. Keep raw
        # network failures and environment values out of provider build logs.
        if isinstance(exc, RuntimeError):
            print(str(exc), file=sys.stderr)
        else:
            print("Release build failed. Inspect this build's retained outputs before retrying.", file=sys.stderr)
        raise SystemExit(1)
