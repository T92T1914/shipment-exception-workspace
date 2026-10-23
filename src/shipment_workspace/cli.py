"""Run the built application against an explicitly configured PostgreSQL database."""

import argparse
import os

import uvicorn

from .app import create_app
from .config import Settings
from .db import initialize, migrate, seed


def main():
    parser = argparse.ArgumentParser(description="Synthetic shipment exception workspace")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create schema version 2 in an empty project database")
    commands.add_parser("migrate", help="Upgrade a stopped version 1 database to version 2 atomically")
    commands.add_parser("seed", help="Insert two synthetic organizations without resetting existing records")
    serve = commands.add_parser("serve", help="Serve the installed React build and API on loopback")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    database_url = os.environ.get("SHIPMENT_DATABASE_URL")
    if not database_url:
        parser.error("Set SHIPMENT_DATABASE_URL to a dedicated PostgreSQL database")
    if args.command == "init":
        initialize(database_url)
        print("Schema version 2 initialized.")
    elif args.command == "migrate":
        migrate(database_url)
        print("Schema version 2 ready. Existing records, sessions and receipts were preserved.")
    elif args.command == "seed":
        password = os.environ.get("SHIPMENT_DEMO_PASSWORD", "")
        if len(password) < 12:
            parser.error("Set SHIPMENT_DEMO_PASSWORD to at least 12 characters")
        seed(database_url, password)
        print("Synthetic organizations and accounts seeded. Existing workflow state was preserved.")
    else:
        if not 1024 <= args.port <= 65535:
            parser.error("Use an unprivileged port from 1024 through 65535")
        from pathlib import Path
        if not Path(__file__).with_name("static").joinpath("index.html").is_file():
            parser.error("Frontend build missing. Build the React app before packaging the wheel")
        settings = Settings(database_url, origin=f"http://127.0.0.1:{args.port}")
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port,
                    workers=1, limit_concurrency=8, timeout_keep_alive=5,
                    access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
