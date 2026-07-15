# iris_persistence

Python-authored persistent and serial IRIS classes. Python owns class members; the IRIS
compiler owns generated storage and runtime methods.

## Quick start

```python
from iris_persistence import Field, Index, Model


class Person(Model, persistent=True):
    Name: str = Field(required=True, max_length=120)

    class Meta:
        classname = "App.Person"
        mode = "managed"
        indexes = [Index("NameIdx", properties="Name")]


Person.sync_schema()
person = Person(Name="Ada")
person.save()

iris_object = person.to_iris()
copy = Person.from_iris(iris_object)
```

`managed` adds, updates, and removes Python-owned properties, indexes, and parameters without
deleting the class. IRIS generates and evolves `Storage Default` when the class is compiled.
`observe` never changes IRIS and is intended for existing or scaffolded classes.

The former `extend` and `replace` modes were removed in 0.3.0.

## Storage ownership

Prefer IRIS class parameters when they express the intended layout:

```python
class Meta:
    mode = "managed"
    parameters = {
        "DEFAULTGLOBAL": "^App.PersonD",
        "USEEXTENTSET": "1",
    }
```

For creation-time physical locations, use `StorageTuning`:

```python
from iris_persistence import StorageTuning


class Meta:
    mode = "managed"
    storage_tuning = StorageTuning(
        data_location="^App.PersonD",
        id_location="^App.PersonD",
        index_location="^App.PersonI",
        stream_location="^App.PersonS",
        index_locations={"NameIdx": '^App.PersonI("NameIdx")'},
    )
```

On first creation, iris_persistence pre-seeds only these fields on a storage definition named
`Default`, then compiles once. IRIS fills in data nodes and runtime methods.

For a complete expert-owned layout, import from the explicit advanced module:

```python
from iris_persistence.advanced_storage import StorageData, StorageDefinition


class Meta:
    mode = "managed"
    custom_storage = StorageDefinition(
        name="CustomStorage",
        data_location="^App.PersonD",
        data=(
            StorageData(
                name="PersonData",
                structure="listnode",
                values={"1": "Name"},
            ),
        ),
    )
```

`storage_tuning` and `custom_storage` are mutually exclusive. Neither is valid for `observe`
or serial models. After the class has compiled, the declaration is immutable through ordinary
sync. A mismatch raises `StorageMigrationRequired` before mutation and migration plans report a
non-bypassable `blocked_storage_change`. Moving existing data requires a separate migration.

### Advanced tuning of an existing class

There are two distinct workflows for an existing class.

Non-location optimizer statistics can be changed explicitly through the advanced API:

```python
from iris_persistence.advanced_storage import (
    StorageProperty,
    inspect_existing_storage,
    tune_existing_storage_statistics,
)

before = inspect_existing_storage("App.Person")
name_stats = {item.name: item for item in before.properties}["Name"]
print(before.data_location, name_stats.selectivity)

result = tune_existing_storage_statistics(
    "App.Person",
    properties=(
        StorageProperty(
            name="Name",
            average_field_size="32",
            selectivity="5.0000%",
            outlier_selectivity='.999999:"UNKNOWN"',
        ),
    ),
)

after = inspect_existing_storage("App.Person")
```

`inspect_existing_storage()` returns a typed, read-only `StorageDefinition` snapshot from the
active writable dictionary storage. Pass `storage_name="CustomStorage"` to inspect a named
definition instead. It does not use compiled SQL projections and performs no mutation.

`tune_existing_storage_statistics()` opens the active writable `%Dictionary.StorageDefinition`, updates only storage-property
statistics, saves, and recompiles the class. It cannot change any data, ID, index, stream,
counter, version, or extent location. The complete runnable example is
[examples/advanced_existing_statistics.py](examples/advanced_existing_statistics.py):

```bash
python examples/advanced_existing_statistics.py App.Person Name
```

InterSystems documents these writable fields on
[`%Dictionary.StoragePropertyDefinition`](https://docs.intersystems.com/irislatest/csp/documatic/%25CSP.Documatic.cls?CLASSNAME=%25Dictionary.StoragePropertyDefinition&LIBRARY=%25SYS)
and recommends modifying defined dictionary classes rather than compiled projections.

Physical relocation is not an in-place tuning operation. Never point an occupied class at empty
new globals: existing IDs, data, indexes, streams, and references would still be in the old
locations. The safe general pattern is:

1. Back up the namespace and establish a maintenance or dual-write window.
2. Create a second persistent class with the target `StorageTuning`.
3. Copy through object or SQL APIs and retain an old-ID to new-ID map.
4. Validate row counts, field values, streams, indexes, relationships, and application queries.
5. Cut application reads and writes over explicitly.
6. Keep the source intact until rollback is no longer required.

[examples/advanced_storage_relocation.py](examples/advanced_storage_relocation.py) implements
the create/copy/validate portion and deliberately does not perform cutover or delete the source:

```bash
python examples/advanced_storage_relocation.py             # review-only
python examples/advanced_storage_relocation.py --execute-copy
```

Adapt both model shapes before running it. IDs and external references are not automatically
preserved. InterSystems likewise warns not to redefine or delete storage for a class containing
data in its
[persistent storage guidance](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls/framework-api/scbi/Documatic/DocBook.UI.Page.cls?KEY=GOBJ_storageglobals).

## How the workflow works now

The normal lifecycle has one Python-owned model definition and one IRIS-owned compiled class:

1. Declare fields, indexes, parameters, and metadata in Python with `mode="managed"`.
2. Preview the difference with `Model.diff_schema()` or `Model.sync_schema(dry_run=True)`.
3. Create or evolve the IRIS class with a reviewed migration plan.
4. IRIS compiles the class and generates `Storage Default`, SQL projection, and runtime methods.
5. Use the model for object CRUD. Schema synchronization is not needed for each object operation.
6. Change the Python model and repeat the plan/apply/verify cycle.

```python
from iris_persistence import apply_plan, create_plan, verify_plan

plan = create_plan([Person], target_revision="001-person")

# Review plan.operations or save the JSON plan for code review.
for operation in plan.operations:
    print(operation.safety, operation.op_type, operation.path)

result = apply_plan(plan)  # writes a backup before mutation
if result.status == "blocked":
    raise RuntimeError(result.skipped_operations)

assert verify_plan(plan).converged
```

Calling `apply_plan()` is explicit authorization to apply the reviewed plan. Calling
`rollback_backup(result.backup_dir)` is explicit authorization to restore its backup; there is no
`allow_destructive` flag. A storage operation with `safety="blocked"` is different: it is always
rejected because physical data relocation needs a dedicated migration workflow.

For quick local development, `Person.sync_schema()` performs the same managed reconciliation
directly. Production code should normally use `create_plan()`, `apply_plan()`, and `verify_plan()`
so the change is inspectable and backed up.

Generated compiler storage is excluded from ordinary diffs and backups. Managed migrations make
targeted member changes; they do not delete and rebuild the class or rewrite storage.

## Lifecycle of a `%Persistent` object

Once the class exists, object operations are deliberately small:

```python
# Create
person = Person(Name="Ada")
person.save()
person_id = person.pk

# Read
loaded = Person.get(person_id)

# Update
loaded.Name = "Ada Lovelace"
loaded.save()

# Query through the IRIS SQL projection
matches = Person.where(Name="Ada Lovelace").order_by("Name").all()

# Delete
deleted = loaded.delete()
assert deleted
assert Person.get(person_id) is None
```

`save()` calls IRIS `%Save()`, `get()` opens the IRIS object by ID, query methods use the compiled
SQL projection, and `delete()` removes the persistent object. These operations do not rewrite the
class definition or its storage unless `Meta.auto_sync=True` was explicitly enabled.

A complete runnable example also evolves the class from `PersonV1` to `PersonV2` without
rebuilding storage: [examples/demo/06_persistent_lifecycle.py](examples/demo/06_persistent_lifecycle.py).

Run it against the in-memory demonstration backend:

```bash
IRIS_DEMO_BACKEND=fake python examples/demo/06_persistent_lifecycle.py
```

Or against IRIS:

```bash
IRIS_DEMO_BACKEND=embedded python examples/demo/06_persistent_lifecycle.py
```

## Scaffolding

```python
from iris_persistence import scaffold_from_iris

# Default: no storage metadata; generated models observe IRIS.
scaffold_from_iris("App.*", "./generated")

# Expert snapshot from writable %Dictionary.ClassDefinition.Storages.
scaffold_from_iris(
    "App.Person",
    "./generated",
    mode="managed",
    extract_meta=True,
    storage="custom",
)
```

`storage="custom"` emits `Meta.custom_storage` and imports from
`iris_persistence.advanced_storage`. Compiled storage projections, selectivity enrichment, and
hidden-storage fallback queries are intentionally not used.

## Runtime configuration

Embedded Python discovers its IRIS runtime automatically. For Native Python, configure the wrapper
through an immutable `RuntimeConfig`:

```python
from iris_persistence import RuntimeConfig, configure_runtime

configure_runtime(RuntimeConfig(native_connection=connection))
```

Both runtime paths use the same model and schema APIs.

The root `configure` function and the former runtime adapter classes were removed. The root
`materialize` and `from_iris` names remain deprecated compatibility wrappers; prefer
`Model.to_iris` and `Model.from_iris`.

See [runtime boundary migration and breaking changes](docs/runtime_boundary_migration.md) before
upgrading custom runtimes, Native integrations, or code that directly manages DBAPI connections.

## Development

```bash
.venv/bin/ruff check .
.venv/bin/mypy iris_persistence
.venv/bin/pytest -m "not integration"
.venv/bin/pytest -m integration
```

See [advanced schema mapping](docs/advanced_schema_mapping.md) for the dictionary-level mapping.
