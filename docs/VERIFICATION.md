# Local backup and restore verification

The October 25, 2026 campaign qualifies one trusted local schema-4 PostgreSQL
18.1 dump/restore route through an ordinary installed v0.8.0 application.
The source stayed quiet while its complete logical fingerprint was captured,
dumped, compared and later rechecked. A separately named empty target matched
before any target application or session request started.

The practical [backup and restore guide](backup-and-restore.md) contains the
native recipe, privilege assumptions, failure handling and exclusions. Its
actual Python heredoc was executed against another fresh target, rather than
only checked as prose.

Earlier [v0.7.1](VERIFICATION-v0.7.1.md), [v0.7.0](VERIFICATION-v0.7.0.md),
[v0.6.0](VERIFICATION-v0.6.0.md), [v0.5.0](VERIFICATION-v0.5.0.md),
[v0.4.0](VERIFICATION-v0.4.0.md), [v0.3.0](VERIFICATION-v0.3.0.md),
[v0.2.0](VERIFICATION-v0.2.0.md) and [v0.1.0](VERIFICATION-v0.1.0.md)
records retain their own outcomes, warnings, failures and scope.

## Local route and actual results

The combination was Windows x64, CPython 3.13.3, PostgreSQL client/server 18.1,
Psycopg 3.3.6, Node 24.16.0/npm 11.13.0, and the unchanged dependency locks.
Installed UI checks used Playwright 1.64.1 with isolated Chromium headless shell
153.0.8010.12. Limits were two build/test threads, one heavy campaign at a time
and one browser worker. No real browser profile, screen, clipboard, audio,
visible application or GPU was used.

| Check | Actual outcome and scope |
| --- | --- |
| Ordinary wheel and source payload | Built v0.8.0 and installed it in a fresh external environment. Imports came from site-packages. Package checks include exact bytes for the new guide, tools and guard tests, with the earlier security-note check retained. |
| Initial complete backend suite | 270 passed, one new identity-guard case failed, one TestClient deprecation warning. This is a retained failed campaign, not a whole-suite pass. |
| Original installed consumer/UI | Restart, workflow, roles, history, receipts and session consumer passed, followed by all 47 original journeys. Their later applicability is explicitly checked by unchanged runtime/callers and all 16 installed wheel payload members. This is reused execution, not another local browser run. |
| Corrected affected guard tests | Eight passed. These include parameter-only admission cases and actual PostgreSQL same-identity/nonempty checks. No assertion was weakened. |
| Final native route and restored API consumer | Passed at b0d40e76f3fbf99f552e7ca76c282b8095a1b4d7, including complete pre-app readback, current authorization, retained receipt replay and a subsequent valid write. |
| Actual guide recipe | Passed against a separate new target, with complete logical comparison and unchanged source. |
| Restored installed UI | Two fresh desktop/narrow journeys passed, reading the preserved resolved record and its three history events as operator and reviewer. |
| Source preservation | Complete source fingerprint stayed equal before/after dump, native controls, restored API, guide recipe and restored UI. |
| Prior accepted state | Read-only byte comparisons of 2,381 retained files, covering the previous stopped cluster and selected credential/artifact files, remained equal. Prior source worktrees and environments were not reset, migrated, seeded or replaced. |
| Independent review | Non-author source, test-design, evidence, packaging and public-claim review. This does not mean independent repeated execution or required human approval. |

The ordinary local wheel SHA256 is
`3f4fd65452d25a5a80bcca1a4eb9cc02669d4b10a3e352fecc9a20df75b27be1`.
Source-only guard corrections did not rebuild that unchanged runtime wheel.
The final local report sampled fingerprint
`2bff9931d45a3a56838dfe9630524475f258e0482511dab69a14e677d4bb2994`
at the committed execution revision. Later evidence/qualification prose is
separate from that execution. Full private reports retain exact commands,
content identities, phases and native logs without publishing archive rows,
passwords, session material or connection records.

## What was preserved

The fresh source used supported initialization/seeding and actual API creation,
assignment and resolution. It contained two synthetic organizations, six users,
seven shipment records, four audit events, four mutation receipts, four sessions
and saved login-admission state. These counts describe this fixture only. They
were not the equality criterion.

The comparison hashes every complete ordered row in all nine application
tables, including password hashes, current roles, session/CSRF/expiry values,
receipt fingerprints/status/JSON and admission counters/timestamps. It also
compares columns/defaults/identity metadata, constraint definitions and
validation, indexes, object ownership/ACL and actual sequence configuration,
ownership, last_value and is_called. Physical files, database OIDs and planner
statistics are outside this logical comparison. Default per-database settings,
existing matching cluster roles and only the declared application shape are
preconditions, not recovered cluster configuration.

A deliberately unused sequence value left last_value 5 and is_called true,
while the largest saved event ID was 4. Restoration retained that gap. The next
valid assignment used event ID 6 without a collision. Reconstructing sequence
state from MAX(id) would not have established this result.

The original creation receipt still described version 1 of a record now at
version 3. An explicitly authorized replay under the same actor/key/body
returned that historical response without changing any shipment, event or
receipt row. It was not presented as current state. Current operator/reviewer,
organization and CSRF checks remained enforced. An unexpired synthetic saved
session was accepted and a declared expired synthetic session was refused.
No expiry was extended, and saved 60-second admission timestamps were not
claimed to remain active indefinitely.

## Actual refusal and failure controls

The normal route restored the entire trusted custom-format archive using
pg_restore --single-transaction, with no --clean, archive-driven --create or
parallel jobs. Separate disposable controls established:

- Two connection syntaxes resolving to the same actual database were refused
  before the restore tool ran. An unexpected endpoint was rejected before a
  connection attempt.
- Targets containing a populated table, function, enum type, extra schema,
  collation or PostgreSQL large object were refused before the archive ran.
  Their marker state, including the table row and large-object payload, stayed
  unchanged.
- Missing and truncated archives each produced native exit 1, with their
  distinct target's empty logical state unchanged.
- A private edited TOC omitted the users table definition while retaining its
  data. The verbose native log showed earlier table creation and data work,
  then exit 1. Actual readback matched that target's pre-restore empty state,
  demonstrating rollback for this failure. The normal route used the full TOC.

These are bounded observed controls, not storage-corruption, power-loss or
crash-recovery acceptance. Failed targets and logs were retained. There was no
automatic cleanup, repair, reseeding or destructive retry.

## Preserved adverse work and correction

The first implementation
[`a10895a880aa949a88513ac649b7fc1ccafddc9b`](https://github.com/T92T1914/shipment-exception-workspace/commit/a10895a880aa949a88513ac649b7fc1ccafddc9b)
used inet_server_addr()::text to compare the effective host. PostgreSQL includes
the /32 netmask in that cast, so a valid loopback endpoint was rejected before
the intended same-database refusal. The new test caught this. Native
qualification then stopped at preflight before source setup or any dump/restore.
Dependent restored-UI commands had no prerequisite state; no restored journey
was executed in that failed campaign.

Correction
[`f14848296e8cc6e1456439ba30c93980e0836427`](https://github.com/T92T1914/shipment-exception-workspace/commit/f14848296e8cc6e1456439ba30c93980e0836427)
uses host(inet_server_addr()), with the original assertions intact. Its fresh
round trip passed. Independent review then found that the pristine-target check
missed large objects outside public namespace dependencies. Final correction
[`b0d40e76f3fbf99f552e7ca76c282b8095a1b4d7`](https://github.com/T92T1914/shipment-exception-workspace/commit/b0d40e76f3fbf99f552e7ca76c282b8095a1b4d7)
added that refusal and its retained-payload control. The complete affected
native/API/guide/UI proof passed on another new source and target. Earlier
positive and failed state remains separate. This is review-driven correction,
not an observed overwrite or a native restore success claimed for the failure.

## Publication and limits

The ordinary Linux workflow independently builds/checks the final source and
wheel, runs the complete backend suite and original installed/UI consumers at
its actual revision. Those results are separate from this Windows native
restore qualification. Linux application CI is not a Linux pg_dump/pg_restore,
cross-version or production-backup result. Final PR/main identities and outcomes
are recorded separately during delivery.

The package keeps schema 4, existing dependencies, server authorization,
transactions, migrations and frontend runtime behavior. Database restoration
does not restore lost browser intent, automatically replay writes, extend
sessions, preserve cluster-wide roles/tablespaces or establish disaster
recovery. Archives and raw evidence remain private. Source/tag/artifact
publication is not application hosting or a broader security credential.
Ragged Pool remains at maintenance, with no new native or GPU campaign.
