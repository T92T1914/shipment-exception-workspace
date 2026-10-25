# Shared-session coherence verification

The October 25, 2026 campaign reproduced a v0.6.0 account-coherence gap, then
tested v0.7.0 through ordinary wheels installed in fresh environments outside
the checkout. Initial implementation
[`3b9ea4c9de82be89a9455c8f1465af992aa96fc0`](https://github.com/T92T1914/shipment-exception-workspace/commit/3b9ea4c9de82be89a9455c8f1465af992aa96fc0)
passed the complete backend suite and installed consumer, but its browser
campaign failed an existing delayed-response case. Frontend correction
[`4c85922b46ca5223f9ff9baa314cf8e40bcb0d7d`](https://github.com/T92T1914/shipment-exception-workspace/commit/4c85922b46ca5223f9ff9baa314cf8e40bcb0d7d)
then passed the complete 42-journey browser campaign on a separate fresh
consumer. The evidence note and new synthetic captures were added afterward.

Earlier [v0.6.0](VERIFICATION-v0.6.0.md), [v0.5.0](VERIFICATION-v0.5.0.md),
[v0.4.0](VERIFICATION-v0.4.0.md), [v0.3.0](VERIFICATION-v0.3.0.md),
[v0.2.0](VERIFICATION-v0.2.0.md) and [v0.1.0](VERIFICATION-v0.1.0.md) records
retain their original results and scope.

## Baseline and executed results

The baseline used an ordinary installed v0.6.0 wheel at accepted source
`d733c340cd54ecad0beaea0e1867e2329c49f895`, a new dedicated database and two
actual isolated browser pages sharing cookies. After the second page signed out
of Northline and into Harbor, the first page retained its Northline identity
label. Its HS- search displayed Harbor rows, while an authoritative session
read correctly identified Harbor. The first page was not reloaded.

This is an observed client identity/cache-coherence mismatch. The server still
authorized against the current shared cookie. It is not a demonstrated
server-side tenant-authorization bypass. The baseline result and capture remain
private, separately from the candidate and its accepted captures.

The tested local combination was Windows x64, CPython 3.13.3, PostgreSQL 18.1,
Node 24.16.0/npm 11.13.0 and the existing locks. Browser checks used Playwright
1.64.1 and Chromium headless shell 153.0.8010.12 with one worker and isolated
profiles. Build/test thread limits were two. No screen, real browser profile,
clipboard, audio or visible application was used.

| Check | Actual result and identity |
| --- | --- |
| Frontend and package | Production builds, wheel/source contents, built UI, notices and immutable SQL fixtures passed |
| Initial installed backend | 263 tests passed in 202.63 seconds on 3b9ea4c, with one retained TestClient warning |
| Initial browser | 20 passed, one timeout, 21 not run; this campaign failed |
| Corrected fresh installation | Ordinary v0.7.0 imported from external site-packages on Python 3.13.3; pip check passed |
| Backend evidence reuse | Exact Python/SQL wheel bytes, backend tests, consumer and pinned inputs remained unchanged after the frontend-only correction |
| Corrected installed consumer | Session rotation, retired-context denial, optional-header compatibility and real process-restart checks passed alongside retained workflow acceptance |
| Corrected built browser | All 42 passed, approximately 1.4 minutes; JSON duration 81.75 seconds, with zero skipped, unexpected or flaky |
| Final local manifest | All seven checks passed, including the explicitly labeled backend-evidence identity check rather than a new backend test execution |

The corrected local wheel SHA-256 is
`41b21991ca7c29c77a88c10457e11d2443142fafc1ac39f57804f146a0232e0c`.
Its sampled repository fingerprint remained
`14d07670ceb157a26812903a43d7c6302ae3ad6c21657c6cb24f7c0593d708bb`,
and retry manifest SHA-256 is
`4d21d57d097e27cc6c9e7608eb48222a1d2683628107cc84e0f7dc3baa31f7e3`.
The initial wheel
`03cd62a233a07debaf5a467f362e78a0f2f38412cc1197d5993b4d41de5010ba`
and failed campaign remain retained. These identify actual builds, not
reproducible-build guarantees.

The backend was not rerun locally merely because frontend response cleanup
changed. Reuse requires the recorded 263-pass result at 3b9ea4c, an empty diff
for backend source/tests/consumer/pins, and identical packaged Python/SQL member
sets and bytes between the initial and corrected wheels. The final identity
check records that distinction explicitly. Hosted final-head and main workflows
still execute the complete backend suite independently.

## Server context and installed consumer

Eighteen new API test instances cover marker representation and stability,
anonymous and authenticated session rotation, same-actor new sessions, all four
private read routes, optional legacy clients, malformed/duplicate/oversized
headers, stale logout, authentication precedence and login rejection before
CSRF/password admission. They also check all three business mutation routes,
unreserved denied keys, unchanged historical receipts and authorized current-
context replay. Full business/security row comparisons check denial side
effects. A focused preliminary source run passed these 18 in 15.19 seconds.

The marker is domain-separated consistency metadata derived from the stored
session hash. It exposes neither that hash, the bearer cookie nor CSRF secret.
It cannot authenticate, choose an organization, provide role authority or
replace CSRF. Header omission remains compatible with existing API consumers.
A same-session database role or organization change does not rotate the marker;
current server policy and authoritative principal facts remain independent.

The corrected consumer runs from installed site-packages and performs a real
same-actor login rotation. It checks stale-marker 409 without value echoes,
authoritative session recovery, cookie-only legacy access and correct-context
reads. Operator and reviewer contexts survive an actual API-process restart,
and the retired marker remains denied. Three successful sign-ins and 37 real
failed verifications fill the global admission budget. This is distinct from
the API test that constructs another app instance using the same cookie.

Retained installed checks also cover queue continuation, 45 real API-generated
events across restart, append fencing, historical creation receipts, current
reviewer denials and business-row preservation. Only disposable admission
timestamps are expired before the browser campaign. Earlier accepted databases
and the failed/baseline consumers are not reset as fresh fixtures.

## Browser behavior and its limits

The 42 serial journeys retain the previous 29 and add 13 cases. Desktop and
390-pixel tests use two actual pages in one browser context. The first document
remains open while another page signs out and signs into Harbor. Its old private
record, draft and filters retire, and Harbor's reviewer identity and queue
replace the earlier view. A document nonce confirms that the first page was
not reloaded. Observed channel messages contain only the declared version and
type, with no marker, identity, role or shipment data.

Three fixtures make the channel missing, its constructor throw, or its send
operation throw. Lifecycle notifications are deliberately muted in those cases
to isolate the real server context-mismatch path. A stale UI request receives
actual 409 `session_changed`, then the page recovers the actual account. This is
a controlled failure fixture, not a cross-browser compatibility result.

Three cases hold actual queue, detail or history responses, sign into the next
account, and deliver the old responses after the new account is active on the
same document. The new identity, queue and selected history remain correct.
Two further cases actually commit an assignment before dropping or delaying its
response. Session change retires the local retry with possible-prior-commit
wording, including a same-actor new session. Exactly one assignment attempt is
observed, with no automatic replay under the next context.

Other cases reject malformed hints, coalesce a held burst of 20 valid hints,
retain drafts during matching-session checks, recover manually after a
substituted session-check 503, and handle a real incorrect-password 401 without
automatic session GET or POST retry. Focus, visibility and persisted-pageshow
events are dispatched by the tests. They are not actual mobile suspension or
back/forward-cache restoration trials.

The [desktop session-change](assets/desktop-session-change.png) and
[390-pixel session-change](assets/narrow-session-change.png) captures were
generated from the two-page journeys and visually inspected. They show synthetic
Harbor records under Harbor's reviewer identity and the recovery notice. No
credential, marker, private path, browser chrome or unrelated desktop content is
included.

Browser messaging is advisory and partition-scoped. No instant frozen-page
erasure, cross-device synchronization or serialization of concurrent
authentication responses is claimed. Discarding an old JavaScript result cannot
undo a browser-applied Set-Cookie or reverse an admitted database commit. Epoch
guards apply after transitions the tab observes. No persistent browser storage
or new authorization system is added.

## Adverse results, review and hosted evidence

The first browser campaign timed out in existing case 21 after reaching the
correct Harbor label and seven rows. Cleanup masked the precise wait site.
The new response helper could reject a stale response after headers without
consuming its body. The correction consumes the admitted body before rejecting
the stale result. The unchanged complete-delivery and no-stale-render assertions
then passed, with diagnostic stages confirming headers, body/render settlement
and a fresh Harbor search. No timeout was increased or test removed.

Source review also caught ordinary invalid-credentials 401 being classified as
a session transition. That was corrected before acceptance and the dedicated
manual-retry browser case passed. Package/doc version-edit mistakes were caught
by diff review and corrected before the implementation commit. Dependency-lock
comparison confirms only the two project-version fields changed. TestClient and
terminal-color warnings remain. No failed or unexecuted result is relabeled.

A separate non-author reviewed the composed source, assertions, evidence and
public claims. Code Review exposed no callable semantic tool. The independent
agent review and GitHub's actual CI diagnostics are labeled separately. The
same-day Consensus exhausted-search receipt is reused as an access limit, not a
new paper result. Original WHATWG/MDN/OWASP sources support rationale, separately
from executed application behavior.

MIT licensing, dependency pins, notices, schema 4, migrations and historical SQL
fixtures are unchanged. The [Actions workflow](https://github.com/T92T1914/shipment-exception-workspace/actions/workflows/verify.yml)
rebuilds on Ubuntu 24.04 with PostgreSQL 18.1 and repeats the complete backend
suite, installed restart consumer and all 42 journeys. Hosted results must
match the final head and merge. See actual run pages for their tested identities
and outcomes. Tags identify source; Actions artifacts expire and are not
permanent release assets. Production hosting, offensive-security qualification,
defense deployment, employer endorsement and GitHub achievement awards remain
outside these checks. See [limitations](LIMITATIONS.md).
