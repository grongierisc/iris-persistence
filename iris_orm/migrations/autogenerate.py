"""
Migration autogeneration using canonical schema snapshots.
"""
from __future__ import annotations

from typing import Any

from iris_orm.schema import SchemaCatalog, SchemaPlan, SchemaPlanner


def load_head_schema(migration_files: list[Any]) -> SchemaCatalog:
    if not migration_files:
        return SchemaCatalog()
    module = migration_files[-1].module
    payload = dict(getattr(module, "schema_after", {}))
    return SchemaCatalog.from_dict(payload)


def diff_registry(registry: Any) -> tuple[SchemaCatalog, SchemaCatalog, SchemaPlan]:
    from iris_orm.schema import SchemaCompiler  # noqa: PLC0415

    compiler = SchemaCompiler()
    before = load_head_schema([])
    after = compiler.catalog_from_registry(registry)
    plan = SchemaPlanner().diff(before, after)
    return before, after, plan
