# Database interruption and explicit recovery

Version 0.9.1 distinguishes a narrowly classified database outage from an
unexpected internal failure. A failed read can return HTTP 503 with the stable
code `dependency_unavailable` and this message:

> The workspace is temporarily unavailable. Check your session, then refresh the records.

The old generic response said that a change could not be completed even when
only a read or session lookup had failed. The [November 1 capacity study](capacity-study.md)
retains its observed 500 response at the original source identity. This later
correction does not change that historical result or repeat its performance study.

## What to do in the workspace

If a queue or history read fails, use the existing explicit refresh or page
retry after the service becomes available. The message does not suggest changing
the search to repair a database outage. No business action is automatically sent.

If an assignment, resolution or new exception has an uncertain result, the
workspace says that the change may already be saved. `Retry same change` uses
the original request key and body while that context remains eligible. It does
not create another action. `Check current session` makes a session read first,
without sending a business POST. A matching operator session retains the pending
intent. Refreshing records and retrying an uncertain action are different operations.

If the authoritative session check fails, private workspace state and its local
retry are retired. The warning remains: an earlier request may already have
committed. After session recovery, review the current records before beginning
new work. A changed account/context or reviewer role does not inherit an old
operator's pending intent. Client retirement cannot undo a database commit.

The server checks its database backed session before it can establish current
authority. During an outage a reviewer mutation therefore receives the unavailable
response, not a fabricated permission decision. After recovery the reviewer is
still refused with 403 `read_only`, including attempts to replay an old receipt.

## Why classification is deliberately narrow

The request connection boundary in [availability.py](../src/shipment_workspace/availability.py)
recognizes SQLSTATE `08006`, `57P01`, `57P02` and `57P03`. On a previously open
connection, an exact SQLSTATE less Psycopg `OperationalError` also requires
`connection.broken` before cleanup. Explicit application closure is different.

Psycopg 3.3.6 can report a failed new connection without SQLSTATE or a structured
operating system error. The same exception type can represent authentication,
TLS or configuration failures. A bad connection status alone is insufficient.
For this specific path, the failed connection must identify the same numeric
address and port that successfully connected at startup. One TCP diagnostic,
bounded to 2.5 seconds, classifies only an explicit connection refusal. It sends no
credentials or SQL, performs no DNS lookup and does not retry the database request.
A successful TCP handshake never establishes authentication or authorization.

On the executed Windows route, a stopped PostgreSQL listener instead produced
an exact `ConnectionTimeout` without a failed connection object. That exception
alone is not classified. Its additional route requires the parsed connection
configuration to contain one explicit numeric host and port matching the
successful startup connection, without service/host-address or environment
routing overrides. URL query overrides are included in that parsing. It then
requires the same explicit TCP refusal. Windows took about two seconds to report
that refusal, beyond the initial candidate's 250 ms diagnostic. This adds at most
2.5 seconds after the existing connection attempt, whose timeout remains five
seconds. There is one diagnostic, not a transaction retry.

That later diagnostic corroborates current endpoint unavailability, not the
original failure's sole cause. An unknown address, changed endpoint, diagnostic timeout,
diagnostic failure or reachable listener remains unclassified. DNS rotation,
multihost and Unix socket outage routes are not qualified by this mechanism.
Invalid credentials/database, schema errors, integrity errors, query cancellation,
transaction conflicts and unexpected programming errors remain sanitized
`500/internal_error` responses. The implementation does not map every database
or operational error to 503.

The new dependency and internal failure messages use fixed public text. Driver diagnostics, SQL, connection
strings and paths are not returned. There is no guessed `Retry-After`, recovery
deadline, automatic transaction retry or promise that a failed response means
nothing committed. Readiness remains a separate coarse dependency/schema check.

## Inspect the evidence

The focused [backend regressions](../tests/test_dependency_outage.py) inject
documented errors at actual connection, session query, write and transaction
boundaries. They compare full business records, audit entries and receipts.
The committed acknowledgement case commits first and deliberately withholds its
result. It is a controlled fixture, not naturally observed packet loss.

The [browser journeys](../frontend/e2e/outage-recovery.spec.ts) separately exercise
desktop and narrow recovery, keyboard controls, a matching session recheck,
same-key/body replay and retirement after an unavailable session check. Browser
response fixtures keep the database running and are distinct from a native
stopped database consumer. [VERIFICATION.md](VERIFICATION.md) records actual
executions, package identities and publication checks.

The method follows the documented call site principle in section 3.4 of
[Assad et al., ICSE Companion 2024](https://ase.cit.tum.de/research/publications/krusche2024icse-0.pdf).
That research informs fault placement, not this application's correctness.
Exception semantics were checked against [Psycopg 3.3.6 source](https://github.com/psycopg/psycopg/tree/3.3.6/psycopg/psycopg).
[HTTP 503](https://www.rfc-editor.org/rfc/rfc9110.html#name-503-service-unavailable)
does not by itself make an arbitrary POST safe to replay.

The accepted hosted demo and downloadable v0.9.0 Release remain separate from
this source/package correction. A source merge does not establish a hosted
upgrade. No public demo fault, load test, failover, power loss, transaction crash
or production availability qualification is claimed.
