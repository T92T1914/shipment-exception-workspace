# Limitations

This release is a synthetic local workflow with a bounded acceptance record.
It demonstrates application integration and concrete failure handling. It does
not establish production operation, regulatory compliance, offensive security
practice or suitability for sensitive logistics data.

## Product scope

- Two organizations and four accounts are seeded explicitly. There is no signup,
  invitation flow, account administration, password recovery or password change UI.
- All members within an organization have the same permissions. There are no
  owner, dispatcher or administrator roles.
- Members can create, assign, unassign and resolve exceptions. Intake is manual
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
- A page-size cap does not bound database scanning, sorting or latency. No new
  queue index, measured speed improvement or production capacity is claimed.
  There is no carrier feed, file upload, notification system, forecasting, AI
  feature or general workflow engine.
- A pending retry is held only in the current page's memory. Closing or reloading
  that page loses the original retry key and body. A saved server receipt still
  exists, but the UI has no receipt browser or cross-device recovery flow. A
  replayed creation response reflects version 1, even if current state has since
  advanced. It must not be treated as the latest record.

## Security and operations

- The CLI serves loopback HTTP only. Transport security, reverse proxies,
  externally reachable hosting and secure production cookie configuration have
  not been accepted as a deployment route.
- Login admission permits 20 password verifications per normalized identifier
  and 40 globally in each counter's fixed 60-second window. It counts correct
  passwords too and does not reset on success. It is not a failed-attempt-only
  lockout, sliding-window limiter or complete abuse-prevention system.
- A caller can exhaust the global budget and temporarily deny all new logins.
  Fixed windows allow bursts around expiry, and counter expiries need not align.
  Other routes, including anonymous-session creation, have no admission limiter.
  Anonymous-session flooding, distributed attacks and production availability
  remain unsolved. There is no MFA, device management or session-management UI.
- Identifier digests are SHA-256 of the trimmed, lowercased submitted email. A
  digest does not anonymize a guessable identifier. Known and unknown addresses
  share the admission policy, but broad timing-side-channel resistance has not
  been established. There is no IP or forwarded-header reputation system.
- Authorization is enforced in the application and supported by relational
  constraints. PostgreSQL row-level security is not configured. A database
  administrator can read or alter application data.
- Audit events are ordinary database rows. They are not cryptographically sealed
  or protected from a privileged database operator.
- Mutation receipts and audit events have no automatic retention or archival
  policy. Expired sessions are cleaned up when a new anonymous session is created,
  rather than by a background maintenance service.
- Version 0.4.0 retains schema 3, so an existing v0.3.0 database needs no new
  migration. The explicit transactional upgrade from schema 1 or 2 to 3 remains
  available. Stop application processes and back up the dedicated database before
  that upgrade. There is
  no downgrade, general migration framework or automatic startup upgrade. Older
  seeded records retain their original history without fabricated creation events.
  Backup restoration, disaster recovery and high availability remain outside the
  accepted workflow.
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
