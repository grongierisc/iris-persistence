# iris_orm examples

Each file is a small example. The early ones use the convenience facade; the explicit runtime remains available for advanced control. They assume embedded IRIS is available when they touch live schema or runtime CRUD.

| File | What it shows |
|------|---------------|
| `01_existing_class.py` | Brownfield binding with `bind_existing()` |
| `02_typed_model.py` | Python-owned model with automatic schema alignment on first use |
| `03_relationships.py` | Parent/children relationships with the explicit session |
| `04_schema_sync.py` | Explicit schema diffing and live apply with `SchemaPlanner` + `SchemaApplier` |
| `06_migrations.py` | Snapshot-based migration generation and upgrade |
| `06_serial_objects.py` | Declared serial objects and nested persistence |
| `07_brownfield_scaffold.py` | Typed proxy scaffolding and optional python-owned scaffold generation |
| `08_python_first_sync.py` | Python-owned model with decorator-based schema declarations and explicit schema inspection |

Run from the repository root:

```bash
PYTHONPATH=. python examples/02_typed_model.py
```
