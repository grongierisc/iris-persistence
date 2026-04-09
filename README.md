# iris_orm

`iris_orm` is a small mapper for InterSystems IRIS with a Python-first model class, brownfield scaffolding, and typed storage metadata.

## What This Version Supports

- `IRISModel`
- `Annotated[..., Field(...)]` field declarations
- `class Meta` for model configuration
- additive, python, and proxy ownership modes
- scaffold from live IRIS
- scaffold from exported `.cls`
- typed `StorageDefinition` metadata
- `iris_orm.testing.FakeAdapter` for unit tests

Compatibility shims still exist for `field(...)`, `@index(...)`, `@parameter(...)`, and bare `_iris_*` attributes, but they now emit `DeprecationWarning`.

## Quick Start

```python
from __future__ import annotations

from typing import Annotated

from iris_orm import Field, IRISModel, Index, StorageDefinition


class Product(IRISModel):
    Name: Annotated[str, Field(required=True, maxlen=200)]
    Price: Annotated[float, Field(default=0.0)]
    InStock: Annotated[bool, Field(default=True)]

    class Meta:
        classname = "Demo.Product"
        mode = "python"
        storage = StorageDefinition(
            data_location="^Demo.ProductD",
            default_data="ProductDefaultData",
            type="%Storage.Persistent",
        )
        indexes = [Index("NameIdx", properties="Name", unique=True)]
        parameters = {"DEFAULTGLOBAL": "^Demo.ProductD"}


product = Product(Name="Widget", Price=12.5, InStock=True).save()
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
    mode = "additive"
    superclasses = "%Persistent"
    engine = some_sqlalchemy_engine
    storage = StorageDefinition(data_location="^Demo.ArticleD")
    indexes = [Index("TitleIdx", properties="Title", unique=True)]
    parameters = {"DEFAULTGLOBAL": "^Demo.ArticleD"}
```

`Meta` fields map to the internal `_iris_*` attributes:

- `classname` -> `_iris_classname`
- `mode` -> `_iris_mode`
- `superclasses` -> `_iris_superclasses`
- `engine` -> `_iris_engine`
- `storage` -> `_iris_storage`
- `indexes` -> `_iris_indexes`
- `parameters` -> `_iris_parameters`

## Ownership Modes

### Additive

`"additive"` is the default and the safe starting point.

```python
class Product(IRISModel):
    Name: Annotated[str, Field(required=True)]

    class Meta:
        classname = "Demo.Product"
```

Behavior:

- Python adds missing properties, indexes, parameters, and storage metadata
- existing IRIS-only members are kept
- conflicts are overwritten from Python

### Python

`"python"` is the destructive mode.

```python
class Meta:
    classname = "Demo.Product"
    mode = "python"
```

Behavior:

- Python declarations are authoritative
- first real use auto-syncs the class to IRIS
- extra IRIS properties, indexes, parameters, and storage settings are removed or overwritten

### Proxy

`"proxy"` binds to an existing IRIS class without changing its schema.

```python
class Article(IRISModel):
    class Meta:
        classname = "Demo.Article"
        mode = "proxy"
```

Behavior:

- IRIS stays authoritative
- schema is loaded from IRIS
- Python gets typed fields for CRUD and queries
- no schema overwrite happens

## Storage Metadata

Storage uses typed dataclasses instead of raw nested dicts.

```python
from iris_orm import StorageData, StorageDefinition, StorageProperty, StorageSQLMap


class Product(IRISModel):
    Name: Annotated[str, Field(required=True)]

    class Meta:
        classname = "Demo.Product"
        mode = "python"
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

Use `configure(...)` to register the runtime for the current execution context:

```python
import iris_orm
from sqlalchemy import create_engine

iris_orm.configure(create_engine("iris://user:pass@host:1972/USER"))
```

If you do not call `configure(...)` and a model has no `Meta.engine`, `iris_orm` falls back to the embedded Python runtime by default.

Runtime backends are split into three flavors: `EmbeddedRuntime`, `CommunityRuntime` (for `iris://` / `intersystems_iris`), and `OfficialRuntime` (for `iris+intersystems://`).

Or attach an engine directly to a model:

```python
class Meta:
    classname = "Demo.Product"
    engine = create_engine("iris://user:pass@host:1972/USER")
```

`configure_default_runtime(...)` remains available as a compatibility alias.

## Testing

`FakeAdapter` moved into the package so downstream projects can test models without a live IRIS instance.

```python
from iris_orm import IRISModel, configure
from iris_orm.testing import FakeAdapter

runtime = FakeAdapter()
configure(runtime=runtime)
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

- [examples/python_first.py](/Users/grongier/git/iris-persistence/examples/python_first.py)
- [examples/proxy.py](/Users/grongier/git/iris-persistence/examples/proxy.py)
- [examples/scaffold.py](/Users/grongier/git/iris-persistence/examples/scaffold.py)

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

Advanced but available:

- `Model.plan()`
- `Model.sync()`
- `configure_default_runtime(...)`
- `EmbeddedRuntime`
- `CommunityRuntime`
- `OfficialRuntime`
