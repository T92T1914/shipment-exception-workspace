# Login admission verification

The October 23, 2026 local campaign tested implementation commit
[`e91d91a59c75a2f203aaf261567ffd50bf63b370`](https://github.com/T92T1914/shipment-exception-workspace/commit/e91d91a59c75a2f203aaf261567ffd50bf63b370)
through a newly installed v0.3.0 wheel outside the checkout. Runtime source,
tests and build configuration stayed unchanged across the seven sequential
manifest checks. This evidence record and the new synthetic captures were added
afterward. Earlier [v0.2.0](VERIFICATION-v0.2.0.md) and
[v0.1.0](VERIFICATION-v0.1.0.md) records remain as history.

## Executed local results

The executed combination was Windows x64, CPython 3.13.3, PostgreSQL 18.1,
Node 24.16.0 and npm 11.13.0, using the existing dependency locks. Browser
acceptance used Playwright 1.64.1 and isolated Chromium headless shell
153.0.8010.12 with one worker. Builds and tests used conservative thread limits.
No screen, interactive browser profile, clipboard, audio or visible app was used.

| Check | Actual result |
| --- | --- |
| TypeScript and Vite | Production build passed |
| Wheel and source archive | Built v0.3.0; application/SQL byte identity, frontend, notices and both immutable SQL fixtures checked |
| Fresh installation | Imported v0.3.0 from the external environment's site-packages; pip check passed |
| Installed PostgreSQL suite | 131 passed in 87.46 seconds, including retained workflow checks and the new admission/upgrade boundaries |
| Installed API restart | Real global budget exhaustion survived a fresh API process; a correct password still received 429; anonymous session and counter rows persisted |
| Existing authenticated workflow | Assignment and creation receipt replay still worked while further login work was denied |
| Built browser journeys | All 17 passed in 22.6 seconds, including actual desktop/narrow 429 and manual recovery |
| Normal PostgreSQL restart | All row-value fingerprints unchanged, including the global admission row and two identifier rows, 22 sessions, 13 exceptions, 21 events and 23 receipts |
| Independent semantic/security review | Separate agent inspected the composed code, tests and claims; no remaining actionable source finding in that scope |

The tested local wheel SHA-256 is
`66c143e926487028053a6552e184fe1816f70668c3939c2363bd4f271fcb922b`.
The manifest's repository content fingerprint was
`a3a8caccd9e02b679648e1846cbb6ea77b9c20dcc90e6eb99a232586f5e1b4e8`.
Its before/after samples remained equal. Different environments and later
documentation builds can produce different archive hashes. These identities
describe the actual local campaign, not reproducible-build guarantees.

## What admission tests exercise

Tests use actual PostgreSQL tables, locks and transactions. They check the
twentieth identifier admission, fortieth global admission, known/unknown policy,
normalization, no success refund, generic denial, no denied-row allocation,
unchanged expiry and the later blocking Retry-After value. Envelope rejection
does not charge either counter. Existing authenticated work remains available.

Two independent clients compete for the last identifier or global slot. A
separate connection takes the global row lock NOWAIT from inside a verification
probe, establishing that the reservation is already committed and the lock
released. Another regression holds the global row, confirms the request is
waiting through PostgreSQL lock diagnostics, then moves expiry before release.
It distinguishes a post-lock wall-clock sample from stale transaction-start time.

Threshold/race tests replace only the password-verification boundary with a
narrow call probe. They are not Argon2 load measurements. Retained API tests and
the installed consumer also execute real password hashing. Trigger failures
check fail-closed admission rollback and retained charging when a later session
write fails. A missing global state row performs no password verification.

Expiry tests move only disposable database fixture timestamps. Two directly
advanced global windows exercise allocation of 80 identifier rows and denial
without further growth. This checks a boundary fixture. The general 80-row
argument in [Design](DESIGN.md) depends on normal writers, fixed expiries and the
declared clock assumptions. It is not a measured attack-resistance result.

The consumer performs one successful sign-in and 39 real failed verifications,
then verifies that a denied correct-password attempt and counter state survive
API restart. It explicitly expires only its synthetic admission fixtures before
the separate browser campaign, preserving sessions and workflow history.

## Upgrade and browser evidence

Both old SQL fixtures retain exact accepted Git blob identities:

- Schema 1: `a5c75d707fa08e65fc6d539424d7be333c8040c4`.
- Schema 2: `c8f6bf47db94ae6b0dffeffd136606df1e2029be`.

The installed suite upgrades each to schema 3, preserves prior rows, sessions,
events and receipt fingerprints, and replays old assignment/creation outcomes.
Concurrent migrations serialize. A failure during the second stage of the
schema-one chain rolls back the earlier stage too. Repeating initialization or
migration on schema 3 preserves live budgets. The fixtures are disposable and
do not upgrade either retained accepted consumer database.

The 17 serial browser journeys retain the previous 14 and add desktop/narrow
admission recovery plus one malformed-header case. Actual 429 cases exhaust the
dedicated synthetic identifier through a scoped SQL fixture, receive the real
API's Retry-After, keep the session anonymous, block Enter and preserve cooldown
when email changes. A second fixture expires server state and Playwright advances
only the isolated browser clock. No automatic credential retry occurs. Manual
submission then authenticates and logout confirms cleared password/cooldown.

The malformed-header case forwards a real wrong-password request, confirms its
401, then substitutes a browser-facing 429 with an invalid Retry-After. It is a
client-response fixture, not a claim that the application emits malformed headers.
Keyboard focus, viewport fit and unexpected errors/external requests are checked.
The generated desktop and 390-pixel captures were visually inspected. This is
headless and controlled-clock evidence, not a physical phone or real minute wait.

## Limits, warnings and hosted checks

Independent semantic review is an agent review of the supplied composition.
Code Review exposes CI diagnostics and is used at that capability. Neither is a
human security audit, penetration test, production assurance or hiring outcome.
There is no login-policy effectiveness study, Python vulnerability audit, load
qualification, power-loss/failover test or backup-restoration acceptance.

The TestClient path retains Starlette's httpx deprecation warning. Browser output
retains the NO_COLOR/FORCE_COLOR overlap. They did not fail the executed checks.
No dependency pins, project license or notices changed. Credentials, raw logs,
database files and test controls stay outside the public application interface.

The [Actions workflow](https://github.com/T92T1914/shipment-exception-workspace/actions/workflows/verify.yml)
rebuilds on Ubuntu 24.04 using the pinned PostgreSQL 18.1 container, runs the
suite through the wheel, installs a separate consumer and repeats restart plus
all 17 journeys with Playwright's matching headless browser. Hosted outcomes
are separate from the Windows results above. Current pull-request and main
run pages identify the actual tested revisions and status. An older passing run
does not accept a newer head. A version tag is not a permanent release asset.

Build/install using the README. Database tests require an explicit disposable
SHIPMENT_TEST_DATABASE_URL and replace its public schema. Browser cooldown tests
also require WORKSPACE_FIXTURE_PYTHON pointing to the installed environment and
WORKSPACE_LOGIN_FIXTURE_URL pointing to that clean synthetic consumer database.
Never use either fixture route against retained or operational state. The
standalone browser helper is test setup and supplies no HTTP control endpoint.
