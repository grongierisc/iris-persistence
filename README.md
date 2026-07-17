# iris_persistence

Python models, object persistence, queries, and managed schema for InterSystems IRIS.
Python owns declared class members; the IRIS compiler owns generated storage and runtime methods.

## Install the AI agent skills

Use the portable skills installer to discover and install the model, scaffold, and migration
skills for Codex, Claude Code, Cursor, or another supported agent—no repository clone required:

```bash
npx skills add grongierisc/iris-persistence
```

Install every skill globally for Codex without prompts:

```bash
npx skills add grongierisc/iris-persistence --skill '*' --agent codex --global --yes
```

See the [AI agent skills guide](docs/agent_skills.md) for individual skills, Claude Code,
project-scoped installation, updates, removal, and the native Codex installer.

## 1. Define a model and configure the runtime

```python
from iris_persistence import Field, Index, Model


class Person(Model, persistent=True):
    Name: str = Field(required=True, max_length=120)
    Age: int | None = None

    class Meta:
        classname = "App.Person"
        mode = "managed"
        indexes = [Index("NameIdx", properties="Name")]
```

Embedded Python discovers IRIS automatically. Native Python supplies its connection through the
same normalized runtime boundary:

```python
from iris_persistence import RuntimeConfig, configure_runtime

configure_runtime(RuntimeConfig(native_connection=connection))
```

Application and domain code uses the same model API in both environments. It does not inspect the
selected backend or wrapper state.

## 2. Manage schema

Preview and apply the Python-owned schema through the model:

```python
diff = Person.diff_schema()
Person.sync_schema()

# Equivalent preview form
assert Person.sync_schema(dry_run=True) == Person.diff_schema()
```

`managed` adds, updates, and removes Python-owned properties, indexes, and parameters without
deleting the class. IRIS generates and evolves `Storage Default` when compiling the class.
`observe` never changes IRIS and is intended for existing or scaffolded classes.

For creation-time physical locations, managed models can declare `StorageTuning`:

```python
from iris_persistence import StorageTuning


class Meta:
    mode = "managed"
    storage_tuning = StorageTuning(
        data_location="^App.PersonD",
        id_location="^App.PersonD",
        index_location="^App.PersonI",
    )
```

Existing populated storage is never relocated by ordinary schema synchronization. A conflicting
location raises `StorageMigrationRequired` before mutation.

## 3. Persist and query objects

```python
person = Person(Name="Ada", Age=36)
person.save()

loaded = Person.get(person.pk)
loaded.Name = "Ada Lovelace"
loaded.save()

matches = Person.where(Name="Ada Lovelace").order_by("Name").all()
deleted = loaded.delete()
```

`save()` calls IRIS `%Save()`, `get()` opens by ID, query methods use the compiled SQL projection,
and `delete()` removes the persistent object. CRUD does not rewrite schema unless
`Meta.auto_sync=True` was explicitly selected.

IRIS handles can be converted explicitly with `Model.to_iris()` and `Model.from_iris()`.
The old root `materialize()` and `from_iris()` wrappers are deprecated and will be removed in
`0.4.0`.

## 4. Optional operational tooling

The package includes operational capabilities, but they are intentionally imported from explicit
secondary namespaces rather than the core package root.

### Reviewed migrations

```python
from iris_persistence.migrations import apply_plan, create_plan, verify_plan

plan = create_plan([Person], target_revision="001-person")
for operation in plan.operations:
    print(operation.safety, operation.op_type, operation.path)

result = apply_plan(plan)
assert verify_plan(plan).converged
```

`apply_plan()` is explicit authorization to apply a reviewed plan and writes a backup before
mutation. Blocked physical-storage changes remain rejected. The `iris-persistence` migration CLI
continues to expose the same commands.

### Reverse scaffolding

```python
from iris_persistence.scaffold import scaffold_from_iris

scaffold_from_iris("App.*", "./generated")
```

Generated models observe IRIS by default. Storage extraction is an expert option and emits
explicit imports from `iris_persistence.advanced_storage`.

### Expert storage operations

Complete custom storage definitions, optimizer statistics, inspection, and relocation helpers are
expert APIs:

```python
from iris_persistence.advanced_storage import (
    StorageProperty,
    inspect_existing_storage,
    tune_existing_storage_statistics,
)
```

These APIs operate on writable dictionary definitions and enforce storage safety rules. Physical
relocation requires a maintenance/copy/validation/cutover workflow; it is not an in-place tuning
operation. See [advanced schema mapping](docs/advanced_schema_mapping.md) and the runnable
[storage statistics](examples/advanced_existing_statistics.py) and
[relocation](examples/advanced_storage_relocation.py) examples.

## Compatibility and architecture

- [Product-surface migration for 0.3 and 0.4](docs/product_surface_migration.md)
- [Runtime boundary migration and breaking changes](docs/runtime_boundary_migration.md)
- [Runtime compatibility matrix](docs/runtime_compatibility.md)
- [Architecture](docs/architecture.md)

The `0.3.0` compatibility window supports old root imports for migrations and scaffolding with a
`DeprecationWarning`. Canonical module imports are unchanged. The aliases are removed in `0.4.0`.

## Development

```bash
.venv/bin/ruff check .
.venv/bin/mypy iris_persistence
.venv/bin/pytest -m "not integration"
.venv/bin/pytest -m integration
```

Generated model execution is a private optimization guarded by a reproducible Embedded and Native
benchmark. See [the benchmark gate](benchmarks/README.md).
