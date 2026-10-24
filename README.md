# Shipment Exception Workspace

A small React and Python application for creating, finding, inspecting,
assigning and resolving synthetic shipment exceptions. Two seeded organizations
have separate records.
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

![Manually created synthetic exception with creation, assignment and resolution history](docs/assets/desktop-intake.png)

The [narrow-mobile capture](docs/assets/mobile-intake.png) shows the same intake
workflow on a 390-pixel-wide viewport. The earlier v0.1.0 captures remain in
`docs/assets` with their original bytes.

## The workflow

1. Sign in to one of the two synthetic organizations.
2. Search shipment references and summaries, filter by status, and use
   **Next page** and **Previous page** to browse the matching queue.
3. Choose **New exception** and enter a shipment reference, summary, details and
   priority. Saving opens the new record with its creation event at version 1.
4. Assign it to a member of the same organization, then resolve it with a short
   explanation. The detail view retains the version and
   audit history after a reload.
5. If another tab changes the record first, refresh before editing again. If a
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

## Browse the queue

The UI shows up to 20 records at a time. Search matches literal text in the
reference or summary, with ASCII letters compared without case. The submitted
search is limited to 80 characters before outer whitespace is removed. `%`, `_`,
`!` and backslash remain literal characters. This is not full-text search or
Unicode case folding, and creation still treats differently cased references as
distinct.

Submit a search with Enter or **Search queue**, then use **Show exceptions** to
choose a status. The same controls are available in the narrow-screen queue
view. **Clear search** keeps the current status and returns to the first page.

The API defaults to 20 records and permits at most 50 per page. A next-page
cursor carries the current search and status context. Every query uses the
organization from the authenticated session. The displayed count describes the
current page, not a total number of matching records.

A selected record can stay open outside the current page or filters. Its detail
request is independent of queue membership. Refreshing, assigning or resolving
returns the queue to its first page with the current criteria. Creating an
exception clears the search and status filter, returns to the first page, and
opens the new record. Signing out clears private search and page history.

Pages are a live view. A record inserted before the current position needs a
refresh to appear, and a status change can move a record out of the results.
Previous pages are fetched again rather than restored from a snapshot. The
response bound does not establish a bound on database scanning, sorting or
latency. See the [queue design](docs/DESIGN.md#bounded-live-queue) and
[limitations](docs/LIMITATIONS.md).

The [desktop page-two capture](docs/assets/desktop-queue-page-two.png) and
[narrow literal-search capture](docs/assets/mobile-queue-literal.png) show the
larger synthetic queue used in the installed browser checks.

## Sign-in admission

Before checking a password, the server reserves a PostgreSQL admission slot.
It permits 20 verifications per normalized email and 40 across the application
in each counter's fixed 60-second window. Email normalization removes outer
whitespace and lowercases the address. Known and unknown addresses follow the
same policy. A successful sign-in uses a slot too and does not reset either
budget. New browser sessions and API restarts do not reset the saved counters.

When a budget is full, the API returns a generic HTTP 429 and `Retry-After`.
The sign-in form shows a temporary wait and keeps the email editable. Its
countdown is a local reminder, and the server decides whether the next explicit
submission is allowed. The UI does not retry a password automatically.

The [desktop cooldown](docs/assets/desktop-login-throttled.png) and
[narrow-mobile cooldown](docs/assets/mobile-login-throttled.png) captures show
the exercised wait state with synthetic credentials.

This bounds one kind of local password-verification work. One caller can spend
the global budget and temporarily block other users' new sign-ins. Fixed windows
also allow bursts across a boundary. Other routes, including anonymous-session
creation, are not rate-limited by this policy. See the
[design](docs/DESIGN.md#durable-login-admission) and
[limits](docs/LIMITATIONS.md) before treating it as broader abuse protection.

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
& $consumerPython -m pip install -r requirements-lock.txt .\dist\shipment_exception_workspace-0.4.0-py3-none-any.whl

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
/path/to/private/consumer-env/bin/python -m pip install -r requirements-lock.txt dist/shipment_exception_workspace-0.4.0-py3-none-any.whl
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

## Use an existing database

Version 0.4.0 keeps schema version 3. A v0.3.0 database needs no migration. This
release adds no queue index. Stop every application process using the dedicated
database before changing its installed environment. If it still uses schema 1 or 2,
make a private backup with your PostgreSQL backup tooling before migration. Keep
the backup, connection record and existing credentials outside Git. The migration
command does not make a backup, and this release does not qualify a
backup-restoration or downgrade procedure.

Build the v0.4.0 wheel as above, then install it into a new environment. Load
`SHIPMENT_DATABASE_URL` from the retained connection record for the existing
consumer database. Do not point it at another project or rerun the first-start
database helper over existing state.

```powershell
$upgradeEnv = Join-Path $state 'consumer-env-v040'
py -3.13 -m venv $upgradeEnv
$upgradePython = Join-Path $upgradeEnv 'Scripts\python.exe'
& $upgradePython -m pip install -r requirements-lock.txt .\dist\shipment_exception_workspace-0.4.0-py3-none-any.whl
```

For schema 1 or 2, run the explicit migration before serving. Skip this step for
an existing schema 3 database.

```powershell
& $upgradePython -m shipment_workspace.cli migrate
if ($LASTEXITCODE -ne 0) { throw 'Migration failed. Keep the application stopped and inspect the error.' }
```

Start the new installed environment against the retained connection record:

```powershell
& $upgradePython -m shipment_workspace.cli serve
```

The command upgrades schema 1 or 2 to schema 3 in one transaction, applying the
earlier audit-constraint upgrade when needed and adding admission state. It
preserves existing records, password hashes, sessions, audit events and retry
receipts, including their original fingerprint bytes. Repeating `migrate` on
schema 3 makes no further change. An unsupported version is refused. `init`,
`seed` and `serve` require the current schema and do not silently upgrade an old
database. Upgrade tests use disposable fixtures, rather than modifying a
previously accepted local consumer database.

Do not run `seed` as an upgrade step. Neither migration nor seeding invents
creation history for existing records. New manually entered exceptions receive
a creation event, while older seeded records keep their actual saved history.
For a POSIX installation using schema 1 or 2, invoke
`bin/shipment-workspace migrate` from the newly installed environment before
starting its server. The accepted older consumer environments and databases do
not need to be changed to verify a new release.

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
Admission checks cover durable budgets, concurrent reservations, expiry and
temporary sign-in denial. Tests that control counter timestamps or the database
clock are synthetic boundary checks, not measurements of attack resistance or
real elapsed-time throughput.
See [verification](docs/VERIFICATION.md) for commands, actual outcomes and limits.

The additional queue browser scenarios require a fresh disposable installed
consumer database. `WORKSPACE_QUEUE_FIXTURE_URL` explicitly chooses that database,
and `WORKSPACE_FIXTURE_PYTHON` names the installed environment's Python executable
used by the fixture helper. Admission browser scenarios separately use
`WORKSPACE_LOGIN_FIXTURE_URL`. These connection URLs contain credentials and
belong outside Git and public logs.

The queue fixture inserts 54 Northline and four Harbor records and refuses a
database already containing its reference prefixes. It adds no invented audit
events. This is test setup that changes its target database, not a recovery or
maintenance tool. Never point it at a retained accepted consumer or another
project's database. The larger fixture exercises page behavior and isolation;
it is not a load test or performance measurement.

## Boundaries and licenses

This version supports one small local workflow. It has no registration,
password recovery, permission roles, reopen action or production
deployment route. The audit history is an application record, not a tamper-proof
compliance log. [Limitations](docs/LIMITATIONS.md) and [security notes](SECURITY.md)
describe the remaining boundaries.

Project source is [MIT licensed](LICENSE). Dependency licenses remain their own.
The wheel includes the MIT notices for the React code in its frontend bundle.
Psycopg and psycopg-binary are unmodified LGPL dependencies installed separately.
PostgreSQL is not bundled. See [third-party notices](THIRD_PARTY_NOTICES.txt),
also available from the running application at `/third-party-notices`.
