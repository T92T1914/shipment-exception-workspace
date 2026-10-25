"""Guard the bounded same-owner, same-cluster PostgreSQL 18.1 local route.

This is source-tree tooling, not an application endpoint or backup service.
Archives and generated connection records contain private application state.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

TABLES = {"schema_version", "organizations", "users", "sessions", "shipment_exceptions",
          "exception_events", "mutation_requests", "login_global", "login_identifiers"}
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class Refused(ValueError):
    """A declared local endpoint or empty-target precondition was not met."""


def parameters(url, expected_port):
    if not 1024 <= expected_port <= 65535:
        raise Refused("Choose an explicit unprivileged TCP port")
    try:
        result = conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        raise Refused("Invalid connection record; values are not echoed") from None
    required = {"host", "port", "dbname", "user", "password"}
    if set(result) != required or result["host"] != "127.0.0.1" or str(result["port"]) != str(expected_port):
        raise Refused("Require explicit loopback host, expected port, database, owner and password")
    if any(not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", result[key]) for key in ("dbname", "user")):
        raise Refused("This bounded route requires simple explicit database and role names")
    if not result["password"]:
        raise Refused("No inherited password or interactive prompt is admitted")
    return result


def connect(params):
    # Explicit core parameters and hostaddr prevent environment/service defaults
    # from redirecting this connection before the actual endpoint is inspected.
    return psycopg.connect(**params, hostaddr=params["host"], connect_timeout=5,
                           options="-c timezone=UTC -c search_path=public,pg_catalog", autocommit=True)


def identity(params):
    with connect(params) as conn:
        row = conn.execute("""SELECT inet_server_addr()::text, inet_server_port(),
            current_database(), current_user, pg_get_userbyid(datdba), oid
            FROM pg_database WHERE datname=current_database()""").fetchone()
        cluster = conn.execute("SELECT system_identifier::text FROM pg_control_system()").fetchone()[0]
        if row[:4] != (params["host"], int(params["port"]), params["dbname"], params["user"]):
            raise Refused("Effective endpoint differs from the explicit record")
        if row[3] != row[4] or conn.info.server_version != 180001:
            raise Refused("Require database ownership and the qualified PostgreSQL 18.1 server")
        return dict(host=row[0], port=row[1], database=row[2], user=row[3], owner=row[4],
                    database_oid=row[5], cluster=cluster, server_version=conn.info.server_version)


def empty_database(params):
    with connect(params) as conn:
        namespaces = conn.execute("""SELECT nspname FROM pg_namespace
            WHERE nspname !~ '^pg_' AND nspname NOT IN ('information_schema','public')""").fetchall()
        objects = conn.execute("""SELECT
            (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'),
            (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'),
            (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'),
            (SELECT count(*) FROM pg_depend WHERE refclassid='pg_namespace'::regclass AND refobjid='public'::regnamespace),
            (SELECT count(*) FROM pg_extension WHERE extname<>'plpgsql'),
            (SELECT count(*) FROM pg_default_acl)""").fetchone()
        if namespaces or any(objects):
            raise Refused("Target must be a separate pristine empty database, including types/functions/schemas")


def guard_restore(source, target):
    left, right = identity(source), identity(target)
    if (left["host"], left["port"], left["cluster"], left["database_oid"]) == (
            right["host"], right["port"], right["cluster"], right["database_oid"]):
        raise Refused("Source and target resolve to the same database")
    if left["cluster"] != right["cluster"] or left["user"] != right["user"]:
        raise Refused("This route requires the same cluster and existing matching owner")
    empty_database(target)
    return {"source": left, "target": right}


def fingerprint(params, allow_empty=False):
    """Hash complete ordered values, plus portable schema/sequence metadata.

    Row contents, password hashes and session secrets are never returned.
    Database OIDs, physical files and planner statistics are intentionally absent.
    """
    with connect(params) as conn:
        names = [row[0] for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        if set(names) != TABLES and not (allow_empty and not names):
            raise Refused("Fingerprint requires the exact schema-4 application table set or an empty target")
        if names:
            if conn.execute("SELECT singleton,version FROM schema_version").fetchall() != [(True, 4)]:
                raise Refused("Only the current schema 4 route is qualified")
            extras = conn.execute("""SELECT
                (SELECT count(*) FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema')),
                (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'),
                (SELECT count(*) FROM pg_extension WHERE extname<>'plpgsql'),
                (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'
                    AND (t.typtype IN ('d','e','r','m') OR (t.typtype='b' AND t.typcategory<>'A'))),
                (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
                    AND c.relkind NOT IN ('r','i','S')),
                (SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='public' AND NOT t.tgisinternal),
                (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
                    AND (c.relrowsecurity OR c.relforcerowsecurity)),
                (SELECT count(*) FROM pg_largeobject_metadata),
                (SELECT count(*) FROM pg_depend WHERE refclassid='pg_namespace'::regclass AND refobjid='public'::regnamespace
                    AND classid NOT IN ('pg_class'::regclass,'pg_type'::regclass,'pg_constraint'::regclass,'pg_attrdef'::regclass))""").fetchone()
            if any(extras):
                raise Refused("This application route admits no extra schemas, functions, extensions or scalar types")
        tables = {}
        for name in names:
            rows = conn.execute(sql.SQL("SELECT row_to_json(t)::text FROM {} t").format(sql.Identifier("public", name))).fetchall()
            canonical = sorted(json.dumps(json.loads(row[0]), sort_keys=True, separators=(",", ":")) for row in rows)
            tables[name] = {"count": len(rows), "sha256": sha256("\n".join(canonical).encode()).hexdigest()}
        queries = {
            "columns": """SELECT c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),
                a.attnotnull,a.attidentity,pg_get_expr(d.adbin,d.adrelid)
                FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
                WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1,2""",
            "constraints": """SELECT c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid),k.convalidated
                FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' ORDER BY 1,2""",
            "indexes": "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2",
            "owners_acl": """SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner),c.relacl::text
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY 1,2""",
            "schemas": """SELECT nspname,pg_get_userbyid(nspowner),nspacl::text FROM pg_namespace
                WHERE nspname !~ '^pg_' AND nspname<>'information_schema' ORDER BY 1""",
            "extensions": "SELECT extname,extversion,pg_get_userbyid(extowner) FROM pg_extension ORDER BY 1",
            "triggers": """SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2""",
            "sequence_configuration": """SELECT sequencename,sequenceowner,data_type,start_value,min_value,max_value,
                increment_by,cycle,cache_size FROM pg_sequences WHERE schemaname='public' ORDER BY 1""",
            "sequence_ownership": """SELECT s.relname,t.relname,a.attname,d.deptype FROM pg_class s
                JOIN pg_namespace n ON n.oid=s.relnamespace JOIN pg_depend d ON d.objid=s.oid AND d.classid='pg_class'::regclass
                JOIN pg_class t ON t.oid=d.refobjid JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
                WHERE n.nspname='public' AND s.relkind='S' AND d.deptype IN ('a','i') ORDER BY 1,2,3""",
        }
        metadata = {name: conn.execute(query).fetchall() for name, query in queries.items()}
        sequences = {}
        for (name,) in conn.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY 1"):
            sequences[name] = conn.execute(sql.SQL("SELECT last_value,is_called FROM {}").format(sql.Identifier("public", name))).fetchone()
        result = {"tables": tables, "metadata": metadata, "sequences": sequences}
        result["sha256"] = sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
        return result


def native(pg_bin, name, params, arguments, log):
    executable = Path(pg_bin) / (name + (".exe" if os.name == "nt" else ""))
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(PGPASSWORD=params["password"], PGCONNECT_TIMEOUT="5")
    argv = [str(executable), "--no-password", "--host", params["host"], "--port", params["port"],
            "--username", params["user"], "--dbname", params["dbname"], *map(str, arguments)]
    with Path(log).open("xb") as output:
        result = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                creationflags=FLAGS, timeout=60)
    return result.returncode


def restore(pg_bin, source, target, archive, log, *, broken_list=None):
    identities = guard_restore(source, target)
    arguments = ["--single-transaction", "--verbose"]
    if broken_list is not None:
        arguments += ["--use-list", broken_list]
    code = native(pg_bin, "pg_restore", target, [*arguments, archive], log)
    return code, identities
