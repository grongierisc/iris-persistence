# iris_persistence

`iris_persistence` is a Python object persistence layer for InterSystems IRIS, inspired by `%Persistent`. It provides a Python-first model class, brownfield scaffolding, and typed storage metadata using IRIS APIs rather than SQL as its persistence model.

> Status: `0.1.0` public preview. The API is experimental and may change before a stable `1.0` release. Python 3.10 or newer is required.

## What This Version Supports

- `Model` as the primary base class
- both `name: str = Field(...)` and `Annotated[..., Field(...)]` declarations
- `class Meta` for model configuration
- `persistent=True` and `serial=True` class flags
- field-level index synthesis via `Field(index=True|unique=True|primary_key=True)`
- `extend`, `replace`, and `observe` schema sync modes
- scaffold from live IRIS
- recursive references between `%Persistent` and `%SerialObject` models
- native `Model` inheritance
- explicit `dict` and dataclass DTO conversion helpers
- typed `StorageDefinition` metadata
- `iris_persistence.testing.InMemoryAdapter` for unit tests
- structured scaffold warnings/results for partial metadata extraction
- raw IRIS object interop with `to_iris()` and `from_iris()`

## Quick Start

```python
from __future__ import annotations

from typing import Annotated

import iris_persistence
from iris_persistence import Field, Model

# Embedded Python (running inside IRIS) — no argument needed.
iris_persistence.configure()

# Remote connection — pass the iris native-API object.
# import iris
# conn = iris.connect(host, port, ns, user, pw)
# iris_persistence.configure(conn)


class Product(Model, persistent=True):
    name: str = Field(required=True, max_length=200, unique=True)
    price: Annotated[float, Field(default=0.0)]
    in_stock: bool = True

    class Meta:
        classname = "Demo.Product"
        mode = "replace"


product = Product(name="Widget", price=12.5, in_stock=True)
Product.sync_schema()
product.save()
same = Product.get(product.pk)
rows = Product.where(name="Widget").order_by("name").all()
```

## Update Semantics

`None` is an explicit value. When a model field is nullable, assigning `None`
and saving clears that IRIS property. Fields that are absent from a partially
constructed model are not written, so existing IRIS values are left unchanged.

## Schema Migrations

For production-controlled schemas, use the migration API or CLI instead of ad hoc
`auto_sync` writes:

```python
from iris_persistence.migrations import apply_plan, create_plan, rollback_backup, verify_plan

plan = create_plan([Product], target_revision="001_add_product")
plan.save("plan.json")

result = apply_plan(plan, backup_dir=".iris_persistence/backups")
verify_plan(plan)

# If the reviewed change must be reverted:
rollback_backup(result.backup_dir, allow_destructive=True)
```

The console script exposes the same workflow:

```bash
iris-persistence plan myapp.models:Product --to 001_add_product --out plan.json
iris-persistence review-plan plan.json
iris-persistence apply-plan plan.json --backup-dir .iris_persistence/backups
iris-persistence verify-plan plan.json
iris-persistence rollback-backup .iris_persistence/backups/<backup-id> --allow-destructive
```

Migration plans include structured operations, safety classification, and
live-schema fingerprints so stale plans are rejected before writes. Apply writes
a pre-change backup before any IRIS mutation. Rollback restores classes from
`schema_states.json`; hand-written downgrade functions are not part of this
workflow.

## Model Inheritance And DTOs

Use `Model` inheritance for shared persistence fields:

```python
class NamedRecord(Model):
    name: str


class Product(NamedRecord, persistent=True):
    price: float = 0.0
```

Use explicit conversion helpers for API or application DTOs:

```python
from dataclasses import dataclass


@dataclass
class ProductDTO:
    name: str
    price: float


product = Product.from_dict({"name": "Widget", "price": 12.5})
payload = product.to_dict()
dto = product.to_dataclass(ProductDTO)
same = Product.from_dataclass(dto)
```

Dataclasses are supported as DTOs, not as persistence base classes.

## Model Definition

Fields can be declared either with `Field(...)` defaults or with `Annotated` metadata:

```python
from typing import Annotated
from iris_persistence import Field, Model


class Article(Model, persistent=True):
    title: str = Field(required=True, max_length=500)
    views: Annotated[int, Field(default=0)]

    class Meta:
        classname = "Demo.Article"
```

If you need to force the underlying IRIS property type instead of using the Python type mapping,
set `Field(iris_type="...")`:

```python
class Event(Model, persistent=True):
    payload: bytes = Field(iris_type="%Stream.GlobalBinary")
    created_at: str = Field(iris_type="%Library.TimeStamp")
```

Model configuration lives in an optional inner `Meta` class:

```python
class Meta:
    classname = "Demo.Article"
    mode = "extend"             # "extend" | "replace" | "observe" (default: "extend")
    storage = StorageDefinition(data_location="^Demo.ArticleD")
    indexes = [Index("TitleIdx", properties="Title", unique=True)]
    parameters = {"DEFAULTGLOBAL": "^Demo.ArticleD"}
```

`Meta.parameters` is written into IRIS class parameters during `sync_schema()`.
When scaffolding with `extract_meta=True`, `iris_persistence` reads parameters from
`%Dictionary.CompiledParameter` and falls back to the live
`%Dictionary.ClassDefinition.Parameters` collection if the SQL dictionary view is empty.

## Ownership Modes

### extend (default)

Python and IRIS share ownership. Safe starting point for brownfield classes.

```python
class Product(Model, persistent=True):
    name: str = Field(required=True)

    class Meta:
        classname = "Demo.Product"
        # mode = "extend"  ← default, can be omitted
```

Behavior:

- Python adds missing properties, indexes, parameters, and storage metadata
- existing IRIS-only members are kept
- Python-declared fields overwrite IRIS fields with the same name
- schema changes happen when `Model.sync_schema()` is called

### replace

Python is fully authoritative. Use for greenfield classes owned entirely by Python.

```python
class Meta:
    classname = "Demo.Product"
    mode = "replace"
```

Behavior:

- IRIS class is rebuilt from the Python model when `Model.sync_schema()` is called
- properties, indexes, parameters, and storage not declared in Python are removed from IRIS
- referenced `Model` types are synced first so related classes exist before parent compilation

### observe

IRIS is authoritative. Use to bind to existing classes without touching their schema.

```python
class Article(Model):
    class Meta:
        classname = "Demo.Article"
        mode = "observe"
```

Behavior:

- no schema write or compile ever happens
- use this with explicitly declared Python fields or scaffolded models
- typed CRUD and queries work the same as the other modes

## Storage Metadata

Storage uses typed dataclasses instead of raw nested dicts.

```python
from iris_persistence import StorageData, StorageDefinition, StorageProperty, StorageSQLMap


class Product(Model, persistent=True):
    name: str = Field(required=True)

    class Meta:
        classname = "Demo.Product"
        mode = "replace"
        storage = StorageDefinition(
            data_location="^Demo.ProductD",
            default_data="ProductDefaultData",
            type="%Storage.Persistent",
            data=(
                StorageData(
                    name="ProductDefaultData",
                    structure="listnode",
                    values={"1": "%%CLASSNAME", "2": "Name"},
                ),
            ),
            properties=(
                StorageProperty(name="Name", average_field_size="8"),
            ),
            sql_maps=(
                StorageSQLMap(name="IDKEY", block_count="-4"),
            ),
        )
```

Plain dicts are accepted, but `StorageDefinition(...)` is the intended API.

## Related Objects

`iris_persistence` supports nested model references:

- `%Persistent` models can reference other `%Persistent` models
- `%Persistent` models can embed `%SerialObject` models
- recursive save/load works across those references
- live IRIS scaffolding emits sibling imports when related classes are included in the scaffold pattern

```python
from typing import Annotated
from iris_persistence import Field, Model


class Address(Model, serial=True):
    street: str = Field(required=True, max_length=120)

    class Meta:
        classname = "Demo.Address"
        mode = "replace"


class Customer(Model, persistent=True):
    name: str = Field(required=True, max_length=120)

    class Meta:
        classname = "Demo.Customer"
        mode = "replace"


class Order(Model, persistent=True):
    number: str = Field(required=True, max_length=32)
    customer: Customer | None = None
    ship_to: Address | None = None

    class Meta:
        classname = "Demo.Order"
        mode = "replace"
```

## IRIS Object Interop

Use `to_iris()` when you need the underlying IRIS object handle without saving a row:

```python
product = Product(name="Widget", price=12.5)
iris_obj = product.to_iris()

assert product.pk is None
```

`to_iris()` populates the object graph in memory. It may create unsaved IRIS object
handles for related models, but it does not call `%Save()` and does not persist
`%Persistent` rows. A later `save()` reuses those materialized handles and
persists related `%Persistent` models through the normal save path. For pure
transient object-body creation, disable persistence-oriented conveniences:

```python
iris_obj = product.to_iris(auto_sync=False, validate=False)
```

Use `from_iris()` when you already have an IRIS object handle and want a typed
Python model wrapper:

```python
iris_obj = iris.cls("Demo.Product")._OpenId("1")
product = Product.from_iris(iris_obj, known_pk="1")
```

## Runtime Configuration

`iris_persistence` uses `iris-embedded-python-wrapper` as its unified runtime facade for embedded, embedded-local, and native remote access.

**Embedded Python** (running inside IRIS — no argument needed):

```python
import iris_persistence
iris_persistence.configure()
```

**Remote** (running externally via the Native API):

```python
import iris
import iris_persistence

conn = iris.connect(host, port, namespace, user, password)
iris_persistence.configure(conn)
```

If `configure()` is never called, `iris_persistence` reads the current `iris.runtime` state without mutating it. Configure embedded mode with `IRISINSTALLDIR` or `iris.connect(path=...)`, or configure native mode with `iris_persistence.configure(conn)`.

If you already have a DB-API connection that should be reused for queries and scaffolding, bind it explicitly:

```python
iris_persistence.configure(dbapi_connection=dbapi_conn)
```

## Testing

`InMemoryAdapter` is available for model tests without a live IRIS instance.
It is intentionally limited to CRUD/query tests and does not emulate `%Dictionary` or schema compilation.

```python
from iris_persistence.testing import InMemoryAdapter
from iris_persistence.runtime import configure_default_runtime

adapter = InMemoryAdapter()
configure_default_runtime(runtime=adapter)
```

Run unit tests inside the IRIS Docker container:

```bash
./scripts/test-unit.sh
```

Run the live IRIS round-trip coverage inside Docker:

```bash
./scripts/test-docker.sh
```

The Docker E2E runner uses `docker-compose-test.yml` and defaults to
`containers.intersystems.com/intersystems/iris-community:latest-cd`.
Override the image tag when needed:

```bash
IRIS_IMAGE_TAG=latest-preview ./scripts/test-docker.sh
```

`test-unit.sh` and `test-docker.sh` use the same local container runner. `test-unit.sh`
selects `pytest -m "not integration"`; `test-docker.sh` selects `pytest -m integration`.

You can still run integration tests directly against a configured local IRIS runtime:

```bash
.venv/bin/pytest -m integration
```

Integration tests use checked-in fixtures under `tests/fixtures/`:

- `tests/fixtures/objectscript/`: one-class-per-`.cls` IRIS source fixtures plus Python fallback sidecars
- `tests/fixtures/python/`: Python-first fixture models for round-trip coverage

That fixture set covers:

- `%Persistent`
- `Ens.Request`
- `%SerialObject`
- recursive object graphs (`%Persistent` referencing `%Persistent` and `%SerialObject`)

## Release Verification

Run the local checks:

```bash
.venv/bin/python -m ruff check iris_persistence tests examples benchmarks
.venv/bin/python -m mypy iris_persistence
.venv/bin/python -m pytest -m "not integration"
```

Run live IRIS integration coverage against the community image:

```bash
IRIS_IMAGE_TAG=latest-cd ./scripts/test-docker.sh
```

Latest verification, 2026-05-11:

- Ruff: passed
- mypy: passed, `10` source files checked
- Unit/non-integration tests: `91 passed`, `14 deselected`
- Docker integration, `latest-cd`: `12 passed`, `2 skipped`, `91 deselected`

## Benchmarks

Run the simple benchmark in Docker:

```bash
./scripts/benchmark-simple.sh --rows 500 --repeats 3
```

Run it from a local virtualenv:

```bash
.venv/bin/python benchmarks/simple_suite.py --rows 500 --repeats 3
```

On macOS, do not export `DYLD_LIBRARY_PATH` to the IRIS install `bin` directory for
local benchmark runs. That can force the Native API wheel to bind to incompatible
IRIS dylibs. If your shell exports it globally, unset it for the benchmark process:

```bash
env -u DYLD_LIBRARY_PATH .venv/bin/python benchmarks/simple_suite.py --rows 500 --repeats 3
```

Use `--modes` to run a subset, and `--require-remote` when remote modes must fail
instead of being skipped:

```bash
.venv/bin/python benchmarks/simple_suite.py --modes embedded_persistence,objectscript
```

## Scaffold

Generate typed models from live IRIS:

```python
from iris_persistence import ScaffoldResult, scaffold_from_iris

scaffold_from_iris("Demo.*", "./generated_models")

result: ScaffoldResult = scaffold_from_iris(
    "Demo.*",
    "./generated_models",
    extract_meta=True,
    scaffold_selectivity=True,
    return_result=True,
)
for warning in result.warnings:
    print(warning.message)
```

Scaffold rules:

- `mode="observe"` is the default
- generated files use `Annotated[..., Field(...)]`
- generated files use `class Meta`
- storage metadata is emitted as `StorageDefinition(...)`
- `scaffold_selectivity=True` enriches `StorageProperty(..., selectivity=...)` from `%Dictionary.StoragePropertyDefinition`
- `mode="extend"` preserves indexes and parameters in `Meta`
- `return_result=True` returns generated file paths plus any metadata extraction warnings
- generated model files are expected to import cleanly
- include related classes in the scaffold pattern if you want generated models to reference each other with typed imports

Runnable examples:

- [examples/scaffold.py](examples/scaffold.py)
- [examples/demo/README.md](examples/demo/README.md)

## Public API

- `Model`
- `Field`
- `Index`
- `StorageDefinition`
- `StorageData`
- `StorageProperty`
- `StorageSQLMap`
- `configure`
- `scaffold_from_iris`
- `iris_persistence.testing.InMemoryAdapter`

Advanced:

- `Model.sync_schema()`
- [Advanced Schema Mapping](./docs/advanced_schema_mapping.md)

## Roadmap

- `iris_persistence.scaffold.scaffold_from_cls()` for exported `.cls` files. It is intentionally
  unimplemented today and raises `NotImplementedError`.
