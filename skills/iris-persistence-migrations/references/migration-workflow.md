# Migration workflow

Model specs use `module:Class` form.

## CLI

```bash
iris-persistence plan app.models:Person \
  --to 001-person \
  --out migrations/001-person.json

iris-persistence review-plan migrations/001-person.json
iris-persistence drift app.models:Person
iris-persistence apply-plan migrations/001-person.json \
  --backup-dir .iris_persistence/backups
iris-persistence verify-plan migrations/001-person.json
```

Rollback is a separate, destructive recovery action:

```bash
iris-persistence rollback-backup .iris_persistence/backups/<exact-backup>
```

Use `--json` for machine-readable output. Drift and verify return exit status 2 when drift or non-convergence is detected. Apply returns 2 when blocked.

## Python API

```python
from iris_persistence.migrations import apply_plan, create_plan, verify_plan

plan = create_plan([Person], target_revision="001-person")
plan.save("migrations/001-person.json")

for operation in plan.operations:
    print(operation.safety, operation.op_type, operation.classname, operation.path)

# Separate, explicitly authorized step:
result = apply_plan(plan, backup_dir=".iris_persistence/backups")
if result.status == "applied":
    assert result.backup_dir
    assert verify_plan(plan).converged
```

`create_plan()` records live and target schema fingerprints. By default, apply rejects drift between planning and execution. Apply writes a backup before mutation and executes changes in a runtime transaction.

## Safety outcomes

- `safe`: eligible for reviewed application.
- Non-safe review markers: investigate before apply.
- `blocked`: apply returns without changing schema; physical-storage changes need a separate maintenance, copy, validation, and cutover workflow.
- `noop`: target already converges; no backup or mutation is needed.

Keep the saved plan and returned backup path with deployment records.
