"""
CLI for iris_orm migrations.

Usage
-----
    python -m iris_orm.migrations init
    python -m iris_orm.migrations generate "add views field" [--models module.path]
    python -m iris_orm.migrations upgrade [revision]
    python -m iris_orm.migrations downgrade <revision>
    python -m iris_orm.migrations history
    python -m iris_orm.migrations current
"""
from __future__ import annotations

import argparse
import importlib
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m iris_orm.migrations",
        description="iris_orm migration management",
    )
    parser.add_argument(
        "--dir",
        default="./migrations",
        metavar="PATH",
        help="Directory for migration files (default: ./migrations)",
    )
    parser.add_argument(
        "--module",
        default=None,
        metavar="MODULE",
        help="Python module to import before running (registers models)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="Create MigrationHistory class in IRIS")

    # generate
    gen = sub.add_parser("generate", help="Autogenerate a new migration file")
    gen.add_argument("description", help="Short description, e.g. 'add views field'")
    gen.add_argument(
        "--models",
        nargs="*",
        metavar="MODULE",
        default=None,
        help="Python modules whose models to diff (imports them to register)",
    )

    # upgrade
    up = sub.add_parser("upgrade", help="Apply pending migrations")
    up.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Revision to upgrade to (default: latest)",
    )

    # downgrade
    dn = sub.add_parser("downgrade", help="Roll back migrations")
    dn.add_argument("target", help="Revision to downgrade to (exclusive lower bound)")

    # history
    sub.add_parser("history", help="List all migrations and their status")

    # current
    sub.add_parser("current", help="Show current applied revision")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Import user module(s) to register models.
    if args.module:
        importlib.import_module(args.module)

    if args.command == "generate" and args.models:
        for mod_path in args.models:
            importlib.import_module(mod_path)

    from iris_orm.connection import IRISConnection  # noqa: PLC0415
    from iris_orm.migrations import MigrationRunner  # noqa: PLC0415

    conn = IRISConnection()
    runner = MigrationRunner(args.dir, conn=conn)

    if args.command == "init":
        runner.init()

    elif args.command == "generate":
        models: list | None = None
        if args.models:
            from iris_orm.metaclass import _MODEL_REGISTRY  # noqa: PLC0415
            models = list(_MODEL_REGISTRY.values())
        runner.generate(args.description, models=models)

    elif args.command == "upgrade":
        runner.upgrade(target=args.target)

    elif args.command == "downgrade":
        runner.downgrade(target=args.target)

    elif args.command == "history":
        runner.history()

    elif args.command == "current":
        runner.current()

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
