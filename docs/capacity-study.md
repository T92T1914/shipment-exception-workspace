# Local queue capacity and recovery study

On November 1, 2026, this finite local study completed all 5,400 measured
requests correctly across 24 fresh-state replicates. Each larger-fixture 4-RPS
replicate met the declared 99% completion and sub-second aggregate p95 targets.
The application was retained without an index, pool or query rewrite. Saturation
was not reached at the safe ceiling of eight offered requests per second.
These results qualify this synthetic Windows/PostgreSQL workload, separate from
the accepted hosted reviewer demo.

[Structured results](capacity-results.json) retain every replicate and route,
all three clocks, sample counts, failure categories and resource observations.
Raw request records, complete business snapshots and connection state remain
private. The supplied checker recomputes accounting and reconciliation from a
complete local run. A summary is not a substitute for those underlying records.

## Measured results

The larger fixture contains 5,000 exceptions per organization and 100,000 initial
history events across both organizations. At four offered RPS, each replicate
completed 240/240 measured requests correctly. Scheduled-arrival-to-completion
p95 was 67.2, 66.3 and 65.8 ms. Dispatch-to-response p95 was 55.7, 53.2 and
54.6 ms. Both clocks matter: dispatch-only timing would hide generator delay.
Timing ends after HTTPX has received the complete response, before correctness
validation. A request counts as successful only after validation also passes.

No measured request was refused, failed or dropped. These are observed client
outcomes, not independently instrumented server admission totals. The following
rows preserve the complete matrix rather than pooling repetitions. R/F/D means
refused/failed/dropped. Times are milliseconds. P95 below 200 successes remains
exploratory; an adequate aggregate does not make every route's tail precise.

| Exceptions/org | Offered RPS | Replicate | Correct/scheduled | R/F/D | Scheduled p95 ms | Dispatch p95 ms | Scheduled max ms | Sampling |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 200 | 1 | 1 | 60/60 | 0/0/0 | 67.9 | 54.4 | 71.8 | exploratory |
| 200 | 1 | 2 | 60/60 | 0/0/0 | 70.0 | 54.8 | 112.3 | exploratory |
| 200 | 1 | 3 | 60/60 | 0/0/0 | 62.8 | 51.5 | 68.0 | exploratory |
| 200 | 2 | 1 | 120/120 | 0/0/0 | 64.3 | 56.3 | 77.5 | exploratory |
| 200 | 2 | 2 | 120/120 | 0/0/0 | 71.0 | 62.3 | 169.4 | exploratory |
| 200 | 2 | 3 | 120/120 | 0/0/0 | 67.7 | 53.7 | 159.9 | exploratory |
| 200 | 4 | 1 | 240/240 | 0/0/0 | 60.4 | 53.3 | 75.2 | adequate aggregate |
| 200 | 4 | 2 | 240/240 | 0/0/0 | 62.4 | 51.1 | 162.2 | adequate aggregate |
| 200 | 4 | 3 | 240/240 | 0/0/0 | 62.1 | 51.0 | 161.3 | adequate aggregate |
| 200 | 8 | 1 | 480/480 | 0/0/0 | 62.7 | 54.5 | 160.1 | adequate aggregate |
| 200 | 8 | 2 | 480/480 | 0/0/0 | 63.1 | 55.2 | 173.5 | adequate aggregate |
| 200 | 8 | 3 | 480/480 | 0/0/0 | 65.7 | 56.1 | 179.8 | adequate aggregate |
| 5000 | 1 | 1 | 60/60 | 0/0/0 | 63.2 | 52.7 | 160.8 | exploratory |
| 5000 | 1 | 2 | 60/60 | 0/0/0 | 65.8 | 53.4 | 71.8 | exploratory |
| 5000 | 1 | 3 | 60/60 | 0/0/0 | 71.4 | 59.4 | 170.0 | exploratory |
| 5000 | 2 | 1 | 120/120 | 0/0/0 | 66.5 | 52.9 | 172.1 | exploratory |
| 5000 | 2 | 2 | 120/120 | 0/0/0 | 66.6 | 57.9 | 153.8 | exploratory |
| 5000 | 2 | 3 | 120/120 | 0/0/0 | 68.6 | 54.9 | 147.9 | exploratory |
| 5000 | 4 | 1 | 240/240 | 0/0/0 | 67.2 | 55.7 | 156.4 | adequate aggregate |
| 5000 | 4 | 2 | 240/240 | 0/0/0 | 66.3 | 53.2 | 164.6 | adequate aggregate |
| 5000 | 4 | 3 | 240/240 | 0/0/0 | 65.8 | 54.6 | 173.0 | adequate aggregate |
| 5000 | 8 | 1 | 480/480 | 0/0/0 | 66.3 | 55.3 | 176.6 | adequate aggregate |
| 5000 | 8 | 2 | 480/480 | 0/0/0 | 67.4 | 56.0 | 173.6 | adequate aggregate |
| 5000 | 8 | 3 | 480/480 | 0/0/0 | 68.2 | 57.1 | 187.5 | adequate aggregate |

All per-route samples are below 200, including the highest offered rate. For
example, the first larger-fixture 4-RPS replicate contains 72 unfiltered queue,
72 filtered queue, 48 first-history, 24 deeper-history and 24 assignment requests.
Every route completed correctly. Their individual counts, errors, p50, p95 and
maximum times are in the structured results and retain the exploratory label.
The largest observed scheduled-to-response time in the measured matrix was
187.5 ms. This is an observation, not a latency bound or production SLA.

## Diagnosis and retained behavior

A small response page is not necessarily a small database query. The captured
larger-fixture first queue plan scanned/sorted candidate data before returning
21 lookahead rows for a 20-item page. Its instrumented execution time was
2.641 ms, versus 0.208 ms for the smaller fixture. The larger filtered plan
using the literal `_!%` search took 3.094 ms. History lookups used the existing
per-exception/version access path and returned six lookahead rows, then five
remaining rows, for the two five-event pages.

These plans were collected outside timed traffic. Their instrumented SQL times
are distinct from complete HTTP response times, which also include connection,
session, routing and serialization work. The gap does not by itself identify a
connection bottleneck. The declared workload met its targets, so there is no
measured reason here to add a pool, index or query rewrite. No speed improvement
or maximum supported capacity is claimed.

## One controlled interruption and recovery

The harness received a committed version-11 assignment response and withheld it
from its logical caller. It then stopped the fresh owned PostgreSQL cluster.
This deliberately models uncertainty; it is not naturally observed transport
loss or a crash during a transaction. The application process stayed running.

| Event | Seconds from fault-phase start |
| --- | --- |
| Committed reply withheld | 0.032 |
| Owned database stop completed | 1.164 |
| Outage probes completed | 11.218 |
| Owned database restart completed | 11.614 |
| Readiness and authenticated queue read succeeded | 11.716 |
| Receipt, audit and business reconciliation completed | 12.799 |

Readiness returned 503 with `ready:false` during the outage. The reviewer request
returned 500 while its database dependency was unavailable, with no replay
header. This is retained availability failure evidence, not a passed role
check. After recovery, the same reviewer received 403 `read_only` without a
business or receipt change.

Readiness plus the authenticated queue read completed 0.102 seconds after the
restart command completed, meeting the proposed 60-second recovery criterion.
That clock excludes the earlier outage probes. The interval from completed stop
to successful readiness/queue read was about 10.55 seconds, and the complete
fault phase took 12.80 seconds.

Retrying the exact original key/body returned the original historical response
with `Idempotency-Replayed:true`, leaving all business rows unchanged. A changed
body under that key returned 409 without replacing its receipt. A stale new
intent returned a separate saved 409 receipt. One later valid assignment advanced
the record to version 12. Old-fence traversal still yielded exactly versions
1 through 11; a refresh observed fence 12. Final reconciliation found two
committed assignments, two new events and three complete receipts, including
the stale-intent refusal. No duplicate committed mutation or unexplained
business/event/receipt change was found.

## Execution identity, controls and limits

The measurement harness was frozen at
[`8ab09aa`](https://github.com/T92T1914/shipment-exception-workspace/tree/8ab09aab8b2a1a9d83c26354de04fc599830a16a).
It consumed a new local v0.9.0 wheel with SHA256
`a5b32405a385617058e08bf13d3bc5a0a1daf85e3753af66c1611be590e2a402`.
The driver compared every installed application payload member against that
wheel. This candidate is separate from the already published v0.9.0 Release
asset; neither that asset nor the accepted Render application was replaced.

The host was Windows NT build 26300 with an AMD Ryzen 7 7800X3D. The job admitted
logical CPU IDs 0 and 1, Python 3.13.3 and native PostgreSQL 18.1. Dependency pins
were retained. The shared host and caches were not controlled as an exclusive
benchmark machine. Fresh-state replicates used different databases in one
new cluster, not independent cold machines.

The campaign charged 2173.007 active seconds, about 36.22 minutes, including
warmup and fault work. Its entire supervisor lifetime, including setup and
checking, was 2621.051 seconds, about 43.68 minutes. No extra performance
confirmation or optional public-mode trial ran. Peak job commit was 408.3 MiB,
peak sampled sum-of-process RSS was 652.0 MiB and peak monitored task storage
was about 1.476 GiB. Limits remained two logical cores, 3 GiB memory and 2 GiB
state/output. RSS may double-count shared pages. The supervisor waits one second
between scans; actual recorded sample gaps ranged from 2.275 to 5.568 seconds,
with a mean of 2.774 seconds across 944 gaps. Disk and RSS observations are
sampled, not continuous maxima or a filesystem quota. The owned stop path is
checked after each scan.

All timed queue reads use first pages. Complete frozen queue enumeration was a
separate functional setup check. Timed history visits fixed ten-event records;
it does not qualify long individual histories or arbitrary data distributions.
All initial records are open, so resolved-status selectivity is unqualified.
There is no public-demo admission, WAN, Linux capacity, production load, power
loss, failover or disaster-recovery qualification in this study.

The final reusable driver adds one admission-only safety correction after the
frozen measurement: it refuses inherited `PG*` environment names before any
helper or administrative connection. Libpq may fill unspecified connection
parameters from those defaults, including `hostaddr`. The measured environment
had no inherited `PG*` names, and actual endpoints matched the owned cluster.
A controlled regression showed the earlier source reaching a mocked helper
with an ambient option, while the final source refused before setup. It did
not contact a remote target. This change does not retune the workload or imply
a fresh execution of the matrix at a later documentation head. The final checker
also refuses response-validation errors regardless of the aggregate target.
The complete retained run passed that stricter checker.

Preflight adverse records remain separate from baseline results: wrong nested-job
lookup, masked-address comparison, all-endpoint state interpretation, a string
rather than UUID diagnostic cursor, and a launcher cleanup race. The corrected
functional setup passed before the baseline. No failed setup is counted as a
performance replicate. The existing TestClient deprecation warning remains.

Owned application processes and the new PostgreSQL cluster were stopped, with
postmaster status checked. State, logs and failed preparations were retained.
The hosted reviewer demo was not a target.

## Frozen method


Two organizations receive overlapping synthetic references, 200 or 5,000
exceptions each, and ten initial history events per exception. Each of the four
offered rates, 1, 2, 4 and 8 requests per second, has three independent fresh
database replicates. A run schedules 30 seconds of warmup and 60 seconds of
measurement. The repeating mix is 60% queue, 30% history and 10% assignment.
History uses five-event first and continuation pages. Assignment intents use
distinct open records and the actual version and saved-receipt contracts.

Arrivals are scheduled independently of responses. Eight requests may be in
flight. A full dispatch cap or more than 250 ms of generator lateness produces
an explicit dropped slot. Requests have a twelve-second total deadline. The
final drain counts against the active budget. Completion uses every valid
scheduled measurement slot, including drops, transport failures and 429/503
refusals. Server admission totals remain unknown without server instrumentation.

Both dispatch-to-completion and scheduled-arrival-to-completion clocks are
reported. The proposed larger-fixture/four-RPS target uses the latter: at least
99% correct completion and successful aggregate p95 below one second in each
adequately sampled replicate. Percentiles with fewer than 200 successes are
exploratory. Per-route samples, failures and maximum times remain visible. These
are study criteria, not a production SLA or promised result.

The qualified launcher uses a Windows job for the supervisor and descendants,
with two logical cores, aggregate committed memory limited to 3 GiB, a sampled
3 GiB sum-of-process-RSS threshold, and a sampled 2 GiB combined state/output
threshold. RSS can count shared pages more than once. Disk sampling is not a
filesystem quota. A task-owned stop file and job termination provide the stop
path. The baseline takes 36 active minutes before drains. Fault work is limited
to five minutes. At most two further 90-second confirmations may support one
evidenced correction. The complete active trial/fault ceiling is 45 minutes.

Every trial checks its fresh database marker, effective direct-loopback endpoint
and owned HTTP listener ancestry. The driver compares the installed package
payload with the selected wheel. Complete ordered business snapshots and an
original-intent ledger support offline reconciliation. These private records
exclude account tokens but include fixture connection state and stay outside
public Git. Only reviewed synthetic summaries are suitable for publication.

One separate fault case withholds a committed response from its logical caller,
stops only the disposable PostgreSQL cluster and restarts that same cluster.
This is synthetic response uncertainty, not an observed network failure. The
same intent must replay its historical receipt without another mutation or audit
event. Recovery requires readiness and an authenticated queue read, measured
from completed database restart. Organization, reviewer, conflict and history
fence checks remain separate from performance statistics.

The ordinary installed consumer uses a different disposable database from the
backend tests and from the study. No cloud changes, application deployment,
dependency upgrade, new worker, pool or index is required by this study.

## Reproduce the declared local route

Use a separate source worktree, Python 3.13.3, native PostgreSQL 18.1 and the
repository's locked dependencies. The existing [installation guide](install.md)
and README describe building the frontend and wheel. Prepare separate build
and installed-consumer environments. Install the actual locally built wheel,
then run the ordinary installed consumer with a new disposable database before
attempting the study. Keep test, consumer and study database identities separate.
Run setup/build commands through the same resource supervisor, serially, with
their new output directories and retained preparation files included in disk
monitoring. This is a Windows route, not a Linux capacity qualification.

The supervisor accepts a private JSON command file with `argv` and `cwd`.
For example, after preparing an installed environment and candidate wheel:

```json
{
  "argv": [
    "C:/study/consumer-env/Scripts/python.exe",
    "C:/source/shipment/tools/qualify_capacity.py",
    "--protocol", "C:/source/shipment/tools/capacity-protocol.json",
    "--output", "C:/study/campaign/study",
    "--python", "C:/study/consumer-env/Scripts/python.exe",
    "--wheel", "C:/study/dist/shipment_exception_workspace-0.9.0-py3-none-any.whl",
    "--pg-bin", "C:/Program Files/PostgreSQL/18/bin"
  ],
  "cwd": "C:/study"
}
```

Replace these example paths with your own new task-owned locations. The command
file contains no database URL, password or arbitrary HTTP target. The driver
creates its own cluster and each fresh trial database. The supervisor's output
directory must not exist yet. Including its parent in `--watch-root` counts
prepared environments and retained runs without counting nested paths twice.

```powershell
python C:/source/shipment/tools/capacity_windows.py `
  --output C:/study/campaign --watch-root C:/study `
  --command-file C:/study/command.json
```

Creating `C:/study/campaign/STOP` requests termination of that owned process job.
An interrupted or over-budget run remains incomplete. Do not automatically
repeat the full matrix or fault case. After a complete run, recompute its
accounting and business invariants with the same installed interpreter:

```powershell
C:/study/consumer-env/Scripts/python.exe `
  C:/source/shipment/tools/check_capacity_run.py --run C:/study/campaign/study
```

Keep the raw run private. It contains cluster connection records alongside
synthetic measurements. Review an explicit summary before publishing it.

Method references: the retained open-arrival decision follows
[Schroeder, Wierman and Harchol-Balter's NSDI paper](https://www.usenix.org/legacy/events/nsdi06/tech/full_papers/schroeder/schroeder.pdf).
The numerical workload and targets are declared choices here, not results from
that paper. Query plans use
[PostgreSQL 18 EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)
outside timed HTTP traffic. Process containment follows
[Windows job objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
Listener identity uses the documented
[owner-PID listener table](https://learn.microsoft.com/en-us/windows/win32/api/iprtrmib/ne-iprtrmib-tcp_table_class).
