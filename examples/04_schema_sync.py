"""
04_schema_sync.py — Explicit schema diffing and live apply.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import IRISAdapter, IRISModel, Registry, SchemaApplier, SchemaCompiler, SchemaPlanner, field


class Post(IRISModel):
    _iris_classname = "Demo.Post"

    Title: str = field(required=True, maxlen=500)
    Views: int = field(default=0)


def main() -> None:
    registry = Registry()
    registry.register(Post)

    adapter = IRISAdapter()
    compiler = SchemaCompiler(adapter)
    desired = registry.export_schema()
    before = compiler.catalog_from_iris(registry.classnames())
    plan = SchemaPlanner().diff(before, desired)

    print("Planned operations:")
    for op in plan.operations:
        print(" ", op.kind, op.classname, op.payload)

    if not plan.is_empty():
        SchemaApplier(adapter).apply(plan, allow_manual=True)
        after = compiler.catalog_from_iris(registry.classnames())
        print("Live classes after apply:", [item.name for item in after.classes])


if __name__ == "__main__":
    main()
