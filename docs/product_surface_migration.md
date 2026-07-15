# Product-surface migration

Version `0.3.0` defines the package root as the persistence and managed-schema API. Migrations,
reverse scaffolding, and expert storage remain in the same distribution under explicit modules.

## Import changes

Legacy imports continue to work in `0.3.0`, emit `DeprecationWarning`, and are removed in `0.4.0`.

| Deprecated root import | Canonical import |
| --- | --- |
| `ApplyResult` | `iris_persistence.migrations.ApplyResult` |
| `BackupRestoreError` | `iris_persistence.migrations.BackupRestoreError` |
| `MigrationOperation` | `iris_persistence.migrations.MigrationOperation` |
| `MigrationPlan` | `iris_persistence.migrations.MigrationPlan` |
| `RollbackResult` | `iris_persistence.migrations.RollbackResult` |
| `VerifyResult` | `iris_persistence.migrations.VerifyResult` |
| `apply_plan` | `iris_persistence.migrations.apply_plan` |
| `check_drift` | `iris_persistence.migrations.check_drift` |
| `create_plan` | `iris_persistence.migrations.create_plan` |
| `rollback_backup` | `iris_persistence.migrations.rollback_backup` |
| `verify_plan` | `iris_persistence.migrations.verify_plan` |
| `ScaffoldResult` | `iris_persistence.scaffold.ScaffoldResult` |
| `ScaffoldWarning` | `iris_persistence.scaffold.ScaffoldWarning` |
| `scaffold_from_iris` | `iris_persistence.scaffold.scaffold_from_iris` |
| `materialize()` | `Model.to_iris()` |
| `from_iris()` | `Model.from_iris()` |

For example:

```python
# Before
from iris_persistence import create_plan, scaffold_from_iris

# 0.3.0 and later
from iris_persistence.migrations import create_plan
from iris_persistence.scaffold import scaffold_from_iris
```

Deprecated secondary names are no longer included in `iris_persistence.__all__`, so wildcard
imports immediately reflect the smaller core surface.

## Unchanged behavior

- Model constructors, CRUD, queries, schema synchronization, and stored data are unchanged.
- Migration and scaffold signatures, return types, and module-level imports are unchanged.
- The migration CLI and its commands are unchanged.
- The project remains one installable distribution.

## Known compatibility risks

- Code treating deprecation warnings as errors must migrate imports before upgrading.
- Dynamic discovery based on root `__all__` no longer finds operational APIs.
- Runtime subclasses must call `IRISRuntime.__init__()`; the old fallback that synthesized missing
  backend/value state was removed. Applications should prefer structural `Runtime`
  implementations instead of subclassing `IRISRuntime`.
- Wrapper objects exposing only `Id()` or `%Id()` are no longer probed. Supported wrapper objects
  expose the normalized `_Id()` method.
