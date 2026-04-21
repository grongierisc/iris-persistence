# iris_orm

`iris_orm` is a small mapper for InterSystems IRIS with a Python-first model class, brownfield scaffolding, and typed storage metadata.

## What This Version Supports

- `Model` as the primary base class
- both `name: str = Field(...)` and `Annotated[..., Field(...)]` declarations
- `class Meta` for model configuration
- `persistent=True` and `serial=True` class flags
- field-level index synthesis via `Field(index=True|unique=True|primary_key=True)`
- `extend`, `replace`, and `observe` schema sync modes
- scaffold from live IRIS
- recursive references between `%Persistent` and `%SerialObject` models
- typed `StorageDefinition` metadata
- `iris_orm.testing.FakeAdapter` for unit tests
- structured scaffold warnings/results for partial metadata extraction

## Quick Start

```python
from __future__ import annotations

from typing import Annotated

import iris_orm
from iris_orm import Field, Model

# Embedded Python (running inside IRIS) — no argument needed.
iris_orm.configure()

# Remote connection — pass the iris native-API object.
# import iris
# conn = iris.connect(host, port, ns, user, pw)
# iris_orm.configure(conn)


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

## Model Definition

Fields can be declared either SQLModel-style or with `Annotated` metadata:

```python
from typing import Annotated
from iris_orm import Field, Model


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

`IRISModel` still exists as a compatibility alias, but new code should prefer `Model`.

`Meta.parameters` is written into IRIS class parameters during `sync_schema()`.
When scaffolding with `extract_meta=True`, `iris_orm` reads parameters from
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
from iris_orm import StorageData, StorageDefinition, StorageProperty, StorageSQLMap


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

Plain dicts are still accepted for backward compatibility, but `StorageDefinition(...)` is the intended API.

## Related Objects

`iris_orm` supports nested model references:

- `%Persistent` models can reference other `%Persistent` models
- `%Persistent` models can embed `%SerialObject` models
- recursive save/load works across those references
- live IRIS scaffolding emits sibling imports when related classes are included in the scaffold pattern

```python
from typing import Annotated
from iris_orm import Field, Model


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

## Runtime Configuration

`iris_orm` uses the `iris` module (from InterSystems) as its single unified runtime for both embedded and remote access.

**Embedded Python** (running inside IRIS — no argument needed):

```python
import iris_orm
iris_orm.configure()
```

**Remote** (running externally via the Native API):

```python
import iris
import iris_orm

conn = iris.connect(host, port, namespace, user, password)
iris_orm.configure(conn)
```

If `configure()` is never called, `iris_orm` falls back to the embedded runtime automatically on first use.

## Testing

`FakeAdapter` moved into the package so downstream projects can test models without a live IRIS instance.
It is intentionally limited to CRUD/query tests and does not emulate `%Dictionary` or schema compilation.

```python
from iris_orm.testing import FakeAdapter, preload_schema
from iris_orm.runtime import configure_default_runtime

adapter = FakeAdapter()
configure_default_runtime(runtime=adapter)
```

Run unit tests only:

```bash
.venv/bin/pytest -m "not integration"
```

Run the live IRIS round-trip coverage:

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

## Scaffold

Generate typed models from live IRIS:

```python
from iris_orm import ScaffoldResult, scaffold_from_iris

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

Generate from exported `.cls` files:

```python
from iris_orm import scaffold_from_cls

scaffold_from_cls("./cls", "./generated_models")
```

`scaffold_from_cls()` is reserved for future work and currently raises `NotImplementedError`.

Scaffold rules:

- `mode="observe"` is the default
- generated files use `Annotated[..., Field(...)]`
- generated files use `class Meta`
- storage metadata is emitted as `StorageDefinition(...)`
- `scaffold_selectivity=True` enriches `StorageProperty(..., selectivity=...)` from `%Dictionary.StoragePropertyDefinition`
- `mode="extend"` preserves indexes and parameters in `Meta`
- `return_result=True` returns generated file paths plus any metadata extraction warnings
- generated model files are expected to import cleanly as a compatibility contract
- include related classes in the scaffold pattern if you want generated models to reference each other with typed imports

Runnable examples:

- [examples/python_first.py](examples/python_first.py)
- [examples/proxy.py](examples/proxy.py)
- [examples/scaffold.py](examples/scaffold.py)
- [examples/demo/README.md](examples/demo/README.md)

## Public API

- `Model`
- `IRISModel`
- `Field`
- `Index`
- `StorageDefinition`
- `StorageData`
- `StorageProperty`
- `StorageSQLMap`
- `configure`
- `scaffold_from_iris`
- `scaffold_from_cls`
- `iris_orm.testing.FakeAdapter`

Advanced:

- `Model.sync_schema()`
- `iris_orm.testing.preload_schema`
- [Advanced Schema Mapping](./docs/advanced_schema_mapping.md)
