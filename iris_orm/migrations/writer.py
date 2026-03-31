"""
Migration file writer for canonical schema snapshots.
"""
from __future__ import annotations

import re
from pprint import pformat
from pathlib import Path

from iris_orm.schema import SchemaCatalog

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("_", text.lower()).strip("_")


def next_revision(existing_revisions: list[str]) -> str:
    if not existing_revisions:
        return "0001"
    last = max(int(item) for item in existing_revisions if item.isdigit())
    return f"{last + 1:04d}"


def render_migration(
    revision: str,
    down_revision: str | None,
    description: str,
    before: SchemaCatalog,
    after: SchemaCatalog,
) -> str:
    before_json = pformat(before.to_dict(), sort_dicts=True, width=88)
    after_json = pformat(after.to_dict(), sort_dicts=True, width=88)
    lines = [
        '"""',
        description,
        '"""',
        "from __future__ import annotations",
        "",
        "from iris_orm.schema import SchemaApplier, SchemaCatalog, SchemaPlanner",
        "",
        f"revision = {revision!r}",
        f"down_revision = {down_revision!r}",
        f"description = {description!r}",
        "",
        "schema_before = " + before_json,
        "",
        "schema_after = " + after_json,
        "",
        "",
        "def upgrade(conn) -> None:",
        "    planner = SchemaPlanner()",
        "    before = SchemaCatalog.from_dict(schema_before)",
        "    after = SchemaCatalog.from_dict(schema_after)",
        "    plan = planner.diff(before, after)",
        "    SchemaApplier(conn.adapter).apply(plan)",
        "",
        "",
        "def downgrade(conn) -> None:",
        "    planner = SchemaPlanner()",
        "    before = SchemaCatalog.from_dict(schema_before)",
        "    after = SchemaCatalog.from_dict(schema_after)",
        "    plan = planner.diff(after, before)",
        "    SchemaApplier(conn.adapter).apply(plan, allow_manual=True)",
        "",
    ]
    return "\n".join(lines)


def write_migration_file(
    migrations_dir: str | Path,
    revision: str,
    down_revision: str | None,
    description: str,
    before: SchemaCatalog,
    after: SchemaCatalog,
) -> Path:
    output_dir = Path(migrations_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{revision}_{_slugify(description)}.py"
    path = output_dir / filename
    path.write_text(
        render_migration(revision, down_revision, description, before, after),
        encoding="utf-8",
    )
    return path
