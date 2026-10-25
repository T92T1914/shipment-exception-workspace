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
404 from the detail routes and from an authorized operator's mutation lookup.
Reviewers receive a uniform `read_only` denial before mutation object lookup,
including for foreign or missing target UUIDs.

The schema also checks organization membership. Composite foreign keys bind an
exception's assignee and each event's actor, assignee and exception to the same
organization. These constraints reject a cross-organization assignment even if
an application check is accidentally omitted. They do not replace query scoping
or constitute PostgreSQL row-level security. PostgreSQL 18's
[constraint documentation](https://www.postgresql.org/docs/18/ddl-constraints.html)
describes the composite foreign-key mechanism.

## Shared browser session coherence

Cookie sessions are shared by the application's tabs. A tab's in-memory user
label and private state do not automatically change when another tab replaces
the cookie. Version 0.7.0 adds a server-checked expected context plus advisory
cross-tab notifications, keeping session authority on the server. It does not
create separate identities for each tab or put a bearer token in browser storage.

Login and session payloads include `session_context`, the lowercase hexadecimal
SHA-256 of the ASCII prefix `shipment-ui-context-v1:` followed by the stored
`token_hash`. Domain separation keeps this marker distinct from the raw cookie,
stored token digest and CSRF value. It is public consistency metadata, not an
authentication credential. It can correlate one session and is not broadcast
or persisted. Repeated session reads and API restarts retain it. Login rotates
it even for the same actor, without a new schema column.

The optional `X-Workspace-Context` request header states which session context
the client expects. If present, there must be exactly one parsed value of 64
lowercase hexadecimal characters matching the current session marker. A mismatch,
duplicate or invalid value gets generic HTTP 409 `session_changed`, without
echoing either value. Protected routes first require authenticated current
session state, so absent or expired authentication remains HTTP 401. Their
context check occurs before route work and business receipt reservation/lookup.
Login checks a supplied context before CSRF and login admission. A supplied
context with no current session is rejected too. `GET /api/session` ignores an
expected-context header and remains the recovery authority.

Clients that omit the header retain the existing API behavior. The marker never
selects an actor, organization or role and does not replace cookie authentication,
Origin/CSRF checks, organization-scoped queries or current operator admission.
The marker identifies a session, not an immutable database principal. A role or
organization change can leave the marker unchanged. Session refresh compares
authentication, actor and organization as well as the marker before retaining
private state, and updates the current role from the server. Every operation
still applies its existing current database policy.

The browser holds a per-document context and generation in memory. Each request
captures them, attaches the expected context except on `/api/session`, and checks
them after response arrival and JSON reading. A retired context raises a stale
response outcome instead of updating queue, detail, history, notices or retry
state. Session refresh also has a request generation, so an older recheck cannot
reinstall a retired session. Action ownership keeps an old request's cleanup
from clearing a newer action's busy state.

Successful login/logout notify `shipment-workspace-session-v1`. The exact hint
is `{ v: 1, type: 'session-changed' }`; receivers accept only that two-field
shape. It carries no cookie, context marker, CSRF token, actor, organization,
role, business payload or record. A receiver retires its old context and private
state synchronously, then checks `/api/session`. The receiver never installs an
identity from the message or echoes the hint. Logout establishes its next
anonymous cookie before notifying peers, reducing competing anonymous-session
creation by those peers.

Session rechecks coalesce into one active request loop with a queued follow-up
when more work arrives. Focus and visible-page transitions recheck a known
session. A persisted `pageshow` triggers the same visible-page check after page
restoration. These checks compare server facts rather than assuming every hint
was delivered. The channel constructor, send and cleanup paths tolerate failure,
and listeners/channel are closed on cleanup. A failed server check retires the
unconfirmed view and offers **Check current session**. This is not a message
rate limiter or a guarantee that arbitrary same-origin script cannot trigger
more checks.

Retirement clears queue criteria, detail, history pages/positions, assignment
and resolution drafts, intake fields and local pending intent. If a mutation
was pending or in flight, the message says that an earlier change may already
be saved. It does not undo a commit or automatically replay its key/body under
the next account. Server receipts remain subject to their original actor,
organization and current permission rules. Ordinary interrupted requests retain
their original key/body while their session context stays current.

The [HTML broadcast mechanism](https://html.spec.whatwg.org/multipage/web-messaging.html#broadcasting-to-other-browsing-contexts)
and [browser lifecycle](https://developer.mozilla.org/en-US/docs/Web/API/Window/pageshow_event)
support these rechecks. Delivery is limited by storage partition, active page
state and queued messages. This is not cross-device synchronization, immediate
frozen-page erasure, instantaneous revocation or serialization of concurrent
authentication responses. Matching context does not certify that database
privileges are unchanged. Source, baseline reproduction and executed acceptance
remain separate evidence in [verification](VERIFICATION.md).

## Operator and reviewer access

The user row contains exactly one role, `operator` or `reviewer`. The server's
session query joins the current user row, and login/session payloads expose its
role to the UI. The role is not trusted from a cookie claim, header, request body
or visible control. Both roles can read their organization's queue, details,
history and member list and can sign out. Only operators can create, assign,
unassign or resolve, including replaying a saved mutation receipt. Any member of
the same organization remains a valid assignee, regardless of that member's role.

Normal input, Origin, CSRF and retry-key checks still apply. After those checks,
each mutation starts its business transaction and reads the actor's current
organization and role with `SELECT ... FOR SHARE`. A missing actor, changed
organization or role other than operator receives HTTP 403 `read_only` before
receipt reservation/lookup and before business writes. Denied attempts create
no receipt or audit event and change no exception version. Previously saved
receipts remain stored, but their existence grants no replay permission.

The user-row lock is held through the business transaction's commit or rollback.
An ordinary non-key role `UPDATE` conflicts with `FOR SHARE`; the weaker
`FOR KEY SHARE` would not provide that boundary. If the mutation obtains its
lock first, it can finish before the role update. If the role update obtains its
lock first and commits, the later locking read sees the changed role and denies
the write. This is a database ordering rule, not instant revocation or cancellation
of an already committed request. PostgreSQL 18 documents these
[row-lock conflicts](https://www.postgresql.org/docs/18/explicit-locking.html) and
[Read Committed locking reads](https://www.postgresql.org/docs/18/transaction-iso.html).

Organization relationships remain mandatory alongside the role. This follows
the [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
to define least privilege and check permission on every request. It is a small
application policy, not a general role/attribute policy engine. There is no
public role-management route, and a privileged database operator remains outside
the protection claimed by this application.

## Bounded live queue

`GET /api/exceptions` accepts `q`, `status`, `limit` and `cursor`. It returns
`items`, `next_cursor` and `page_size`. The default page size is 20 and the maximum
is 50. Status is `all`, `open` or `resolved`. Search input is limited to 80
characters before outer whitespace is removed. Unknown or duplicate parameters,
invalid types or ranges and NUL characters receive the generic HTTP 422
`invalid_queue_query` response without echoing submitted values. Cursor payload
bytes must decode as strict UTF-8. Search values arrive after the framework's URL
decoding, which can replace malformed percent-encoded bytes. This handler does
not promise strict validation of the raw URL encoding.

Search matches a literal substring of the reference or summary. SQL parameters
keep input separate from SQL syntax. Pattern escaping has a different purpose:
`!` becomes `!!`, `%` becomes `!%`, and `_` becomes `!_` under `ESCAPE '!'`.
Backslash is ordinary text. `ILIKE` with `COLLATE "C"` compares ASCII letters
without case and does not promise Unicode case folding or full-text search.
Reference identity at creation remains case-sensitive. PostgreSQL 18's
[pattern-matching documentation](https://www.postgresql.org/docs/18/functions-matching.html)
describes `ILIKE` and the escape mechanism.

Every page query first takes its organization from the authenticated session.
It then applies search, status and the position predicate within that scope.
Rows are ordered by `(reference COLLATE "C", id)`, and the next-page comparison
uses the same pair and collation. The UUID breaks ties without relying on a
database's locale-specific default order. Reference and ID cannot be edited by
the application. The query fetches `limit + 1` rows, returns at most `limit`, and
uses the extra row only to decide whether to issue a next cursor. It does not
calculate a global total. PostgreSQL documents both the need for a predictable
[order with LIMIT](https://www.postgresql.org/docs/18/queries-limit.html) and
[row comparisons](https://www.postgresql.org/docs/18/functions-comparisons.html).

A cursor is at most 2,048 characters and uses canonical unpadded base64url
transport for a UTF-8 JSON object. Its flat fields are `v`, `organization_id`,
`status`, `q`, `limit`, `reference` and `id`. Validation rejects duplicate JSON
keys, extra fields, invalid types and values, NUL characters and text that cannot
be encoded as UTF-8. Organization, normalized search, status and page size must
match the current request. Canonical transport here means the base64url spelling
is checked by decoding and re-encoding. It is not a JSON signature or a promise
of canonical JSON serialization.

The cursor is unsigned and readable. It represents a position, not permission,
secrecy or proof that an anchor record exists. A client can construct another
valid position. No anchor lookup is necessary because each database query still
uses the session's organization. This follows the
[OWASP authorization principle](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
of checking access on every request rather than trusting an object identifier or
client-carried state.

The UI uses 20-record pages, a submitted search and a status filter. Its page
number and count describe the current page. Previous navigation retains cursor
positions in page memory and fetches that page again. Refresh, assignment and
resolution return to the first page under the current criteria. Creation clears
the criteria, returns to the first page and selects the new UUID. Detail loading
is independent of queue membership, so an open record remains available outside
the current page or filters.

Queue requests are associated with their user, query and page. Starting a new
view invalidates the previous request before the replacement fetch, so a late
response cannot install an old page. Signing out or changing account clears
private criteria and page history. This state lives only in the page's memory,
not localStorage or sessionStorage. The existing uncertain-mutation recovery
continues to block conflicting navigation while a submitted change is pending.

The queue is a live view at the database's ordinary READ COMMITTED isolation
level. It does not hold a snapshot across pages. An insertion before the cursor
needs a refresh to appear, and status changes can alter membership between
requests. Revisited pages can therefore contain different records. Explicit
`C` ordering is byte-oriented rather than a natural-language sort. Bounded output
does not bound database scanning, sorting or latency. This release adds no index
and claims no measured speed, query-plan improvement or production capacity.

## Bounded change history

The record detail route, `GET /api/exceptions/{id}`, returns the current
`exception`, its latest 20 `events`, and `history` metadata containing
`next_cursor`, `page_size` and `through_version`. It no longer materializes the
complete event list. `GET /api/exceptions/{id}/history` accepts `limit` and an
optional `cursor`, returning `events`, `next_cursor`, `page_size` and
`through_version`. The default limit is 20 and the maximum is 50. Events retain
ascending version order within each returned page, including short histories.
The first page contains the latest changes, and continuation moves to older
ones.

Both routes authenticate the session and resolve the exception within its
current organization before querying history. Operators and reviewers can read
their own records. Missing and foreign records receive the same 404 before
history-query validation. The event query independently uses that organization
and exception ID. A history cursor cannot replace these access checks.

The initial record read supplies `through_version`. SQL restricts events to that
version or lower, orders by version descending and fetches `limit + 1` rows.
The extra row decides whether another page exists. The selected `limit` rows
are reversed for ascending presentation. The existing
`UNIQUE(exception_id, version)` constraint supplies the unique order. An older
page adds `version < before_version` and retains the original upper fence.
It does not use OFFSET, calculate a total or require an anchor row lookup.
PostgreSQL documents the need for a predictable
[order with LIMIT](https://www.postgresql.org/docs/18/queries-limit.html).

For example, a 45-change record initially returns versions 26 through 45.
Its next page returns 6 through 25, then 1 through 5. If version 46 is saved
between requests, those older pages keep the original boundary of 45. Explicit
refresh starts a new browse through 46. The same fence also excludes a change
committed after the initial detail record read but before its history query.
This is an append boundary at ordinary READ COMMITTED isolation, not a full
database snapshot. Joined actor and assignee names are read from current user
rows. Privileged edits to existing events remain outside the application policy.

History cursors use canonical unpadded base64url for a strict UTF-8 JSON object,
with at most 1,024 characters. The exact fields are `v`, `organization_id`,
`exception_id`, `limit`, `through_version` and `before_version`. `v` is the strict
integer 1, the limit is a strict integer from 1 through 50, and both version
positions are strict integers from 1 through 2,147,483,647. The earlier position
cannot exceed its fence. Organization, exception and page size must match the
current request, and the fence cannot exceed the current record version.
Unknown or duplicate query parameters, malformed encoding, duplicate JSON keys,
extra fields, invalid types and invalid relationships produce generic HTTP 422
`invalid_history_query` without echoing submitted values. Canonical transport
checks the base64url spelling, not a JSON signature or canonical JSON format.

A cursor is unsigned and readable. A caller may construct a different valid
position within its own history or skip rows. That does not select another
organization's events, authenticate a user or establish a durable bookmark.
Every remote request retains the current session/object checks. This is a
bounded application interface, not a cryptographically sealed audit trail.

The UI shows one 20-event page with **Older changes** and **Newer changes**,
the page count and its version boundary. Each page lists changes from oldest to
newest. Current details and editing drafts stay separate from older history.
The browser retains the first bounded page for returning to the same fence,
the current bounded page, and cursor positions for visited pages. It does not
accumulate event pages in the rendered list. Cursor metadata can still grow with
the number of visited pages. Nothing is persisted to browser storage.

History responses are associated with the user, selected record, detail
generation and history view. Record selection, refresh, saved mutation and
private-state clearing retire earlier history work. An older-page failure
clears that page's list and offers **Retry history page** or **Refresh latest
changes**, without replacing current details or an unsent editing draft.
Authentication failure follows the existing session-ending path. Refresh starts
at the latest history and clears the old browse. Returning to the first page
within a browse uses its cached page rather than silently moving the fence.
That cache is not a new permission check or an instantaneous revocation promise.

The output cap addresses the
[OWASP API4 records-per-response concern](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/).
It does not prove a database scan, latency, rate or load bound. No new index,
query-plan measurement, broad denial-of-service protection or production
capacity is claimed. Empty seeded histories remain empty rather than acquiring
invented creation events.

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
locks and checks the actor's current operator access, reserves that actor's key,
inserts the exception, adds its version-one `created`
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

1. Lock the actor row with `FOR SHARE` and require its current operator role and
   matching organization before touching receipts or exceptions.
2. Reserve the key for the authenticated actor and organization. Its fingerprint
   covers the action, exception ID and validated request body in canonical JSON.
3. If that key already exists, read its receipt in a separate SQL statement.
   The same fingerprint returns the saved status and response. A different
   fingerprint returns 409 without applying another change.
4. For a new key, lock the organization-scoped exception row with `FOR UPDATE`.
   A stale expected version returns 409. A resolved record cannot be changed.
5. Validate the assignee or resolution, update the exception and increment its
   version once. Insert one audit event for that new version.
6. Save the response in the retry receipt and commit. Only then expose the
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

Replay still requires a current authenticated session, current operator access,
correct Origin and CSRF token. A receipt is not an authentication or permission
credential. Its response is historical:
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

Read-only reviewers see an access notice and reading/navigation controls, with
no creation or editing forms. **Refresh workspace** also reads current session
access. There is no automatic role-change push, so an operator tab can become
stale. If a write or replay receives an explicit 403 `read_only`, the UI retires
that local pending intent, switches conservatively to read-only access and
explains that an earlier interrupted request may already be saved. It does not
turn the denial into proof of an earlier failure. A permission refresh performs
no automatic POST. Current records can be inspected after an explicit refresh.
Other uncertain operator outcomes retain their original canonical key and body
while their session context stays current.

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

Version 0.7.0 adds shared-session coherence without changing schema 4 or requiring
a new migration for an existing schema 4 database.

Version 0.6.0 adds bounded history without changing schema 4 or requiring a new
migration for an existing schema 4 database.

The database contains organizations, users, sessions, exceptions, audit events,
mutation receipts and login-admission counters. Initialization creates schema
version 4 in a dedicated database. Version 0.5.0 adds the user role column and
requires an explicit upgrade for schema 1, 2 or 3. The application and seeder
require the current schema and do not silently migrate an existing database.
Fresh seeding inserts two organizations, four operators and two reviewers.
Seeding preserves existing passwords, roles and work and fabricates no creation
events. Future user inserts that omit a role default to reviewer.

The explicit `migrate` command upgrades a known schema 1, 2 or 3 to version 4 in
a single transaction after application processes have stopped. It locks the
version table and applies each needed audit, admission and role upgrade in order.
The role upgrade backfills existing users as operators to preserve accepted
access, then changes the future-insert default to reviewer. Existing
domain rows, password hashes, sessions, events and receipts retain their values
and original receipt fingerprints. Old seeded records do not gain invented
actors, timestamps or creation history. Repeating migration on schema 4 returns
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
