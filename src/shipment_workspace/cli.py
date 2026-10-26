"""Run the built application against an explicitly configured PostgreSQL database."""

import argparse
import os

import uvicorn

from .app import create_app
from .config import Settings
from .db import initialize, migrate, provision_demo, seed


def main():
    parser = argparse.ArgumentParser(description="Synthetic shipment exception workspace")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create schema version 4 in an empty project database")
    commands.add_parser("migrate", help="Upgrade a stopped version 1, 2 or 3 database to version 4 atomically")
    commands.add_parser("seed", help="Insert two synthetic organizations without resetting existing records")
    provision = commands.add_parser("provision-demo", help="Provision a separate published reviewer in empty synthetic state")
    provision.add_argument("--origin", default=os.environ.get("SHIPMENT_PUBLIC_ORIGIN"))
    serve = commands.add_parser("serve", help="Serve the installed React build and API on loopback")
    serve.add_argument("--port", type=int, default=8765)
    demo = commands.add_parser("serve-demo", help="Serve the bounded HTTPS-proxied synthetic reviewer deployment")
    demo.add_argument("--host", choices=("0.0.0.0", "127.0.0.1", "::", "::1"), default="0.0.0.0")
    demo.add_argument("--port", type=int, default=os.environ.get("PORT", "10000"))
    demo.add_argument("--origin", default=os.environ.get("SHIPMENT_PUBLIC_ORIGIN"))
    demo.add_argument("--revision", default=os.environ.get("SHIPMENT_SOURCE_REVISION"))
    args = parser.parse_args()
    database_url = os.environ.get("SHIPMENT_DATABASE_URL")
    if not database_url:
        parser.error("Set SHIPMENT_DATABASE_URL to a dedicated PostgreSQL database")
    settings = None
    if args.command in ("provision-demo", "serve-demo"):
        if not args.origin:
            parser.error("Set SHIPMENT_PUBLIC_ORIGIN to the exact public HTTPS origin")
        if args.command == "serve-demo" and not args.revision:
            parser.error("Set SHIPMENT_SOURCE_REVISION to the complete deployed Git commit ID")
        try:
            settings = Settings(database_url, origin=args.origin, secure_cookie=True, public_demo=True,
                                demo_password=os.environ.get("SHIPMENT_PUBLIC_DEMO_PASSWORD"),
                                deployment_revision=getattr(args, "revision", None))
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "init":
        initialize(database_url)
        print("Schema version 4 initialized.")
    elif args.command == "migrate":
        migrate(database_url)
        print("Schema version 4 ready. Existing records, sessions and receipts were preserved.")
    elif args.command == "seed":
        password = os.environ.get("SHIPMENT_DEMO_PASSWORD", "")
        if len(password) < 12:
            parser.error("Set SHIPMENT_DEMO_PASSWORD to at least 12 characters")
        seed(database_url, password)
        print("Synthetic organizations and accounts seeded. Existing workflow state was preserved.")
    elif args.command == "provision-demo":
        provision_demo(settings.database_url, settings.demo_password)
        print("Separate public synthetic reviewer provisioned. Other account credentials remain private.")
    else:
        if not 1024 <= args.port <= 65535:
            parser.error("Use an unprivileged port from 1024 through 65535")
        from pathlib import Path
        if not Path(__file__).with_name("static").joinpath("index.html").is_file():
            parser.error("Frontend build missing. Build the React app before packaging the wheel")
        if args.command == "serve-demo":
            # The provider terminates HTTPS. Incoming forwarded headers do not
            # choose the origin, cookie policy, identity or request-budget key.
            uvicorn.run(create_app(settings), host=args.host, port=args.port,
                        proxy_headers=False, forwarded_allow_ips="", workers=1,
                        limit_concurrency=8, timeout_keep_alive=5,
                        access_log=False, log_level="warning")
        else:
            settings = Settings(database_url, origin=f"http://127.0.0.1:{args.port}")
            uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port,
                        workers=1, limit_concurrency=8, timeout_keep_alive=5,
                        access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
