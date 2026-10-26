# Security

Shipment Exception Workspace demonstrates a synthetic workflow. Ordinary local
use keeps the CLI's loopback binding and a dedicated PostgreSQL database. The
separate public reviewer mode requires the explicit
[deployment configuration](docs/deployment.md). Do not use real shipment,
customer, defense or other sensitive data in either mode.

The application enforces session authentication, organization-scoped object
access, current operator permission for mutations, CSRF checks, version conflicts
and actor-scoped idempotent mutations.
Composite database constraints and transactions support those boundaries.
[Design](docs/DESIGN.md) describes their implementation.

Manual intake accepts bounded reference, summary, details and priority fields.
The server chooses the organization, actor, ID and initial state, and rejects
extra fields. Creation, its audit event and retry response commit together.
References remain case-sensitive within their organization. These are bounded
integrity rules, rather than a general duplicate-detection or abuse-prevention
system.

These controls have a specific tested scope. The public mode is a synthetic
demonstration, with no production-security qualification, multifactor
authentication, password recovery or
tamper-proof audit log. See [limitations](docs/LIMITATIONS.md) and the
[executed verification record](docs/VERIFICATION.md) before interpreting a
security claim.

## Operator and reviewer boundaries

Public mode admits only the separately provisioned visitor identity in Northline.
Its public password does not unlock any of the six ordinary seed accounts.
Every public-mode business transaction refuses writes and receipt replay before
receipt access, independently of hidden UI controls or a subsequently changed
role. Ordinary local operator permissions remain separate. Public history is
explicitly provisioned synthetic fixture data, not operational activity.

Operators and read-only reviewers can inspect their organization's queue,
details, history and members and can sign out. Only operators can create,
assign, unassign, resolve or replay a saved mutation response. Any member of the
same organization remains eligible as an assignee. The role limits the actor's
permission, not the recipient of an assignment.

The server reads role from the current user row. Headers, body fields and UI
controls do not grant permission. After normal model, Origin, CSRF and retry-key
checks, each business transaction locks the actor row with `FOR SHARE` and checks
its current organization and operator role before receipt reservation/lookup or
business writes. A valid reviewer attempt receives HTTP 403 `read_only` without
changing an exception, event or receipt. Foreign and missing mutation targets
receive the same denial before lookup. Read-only detail requests keep the usual
organization-scoped 404 behavior.

The lock orders ordinary role updates against the mutation transaction. A
mutation that already holds it can commit before a waiting role update. A role
update that commits first is visible to the subsequent locking permission read.
This is not instantaneous revocation, cancellation of a committed request or
protection from a privileged database operator. There is no public interface for
role administration or general policy engine.

The UI reflects the role and refreshes access when the workspace is refreshed.
An explicit `read_only` write/replay response retires the tab's local pending
intent and conservatively switches it to read-only access. An earlier
interrupted attempt may already be saved, so that denial is not proof of an
earlier failure. Current records remain available for manual inspection, and
permission refresh performs no automatic mutation retry. Other uncertain
operator requests preserve their original key and body while their session
context stays current.

An authoritative session check can learn reviewer access before a pending
operator request returns. Version 0.7.1 retires that local intent, its write
drafts and old response epoch, then restores the current reviewer's reading and
sign-out controls. A delayed completion cannot restore the retired view. The
warning still says that the earlier change may already be saved. This is client
recovery after an observed permission change, without a new authorization rule,
automatic replay or cancellation of an admitted transaction.

## Shared session and client state

The browser shares the HttpOnly session cookie across tabs. `session_context`
in login/session responses is separate, non-authorizing consistency metadata:
a domain-separated SHA-256 digest derived from the stored session token hash.
It is neither the bearer cookie, that stored hash nor the CSRF token. The server
accepts it only as an expected-context comparison, never as identity or permission.
It is stable for a session across API restart and rotates on login, including
same-actor login. A matching marker does not establish unchanged database role,
organization or permission.

If supplied, `X-Workspace-Context` must have exactly one parsed value of 64
lowercase hexadecimal characters matching the current cookie session. Invalid,
duplicate or stale values receive generic 409 `session_changed` without value
echoes. Protected routes still authenticate first, returning 401 for an absent
or expired session. Their comparison precedes private route results and business
receipt access/writes. Login checks its supplied context before CSRF/admission.
`GET /api/session` ignores it and supplies actual recovery state. Header omission
keeps existing API clients compatible. Current cookie, Origin/CSRF, organization
and operator checks remain independent authorities.

The UI attaches its expected context and retires stale response generations
after session changes. Session reconciliation compares actor and organization
relationships as well as the marker and obtains role from the current server
response. Reusing a marker does not preserve an old user's database privileges.
Private caches and drafts remain in memory and are cleared after an observed
transition. If a pending write is retired, its earlier attempt may already have
committed. The UI preserves that uncertainty and performs no automatic business
POST or replay under the next account.

Cross-tab notification uses only `{ v: 1, type: 'session-changed' }` on the named
same-origin channel. It includes no session marker, credential, identity, role,
organization or shipment data. A valid hint retires private state and requests
actual session state, rather than trusting a message to supply an identity.
Rechecks are coalesced, with focus, visible-page and persisted-page restoration
checks supporting recovery when a channel is absent or a hint is missed. Channel
creation/send failures are tolerated. A failed server check has an explicit
recovery action rather than an unconfirmed private workspace.

This is client/session coherence, not a server tenant-bypass claim or a new
authorization system. It does not guarantee immediate cleanup in frozen pages,
cross-device push, instantaneous revocation or ordered concurrent authentication
responses. Response headers such as `no-store` do not alone erase application
memory. See the [session design](docs/DESIGN.md#shared-browser-session-coherence)
and [limits](docs/LIMITATIONS.md).

## Queue queries and positions

Every queue page uses the organization from the authenticated session. Search,
status and a cursor can narrow that query, but cannot choose another
organization. The cursor's context is checked against the current request; it
does not replace session authentication or query scoping. Independent detail
requests retain the same organization boundary even when a record is outside
the current page or filters.

Queue responses contain at most 50 records, with a default of 20. Search input
is limited to 80 characters before trimming. Unknown or duplicate parameters,
invalid types or ranges, malformed cursors and NUL characters receive a generic
HTTP 422 response without echoing input. Cursor payloads require strict UTF-8,
while search values have already passed through framework URL decoding, which
can replace malformed percent-encoded bytes. Cursors are limited
to 2,048 characters. They use checked unpadded base64url transport for a flat
JSON object and reject duplicate keys and extra fields.

Search treats the reference and summary as literal text using `ILIKE` under
`C` collation, with ASCII case-insensitive matching. SQL parameters separate
input from SQL syntax; escaping `!`, `%` and `_` separately prevents those
characters from expanding the search pattern. Backslash remains literal.
Cursors are unsigned and readable positions, not secrets or authorization
credentials. The server does not look up an anchor row or trust a cursor to
establish object access.

The UI clears private search and page history when the account changes or signs
out, and ignores stale queue responses associated with an earlier user, query
or page. Page state is held in memory. Existing uncertain-mutation handling
continues to preserve the submitted key and body rather than changing the
meaning of an interrupted request.

The output cap does not bound database scanning, sorting or elapsed time. The
existing database statement timeout is a separate resource guard, not proof of
availability under load. Queue routes have no new rate limiter or index, and
this release makes no denial-of-service resistance or query-performance claim.

## History queries and positions

Detail responses include only the latest 20 events and continuation metadata.
The separate history route defaults to 20 and permits at most 50. Every remote
request authenticates the current session, resolves the exception within that
organization and independently scopes the event query. Operators and reviewers
can read their own records. Foreign and missing records receive the same 404
before history-cursor validation. A cursor cannot choose another organization
or supply authentication.

History cursors are readable, unsigned positions, with a 1,024-character cap
and checked unpadded base64url/strict UTF-8 transport. Their exact fields bind
organization, exception, page size, initial upper version and older-page
position. Duplicate keys, extra fields, invalid strict integers, malformed
encodings and mismatched context receive generic HTTP 422
`invalid_history_query` without input echoes. Unknown and duplicate query
parameters are rejected too. The server does not need an anchor lookup, and a
caller may construct another valid position inside its own record's history.

The initial version fence keeps later application appends out of an existing
browse until refresh. It does not freeze user names, provide a full database
snapshot or protect events from a privileged database operator. Pages retain
ascending order within the latest or older selected window. No total is
calculated. Bounded output does not establish a query-cost, latency, rate or
load guarantee, and history requests have no new rate limiter.

The UI renders one bounded event page, retaining the first page and current
page plus positions for visited pages. It does not persist them to browser
storage. Cursor metadata still grows with navigation. Record changes, refresh,
saved mutations and private-state clearing invalidate earlier history work.
Late responses must match the user, record and request generation before being
shown. A failed older-page request has a separate retry path and preserves the
current record and unsent draft. Returning to the cached first page within the
same browse is not another server permission check or instant revocation.

## Login admission and availability

Public mode adds a process-local API budget of five requests per second with a
burst of 30, plus a serialized database admission cap of 128 live session rows.
Anonymous sessions last five minutes and visitor sessions 30 minutes. Admission
cleans expired rows and checks the cap inside the same transaction. Replacement
login locks before deleting its old row. A refused transaction rolls back that
replacement. The configured demo origin must be canonical HTTPS. Session cookies
are Secure, HttpOnly and SameSite Strict. The configured Host is checked exactly,
and forwarded headers do not supply authority. Readiness does not allocate a
session. These controls bound the declared application work and live rows. They
do not bound physical database storage, network traffic or denial-of-service
exposure. Restart resets the process-local budget, not the durable login budget
or database session cap. Use one application process and one provider instance.

The server reserves a durable database slot before Argon2 verification, with
20 reservations per normalized identifier and 40 globally in each counter's
fixed 60-second window. Correct passwords count too. Success, a new anonymous
session and process restart do not reset these budgets. Reservations commit
before verification and are not refunded for later failure or interruption.
Admission storage errors prevent verification rather than bypassing the policy.

Known and unknown identifiers follow the same policy. The stored identifier is
SHA-256 of the trimmed, lowercased submitted email. This digest is not anonymity
for a guessable address. Passwords do not belong in admission state or logs.
Exact Origin, CSRF and input checks run before a request can spend a slot. No
IP address or untrusted `X-Forwarded-For` header chooses a budget.

A denied request receives a generic 429 and `Retry-After`. The responsive form
explains the temporary wait without resubmitting the password automatically.
Its countdown is a hint, and server admission is checked again on submission.

The global budget deliberately trades availability for bounded local password
work. A caller can exhaust it and temporarily block all new sign-ins. Fixed
windows allow boundary bursts. Ordinary local mode has no anonymous-session or
general API limiter. The public-mode controls above do not solve distributed attacks,
credential stuffing or broader availability. The 80-identifier-row bound is a
design derivation under the application's serialized writer and clock, not
measured attack resistance. This local policy is not authentication certification
or OWASP/NIST compliance. [Design](docs/DESIGN.md#durable-login-admission) records
the transaction and cleanup mechanism.

## Local secrets and test databases

Keep `SHIPMENT_DATABASE_URL`, demo passwords, cookies, CSRF tokens and the local
database helper's `connection.json` outside the checkout and outside public
issues, screenshots and logs. A database connection URL contains a credential.
The helper's external state directory is private local state, not a shareable
release artifact.

The API test fixtures truncate and reseed the configured test database. Migration
tests also drop and recreate its entire `public` schema, including contained
objects.
`SHIPMENT_TEST_DATABASE_URL` must point to a disposable database created for
these tests. Never use a retained consumer, existing project or operational
database.

Some admission checks manipulate counter expiries or use a controlled database
clock to exercise boundaries. These are synthetic fixtures, separate from any
recorded real-time or installed-process checks. They do not demonstrate live
attack resistance.

The queue browser fixture inserts 54 Northline and four Harbor records in a
fresh disposable installed consumer database, without fabricated audit events.
It requires `WORKSPACE_QUEUE_FIXTURE_URL` and refuses existing fixture reference
prefixes. Browser scenarios use `WORKSPACE_FIXTURE_PYTHON` for the installed
Python executable; admission scenarios separately use
`WORKSPACE_LOGIN_FIXTURE_URL`. These are private test inputs, not public HTTP
endpoints. The helper changes its target database, and its refusal check does
not make it safe for a retained accepted consumer or another project's data.

The role browser fixture separately requires `WORKSPACE_ROLE_FIXTURE_URL`. It
checks schema 4 and the exact six synthetic account IDs, organizations and
emails, then changes only Alex's role for its demotion/promotion scenarios. It
does not reset domain records, sessions, history or receipts and supplies no
HTTP control endpoint. Its guard does not make it safe for a retained accepted
consumer or another project's data.

The history browser fixture requires `WORKSPACE_HISTORY_FIXTURE_URL`, schema 4
and that same exact six-account identity set. It creates only its designated
`NL-HISTORY-001` record with 45 synthetic events and permits one controlled
append at version 46. Setup refuses an existing designated record. These are
labeled fixture events rather than operational history or requests through
the API. Existing workflow, sessions and receipts are not reset. Run it only
against a fresh disposable browser consumer, never a retained accepted database.
It provides no HTTP control or recovery operation.

The demo seeder requires a password of at least 12 characters. Repeated seeding
does not change an existing account's password or role. Use fresh isolated demo
state
when you need a clean acceptance run.

## Schema upgrades

Version 0.9.0 retains schema version 4. For schema 1, 2 or 3, stop every
application process using the dedicated database and take a private backup before
running the installed
wheel's explicit `migrate` command. Keep its connection record and credentials.
Initialization, seeding and server startup do not silently upgrade an older schema.
Do not use seeding as an upgrade or password-reset step.

The bounded migration upgrades schema 1, 2 or 3 to 4 in one transaction, applying
earlier audit/admission changes when needed and adding roles. Existing users
retain operator access. Future user inserts without a role default to reviewer.
It preserves existing domain rows, password hashes, audit events, sessions and retry receipts,
including old fingerprint bytes, without backfilling fictional creation history.
Preserved sessions still obey their original expiry and logout behavior. A
receipt replay still needs a current authenticated session, current operator
permission, correct Origin and CSRF token. Migration does not add the two fresh-demo reviewer
accounts to an existing database, and seeding is not an upgrade step. There is
no downgrade route. The separate v0.8.0 Windows/PostgreSQL 18.1
[restore guide](docs/backup-and-restore.md) remains the bounded native
qualification, with no managed-service restore claim. See the
[existing-database instructions](README.md#use-an-existing-database) and check
the executed evidence before interpreting preservation as a broader recovery
guarantee. Upgrade acceptance uses disposable legacy fixtures and does not require
changing a retained accepted local consumer database.

## Reporting a problem

Share a minimal synthetic reproduction, the affected revision, expected behavior
and observed behavior. Remove credentials, session values, connection URLs and
real records from any public report. Do not test against other people's systems.

A private reporting channel is not promised by this repository. If GitHub offers
private vulnerability reporting for it, use that route for sensitive details.
Otherwise arrange a private channel with the maintainer before sending those
details. A public issue can describe a sanitized symptom without including a
working secret or another person's data.
