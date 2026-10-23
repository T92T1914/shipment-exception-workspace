# Shipment Exception Workspace

A small React and Python application for creating, inspecting, assigning and
resolving synthetic shipment exceptions. Two seeded organizations have separate
records.
PostgreSQL stores the workflow, audit history, sessions and retry receipts.

The useful part is what happens when a change goes wrong. An older browser tab
cannot overwrite a newer edit. If a request commits but its response is lost,
retrying the same change returns the saved result without creating a second
exception or event. The exception, audit event and saved response share one
database transaction.

This is a local engineering demonstration with synthetic data. It has no carrier
integration or operational users. [Executed verification](docs/VERIFICATION.md)
records the tested revision and results. [Design](docs/DESIGN.md) explains the
authorization and transaction boundaries.

![Desktop queue and resolved synthetic exception](docs/assets/desktop.png)

These v0.1.0 captures show the assignment and resolution workflow. The
[narrow-mobile capture](docs/assets/mobile.png) uses a 390-pixel-wide viewport.

## The workflow

1. Sign in to one of the two synthetic organizations.
2. Choose **New exception** and enter a shipment reference, summary, details and
   priority. Saving opens the new record with its creation event at version 1.
3. Assign it to a member of the same organization, then resolve it with a short
   explanation. The detail view retains the version and
   audit history after a reload.
4. If another tab changes the record first, refresh before editing again. If a
   response is interrupted, use **Retry same change** while that page remains open.

The desktop view shows the queue beside the selected record. Narrow screens
switch between the queue and detail view. All members within an organization
have the same permissions.

New reference, summary and details inputs lose outer whitespace. A reference is
unique within its organization and remains case-sensitive: `NL-2000` and
`nl-2000` are different references. Existing reference bytes are not rewritten.
The server chooses the organization, actor, ID and initial open, unassigned
state. The form cannot choose them.

An identical creation retry returns its saved HTTP 201 response and original ID.
That response remains historical if someone has since assigned or resolved the
record. The UI loads current state after success. A second request with another
key for an existing reference receives a conflict, and the form keeps its text
so the reference can be corrected.

## Build and run locally

The initial local combination uses CPython 3.13.3, Node 24.16.0, npm 11.13.0
and PostgreSQL 18.1. The Python lock and npm lock pin the application and build
dependencies. The executed evidence defines the qualified environment, rather
than a promise that every compatible version or platform works.

Run these PowerShell commands from the checkout. They put Python environments
and database state outside the source tree. PostgreSQL must already be installed.
The helper creates its own loopback cluster and two new databases. It does not
start or alter an installed PostgreSQL service.

```powershell
$state = Join-Path $env:LOCALAPPDATA 'shipment-exception-workspace-local'
py -3.13 -m venv (Join-Path $state 'build-env')
$buildPython = Join-Path $state 'build-env\Scripts\python.exe'
& $buildPython -m pip install -r requirements-lock.txt
$env:GOMAXPROCS = '2'
$env:RAYON_NUM_THREADS = '2'
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build
& $buildPython tools/build_notices.py
& $buildPython -m build --no-isolation

py -3.13 -m venv (Join-Path $state 'consumer-env')
$consumerPython = Join-Path $state 'consumer-env\Scripts\python.exe'
& $consumerPython -m pip install -r requirements-lock.txt .\dist\shipment_exception_workspace-0.2.0-py3-none-any.whl

$pgBin = 'C:\Program Files\PostgreSQL\18\bin'
$pgState = Join-Path $state 'postgres'
& $buildPython tools/local_postgres.py start --bin $pgBin --state $pgState
$db = Get-Content (Join-Path $pgState 'connection.json') -Raw | ConvertFrom-Json
$env:SHIPMENT_DATABASE_URL = $db.consumer_url
$env:SHIPMENT_DEMO_PASSWORD = [guid]::NewGuid().ToString('N')
$env:SHIPMENT_DEMO_PASSWORD | Set-Content (Join-Path $state 'demo-password.txt')
& $consumerPython -m shipment_workspace.cli init
& $consumerPython -m shipment_workspace.cli seed
& $consumerPython -m shipment_workspace.cli serve
```

Open `http://127.0.0.1:8765` in your own browser. The generated demo password is
in `demo-password.txt` under the private state directory. Each newly seeded
account uses that password:

| Organization | Accounts |
| --- | --- |
| Northline Logistics | `alex@northline.example`, `sam@northline.example` |
| Harbor Supply | `jules@harbor.example`, `robin@harbor.example` |

The names, email addresses and shipment records are synthetic. The password
must contain at least 12 characters. Repeating `seed` preserves existing
passwords and workflow state. It is not a password reset command.

Stop the application with Ctrl+C. From the checkout, stop only the helper's
owned database cluster with:

```powershell
& $buildPython tools/local_postgres.py stop --bin $pgBin --state $pgState
```

The helper deliberately refuses to overwrite an initialized state directory.
Preserve `connection.json` and its database directory when resuming that cluster.
Start that same data directory with PostgreSQL's `pg_ctl`, then load the retained
connection record and demo password. Do not rerun the first-start block over
existing state. Connection records and passwords belong outside Git.

For a POSIX shell, use the same source build with an isolated environment and
the `bin/python` executable layout:

```sh
python3.13 -m venv /path/to/private/build-env
/path/to/private/build-env/bin/python -m pip install -r requirements-lock.txt
GOMAXPROCS=2 npm --prefix frontend ci --ignore-scripts
GOMAXPROCS=2 RAYON_NUM_THREADS=2 npm --prefix frontend run build
/path/to/private/build-env/bin/python tools/build_notices.py
/path/to/private/build-env/bin/python -m build --no-isolation
python3.13 -m venv /path/to/private/consumer-env
/path/to/private/consumer-env/bin/python -m pip install -r requirements-lock.txt dist/shipment_exception_workspace-0.2.0-py3-none-any.whl
export SHIPMENT_DATABASE_URL='postgresql://USER:PASSWORD@127.0.0.1:PORT/DEDICATED_DATABASE'
export SHIPMENT_DEMO_PASSWORD='YOUR_PRIVATE_GENERATED_PASSWORD'
/path/to/private/consumer-env/bin/shipment-workspace init
/path/to/private/consumer-env/bin/shipment-workspace seed
/path/to/private/consumer-env/bin/shipment-workspace serve
```

Replace the placeholder paths and credentials with your own dedicated local
database. The CLI binds only to `127.0.0.1`. Use `serve --port 8766` if the default
port is occupied. The frontend is built into the wheel and served from the same
origin as the API, so the installed application needs no Vite development server.

## Upgrade an existing v0.1.0 database

Version 0.2.0 uses schema version 2. Stop every application process using the
dedicated database before upgrading. Keep PostgreSQL running and make a private
backup of that database with your PostgreSQL backup tooling. Keep the backup,
connection record and existing credentials outside Git. The migration command
does not make a backup, and this release does not qualify a backup-restoration
or downgrade procedure.

Build the v0.2.0 wheel as above, then install it into a new environment. Load
`SHIPMENT_DATABASE_URL` from the retained connection record for the existing
consumer database. Do not point it at another project or rerun the first-start
database helper over existing state.

```powershell
$upgradeEnv = Join-Path $state 'consumer-env-v020'
py -3.13 -m venv $upgradeEnv
$upgradePython = Join-Path $upgradeEnv 'Scripts\python.exe'
& $upgradePython -m pip install -r requirements-lock.txt .\dist\shipment_exception_workspace-0.2.0-py3-none-any.whl
& $upgradePython -m shipment_workspace.cli migrate
if ($LASTEXITCODE -ne 0) { throw 'Migration failed. Keep the application stopped and inspect the error.' }
& $upgradePython -m shipment_workspace.cli serve
```

The explicit transaction changes the version marker and audit constraints. It
preserves existing records, passwords, sessions, audit events and retry receipts,
including the original assignment and resolution fingerprints. Repeating
`migrate` on schema 2 makes no further change. An unsupported version is refused.
`init` and `serve` require the correct schema and do not silently upgrade schema 1.

Do not run `seed` as an upgrade step. Neither migration nor seeding invents
creation history for existing records. New manually entered exceptions receive
a creation event, while older seeded records keep their actual saved history.
For a POSIX installation, invoke `bin/shipment-workspace migrate` from the newly
installed environment before starting its server.

## Checks that matter

The API tests require actual PostgreSQL. They truncate and reseed their target
database, and migration tests drop and recreate its entire `public` schema.
`SHIPMENT_TEST_DATABASE_URL` must name a disposable test database.
With the helper above, that is `$db.test_url`. The consumer database is separate.
An unset test URL causes the database tests to skip, which is not a database pass.

```powershell
$env:SHIPMENT_TEST_DATABASE_URL = $db.test_url
& $consumerPython -m pytest tests
```

The suite includes organization isolation, session and CSRF rejection, stale
versions, creation and reference races, conflicting retry keys, rollback and
schema-upgrade preservation. Installed consumer and headless acceptance exercise
the built application outside the checkout, including desktop, narrow mobile,
stale tabs and interrupted responses.
See [verification](docs/VERIFICATION.md) for commands, actual outcomes and limits.

## Boundaries and licenses

This version supports one small local workflow. It has no registration,
password recovery, permission roles, reopen action, pagination or production
deployment route. The audit history is an application record, not a tamper-proof
compliance log. [Limitations](docs/LIMITATIONS.md) and [security notes](SECURITY.md)
describe the remaining boundaries.

Project source is [MIT licensed](LICENSE). Dependency licenses remain their own.
The wheel includes the MIT notices for the React code in its frontend bundle.
Psycopg and psycopg-binary are unmodified LGPL dependencies installed separately.
PostgreSQL is not bundled. See [third-party notices](THIRD_PARTY_NOTICES.txt),
also available from the running application at `/third-party-notices`.
