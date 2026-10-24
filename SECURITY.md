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
route, multifactor authentication, password recovery or
tamper-proof audit log. See [limitations](docs/LIMITATIONS.md) and the
[executed verification record](docs/VERIFICATION.md) before interpreting a
security claim.

## Login admission and availability

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
windows allow boundary bursts, and neither anonymous-session creation nor other
API routes are rate-limited. This does not solve flooding, distributed attacks,
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

The demo seeder requires a password of at least 12 characters. Repeated seeding
does not change an existing account's password. Use fresh isolated demo state
when you need a clean acceptance run.

## Schema upgrades

Version 0.3.0 requires schema version 3. Stop every application process using the
dedicated database and take a private backup before running the new installed
wheel's explicit `migrate` command. Keep its connection record and credentials.
Initialization, seeding and server startup do not silently upgrade schema 1 or 2.
Do not use seeding as an upgrade or password-reset step.

The bounded migration upgrades schema 1 or 2 to 3 in one transaction, adding
admission state and applying the earlier audit change when needed. It preserves
existing domain rows, password hashes, audit events, sessions and retry receipts,
including old fingerprint bytes, without backfilling fictional creation history.
Preserved sessions still obey their original expiry and logout behavior. A
receipt replay still needs a current authenticated session, correct Origin and
CSRF token. There is no downgrade or qualified backup-restoration route. See the
[upgrade instructions](README.md#upgrade-an-existing-v010-or-v020-database) and check
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
