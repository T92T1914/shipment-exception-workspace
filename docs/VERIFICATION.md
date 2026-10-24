# Queue browsing verification

The October 24, 2026 local campaign tested implementation commit
[`b8e7f82684bd7dd1997285c88412142e56481d9d`](https://github.com/T92T1914/shipment-exception-workspace/commit/b8e7f82684bd7dd1997285c88412142e56481d9d)
through a newly installed v0.4.0 wheel outside the checkout. Runtime source,
tests and build configuration stayed unchanged across seven sequential manifest
checks. This record and two synthetic captures were added afterward. The
[v0.3.0](VERIFICATION-v0.3.0.md), [v0.2.0](VERIFICATION-v0.2.0.md) and
[v0.1.0](VERIFICATION-v0.1.0.md) records retain their historical scope.

## Executed local results

The executed combination was Windows x64, CPython 3.13.3, PostgreSQL 18.1,
Node 24.16.0 and npm 11.13.0, using the existing dependency locks. Browser
acceptance used Playwright 1.64.1 and isolated Chromium headless shell
153.0.8010.12 with one worker. Builds and tests used conservative thread limits.
No screen, interactive browser profile, clipboard, audio or visible app was used.

| Check | Actual result |
| --- | --- |
| TypeScript and Vite | Production build passed |
| Wheel and source archive | Built v0.4.0; application/SQL byte identity, frontend, notices and both immutable SQL fixtures checked |
| Fresh installation | Imported v0.4.0 from the external environment's site-packages; pip check passed |
| Installed PostgreSQL suite | 199 passed in 128.26 seconds, including 67 queue tests and retained workflow/admission checks |
| Installed API restart | A bounded queue cursor continued after restart; durable creation/assignment receipt replay and exhausted login admission remained effective |
| Built browser journeys | All 21 passed in 31.5 seconds, including multi-page desktop and narrow-screen queue behavior |
| Normal PostgreSQL restart | All row-value fingerprints unchanged across nine tables, including 72 exceptions, 23 events, 25 receipts and 25 sessions |
| Independent semantic/security review | A separate agent inspected the composed source, tests and claims; no remaining actionable source finding in that scope |

The tested local wheel SHA-256 is
`c76ab5ca4cb41353a50c491e4b7827e023983bc13ebc91b80ef9f2382349ebc4`.
The manifest's repository content fingerprint was
`734ce47782ccbe558efa67a06e3fa4933740becd5035f6329a8cf8589496ca98`.
Its before/after samples remained equal. The manifest SHA-256 was
`5f6064f2aedcaf3c5745d3bd7b6372d927931dd3023692e8d7d8fc7be5186d89`.
These identify this campaign, not reproducible-build guarantees. Later evidence
commits and hosted rebuilds can produce different archive hashes.

## Queue and authorization checks

Tests execute SQL through the installed package against actual PostgreSQL.
Expected static traversal is calculated independently from reference UTF-8 bytes
and UUID integer order. Cases cover the default 20 and maximum 50 rows, a
one-row lookahead, last-returned-row cursors, terminal pages and complete
unchanged-fixture traversal. Ordering and continuation use the same reference
`COLLATE "C"` and UUID pair.

Literal search cases include percent, underscore, the escape character,
backslash, SQL-like text, markup, accented text and ASCII case comparisons.
Search covers references and summaries, not details. Input checks exercise the
decoded query's 80-character bound before trimming, NUL rejection, repeated and
unknown parameters, invalid limits and statuses. Cursor checks cover strict
base64url encoding, payload UTF-8, duplicate JSON keys, field types and bounds,
invalid UUIDs, extra fields, excessive nesting and context mismatch. Framework
URL parsing can replace malformed raw URL bytes before application validation;
this is not strict raw-URL encoding acceptance.

Organization isolation is checked with overlapping references, foreign cursors,
forged positions and ignored organization headers. The authenticated session
supplies the SQL organization constraint regardless of cursor content. The
unsigned cursor is a navigation position, not authorization or an integrity
token. A caller can invent a position within its own authorized results.

Concurrent-change fixtures insert a row before the current position and move an
anchor out of the open-status filter. Continuation does not require the anchor
to remain in that filter. Refresh exposes earlier inserts. These establish the
declared live-view behavior, not snapshot consistency or every interleaving.
An off-page detail remains accessible only through its own organization check.

## Installed consumer and browser evidence

The consumer installed the ordinary wheel in a fresh isolated environment. It
served packaged assets outside the checkout, signed in, committed and replayed
mutations, exhausted login admission, restarted the API, and continued a saved
one-row queue cursor. Authenticated reads and receipt replay still worked while
new login verification was denied. Only synthetic admission timestamps were
expired before the separate browser campaign; workflow history was retained.

The 21 serial browser journeys retain the earlier 17 and add four queue cases.
A dedicated synthetic fixture supplies 54 Northline and four Harbor queue rows.
The unchanged Northline search traverses 20/20/14 rows without omissions or
duplicates and returns to a previous page. Tests exercise status changes,
resolution moving the selected record outside the refreshed filter, literal
search on a 390-pixel viewport, empty recovery, keyboard submission and viewport
fit. Direct links preserve selected off-page details after reload.

Held older requests exercise stale-response protection. One actual older page
response is replaced with a browser-facing 500 after a newer search succeeds.
The stale error cannot replace the new result. Another case creates from a later
filtered page, checks the reset to all statuses and empty search, follows the
new off-page selection, then switches organizations while an old query is held.
The old response cannot restore the prior organization's private queue state.
The substituted response is a client fixture, not an application-emitted fault.

The [desktop page-two](assets/desktop-queue-page-two.png) and
[narrow literal-search](assets/mobile-queue-literal.png) captures were generated
by these headless checks and visually inspected. They show synthetic records.
They are not physical-device, screen-reader or live-user acceptance.

Schema remains 3. Both accepted SQL upgrade fixtures retain their original Git
blob identities, and the suite still checks upgrades, rollback, history and
receipt preservation. No accepted earlier consumer database was upgraded,
reseeded or used for this campaign. After the final normal database restart,
the new owned server and cluster were stopped and retained privately.

## Review, warnings and hosted checks

Independent review found two issues before publication: older browser assertions
still expected the former refresh notice, and initial prose overstated strict
raw-URL UTF-8 rejection. The assertions now follow the actual UI notice while
retaining response/version gates, and the prose distinguishes framework URL
decoding from strict cursor payload decoding. The final source review is clear
within its stated scope. It is an agent review, not a human security audit,
penetration test or production assurance.

The separate Code Review tool was unavailable in this session. GitHub supplies
the actual hosted run, job and log diagnostics. No current Code Review result is
claimed. Consensus returned no new research for this milestone; its earlier
recorded quota limit was not bypassed. PostgreSQL and OWASP primary documentation
support the design decisions, not measured effectiveness claims.

The TestClient path retains Starlette's httpx deprecation warning. Browser output
retains the NO_COLOR/FORCE_COLOR overlap. They did not fail the checks. No
dependency pins, project license or notices changed. Credentials, database files,
private raw logs and fixture controls are not public application endpoints.

The [Actions workflow](https://github.com/T92T1914/shipment-exception-workspace/actions/workflows/verify.yml)
rebuilds on Ubuntu 24.04 using the pinned PostgreSQL 18.1 container, runs the
suite through the wheel, installs a separate consumer, and repeats restart plus
all 21 journeys using Playwright's matching headless browser. Hosted outcomes
are separate from the Windows results above. Run pages identify the actual
tested revisions. An older passing run does not accept a newer head. A version
tag is not a permanent release asset; Actions artifacts have limited retention.

Queue response size is bounded. Database scanning, sorting, latency and total
request cost are not qualified. There is no scale benchmark, index-usage claim,
full denial-of-service protection, production deployment, hiring outcome or
security-role qualification. Search uses ASCII case handling under the declared
collation rather than Unicode case folding. See [limitations](LIMITATIONS.md).

Use the README build route. Database tests replace the public schema and require
an explicit disposable SHIPMENT_TEST_DATABASE_URL. Browser fixtures require
WORKSPACE_FIXTURE_PYTHON plus WORKSPACE_LOGIN_FIXTURE_URL and
WORKSPACE_QUEUE_FIXTURE_URL pointing to the dedicated synthetic consumer
database. The queue fixture refuses to overwrite its existing fixture records.
Never run these fixture routes against retained or operational data.

## Reading-support follow-up

The separately scoped October 24 reader change tested implementation
[`9983ac011b3eceede0a4739cc7c44c292aa4dc56`](https://github.com/T92T1914/shipment-exception-workspace/commit/9983ac011b3eceede0a4739cc7c44c292aa4dc56)
through another fresh ordinary v0.4.0 wheel, isolated environment and disposable
consumer database. The README links the shared reading guide. Native
`translate="no"` hints apply only to the queue reference, selected-record reference
and reference input. Nearby prose and controls remain eligible for translation.

All six manifest checks passed with unchanged before/after source samples:
diff, package identity, installed import, dependency consistency, installed
restart consumer and all 21 browser journeys in 34.5 seconds. Existing journeys
now assert native `translate` booleans and exact reference/input values in both
desktop and narrow workflows. A separate independent agent review found no
remaining source or public-claim issue. The local backend suite was not repeated
for this UI-only change. Exact-revision hosted CI repeats that suite separately.
Backend, schema, record versions, retry behavior, dependency locks and existing
screenshot bytes are unchanged. The rebuilt UI bundle includes the new hints.

The reader campaign wheel SHA-256 is
`7d4deff45fc1cae6c88583b2bb25554ed8be31d825b24dd40a297069993116bd`.
Its repository content fingerprint remained
`e4da58e994232942c56232d046b36afbbca75722a5592ee8d6fa1639f5c30bd1`.
These checks establish declared browser hints and their inheritance boundaries,
not translation-provider behavior, translation quality, maintained localization
or personal fluency. The shared guide remains unchanged. Public README
availability is a separate check.
