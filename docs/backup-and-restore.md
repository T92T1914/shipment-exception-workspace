# Preserve a local workspace through backup and restore

This route saves a trusted schema-4 Shipment workspace as a PostgreSQL custom
archive and restores it into a separately named empty database. The original
workspace stays intact. The qualified combination is Windows x64, PostgreSQL
18.1 client/server, CPython 3.13.3 and the pinned ordinary application wheel.
See [executed verification](VERIFICATION.md) for the exact revision and outcomes.

This is a bounded local application handoff. It does not qualify power loss,
storage corruption, cross-version restoration, failover, high availability,
disaster recovery or production backup readiness. A process restart is a
different test. Linux application CI does not by itself qualify this Windows
native dump/restore route.

## Before making the archive

Use a private directory outside Git for connection records, passwords, dump
archives and command logs. The archive contains private records, password
hashes, sessions and retry receipts. Restore only an archive you made from a
trusted source. A digest or a successful archive listing does not make an
arbitrary third-party dump safe: restoring can execute code chosen by the source
superuser. [PostgreSQL's warning](https://www.postgresql.org/docs/18/app-pgdump.html#APP-PGDUMP-DESCRIPTION)
applies to partial restores too.

The route uses the same owned loopback cluster and existing matching database
owner. It admits the current nine application tables, their constraints,
indexes and identity sequence, with no extra schemas, functions, application
extensions or custom scalar types. The qualification fixture uses the helper's
database owner with permission to create disposable databases and read cluster
identity. It creates no role or tablespace. A single-database dump does not save
cluster-wide roles or tablespaces; those must already exist under a separately
qualified cluster-recovery procedure. See [SQL dump guidance](https://www.postgresql.org/docs/18/backup-dump.html).

The qualification uses the new cluster's bootstrap superuser. Database ownership
alone does not grant access to `pg_control_system()`. Delegating production
database privileges is outside this route; do not grant privileges merely to
make this fixture pass.

The fixture uses default per-database settings. This no-create recipe does not
restore database-level configuration, cluster configuration, roles or
tablespaces. If an existing workspace depends on other settings, stop and
qualify those separately rather than assuming the record comparison covers them.

Stop the source application and any fixture writers you own before taking its
comparison fingerprint. Keep them stopped through the dump and post-dump
fingerprint, while leaving PostgreSQL running. This makes the controlled
comparison meaningful. PostgreSQL can make a consistent dump with concurrent
writers; the quiet-source rule here is not a PostgreSQL requirement or a
general concurrency lock.

Do not use a retained accepted database as an acceptance fixture. The executable
qualification below requires a fresh source and target. A real existing
workspace instead uses the guarded native recipe, without initialization or
seeding.

## Guarded native recipe

Run from this source checkout with the ordinary installed environment's Python.
The tools import Psycopg from that environment; they do not import the app from
`src`. Keep `PYTHONPATH` unset. Replace every private placeholder explicitly.

```powershell
$consumerPython = 'C:\private\shipment-consumer\Scripts\python.exe'
$env:SHIPMENT_RESTORE_SOURCE_URL = (Get-Content 'C:\private\source-connection.txt' -Raw).Trim()
$env:SHIPMENT_RESTORE_PORT = '55432'
$env:SHIPMENT_RESTORE_TARGET = 'shipment_restored'
$env:SHIPMENT_RESTORE_DIRECTORY = 'C:\private\shipment-backup-new'
$env:SHIPMENT_RESTORE_PG_BIN = 'C:\Program Files\PostgreSQL\18\bin'
& (Join-Path $env:SHIPMENT_RESTORE_PG_BIN 'pg_dump.exe') --version
& (Join-Path $env:SHIPMENT_RESTORE_PG_BIN 'pg_restore.exe') --version
```

Require both tools to report PostgreSQL 18.1 before proceeding. This guide does
not upgrade a client or server.

The source connection must explicitly contain `host=127.0.0.1`, that port,
database, user and password, as either a PostgreSQL URL or keyword string. The
helper rejects other connection options and inherited endpoint/password
defaults. Never print the connection value. The target name below is a new,
simple database identifier owned by that same role. An existing name causes
creation to fail; do not drop it to make the recipe pass.

```powershell
@'
import json, os
from pathlib import Path
from psycopg import sql
from psycopg.conninfo import make_conninfo
from tools.local_restore import parameters, connect, identity, guard_restore, fingerprint, native, restore

port = int(os.environ['SHIPMENT_RESTORE_PORT'])
source = parameters(os.environ['SHIPMENT_RESTORE_SOURCE_URL'], port)
identity(source)
target = parameters(make_conninfo(**{**source, 'dbname': os.environ['SHIPMENT_RESTORE_TARGET']}), port)
if source['dbname'] == target['dbname']:
    raise ValueError('Choose a separate target database')
with connect(source) as conn:
    conn.execute(sql.SQL('CREATE DATABASE {} WITH TEMPLATE template0 OWNER {}').format(
        sql.Identifier(target['dbname']), sql.Identifier(source['user'])))
identities = guard_restore(source, target)
print(json.dumps(identities))  # Effective endpoints and owner, without passwords.
output = Path(os.environ['SHIPMENT_RESTORE_DIRECTORY'])
output.mkdir(parents=True, exist_ok=False)
pg_bin = Path(os.environ['SHIPMENT_RESTORE_PG_BIN'])
archive = output / 'trusted-workspace.dump'
before = fingerprint(source)
if native(pg_bin, 'pg_dump', source, ['--format=custom', '--file', archive], output / 'dump.log'):
    raise RuntimeError('Dump failed. Preserve the log and partial archive; do not restore it.')
assert fingerprint(source) == before
code, _ = restore(pg_bin, source, target, archive, output / 'restore.log')
if code:
    raise RuntimeError('Restore failed. Retain this target and inspect the log; do not automatically clean or retry.')
assert fingerprint(target) == before
assert fingerprint(source) == before
(output / 'logical-readback.json').write_text(json.dumps(before, indent=2, default=str))
print('Complete logical readback matched before application startup.')
'@ | & $consumerPython -
if ($LASTEXITCODE -ne 0) { throw 'Stop here and inspect the private result.' }
```

The native commands use explicit host, port, user and database arguments, an
isolated child connection environment and no password prompt. The actual
database OIDs and cluster identity are checked, not just two different strings.
An equal source/target, unexpected endpoint or target with a table, sequence,
index, function, type, large object, extra schema or default privilege is refused before
`pg_restore` runs.

The normal restore reads the complete archive with `--single-transaction`.
PostgreSQL documents that this implies exit on error and cannot be combined
with parallel restore jobs. This route uses neither `--clean` nor archive-driven
`--create`. Those options can drop objects or select the archived database name.
See [PostgreSQL 18 pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html).

## Inspect the restored application

Point a fresh ordinary installed environment at the target connection. Do not
run `init`, `migrate`, `seed`, or the original fresh-fixture installed consumer
over it. The logical comparison must already have passed before application
startup or session requests. Start only `shipment-workspace serve`, then sign
in with the existing synthetic account credentials and inspect current records
and saved history. The target is a separate database with a different identity,
not an identical physical database directory.

Restored session rows retain their actual expiry, CSRF and current-access rules.
A saved session may already be expired. Fresh sign-in is an explicit action;
this guide does not extend expiry or silently authenticate you. Login-admission
timestamps also retain their values, while the current clock determines whether
a saved window remains active.

A database archive does not restore a browser's lost in-memory retry key/body.
The qualification replays one declared synthetic receipt under the same actor,
key and body with current authorization. It does not supply a receipt browser,
cross-device recovery or automatic replay of uncertain business writes.

## Reproduce the qualification with disposable state

Create a new cluster with `tools/local_postgres.py` and two separately named
empty databases from `template0`, owned by its existing role. Load their private
URLs into `SHIPMENT_RESTORE_SOURCE_URL` and `SHIPMENT_RESTORE_TARGET_URL`.
Use a new output directory and the actual port from that cluster's record:

```powershell
& $consumerPython tools/installed_restore_consumer.py --python $consumerPython `
  --pg-bin 'C:\Program Files\PostgreSQL\18\bin' --expected-port 55432 `
  --output 'C:\private\restore-acceptance-new'
```

Only the fresh source is initialized and seeded. It receives actual API
creation, assignment and resolution history. A declared expired session and a
real unused sequence value test expiry and sequence-gap preservation. Source
writers stop before the comparison. The restored consumer polls a static route
for readiness and never initializes or edits admission fixtures on the target.

Readback covers all ordered row values in the nine application tables,
including roles, password/session hashes, expiry, receipts and admission state,
plus columns/defaults, constraints, indexes, object ownership and actual identity
sequence configuration, `last_value` and `is_called`. Counts alone are not the
acceptance criterion. Planner statistics, database OIDs and physical file bytes
are outside that logical comparison.

The run also creates distinct disposable targets for missing/truncated archives,
nonempty-object guard cases and a deliberately incomplete TOC restore. That
last control omits one table definition while retaining its data. The native
command fails after earlier DDL/data work, and actual target readback checks the
single-transaction rollback. The normal restore uses the full archive.

Preserve each failed archive, log and target. A nonzero exit is failure even if
some earlier output looked successful. Do not run `--clean`, reseed, silently
repair or retry into the same target. Diagnose the cause, then explicitly choose
another new empty target for a new attempt. Stop only this run's owned app and
cluster when finished, keeping their data and private connection record.
