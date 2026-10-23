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
- The queue is a small unpaginated list. There is no carrier feed, file upload,
  notification system, forecasting, AI feature or general workflow engine.
- A pending retry is held only in the current page's memory. Closing or reloading
  that page loses the original retry key and body. A saved server receipt still
  exists, but the UI has no receipt browser or cross-device recovery flow. A
  replayed creation response reflects version 1, even if current state has since
  advanced. It must not be treated as the latest record.

## Security and operations

- The CLI serves loopback HTTP only. Transport security, reverse proxies,
  externally reachable hosting and secure production cookie configuration have
  not been accepted as a deployment route.
- There is no login rate limiter, abuse protection, multifactor authentication,
  device management or session-management UI.
- Authorization is enforced in the application and supported by relational
  constraints. PostgreSQL row-level security is not configured. A database
  administrator can read or alter application data.
- Audit events are ordinary database rows. They are not cryptographically sealed
  or protected from a privileged database operator.
- Mutation receipts and audit events have no automatic retention or archival
  policy. Expired sessions are cleaned up when a new anonymous session is created,
  rather than by a background maintenance service.
- Version 0.2.0 provides one explicit transactional upgrade from schema 1 to 2.
  Stop application processes and back up the dedicated database first. There is
  no downgrade, general migration framework or automatic startup upgrade. Older
  seeded records retain their original history without fabricated creation events.
  Backup restoration, disaster recovery and high availability remain outside the
  accepted workflow.
- Request bodies and field lengths are bounded, but the application has not been
  load tested. Two concurrent synchronous handlers and one server worker keep
  the local resource footprint small.
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

The installed consumer restarts the API process. A separate normal PostgreSQL
process restart checks that saved records remain available. These are not
power-loss, storage-corruption or database failover tests. Headless desktop and
narrow-mobile checks demonstrate the exercised browser journeys. They do not
establish all browser, accessibility or physical device behavior.

The screenshots and seeded records contain synthetic examples. No real shipment
data, business impact, employer endorsement, security certification or hiring
outcome is claimed.
