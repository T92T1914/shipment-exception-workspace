"""Pure deployment-helper checks with fake downloads, processes and connections.

These checks do not install a package, create a virtual environment, connect to
PostgreSQL or qualify Render hosting. The owner executes installed and hosted
acceptance separately.
"""

from contextlib import contextmanager
import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[1]


def helper(name):
    source = ROOT / "deploy" / (name + ".py")
    specification = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture()
def build():
    return helper("render_build")


@pytest.fixture()
def initial_setup():
    return helper("render_initial_setup")


def identity(**changes):
    return {"SHIPMENT_RELEASE_SHA256": "1" * 64, "SHIPMENT_SOURCE_REVISION": "2" * 40, **changes}


@pytest.mark.parametrize("changes", [
    {"SHIPMENT_RELEASE_SHA256": ""}, {"SHIPMENT_RELEASE_SHA256": "0" * 64},
    {"SHIPMENT_RELEASE_SHA256": "A" * 64}, {"SHIPMENT_RELEASE_SHA256": "1" * 63},
    {"SHIPMENT_SOURCE_REVISION": ""}, {"SHIPMENT_SOURCE_REVISION": "2" * 7},
    {"SHIPMENT_SOURCE_REVISION": "A" * 40},
])
def test_release_identity_requires_final_explicit_digest_and_full_revision(build, changes):
    with pytest.raises(RuntimeError):
        build.release_identity(identity(**changes))


def test_valid_release_identity_is_returned_without_inventing_a_candidate_commit(build):
    assert build.release_identity(identity()) == ("1" * 64, "2" * 40)


@pytest.mark.parametrize("url", [
    "http://github.com/asset", "https://unrelated.synthetic.example/asset",
    "https://github.com.unrelated.synthetic.example/asset", "https://user@github.com/asset",
    "https://release-assets.githubusercontent.com:8443/asset", "https://github.com/asset#fragment",
])
def test_redirect_policy_refuses_other_hosts_credentials_downgrades_and_ports(build, url):
    with pytest.raises(RuntimeError):
        build.validate_redirect(url)


def test_declared_https_github_asset_redirect_remains_admitted(build):
    build.validate_redirect("https://release-assets.githubusercontent.com/asset?synthetic-signed-query=retained")
    assert build.WHEEL_URL == "https://github.com/T92T1914/shipment-exception-workspace/releases/download/v0.9.0/shipment_exception_workspace-0.9.0-py3-none-any.whl"


def test_actual_redirect_handler_checks_the_destination_before_following(build):
    request = urllib.request.Request(build.WHEEL_URL)
    with pytest.raises(RuntimeError, match="declared HTTPS asset route"):
        build.ReleaseRedirect().redirect_request(request, None, 302, "Found", {}, "http://github.com/asset")


class Download(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status


def fake_download(data, status=200):
    calls = []

    def open_url(request, timeout):
        calls.append((request.full_url, timeout))
        return Download(data, status)

    return open_url, calls


def test_download_consumes_fixed_public_route_and_verifies_actual_bytes(build, tmp_path):
    payload = b"Synthetic wheel bytes for the downloader fixture."
    expected = hashlib.sha256(payload).hexdigest()
    opener, calls = fake_download(payload)
    wheel = tmp_path / build.WHEEL
    assert build.download_wheel(wheel, expected, open_url=opener, clock=lambda: 0) == (expected, len(payload))
    assert wheel.read_bytes() == payload
    assert calls == [(build.WHEEL_URL, 30)]


def test_mismatching_download_fails_and_preserves_its_failed_bytes(build, tmp_path):
    wheel = tmp_path / build.WHEEL
    opener, _ = fake_download(b"Different bytes")
    with pytest.raises(RuntimeError, match="accepted release digest"):
        build.download_wheel(wheel, "1" * 64, open_url=opener, clock=lambda: 0)
    assert wheel.read_bytes() == b"Different bytes"


def test_download_limits_and_http_failure_cannot_become_accepted_bytes(build, tmp_path, monkeypatch):
    monkeypatch.setattr(build, "MAX_WHEEL_BYTES", 8)
    opener, _ = fake_download(b"123456789")
    with pytest.raises(RuntimeError, match="size or time bound"):
        build.download_wheel(tmp_path / "large.whl", "1" * 64, open_url=opener, clock=lambda: 0)
    assert (tmp_path / "large.whl").read_bytes() == b""
    ticks = iter((0, 121))
    opener, _ = fake_download(b"small")
    with pytest.raises(RuntimeError, match="size or time bound"):
        build.download_wheel(tmp_path / "late.whl", "1" * 64, open_url=opener, clock=lambda: next(ticks))
    opener, _ = fake_download(b"not a wheel", 503)
    with pytest.raises(RuntimeError, match="HTTP 200"):
        build.download_wheel(tmp_path / "unavailable.whl", "1" * 64, open_url=opener, clock=lambda: 0)


def test_dependency_lock_allows_only_line_ending_conversion(build):
    original = (ROOT / "requirements-lock.txt").read_bytes()
    lf = original.replace(b"\r\n", b"\n")
    build.verify_lock(lf)
    build.verify_lock(lf.replace(b"\n", b"\r\n"))
    with pytest.raises(RuntimeError, match="reviewed v0.9.0 pins"):
        build.verify_lock(lf.replace(b"fastapi==", b"fastapi!="))


def test_existing_provider_outputs_are_preserved_instead_of_automatically_replaced(build, tmp_path):
    runtime, inputs = build.admit_outputs(tmp_path)
    assert runtime == tmp_path / ".shipment-runtime" and inputs == tmp_path / ".shipment-release-inputs"
    runtime.mkdir()
    witness = runtime / "previous-attempt.txt"
    witness.write_text("Retain this attempt", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Inspect the previous attempt"):
        build.admit_outputs(tmp_path)
    assert witness.read_text(encoding="utf-8") == "Retain this attempt"


def test_build_environment_withholds_credentials_before_explicit_ensurepip(build, tmp_path):
    parent = {"PATH": "synthetic-bin", "HOME": "synthetic-home", "SHIPMENT_DATABASE_URL": "private-database",
              "SHIPMENT_PUBLIC_DEMO_PASSWORD": "published-credential", "GH_TOKEN": "private-token",
              "RENDER_API_KEY": "provider-secret", "PIP_INDEX_URL": "unapproved-index", "PYTHONPATH": "source-tree"}
    env = build.child_environment(parent)
    assert not any(key in env for key in ("SHIPMENT_DATABASE_URL", "SHIPMENT_PUBLIC_DEMO_PASSWORD", "GH_TOKEN", "RENDER_API_KEY", "PIP_INDEX_URL"))
    assert env["PYTHONPATH"] == "" and env["MAX_JOBS"] == "2"
    calls = []

    class Builder:
        def __init__(self, **options):
            calls.append(("builder", options))

        def create(self, destination):
            calls.append(("create", destination))

    def execute(argv, environment, cwd, timeout):
        calls.append(("execute", argv, dict(environment), cwd, timeout))

    runtime, inputs = tmp_path / "runtime", tmp_path / "inputs"
    python = build.prepare_runtime(runtime, env, inputs, builder=Builder, execute=execute)
    assert calls[0] == ("builder", {"with_pip": False})
    assert calls[1] == ("create", runtime)
    assert calls[2] == ("execute", [str(python), "-I", "-m", "ensurepip", "--upgrade"], env, inputs, 120)
    assert parent["PYTHONPATH"] == "source-tree"


def test_setup_refuses_global_runtime_and_filters_unrelated_secrets(initial_setup, tmp_path):
    with pytest.raises(RuntimeError, match="isolated installed"):
        initial_setup.require_isolated_runtime(tmp_path, tmp_path)
    initial_setup.require_isolated_runtime(tmp_path / "venv", tmp_path / "python")
    env = initial_setup.setup_environment({"SHIPMENT_DATABASE_URL": "required-target",
        "SHIPMENT_PUBLIC_DEMO_PASSWORD": "required-public-password", "RENDER_API_KEY": "private-provider-key",
        "GH_TOKEN": "private-token", "PYTHONPATH": "source-tree"})
    assert env["SHIPMENT_DATABASE_URL"] == "required-target"
    assert env["SHIPMENT_PUBLIC_DEMO_PASSWORD"] == "required-public-password"
    assert "RENDER_API_KEY" not in env and "GH_TOKEN" not in env and env["PYTHONPATH"] == ""


def fake_connection(populated=False, failure=None):
    calls = []

    class Connection:
        def execute(self, statement):
            calls.append(statement)
            if failure:
                raise failure
            return self

        def fetchone(self):
            return {"value": populated}

    @contextmanager
    def connect(database_url):
        calls.append(database_url)
        yield Connection()

    return connect, calls


def test_populated_or_unreadable_setup_target_never_reaches_application_commands(initial_setup):
    executed = []
    for connect, expected in ((fake_connection(populated=True)[0], RuntimeError),
                              (fake_connection(failure=OSError("synthetic refusal"))[0], OSError)):
        with pytest.raises(expected):
            initial_setup.setup("synthetic-target", "synthetic-python", {}, connect=connect,
                                execute=lambda *args, **kwargs: executed.append((args, kwargs)))
    assert executed == []


def test_setup_runs_init_then_provision_once_and_preserves_failure_instead_of_retrying(initial_setup):
    connect, _ = fake_connection()
    commands = []

    def successful(argv, **options):
        commands.append((argv, options))

    initial_setup.setup("synthetic-target", "synthetic-python", {"SHIPMENT_DATABASE_URL": "synthetic-target"},
                        connect=connect, execute=successful)
    assert [argv[-1] for argv, _ in commands] == ["init", "provision-demo"]
    assert all(options["timeout"] == 120 and options["check"] and options["stdin"] == subprocess.DEVNULL for _, options in commands)
    failed = []

    def fail_initialization(argv, **options):
        failed.append(argv[-1])
        raise subprocess.CalledProcessError(1, argv)

    with pytest.raises(subprocess.CalledProcessError):
        initial_setup.setup("synthetic-target", "synthetic-python", {}, connect=connect, execute=fail_initialization)
    assert failed == ["init"]
    failed.clear()

    def fail_provisioning(argv, **options):
        failed.append(argv[-1])
        if argv[-1] == "provision-demo":
            raise subprocess.CalledProcessError(1, argv)

    with pytest.raises(subprocess.CalledProcessError):
        initial_setup.setup("synthetic-target", "synthetic-python", {}, connect=connect, execute=fail_provisioning)
    assert failed == ["init", "provision-demo"]
