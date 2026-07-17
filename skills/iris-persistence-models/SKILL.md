---
name: iris-persistence-models
description: Build, modify, and troubleshoot typed Python persistence models backed by InterSystems IRIS using iris-persistence. Use for Model subclasses, Field and Index definitions, runtime configuration, managed versus observe schema modes, CRUD, QuerySet filters and ordering, serial or persistent relationships, collection fields, dataclass conversion, and tests using the in-memory adapter.
---

# Build IRIS persistence models

## Workflow

1. Inspect the project's installed `iris-persistence` version and nearby models before editing.
2. Choose ownership explicitly: use `mode = "managed"` for Python-owned members and `mode = "observe"` for existing IRIS classes Python must not mutate.
3. Declare a stable IRIS classname in `Meta.classname`.
4. Use Python annotations for types and `Field(...)` only when metadata or a default factory is needed.
5. Preview managed changes with `Model.diff_schema()` or `Model.sync_schema(dry_run=True)`.
6. Apply schema only when the task authorizes mutation; otherwise report the diff.
7. Implement CRUD through `save`, `get`, `where`, `order_by`, `all`, and `delete`.
8. Add focused unit tests. Use `iris_persistence.testing.InMemoryAdapter` when live IRIS is unnecessary.

Read [references/model-api.md](references/model-api.md) for declarations, runtime setup, relationships, and examples.

## Guardrails

- Do not enable `Meta.auto_sync` by default. Keep schema changes explicit.
- Do not call `sync_schema()` for `observe` models.
- Do not use deprecated root `materialize()` or `from_iris()` wrappers; use `Model.to_iris()` and `Model.from_iris()`.
- Treat `StorageTuning` as creation-time placement. Do not use ordinary sync to relocate populated storage.
- Import migrations from `iris_persistence.migrations`, scaffolding from `iris_persistence.scaffold`, and expert storage APIs from `iris_persistence.advanced_storage`.
- Keep query keys to declared model fields. QuerySet supports equality filters and ordering, not arbitrary SQL expressions.

## Verification

Run the narrowest relevant test first, then the non-integration suite when practical:

```bash
pytest path/to/test_models.py -q
pytest -m "not integration"
```

Run live-IRIS integration tests only when credentials and a disposable target are available.
