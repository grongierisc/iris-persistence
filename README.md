# iris_orm — Explicit IRIS Mapper + Schema Toolkit

`iris_orm` is a Python-first mapper for InterSystems IRIS built around three explicit layers:

- `Registry` collects declared models and existing-class bindings
- `SchemaCompiler` / `SchemaPlanner` / `SchemaApplier` manage schema state through a canonical AST
- `Binder` + `Session` provide runtime CRUD and validated querying

The package no longer binds to live IRIS at import time. Declaring models is offline-safe and deterministic.

## Quick Start

```python
from iris_orm import (
    Binder,
    IRISAdapter,
    IRISModel,
    Registry,
    SchemaApplier,
    SchemaCompiler,
    SchemaPlanner,
    Session,
    field,
)


class Article(IRISModel):
    _iris_classname = "Demo.Article"

    Title: str = field(required=True, maxlen=500)
    Views: int = field(default=0)


registry = Registry()
registry.register(Article)

adapter = IRISAdapter()
desired = registry.export_schema()
live = SchemaCompiler(adapter).catalog_from_iris(registry.classnames())
plan = SchemaPlanner().diff(live, desired)
SchemaApplier(adapter).apply(plan)

binder = Binder(registry, adapter)
binder.bind_all()
session = Session(binder, adapter)

article = Article(Title="Hello", Views=1)
session.add(article)
session.commit()

loaded = session.get(Article, article.pk)
assert loaded is article

for row in session.query(Article).filter_eq(Views=1).order_by("Title"):
    print(row.Title)
```

## Core API

### Model Declaration

Use `IRISModel` and `IRISSerial` only for declaration. They do not attach to IRIS at import time.

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

Lockfiles are canonical schema snapshots:

```python
from iris_orm.lockfile import build_lockfile, write_lockfile

lockfile = build_lockfile(desired, source={"kind": "declared", "origin": "models.py"})
write_lockfile("./article.iris.lock.json", lockfile)
```

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

Scaffold from live IRIS:

```python
from iris_orm.scaffold import scaffold_from_iris

scaffold_from_iris("Demo.*", "./generated_models")
```

Scaffold from exported `.cls` files:

```python
from iris_orm.scaffold import scaffold_from_cls

scaffold_from_cls("./cls", "./generated_models")
```

Both workflows write adjacent `.iris.lock.json` files containing canonical schema snapshots.
