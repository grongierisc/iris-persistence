"""
iris_orm migrations — Alembic-style versioned schema migrations for IRIS.

Usage
-----
    from iris_orm import IRISConnection
    from iris_orm.migrations import MigrationRunner

    conn = IRISConnection()
    runner = MigrationRunner("./migrations", conn=conn)

    runner.init()                            # create MigrationHistory in IRIS (once)
    runner.generate("create article table", models=[Article])
    runner.upgrade()                         # apply all pending
    runner.downgrade("0001")                 # roll back to revision 0001
    runner.history()                         # print applied / pending table
    runner.current()                         # print current head revision

CLI
---
    python -m iris_orm.migrations init
    python -m iris_orm.migrations generate "add views field" --models myapp.models
    python -m iris_orm.migrations upgrade
    python -m iris_orm.migrations upgrade 0003
    python -m iris_orm.migrations downgrade 0001
    python -m iris_orm.migrations history
    python -m iris_orm.migrations current
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .autogenerate import diff_models, load_state_from_migrations
from .migration import MigrationConnection, Operation
from .tracker import get_applied, init, mark_applied, mark_reverted
from .writer import next_revision, write_migration_file


# ---------------------------------------------------------------------------
# MigrationFile — represents one discovered .py file in migrations_dir
# ---------------------------------------------------------------------------

@dataclass
class MigrationFile:
    path: Path
    revision: str
    down_revision: Optional[str]
    description: str
    module: Any   # the loaded Python module


def _load_migration_files(migrations_dir: Path) -> list[MigrationFile]:
    """
    Discover, load, and sort all migration .py files in *migrations_dir*.
    Files must start with a 4-digit revision prefix (e.g. ``0001_``) and
    define ``revision`` and ``down_revision`` at module level.
    """
    files: list[MigrationFile] = []
    for py_file in sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.py")):
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"_iris_migration_{py_file.stem}"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        files.append(
            MigrationFile(
                path=py_file,
                revision=str(getattr(mod, "revision", py_file.stem[:4])),
                down_revision=getattr(mod, "down_revision", None),
                description=str(getattr(mod, "description", py_file.stem[5:])),
                module=mod,
            )
        )
    return files


def _build_chain(files: list[MigrationFile]) -> list[MigrationFile]:
    """
    Return migration files ordered by their linked-list chain
    (down_revision → revision) from the root to the head.
    """
    by_rev = {f.revision: f for f in files}
    # Find root(s): down_revision is None
    roots = [f for f in files if f.down_revision is None]
    if not roots:
        return files  # fallback: already sorted by filename

    chain: list[MigrationFile] = []
    current: Optional[MigrationFile] = roots[0]
    visited: set[str] = set()
    while current is not None and current.revision not in visited:
        chain.append(current)
        visited.add(current.revision)
        # Find the file whose down_revision points at current
        current = next(
            (f for f in files if f.down_revision == current.revision),
            None,
        )
    return chain


# ---------------------------------------------------------------------------
# MigrationRunner
# ---------------------------------------------------------------------------

class MigrationRunner:
    """
    Manages versioned schema migrations for one or more IRIS classes.

    Parameters
    ----------
    migrations_dir:
        Directory where migration .py files are stored (created by generate()).
    conn:
        An :class:`~iris_orm.connection.IRISConnection` instance.
        Defaults to an embedded connection if omitted.
    """

    def __init__(
        self,
        migrations_dir: str | Path,
        conn: Any = None,
    ) -> None:
        self.migrations_dir = Path(migrations_dir)
        if conn is None:
            from iris_orm.connection import IRISConnection  # noqa: PLC0415
            conn = IRISConnection()
        self._conn = conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init(self) -> None:
        """
        Create the ``iris_orm.MigrationHistory`` %Persistent class in IRIS.
        Safe to call multiple times (idempotent).
        """
        init(self._conn)
        print("Migration history table ready.")

    def generate(
        self,
        description: str,
        *,
        models: list[type] | None = None,
    ) -> Path:
        """
        Autogenerate a new migration file.

        Parameters
        ----------
        description:
            Short human-readable label, e.g. ``"add views field"``.
        models:
            List of declared IRISModel classes to diff.
            If omitted, all registered declared models are used.

        Returns
        -------
        Path
            The path of the newly written migration file.
        """
        if models is None:
            from iris_orm.metaclass import _MODEL_REGISTRY  # noqa: PLC0415
            models = [
                cls for cls in _MODEL_REGISTRY.values()
                if getattr(cls, "_iris_declared_model", False)
            ]

        existing = _load_migration_files(self.migrations_dir)
        chain = _build_chain(existing)

        applied_state = load_state_from_migrations(chain)
        ops = diff_models(models, applied_state, self._conn)

        existing_revisions = [f.revision for f in existing]
        revision = next_revision(existing_revisions)
        down_revision = chain[-1].revision if chain else None

        path = write_migration_file(
            self.migrations_dir,
            revision=revision,
            down_revision=down_revision,
            description=description,
            ops=ops,
        )
        print(f"Generated: {path}  ({len(ops)} operation(s))")
        return path

    def upgrade(self, target: str | None = None) -> None:
        """
        Apply pending migrations up to (and including) *target* revision.
        If *target* is None, apply all pending migrations.
        """
        chain = _build_chain(_load_migration_files(self.migrations_dir))
        applied = set(get_applied(self._conn))

        pending = [f for f in chain if f.revision not in applied]
        if target is not None:
            pending = _up_to(pending, target)

        if not pending:
            print("Already up to date.")
            return

        mc = MigrationConnection(self._conn)
        for mf in pending:
            print(f"Applying {mf.revision}: {mf.description} …", end=" ")
            upgrade_fn = getattr(mf.module, "upgrade", None)
            if upgrade_fn:
                upgrade_fn(mc)
            mark_applied(self._conn, mf.revision, mf.description)
            print("done")

    def downgrade(self, target: str) -> None:
        """
        Roll back applied migrations down to (but not including) *target*.
        I.e., after this call, *target* is the current head.
        """
        chain = _build_chain(_load_migration_files(self.migrations_dir))
        applied = set(get_applied(self._conn))

        applied_chain = [f for f in chain if f.revision in applied]
        to_revert = _after(applied_chain, target)

        if not to_revert:
            print(f"Nothing to downgrade (already at or below {target!r}).")
            return

        mc = MigrationConnection(self._conn)
        for mf in reversed(to_revert):
            print(f"Reverting {mf.revision}: {mf.description} …", end=" ")
            downgrade_fn = getattr(mf.module, "downgrade", None)
            if downgrade_fn:
                downgrade_fn(mc)
            mark_reverted(self._conn, mf.revision)
            print("done")

    def history(self) -> None:
        """Print a table of all migrations with their applied status."""
        chain = _build_chain(_load_migration_files(self.migrations_dir))
        applied = set(get_applied(self._conn))

        if not chain:
            print("No migrations found.")
            return

        print(f"{'Rev':<6}  {'Status':<9}  Description")
        print("-" * 60)
        for mf in chain:
            status = "applied" if mf.revision in applied else "pending"
            mark = "✓" if mf.revision in applied else " "
            print(f"{mark} {mf.revision:<6}  {status:<9}  {mf.description}")

    def current(self) -> str | None:
        """Return (and print) the latest applied revision, or None."""
        applied = get_applied(self._conn)
        if not applied:
            print("No migrations applied yet.")
            return None
        rev = applied[-1]
        print(f"Current revision: {rev}")
        return rev


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _up_to(files: list[MigrationFile], target: str) -> list[MigrationFile]:
    """Return files up to and including *target*."""
    result = []
    for f in files:
        result.append(f)
        if f.revision == target:
            break
    return result


def _after(files: list[MigrationFile], target: str) -> list[MigrationFile]:
    """Return files strictly after *target* (exclusive)."""
    result = []
    found = False
    for f in files:
        if found:
            result.append(f)
        if f.revision == target:
            found = True
    if not found:
        # target not in applied list — revert everything
        return files
    return result
