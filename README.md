# 1. iris_orm — Python ORM for InterSystems IRIS

`iris_orm` is a Python-first ORM for IRIS that uses `%Dictionary` exclusively
— no `.cls` file generation or injection required.

## 1.1. Quick start

```python
from iris_orm import IRISModel, field

class Article(IRISModel):
    _iris_classname = "Demo.Article"
    Title: str = field(required=True, maxlen=500)
    Views: int = field(default=0)

# Create class in IRIS via %Dictionary (no .cls files)
Article.schema.ensure_iris_class()

# CRUD
a = Article(Title="Hello", Views=0)
a.save()
print(a.pk)

loaded = Article.get(a.pk)
loaded.Views += 1
loaded.save()

for art in Article.objects.filter(Views=1):
    print(art.Title)
```

## 1.2. Two workflows

| Mode | When to use | How |
|---|---|---|
| **Existing-class binding** | IRIS class already exists | `_iris_classname = "Demo.X"` — descriptors auto-injected |
| **Declared model** | Greenfield, Python is source of truth | Add typed annotations + `field()` metadata |

## 1.3. Schema sync

```python
Article.schema.push()          # Python additions/changes → IRIS via %Dictionary
Article.schema.pull()          # IRIS additions → Python
Article.schema.status()        # 3-way diff
Article.schema.delete_property("OldField")  # explicit destructive op
```

## 1.4. Migrations

`iris_orm.migrations` provides Alembic-style versioned migrations stored as
plain Python files that live in git.

### 1.4.1. Setup (once per project)

```python
from iris_orm.migrations import MigrationRunner

runner = MigrationRunner("./migrations")
runner.init()   # creates iris_orm.MigrationHistory in IRIS
```

Or via CLI:

```bash
python -m iris_orm.migrations --dir ./migrations init
```

### 1.4.2. Autogenerate a migration

```python
runner.generate("create article table", models=[Article])
# → ./migrations/0001_create_article_table.py
```

Generated file:

```python
revision = "0001"
down_revision = None
description = "create article table"

def upgrade(conn):
    conn.create_class("Demo.Article", extends="%Persistent")
    conn.add_property("Demo.Article", "Title", "%String", required=True, maxlen=500)
    conn.add_property("Demo.Article", "Views", "%Integer")

def downgrade(conn):
    conn.drop_class("Demo.Article")
```

### 1.4.3. Apply / roll back

```python
runner.upgrade()            # apply all pending
runner.upgrade("0003")      # apply up to 0003
runner.downgrade("0001")    # roll back to 0001
runner.history()            # show applied / pending table
runner.current()            # show current revision
```

CLI equivalents:

```bash
python -m iris_orm.migrations upgrade
python -m iris_orm.migrations downgrade 0001
python -m iris_orm.migrations history
python -m iris_orm.migrations current
```

### 1.4.4. Available operations in migration files

| Operation | Direction | Auto-generated? |
|---|---|---|
| `conn.create_class(classname, extends)` | upgrade | ✅ yes |
| `conn.add_property(classname, name, type, ...)` | upgrade | ✅ yes |
| `conn.alter_property(classname, name, new_type)` | upgrade | ✅ yes |
| `conn.add_relationship(classname, name, ...)` | upgrade | ✅ yes |
| `conn.drop_class(classname)` | downgrade | ❌ manual only |
| `conn.drop_property(classname, name)` | downgrade | ❌ manual only |
| `conn.drop_relationship(classname, name)` | downgrade | ❌ manual only |
| `conn.compile(classname)` | either | n/a |

> **Destructive operations are never auto-generated** to prevent accidental
> data loss.  Add them manually when intentional.

## 1.5. Module layout

```
iris_orm/
  connection.py        IRISConnection (embedded IRIS runtime helper)
  metaclass.py         IRISMeta, IRISModel, IRISSerial
  descriptors.py       IRISDescriptor, IRISRelationshipDescriptor, …
  fields.py            field(), relationship() helpers
  introspection.py     get_class_properties() via %Dictionary
  query.py             IRISQuerySet (filter/count/iterate)
  schema.py            SchemaManager (push/pull/status/ensure_iris_class/delete_property)
  types.py             IRIS ↔ Python type mapping
  stubs.py             .pyi stub generation for IDE autocomplete
  migrations/
    __init__.py        MigrationRunner
    migration.py       Operation dataclasses + MigrationConnection
    autogenerate.py    Diff models → Operations
    writer.py          Render Operations → .py migration file
    tracker.py         MigrationHistory %Persistent class in IRIS
    cli.py             python -m iris_orm.migrations
```
