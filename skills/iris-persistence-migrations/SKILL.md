---
name: iris-persistence-migrations
description: Plan, review, apply, verify, and roll back iris-persistence schema migrations for InterSystems IRIS. Use for migration plan files, schema drift checks, safety classification, plan fingerprints, backups, CLI migration commands, blocked physical-storage changes, deployment runbooks, or diagnosing stale plans and non-converged schemas.
---

# Manage reviewed IRIS schema migrations

## Workflow

1. Configure the intended IRIS runtime and confirm the namespace.
2. Create a plan from explicit `module:Model` specs and save it as JSON.
3. Review the revision, fingerprints, and every operation's `safety`, `op_type`, classname, and path.
4. Stop on `blocked` operations. Design a separate maintenance migration for physical storage relocation.
5. Check drift immediately before apply. Keep `fail_on_drift=True` unless the user explicitly accepts the risk.
6. Apply only after explicit authorization, using a durable backup directory.
7. Record the returned backup path and result status.
8. Verify the saved plan converges after apply.
9. Roll back from the exact backup directory only when recovery is requested and its impact is understood.

Prefer the CLI for auditable operator workflows and the Python API for application-controlled workflows. Read [references/migration-workflow.md](references/migration-workflow.md) for exact commands and result behavior.

## Guardrails

- Planning, reviewing, drift checking, and verification are read-only; applying and rollback mutate IRIS.
- Do not apply in the same step as plan creation unless the user explicitly requested it.
- Do not bypass blocked operations or reinterpret them as warnings.
- Do not edit plan fingerprints manually.
- Do not discard the backup path returned by a successful apply.
- A `noop` result is successful and requires no mutation; a `blocked` result is not applied.

## Verification

For repository changes, run:

```bash
pytest tests/test_migrations.py -q
pytest -m "not integration"
```
