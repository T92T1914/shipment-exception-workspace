# Security

Shipment Exception Workspace is a local application demonstration using synthetic
records. Run it against a dedicated local PostgreSQL database and keep the CLI's
loopback binding. Do not use real shipment, customer, defense or other sensitive
data in this release.

The application enforces session authentication, organization-scoped object
access, CSRF checks, version conflicts and actor-scoped idempotent mutations.
Composite database constraints and transactions support those boundaries.
[Design](docs/DESIGN.md) describes their implementation.

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

The API test fixtures truncate and reseed the configured test database.
`SHIPMENT_TEST_DATABASE_URL` must point to a disposable database created for
these tests. Never use an existing project or operational database.

The demo seeder requires a password of at least 12 characters. Repeated seeding
does not change an existing account's password. Use fresh isolated demo state
when you need a clean acceptance run.

## Reporting a problem

Share a minimal synthetic reproduction, the affected revision, expected behavior
and observed behavior. Remove credentials, session values, connection URLs and
real records from any public report. Do not test against other people's systems.

A private reporting channel is not promised by this repository. If GitHub offers
private vulnerability reporting for it, use that route for sensitive details.
Otherwise arrange a private channel with the maintainer before sending those
details. A public issue can describe a sanitized symptom without including a
working secret or another person's data.
