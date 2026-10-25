# Read-only recovery verification

The October 25, 2026 campaign reproduced a v0.7.0 client recovery defect, then
verified a v0.7.1 correction through ordinary wheels installed outside the
checkout. A successful session read could learn reviewer access while an
uncertain operator change remained pending. Retry, refresh, sign-out and search
then stayed disabled. The server's authorization was not bypassed.

Initial implementation
[`0cc074045ea285e8df3c5703743c1aff06b98e7a`](https://github.com/T92T1914/shipment-exception-workspace/commit/0cc074045ea285e8df3c5703743c1aff06b98e7a)
passed the backend suite and installed consumer but failed an existing browser
role-denial case. Correction
[`f7ae5de21eb40ae32d800ba217d4a39234973e87`](https://github.com/T92T1914/shipment-exception-workspace/commit/f7ae5de21eb40ae32d800ba217d4a39234973e87)
then passed all 47 browser journeys in a fresh corrected installation. This
verification note and a source-archive security-note check were added afterward
without changing runtime or the business/browser tests.

Earlier [v0.7.0](VERIFICATION-v0.7.0.md), [v0.6.0](VERIFICATION-v0.6.0.md),
[v0.5.0](VERIFICATION-v0.5.0.md), [v0.4.0](VERIFICATION-v0.4.0.md),
[v0.3.0](VERIFICATION-v0.3.0.md), [v0.2.0](VERIFICATION-v0.2.0.md) and
[v0.1.0](VERIFICATION-v0.1.0.md) records retain their original results and limits.
The v0.7.0 archive preserves accepted Git content, without a claim that Windows
CRLF and earlier LF working copies have identical physical bytes.

## Reproduced baseline

The accepted v0.7.0 wheel was installed in a new external environment against a
new disposable PostgreSQL database. On one isolated browser document, an actual
assignment committed HTTP 200, advanced version 1 to 2 and added one audit event.
Its response was dropped. The synthetic role fixture then demoted only that
operator. A real session GET learned reviewer access with unchanged actor,
organization and session marker. Retry, Refresh workspace, Sign out and Search
queue were all disabled. The saved record did not change after that role read.
The witness, screenshot, installed environment and database remain private.

This establishes a client liveness and recovery defect. It does not establish a
server authorization failure, duplicate mutation or failed earlier transaction.
The baseline used a synthetic focus event to invoke the existing check handler,
not an observed physical tab-switch or mobile suspension.

## Local execution and correction

The tested combination was Windows x64, CPython 3.13.3, PostgreSQL 18.1,
Node 24.16.0/npm 11.13.0, Playwright 1.64.1 and Chromium headless shell
153.0.8010.12. Dependency locks are unchanged. Build/test thread limits were two,
with one heavy campaign at a time and one isolated browser worker. No real
browser profile, screen, clipboard, audio, visible application or GPU was used.

| Check | Actual result and identity |
| --- | --- |
| Package and installed identity | Ordinary wheel built and checked; installed in a fresh external environment, with imports from site-packages and dependency consistency accepted. |
| Complete PostgreSQL suite | 263 passed in 170.96 seconds at initial implementation 0cc0740, with one retained TestClient deprecation warning. |
| Initial installed consumer | Passed API process restart, current session/role enforcement, original retry receipt and persisted workflow/history checks. |
| Initial browser campaign | Failed: 23 passed, one existing role-denial case failed, and 23 later cases did not run. The failed wheel, environment, database, log, screenshot and error context were preserved. |
| Backend evidence applicability after correction | Reused the original 263-test execution only after unchanged backend/tests/consumer/pins and exact Python/SQL wheel-member byte checks. This was not another local PostgreSQL execution. |
| Corrected installed consumer | Passed again in a fresh environment against a separate new consumer database. |
| Corrected browser campaign | All 47 passed. JSON reports 77.607 seconds, zero skipped, unexpected or flaky. |
| Final source payload | Source-archive inspection found SECURITY.md omitted by the earlier manifest. The manifest now includes it, and the package checker requires its exact current bytes. The corrected archive passed that check and the final payload comparisons. |
| Independent review | A non-author agent reviewed source, test design, evidence and public boundaries. Source review is distinct from runtime acceptance, CI and required human approval. |

The initial helper also treated an owned mutation lock as unresolved intent.
During the existing explicit 403 read_only cleanup, the pending intent had
already been cleared, but the lock remained held while access refreshed. Full
retirement then cleared a record that should stay readable. The existing test
caught this regression after the first source review had missed it.

The correction checks the actual pending intent. It is installed synchronously
before the first asynchronous business dispatch, so interrupted and in-flight
requests remain covered. Confirmed completion or explicit denial clears that
intent. A remaining finalization lock alone no longer triggers retirement. The
existing assertion and timeout were preserved, and the corrected campaign
passed that case and every later journey.

Initial wheel SHA256:
`98fc8e3f325d1f8b7f9991634f5a58566a37ebeb94c8b6b164c2a46fca4d3e79`.
Corrected artifact identity is retained with the private acceptance record and
can be compared with the separately built hosted artifact. Build digests
identify their actual files, without a reproducible-build guarantee.

## Changed behavior and regression coverage

An authoritative session response reporting reviewer access retires a pending
operator intent through the existing workspace/response-epoch cleanup. It clears
unusable write drafts and the local retry, installs current server facts and
reloads the queue on the role change. A delayed old completion cannot restore
its view or clear a later action's ownership. The recovery warning preserves
that the earlier request may already be saved. No business POST is replayed.

The five new journeys retain the previous 42 and cover:

- Actual committed assignment responses dropped or held, at desktop and
  390-pixel widths, followed by a real session response reporting reviewer.
- Unchanged actor, organization, session marker and browser document across the
  observed role transition.
- Retirement of the old intent, a persistent earlier-commit warning, available
  read-only search/detail/history/refresh/sign-out, unchanged saved state and
  exactly one browser business POST.
- Completed delivery of the held old HTTP 200 before checking that no stale
  success message or detail state returned.
- A matching operator session check preserving its uncertain retry. The later
  explicit retry uses the original key/body and returns the saved result without
  adding another event.

Setup records are created through the actual API. The guarded role fixture
changes one synthetic actor in the dedicated disposable database. Lifecycle
signals are dispatched events followed by actual HTTP/database execution. They
are not actual BFCache, mobile suspension, physical-device or production tests.

## Publication and limits

The existing GitHub workflow independently builds and installs the final wheel,
runs the complete PostgreSQL suite, restarts the installed consumer and exercises
the browser journeys on its exact tested revision. PR, merge and main workflow
identities/results are separate delivery evidence and are linked in the final
acceptance record. A workflow definition or earlier result is not a current pass.

Schema 4, SQL migrations, server authorization, transaction/receipt behavior,
license notices and dependency pins are unchanged. Client recovery applies only
after access is observed. It does not cancel an admitted transaction, provide
instant role-change notification, serialize authentication, restore a lost
retry after page closure, or establish production security. Source/artifact
publication is not public application deployment. Ragged Pool was retained at
maintenance and no other repository or public profile was changed.
