# iris_orm examples

Each file is a small explicit-runtime example. They assume embedded IRIS is available when they touch live schema or runtime CRUD.

| File | What it shows |
|------|---------------|
| `01_existing_class.py` | Explicit brownfield binding with `Registry.bind_existing()` |
| `02_typed_model.py` | Declared model export, schema planning, binding, and CRUD |
| `03_relationships.py` | Parent/children relationships with the explicit session |
| `04_schema_sync.py` | Schema diffing and live apply with `SchemaPlanner` + `SchemaApplier` |
| `06_migrations.py` | Snapshot-based migration generation and upgrade |
| `06_serial_objects.py` | Declared serial objects and nested persistence |
| `07_brownfield_scaffold.py` | Scaffolding from live IRIS or exported `.cls` files |
| `08_python_first_sync.py` | Python-owned schema sync plus adjacent canonical lockfile |

Run from the repository root:

```bash
PYTHONPATH=. python examples/02_typed_model.py
```
