# Application verification and retained release evidence

## v0.9.1 downloadable package and deployment helper

The [v0.9.1 Release](https://github.com/T92T1914/shipment-exception-workspace/releases/tag/v0.9.1)
publishes the selected accepted Windows wheel and source archive without moving
the original tag. Its companion installation guide supersedes the archive's
older installation text. The archive retains its original v0.9.0 Render helper.

The later helper selects the published v0.9.1 wheel, checks its digest before
installation, and checks both installed version identities and the runtime import
location. Focused regressions cover wrong versions, source path leakage and
missing frontend/notices while retaining the previous admission checks. The
separate `Qualify published release wheel` workflow downloads those exact bytes,
refuses a deliberate wrong digest, and runs the helper and ordinary installed
restart consumer with a fresh PostgreSQL 18.1 database outside the checkout.

The Release notes record executed results and the final helper/deployment
identities as each delivery gate completes. Workflow definition alone is not a
passing run. The ordinary source built CI wheel, selected release wheel, provider
deployment and Windows native outage evidence remain distinct. No dependency,
application payload, schema or native restore qualification changed in the helper
delivery.

## v0.9.1 dependency outage recovery

The [recovery guide](dependency-outages.md) explains the corrected response and
explicit user actions. The change was developed over accepted PR19 merge
`8cb3de10985287187aa743271bb7e43a28d13eff`. The `v0.9.1` tag points at source
revision `e631e638a4e73f7a8104fababc753f5761fd930c`. The earlier capacity
measurements and hosted v0.9.0 acceptance below keep their original identities.

The selected local v0.9.1 wheel has SHA256
`aaf7da963b3237e318d1e376e12f8c58c9e934b7f43880b6037784ca98901df6`.
It was built on Windows x64 with CPython 3.13.3 and the existing locked
dependencies, installed into a new external environment and consumed outside
the checkout. PostgreSQL was 18.1. Python/SQL package members were checked
against source. Compiled UI members were compared with the browser tested wheel.
The runtime correction changes no database schema, dependency pins or receipt
format. The source archive includes its regression and recovery documentation.

| Evidence | Executed result and boundary |
| --- | --- |
| Baseline caller | The older installed package returned the misleading generic 500 for a read and reviewer mutation when a documented shutdown exception was injected at the actual session query. Business rows, audit events and receipts stayed unchanged. This was a simulated driver fault, not a native stop. |
| Initial regression suite | 413 backend/helper cases passed before the native timeout correction, with the retained TestClient warning. This is not relabeled as a full suite run of the final candidate. |
| Final focused backend | 49 cases passed on the corrected installed package. These include actual caller faults, rollback and deliberately withheld commit acknowledgement, receipt/role/expiry/organization checks, and parameter only classification checks. They are not 49 native interruptions. |
| Ordinary installed consumer | The final fresh wheel consumer passed startup, UI/API use, process restart, durable receipt retry, reviewer denial, queue/history and session context checks. |
| Affected browser journeys | Six headless journeys passed with one worker: read recovery, matching session explicit receipt retry, and unavailable session retirement, each at desktop and 390 pixel narrow widths. Narrow checks used twice the root text size. Keyboard controls, original key/body, no automatic business replay and viewport fit were checked. These used controlled browser responses on the earlier candidate. Its UI bytes are unchanged in the selected wheel. |
| Corrected native interruption | One fresh direct loopback cluster and a fixture of three exceptions per organization passed the corrected stop/restart scenario. Session, queue and member reads returned sanitized 503. Reviewer mutation returned 503 during the outage and 403 after recovery. The historical receipt replayed exactly. Changed body and stale actions were refused, later valid work succeeded, and ordered full business/audit/receipt comparison passed. |

The corrected native scenario produced two committed actions, two new events
and three complete saved receipts, including the stale action response. The
acknowledgement loss was deliberate withholding of an actually committed
response, not naturally occurring network loss. No retained database, hosted
service or capacity workload matrix was exercised. Fresh resources were bounded
by the existing Windows two core Job Object, 3 GiB memory limit, sampled 2 GiB
storage stop and finite scenario timeouts. These are containment limits, not
performance measurements or storage quotas.

Adverse results remain part of acceptance. The first browser launcher used an
obsolete executable path and launched no browser. The next run passed three
desktop cases but timed out on a test that omitted the normal narrow back
navigation. Its following two cases did not run. The corrected six case run
passed, then its separate cleanup command failed. Job Object termination and
ownership readback are recorded separately from those browser passes. The first
real native attempt did stop its database but returned 500 because Windows
reported a SQLSTATE less connection timeout. It did not pass recovery. The later
corrected scenario above used new state and the selected wheel. It does not erase
that first stopped database failure.

The fix requires corroborated refusal, including explicit numeric routing checks
for that timeout path. It does not classify all timeouts, credential/TLS/schema
errors or programming failures as unavailable. The one TCP diagnostic may add up
to 2.5 seconds after the existing five second connection attempt. There is no
guessed recovery deadline, automatic transaction retry, failover qualification,
new native restore result or production availability claim. At outage closeout,
source/CI artifact publication was separate from the then current v0.9.0 Release
and hosted demo. The later distribution work is recorded above. Exact revision GitHub checks belong to this contribution's
PR and subsequent main run, not the historical runs below.

## v0.9.0 release and reviewer deployment verification

Version 0.9.0 adds a separately configured synthetic reviewer deployment while preserving the ordinary local operator application. The public route requires an explicit HTTPS origin, a separately provisioned visitor identity and matching startup configuration. It denies business writes at the server. The built frontend and API still share one origin.

The [v0.8.1 verification](VERIFICATION-v0.8.1.md) preserves the accepted refresh correction and its original evidence. The [v0.8.0 verification](VERIFICATION-v0.8.0.md) preserves the native backup/restore campaign and adverse results. Neither is relabeled as a new v0.9.0 execution.

## November 1 local capacity and recovery study

The [separate study record](capacity-study.md) and
[structured results](capacity-results.json) retain the frozen source, selected
installed wheel, 24 fresh state replicates, all scheduled/completed/refused/failed/
dropped counts, low sample limits and one controlled database interruption.
All 5,400 measured requests completed correctly. Each larger fixture 4 RPS
replicate met its declared completion and scheduled to response p95 targets.
The original uncertain intent replayed without another committed change or event.
The unavailable reviewer request returned 500 during the outage. Recovered
reviewer denial was separately verified as 403. No optimization was selected.

Local package preparation passed 364 backend/initial harness cases, one existing
warning and no skips, plus the ordinary external installed consumer on a separate
fresh database. The final harness focused check passed 26 cases. Its stricter
offline checker recomputed all 24 trials and their complete business snapshots
and intent ledgers. Independent source/evidence review and current PR/main CI
are distinct delivery gates. This study adds no new application version, hosted
deployment or native restore qualification. The earlier release and hosted
records below retain their original execution identities and counts.

## v0.9.0 release evidence and delivery

| Layer | Observed result |
| --- | --- |
| Backend suite | 323 cases passed, no skips, one existing TestClient warning. This was an installed package run against new disposable PostgreSQL state, before the core source was committed. Its exact fingerprint is recorded below. |
| Corrected installed HTTPS staging | All four sequential public reviewer journeys passed at candidate `ff0935c23e3aedd9cf6018bb4c73c5dd2228d2a8`. Direct API controls, process restart and controlled session expiry passed separately. |
| Installed operator walkthrough | Actual creation, independent API assignment, stale version refusal, controlled response interruption, explicit receipt replay, resolution and desktop/narrow reload passed on a different fresh synthetic database. |
| Candidate package acceptance | A fresh external installed consumer passed at `aa565af`, using wheel SHA256 `4ec45d384b142e5c8880fe411fbca0b0cfc6c167806e32cb3ebcd0dc5123625a`. All 25 pure deployment helper cases and the new narrow enlarged login browser regression passed separately. |
| GitHub Actions | Branch and PR executions at `08b94a6` each passed 348 backend/helper cases, the installed restart consumer and 54 browser journeys. Links and scope are below. |
| v0.9.0 distribution | The selected Windows built wheel has SHA256 `4ec45d384b142e5c8880fe411fbca0b0cfc6c167806e32cb3ebcd0dc5123625a`. The [versioned Release](https://github.com/T92T1914/shipment-exception-workspace/releases/tag/v0.9.0) records actual publication availability, source archive and asset digests. The completed v0.8.1 release remains separate. |
| Public HTTPS application hosting | The separate October 27 [hosted acceptance](hosted-demo.md) joins the selected release wheel, actual Render checkout/build receipts, HTTPS identity, direct reviewer refusals, four browser journeys and instance-restart/session/business readback. Initial deployment and consumer observer failures remain separate adverse results. |

The local combination is Windows x64, CPython 3.13.3, PostgreSQL 18.1, React 19.3.1 and the existing pinned dependencies. Frontend checks use the qualified isolated Playwright/Chromium route with one browser worker. Build/test concurrency remains at two or fewer. Those local/CI results do not qualify every compatible environment. The separately
recorded [hosted route](hosted-demo.md) qualifies one managed PostgreSQL 18 demo
configuration. It does not extend the native backup/restore campaign.

## Backend execution identity

The [branch run](https://github.com/T92T1914/shipment-exception-workspace/actions/runs/40340420693)
and [PR run](https://github.com/T92T1914/shipment-exception-workspace/actions/runs/40340427865)
both executed source `08b94a6d45605499819507a6585fd98b0f1ba76f` on the declared
Linux CI route. Each reported 348 passed backend/helper cases with the retained
TestClient warning, a successful installed restart consumer and 54 passed browser
journeys. The 348 includes 25 pure provider helper cases, not provider trials.
These runs built their own wheel/source archives. Their wheel bytes are separate
from the selected Windows built release wheel. No reproducible build equivalence
is claimed. These are GitHub hosted CI results, not public application hosting or
native Linux restoration. Later runs and their exact revisions remain available
in [Actions](https://github.com/T92T1914/shipment-exception-workspace/actions).

The 323 case run imported the ordinary installed package from an external environment and used a support only external test directory. PostgreSQL fixtures were disposable. No retained accepted consumer database was initialized, reseeded or used as a fixture.

The executed source was uncommitted over the accepted v0.8.1 head. The repository runner recorded stable content fingerprint `2451e76a9b017c61563c2c8a1aa56f94e51d0b41850728d9b1b2e9cefc90962e` before and after the command. The backend core was subsequently frozen at [`a0317171e44c2b97f2e50db89895400e4581aba7`](https://github.com/T92T1914/shipment-exception-workspace/commit/a0317171e44c2b97f2e50db89895400e4581aba7). This is not a claim that the suite was rerun at that commit. Later source and final package applicability require their own identity comparison or execution.

The suite includes the prior application contracts and 52 new public demo cases. Parameter only origin, transport and configuration cases are part of that total. They do not establish actual remote database connectivity. Relevant checks include separate visitor provisioning, refusal to repurpose existing stock state, transactional provisioning failure, current identity at startup, secure cookies, role and organization admission, actual matching saved receipt denials, session allocation/expiry controls, concurrent slot admission, request budget behavior and ordinary local defaults. Registration of a configuration value is distinct from connecting to an external service.

The existing FastAPI/Starlette TestClient deprecation warning remains recorded. Dependencies were not upgraded to conceal it.

The owner compared every Python and SQL package member from the initial installed
wheel to the corrected staging wheel and source at `aa565af`. Those bytes agree
exactly. This joins the earlier backend execution to unchanged runtime code,
without presenting it as a rerun. Frontend changes have their own actual staging
journeys. The later fresh environment used only the selected ordinary wheel,
with dependency consistency and installed path checks, against another new
disposable database. Its ordinary consumer passed process restart, persistent
session/receipt, one business effect after retry, reviewer denial, queue/history
and session context checks. The 25 helper cases use fake downloads and connections
and do not qualify the provider. The browser regression exercised the ordinary
installed login at 390 pixels and exactly twice its root text size.

## Corrected installed staging

The completed staging candidate was source [`ff0935c23e3aedd9cf6018bb4c73c5dd2228d2a8`](https://github.com/T92T1914/shipment-exception-workspace/commit/ff0935c23e3aedd9cf6018bb4c73c5dd2228d2a8), installed wheel SHA256 `23c6f969600794ec8e89cbf3258d5219b4e19dfe1ae81ecd7036615837c2bcb5`. Installed runtime members matched the selected wheel and candidate source. The frontend was the actual build carried in that wheel.

This route used direct loopback HTTPS with a task owned self signed certificate and an exception limited to its isolated clients. No system certificate trust was changed. It does not qualify an external TLS terminating proxy, provider hostname, managed database or public network.

The actual visitor credential authenticated only the dedicated reviewer. It failed against all six stock accounts. Valid direct create, repeated key create, assign, unassign and resolve attempts received `read_only` denials without a replay response. Foreign and guessed record references remained unavailable. Wrong Origin and CSRF values were refused. Invalid Host was rejected without allocating a cookie, and supplied forwarded host/protocol headers granted no authority.

The session cookie carried Secure, HttpOnly and SameSite=Strict with the configured expiry. The application process was restarted, then the current session read records again. A controlled database timestamp change expired that specific session and required recovery. This is a fixture driven expiry boundary, not an elapsed time longevity result. Complete business row and event sequence comparisons remained unchanged across the public checks. Sessions and login admission rows can still change, so the database is not described as immutable.

Four browser journeys ran serially:

| Journey | Viewport | Appearance and root text |
| --- | --- | --- |
| Desktop | 1440 by 1000 | Light, 100 percent |
| Desktop enlarged | 1440 by 1000 | Dark, 200 percent |
| Narrow enlarged | 390 by 844 | Light, 200 percent |
| Narrow | 390 by 844 | Dark, 100 percent |

Each used the real reviewer entry, server search/filter results, selected record/history, authenticated hash reload, browser back navigation and explicit sign out. Keyboard entry, search, record selection and sign out had observed focus and a visible outline. Enlarged cases checked the actual computed root text size, rather than assuming the requested style took effect. Checked panels fit their viewports. All four sent zero UI business POSTs and recorded no unexpected browser/network errors.

Provisioned public history supplies the read only browsing examples. It is synthetic setup, separate from the [operator walkthrough](operator-walkthrough.md). That walkthrough performs real application writes and ends at version 4 with four events. Its uncertain assignment makes two identical key/body attempts, receives the actual server's replay marker and adds only one assignment event. Its screenshot identity and limits remain attached to the executed candidate.

## Adverse results retained

The first 52 case public backend run returned 51 passes and one failed new assertion. The API lists each history page oldest first, while that assertion expected reverse order. The assertion was corrected without changing history semantics. The original source and failed run remain retained.

An initial full suite launcher imposed importlib isolation on existing fixture/support imports and failed collection for ten modules. It executed no backend tests. The corrected external support only route and independent installed import probe produced the 323 case result above. Collection failure is not counted as an application test pass or failure.

Staging attempt a1 passed two desktop journeys but failed the narrow light 200 percent login layout. Measured content extended to 478 pixels at a 390 pixel viewport. The intro flow flex row did not wrap. The source correction adds wrapping without hiding overflow or reducing text size. The overall attempt remained failed, and its downstream operator journey was not executed.

Attempt a2 passed direct API/restart/controlled-expiry checks and both desktop journeys, but the same narrow entry still failed. A separate diagnostic measured 451 pixels of document content. An unbroken login headline overflowed its own box even though element bounds fitted the viewport. The correction permits word wrapping in that headline. The overall a2 attempt remained failed and its operator journey remained unexecuted. The final installed attempt passed all four journeys and the operator workflow. Earlier targets, wheels, captures, diagnostics and logs remain distinct and preserved privately.

## Scope and limits

Current role, organization, session expiry, Origin and CSRF checks remain authoritative. A local client cannot undo a committed write by retiring its intent. Ordinary operator recovery preserves the difference between version conflicts and an uncertain committed request. No session or access recovery performs an automatic business POST.

Public configuration, request/session limits and negative fixtures do not establish resistance to distributed abuse, production security, sensitive data suitability, failover or operational capacity. Local restart proves the observed application process restart, not host replacement, storage recovery or database disaster recovery. Text resizing, appearance and viewport emulation do not prove physical device, BFCache or every accessibility setting.

The native restore qualification remains the v0.8.0 Windows/PostgreSQL 18.1 trusted archive, direct loopback, same cluster route. There is no new native dump/restore run, managed service restore, native Linux restore, cross version restoration or production backup claim here.

SHARED_PC remained active. Verification used files, APIs and isolated headless pages without foreground capture/control, real browser profile attachment, clipboard, audio or a GPU campaign. Private connection records, credentials, database state, raw logs and unreviewed captures remain outside public Git. Public source, downloadable assets, installed acceptance, local TLS staging and actual hosting are separate delivery layers.
