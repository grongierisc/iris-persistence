from __future__ import annotations

from pathlib import Path

from iris_orm import Binder, IRISAdapter, Registry, SchemaApplier, SchemaCatalog, SchemaCompiler, SchemaPlanner, Session
from iris_orm.lockfile import build_lockfile, lockfile_path_for_module, write_lockfile


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


def write_model_lockfile(model_class: type, registry: Registry, *, source_kind: str = "declared") -> Path:
    schema_class = registry.export_schema().get_class(model_class._iris_classname)  # type: ignore[attr-defined]
    if schema_class is None:
        raise LookupError(f"No schema found for {model_class._iris_classname!r}")  # type: ignore[attr-defined]
    module_path = Path(model_class.__module__.replace(".", "/"))
    try:
        import inspect

        module_file = Path(inspect.getfile(model_class)).resolve()
    except (OSError, TypeError):
        module_file = module_path
    lockfile = build_lockfile(
        SchemaCatalog(classes=(schema_class,)),
        source={"kind": source_kind, "origin": str(module_file)},
    )
    return write_lockfile(lockfile_path_for_module(module_file), lockfile)
