# iris_orm — Python-First IRIS Mapper

`iris_orm` has two ownership modes:

- `_iris_mode = "python"`: Python is the schema reference. The runtime auto-aligns IRIS on first real use when the drift is safe to apply.
- `_iris_mode = "proxy"`: IRIS is the schema reference. Python only binds the class for CRUD and queries.

The package does not attach to live IRIS at import time. Declaring models is offline-safe and deterministic.

## Quick Start

```python
from iris_orm import IRISModel, field, index, parameter, trigger


@parameter("DEFAULTGLOBAL", "^Demo.ArticleD")
@trigger("AuditInsert", event="INSERT", time="AFTER", code="quit")
@index("TitleIdx", properties="Title", unique=True)
class Article(IRISModel):
    _iris_classname = "Demo.Article"
    _iris_mode = "python"

    Title: str = field(required=True, maxlen=500)
    Views: int = field(default=0)


article = Article(Title="Hello", Views=1)
article.save()

loaded = Article.get(article.pk)
assert loaded is article

for row in Article.where(Views=1).order_by("Title"):
    print(row.Title)
```

This path uses the default lazy runtime under the hood. No adapter or session setup is required for simple CRUD.

## Convenience API

ObjectScript-style usage is intentionally small:

- `Model.get(id)`
- `Model.where(...)`
- `Model.query()`
- `instance.save()`
- `instance.delete()`

Batching is still available when needed:

```python
from iris_orm import session_scope

with session_scope():
    Article(Title="One").save()
    Article(Title="Two").save()
```

## Core API

### Model Declaration

Use `IRISModel` and `IRISSerial` only for declaration. They do not attach to IRIS at import time.

Python-owned models should declare:

```python
class Product(IRISModel):
    _iris_classname = "Demo.Product"
    _iris_mode = "python"
```

Proxy bindings are created with:

```python
Article = bind_existing("Demo.Article")
```

### Registry

```python
registry = Registry()
registry.register(Article)
LegacyCustomer = registry.bind_existing("Demo.Customer")
catalog = registry.export_schema()
```

### Schema Toolkit

```python
compiler = SchemaCompiler(adapter)
live = compiler.catalog_from_iris(registry.classnames())
desired = registry.export_schema()
plan = SchemaPlanner().diff(live, desired)
SchemaApplier(adapter).apply(plan, allow_manual=True)
```

`bind_existing("Demo.Customer")` creates a proxy model with `_iris_mode = "proxy"`. It can query and persist data, but `plan()` / `sync()` are disabled because Python is not the schema reference.

### Runtime

```python
binder = Binder(registry, adapter)
binder.bind_all()
session = Session(binder, adapter)

session.add(Article(Title="Hello"))
session.commit()

row = session.query(Article).filter_eq(Title="Hello").first()
```

Supported query operators are intentionally small:

- `filter_eq`
- `filter_in`
- `order_by`
- `limit`
- `offset`
- `count`
- `first`
- `all`

Every queried field is validated against the bound schema before SQL is emitted.

## Migrations

`iris_orm.migrations` stores canonical `schema_before` / `schema_after` snapshots in each migration file.

```python
from iris_orm import Registry
from iris_orm.migrations import MigrationRunner

runner = MigrationRunner("./migrations", registry=registry, adapter=adapter)
runner.init()
runner.generate("create article")
runner.upgrade()
```

Generated migrations rebuild upgrade/downgrade plans from the stored snapshots rather than replaying ad hoc state.

## Scaffolding

Scaffold typed proxy classes from live IRIS:

```python
from iris_orm.scaffold import scaffold_from_iris

scaffold_from_iris("Demo.*", "./generated_models")
```

Generate Python-owned starting points instead:

```python
from iris_orm.scaffold import scaffold_from_iris

scaffold_from_iris("Demo.*", "./generated_models", style="python")
```

Scaffold from exported `.cls` files:

```python
from iris_orm.scaffold import scaffold_from_cls

scaffold_from_cls("./cls", "./generated_models")
```

Proxy scaffolds stay typed for editor support, but they bind live IRIS metadata at runtime. Python scaffolds render supported schema metadata with decorators plus `_iris_storage` when needed.

Python-first advanced features can be declared directly as decorators:

```python
from iris_orm import index, parameter, trigger

@parameter("DEFAULTGLOBAL", "^Demo.ProductD")
@trigger("AuditInsert", event="INSERT", time="AFTER", code="quit")
@index("NameIdx", properties="Name", unique=True)
class Product(IRISModel):
    _iris_classname = "Demo.Product"
    _iris_mode = "python"
```

The list-style `_iris_indexes`, `_iris_triggers`, and `_iris_class_parameters` forms still work, but the decorator form is the intended Python-first syntax.

## Ownership Modes

Use `_iris_mode` to make schema ownership explicit on the class:

```python
class Product(IRISModel):
    _iris_classname = "Demo.Product"
    _iris_mode = "python"
```

```python
class LegacyArticle(IRISModel):
    _iris_classname = "Demo.Article"
    _iris_mode = "proxy"
```

- `"python"`: Python declarations are authoritative. Runtime use auto-aligns safe schema drift. `plan()` and `sync(force=True)` remain available for advanced control.
- `"proxy"`: the class binds to live IRIS for CRUD/query only. Schema management is disabled.
