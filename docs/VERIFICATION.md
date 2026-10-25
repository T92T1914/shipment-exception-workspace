# Explicit refresh coordination verification

Version 0.8.1 corrects a client race: an explicit Refresh workspace action now
joins the existing authoritative session-check owner, including a queued
lifecycle check, before reloading current records. A matching background check
can no longer discard the requested refresh through a competing generation.
Failed checking hides the unconfirmed workspace and offers manual recovery.
The server's current authorization remains authoritative.

The [v0.8.0 verification](VERIFICATION-v0.8.0.md) retains the completed native
backup/restore outcome and its adverse history. Earlier versioned records also
remain intact. This patch does not repeat or extend native restore qualification.

## Baseline witness

The baseline was the ordinary installed v0.8.0 wheel in a fresh environment and
new task-owned PostgreSQL database. An actual API creation produced version 1.
An independent actual assignment advanced the server to version 2 with two
history events, while the existing page still displayed version 1.

The regression held the explicit refresh's actual session response, dispatched
a focus event to invoke the installed lifecycle listener, and controlled both
response deliveries. The strengthened witness awaited the second response's
finished body, checked two matching operator results, observed the refresh
button available again and counted no business POST. The original document
still displayed version 1. The regression failed at the expected version-2
assertion. This was an executed installed-client fault, not a claimed server
write failure or organization bypass.

A first command matched no tests because its grep was anchored before the
composed file/title prefix. That exit 1 ran no journey and supplied no baseline
proof. The corrected first witness and stronger delivered-response witness ran
against separate fresh state and remain retained with their actual failures.

## Candidate and local execution

The combination was Windows x64, CPython 3.13.3, PostgreSQL 18.1, Node 24.16.0,
React 19.3.1 and the unchanged dependency locks. Isolated browser checks used
Playwright 1.64.1 and the already qualified Chromium headless shell. Limits were
two build/test threads, one heavy campaign and one browser worker. SHARED_PC
remained active without screen capture, real-browser attachment, clipboard,
audio, visible fallback or GPU execution.

The narrow runtime change awaits synchronizeSession(), then checks mounting,
active user, captured epoch/context and current authenticated session facts.
It does not reinstall the earlier refresh response. The existing shared owner
still retires changed sessions and actual uncertain operator intents, while a
same-actor reviewer with no pending intent can keep readable selected detail.

| Local check | Actual result |
| --- | --- |
| Build and ordinary installation | v0.8.1 wheel built, installed into a fresh environment outside the checkout and imported from site-packages. Installed restart/workflow consumer passed. |
| Package identity | All 16 installed package payload members matched the actual wheel. Source archive checks include changed client/test bytes, new guide/restore tools, security notes and migration fixtures. |
| Full installed browser campaign | All 53 journeys passed, with zero skipped, unexpected or flaky results. These comprise the original 47 and six new controls. |
| Backend applicability | Server code, backend tests, SQL and pins are unchanged apart from package-version metadata. The earlier 271-case execution is labeled reused local evidence, not a new local suite run. |
| Preservation | Three accepted v0.8.0 artifact digests, 42 selected accepted metadata/credential files and all other worktree identities/status remained equal under the declared checks. No whole-database-tree byte comparison is claimed for this patch. |
| Owned resources | Both fresh baseline apps and the candidate app were stopped with exact ownership checks. Only the new cluster was stopped, with retained data/environments/logs and no listeners on its recorded owned ports. |

The execution source was
[3818e3c6f69533f531e371f0fef35cc09d9e5928](https://github.com/T92T1914/shipment-exception-workspace/commit/3818e3c6f69533f531e371f0fef35cc09d9e5928).
The five-entry report sampled fingerprint
479eb93428c57a633b53322b955584592f7a5441cce5dc65ce162bcda5e3c917
before/after each check. Browser-reported duration was 96.795 seconds.
The local wheel SHA256 is
a07c28558aca20df5208cbe1ba4c4a016fea2a85b45ea2a8ad5dc71a02ca4e30.
Later evidence prose and branch naming are separate from that execution.

## Six added controls

- Desktop keyboard activation and narrow activation both complete an explicit
  refresh after a matching focus check. Complete delivered responses precede
  the final record/history assertions. No business POST is sent by the refresh,
  the original document remains and server data stays unchanged by reading.
- The narrow fixture doubles the measured root text size through CSSOM, verifies
  its computed value and checks horizontal fit. It is synthetic text resizing,
  not physical-device or browser-zoom acceptance.
- An actual read_only 403 response is held while a lifecycle check starts. Its
  cleanup joins the active check after retiring the actual pending intent.
  Selected readable detail survives, no extra POST is sent, and a later explicit
  refresh reads current state. A finalization lock is not treated as an uncertain
  intent by itself.
- A trailing actual session read learns the same actor's reviewer role. The
  latest access is used without reinstalling the earlier operator response.
- A declared fixture replaces the trailing normally successful session response
  with HTTP 503. The unconfirmed private view clears, no success is invented and
  keyboard activation of Check current session recovers reading without a POST.
- A real shared-cookie account change retires a held refresh. Its old response
  cannot read the retired detail or enter the next organization's workspace.

Non-author review first found an unreachable proposed test ordering: it tried
to click Refresh while sessionChecking disabled it. That test was corrected to
the actual denial-cleanup caller before positive execution. Review also required
computed text-size proof instead of assuming inline style insertion worked under
CSP. These were source/test-design findings, not executed application failures.
Product controls and CSP were not weakened to satisfy the tests.

## Delivery and limits

The normal Linux branch, PR and merged-main workflow independently builds and
checks its actual source/wheel, runs the complete backend suite and exercises the
ordinary installed consumer and full browser suite. Delivery records and PR
receipts distinguish those fresh hosted executions from local reuse and baseline
failures. The exposed Code Review diagnostics are separate from the labeled
independent agent source/evidence review and required human approval.

There is no new dependency, schema, server-policy, background polling or business
retry behavior. Session checking is not a general message rate limiter, and
progress under an endless notification stream is not promised. A failed check
requires explicit recovery. Retired browser intent cannot undo a committed
transaction. Dispatched lifecycle events do not establish actual mobile
suspension, BFCache restoration or instantaneous access notification.

The native restore helper retains its qualified v0.8.0 version admission and
[guide](backup-and-restore.md). No v0.8.1 native dump/restore, cross-version,
failover, disaster-recovery or production-security claim is added. Private raw
reports and new captures stay outside Git. Source/tag/artifact publication is
separate from application hosting. Ragged Pool remains in maintenance unchanged.
