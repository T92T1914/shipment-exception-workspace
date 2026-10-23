# Security

Shipment Exception Workspace is a local application demonstration using synthetic
records. Run it against a dedicated local PostgreSQL database and keep the CLI's
loopback binding. Do not use real shipment, customer, defense or other sensitive
data in this release.

The application enforces session authentication, organization-scoped object
access, CSRF checks, version conflicts and actor-scoped idempotent mutations.
Composite database constraints and transactions support those boundaries.
[Design](docs/DESIGN.md) describes their implementation.

Manual intake accepts bounded reference, summary, details and priority fields.
The server chooses the organization, actor, ID and initial state, and rejects
extra fields. Creation, its audit event and retry response commit together.
References remain case-sensitive within their organization. These are bounded
integrity rules, rather than a general duplicate-detection or abuse-prevention
system.

These controls have a specific tested scope. There is no production deployment
route, login rate limiter, multifactor authentication, password recovery or
tamper-proof audit log. See [limitations](docs/LIMITATIONS.md) and the
[executed verification record](docs/VERIFICATION.md) before interpreting a
security claim.

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

The demo seeder requires a password of at least 12 characters. Repeated seeding
does not change an existing account's password. Use fresh isolated demo state
when you need a clean acceptance run.

## Schema upgrades

Version 0.2.0 requires schema version 2. Stop every application process using the
dedicated database and take a private backup before running the new installed
wheel's explicit `migrate` command. Keep its connection record and credentials.
Initialization and server startup do not silently upgrade schema 1. Do not use
seeding as an upgrade or password-reset step.

The bounded schema 1-to-2 transaction preserves existing records, audit events,
sessions and retry receipts without backfilling fictional creation history.
Preserved sessions still obey their original expiry and logout behavior. A
receipt replay still needs a current authenticated session, correct Origin and
CSRF token. There is no downgrade or qualified backup-restoration route. See the
[upgrade instructions](README.md#upgrade-an-existing-v010-database) and check
the executed evidence before interpreting preservation as a broader recovery
guarantee.

## Reporting a problem

Share a minimal synthetic reproduction, the affected revision, expected behavior
and observed behavior. Remove credentials, session values, connection URLs and
real records from any public report. Do not test against other people's systems.

A private reporting channel is not promised by this repository. If GitHub offers
private vulnerability reporting for it, use that route for sensitive details.
Otherwise arrange a private channel with the maintainer before sending those
details. A public issue can describe a sanitized symptom without including a
working secret or another person's data.
