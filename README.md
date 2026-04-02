# iris_orm

`iris_orm` is a small Python-first mapper for InterSystems IRIS built around one idea:

- `_iris_mode = "python"`: Python owns the schema and overwrites IRIS to match it.
- `_iris_mode = "proxy"`: IRIS owns the schema and Python only acts as a typed proxy.

The package keeps the `IRISModel` idea, supports brownfield scaffolding, and carries IRIS storage metadata in Python files so you can inspect it in proxy models or fine tune it in python-first models.

## What This Version Supports

- `IRISModel`
- `field(...)`
- `@parameter(...)`
- `@index(...)`
- python-first overwrite
- proxy binding for existing IRIS classes
- scaffold from live IRIS
- scaffold from exported `.cls`
- storage metadata on generated models and python-first models through `_iris_storage`

This restart intentionally does not include the older migration/session/trigger surface.

## Quick Start

```python
from iris_orm import IRISModel, field, index, parameter


@parameter("DEFAULTGLOBAL", "^Demo.ProductD")
@index("NameIdx", properties="Name", unique=True)
class Product(IRISModel):
    _iris_classname = "Demo.Product"
    _iris_mode = "python"
    _iris_storage = {
        "name": "Default",
        "type": "%Storage.Persistent",
        "data_location": "^Demo.ProductD",
        "default_data": "ProductDefaultData",
    }

    Name: str = field(required=True, maxlen=200)
    Price: float = field(default=0.0)
    InStock: bool = field(default=True)


product = Product(Name="Widget", Price=12.5, InStock=True)
product.save()

same = Product.get(product.pk)
rows = Product.where(Name="Widget").order_by("Name").all()
```

On first real use, a python-first model compares its declared schema to IRIS and overwrites IRIS when they differ.

## Ownership Modes

### Python First

```python
class Product(IRISModel):
    _iris_classname = "Demo.Product"
    _iris_mode = "python"
```

Behavior:

- Python declarations are the reference
- first runtime use auto-syncs the class to IRIS
- extra IRIS properties, indexes, parameters, and storage settings are overwritten
- `_iris_storage` lets you fine tune storage mapping directly in Python

### Proxy

```python
from iris_orm import IRISModel


class Article(IRISModel):
    _iris_classname = "Demo.Article"
    _iris_mode = "proxy"
```

Behavior:

- IRIS stays authoritative
- schema is fetched from IRIS
- Python gets typed fields for CRUD and queries
- no schema overwrite happens
- scaffolded proxy files still keep `_iris_storage` metadata for visibility

## Decorators

Only 2 schema decorators are supported in this version:

```python
@parameter("DEFAULTGLOBAL", "^Demo.ProductD")
@index("NameIdx", properties="Name", unique=True)
class Product(IRISModel):
    ...
```

They are meant for python-first models.

## Storage Metadata

Storage is carried as structured Python data on `_iris_storage`.

Example:

```python
class Product(IRISModel):
    _iris_classname = "Demo.Product"
    _iris_mode = "python"
    _iris_storage = {
        "name": "Default",
        "type": "%Storage.Persistent",
        "data_location": "^Demo.ProductD",
        "default_data": "ProductDefaultData",
        "id_location": "^Demo.ProductD",
        "index_location": "^Demo.ProductI",
        "stream_location": "^Demo.ProductS",
        "data": [
            {
                "name": "ProductDefaultData",
                "structure": "listnode",
                "values": [
                    {"name": "1", "value": "%%CLASSNAME"},
                    {"name": "2", "value": "Name"},
                ],
            }
        ],
    }
```

This is used in two places:

- scaffolded/brownfield models keep IRIS storage information in the generated Python file
- python-first models can declare or edit `_iris_storage` to fine tune storage mapping

## Scaffold

Generate typed proxy models from live IRIS:

```python
from iris_orm import scaffold_from_iris

scaffold_from_iris("Demo.*", "./generated_models")
```

Generate python-first starting points instead:

```python
from iris_orm import scaffold_from_iris

scaffold_from_iris("Demo.*", "./generated_models", style="python")
```

Generate models from exported `.cls` files:

```python
from iris_orm import scaffold_from_cls

scaffold_from_cls("./cls", "./generated_models")
```

Scaffold rules:

- `style="proxy"` is the default
- proxy scaffolds keep typed fields and `_iris_storage`
- `style="python"` renders `@parameter(...)`, `@index(...)`, and `_iris_storage`

There is a runnable scaffold example at [examples/scaffold.py](/Users/grongier/git/iris-persistence/examples/scaffold.py).

## Public API

Small by design:

- `IRISModel`
- `field`
- `parameter`
- `index`
- `scaffold_from_iris`
- `scaffold_from_cls`

Advanced but still available:

- `Model.plan()`
- `Model.sync()`
- `configure_default_runtime(runtime=...)`
