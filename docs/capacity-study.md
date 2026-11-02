# Local queue capacity and recovery study

The protocol in `tools/capacity-protocol.json` declares a finite synthetic study.
At this preparation revision it has not produced a capacity or recovery result.
It qualifies the installed application in a fresh local Windows/PostgreSQL
environment. It never targets the public reviewer demo.

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

Method references: the retained open-arrival decision follows
[Schroeder, Wierman and Harchol-Balter's NSDI paper](https://www.usenix.org/legacy/events/nsdi06/tech/full_papers/schroeder/schroeder.pdf).
The numerical workload and targets are declared choices here, not results from
that paper. Query plans use
[PostgreSQL 18 EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)
outside timed HTTP traffic. Process containment follows
[Windows job objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
Listener identity uses the documented
[owner-PID listener table](https://learn.microsoft.com/en-us/windows/win32/api/iprtrmib/ne-iprtrmib-tcp_table_class).
