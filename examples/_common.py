from __future__ import annotations

from iris_orm import Binder, IRISAdapter, Registry, SchemaApplier, SchemaCompiler, SchemaPlanner, Session


def sync_registry(registry: Registry, *, adapter: IRISAdapter | None = None) -> IRISAdapter:
    adapter = adapter or IRISAdapter()
    compiler = SchemaCompiler(adapter)
    desired = registry.export_schema()
    live = compiler.catalog_from_iris(registry.classnames())
    plan = SchemaPlanner().diff(live, desired)
    if not plan.is_empty():
        SchemaApplier(adapter).apply(plan, allow_manual=True)
    return adapter


def bind_session(registry: Registry, *, adapter: IRISAdapter | None = None) -> tuple[IRISAdapter, Binder, Session]:
    adapter = adapter or IRISAdapter()
    binder = Binder(registry, adapter)
    binder.bind_all()
    return adapter, binder, Session(binder, adapter)
