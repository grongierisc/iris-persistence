"""
Migration connection facade for schema-snapshot migrations.
"""
from __future__ import annotations

from typing import Any

from iris_orm.adapter import IRISAdapter
from iris_orm.schema import SchemaApplier, SchemaPlan


class MigrationConnection:
    """Facade exposed to migration upgrade()/downgrade() functions."""

    def __init__(self, adapter: IRISAdapter | Any) -> None:
        self.adapter = adapter if isinstance(adapter, IRISAdapter) else adapter
        self.applier = SchemaApplier(self.adapter)

    def apply_plan(self, plan: SchemaPlan, *, allow_manual: bool = False) -> None:
        self.applier.apply(plan, allow_manual=allow_manual)
