# Run the installed v0.9.0 application locally

The wheel contains the Python application, built React frontend, schema and third-party notices. Running it needs Python and PostgreSQL. It does not need Node, npm, a frontend build or a Vite development server.

The directly qualified local combination is Windows x64, CPython 3.13.3 and PostgreSQL 18.1. The Python dependency lock remains pinned. Other environments need their own execution evidence. Source-building and the separately configured public reviewer deployment have different prerequisites.

Obtain `shipment_exception_workspace-0.9.0-py3-none-any.whl`, `requirements-lock.txt` and the corresponding checksum file from the [repository releases](https://github.com/T92T1914/shipment-exception-workspace/releases). The [verification record](VERIFICATION.md) states whether the final v0.9.0 release and downloadable bytes have been accepted. The source distribution supplies source, frontend code, guides and tests. Compare the selected asset names and SHA256 values before installation. A matching checksum identifies bytes, not a trustworthy publisher.

## A fresh local workspace

Use a new environment outside a checkout and a dedicated empty PostgreSQL database. Create that database and an authorized role with your own PostgreSQL administrator first. Do not use a retained acceptance database, another project's database or real logistics data. Keep the connection string private.

Place the selected wheel and lock in `C:\work\shipment-v0.9.0\downloads`, then run these PowerShell commands. Replace the example database connection with your actual dedicated local database. Stop if any command fails.

```powershell
$root = 'C:\work\shipment-v0.9.0'
$downloads = Join-Path $root 'downloads'
$envPath = Join-Path $root 'installed-env'
$consumer = Join-Path $root 'consumer'
if ((Test-Path -LiteralPath $envPath) -or (Test-Path -LiteralPath $consumer)) {
    throw 'Use new environment and consumer directories.'
}
py -3.13 -m venv $envPath
$python = Join-Path $envPath 'Scripts\python.exe'
& $python -I -c "import sys; assert sys.version_info[:3] == (3, 13, 3), sys.version"
$env:PYTHONPATH = ''
$env:PYTHONNOUSERSITE = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
& $python -m pip --isolated install -r (Join-Path $downloads 'requirements-lock.txt')
& $python -m pip --isolated install --no-deps (Join-Path $downloads 'shipment_exception_workspace-0.9.0-py3-none-any.whl')
& $python -m pip check
New-Item -ItemType Directory -Path $consumer | Out-Null
Set-Location -LiteralPath $consumer
& $python -I -c "import shipment_workspace; print(shipment_workspace.__file__)"
$env:SHIPMENT_DATABASE_URL = 'postgresql://ROLE:PASSWORD@127.0.0.1:5432/DEDICATED_EMPTY_DATABASE'
& $python -I -m shipment_workspace.cli init
$env:SHIPMENT_DEMO_PASSWORD = & $python -I -c "import secrets; print(secrets.token_urlsafe(24))"
& $python -I -m shipment_workspace.cli seed
& $python -I -m shipment_workspace.cli serve --port 8765
```

The import path should be inside the new environment's `site-packages`. `init` and `seed` are explicit first-setup steps for this empty synthetic workspace. The server does not repeat them at startup.

Open `http://127.0.0.1:8765` in your own browser. If the port is occupied, choose another unprivileged port without stopping its owner. The ordinary `serve` route binds to loopback and serves the frontend and API together.

Inspect `$env:SHIPMENT_DEMO_PASSWORD` privately in that PowerShell session to sign in. Keep the password in your own private credential storage if you will resume the workspace. The stock seed uses the same generated password for all six accounts:

| Organization | Operators | Reviewer |
| --- | --- | --- |
| Northline Logistics | `alex@northline.example`, `sam@northline.example` | `casey@northline.example` |
| Harbor Supply | `jules@harbor.example`, `robin@harbor.example` | `taylor@harbor.example` |

These are synthetic identities. Publishing this stock reviewer password would also grant operator access. The public deployment provisions a separate visitor credential in separate state and enforces its reviewer-only policy at the server. Do not publish this local password or turn the local stock database into a public demo.

As Alex, create a new exception, assign it to a member of Northline, resolve it and inspect its history after reload. Casey can browse the same organization's records and history but cannot change business records or replay mutation receipts. The [operator walkthrough](operator-walkthrough.md) shows the executed workflow, stale-state recovery and an interrupted-response case.

## Stop, resume or upgrade an existing workspace

Press Ctrl+C in the application terminal to stop the server. Stop PostgreSQL only if you own that exact cluster and no other consumer needs it. Ordinary shutdown does not remove the database.

To resume, use the installed environment and the same private database configuration, then run `serve`. Do not initialize, migrate or seed during ordinary restart. Sessions retain their actual expiry and may require another sign-in.

Version 0.9.0 continues to use schema 4. An existing schema-4 local workspace needs no migration or reseeding. Install the selected release into another new environment, stop the old application, load the retained database configuration and start the new application. Preserve its original credentials and records. Do not run `seed` as an upgrade or password-reset command.

An older schema 1, 2 or 3 needs an explicit stopped-application migration to schema 4. Preserve a private database backup first, install into a new environment, load that dedicated database's retained configuration, then run:

```powershell
& $python -I -m shipment_workspace.cli migrate
if ($LASTEXITCODE -ne 0) { throw 'Migration failed. Keep the application stopped and inspect the error.' }
& $python -I -m shipment_workspace.cli serve --port 8765
```

Migration preserves the existing account population and workflow. It does not create a public visitor identity. Do not use public-demo provisioning against that existing local workspace.

The package is MIT licensed and retains third-party notices, also served at `/third-party-notices`. Python dependency wheels and PostgreSQL are installed separately. The [native backup/restore guide](backup-and-restore.md) remains qualified only for the v0.8.0 Windows/PostgreSQL 18.1 direct-loopback, same-cluster route. This application release does not qualify managed-service restore, native Linux restoration, cross-version restoration, disaster recovery or production backups.
