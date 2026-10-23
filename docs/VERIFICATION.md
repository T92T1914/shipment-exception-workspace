# First workflow verification

Local execution on October 23, 2026 used Windows x64, CPython 3.13.3,
PostgreSQL 18.1, Node 24.16.0 and npm 11.13.0. Python dependencies are pinned
in `requirements-lock.txt`, and frontend dependencies in `frontend/package-lock.json`.
This qualifies the executed combination. It is not a platform compatibility claim.

| Evidence | Actual result |
| --- | --- |
| PostgreSQL API checks | 33 passed, including authorization, two-request races, idempotency, constraints, CSRF and injected rollback |
| TypeScript and Vite build | Passed, built assets included in the Python wheel |
| Installed consumer | Passed outside the checkout, imported from its isolated environment's site-packages |
| API process restart | Session, committed assignment and stored retry response survived a fresh process |
| PostgreSQL process restart | Five records, their versions and state, nine events and ten retry receipts survived the owned cluster restart |
| Headless browser | Six journeys passed with Playwright 1.64.1 and isolated Chromium headless shell 153.0.8010.12 |
| Desktop and narrow viewport | 1440 by 1000 and 390 by 844, keyboard focus and no horizontal overflow checked |
| Package content check | UI, SQL, Python source identity and dependency notices checked inside the wheel |
| Dependency consistency | `pip check` passed. npm production dependency audit reported zero known vulnerabilities at the time of the query |
| Independent source review | Authorization, transactions, frontend races and owned-process cleanup reviewed by a separate agent. Findings were corrected and focused regressions added |
| Remote CI and Code Review | Workflow prepared. The empty public repository is created and its first PR is pending. The exposed Code Review tool reads PR CI diagnostics, so it supplies no semantic review result here |

The browser cases use the real installed API and PostgreSQL. For two recovery
cases, Playwright forwards a real mutation and then discards its response or
substitutes a JSON 500. The database transaction still executes. The tests then
check that retry sends the same key and body and creates no additional effect.
The navigation regression holds an actual response until another record is
selected. These are controlled failure fixtures, not observations of a real
gateway outage or a physical phone.

The rollback test installs a temporary trigger in the disposable test database.
It rejects an audit insert after the exception update, then checks that the
record, event and retry receipt all roll back. No fault-injection endpoint is
included in the application.

## Adverse results retained

The first TypeScript build rejected the CSS import because its Vite type
declaration was missing. Adding the declaration corrected the build.
The first mobile journey completed its writes but timed out on the exact
accessible name of the status filter. An explicit accessible label corrected
that interaction. The later six-case run passed.

The initial PostgreSQL helper hung waiting for an inherited subprocess pipe
after the database started. File-based subprocess capture corrected the helper,
and the exact owned cluster was stopped. The first installed-consumer readiness
attempt was affected by inherited HTTP proxy configuration. Loopback probes now
disable proxy inheritance. A subsequent repeated setup found that seed correctly
preserved the old password while the runner generated a new one. The runner now
retains its private generated password before setup. Verification used a clean
dedicated database after these fixes.

Starlette emits a deprecation warning for its current httpx TestClient route.
The executed tests pass. This warning is retained, not suppressed or described
as a failed assertion. Browser output also reports the runner's NO_COLOR and
FORCE_COLOR environment overlap.

Private raw logs, generated credentials, database files and failed-run
screenshots stay outside the checkout. The public screenshots contain only the
synthetic fixture. No user browser, screen, clipboard or existing project was
used. A Python vulnerability audit, production deployment, penetration test,
load study and physical-device acceptance were not performed.
