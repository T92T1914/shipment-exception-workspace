# Shipment Exception Workspace

A small React and Python application for inspecting, assigning and resolving
synthetic shipment exceptions. Two seeded organizations have separate records.
PostgreSQL stores the workflow, audit history, sessions and retry receipts.

The useful part is what happens when a change goes wrong. An older browser tab
cannot overwrite a newer edit. If a request commits but its response is lost,
retrying the same change returns the saved result without creating a second
event. The exception update, audit event and saved response share one database
transaction.

This is a local engineering demonstration with synthetic data. It has no carrier
integration or operational users. [Executed verification](docs/VERIFICATION.md)
records the tested revision and results. [Design](docs/DESIGN.md) explains the
authorization and transaction boundaries.

![Desktop queue and resolved synthetic exception](docs/assets/desktop.png)

The [narrow-mobile capture](docs/assets/mobile.png) shows the same workflow on
a 390-pixel-wide viewport.

## The workflow

1. Sign in to one of the two synthetic organizations.
2. Open an exception and assign it to a member of that organization.
3. Resolve it with a short explanation. The detail view retains the version and
   audit history after a reload.
4. If another tab changes the record first, refresh before editing again. If a
   response is interrupted, use **Retry same change** while that page remains open.

The desktop view shows the queue beside the selected record. Narrow screens
switch between the queue and detail view. All members within an organization
have the same permissions.

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
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build
& $buildPython tools/build_notices.py
& $buildPython -m build --no-isolation

py -3.13 -m venv (Join-Path $state 'consumer-env')
$consumerPython = Join-Path $state 'consumer-env\Scripts\python.exe'
& $consumerPython -m pip install -r requirements-lock.txt .\dist\shipment_exception_workspace-0.1.0-py3-none-any.whl

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
GOMAXPROCS=2 npm --prefix frontend run build
/path/to/private/build-env/bin/python tools/build_notices.py
/path/to/private/build-env/bin/python -m build --no-isolation
python3.13 -m venv /path/to/private/consumer-env
/path/to/private/consumer-env/bin/python -m pip install -r requirements-lock.txt dist/shipment_exception_workspace-0.1.0-py3-none-any.whl
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

## Checks that matter

The API tests require actual PostgreSQL. They truncate and reseed their target
database, so `SHIPMENT_TEST_DATABASE_URL` must name a disposable test database.
With the helper above, that is `$db.test_url`. The consumer database is separate.
An unset test URL causes the database tests to skip, which is not a database pass.

```powershell
$env:SHIPMENT_TEST_DATABASE_URL = $db.test_url
& $consumerPython -m pytest tests
```

The suite exercises organization isolation, session and CSRF rejection, stale
versions, conflicting retry keys, concurrent submissions and transaction rollback.
The installed consumer starts a wheel outside the checkout, restarts the API
process and retries a committed request. Headless browser journeys cover desktop,
narrow mobile, stale tabs and interrupted responses against the built application.
See [verification](docs/VERIFICATION.md) for commands, actual outcomes and limits.

## Boundaries and licenses

This first version supports one small local workflow. It has no registration,
password recovery, permission roles, reopen action, pagination or production
deployment route. The audit history is an application record, not a tamper-proof
compliance log. [Limitations](docs/LIMITATIONS.md) and [security notes](SECURITY.md)
describe the remaining boundaries.

Project source is [MIT licensed](LICENSE). Dependency licenses remain their own.
The wheel includes the MIT notices for the React code in its frontend bundle.
Psycopg and psycopg-binary are unmodified LGPL dependencies installed separately.
PostgreSQL is not bundled. See [third-party notices](THIRD_PARTY_NOTICES.txt),
also available from the running application at `/third-party-notices`.
