"""
Migration file writer — renders a list of Operations into a .py migration file.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .migration import Operation

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("_", text.lower()).strip("_")


def next_revision(existing_revisions: list[str]) -> str:
    """Return the next zero-padded 4-digit revision number."""
    if not existing_revisions:
        return "0001"
    last = max(int(r) for r in existing_revisions if r.isdigit())
    return f"{last + 1:04d}"


def render_migration(
    revision: str,
    down_revision: str | None,
    description: str,
    ops: list["Operation"],
) -> str:
    """
    Render a migration file as a Python source string.

    Parameters
    ----------
    revision:       e.g. "0002"
    down_revision:  e.g. "0001" or None for first migration
    description:    human-readable label, e.g. "add views field"
    ops:            list of Operation objects for upgrade()
    """
    upgrade_lines = [op.as_code() for op in ops] or ["    pass"]
    downgrade_lines = [op.revert_code() for op in reversed(ops)] or ["    pass"]

    down_rev_repr = repr(down_revision)
    slug = _slugify(description)

    lines = [
        '"""',
        f"{description}",
        '"""',
        "from __future__ import annotations",
        "",
        f'revision = {revision!r}',
        f'down_revision = {down_rev_repr}',
        f'description = {description!r}',
        "",
        "",
        "def upgrade(conn) -> None:",
    ]
    lines.extend(upgrade_lines)
    lines += [
        "",
        "",
        "def downgrade(conn) -> None:",
    ]
    lines.extend(downgrade_lines)
    lines.append("")

    return "\n".join(lines)


def write_migration_file(
    migrations_dir: str | Path,
    revision: str,
    down_revision: str | None,
    description: str,
    ops: list["Operation"],
) -> Path:
    """Write a migration .py file to *migrations_dir* and return the path."""
    migrations_dir = Path(migrations_dir)
    migrations_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(description)
    filename = f"{revision}_{slug}.py"
    path = migrations_dir / filename

    source = render_migration(revision, down_revision, description, ops)
    path.write_text(source, encoding="utf-8")
    return path
