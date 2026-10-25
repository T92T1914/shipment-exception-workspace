# Bounded history verification

The October 25, 2026 local campaign tested implementation
[`ab7c6b8dff04788348f3272dfb12af1b0f1e3072`](https://github.com/T92T1914/shipment-exception-workspace/commit/ab7c6b8dff04788348f3272dfb12af1b0f1e3072)
through an ordinary v0.6.0 wheel installed into a fresh environment outside the
checkout. All seven sequential manifest checks passed with unchanged sampled
source contents. This evidence note and its two synthetic captures were added
afterward. Earlier [v0.5.0](VERIFICATION-v0.5.0.md),
[v0.4.0](VERIFICATION-v0.4.0.md), [v0.3.0](VERIFICATION-v0.3.0.md),
[v0.2.0](VERIFICATION-v0.2.0.md) and [v0.1.0](VERIFICATION-v0.1.0.md) records keep
their original results and scope.

## Executed local results

The tested combination was Windows x64, CPython 3.13.3, PostgreSQL 18.1,
Node 24.16.0 and npm 11.13.0 with the existing dependency locks. Browser checks
used Playwright 1.64.1 and Chromium headless shell 153.0.8010.12, one worker and
an isolated profile. Build/test thread limits were two. No screen, interactive
browser profile, clipboard, audio or visible application was used.

| Check | Actual result |
| --- | --- |
| TypeScript/Vite | Production build passed |
| Wheel/source archive | Built v0.6.0 and checked packaged Python/SQL source identity, built UI, notices and all three immutable migration fixtures |
| Fresh installation | Imported v0.6.0 from external site-packages on Python 3.13.3; pip check passed |
| Installed PostgreSQL suite | 245 passed in 156.33 seconds, with one retained TestClient deprecation warning |
| Installed restart consumer | Retained workflow/reviewer/admission checks plus bounded detail, three-page history, cursor continuation across API restart and append fencing passed |
| Built browser journeys | All 29 passed in 44.7 seconds, retaining the prior 25 and adding desktop/narrow history, failure recovery and delayed-response cases |
| Independent source review | A separate non-author found no remaining semantic or authorization blocker in the inspected implementation and test design |

Local wheel SHA-256 is
`f1acabef55503c4f9bff58532849ed0341cf0af0142716a7cc5d01bf5a32699d`.
The sampled repository fingerprint remained
`c3be382a255f1dc78868d0fa1b9570f9bd723bda5567267214af48ea2dfef9d4`.
Manifest SHA-256 is
`aae2a2344006d0bae78beda8ac304557e976c1fa5e77adf388e8f4019742ba67`.
These identify this local execution, not later hosted build hashes or
reproducible-build guarantees. No earlier accepted consumer was changed,
migrated or reseeded.

## History contract and PostgreSQL checks

The original detail route now returns at most 20 events, together with
continuation metadata. The separate history route defaults to 20 and accepts
at most 50. Each page selects the latest or next older window and returns its
events in ascending version order. Queries fetch one lookahead row to decide
whether a continuation exists, without a total count or offset.

Twenty-four new test instances cover complete 65-event traversal at page sizes
1, 7, 20 and 50, empty and exact page boundaries, equal timestamps and legacy
version gaps without invented creation events. Authentication and same-organization
record lookup precede history-query validation. Both reviewers can traverse their
own organization's records. Foreign/missing records return the same 404.
Cross-record, cross-organization and page-size context mismatches are rejected.
Forged headers and cursor fields do not provide access. Full business rows are
compared around read and denial scenarios.

Validation checks cover unknown/duplicate query parameters, malformed UTF-8,
base64url aliases and padding, oversized/deep JSON, duplicate or extra JSON
fields, integer types and ranges, invalid UUIDs and version relationships.
Generic errors do not echo submitted values. A valid own-context cursor can
skip rows or reach an empty page. This is intentional for an unsigned position,
not evidence that a cursor authorizes access. A sparse SQL boundary fixture
checks the admitted maximum PostgreSQL integer without claiming billions of
events were generated or scanned.

One case commits a real assignment between page requests. The original browse
still traverses exactly its initial versions, while refresh includes the new
version. Another test places a separate committed SQL append precisely after
the real detail record read and before its event query. The first response
keeps the older record version and fence, then a fresh detail request sees the
append. This ordering is explicit and does not rely on a delay or unfinished
thread as its witness.

The fence holds later application appends outside an existing browse. It is
not a full database snapshot. Joined names are current, and privileged database
changes are outside the application contract. A returned-row cap does not prove
scan cost, latency, throughput or denial-of-service resistance.

## Installed consumer and browser evidence

The ordinary installed consumer creates one record and performs 44 real
assignment requests, giving it 45 saved events. It captures the bounded detail
and cursor, restarts the API process, then reads the remaining pages and checks
all versions 1 through 45 exactly once. A subsequent assignment produces version
46. The previous continuation stays fenced, while refresh includes 46. Replaying
the old creation request still returns its historical version-1 receipt, and
the consumer reads current state separately.

The consumer also retains operator and reviewer access checks, business-denial
snapshots, durable queue continuation and login admission across API restart.
Two successful sign-ins and 38 actual failed verifications fill the global
budget. Only that disposable consumer's admission fixture timestamps are expired
before the separate browser campaign.

The 29 serial browser journeys retain all earlier 25. The added desktop and
390-pixel reviewer cases traverse three pages against actual API responses,
check exact versions and bounded rendered rows, move back through the same
boundary, and refresh to newer history. A designated SQL fixture supplies 45
explicitly synthetic events and a controlled version-46 append. These fixture
events are test setup, distinct from the installed consumer's real API requests.

A substituted 503 response tests page-error recovery without losing the current
record or unsent draft. Retrying loads the actual older page. A subsequent real
assignment resets history to the latest page. A delayed real history response
is delivered after a record switch, same-user refresh and logout, and is ignored.
A later clean other-organization login is also checked. That test does not
deliver the old response after the new account has already signed in.

The [desktop history](assets/desktop-history.png) and
[390-pixel history](assets/narrow-history.png) captures were generated from those
journeys and visually inspected. They show the oldest page of the synthetic
record at version boundaries 45 and 46 respectively. This is isolated headless
evidence, not physical-device, screen-reader or translation-provider acceptance.

The UI renders one bounded page and retains only its first and current event
pages, plus cursor positions. Cursor metadata grows with visited pages. Cached
page return is not another server permission check or instant revocation.

## Adverse observations, attribution and hosted checks

The initial source-install attempt used PATH's Python 3.11.8 and correctly
failed the package's Python requirement. That unused environment and refusal
log were retained. The separate explicit Python 3.13.3 environment then passed
24 focused source history checks in 23.38 seconds, followed by the complete
fresh installed campaign above. No acceptance is attributed to Python 3.11.
The TestClient/httpx deprecation and terminal-color warnings remain recorded.

The MIT license, dependency pins, notices, schema 4 and earlier migration/fixture
bytes are unchanged. Credentials, raw private logs, generated connection records
and databases stay outside Git. Test controls require explicit disposable URLs
and supply no HTTP administration endpoints.

Code Review exposed no callable tool. The semantic/security review came from a
separate agent, while GitHub provides actual CI diagnostics. One scoped Consensus
query received the current included-search quota refusal, with reset November 1.
No paper result or paid escalation is claimed. Original PostgreSQL and OWASP
documentation supports design rationale, separate from executed acceptance.

The [Actions workflow](https://github.com/T92T1914/shipment-exception-workspace/actions/workflows/verify.yml)
rebuilds on Ubuntu 24.04 with the pinned PostgreSQL 18.1 container and repeats the
installed suite, separate consumer and all 29 browser journeys. Hosted execution
must match the final PR/main revision and remains separate from this Windows
campaign. See the current run pages for actual tested identities and results.
Source tags identify revisions. Actions artifacts expire and are not permanent
release assets. No public application hosting, production assurance, offensive
capability, employer qualification or awarded achievement is established by
these checks. See [limitations](LIMITATIONS.md).
