# Design

The application keeps one complete workflow small enough to inspect. React
renders intake, the queue and detail view. FastAPI authenticates every protected API
request and applies organization boundaries. PostgreSQL stores the durable
records and serializes changes to an individual exception.

The built frontend ships inside the Python wheel. A single loopback server
serves the UI and API from the same origin. The UI keeps no authentication token
in localStorage or sessionStorage. The installed route needs no credentialed
CORS configuration or separate frontend service.

## Identity and organization boundaries

An anonymous session supplies the CSRF token needed to sign in. A successful
login replaces that session with a new random cookie and a new CSRF token.
Passwords use Argon2id. Its parallelism is explicitly one, and the application's
synchronous handler limiter permits two concurrent handlers.

The cookie is opaque, HttpOnly and SameSite=Strict. PostgreSQL stores its SHA-256
digest, rather than its bearer value. Anonymous sessions expire after 15 minutes.
Authenticated sessions have an absolute eight-hour expiry. The server checks
expiry on each request, and logout deletes the server session.

The loopback HTTP route deliberately uses a cookie without the Secure flag.
That is a local development constraint. HTTPS settings require Secure cookies,
but a production HTTPS deployment has not been qualified.

Every state-changing request requires the configured exact Origin and a
synchronizer CSRF token from the current session. Requests must use JSON.
The server buffers at most 16 KiB of request body and returns generic validation
errors without echoing submitted credentials. API values never establish the
requester's identity or organization. The token and Origin checks follow the
[OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
with SameSite used as another layer rather than the only check.

List, detail, member and mutation queries take the organization from the server
session. An absent exception and another organization's exception both return
404 from the detail and mutation routes. All members in one organization have
the same creation, assignment and resolution permissions.

The schema also checks organization membership. Composite foreign keys bind an
exception's assignee and each event's actor, assignee and exception to the same
organization. These constraints reject a cross-organization assignment even if
an application check is accidentally omitted. They do not replace query scoping
or constitute PostgreSQL row-level security. PostgreSQL 18's
[constraint documentation](https://www.postgresql.org/docs/18/ddl-constraints.html)
describes the composite foreign-key mechanism.

## Durable login admission

`POST /api/login` reserves permission to perform a password verification before
calling Argon2. Each normalized identifier has a budget of 20, and the application
shares a global budget of 40. Each counter has a fixed 60-second window starting
with its first admitted request after expiry. Identifier and global expiries can
differ. This is an all-verification admission policy: correct and incorrect
passwords both use a reservation, and success never resets or refunds it.

The identifier uses the existing email lookup normalization, `strip().lower()`.
PostgreSQL stores a SHA-256 digest of that value in admission state. Known and
unknown addresses follow the same path. The digest avoids another plaintext
copy but does not anonymize a guessable email address or prevent dictionary
recovery. No submitted password belongs in these counters.

Session, exact Origin, CSRF and input checks precede admission. One short database
transaction locks the singleton global row, reads `clock_timestamp()` after that
lock has been acquired, removes expired identifier rows and checks both budgets.
A request may have waited for the lock, so transaction-start or pre-lock time
could place it in an expired window. An allowed request increments both counters
and commits before password verification. No lock is held during Argon2.

Denied requests create no new identifier row and do no password verification.
They commit expiry cleanup and return a generic 429 with a positive `Retry-After`
for the later of the blocking expiries. Denied requests do not extend a live
window. A storage failure propagates before verification rather than bypassing
admission. A process interruption after a committed reservation still consumes
that slot. Cookie renewal, a new anonymous session and API restart do not clear
the durable counters.

Under the application's serialized writer, each global window admits at most
40 new identifier rows. An identifier lasts 60 seconds from its first admission,
so unexpired identifiers span at most two adjacent global windows. This gives
an upper bound of 80 identifier rows, with expired rows removed on the next
admission check. It is a design derivation under these writer and clock
assumptions, not a measured storage or attack-resistance result. A database
administrator can bypass those application assumptions.

The global counter is a local resource guard and has an availability cost: one
caller can temporarily block everyone else's new login. Fixed windows permit
bursts on opposite sides of a boundary and do not impose a sliding-window rate.
No source-IP or `X-Forwarded-For` value selects a budget. This policy does not
rate-limit anonymous-session creation or other API routes, prevent distributed
attacks, add MFA or establish production capacity.

[OWASP's authentication guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
discusses threshold, duration and lockout-denial tradeoffs. Its failed-attempt
examples differ from this application's all-verification resource policy. The
chosen numbers and no-reset behavior are local design choices, with no claimed
OWASP or NIST compliance.

## Create one exception

`POST /api/exceptions` accepts reference, summary, details and an explicit normal
or high priority. Text must contain content, with reference, summary and details
limited to 80, 200 and 4,000 characters. Outer whitespace is removed from newly
admitted text. Reference identity remains case-sensitive within the organization.
Existing rows are not normalized. The same exact reference in another
organization is allowed.

The session supplies organization and actor. The server generates the exception
UUID and chooses open, unassigned, version-one state. Extra fields, including
attempts to set those server-owned values, are rejected. Input validation stays
separate from authorization and parameterized SQL, following
[OWASP's input-validation guidance](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html).

Creation requires a UUID `Idempotency-Key`. In one transaction, the server
reserves that actor's key, inserts the exception, adds its version-one `created`
audit event and stores the HTTP 201 response. It exposes that response only after
commit. An unexpected error rolls back the record, event and receipt together.

The database's unique organization/reference constraint decides concurrent
duplicates. A targeted `ON CONFLICT (organization_id, reference) DO NOTHING`
insert produces either one new row or a 409 reference-conflict receipt. A
preliminary unlocked lookup would leave a race between checking and inserting.
PostgreSQL 18 documents this behavior in its
[INSERT reference](https://www.postgresql.org/docs/18/sql-insert.html).

Two identical same-key submissions share the original ID and saved 201 response.
Two distinct keys for the same reference can create only one row. A saved
creation response is historical: replaying version 1 after a later assignment or
resolution does not reset the current record.

## Assignment, resolution and shared receipts

Each exception begins at version 1. Assignment and resolution requests include
the version displayed to the editor and a UUID `Idempotency-Key`. An idempotency
key identifies one intended change so the client can retry an uncertain result.

The server uses one explicit transaction at PostgreSQL's READ COMMITTED isolation
level. The connection is otherwise in autocommit mode, following Psycopg's
[version 3.3.6 transaction-context API](https://github.com/psycopg/psycopg/blob/3.3.6/docs/basic/transactions.rst):

1. Reserve the key for the authenticated actor and organization. Its fingerprint
   covers the action, exception ID and validated request body in canonical JSON.
2. If that key already exists, read its receipt in a separate SQL statement.
   The same fingerprint returns the saved status and response. A different
   fingerprint returns 409 without applying another change.
3. For a new key, lock the organization-scoped exception row with `FOR UPDATE`.
   A stale expected version returns 409. A resolved record cannot be changed.
4. Validate the assignee or resolution, update the exception and increment its
   version once. Insert one audit event for that new version.
5. Save the response in the retry receipt and commit. Only then expose the
   response to the client.

The separate receipt lookup matters during a race. At READ COMMITTED, a
conflicting insertion can wait for another transaction to commit. A following
statement receives a fresh snapshot that can see its receipt. Combining the
insert and lookup into one statement could leave that lookup using an earlier
snapshot. This follows PostgreSQL 18's documented
[READ COMMITTED and ON CONFLICT behavior](https://www.postgresql.org/docs/18/transaction-iso.html).

Creation, assignment and resolution share the actor/organization/key namespace.
Creation fingerprints contain the distinct `created` action and validated input.
Assignment and resolution keep their original fingerprint shape, including the
exception ID, so receipts from schema version 1 remain replayable. Reusing a key
for another action or content returns 409 rather than changing its meaning.

Two distinct keys with the same expected version contend for the same record.
One change succeeds, and the other observes a stale version. Two identical
requests with the same key share one committed receipt. Expected application
errors after reservation are saved as receipts too. An unexpected exception
rolls back the update, event and reservation together, leaving the same request
available for a fresh attempt.

Replay still requires a current authenticated session, correct Origin and CSRF
token. A receipt is not an authentication credential. Its response is historical:
another accepted change may already have advanced the record, so the UI refreshes
the detail after success rather than treating the saved response as current state.

## Browser recovery

The sign-in form handles 429 separately from an incorrect-password response.
It reads `Retry-After`, announces a temporary wait and keeps the email editable.
A countdown can disable submission temporarily, but it is only a local hint.
The next explicit submission is always checked by the server. A missing or
unusable delay leaves a generic wait message rather than inventing a deadline.
No password is automatically resubmitted when the countdown ends.

The UI retains the key and body of a change while its result is uncertain.
Network failures, unreadable responses and server errors offer **Retry same
change**. They do not silently mint a new key. This pending state lives in the
page's memory, so closing or reloading the page loses that recovery action.

Pending intake keeps its submitted fields and blocks another form submission or
navigation to a different record. A duplicate reference is a confirmed conflict,
so the form remains available for correction with a new intended request. After
an accepted creation, the UI selects the new ID and loads current detail rather
than installing the historical receipt as current state.

A version conflict requires a refresh before editing again. The browser does not
merge competing assignments or resolution notes. Request identity checks also
keep a late detail response from replacing the record selected by newer browser
navigation.

React renders user-provided strings as text. SQL parameters keep those strings
separate from SQL syntax, using Psycopg's
[version 3.3.6 parameter API](https://github.com/psycopg/psycopg/blob/3.3.6/docs/basic/params.rst).
The application serves a restrictive Content Security Policy, no-store responses
and frame-denial headers. These are specific defensive
boundaries, not a claim of complete application security.

## Durable state and packaging

The database contains organizations, users, sessions, exceptions, audit events,
mutation receipts and login-admission counters. Initialization creates schema
version 3 in a dedicated database. The application and seeder require that
version. They do not silently
migrate an existing schema. Seeding inserts synthetic records without resetting
existing passwords or work and does not fabricate creation events.

The explicit `migrate` command upgrades a known version-one or version-two schema
to version 3 in a single transaction after application processes have stopped.
It locks the version table, applies the earlier audit change when starting from
version 1, then creates admission state and changes the version marker. Existing
domain rows, password hashes, sessions, events and receipts retain their values
and original receipt fingerprints. Old seeded records do not gain invented
actors, timestamps or creation history. Repeating migration on schema 3 returns
without changing it, and other versions are refused. This is a bounded upgrade,
with no general migration framework or downgrade route. The operator must make
a private database backup before invoking it. Acceptance uses disposable legacy
fixtures without migrating retained accepted consumer databases.

The wheel contains the Python application, schema, upgrade SQL, built frontend
and dependency notices. Python runtime dependencies are installed separately under their own
licenses. The local database helper owns a new cluster under an explicit external
state directory. It does not alter an installed database service.

[Verification](VERIFICATION.md) records executed checks and their revisions,
including database, installed-consumer and browser outcomes. Source and test
definitions alone do not establish that a new path passed. None of those checks
establishes production load capacity or an operational deployment.
