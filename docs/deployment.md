# Shipment v0.9.0 native Render candidate

Prepared October 26, 2026. This route is a deployment candidate pending an appropriate provider account, an actual cost decision and hosted acceptance. A prepared configuration, successful local run or published wheel does not establish a hosted application. Package publication, local installed acceptance and hosted acceptance have separate records.

## Selected shape

Use one native Python web service and one new dedicated Render PostgreSQL 18 database in the same region. Ohio is the proposed region, subject to the chosen account's availability. The installed wheel serves the built React frontend and API at the service's own HTTPS `onrender.com` origin. No Node build, Docker image, custom domain, public tunnel or local-PC exposure is needed for this route.

The source checkout supplies these two reviewed helpers and the unchanged dependency lock. The build installs the exact reviewed public v0.9.0 wheel instead of building the application from that checkout. Record the application commit, deployment-helper checkout commit and wheel digest separately when they differ.

Render supports selecting a released Python patch version through `PYTHON_VERSION`. Pin `3.13.3`, matching the application qualification. [Python selection](https://render.com/docs/python-version).

## Decision and quote still required

The proposed continuing demo uses paid web compute `0.5c-512mb` and PostgreSQL compute `0.1c-256mb`, with 1 GB initial database storage and storage autoscaling disabled. Use one service instance. Obtain the actual account quote before resource creation. Render's July 2026 guidance estimated about $13/month for small always-on application/database compute before bandwidth and storage changes. That is a dated estimate, not a price guarantee or a granted budget. [Official cost example](https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses), [current compute names](https://render.com/docs/compute-plans).

A free preview is a different finite choice: web sleep after 15 idle minutes, roughly one-minute wake, 750 workspace free hours monthly, and a 1 GB database expiring after 30 days. The upgrade grace period is another 14 days before deletion. It does not provide durable ongoing demo storage or free backups. Do not create keep-alive traffic to evade sleeping. [Free limits](https://render.com/docs/free).

The initial setup job is separately billed at its compute plan's per-second rate. Do not assume a free web service makes that job free. Confirm the job quote and account permissions too. [One-off job behavior and billing](https://render.com/docs/one-off-jobs).

Required scoped authority is permission to create this web service and this dedicated database in the selected workspace, set their service-scoped environment variables, run one initial setup job, deploy the selected commit, read status/logs and perform one restart acceptance check. Account creation, broad GitHub installation access, payment changes, paid resources or expanded permissions require the corresponding decision. Use an existing appropriate account if one is available. No unrelated services should be inspected or modified.

## Fill the exact inputs

`environment.example` lists the required values without real secrets. Before any provider build:

1. Publish and independently download the accepted `shipment_exception_workspace-0.9.0-py3-none-any.whl` from the repository's v0.9.0 GitHub Release. Record its final SHA256. Set `SHIPMENT_RELEASE_SHA256` to that digest, not to a guessed or earlier build's hash.
2. Set `SHIPMENT_SOURCE_REVISION` to the exact accepted application commit associated with those bytes. The build receipt also records Render's helper-checkout commit. A configured revision string is not independent proof of source provenance.
3. Use the service's actually assigned HTTPS origin for `SHIPMENT_PUBLIC_ORIGIN`, without a trailing slash or explicit default port. It must also match the HTTP health-check Host.
4. Set a separate deliberately public reviewer password of 12 through 256 characters. Public access is `visitor@northline.example`. Never publish the stock seed password or a database/account secret.
5. Put the database URL in the service's secret environment settings. Use the dedicated same-region internal endpoint and append `?sslmode=require`. Do not print, put in Git or attach this URL. Block external database connections for this route.

Render internal PostgreSQL TLS uses a self-signed certificate. `require` prevents plaintext fallback but does not establish certificate/hostname verification. Internal `verify-ca` and `verify-full` are unsupported. This is a declared provider trust boundary, not a general encrypted-database compatibility claim. [Connection documentation](https://render.com/docs/postgresql-creating-connecting).

The helper checks the lock's LF-normalized SHA256, `f56bdd4266247a765c201073c2dd94f8356550429c4fac563b3c747dd6643434`. It creates a named `.shipment-runtime` environment without automatic pip bootstrap, then runs `ensurepip` under a deliberately filtered child environment. Database credentials and the published password are excluded from bootstrap and installation children. It installs the pinned dependencies from PyPI as wheels only and installs the verified application wheel with `--no-deps`. It does not change the provider's global Python environment or contact PostgreSQL.

## Service configuration

Review the helpers under `deploy/` and configure these exact commands in the selected deployment checkout. Final application revision and wheel SHA256 remain required operator-filled inputs. No candidate commit is silently promoted to the release identity.

| Field | Candidate value |
| --- | --- |
| Runtime | Native Python |
| Build command | `python deploy/render_build.py` |
| Start command | `./.shipment-runtime/bin/python -I -m shipment_workspace.cli serve-demo` |
| Health check | `/api/ready` |
| Automatic deploys | Off |
| Replicas | One |
| Pre-deploy command | Empty |
| Initial-deploy hook | Empty |
| App persistent disk | None |
| PostgreSQL | Major version 18, same region, dedicated database |
| Database external IP access | Empty allowlist |
| Storage autoscaling | Disabled |

Select a specific reviewed helper commit for the manual deployment. Render's API/CLI commit selection does not itself always disable automatic deploys, so verify that setting explicitly. The normal start command must remain `serve-demo`, with no initialization chain. [Deployment lifecycle](https://render.com/docs/deploys).

The build fails closed if the named output paths already exist. It does not erase them. Inspect the previous attempt, then use a clean provider build after understanding the failure. A digest mismatch, missing release, dependency installation failure or import failure is not a usable runtime. Keep the failed attempt separate from a later successful build.

## Initialize before a healthy application start

The first application start is expected to refuse an uninitialized database. Preserve that as an expected setup prerequisite, not as a successful deployment or an application regression. First confirm the wheel/dependency build succeeded and its nonsecret build receipt identifies the intended bytes.

Create one explicit initial-setup job from that service's successful build using this start command:

```text
./.shipment-runtime/bin/python -I deploy/render_initial_setup.py
```

A one-off job uses its base service's most recent successful build artifact and configured environment snapshot. That permits setup from a successful build even when the uninitialized web process has not become healthy. Read back the actual job's selected build and status. The job is complete only when its recorded execution finishes successfully. [Build snapshot and job status](https://render.com/docs/one-off-jobs).

The setup helper first refuses an existing public schema object, public function or large object. For a verified new target with no competing writers it runs installed `init`, then installed `provision-demo`, with bounded subprocess timeouts. This admission is for a fresh dedicated demo target. It is not a restore qualification or a general database inventory tool.

If setup fails or its result is uncertain, retain the database and logs and inspect actual schema/data before any retry. `init` and provisioning are distinct committed steps. A failure after initialization can leave an initialized empty schema, and rerunning the whole helper then refuses it. Do not drop/reset the target or make startup repair it automatically. A deliberate retry of only `provision-demo` requires verified empty application state and the applicable owner decision.

After setup, deploy or restart the same reviewed application bytes with the normal start command. No permanent setup command should be enabled. A paid pre-deploy command is an alternative only if separately reviewed and manually removed after the one initial successful setup. It is not selected here. An after-first-successful-deploy hook cannot solve a startup prerequisite that prevents the first healthy deploy.

## Actual acceptance after deployment

Record the provider resource/deployment IDs privately and verify the actual public HTTPS origin, `/api/version` and `/api/ready`. Join that readback with the accepted wheel SHA256, build receipt and provider checkout/build identity. Do not treat a URL being assigned as proof that it serves this version.

Use the actual public visitor credential for browser and direct API checks. Verify queue search, open/resolved filters, detail/history, reload, keyboard navigation, sign-out and session recovery at desktop and narrow sizes. Include light/dark and enlarged text. `NL-1086` contains provisioned resolved history and `NL-1091` an assigned open record. These initial fixtures do not prove an operator API journey.

Verify business create/assign/unassign/resolve and saved-receipt replay remain denied, guessed Harbor record references remain unavailable, CSRF/origin and Host checks hold, and no public password works for an operator. Keep deliberate error injection and database expiry fixtures confined to disposable staging. On the public instance, use harmless denied requests and normal visitor behavior within the owner-authorized acceptance scope.

Read cookie flags on the actual HTTPS response. Check that HTTP is redirected by the provider before application interaction, and slash/missing API paths do not downgrade to HTTP. The app ignores forwarded headers rather than trusting a client-supplied proxy identity.

Record the current synthetic business rows, exercise one provider restart, then verify the same rows/history and an unexpired visitor session still behave correctly. Startup must not create/reset data. Record observed PostgreSQL/Python versions. Managed PostgreSQL 18 is a new hosted application route and does not inherit native restore or cross-version qualification.

## Resource, retention and shutdown policy

The application uses one Uvicorn worker, eight concurrent requests and two application thread tokens. Public API admission is five requests/second with burst thirty per process. Sessions have a transactionally enforced cap of 128 live rows, with five-minute anonymous and thirty-minute authenticated lifetimes. Existing durable password admission is separate. These controls do not establish attack resistance, constant physical database size or a response-time guarantee.

Only fictional records and identities belong here. Business records are read-only to public visitors. Sessions and login-admission state still change. Do not invite employers to submit personal or real logistics data. Keep connection URLs, database passwords, provider tokens, cookies and raw logs out of public assets. Before creating resources, inspect the selected workspace's log retention, billing limits, egress allowance and database retention policies. Record their actual values without changing account-wide settings as a convenience.

Suspending the selected web service stops public access but does not by itself prove that database charges stop. Preserve the synthetic database and secrets until T explicitly chooses deletion or retention. Check the provider's actual billable-resource state. Never delete unrelated resources or assume an expired free database can be recovered.

Confirm the initial job has exited. If it is still running after a failure, cancel only that recorded job and read back its terminal status. Suspending or redeploying the base web service does not cancel a running one-off job. The helper's subprocess timeouts are not a substitute for that provider readback.

For a later redeploy, retain the existing database, use a separately accepted matching wheel digest and application revision, and repeat affected installed/hosted checks. Keep automatic deployment off and leave setup hooks empty. An app rollback does not undo database changes and must not be presented as a backup/restore procedure.

This candidate can support a concrete account/cost question after the owner has reviewed the code, frozen release identities and completed disposable staging. It is not evidence of a hosted demo.
