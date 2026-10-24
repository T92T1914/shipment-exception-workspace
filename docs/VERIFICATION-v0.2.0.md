# Manual intake verification

The October 23, 2026 local campaign exercised implementation commit
[`b22154d5e09ba23e4a78ee43d015509450dcdacd`](https://github.com/T92T1914/shipment-exception-workspace/commit/b22154d5e09ba23e4a78ee43d015509450dcdacd).
Runtime source, tests and build configuration remained unchanged during that
campaign. This record and the new synthetic screenshots were added afterward.
The [v0.1.0 verification record](VERIFICATION-v0.1.0.md) retains its earlier
results and adverse observations.

## Executed local results

The executed combination was Windows x64, CPython 3.13.3, PostgreSQL 18.1,
Node 24.16.0, npm 11.13.0 and the existing dependency locks. Playwright 1.64.1
used an isolated Chromium headless shell 153.0.8010.12 with one worker. No
interactive browser profile, screen, clipboard or visible app was used.

| Evidence | Actual result |
| --- | --- |
| TypeScript and Vite | Production build passed with two build threads or fewer |
| Wheel and source distribution | Built v0.2.0; Python/SQL source identity, bundled frontend, license notices and exact legacy SQL fixture checked |
| Fresh installed environment | Wheel installed outside the checkout; import came from that environment's site-packages; pip check passed |
| PostgreSQL checks through installed package | 74 passed: 33 retained API checks, 30 intake checks and 11 migration checks |
| Installed API process restart | Session, assignment receipt and creation receipt survived; creation replay returned the original 201, ID and one creation event |
| Built browser journeys | All 14 passed against the installed API and real PostgreSQL |
| Normal PostgreSQL process restart | Row-value fingerprints unchanged for schema metadata, two organizations, four users, 18 sessions, 13 exceptions, 21 events and 23 retry receipts |
| Independent semantic/security review | Separate agent reviewed the composed diff; three findings repaired and re-reviewed; it did not execute tests itself |
| Licensing and privacy | Existing MIT source license and dependency notices retained; no dependency pins changed; screenshots contain only synthetic records |

The tested local wheel SHA-256 is
`a41cd1f2c1891398543a0a21cb5e81f8ec398a2a3bb06c56927e5be8767d14a7`.
A later documentation build or another platform can produce a different archive
hash. This identifies the wheel actually installed for this campaign.

## What the checks establish

Intake tests verify server-owned identity and initial state, field bounds,
authentication and CSRF, organization isolation, case-sensitive references,
actor-scoped retry identity and historical replay after later edits. Independent
clients exercise same-key creation and two actors racing for one reference.
The barrier starts both clients together, but does not prove every possible
database interleaving or load condition.

A temporary PostgreSQL trigger rejects the creation audit insert. The test
checks rollback of the exception, event and retry reservation, then retries the
same key after removing that trigger. No fault-injection route ships in the app.

Migration tests use the exact v0.1.0 SQL blob from accepted commit
`e722a336f87462423769192d455a57560f8895ae`, with Git blob identity
`a5c75d707fa08e65fc6d539424d7be333c8040c4`. The fixture retains its original
bytes across checkouts. Legacy records, passwords, session, assignment event
and original receipt survive the explicit upgrade. The old assignment receipt
replays through the installed v0.2.0 API. No historical creation events are added.
Concurrent migrations complete as one upgrade and one current-schema no-op.
A late schema-version trigger failure rolls back the preceding DDL and data.
Missing, unknown or partial metadata is refused without relabeling old tables.

The 14 browser cases include the seven retained workflow/navigation cases,
desktop and 390-pixel mobile intake through assignment and resolution, a local
UUID preparation failure and duplicate-reference correction. Four recovery
cases forward a real creation, then drop its response, substitute a JSON 500,
return an incomplete 201 representation or return a mismatched UUID/body. Retry
preserves URL, key and body, selects the actual saved record and leaves one
creation event. These are controlled response fixtures, not observed outages.
Keyboard focus, viewport fit and unexpected browser/network errors are checked
in the exercised journeys. Captures were visually inspected for synthetic
content and readable layout, not full accessibility compliance.

## Review findings and limits

Independent source review found that row-lock-before-DDL ordering could make
concurrent migration commands deadlock. The migration now acquires its required
table lock first. Review also found that a UUID/version pair alone was
insufficient confirmation of a creation response, and that missing version
metadata could let initialization relabel retained legacy tables. The repaired
source has response matching and nonempty-database refusal. Relevant PostgreSQL
and browser checks pass. The original findings remain in the private review
record, rather than being described as executed failures.

The first source-distribution inspection also showed the new SQL test fixture
needed explicit inclusion. Packaging now includes it and checks its bytes.
The TestClient path emits Starlette's httpx deprecation warning. Browser output
reports the existing NO_COLOR/FORCE_COLOR overlap. Those warnings were retained.
No unrelated dependency upgrade or suppression was needed for the passing runs.

A normal database restart is not a power-loss, storage-corruption or failover
test. The disposable legacy fixture is not a migration of anyone's retained
application database. No production hosting, physical-device acceptance,
penetration test, Python vulnerability audit, abuse/load study, defense system
qualification or hiring outcome is established. The retained v0.1.0 consumer
database and primary checkout were not upgraded or replaced.

## Hosted verification and repetition

The [Actions workflow](https://github.com/T92T1914/shipment-exception-workspace/actions/workflows/verify.yml)
builds the wheel on Ubuntu 24.04 with the pinned PostgreSQL 18.1 container,
runs the database checks through that wheel, installs a fresh separate consumer,
restarts its API and runs all 14 journeys using Playwright's matching headless
browser. Exact-revision hosted outcomes are separate from the local results
above. Code Review exposes CI diagnostics; the semantic review described above
is an independent agent review.

[PR run 40031520062](https://github.com/T92T1914/shipment-exception-workspace/actions/runs/40031520062)
passed for head `6ff198bd79059a215b209185e72da8b676ea4d29`, tested through
GitHub's PR merge revision. It passed all 74 PostgreSQL checks, the installed
API restart and all 14 browser journeys on Ubuntu 24.04. The matching browser
was Chrome headless shell 156.0.8078.4, Playwright revision 1248. Code Review
read the exact-head successful job and its diagnostic log. Its initial live-log
read returned HTTP 502, an access error rather than a failed application check.

That hosted wheel's SHA-256 is
`455e8821562f901bd218b220f01c5fb5020ce57c407751806c1758cea1f9bf38`.
The run's installed-workflow-wheel artifact includes the wheel and browser
summary, with a 14-day retention period. A tag is not a permanent downloadable
release asset. Later documentation-only revisions run the same workflow. The
[pull request](https://github.com/T92T1914/shipment-exception-workspace/pull/2)
and Actions show their exact current statuses; an earlier green run does not
accept a newer head automatically.

Build and install using the README. Run `python -m pytest tests` using the
installed environment and an explicit disposable SHIPMENT_TEST_DATABASE_URL.
These tests truncate records and migration tests replace its entire public
schema. An unset URL skips database checks, which is not a database pass.
`python tools/check_package.py` checks the actual wheel and legacy fixture in
the source archive.

For a separate clean consumer database, set SHIPMENT_DATABASE_URL, then run
`tools/installed_consumer.py --python PATH_TO_INSTALLED_PYTHON --output
PRIVATE_ACCEPTANCE_DIRECTORY --keep-server`. Load its private base_url and
demo_password into WORKSPACE_BASE_URL and WORKSPACE_DEMO_PASSWORD before
`npm --prefix frontend run test:e2e`. Use a fresh consumer state for the serial
cases, and stop only its owned app/database processes afterward. Private
credentials, database files, raw logs and failed captures stay out of Git.
