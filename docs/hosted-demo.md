# Hosted synthetic reviewer demo

[Open Shipment Exception Workspace](https://shipment-employer-demo.onrender.com/)
and choose **Enter synthetic demo**. The entry page supplies its separate public
reviewer credential. Browse the Northline queue, search references, open records
and history, then sign out. Do not submit real shipment or personal data.

This is a small read-only employer demonstration, accepted on October 27, 2026.
It has no carrier integration or operational users. GitHub Pages remains the
[static project explanation](https://t92t1914.github.io/shipment-exception-workspace/).
The [operator walkthrough](operator-walkthrough.md) separately shows actual local
creation, conflict, interrupted response, receipt replay and resolution.

## Served package and environment

| Identity | Observed value |
| --- | --- |
| Installed release | v0.9.0, ordinary published wheel |
| Wheel | `shipment_exception_workspace-0.9.0-py3-none-any.whl`, 121,892 bytes |
| Wheel SHA256 | `4ec45d384b142e5c8880fe411fbca0b0cfc6c167806e32cb3ebcd0dc5123625a` |
| Application/helper checkout | `618aa4f18394064004318ea3619ae2412d609c8c` |
| CPython in the build receipt | 3.13.3 |
| Provider configuration | Ohio, one native Python web instance and dedicated PostgreSQL 18 |
| Database | 1 GB, external allowlist empty, autoscaling and HA off |
| Normal start and readiness | `serve-demo`, `/api/ready` |
| Deployment/setup policy | Automatic deploys off, empty pre-deploy/setup hooks, one explicit completed setup job |

The provider checkout and build receipts were read independently of
`/api/version`. The receipts identify the verified wheel digest, dependency-lock
digest, Python version and absence of build-time database actions. The actual
HTTPS version endpoint returned v0.9.0, the accepted revision and
`public_demo: true`. A configured revision string alone would not prove that
installed identity. The provider reported PostgreSQL major 18; no minor-version
or native restore qualification is inferred.

The deployed application remains at that accepted source even after later
presentation/documentation commits. No new wheel, release or application feature
was needed to publish this record.

## Executed hosted checks

Actual HTTPS readiness returned 200 with `ready: true` without issuing a session
cookie. Anonymous session cookies had Secure, HttpOnly, SameSite Strict, root
path and the five-minute lifetime. The public reviewer signed in successfully.
The public reviewer password did not authenticate the tested stock operator.

With a real authenticated reviewer, valid Origin/CSRF/context headers and UUID
retry keys, create, repeated same-intent create, assign, unassign and resolve
requests returned 403 `read_only`. No replay header was returned. A Harbor record
read returned 404. A wrong-Origin logout returned 403 `csrf_failed`. These are
direct API checks, separate from the browser journeys' zero business POSTs.
The public instance has no fabricated historical operator receipt. The
before-receipt role guard is supported by the accepted source and separate
local/CI authorization tests, not a claim that a saved operator receipt was
created and replayed publicly.

HTTP entry redirected to the canonical HTTPS origin. Slash/missing API paths
returned 404 without an HTTP downgrade. A wrong Host was refused with 403 at the
provider/app boundary; that response is not attributed specifically to the
application handler. Normal provider TLS certificate verification stayed on.

The actual entry HTML and its linked JavaScript/stylesheets contained no match
for this database's password or internal/external connection URL bytes. This
finite payload check is not a comprehensive security audit. Private connection
records, tokens, cookies and raw logs remain outside public Git.

Four sequential journeys ran in one isolated headless Chromium process:

| Journey | Viewport | Appearance | Root text size |
| --- | --- | --- | --- |
| Desktop | 1440 x 1000 | Light | 100% |
| Desktop enlarged | 1440 x 1000 | Dark | 200% |
| Narrow enlarged | 390 x 844 | Light | 200% |
| Narrow | 390 x 844 | Dark | 100% |

All four passed entry/readonly fields, keyboard focus, queue search and filters,
resolved and assigned history, hash reload, Back navigation and sign-out clearing.
They recorded zero business POSTs and no unexpected page, console, HTTP, network
or escape-path event. Their browser process closed normally. The maintained
[consumer](../tools/public_demo_browser.cjs) records the exact checks and scopes.
These are headless browser results, not physical-phone or native browser-zoom
acceptance. At 390px with doubled root text, headings wrap awkwardly and the page
becomes long. Content and controls remained available, but comfortable readability
at every enlargement and comprehensive accessibility conformance are not claimed.

A corrected lifecycle check combined a replacement service-instance ID, actual
HTTPS readiness, the unchanged live source commit, the same unexpired reviewer
session/context/CSRF values, and complete API-visible queue/detail/history
agreement. Logout then returned 204 and protected reads returned 401. The same
business values also matched the snapshot retained before the earlier restart
and browser journeys. This compares admitted Northline business values, not all
database tables, receipts or sequence state. Ordinary authentication/admission
rows can change.

## Retained failures and scope

The first service snapshot started before its database environment was supplied
and refused startup. The next reached the new database but refused missing schema
4. Both builds had installed the exact accepted wheel. The initial one-off job
request was then rejected because the service had no successful deployment. No
job ran from that request. The temporary bootstrap route in the
[deployment guide](deployment.md#establish-the-explicit-setup-prerequisite)
resolved that provider prerequisite. One actual setup job completed. Normal
startup was restored afterward and never initialized or repaired the database.

The first API consumer failed because it assumed every record version implied a
history event. The accepted seeded `NL-1042` record is version 1 with no events;
`NL-1086` and `NL-1091` have their provisioned three- and two-event histories.
The test was corrected without changing those records.

The next consumer passed API controls but incorrectly waited for a new deployment
entry after CLI restart. Render had actually emitted `server_restarted` and
replaced the instance. That observation run remains failed. The affected lifecycle
check was corrected and passed with one additional restart request. Two restart
requests occurred in total; there was no second setup job or database reset.

This qualifies one synthetic hosted route. It does not establish production
security, uptime, attack resistance, failover, disaster recovery, native Linux
restoration or a new PostgreSQL cross-version restore result. The earlier
[v0.8.0 backup/restore record](VERIFICATION-v0.8.0.md) retains its own executed
Windows/PostgreSQL 18.1 scope. The original release downloads and local staging
remain separately qualified.

The selected resource prices gave a $13.30/month recurring baseline before the
one-off job, metered usage and applicable tax. No overall hard spending cap was
verified. The completed job no longer runs. The approved web/database resources
remain the intended deliverable and can continue accruing charges. Suspending
only the web service does not establish zero database/storage charges. Preserve
the database unless its owner explicitly chooses deletion.
