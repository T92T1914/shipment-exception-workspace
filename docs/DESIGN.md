# Design

The application keeps one complete workflow small enough to inspect. React
renders the queue and detail view. FastAPI authenticates every protected API
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
the same assignment and resolution permissions.

The schema also checks organization membership. Composite foreign keys bind an
exception's assignee and each event's actor, assignee and exception to the same
organization. These constraints reject a cross-organization assignment even if
an application check is accidentally omitted. They do not replace query scoping
or constitute PostgreSQL row-level security. PostgreSQL 18's
[constraint documentation](https://www.postgresql.org/docs/18/ddl-constraints.html)
describes the composite foreign-key mechanism.

## One committed change

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

The UI retains the key and body of a change while its result is uncertain.
Network failures, unreadable responses and server errors offer **Retry same
change**. They do not silently mint a new key. This pending state lives in the
page's memory, so closing or reloading the page loses that recovery action.

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

The database contains organizations, users, sessions, exceptions, audit events
and mutation receipts. Initialization creates schema version 1 in a dedicated
database. Seeding inserts synthetic records without resetting existing passwords
or work. There is no schema upgrade framework in this release.

The wheel contains the Python application, schema, built frontend and dependency
notices. Python runtime dependencies are installed separately under their own
licenses. The local database helper owns a new cluster under an explicit external
state directory. It does not alter an installed database service.

[Verification](VERIFICATION.md) records the actual database races, rollback,
installed consumer, API restart and browser results. None of those checks
establishes production load capacity or an operational deployment.
