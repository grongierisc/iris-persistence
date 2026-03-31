"""
06_migrations.py — Snapshot-based migration generation and upgrade.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import IRISAdapter, IRISModel, Registry, field
from iris_orm.migrations import MigrationRunner


class Article(IRISModel):
    _iris_classname = "Demo.Article"

    Title: str = field(required=True, maxlen=500)
    Views: int = field(default=0)


def main() -> None:
    migrations_dir = PROJECT_ROOT / "examples" / "migrations"
    registry = Registry()
    registry.register(Article)

    runner = MigrationRunner(migrations_dir, adapter=IRISAdapter(), registry=registry)
    runner.init()
    path = runner.generate("create article")
    print("Generated migration:", path)
    runner.upgrade()
    print("Current revision:", runner.current())


if __name__ == "__main__":
    main()
