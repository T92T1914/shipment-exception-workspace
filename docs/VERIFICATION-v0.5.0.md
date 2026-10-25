# Reviewer access verification

The October 24, 2026 local campaign tested implementation commit
[`333b98300ffa4f36deb2905c69fa851310781b8c`](https://github.com/T92T1914/shipment-exception-workspace/commit/333b98300ffa4f36deb2905c69fa851310781b8c)
through a fresh ordinary v0.5.0 wheel installed outside the checkout. All seven
sequential manifest checks passed with unchanged before/after source samples.
This evidence note and two synthetic captures were added afterward. Earlier
[v0.4.0](VERIFICATION-v0.4.0.md), [v0.3.0](VERIFICATION-v0.3.0.md),
[v0.2.0](VERIFICATION-v0.2.0.md) and [v0.1.0](VERIFICATION-v0.1.0.md) records retain
their historical scope.

## Executed local results

The tested combination was Windows x64, CPython 3.13.3, PostgreSQL 18.1,
Node 24.16.0 and npm 11.13.0 with the existing dependency locks. Browser checks
used Playwright 1.64.1 and Chromium headless shell 153.0.8010.12, one worker and
an isolated profile. Build/test thread limits were two. No screen, interactive
browser profile, clipboard, audio or visible application was used.

| Check | Actual result |
| --- | --- |
| TypeScript/Vite | Production build passed |
| Wheel/source archive | Built v0.5.0; package source/SQL identity, built UI, notices and all three immutable schema fixtures checked |
| Fresh installation | Imported v0.5.0 from the external environment's site-packages; pip check passed |
| Installed PostgreSQL suite | 221 passed in 151.51 seconds, with one retained TestClient deprecation warning |
| Installed restart consumer | Operator receipt/admission/cursor behavior and reviewer reads/business-write denials passed before and after API restart |
| Built browser journeys | All 25 passed in 40.0 seconds, including desktop/narrow reviewers, stale access and denied replay after an actual interrupted commit |
| Independent source and claim review | Separate agent found no remaining material semantic, authorization, privacy or public-claim issue in the inspected composition |

The local wheel SHA-256 is
`d35ef148acc2145fb829a3b4e47fc09d1fc4e42be94c3e4edc8114c6d853213e`.
The repository content fingerprint remained
`1392ec7b15c7918616958f823e2c9531a590b56522cac620d7aa6cbe797765d7`.
Manifest SHA-256 was
`e2e99d79d167ba0e27c71c6fbd352578612a46dda14776729d6cf88ca79f5fed`.
These identify the executed campaign, not reproducible builds or later hosted
archive hashes. The owned app and new database cluster were stopped and retained.
No previously accepted consumer was migrated or reseeded.

## Permission and transaction checks

The suite retains the prior workflow, queue, admission and organization checks.
Fourteen new reviewer test instances cover both organizations' own reads and
foreign-detail 404s, all three valid business-mutation routes, forged claims,
current role changes on an existing cookie, denied keys, saved receipts across
downgrade/restored access, default roles and repeated seeding. Complete exception,
event and receipt rows are compared around denials. Session/authentication
maintenance is separate, so these are not claims of zero database writes.

The downgrade-first race captures an already-read operator principal, holds an
ordinary non-key role update, then requires actual PostgreSQL lock-wait evidence
before committing the downgrade. The waiting mutation denies without a business
effect. The mutation-first race holds the actual exception row, confirms the
authorized mutation is waiting there, and confirms the competing role update
waits behind that mutation. Releasing the business row permits its authorized
commit before the downgrade. Events, finite diagnostics and cleanup bound both
scenarios. A sleep or unfinished future alone is not accepted as proof of locking.

A reviewer denial also completes while an uncommitted conflicting receipt key
is held, checking that authorization precedes reservation. Committed create,
assign and resolve receipts are denied after downgrade, remain unchanged, and
can replay their historical results after operator access returns. These are
specific application/transaction tests, not a general revocation or audit claim.

Eight new migration instances cover the exact accepted schema-3 fixture,
explicit upgrade, preserved sessions/receipts/history/admission, operator backfill,
future reviewer default, repeat migration, competing migrators and a final-stage
failure starting from each of schemas 1, 2 and 3. Earlier upgrade checks remain.
The accepted fixture Git blobs are `a5c75d707fa08e65fc6d539424d7be333c8040c4`,
`c8f6bf47db94ae6b0dffeffd136606df1e2029be` and
`1cd24211bec132199e87a7f1ad4175be381fbf9d`. Failure fixtures check rollback of the
whole required chain, including the new role column. Accepted runtime databases
are not migration fixtures.

## Installed browser and recovery evidence

The consumer serves packaged assets from its installed environment, signs in an
operator and reviewer, and checks reviewer reads plus three valid denied writes
against full business-row snapshots before and after API restart. Two successful
sign-ins and 38 real failed verifications fill the global login budget. Restart
preserves the exhausted budget and authenticated workflow. Only disposable
admission timestamps expire before the separate browser campaign.

The 25 serial journeys retain the previous 21 and add desktop/narrow reviewer
reading, queue navigation, history and logout with no business POST. Direct
`#new` navigation cannot expose intake. A stale operator's actual write receives
403 after fixture demotion; explicit refresh observes current access. Another
case obtains a real committed assignment response, drops its delivery, demotes
the actor, and sends the same retry key/body. The real 403 leaves the committed
record/history unchanged and the UI explains that the earlier change may be
saved. It retires the tab's intent and performs no automatic further POST.

The [desktop reviewer](assets/desktop-reviewer.png) and
[390-pixel reviewer](assets/narrow-reviewer.png) captures were generated from
those checks and visually inspected. They contain synthetic records. Native
translation-hint, viewport-fit, stale-response and ordinary operator retry checks
remain. This is isolated headless evidence, not physical-device, screen-reader
or translation-provider acceptance.

## Adverse results, review and limits

The first source regression campaign reported nine failures and 198 passes.
All nine failures were retained literal-data tests expecting four users after
the seed gained two reviewers. Three exact-count assertions now expect six,
preserving their users-table and literal-data checks. The focused follow-up
passed 31 checks, followed by the complete installed campaign above. The earlier
failures remain retained rather than being relabeled as passes.

The TestClient/httpx deprecation and browser NO_COLOR/FORCE_COLOR warning remain
in logs. No dependency pins, MIT license or notices changed. Credentials, raw
private logs, connection records and database files stay outside the repository.
Fixture helpers require explicit disposable URLs and expose no HTTP controls.

Code Review had no exposed tool in this session. Semantic/security and public
claim review came from a separate agent; GitHub supplies actual CI diagnostics.
Neither is a human audit, penetration test, security certification or production
acceptance. Current primary OWASP/PostgreSQL/FastAPI sources support design
rationale, not measured effectiveness or employer endorsement.

The [Actions workflow](https://github.com/T92T1914/shipment-exception-workspace/actions/workflows/verify.yml)
rebuilds on Ubuntu 24.04 with the pinned PostgreSQL 18.1 container, repeats the
installed suite, installs a separate consumer and runs all 25 journeys. Hosted
results are separate from Windows acceptance and must match the current revision.
A tag identifies source; Actions artifacts expire and are not permanent release
assets. See current PR/main run pages for actual tested identities and outcomes.

Role management, privileged database tampering, instant cancellation of earlier
effects, general IAM, production deployment, load capacity and offensive/security
role qualification remain outside this capability. See [limitations](LIMITATIONS.md).
