# v0.9.0 release and reviewer-deployment verification

Version 0.9.0 adds a separately configured synthetic reviewer deployment while preserving the ordinary local operator application. The public route requires an explicit HTTPS origin, a separately provisioned visitor identity and matching startup configuration. It denies business writes at the server. The built frontend and API still share one origin.

The [v0.8.1 verification](VERIFICATION-v0.8.1.md) preserves the accepted refresh correction and its original evidence. The [v0.8.0 verification](VERIFICATION-v0.8.0.md) preserves the native backup/restore campaign and adverse results. Neither is relabeled as a new v0.9.0 execution.

## Current evidence and pending delivery

| Layer | Observed result |
| --- | --- |
| Backend suite | 323 cases passed, no skips, one existing TestClient warning. This was an installed-package run against new disposable PostgreSQL state, before the core source was committed. Its exact fingerprint is recorded below. |
| Corrected installed HTTPS staging | All four sequential public reviewer journeys passed at candidate `ff0935c23e3aedd9cf6018bb4c73c5dd2228d2a8`. Direct API controls, process restart and controlled session expiry passed separately. |
| Installed operator walkthrough | Actual creation, independent API assignment, stale-version refusal, controlled response interruption, explicit receipt replay, resolution and desktop/narrow reload passed on a different fresh synthetic database. |
| Candidate package acceptance | A fresh external installed consumer passed at `aa565af`, using wheel SHA256 `4ec45d384b142e5c8880fe411fbca0b0cfc6c167806e32cb3ebcd0dc5123625a`. All 25 pure deployment-helper cases and the new narrow enlarged-login browser regression passed separately. |
| v0.9.0 hosted CI and downloadable release | Pending final-revision delivery and public download readback. The completed v0.8.1 release remains separate. |
| Public HTTPS application hosting | Pending actual provider deployment, served-revision readback and public journeys. Local TLS staging is not a deployed application. |

The local combination is Windows x64, CPython 3.13.3, PostgreSQL 18.1, React 19.3.1 and the existing pinned dependencies. Frontend checks use the qualified isolated Playwright/Chromium route with one browser worker. Build/test concurrency remains at two or fewer. These results do not qualify every compatible environment or a managed PostgreSQL service.

## Backend execution identity

The 323-case run imported the ordinary installed package from an external environment and used a support-only external test directory. PostgreSQL fixtures were disposable. No retained accepted consumer database was initialized, reseeded or used as a fixture.

The executed source was uncommitted over the accepted v0.8.1 head. The repository runner recorded stable content fingerprint `2451e76a9b017c61563c2c8a1aa56f94e51d0b41850728d9b1b2e9cefc90962e` before and after the command. The backend core was subsequently frozen at [`a0317171e44c2b97f2e50db89895400e4581aba7`](https://github.com/T92T1914/shipment-exception-workspace/commit/a0317171e44c2b97f2e50db89895400e4581aba7). This is not a claim that the suite was rerun at that commit. Later source and final-package applicability require their own identity comparison or execution.

The suite includes the prior application contracts and 52 new public-demo cases. Parameter-only origin, transport and configuration cases are part of that total. They do not establish actual remote database connectivity. Relevant checks include separate visitor provisioning, refusal to repurpose existing stock state, transactional provisioning failure, current identity at startup, secure cookies, role and organization admission, actual matching saved-receipt denials, session allocation/expiry controls, concurrent slot admission, request-budget behavior and ordinary local defaults. Registration of a configuration value is distinct from connecting to an external service.

The existing FastAPI/Starlette TestClient deprecation warning remains recorded. Dependencies were not upgraded to conceal it.

The owner compared every Python and SQL package member from the initial installed
wheel to the corrected staging wheel and source at `aa565af`. Those bytes agree
exactly. This joins the earlier backend execution to unchanged runtime code,
without presenting it as a rerun. Frontend changes have their own actual staging
journeys. The later fresh environment used only the selected ordinary wheel,
with dependency consistency and installed-path checks, against another new
disposable database. Its ordinary consumer passed process restart, persistent
session/receipt, one business effect after retry, reviewer denial, queue/history
and session-context checks. The 25 helper cases use fake downloads and connections
and do not qualify the provider. The browser regression exercised the ordinary
installed login at 390 pixels and exactly twice its root text size.

## Corrected installed staging

The completed staging candidate was source [`ff0935c23e3aedd9cf6018bb4c73c5dd2228d2a8`](https://github.com/T92T1914/shipment-exception-workspace/commit/ff0935c23e3aedd9cf6018bb4c73c5dd2228d2a8), installed wheel SHA256 `23c6f969600794ec8e89cbf3258d5219b4e19dfe1ae81ecd7036615837c2bcb5`. Installed runtime members matched the selected wheel and candidate source. The frontend was the actual build carried in that wheel.

This route used direct loopback HTTPS with a task-owned self-signed certificate and an exception limited to its isolated clients. No system certificate trust was changed. It does not qualify an external TLS-terminating proxy, provider hostname, managed database or public network.

The actual visitor credential authenticated only the dedicated reviewer. It failed against all six stock accounts. Valid direct create, repeated-key create, assign, unassign and resolve attempts received `read_only` denials without a replay response. Foreign and guessed record references remained unavailable. Wrong Origin and CSRF values were refused. Invalid Host was rejected without allocating a cookie, and supplied forwarded host/protocol headers granted no authority.

The session cookie carried Secure, HttpOnly and SameSite=Strict with the configured expiry. The application process was restarted, then the current session read records again. A controlled database timestamp change expired that specific session and required recovery. This is a fixture-driven expiry boundary, not an elapsed-time longevity result. Complete business-row and event-sequence comparisons remained unchanged across the public checks. Sessions and login-admission rows can still change, so the database is not described as immutable.

Four browser journeys ran serially:

| Journey | Viewport | Appearance and root text |
| --- | --- | --- |
| Desktop | 1440 by 1000 | Light, 100 percent |
| Desktop enlarged | 1440 by 1000 | Dark, 200 percent |
| Narrow enlarged | 390 by 844 | Light, 200 percent |
| Narrow | 390 by 844 | Dark, 100 percent |

Each used the real reviewer entry, server search/filter results, selected record/history, authenticated hash reload, browser-back navigation and explicit sign-out. Keyboard entry, search, record selection and sign-out had observed focus and a visible outline. Enlarged cases checked the actual computed root text size, rather than assuming the requested style took effect. Checked panels fit their viewports. All four sent zero UI business POSTs and recorded no unexpected browser/network errors.

Provisioned public history supplies the read-only browsing examples. It is synthetic setup, separate from the [operator walkthrough](operator-walkthrough.md). That walkthrough performs real application writes and ends at version 4 with four events. Its uncertain assignment makes two identical key/body attempts, receives the actual server's replay marker and adds only one assignment event. Its screenshot identity and limits remain attached to the executed candidate.

## Adverse results retained

The first 52-case public backend run returned 51 passes and one failed new assertion. The API lists each history page oldest first, while that assertion expected reverse order. The assertion was corrected without changing history semantics. The original source and failed run remain retained.

An initial full-suite launcher imposed importlib isolation on existing fixture/support imports and failed collection for ten modules. It executed no backend tests. The corrected external support-only route and independent installed import probe produced the 323-case result above. Collection failure is not counted as an application test pass or failure.

Staging attempt a1 passed two desktop journeys but failed the narrow light 200-percent login layout. Measured content extended to 478 pixels at a 390-pixel viewport. The intro-flow flex row did not wrap. The source correction adds wrapping without hiding overflow or reducing text size. The overall attempt remained failed, and its downstream operator journey was not executed.

Attempt a2 passed direct API/restart/controlled-expiry checks and both desktop journeys, but the same narrow entry still failed. A separate diagnostic measured 451 pixels of document content. An unbroken login headline overflowed its own box even though element bounds fitted the viewport. The correction permits word wrapping in that headline. The overall a2 attempt remained failed and its operator journey remained unexecuted. The final installed attempt passed all four journeys and the operator workflow. Earlier targets, wheels, captures, diagnostics and logs remain distinct and preserved privately.

## Scope and limits

Current role, organization, session expiry, Origin and CSRF checks remain authoritative. A local client cannot undo a committed write by retiring its intent. Ordinary operator recovery preserves the difference between version conflicts and an uncertain committed request. No session or access recovery performs an automatic business POST.

Public configuration, request/session limits and negative fixtures do not establish resistance to distributed abuse, production security, sensitive-data suitability, failover or operational capacity. Local restart proves the observed application-process restart, not host replacement, storage recovery or database disaster recovery. Text resizing, appearance and viewport emulation do not prove physical-device, BFCache or every accessibility setting.

The native restore qualification remains the v0.8.0 Windows/PostgreSQL 18.1 trusted-archive, direct-loopback, same-cluster route. There is no new native dump/restore run, managed-service restore, native Linux restore, cross-version restoration or production-backup claim here.

SHARED_PC remained active. Verification used files, APIs and isolated headless pages without foreground capture/control, real-browser profile attachment, clipboard, audio or a GPU campaign. Private connection records, credentials, database state, raw logs and unreviewed captures remain outside public Git. Public source, downloadable assets, installed acceptance, local TLS staging and actual hosting are separate delivery layers.
