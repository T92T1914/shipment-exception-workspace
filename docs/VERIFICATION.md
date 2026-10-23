# First workflow verification

Local execution on October 23, 2026 used Windows x64, CPython 3.13.3,
PostgreSQL 18.1, Node 24.16.0 and npm 11.13.0. Python dependencies are pinned
in `requirements-lock.txt`, and frontend dependencies in `frontend/package-lock.json`.
This qualifies the executed combination. It is not a platform compatibility claim.

The final local campaign tested implementation commit
[`c599d78bd22b567d4aa39e91417bcfa57b7b7345`](https://github.com/T92T1914/shipment-exception-workspace/commit/c599d78bd22b567d4aa39e91417bcfa57b7b7345)
from a clean checkout state. Its wheel SHA-256 is
`02004cd92e8aeed9a8b82b2514ad4c4a41c3530daa46c3d7ddd7cf52489f8885`.
The final campaign installed that wheel into a newly created environment outside
the checkout, then ran the API tests and browser consumer against the installed
package. Its repository fingerprint stayed unchanged across all six checks.

| Evidence | Actual result |
| --- | --- |
| PostgreSQL API checks | 33 passed, including authorization, two-request races, idempotency, constraints, CSRF and injected rollback |
| TypeScript and Vite build | Passed, built assets included in the Python wheel |
| Installed consumer | Passed outside the checkout, imported from its isolated environment's site-packages |
| API process restart | Session, committed assignment and stored retry response survived a fresh process |
| PostgreSQL process restart | Five records, their versions and state, nine events and ten retry receipts survived the owned cluster restart |
| Headless browser | Seven journeys passed with Playwright 1.64.1 and isolated Chromium headless shell 153.0.8010.12 |
| Desktop and narrow viewport | 1440 by 1000 and 390 by 844, keyboard focus and no horizontal overflow checked |
| Package content check | UI, SQL, Python source identity and dependency notices checked inside the wheel |
| Dependency consistency | `pip check` passed. npm production dependency audit reported zero known vulnerabilities at the time of the query |
| Independent source review | Authorization, transactions, frontend races and owned-process cleanup reviewed by a separate agent. Findings were corrected and focused regressions added |
| Remote CI and Code Review | Linux build, 33 PostgreSQL API checks, installed restart and seven browser journeys passed. Code Review independently read the exact-head successful CI status and job log. It supplied CI diagnostics, not semantic source review |

## Hosted acceptance

[PR run 40003167787](https://github.com/T92T1914/shipment-exception-workspace/actions/runs/40003167787)
passed for head `00482dbf80500de6c0a48380be4b3c49eb818fcf`, checked out through
GitHub's PR merge revision. The corresponding branch run also passed.
Ubuntu 24.04 used CPython 3.13.3, Node 24.16.0 and the pinned PostgreSQL 18.1
container manifest. The browser was Playwright's matching Chrome headless shell
156.0.8078.4, revision 1248.

The hosted job built the source distribution and wheel, passed all 33 API checks,
installed into a fresh environment outside the checkout, restarted the API and
passed all seven browser journeys. Its wheel SHA-256 is
`41a5349be55e1130d4028d0d7a22d8dea9021517b6ba38aaf6e2ce33718ffce9`.
The run's `installed-workflow-wheel` artifact contains that wheel and the browser
summary, with a 14-day retention period. A wheel from another build can have a
different archive hash. These recorded identities describe the actual artifacts.

Later documentation-only commits still run the same workflow. The [PR](https://github.com/T92T1914/shipment-exception-workspace/pull/1)
and [Actions page](https://github.com/T92T1914/shipment-exception-workspace/actions/workflows/verify.yml)
show the exact current revision and status. Successful Windows and Linux checks
qualify these two executed environments, without a broader compatibility claim.

The browser cases use the real installed API and PostgreSQL. For two recovery
cases, Playwright forwards a real mutation and then discards its response or
substitutes a JSON 500. The database transaction still executes. The tests then
check that retry sends the same key and body and creates no additional effect.
The navigation regression holds an actual response until another record is
selected. A second ordering holds the old list response and the new detail
response, checking that the stale continuation cannot invalidate the selected
record's request. These are controlled failure fixtures, not observations of a real
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
that interaction. The later six-case run and final seven-case run passed.

Independent review found and corrected a receipt CHECK that accepted a partial
NULL state, malformed CSRF handling, subprocess recovery gaps, stale browser
responses and loss of the retry key on a JSON 500. The final navigation ordering
also needed an early selection guard before advancing the request generation.
The PostgreSQL and browser regressions exercise the corrected boundaries.

The first hosted workflow attempts failed before application setup. The runner
passed a single-quoted health command through Docker's argument parser, which
treated its `-U` as a Docker flag. The service options now use a double-quoted
health command. This was a CI setup failure, not a failed API assertion.

After container setup was corrected, the Linux build and all 33 PostgreSQL API
checks passed. The installed-consumer runner then selected the base interpreter
by resolving the virtual environment executable's symlink. Preserving the
absolute venv path corrects that runner error. It was not a wheel import failure
inside the intended installed environment.

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

## Repeating the acceptance route

Build and install as described in the README. With a dedicated disposable test
database, run `python -m pytest tests` using the installed environment. Run
`python tools/check_package.py` from the checkout to inspect the actual wheel.

For a clean, separately seeded consumer database, set `SHIPMENT_DATABASE_URL`
and invoke `tools/installed_consumer.py --python PATH_TO_INSTALLED_PYTHON
--output PRIVATE_ACCEPTANCE_DIRECTORY --keep-server` with a Python environment
containing httpx. It creates private generated credentials and reports the
installed module path. Keep its output directory out of Git. It deliberately
preserves its password across setup retries, and expects fresh workflow state
for the one-event restart assertion.

Load `base_url` and `demo_password` from that directory's `consumer-state.json`
into `WORKSPACE_BASE_URL` and `WORKSPACE_DEMO_PASSWORD`. From `frontend`, run
`npm run test:e2e` with an installed Playwright headless Chromium. The qualified
local run explicitly selected its cached binary through
`WORKSPACE_BROWSER_EXECUTABLE`. The workflow installs its matching headless
browser instead. The seven browser cases are serial and share a clean seeded
consumer database. Stop only the owned app process and database afterward.
