# iris_orm

`iris_orm` is a small mapper for InterSystems IRIS with a Python-first model class, brownfield scaffolding, and typed storage metadata.

## What This Version Supports

- `IRISModel`
- `Annotated[..., Field(...)]` field declarations
- `class Meta` for model configuration
- `extend`, `replace`, and `observe` schema sync modes
- scaffold from live IRIS
- scaffold from exported `.cls`
- typed `StorageDefinition` metadata
- `iris_orm.testing.FakeAdapter` for unit tests

## Quick Start

```python
from __future__ import annotations

from typing import Annotated

import iris_orm
from iris_orm import Field, IRISModel, Index

# Embedded Python (running inside IRIS) — no argument needed.
iris_orm.configure()

# Remote connection — pass the iris native-API object.
# import iris
# conn = iris.connect(host, port, ns, user, pw)
# iris_orm.configure(conn)


class Product(IRISModel):
    Name: Annotated[str, Field(required=True, maxlen=200)]
    Price: Annotated[float, Field(default=0.0)]
    InStock: Annotated[bool, Field(default=True)]

    class Meta:
        classname = "Demo.Product"
        mode = "replace"
        indexes = [Index("NameIdx", properties="Name", unique=True)]


product = Product(Name="Widget", Price=12.5, InStock=True)
product.save()
same = Product.get(product.pk)
rows = Product.where(Name="Widget").order_by("Name").all()
```

## Model Definition

Fields are declared with `typing.Annotated` and `Field(...)` metadata:

```python
from typing import Annotated
from iris_orm import Field, IRISModel


class Article(IRISModel):
    Title: Annotated[str, Field(required=True, maxlen=500)]
    Views: Annotated[int, Field(default=0)]

    class Meta:
        classname = "Demo.Article"
```

Model configuration lives in an optional inner `Meta` class:

```python
class Meta:
    classname = "Demo.Article"
    mode = "extend"             # "extend" | "replace" | "observe" (default: "extend")
    superclasses = "%Persistent"
    storage = StorageDefinition(data_location="^Demo.ArticleD")
    indexes = [Index("TitleIdx", properties="Title", unique=True)]
    parameters = {"DEFAULTGLOBAL": "^Demo.ArticleD"}
```

## Ownership Modes

### extend (default)

Python and IRIS share ownership. Safe starting point for brownfield classes.

```python
class Product(IRISModel):
    Name: Annotated[str, Field(required=True)]

    class Meta:
        classname = "Demo.Product"
        # mode = "extend"  ← default, can be omitted
```

Behavior:

- Python adds missing properties, indexes, parameters, and storage metadata
- existing IRIS-only members are kept
- Python-declared fields overwrite IRIS fields with the same name

### replace

Python is fully authoritative. Use for greenfield classes owned entirely by Python.

```python
class Meta:
    classname = "Demo.Product"
    mode = "replace"
```

Behavior:

- IRIS class is kept in sync with the Python model on every first use
- properties, indexes, parameters, and storage not declared in Python are removed from IRIS
- recompile is skipped when the schema has not changed

### observe

IRIS is authoritative. Use to bind to existing classes without touching their schema.

```python
class Article(IRISModel):
    class Meta:
        classname = "Demo.Article"
        mode = "observe"
```

Behavior:

- schema is loaded from IRIS on first use; Python fields are inferred from it
- no schema write or compile ever happens
- typed CRUD and queries work the same as the other modes

## Storage Metadata

Storage uses typed dataclasses instead of raw nested dicts.

```python
from iris_orm import StorageData, StorageDefinition, StorageProperty, StorageSQLMap


class Product(IRISModel):
    Name: Annotated[str, Field(required=True)]

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

```python
from iris_orm.testing import FakeAdapter, preload_schema
from iris_orm.runtime import configure_default_runtime

adapter = FakeAdapter()
configure_default_runtime(runtime=adapter)
```

## Scaffold

Generate typed models from live IRIS:

```python
from iris_orm import scaffold_from_iris

scaffold_from_iris("Demo.*", "./generated_models")
```

Generate from exported `.cls` files:

```python
from iris_orm import scaffold_from_cls

scaffold_from_cls("./cls", "./generated_models")
```

Scaffold rules:

- `style="proxy"` is the default
- generated files use `Annotated[..., Field(...)]`
- generated files use `class Meta`
- storage metadata is emitted as `StorageDefinition(...)`
- `style="python"` preserves indexes and parameters in `Meta`

Runnable examples:

- [examples/python_first.py](examples/python_first.py)
- [examples/proxy.py](examples/proxy.py)
- [examples/scaffold.py](examples/scaffold.py)

## Public API

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

- `Model.plan()`
- `Model.sync_schema()`
- `iris_orm.testing.preload_schema`
