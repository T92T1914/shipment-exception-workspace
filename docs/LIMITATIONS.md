# Limitations

This release is a synthetic workflow with a bounded acceptance record.
It demonstrates application integration and concrete failure handling. It does
not establish production operation, regulatory compliance, offensive security
practice or suitability for sensitive logistics data.

## Product scope

- Two organizations and six accounts are seeded explicitly: four operators and
  two read-only reviewers in ordinary local mode. Public mode adds one separate
  Northline visitor reviewer and denies business writes even if that account's
  role is changed. There is no signup,
  invitation flow, account administration, password recovery or password change UI.
- Both roles can inspect their organization's queue, details, history and
  members. Only operators can create, assign, unassign, resolve or replay a
  mutation receipt. Roles restrict the actor, not assignment eligibility: any
  member of the same organization can be an assignee. There is no interface for
  role administration, general permission engine or owner/administrator role.
- Operators can create, assign, unassign and resolve exceptions. Intake is manual
  and intended for synthetic records. Resolved records cannot be reopened or
  edited, and reference, summary, details and priority cannot be edited after
  creation.
- New text inputs trim outer whitespace. Reference uniqueness is case-sensitive
  within an organization, so differently cased references remain distinct. No
  automatic deduplication, carrier reconciliation or legacy normalization occurs.
- The queue uses bounded server pages. The UI shows up to 20 records and the API
  permits up to 50. Counts describe the current page, not all matches. There is
  no global total, arbitrary sort, detail or audit search, export or full-text
  ranking.
- Search is a literal reference or summary substring with ASCII case-insensitive
  matching under `C` collation. It does not provide Unicode case folding,
  natural-language search or different creation-time reference identity rules.
- Cursors are unsigned positions whose organization, search, status and page
  size are checked against the request. They are not permissions, secrets or
  durable bookmarks. Pages form a live view rather than a snapshot. An insertion
  before the current position needs a refresh, status changes can alter result
  membership, and fetching a previous page again can produce different contents.
- Detail returns only the latest 20 events, with history continuation metadata.
  The history API defaults to 20 and permits at most 50 events per page. The UI
  shows one 20-event page, ascending from oldest to newest within that page,
  and moves between newer and older pages. The count describes shown events,
  not a global total. There is no history search, arbitrary sort or export.
- History continuation is fenced at its initial record version, so later
  application appends need an explicit refresh to appear. That fence does not
  freeze joined user names or provide a full database snapshot. History cursors
  are unsigned, readable positions bound to the organization, record and page
  size, not permissions, secrets or durable bookmarks. A valid own-context
  cursor may skip rows. Privileged edits remain outside the application boundary.
- History event caching retains its first bounded page and current bounded page,
  rather than accumulating all visited events. Cursor positions still grow with
  visited pages. Returning to the cached first page does not perform another
  server permission check. Account/session changes and refresh clear that state,
  but this is not an instantaneous revocation or offline recovery guarantee.
- A page-size cap does not bound database scanning, sorting or latency. No new
  queue/history index, measured speed improvement or production capacity is claimed.
  There is no carrier feed, file upload, notification system, forecasting, AI
  feature or general workflow engine.
- A pending retry is held only in the current page's memory. Closing or reloading
  that page loses the original retry key and body. A saved server receipt still
  exists, but the UI has no receipt browser or cross-device recovery flow. A
  replayed creation response reflects version 1, even if current state has since
  advanced. It must not be treated as the latest record.
- An explicit HTTP 403 `read_only` retires the tab's pending mutation intent and
  allows current-state inspection. A prior interrupted request may already have
  committed, so the later denial does not establish its outcome. Permission
  refresh does not automatically retry a POST. There is no automatic role-change
  push, cross-device recovery or receipt browser.
- A successful session check that learns reviewer access also retires a pending
  or in-flight operator intent and its old response epoch. Reading, refresh and
  sign-out remain available, with an earlier-commit warning. This happens after
  the role change is observed and cannot cancel or undo a server transaction.
- The expected session-context header is a consistency check, not authentication
  or permission. It remains optional for existing API clients. A matching marker
  does not mean that database role, organization or other principal facts are
  unchanged; the server still enforces its current session and business policy.
- Cookie sessions are shared across tabs. The UI retires private state after an
  observed session transition and rechecks actual server state. Its cross-tab
  signal is advisory and carries no identity or private data. No immediate
  frozen-page erasure, cross-device push, instantaneous revocation or concurrent
  authentication serialization is promised. Channel failure retains request
  context checks and explicit/visible-page recovery routes.
- Session rechecks coalesce active work, but are not a general message rate
  limiter. Explicit refresh joins that work and waits for queued checking to
  settle before reading current data. This does not promise progress during an
  endless stream of notifications. A failed recheck clears the unconfirmed view and needs explicit
  recovery. An old in-flight mutation may already have committed when its local
  intent is retired. Recovery sends no automatic business POST and does not
  transfer an earlier actor's retry to the current account.

## Security and operations

- Ordinary `serve` binds loopback HTTP. Explicit `serve-demo` supports a separately
  provisioned public reviewer, canonical HTTPS origin, exact Host admission,
  Secure/HttpOnly/SameSite Strict cookies and no forwarded-header trust. Local
  HTTPS staging and the separate October 27 hosted route passed their declared
  checks. The [hosted record](hosted-demo.md) preserves direct API refusals,
  browser journeys, instance replacement and API-visible state comparison.
  Doubled root text at 390px produces awkward heading wraps and a long page.
  These are synthetic demo controls, without production-security or
  comprehensive accessibility acceptance.
- Login admission permits 20 password verifications per normalized identifier
  and 40 globally in each counter's fixed 60-second window. It counts correct
  passwords too and does not reset on success. It is not a failed-attempt-only
  lockout, sliding-window limiter or complete abuse-prevention system.
- A caller can exhaust the global budget and temporarily deny all new logins.
  Fixed windows allow bursts around expiry, and counter expiries need not align.
  Ordinary local mode has no general API or anonymous-session limiter. Public
  mode adds a process-local five-request-per-second budget with burst 30 and a
  transactional cap of 128 live sessions, with five-minute anonymous and
  30-minute visitor expiry. Readiness allocates no session. These do not bound
  physical database storage, traffic or distributed denial of service. Restart
  resets the process-local budget. There is no MFA, device management or
  session-management UI, and production availability remains unqualified.
- Identifier digests are SHA-256 of the trimmed, lowercased submitted email. A
  digest does not anonymize a guessable identifier. Known and unknown addresses
  share the admission policy, but broad timing-side-channel resistance has not
  been established. There is no IP or forwarded-header reputation system.
- Authorization is enforced in the application and supported by relational
  constraints. PostgreSQL row-level security is not configured. A database
  administrator can read or alter application data.
- Mutations lock and check the current actor row with `FOR SHARE` before receipt
  access and business writes. Ordinary role updates serialize with that lock.
  A mutation admitted before a role update can finish first. This does not cancel
  committed work, provide instant revocation or protect against privileged
  database changes. UI controls can remain stale until access refresh or an
  explicit server denial.
- Audit events are ordinary database rows. They are not cryptographically sealed
  or protected from a privileged database operator.
- Mutation receipts and audit events have no automatic retention or archival
  policy. Expired sessions are cleaned up when a new anonymous session is created,
  rather than by a background maintenance service.
- Version 0.9.0 retains schema 4. The explicit transactional upgrade from schema
  1, 2 or 3 preserves existing users as operators and gives future omitted roles
  a reviewer default. Stop application processes and privately back up the
  dedicated database before that upgrade. There is
  no downgrade, general migration framework or automatic startup upgrade. Older
  seeded records retain their original history without fabricated creation events.
  The [local restore guide](backup-and-restore.md) covers the qualified v0.8.0
  PostgreSQL 18.1 same-cluster, same-owner route with a separate empty target.
  The v0.8.1 client correction is not a new native restore qualification. Cross-version
  restore, storage corruption, power loss, disaster recovery and high availability
  remain outside the accepted workflow.
- Request bodies and field lengths are bounded, but the application has not been
  load tested. Two concurrent synchronous handlers and one server worker keep
  the local resource footprint small. The derived 80-row bound for identifier
  admission state assumes the normal serialized application writer and database
  clock. It is not a measured protection against denial of service or privileged
  database changes. Expired rows are removed at the next admission check.
- Dependency pins describe the tested environment. They do not guarantee that
  every package is free of vulnerabilities or that future releases behave
  identically. The release does not bundle or update the system PostgreSQL server.

## Evidence boundaries

See [verification](VERIFICATION.md) for the exact revision, commands, platforms
and actual results. Database tests require PostgreSQL and are skipped when their
test database is not configured. Migration tests drop and recreate the configured
test database's entire `public` schema, so it must be disposable. A skipped
integration test is not a pass. New implementation and test definitions are not
executed acceptance until their results are recorded.

The queue browser fixture adds 54 Northline and four Harbor synthetic records
without invented audit events. It refuses existing fixture reference prefixes
and requires an explicit `WORKSPACE_QUEUE_FIXTURE_URL`. Browser checks use
`WORKSPACE_FIXTURE_PYTHON` to run that helper in the installed environment. This
setup changes its database, so its target must be a fresh disposable consumer,
never a retained accepted consumer or another project. The fixture is not a
recovery tool, scale trial or performance measurement.

The role browser fixture requires `WORKSPACE_ROLE_FIXTURE_URL`, schema 4 and the
exact six synthetic account IDs, organizations and emails. It changes only
Alex's role for the declared demotion/promotion scenarios, without resetting
domain records, sessions, history or receipts. These guards do not authorize
using it against a retained accepted consumer or operational state. It is test
setup, not an application endpoint or role-management feature.

The history browser fixture requires `WORKSPACE_HISTORY_FIXTURE_URL`, schema 4
and the exact six synthetic account IDs, organizations and emails. It creates
the designated `NL-HISTORY-001` record and 45 synthetic events, then permits one
controlled append at version 46. Those events are explicitly test setup, not
operational history or application API requests. It refuses an existing
designated record during setup and does not reset existing workflow, sessions
or receipts. Its guards do not authorize use against a retained accepted
consumer or another project's data. This fixture exposes no HTTP controls and
does not establish scale or query performance.

Admission tests may set counter expiries or substitute a test clock inside a
disposable database scenario. Those checks exercise declared boundaries without
claiming real elapsed-time throughput, timing indistinguishability or resistance
to a live attack. A browser countdown is a client hint. The server reevaluates
admission on the next explicit submission, and the UI does not retry passwords
automatically.

The installed consumer restarts the API process. A separate normal PostgreSQL
process restart checks that saved records remain available. These are not
power-loss, storage-corruption or database failover tests. Headless desktop and
narrow-mobile checks demonstrate the exercised browser journeys. They do not
establish all browser, accessibility or physical device behavior.

The screenshots and seeded records contain synthetic examples. No real shipment
data, business impact, employer endorsement, security certification or hiring
outcome is claimed.
