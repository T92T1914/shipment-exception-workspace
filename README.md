# Shipment Exception Workspace

A small React and Python application for creating, finding, inspecting,
assigning and resolving synthetic shipment exceptions. Two seeded organizations
have separate records.
PostgreSQL stores the workflow, audit history, sessions and retry receipts.

The useful part is what happens when a change goes wrong. An older browser tab
cannot overwrite a newer edit. If a request commits but its response is lost,
an authorized retry of the same change returns the saved result without creating
a second exception or event. The exception, audit event and saved response share one
database transaction.

This is an engineering demonstration with synthetic data. It has no carrier
integration or operational users. [Executed verification](docs/VERIFICATION.md)
records the tested revision and results. [Design](docs/DESIGN.md) explains the
authorization and transaction boundaries.

Start with the [download and local installation guide](docs/install.md) or the
[v0.9.0 operator walkthrough](docs/operator-walkthrough.md). The walkthrough shows
actual creation, conflicting edits, an interrupted response, receipt replay and
resolution in the installed application.

[Open the hosted synthetic demo](https://shipment-employer-demo.onrender.com/)
and choose **Enter synthetic demo**. It supplies its separate public reviewer
credential. Browse the Northline queue, search references, inspect details and
history, then sign out. Do not enter real shipment or personal data.

The v0.9.0 hosted route passed actual HTTPS, reviewer-denial, desktop/narrow and
provider-restart checks on October 27, 2026. The
[hosted acceptance record](docs/hosted-demo.md) separates those results from
local staging and the operator walkthrough. Business writes and receipt replay
are denied by the server. The [deployment guide](docs/deployment.md) records the
explicit database/setup route, including Render's successful-deployment
prerequisite for one-off jobs.

The [public-mode desktop](docs/assets/v0.9.0/public-desktop-light.png) and
[narrow dark](docs/assets/v0.9.0/public-narrow-dark.png) captures show installed
v0.9.0 staging on October 26, 2026, at candidate `ff0935c`. Their saved history
is labeled provisioned synthetic fixture data. The separate operator walkthrough
records actual API actions and recovery.

[Read in another language](https://github.com/T92T1914/T92T1914/blob/main/TRANSLATION.md).

<a href="https://t92t1914.github.io/shipment-exception-workspace/">
  <picture>
    <source media="(max-width: 700px)" srcset="docs/assets/workflow-obscur-narrow.png">
    <img src="docs/assets/workflow-obscur-wide.png" alt="Synthetic intake creates version 1. After Sam assignment, current access and expected version 2 admit Casey assignment. Version 3, history and receipt commit together. A matching retry adds no event; later resolution reaches version 4." width="1800">
  </picture>
</a>

This conceptual example follows the [installed operator walkthrough](docs/operator-walkthrough.md):
creation, two assignments and resolution leave a version-4 record with four
history events. Current authorization and version checks guard a change. The
record, new event and response receipt commit together. A still-authorized
same-intent retry uses the original key and body, then refreshes current state.
Session or access recovery does not automatically POST a business change.
[Explore the static project page](https://t92t1914.github.io/shipment-exception-workspace/),
[read the design](docs/DESIGN.md), or inspect the
[diagram explanation and source](docs/workflow-explainer.md) and [rendering record](docs/workflow-rendering.json).
The static page explains the project; it does not host the application.

<p align="center">
  <a href="docs/operator-walkthrough.md">
    <img src="docs/assets/v0.9.0/operator-05-narrow-resolved.png" alt="Dark appearance of the installed v0.9.0 operator walkthrough: a resolved version-4 synthetic exception with creation, two assignments and resolution history" width="390">
  </a>
</p>

This dark capture shows the installed v0.9.0 operator walkthrough at 390 pixels
wide. The resolved version-4 record retains all four history events. The
[walkthrough](docs/operator-walkthrough.md#capture-identity-and-limits) records
the capture source, wheel identity and execution limits. It is a local
demonstration, separate from the hosted reviewer's provisioned fixtures and
[hosted checks](docs/hosted-demo.md).

The earlier v0.2.0 [desktop intake](docs/assets/desktop-intake.png) and
[narrow intake](docs/assets/mobile-intake.png) captures remain available. Later
queue and login captures are linked below. The v0.1.0 captures also remain in
`docs/assets` with their original bytes.

## The workflow

1. Sign in to one of the two synthetic organizations.
2. Search shipment references and summaries, filter by status, and use
   **Next page** and **Previous page** to browse the matching queue.
3. As an operator, choose **New exception** and enter a shipment reference,
   summary, details and priority. Saving opens the new record with its creation
   event at version 1.
4. Assign it to a member of the same organization, then resolve it with a short
   explanation. The detail view retains the version and
   saved history after a reload. Use **Older changes** and **Newer changes** to
   inspect a long history in pages of up to 20 changes.
5. If another tab changes the record first, refresh before editing again. If a
   response is interrupted, use **Retry same change** while that page retains
   the same session. An account/session transition retires that local retry.

The desktop view shows the queue beside the selected record. Narrow screens
switch between the queue and detail view. Operators can change the workflow.
Read-only reviewers can search the queue and inspect records and their history.

The [desktop reviewer](docs/assets/desktop-reviewer.png) and
[narrow reviewer](docs/assets/narrow-reviewer.png) captures show that view with
synthetic saved history.

## Operator and reviewer access

The account's current database role determines what it can do. Sign-in and
session responses include that role, and **Refresh workspace** refreshes access
as well as records. The cookie does not carry a trusted client-selected role.

| Action within the account's organization | Operator | Reviewer |
| --- | --- | --- |
| Sign in and sign out | Yes | Yes |
| Browse/search the queue, inspect details/history and list members | Yes | Yes |
| Create, assign, unassign or resolve an exception | Yes | No |
| Replay a saved mutation response | Yes | No |
| Be selected as an assignee | Yes | Yes |

Roles restrict the actor, not who may receive an assignment. Operators can
assign any member of the same organization, including a reviewer. Both roles
retain the organization boundary. There is no role-administration interface.

For valid mutation requests with the required CSRF token and retry key, the
server checks current operator access inside the write transaction before
reserving or reading a receipt. A reviewer receives HTTP 403 `read_only`, with
no exception, event or receipt change from that attempt. Hiding buttons is only
a UI affordance; the server enforces this rule independently.

An operator tab can become stale after its database role changes. On an explicit
`read_only` response, the UI retires its local pending change and shows read-only
access. A successful session check that learns reviewer access also retires a
pending or in-flight operator change, rejects its delayed completion and restores
reading, refresh and sign-out. Either path preserves the warning that an earlier
attempt may already have committed. Inspect saved records before new work.
Permission refresh performs no automatic mutation retry. Ordinary uncertain
operator requests still retain their original key and body while their session
and operator access remain current.

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

## Browse change history

Opening a record starts with its latest 20 saved changes. Each page lists those
changes from oldest to newest, with **Older changes** and **Newer changes** to
move between pages. The displayed count describes that page. A record's current
version and details remain separate from an older history page.

The first page establishes a version boundary for that browse. Later changes
stay outside it until **Refresh workspace**, which reloads current access,
details and the latest history. An operator's saved mutation also starts a new
history browse. Reading another history page preserves an unsent assignment or
resolution draft. A failed page request has its own **Retry history page** action
and leaves the current record available.

The detail API returns its latest 20 events in `events`, plus `history` metadata
with `next_cursor`, `page_size` and `through_version`. The continuation route is
`GET /api/exceptions/{id}/history?limit=20&cursor=...`; its default is 20 and its
maximum is 50. Both routes check the authenticated organization and permit
reviewers to read their own records. A cursor supplies a position, never access.

The version boundary holds back later application appends. It does not freeze
joined user names or create a full database snapshot. This limits returned and
rendered events without claiming a database scan, latency or load bound. See the
[history design](docs/DESIGN.md#bounded-change-history) and
[limitations](docs/LIMITATIONS.md). The [desktop history](docs/assets/desktop-history.png)
and [narrow history](docs/assets/narrow-history.png) captures use a dedicated
synthetic long-history record.

## Keep tabs aligned with the current session

Browser tabs share this application's cookie. Signing out or signing into a
different account in one tab can therefore change the session used by another
open tab. The UI rechecks the current session after a cross-tab change hint,
when a visible page regains focus, and when a restored page becomes active.
It also handles a server-reported context mismatch. A hint retires the old
private view before the server check, rather than supplying a new identity.

When an account or session change is observed, the page clears its old queue,
record, history, forms and local retry intent. It adopts the server's current
session and starts the current account's workspace. Delayed responses from the
retired context cannot restore the old view. A failed recheck leaves an explicit
**Check current session** recovery action instead of an unconfirmed workspace.

An explicit **Refresh workspace** shares that session-check owner, including a
queued lifecycle check. A matching focus check cannot silently discard the
requested refresh. Once checking settles, the same current session can reload
the queue, selected record and latest history. A failed check hides the
unconfirmed workspace and requires **Check current session** before browsing
again. This coordination sends no automatic business POST.

An earlier interrupted change may already be saved. Retiring its local retry
does not undo that change or establish its outcome. The message preserves that
uncertainty, and session recovery performs no automatic business POST. Review
saved records under the current account before new work.

Login/session payloads include a non-authorizing `session_context`. The UI sends
it as `X-Workspace-Context` on subsequent API requests. If a supplied context no
longer matches the current cookie session, protected requests receive HTTP 409
`session_changed`; expired or absent authentication still receives 401. Existing
API consumers may omit the header. The cookie, CSRF token and current server
organization/role checks remain authoritative. A matching marker does not mean
the account's database role or organization has remained unchanged.

The cross-tab channel carries only a small session-change hint, with no token,
context marker, identity or shipment data. It is an advisory same-origin browser
mechanism, not cross-device push or instant revocation. If the channel is missing
or fails, request-context checks, explicit refresh and visible-page checks remain
available. Frozen pages cannot be promised immediate cleanup, and concurrent
authentication responses are not serialized by this feature. See the
[session design](docs/DESIGN.md#shared-browser-session-coherence) and
[limits](docs/LIMITATIONS.md).

The [desktop session-change](docs/assets/desktop-session-change.png) and
[narrow session-change](docs/assets/narrow-session-change.png) captures show
the current-account recovery message using synthetic records.

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
also allow bursts across a boundary. Ordinary local mode has no general API or
anonymous-session limiter. Public mode adds the separate API/session controls in
the [deployment guide](docs/deployment.md). See the
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
$state = Join-Path $env:LOCALAPPDATA 'shipment-exception-workspace-local-v090'
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
& $consumerPython -m pip install -r requirements-lock.txt .\dist\shipment_exception_workspace-0.9.0-py3-none-any.whl

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

| Organization | Operators | Read-only reviewer |
| --- | --- | --- |
| Northline Logistics | `alex@northline.example`, `sam@northline.example` | `casey@northline.example` |
| Harbor Supply | `jules@harbor.example`, `robin@harbor.example` | `taylor@harbor.example` |

The names, email addresses and shipment records are synthetic. The password
must contain at least 12 characters. Repeating `seed` preserves existing
passwords, roles and workflow state. It is not a password reset or role-management
command.

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
/path/to/private/consumer-env/bin/python -m pip install -r requirements-lock.txt dist/shipment_exception_workspace-0.9.0-py3-none-any.whl
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

Version 0.9.0 continues to use schema version 4. An existing schema 1, 2 or 3 database
needs the explicit migration below. Stop every application process using the
dedicated database before changing its installed environment, and make a private
backup with your PostgreSQL backup tooling before migration. Keep
the backup, connection record and existing credentials outside Git. The migration
command does not make a backup, and this release does not qualify a
general backup-restoration or downgrade procedure. The separate
[local backup and restore guide](docs/backup-and-restore.md) defines a bounded
PostgreSQL 18.1, same-owner, same-cluster route qualified with v0.8.0 and its
tagged tools. It uses a distinct empty target and never initializes or seeds
over restored state. This v0.9.0 deployment extension does not claim a newly
executed native restore combination.

Build the v0.9.0 wheel as above, then install it into a new environment. Here,
`$state` names the existing private state directory, not the fresh-start example.
Load `SHIPMENT_DATABASE_URL` from the retained connection record for the existing
consumer database. Do not point it at another project or rerun the first-start
database helper over existing state.

```powershell
$upgradeEnv = Join-Path $state 'consumer-env-v090'
if (Test-Path -LiteralPath $upgradeEnv) { throw 'Choose a new unused environment path.' }
py -3.13 -m venv $upgradeEnv
$upgradePython = Join-Path $upgradeEnv 'Scripts\python.exe'
& $upgradePython -m pip install -r requirements-lock.txt .\dist\shipment_exception_workspace-0.9.0-py3-none-any.whl
```

For schema 1, 2 or 3, run the explicit migration before serving. An existing
schema 4 database needs no further migration.

```powershell
& $upgradePython -m shipment_workspace.cli migrate
if ($LASTEXITCODE -ne 0) { throw 'Migration failed. Keep the application stopped and inspect the error.' }
```

Start the new installed environment against the retained connection record:

```powershell
& $upgradePython -m shipment_workspace.cli serve
```

The command upgrades schema 1, 2 or 3 to schema 4 in one transaction, applying
earlier audit/admission changes when needed and adding the role column. Existing
users retain operator access. A future user inserted without an explicit role
defaults to reviewer. The migration preserves existing records, password hashes,
sessions, audit events and retry
receipts, including their original fingerprint bytes. Repeating `migrate` on
schema 4 makes no further change. An unsupported version is refused. `init`,
`seed` and `serve` require the current schema and do not silently upgrade an old
database. Upgrade tests use disposable fixtures, rather than modifying a
previously accepted local consumer database.

Migration preserves the existing user population rather than adding the two
fresh-demo reviewer accounts. Do not run `seed` as an upgrade step.
Neither migration nor seeding invents
creation history for existing records. New manually entered exceptions receive
a creation event, while older seeded records keep their actual saved history.
For a POSIX installation using schema 1, 2 or 3, invoke
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

The suite includes operator/reviewer access, role-change ordering, denied receipt
replay, organization isolation, session/context and CSRF rejection, stale
versions, creation and reference races, conflicting retry keys, rollback and
schema-upgrade preservation. History checks cover bounded detail responses,
complete older-page traversal, strict untrusted cursors and a version fence
across later appends. Session-context checks cover rotation, stale-context
denials without new business/receipt effects, current-role enforcement and
backward-compatible header omission. Installed consumer and headless acceptance exercise
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

Reviewer browser scenarios also require `WORKSPACE_ROLE_FIXTURE_URL` pointing
to that same dedicated synthetic consumer. Its helper checks schema 4 and the
exact six-account identity/organization set, then changes only Alex's role for
the demotion/promotion cases. It resets no domain records, sessions, history or
receipts and supplies no HTTP endpoint. The guard is not permission to use it
against a retained accepted consumer or other data.

History scenarios require `WORKSPACE_HISTORY_FIXTURE_URL` pointing to that same
fresh disposable installed consumer. The helper checks schema 4 and the exact
six-account identity/organization set, creates only its designated
`NL-HISTORY-001` record with 45 synthetic events, then permits one controlled
append at version 46. Those events are test setup, not real operational history
or requests made through the application. Existing workflow, sessions and retry
receipts are not reset. It exposes no HTTP control and is not a recovery tool.

After preparing that dedicated installed consumer and its private environment,
the browser setup includes all fixture targets explicitly:

```powershell
$env:WORKSPACE_FIXTURE_PYTHON = $consumerPython
$env:WORKSPACE_LOGIN_FIXTURE_URL = $db.consumer_url
$env:WORKSPACE_QUEUE_FIXTURE_URL = $db.consumer_url
$env:WORKSPACE_ROLE_FIXTURE_URL = $db.consumer_url
$env:WORKSPACE_HISTORY_FIXTURE_URL = $db.consumer_url
```

The same variable names apply to the POSIX route. These fixture values contain
credentials. Use only the fresh disposable browser database and keep them out of
public logs. The configured browser route is isolated, headless and one worker.
See the verification record for its exact installed-consumer preparation,
base URL, generated password, browser executable and executed results.

The queue fixture inserts 54 Northline and four Harbor records and refuses a
database already containing its reference prefixes. It adds no invented audit
events. This is test setup that changes its target database, not a recovery or
maintenance tool. Never point it at a retained accepted consumer or another
project's database. The larger fixture exercises page behavior and isolation;
it is not a load test or performance measurement.

## Boundaries and licenses

This version supports one small synthetic workflow and a separate read-only
public-demo mode. It has no registration,
password recovery, role administration, reopen action or production
deployment route. The audit history is an application record, not a tamper-proof
compliance log. [Limitations](docs/LIMITATIONS.md) and [security notes](SECURITY.md)
describe the remaining boundaries.

Project source is [MIT licensed](LICENSE). Dependency licenses remain their own.
The wheel includes the MIT notices for the React code in its frontend bundle.
Psycopg and psycopg-binary are unmodified LGPL dependencies installed separately.
PostgreSQL is not bundled. See [third-party notices](THIRD_PARTY_NOTICES.txt),
also available from the running application at `/third-party-notices`.
