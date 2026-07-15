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

Embedded Python discovers its IRIS runtime automatically. For native Python, pass an IRIS
connection:

```python
import iris_persistence

iris_persistence.configure(connection)
```

Both runtime paths use the same model and schema APIs.

## Development

```bash
.venv/bin/ruff check .
.venv/bin/mypy iris_persistence
.venv/bin/pytest -m "not integration"
.venv/bin/pytest -m integration
```

See [advanced schema mapping](docs/advanced_schema_mapping.md) for the dictionary-level mapping.
