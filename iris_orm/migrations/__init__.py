"""
Schema-snapshot migration runner.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iris_orm.adapter import IRISAdapter
from iris_orm.schema import SchemaCatalog, SchemaCompiler, SchemaPlanner

from .migration import MigrationConnection
from .tracker import get_applied, init, mark_applied, mark_reverted
from .writer import next_revision, write_migration_file


@dataclass
class MigrationFile:
    path: Path
    revision: str
    down_revision: str | None
    description: str
    module: Any


def _load_migration_files(migrations_dir: Path) -> list[MigrationFile]:
    files: list[MigrationFile] = []
    for py_file in sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.py")):
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"_iris_migration_{py_file.stem}"] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        files.append(
            MigrationFile(
                path=py_file,
                revision=str(getattr(module, "revision", py_file.stem[:4])),
                down_revision=getattr(module, "down_revision", None),
                description=str(getattr(module, "description", py_file.stem[5:])),
                module=module,
            )
        )
    return files


def _build_chain(files: list[MigrationFile]) -> list[MigrationFile]:
    by_rev = {item.revision: item for item in files}
    roots = [item for item in files if item.down_revision is None]
    if not roots:
        return files
    chain: list[MigrationFile] = []
    current = roots[0]
    seen: set[str] = set()
    while current is not None and current.revision not in seen:
        chain.append(current)
        seen.add(current.revision)
        current = next((item for item in files if item.down_revision == current.revision), None)
    return chain


def _head_schema(files: list[MigrationFile]) -> SchemaCatalog:
    if not files:
        return SchemaCatalog()
    return SchemaCatalog.from_dict(dict(getattr(files[-1].module, "schema_after", {})))


class MigrationRunner:
    def __init__(self, migrations_dir: str | Path, *, adapter: IRISAdapter | None = None, registry: Any = None) -> None:
        self.migrations_dir = Path(migrations_dir)
        self.adapter = adapter or IRISAdapter()
        self.registry = registry

    def init(self) -> None:
        init(self.adapter)

    def generate(self, description: str, *, registry: Any | None = None) -> Path:
        active_registry = registry or self.registry
        if active_registry is None:
            raise ValueError("Migration generation requires a Registry")
        files = _build_chain(_load_migration_files(self.migrations_dir))
        before = _head_schema(files)
        after = SchemaCompiler().catalog_from_registry(active_registry)
        revision = next_revision([item.revision for item in files])
        down_revision = files[-1].revision if files else None
        return write_migration_file(
            self.migrations_dir,
            revision=revision,
            down_revision=down_revision,
            description=description,
            before=before,
            after=after,
        )

    def upgrade(self, target: str | None = None) -> None:
        chain = _build_chain(_load_migration_files(self.migrations_dir))
        applied = set(get_applied(self.adapter))
        pending = [item for item in chain if item.revision not in applied]
        if target is not None:
            pending = _up_to(pending, target)
        conn = MigrationConnection(self.adapter)
        for migration in pending:
            upgrade_fn = getattr(migration.module, "upgrade", None)
            if upgrade_fn is not None:
                upgrade_fn(conn)
            mark_applied(self.adapter, migration.revision, migration.description)

    def downgrade(self, target: str | None = None) -> None:
        chain = _build_chain(_load_migration_files(self.migrations_dir))
        applied = get_applied(self.adapter)
        if not applied:
            return
        conn = MigrationConnection(self.adapter)
        for migration in reversed(chain):
            if migration.revision not in applied:
                continue
            if target is not None and migration.revision <= target:
                break
            downgrade_fn = getattr(migration.module, "downgrade", None)
            if downgrade_fn is not None:
                downgrade_fn(conn)
            mark_reverted(self.adapter, migration.revision)

    def history(self) -> list[tuple[str, str, str]]:
        chain = _build_chain(_load_migration_files(self.migrations_dir))
        applied = set(get_applied(self.adapter))
        return [
            (
                migration.revision,
                migration.description,
                "applied" if migration.revision in applied else "pending",
            )
            for migration in chain
        ]

    def current(self) -> str | None:
        applied = get_applied(self.adapter)
        return applied[-1] if applied else None


def _up_to(migrations: list[MigrationFile], target: str) -> list[MigrationFile]:
    result: list[MigrationFile] = []
    for migration in migrations:
        result.append(migration)
        if migration.revision == target:
            break
    return result
